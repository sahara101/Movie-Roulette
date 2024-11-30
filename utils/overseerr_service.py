import os
import requests
import logging
from dotenv import load_dotenv
from utils.settings import settings
from utils.tmdb_service import tmdb_service

load_dotenv()  # Load environment variables from .env
logger = logging.getLogger(__name__)

# Global state
OVERSEERR_INITIALIZED = False
OVERSEERR_URL = None
OVERSEERR_API_KEY = None

def initialize_overseerr():
    """Initialize or reinitialize Overseerr service"""
    global OVERSEERR_INITIALIZED, OVERSEERR_URL, OVERSEERR_API_KEY

    # Get settings
    overseerr_settings = settings.get('overseerr', {})

    # Get values from ENV or settings
    OVERSEERR_URL = os.getenv('OVERSEERR_URL') or overseerr_settings.get('url', '').strip()
    OVERSEERR_API_KEY = os.getenv('OVERSEERR_API_KEY') or overseerr_settings.get('api_key', '').strip()

    # Check if service should be enabled
    if ((os.getenv('OVERSEERR_URL') and os.getenv('OVERSEERR_API_KEY')) or
        (overseerr_settings.get('enabled') and OVERSEERR_URL and OVERSEERR_API_KEY)):
        OVERSEERR_INITIALIZED = True
        logger.info("Overseerr service initialized successfully")
        return True

    OVERSEERR_INITIALIZED = False
    logger.info("Overseerr service not initialized - missing configuration or disabled")
    return False

# Initialize right away
initialize_overseerr()

OVERSEERR_HEADERS = {}

def update_headers():
    """Update headers with current API key"""
    global OVERSEERR_HEADERS
    if OVERSEERR_API_KEY:
        OVERSEERR_HEADERS = {
            'X-Api-Key': OVERSEERR_API_KEY,
            'Content-Type': 'application/json'
        }

def get_overseerr_csrf_token():
    """Gets CSRF token from Overseerr."""
    if not OVERSEERR_INITIALIZED:
        logger.warning("Cannot get CSRF token: Overseerr not initialized")
        return None

    try:
        update_headers()
        response = requests.get(f"{OVERSEERR_URL}/auth/me", headers=OVERSEERR_HEADERS)
        response.raise_for_status()

        csrf_token = response.cookies.get('XSRF-TOKEN')
        if csrf_token:
            return csrf_token
        else:
            logger.info("CSRF token not found in response cookies. CSRF might be disabled.")
            return None
    except requests.RequestException as e:
        logger.error(f"Error getting CSRF token: {e}")
        return None

def request_movie(movie_id, csrf_token=None):
    """Sends a request to Overseerr to add a movie to the request list."""
    if not OVERSEERR_INITIALIZED:
        logger.warning("Cannot request movie: Overseerr not initialized")
        return None

    update_headers()
    endpoint = f"{OVERSEERR_URL}/api/v1/request"
    headers = OVERSEERR_HEADERS.copy()
    if csrf_token:
        headers['X-CSRF-Token'] = csrf_token

    data = {
        "mediaId": int(movie_id),
        "mediaType": "movie"
    }

    try:
        response = requests.post(endpoint, headers=headers, json=data)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        if csrf_token and 'CSRF' in str(e):
            logger.warning("CSRF token failed, retrying without CSRF")
            return request_movie(movie_id)  # Retry without CSRF token
        logger.error(f"Error requesting movie via Overseerr: {e}")
        if hasattr(e.response, 'text'):
            logger.error(f"Response content: {e.response.text}")
        return None

def fetch_all_movies():
    """Fetches all movies from Overseerr."""
    if not OVERSEERR_INITIALIZED:
        logger.warning("Cannot fetch movies: Overseerr not initialized")
        return []

    update_headers()
    endpoint = f"{OVERSEERR_URL}/api/v1/movie"
    params = {
        'take': 100,
        'skip': 0
    }
    all_movies = []

    try:
        while True:
            response = requests.get(endpoint, headers=OVERSEERR_HEADERS, params=params)
            response.raise_for_status()
            data = response.json()
            movies = data.get('results', [])
            if not movies:
                break
            all_movies.extend(movies)
            if len(movies) < params['take']:
                break
            params['skip'] += params['take']
    except requests.RequestException as e:
        logger.error(f"Error fetching all movies from Overseerr: {e}")
        return []

    return all_movies

def get_tmdb_api_key():
    """Get the TMDB API key from ENV or settings"""
    global TMDB_API_KEY
    # Get tmdb key from overseerr section
    overseerr_settings = settings.get('overseerr', {})
    TMDB_API_KEY = os.getenv('TMDB_API_KEY') or overseerr_settings.get('tmdb_api_key', '')
    return TMDB_API_KEY

def update_configuration(url, api_key):
    """Update service configuration"""
    global OVERSEERR_URL, OVERSEERR_API_KEY, OVERSEERR_INITIALIZED
    OVERSEERR_URL = url
    OVERSEERR_API_KEY = api_key
    update_headers()
    OVERSEERR_INITIALIZED = bool(url and api_key)
    return initialize_overseerr()

def get_media_status(tmdb_id):
    """Get media status from Overseerr for a specific TMDb ID."""
    if not OVERSEERR_INITIALIZED:
        logger.warning("Cannot check media: Overseerr not initialized")
        return None

    update_headers()
    endpoint = f"{OVERSEERR_URL}/api/v1/movie/{tmdb_id}"

    try:
        response = requests.get(endpoint, headers=OVERSEERR_HEADERS)
        response.raise_for_status()
        data = response.json()
        return data
    except requests.RequestException as e:
        logger.error(f"Error checking media status: {e}")
        return None
