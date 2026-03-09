import os
import requests
import logging
import json
from dotenv import load_dotenv
from utils.settings import settings
from utils.tmdb_service import tmdb_service

load_dotenv()
logger = logging.getLogger(__name__)

SEERR_INITIALIZED = False
SEERR_URL = None
SEERR_API_KEY = None

def initialize_seerr():
    """Initialize or reinitialize Seerr service"""
    global SEERR_INITIALIZED, SEERR_URL, SEERR_API_KEY

    seerr_settings = settings.get('seerr', {})
    enabled = seerr_settings.get('enabled', False)

    SEERR_URL = os.getenv('SEERR_URL') or seerr_settings.get('url', '').strip()
    SEERR_API_KEY = os.getenv('SEERR_API_KEY') or seerr_settings.get('api_key', '').strip()

    is_env_configured = bool(os.getenv('SEERR_URL') and os.getenv('SEERR_API_KEY'))
    is_settings_configured = bool(enabled and SEERR_URL and SEERR_API_KEY)

    if is_env_configured or is_settings_configured:
        try:
            SEERR_INITIALIZED = True

            state_file = '/app/data/seerr_state.json'
            os.makedirs(os.path.dirname(state_file), exist_ok=True)
            state = {
                'initialized': True,
                'url': SEERR_URL,
                'api_key': bool(SEERR_API_KEY)
            }
            with open(state_file, 'w') as f:
                json.dump(state, f)
            return True
        except Exception as e:
            logger.error(f"Failed to save Seerr state: {e}")
            SEERR_INITIALIZED = False
            return False

    SEERR_INITIALIZED = False

    try:
        state_file = '/app/data/seerr_state.json'
        if os.path.exists(state_file):
            os.remove(state_file)
    except Exception as e:
        logger.error(f"Failed to clean up Seerr state file: {e}")

    return False

initialize_seerr()

SEERR_HEADERS = {}

def update_headers():
    """Update headers with current API key"""
    global SEERR_HEADERS
    if SEERR_API_KEY:
        SEERR_HEADERS = {
            'X-Api-Key': SEERR_API_KEY,
            'Content-Type': 'application/json'
        }

def get_seerr_csrf_token():
    """Gets CSRF token from Seerr."""
    if not SEERR_INITIALIZED:
        logger.warning("Cannot get CSRF token: Seerr not initialized")
        return None

    try:
        update_headers()
        response = requests.get(f"{SEERR_URL}/auth/me", headers=SEERR_HEADERS)
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
    """Sends a request to Seerr to add a movie to the request list."""
    if not SEERR_INITIALIZED:
        logger.warning("Cannot request movie: Seerr not initialized")
        return None

    try:
        update_headers()
        endpoint = f"{SEERR_URL}/api/v1/request"
        headers = SEERR_HEADERS.copy()
        if csrf_token:
            headers['X-CSRF-Token'] = csrf_token

        data = {
            "mediaId": int(movie_id),
            "mediaType": "movie"
        }

        response = requests.post(endpoint, headers=headers, json=data)
        response.raise_for_status()

        # Update the collections cache
        try:
            from utils.collection_service import collection_service
            from flask import g

            user = g.get('user')
            cache_path = collection_service._get_cache_path(user)

            if os.path.exists(cache_path):
                with open(cache_path, 'r+') as f:
                    collections_data = json.load(f)
                    for collection in collections_data.get('collections', []):
                        for movie in collection.get('movies', []):
                            if movie.get('id') == int(movie_id):
                                movie['is_requested'] = True
                                movie['status'] = 'Requested'
                                break
                    f.seek(0)
                    json.dump(collections_data, f)
                    f.truncate()
        except Exception as e:
            logger.error(f"Error updating collections cache: {e}")

        return response.json()

    except requests.RequestException as e:
        if hasattr(e.response, 'text'):
            logger.error(f"Error from Seerr: {e.response.text}")
        logger.error(f"Request error: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in request_movie: {str(e)}")
        return None

def get_media_status(tmdb_id):
    """Get media status from Seerr for a specific TMDb ID."""
    if not SEERR_INITIALIZED:
        logger.warning("Cannot check media: Seerr not initialized")
        return None

    update_headers()
    endpoint = f"{SEERR_URL}/api/v1/movie/{tmdb_id}"

    try:
        response = requests.get(endpoint, headers=SEERR_HEADERS)
        response.raise_for_status()
        data = response.json()
        return data
    except requests.RequestException as e:
        logger.error(f"Error checking media status: {e}")
        return None

def update_configuration(url, api_key):
    """Update service configuration"""
    global SEERR_URL, SEERR_API_KEY, SEERR_INITIALIZED
    SEERR_URL = url
    SEERR_API_KEY = api_key
    update_headers()
    SEERR_INITIALIZED = bool(url and api_key)
    return initialize_seerr()
