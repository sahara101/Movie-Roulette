import requests
import os
import json
import time
from threading import Thread, Lock
from datetime import datetime, timedelta
from utils.settings import settings

from utils.path_manager import path_manager
# Get settings
TRAKT_SETTINGS = settings.get('trakt', {})
TMDB_SETTINGS = settings.get('tmdb', {})

# Get values from ENV or settings
HARDCODED_CLIENT_ID = '2203f1d6e97f5f8fcbfc3dcd5a6942ad03559831695939a01f9c44a1c685c4d1'
HARDCODED_CLIENT_SECRET = '3e5c2b9163264d8e9b50b8727c827b49a5ea8cc6cf0331bca931a697c243f508'

TRAKT_CLIENT_ID = os.getenv('TRAKT_CLIENT_ID') or HARDCODED_CLIENT_ID
TRAKT_CLIENT_SECRET = os.getenv('TRAKT_CLIENT_SECRET') or HARDCODED_CLIENT_SECRET
TRAKT_ACCESS_TOKEN = os.getenv('TRAKT_ACCESS_TOKEN') or TRAKT_SETTINGS.get('access_token')
TRAKT_REFRESH_TOKEN = os.getenv('TRAKT_REFRESH_TOKEN') or TRAKT_SETTINGS.get('refresh_token')
TMDB_API_KEY = os.getenv('TMDB_API_KEY') or TMDB_SETTINGS.get('api_key')

# Check if service is enabled
TRAKT_ENABLED = (
    bool(TRAKT_SETTINGS.get('enabled')) or
    bool(all([
        os.getenv('TRAKT_CLIENT_ID'),
        os.getenv('TRAKT_CLIENT_SECRET'),
        os.getenv('TRAKT_ACCESS_TOKEN'),
        os.getenv('TRAKT_REFRESH_TOKEN')
    ]))
)

TRAKT_TOKEN_FILE = path_manager.get_path('trakt_tokens')
TRAKT_WATCHED_FILE = path_manager.get_path('trakt_watched')
UPDATE_INTERVAL = 600  # 600 seconds = 10 minutes
TRAKT_API_URL = 'https://api.trakt.tv'
TMDB_API_KEY = os.getenv('TMDB_API_KEY')

# Add a lock for thread-safe token operations
token_lock = Lock()

class TokenManager:
    def __init__(self):
        self.access_token = TRAKT_ACCESS_TOKEN
        self.refresh_token = TRAKT_REFRESH_TOKEN
        self.token_expires_at = None
        self.load_tokens()

    def load_tokens(self):
        """Load tokens from file if they exist"""
        if os.path.exists(TRAKT_TOKEN_FILE):
            try:
                with open(TRAKT_TOKEN_FILE, 'r') as f:
                    data = json.load(f)
                    self.access_token = data.get('access_token')
                    self.refresh_token = data.get('refresh_token')
                    self.token_expires_at = data.get('expires_at')
                    
                # Validate tokens were loaded
                if not self.access_token or not self.refresh_token:
                    print("Warning: One or more tokens missing from file")
                    return False
                return True
            except Exception as e:
                print(f"Error loading tokens: {e}")
                return False
        return False

    def save_tokens(self, access_token=None, refresh_token=None):
        """Save tokens to file and update instance"""
        try:
            # Update instance if new tokens provided
            if access_token:
                self.access_token = access_token
            if refresh_token:
                self.refresh_token = refresh_token
                
            # Save to file
            with open(TRAKT_TOKEN_FILE, 'w') as f:
                json.dump({
                    'access_token': self.access_token,
                    'refresh_token': self.refresh_token,
                    'expires_at': self.token_expires_at
                }, f)
            return True
        except Exception as e:
            print(f"Error saving tokens: {e}")
            return False

    def get_valid_access_token(self):
        """Get a valid access token, refreshing if necessary"""
        with token_lock:
            if not self.access_token or not self.refresh_token:
                self.load_tokens()  # Try reloading tokens
                if not self.access_token or not self.refresh_token:
                    print("No valid tokens available")
                    return None
                    
            if self.token_expires_at:
                expires_at = datetime.fromisoformat(self.token_expires_at)
                # Refresh if token expires in less than 7 days
                if expires_at - timedelta(days=7) <= datetime.now():
                    self.refresh_tokens()
            return self.access_token

    def refresh_tokens(self):
        """Refresh the access token using the refresh token"""
        if not self.refresh_token:
            print("No refresh token available")
            return False
            
        try:
            response = requests.post(
                f'{TRAKT_API_URL}/oauth/token',
                json={
                    'refresh_token': self.refresh_token,
                    'client_id': TRAKT_CLIENT_ID,
                    'client_secret': TRAKT_CLIENT_SECRET,
                    'grant_type': 'refresh_token'
                }
            )

            if response.ok:
                data = response.json()
                self.access_token = data['access_token']
                self.refresh_token = data['refresh_token']
                # Calculate and store expiration time
                self.token_expires_at = (datetime.now() +
                    timedelta(seconds=data.get('expires_in', 7776000))).isoformat()
                self.save_tokens()
                return True
            else:
                print(f"Token refresh failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            print(f"Error refreshing tokens: {e}")
            return False

# Create a global token manager instance
token_manager = TokenManager()

def get_trakt_headers():
    """Get headers with a valid access token"""
    return {
        'Content-Type': 'application/json',
        'trakt-api-version': '2',
        'trakt-api-key': TRAKT_CLIENT_ID,
        'Authorization': f'Bearer {token_manager.get_valid_access_token()}'
    }

# Update the request handling to use token refresh on 401 responses
def make_trakt_request(method, endpoint, **kwargs):
    """Make a Trakt API request with automatic token refresh on 401"""
    url = f'{TRAKT_API_URL}/{endpoint}'
    kwargs['headers'] = get_trakt_headers()

    response = requests.request(method, url, **kwargs)

    if response.status_code == 401:
        # Token might be expired, try refreshing
        if token_manager.refresh_tokens():
            # Retry the request with new token
            kwargs['headers'] = get_trakt_headers()
            response = requests.request(method, url, **kwargs)

    return response

def initialize_trakt():
    """Initialize Trakt service and verify credentials"""
    global TRAKT_ENABLED

    try:
        # Check ENV variables first
        env_credentials = all([
            os.getenv('TRAKT_CLIENT_ID'),
            os.getenv('TRAKT_CLIENT_SECRET'),
            os.getenv('TRAKT_ACCESS_TOKEN'),
            os.getenv('TRAKT_REFRESH_TOKEN')
        ])

        # Check token file exists and Trakt is enabled in settings
        file_credentials = os.path.exists(TRAKT_TOKEN_FILE)
        
        # Update TRAKT_ENABLED based on available credentials
        TRAKT_ENABLED = env_credentials or (TRAKT_SETTINGS.get('enabled') and file_credentials)

        if TRAKT_ENABLED:
            # Verify credentials by making a test API call
            test_response = make_trakt_request('GET', 'sync/watched/movies')
            if not test_response.ok:
                print(f"Trakt credentials verification failed: {test_response.status_code}")
                TRAKT_ENABLED = False
                return False

            print("Trakt service initialized successfully")
            return True
        else:
            print("Trakt service not properly configured")
            return False

    except Exception as e:
        print(f"Error initializing Trakt service: {e}")
        TRAKT_ENABLED = False
        return False

def get_watched_movies():
    response = make_trakt_request('GET', 'sync/watched/movies')
    if not response.ok:
        print(f"Trakt API error {response.status_code}: {response.text}")
        return []
    
    watched_movies = response.json()
    tmdb_ids = []
    for movie in watched_movies:
        tmdb_id = movie['movie']['ids'].get('tmdb')
        if tmdb_id:
            tmdb_ids.append(tmdb_id)
    return tmdb_ids


def get_trakt_rating(tmdb_id):
    # First, get the Trakt ID from TMDb ID
    search_response = make_trakt_request('GET', f'search/tmdb/{tmdb_id}?type=movie')
    if not search_response.ok:
        print(f"Error searching for Trakt ID: {search_response.status_code}")
        return 0

    search_data = search_response.json()
    if not search_data:
        print(f"No Trakt data found for TMDb ID: {tmdb_id}")
        return 0

    trakt_id = search_data[0]['movie']['ids']['trakt']

    # Now get the rating using the Trakt ID
    rating_response = make_trakt_request('GET', f'movies/{trakt_id}/ratings')
    if not rating_response.ok:
        print(f"Error fetching Trakt rating: {rating_response.status_code}")
        return 0

    rating_data = rating_response.json()
    rating = rating_data.get('rating', 0)
    return int(rating * 10)  # Convert to percentage

# Keep the existing functions but update them to use make_trakt_request where needed
def sync_watched_status():
    watched_movies = get_watched_movies()
    with open(TRAKT_WATCHED_FILE, 'w') as f:
        json.dump(watched_movies, f)

def get_local_watched_movies():
    if os.path.exists(TRAKT_WATCHED_FILE):
        with open(TRAKT_WATCHED_FILE, 'r') as f:
            return json.load(f)
    return []

def is_movie_watched(tmdb_id):
    watched_movies = get_local_watched_movies()
    return tmdb_id in watched_movies

def get_movie_ratings(tmdb_id):
    trakt_rating = get_trakt_rating(tmdb_id)
    return {
        "trakt_rating": trakt_rating,
        "imdb_rating": None
    }

def get_trakt_id_from_tmdb(tmdb_id):
    response = make_trakt_request('GET', f'search/tmdb/{tmdb_id}?type=movie')
    if response.ok:
        results = response.json()
        if results:
            return results[0]['movie']['ids']['trakt']
    return None

def update_watched_status_loop():
    while True:
        sync_watched_status()
        time.sleep(UPDATE_INTERVAL)

# Start the update loop in a background thread
update_thread = Thread(target=update_watched_status_loop, daemon=True)
update_thread.start()
