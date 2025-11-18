import requests
import os
import json
import time
import os.path
from threading import Thread, Lock
from datetime import datetime, timedelta
import logging
from utils.settings import settings
from flask import request, session, current_app 
from utils.auth.manager import auth_manager 

logger = logging.getLogger(__name__)

TRAKT_SETTINGS = settings.get('trakt', {})
TMDB_SETTINGS = settings.get('tmdb', {})

HARDCODED_CLIENT_ID = '2203f1d6e97f5f8fcbfc3dcd5a6942ad03559831695939a01f9c44a1c685c4d1'
HARDCODED_CLIENT_SECRET = '3e5c2b9163264d8e9b50b8727c827b49a5ea8cc6cf0331bca931a697c243f508'

TRAKT_CLIENT_ID = os.getenv('TRAKT_CLIENT_ID') or HARDCODED_CLIENT_ID
TRAKT_CLIENT_SECRET = os.getenv('TRAKT_CLIENT_SECRET') or HARDCODED_CLIENT_SECRET
TRAKT_ACCESS_TOKEN = os.getenv('TRAKT_ACCESS_TOKEN') or TRAKT_SETTINGS.get('access_token')
TRAKT_REFRESH_TOKEN = os.getenv('TRAKT_REFRESH_TOKEN') or TRAKT_SETTINGS.get('refresh_token')
TMDB_API_KEY = os.getenv('TMDB_API_KEY') or TMDB_SETTINGS.get('api_key')

TRAKT_ENABLED = (
    bool(TRAKT_SETTINGS.get('enabled')) or
    bool(all([
        os.getenv('TRAKT_CLIENT_ID'),
        os.getenv('TRAKT_CLIENT_SECRET'),
        os.getenv('TRAKT_ACCESS_TOKEN'),
        os.getenv('TRAKT_REFRESH_TOKEN')
    ]))
)

DATA_DIR = '/app/data'
USER_DATA_DIR = os.path.join(DATA_DIR, 'user_data')
DEFAULT_WATCHED_FILE = os.path.join(DATA_DIR, 'trakt_watched_movies.json')
UPDATE_INTERVAL = 600  
TRAKT_API_URL = 'https://api.trakt.tv'

token_lock = Lock()

def get_current_user_id():
    """Get current user ID or 'global' if auth is disabled"""
    from utils.auth.manager import auth_manager
    
    if not auth_manager.auth_enabled:
        return 'global'
    
    token = request.cookies.get('auth_token') if hasattr(request, 'cookies') else None
    if token:
        user_data = auth_manager.verify_auth(token)
        if user_data:
            return user_data['username']
    
    if hasattr(session, 'get'):
        username = session.get('username')
        if username:
            return username
            
    return 'global'  

def is_trakt_env_controlled():
    """Check if any core Trakt setting is controlled by ENV vars."""
    return settings.is_field_env_controlled('trakt.enabled') or \
           settings.is_field_env_controlled('trakt.client_id') or \
           settings.is_field_env_controlled('trakt.client_secret') or \
           settings.is_field_env_controlled('trakt.access_token') or \
           settings.is_field_env_controlled('trakt.refresh_token')

def is_trakt_globally_enabled():
    """Check if Trakt is enabled globally (either via ENV or settings.json)."""
    if is_trakt_env_controlled():
        
        return bool(os.getenv('TRAKT_ACCESS_TOKEN'))
    else:
        
        return settings.get('trakt', {}).get('enabled', False)

def is_trakt_enabled_for_user(user_id=None):
    """Check if Trakt is enabled for a specific user."""

    if user_id is None:
        user_id = get_current_user_id()

    if is_trakt_env_controlled():
        
        return bool(os.getenv('TRAKT_ACCESS_TOKEN')) 

    if user_id == 'global':
        return settings.get('trakt', {}).get('enabled', False)

    user_data = auth_manager.db.get_managed_user_by_username(user_id)
    if not user_data:
        user_data = auth_manager.db.get_user(user_id)

    if not user_data:
         return False

    return user_data.get('trakt_enabled', False) and bool(user_data.get('trakt_access_token'))

def get_user_trakt_tokens(user_id=None):
    """Get Trakt tokens for a specific user from AuthDB or ENV."""

    if user_id is None:
        user_id = get_current_user_id()

    if is_trakt_env_controlled():
        access = os.getenv('TRAKT_ACCESS_TOKEN')
        refresh = os.getenv('TRAKT_REFRESH_TOKEN')
        if access:
            return {'access_token': access, 'refresh_token': refresh, 'env_controlled': True}
        else:
            return None 

    if user_id == 'global':
         global_settings = settings.get('trakt', {})
         access = global_settings.get('access_token')
         refresh = global_settings.get('refresh_token')
         if access:
             return {'access_token': access, 'refresh_token': refresh, 'env_controlled': False}
         else:
             return None

    user_data = auth_manager.db.get_managed_user_by_username(user_id)
    if not user_data:
        user_data = auth_manager.db.get_user(user_id)

    if not user_data:
         return None

    access = user_data.get('trakt_access_token')
    refresh = user_data.get('trakt_refresh_token')

    if access:
        return {'access_token': access, 'refresh_token': refresh, 'env_controlled': False}
    else:
        return None 

def refresh_user_trakt_token(user_id=None):
    """Refresh Trakt token for a specific user using AuthDB."""
    if user_id is None:
        user_id = get_current_user_id()

    if is_trakt_env_controlled():
        print(f"Skipping Trakt token refresh for user {user_id}: ENV controlled.")
        return True 

    tokens = get_user_trakt_tokens(user_id)
    if not tokens or not tokens.get('refresh_token'):
        print(f"No refresh token found for user {user_id}. Cannot refresh.")
        return False

    refresh_token = tokens['refresh_token']

    print(f"Attempting to refresh Trakt token for user {user_id}...")
    try:
        response = requests.post(
            f'{TRAKT_API_URL}/oauth/token',
            json={
                'refresh_token': refresh_token,
                'client_id': TRAKT_CLIENT_ID, 
                'client_secret': TRAKT_CLIENT_SECRET, 
                'redirect_uri': 'urn:ietf:wg:oauth:2.0:oob', 
                'grant_type': 'refresh_token'
            }
        )

        if response.ok:
            data = response.json()
            new_access_token = data['access_token']
            new_refresh_token = data['refresh_token']

            update_data = {
                'trakt_access_token': new_access_token,
                'trakt_refresh_token': new_refresh_token
            }

            user_type = None
            if auth_manager.db.get_managed_user_by_username(user_id):
                user_type = 'plex_managed'
            elif auth_manager.db.get_user(user_id):
                user_type = 'local'

            success = False
            message = "User type not handled for token refresh save"

            if user_type == 'plex_managed':
                success, message = auth_manager.db.update_managed_user_data(user_id, update_data)
            elif user_type == 'local':
                success, message = auth_manager.db.update_user_data(user_id, update_data)
            else:
                print(f"Could not determine user type for {user_id} to save refreshed token.")

            if success:
                print(f"Successfully refreshed and saved Trakt token for user {user_id} (type: {user_type})")
                return True
            else:
                print(f"Failed to save refreshed Trakt token for user {user_id} (type: {user_type}): {message}")
                return False
        else:
            user_type = 'unknown'
            if auth_manager.db.get_managed_user_by_username(user_id):
                user_type = 'plex_managed'
            elif auth_manager.db.get_user(user_id):
                user_type = 'local'
            print(f"Trakt token refresh API call failed for user {user_id} (type: {user_type}): {response.status_code} - {response.text}")
            if response.status_code == 401:
                 print(f"Refresh token for user {user_id} (type: {user_type}) seems invalid. Clearing tokens and disabling.")
                 clear_data = {'trakt_access_token': None, 'trakt_refresh_token': None, 'trakt_enabled': False}
                 if user_type == 'plex_managed':
                     auth_manager.db.update_managed_user_data(user_id, clear_data)
                 elif user_type == 'local':
                     auth_manager.db.update_user_data(user_id, clear_data)
            return False
    except Exception as e:
        user_type = 'unknown'
        if auth_manager.db.get_managed_user_by_username(user_id):
            user_type = 'plex_managed'
        elif auth_manager.db.get_user(user_id):
            user_type = 'local'
        print(f"Exception during Trakt token refresh for user {user_id} (type: {user_type}): {e}")
        return False

def get_trakt_headers(user_id=None):
    """Get headers with a valid access token for specific user using AuthDB."""
    if user_id is None:
        user_id = get_current_user_id()

    tokens = get_user_trakt_tokens(user_id)
    if not tokens or not tokens.get('access_token'):
        return None

    access_token = tokens['access_token']
        
    return {
        'Content-Type': 'application/json',
        'trakt-api-version': '2',
        'trakt-api-key': TRAKT_CLIENT_ID,
        'Authorization': f'Bearer {access_token}'
    }

def make_trakt_request(method, endpoint, user_id=None, **kwargs):
    """Make a Trakt API request with automatic token refresh for specific user"""
    if user_id is None:
        user_id = get_current_user_id()
        
    url = f'{TRAKT_API_URL}/{endpoint}'
    headers = get_trakt_headers(user_id) 

    if not headers:
        print(f"make_trakt_request: Initial token invalid for user {user_id}. Attempting refresh...")
        if refresh_user_trakt_token(user_id):
            headers = get_trakt_headers(user_id) 
            if not headers:
                 print(f"make_trakt_request: Still no valid token after refresh for user {user_id}")
                 return None 
        else:
            print(f"make_trakt_request: Token refresh failed for user {user_id}")
            return None 

    if not headers:
        print(f"make_trakt_request: Failed to obtain valid headers for user {user_id}")
        return None
        
    if 'headers' in kwargs:
        headers.update(kwargs.pop('headers'))
    kwargs['headers'] = headers

    response = requests.request(method, url, **kwargs)

    if response.status_code == 401:
        print(f"make_trakt_request: Received 401 for user {user_id}. Attempting refresh...")
        if refresh_user_trakt_token(user_id):
            headers = get_trakt_headers(user_id) 
            if not headers:
                 print(f"make_trakt_request: Failed to get headers after successful refresh for user {user_id}")
                 return response 

            kwargs['headers'] = headers 
            print(f"make_trakt_request: Retrying request for user {user_id} after refresh.")
            response = requests.request(method, url, **kwargs)
        else:
            print(f"make_trakt_request: Token refresh failed for user {user_id} after 401.")

    return response

def initialize_trakt():
    """Initialize Trakt service status based on ENV or global settings."""
    global TRAKT_ENABLED 

    try:
        if is_trakt_env_controlled():
            if os.getenv('TRAKT_ACCESS_TOKEN'):
                 print("Trakt service initialized successfully (ENV controlled)")
                 TRAKT_ENABLED = True
                 return True
            else:
                 print("Trakt service disabled (ENV controlled, but no token)")
                 TRAKT_ENABLED = False
                 return False

        global_setting_enabled = settings.get('trakt', {}).get('enabled', False)
        if global_setting_enabled:
             print("Trakt service potentially enabled via global setting (applies if auth disabled or as default)")
             TRAKT_ENABLED = True
             return True

        print("Trakt service disabled (No ENV override or global setting)")
        TRAKT_ENABLED = False
        return False

    except Exception as e:
        print(f"Error during Trakt initialization check: {e}")
        TRAKT_ENABLED = False
        return False

    except Exception as e:
        print(f"Error initializing Trakt service: {e}")
        TRAKT_ENABLED = False
        return False

def get_watched_movies(user_id=None):
    """Get watched movies for specific user"""
    if user_id is None:
        user_id = get_current_user_id()
        
    if not is_trakt_enabled_for_user(user_id):
        return []

    response = make_trakt_request('GET', 'sync/watched/movies', user_id)
    if not response or not response.ok:
        print(f"Trakt API error getting watched movies for user {user_id}: {response.status_code if response else 'No response'}")
        return []

    watched_movies = response.json()
    tmdb_ids = []
    for movie in watched_movies:
        tmdb_id = movie['movie']['ids'].get('tmdb')
        if tmdb_id:
            tmdb_ids.append(tmdb_id)
    return tmdb_ids

def get_trakt_rating(tmdb_id, user_id=None):
    """Get Trakt rating for specific movie and user"""
    if user_id is None:
        user_id = get_current_user_id()

    if not is_trakt_enabled_for_user(user_id):
        return 0

    search_response = make_trakt_request('GET', f'search/tmdb/{tmdb_id}?type=movie', user_id)
    if not search_response or not search_response.ok:
        print(f"Error searching for Trakt ID for user {user_id}: {search_response.status_code if search_response else 'No response'}")
        return 0

    search_data = search_response.json()
    if not search_data:
        print(f"No Trakt data found for TMDb ID: {tmdb_id}")
        return 0

    trakt_id = search_data[0]['movie']['ids']['trakt']

    rating_response = make_trakt_request('GET', f'movies/{trakt_id}/ratings', user_id)
    if not rating_response or not rating_response.ok:
        print(f"Error fetching Trakt rating for user {user_id}: {rating_response.status_code if rating_response else 'No response'}")
        return 0

    rating_data = rating_response.json()
    rating = rating_data.get('rating', 0)
    return int(rating * 10)  

def sync_watched_status(user_id=None):
    """Sync watched status for specific user"""
    if user_id is None:
        user_id = get_current_user_id()

    if not is_trakt_enabled_for_user(user_id):
        return [] 

    watched_movies = get_watched_movies(user_id) 

    directory_key = user_id
    watched_file = DEFAULT_WATCHED_FILE

    if user_id != 'global':
        user_data = None
        managed_user_data = auth_manager.db.get_managed_user_by_username(user_id)
        if managed_user_data:
            user_type = 'plex_managed'
            user_data = managed_user_data
        else:
            regular_user_data = auth_manager.db.get_user(user_id)
            if regular_user_data:
                 user_type = regular_user_data.get('service_type', 'local')
                 user_data = regular_user_data

        if user_type == 'plex_managed' and user_data:
            plex_user_id = user_data.get('plex_user_id')
            if plex_user_id:
                directory_key = f"plex_managed_{plex_user_id}"
                logger.info(f"Using directory key for managed user {user_id}: {directory_key}")
            else:
                logger.error(f"Managed user {user_id} is missing plex_user_id in DB record. Cannot determine correct data path.")
                directory_key = user_id

        user_dir = os.path.join(USER_DATA_DIR, directory_key)
        os.makedirs(user_dir, exist_ok=True)
        watched_file = os.path.join(user_dir, 'trakt_watched_movies.json')

    with open(watched_file, 'w') as f:
        json.dump(watched_movies, f)
        
    return watched_movies

def get_local_watched_movies(user_id=None):
    """Get locally cached watched movies for specific user"""
    if user_id is None:
        user_id = get_current_user_id()
        
    directory_key = user_id
    watched_file = DEFAULT_WATCHED_FILE

    if user_id != 'global':
        user_data = None
        managed_user_data = auth_manager.db.get_managed_user_by_username(user_id)
        if managed_user_data:
            user_type = 'plex_managed'
            user_data = managed_user_data
        else:
            regular_user_data = auth_manager.db.get_user(user_id)
            if regular_user_data:
                 user_type = regular_user_data.get('service_type', 'local')
                 user_data = regular_user_data

        if user_type == 'plex_managed' and user_data:
            plex_user_id = user_data.get('plex_user_id')
            if plex_user_id:
                directory_key = f"plex_managed_{plex_user_id}"
            else:
                logger.error(f"Managed user {user_id} is missing plex_user_id in DB record. Cannot determine correct data path for get_local_watched_movies.")
                directory_key = user_id

        user_dir = os.path.join(USER_DATA_DIR, directory_key)
        watched_file = os.path.join(user_dir, 'trakt_watched_movies.json')

    if os.path.exists(watched_file):
        try:
            with open(watched_file, 'r') as f:
                return json.load(f)
        except:
            return []
    return []

def is_movie_watched(tmdb_id, user_id=None):
    """Check if movie is watched by specific user"""
    if user_id is None:
        user_id = get_current_user_id()
        
    if not is_trakt_enabled_for_user(user_id):
        return False 

    watched_movies = get_local_watched_movies(user_id)
    return tmdb_id in watched_movies

def get_movie_ratings(tmdb_id, user_id=None):
    """Get movie ratings for specific user"""
    if user_id is None:
        user_id = get_current_user_id()

    if not is_trakt_enabled_for_user(user_id):
         return {"trakt_rating": None, "imdb_rating": None} 

    trakt_rating = get_trakt_rating(tmdb_id, user_id) 
    return {
        "trakt_rating": trakt_rating,
        "imdb_rating": None
    }

def get_trakt_id_from_tmdb(tmdb_id, user_id=None):
    """Get Trakt ID from TMDb ID for specific user"""
    if user_id is None:
        user_id = get_current_user_id()

    if not is_trakt_enabled_for_user(user_id):
        return None

    response = make_trakt_request('GET', f'search/tmdb/{tmdb_id}?type=movie', user_id)
    if response and response.ok:
        results = response.json()
        if results:
            try:
                return results[0]['movie']['ids']['trakt']
            except (IndexError, KeyError, TypeError):
                 print(f"Unexpected structure in Trakt search result for TMDb ID {tmdb_id}")
                 return None
    else:
        print(f"Failed Trakt search for TMDb ID {tmdb_id}. Status: {response.status_code if response else 'No Response'}")
        return None

def update_watched_status_for_users():
    """Sync watched status for all users (regular and managed) with Trakt enabled."""
    print("Starting periodic Trakt watched status sync...")
    users_to_sync = []

    if not auth_manager.auth_enabled:
        if is_trakt_enabled_for_user('global'):
            users_to_sync.append('global')
    else:
        all_regular_users = auth_manager.db.get_users()
        for user_id, user_data in all_regular_users.items():
            if user_data.get('trakt_enabled') and user_data.get('trakt_access_token'):
                users_to_sync.append(user_id)

        all_managed_users = auth_manager.db.get_all_managed_users()
        for user_id, user_data in all_managed_users.items():
             full_managed_user_data = auth_manager.db.get_managed_user_by_username(user_id)
             if full_managed_user_data and \
                full_managed_user_data.get('trakt_enabled') and \
                full_managed_user_data.get('trakt_access_token'):
                 users_to_sync.append(user_id)

    synced_count = 0
    unique_user_ids = list(set(users_to_sync))

    print(f"Found {len(unique_user_ids)} users with Trakt enabled for sync: {unique_user_ids}")

    for user_id in unique_user_ids:
        print(f"Syncing Trakt watched status for user: {user_id}")
        try:
            sync_watched_status(user_id=user_id)
            synced_count += 1
        except Exception as e:
            print(f"Error syncing watched status for user {user_id}: {e}")

    print(f"Finished Trakt watched status sync. Synced for {synced_count} users.")
    return True

def update_watched_status_loop():
    """Background loop to update watched status for all users"""
    while True:
        try:
            update_watched_status_for_users()
        except Exception as e:
            print(f"Error in Trakt update loop: {e}")
            
        time.sleep(UPDATE_INTERVAL)

update_thread = Thread(target=update_watched_status_loop, daemon=True)
update_thread.start()
