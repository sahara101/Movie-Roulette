import os
import requests
import logging
import json
from dotenv import load_dotenv
from utils.settings import settings
from utils.tmdb_service import tmdb_service
from utils.path_manager import path_manager

load_dotenv()
logger = logging.getLogger(__name__)

# Global state
JELLYSEERR_INITIALIZED = False
JELLYSEERR_URL = None
JELLYSEERR_API_KEY = None

def initialize_jellyseerr():
    """Initialize or reinitialize Jellyseerr service"""
    global JELLYSEERR_INITIALIZED, JELLYSEERR_URL, JELLYSEERR_API_KEY

    # Get settings
    jellyseerr_settings = settings.get('jellyseerr', {})
    enabled = jellyseerr_settings.get('enabled', False)

    # Get values from ENV or settings
    JELLYSEERR_URL = os.getenv('JELLYSEERR_URL') or jellyseerr_settings.get('url', '').strip()
    JELLYSEERR_API_KEY = os.getenv('JELLYSEERR_API_KEY') or jellyseerr_settings.get('api_key', '').strip()

    # Check if service should be enabled
    is_env_configured = bool(os.getenv('JELLYSEERR_URL') and os.getenv('JELLYSEERR_API_KEY'))
    is_settings_configured = bool(enabled and JELLYSEERR_URL and JELLYSEERR_API_KEY)

    if is_env_configured or is_settings_configured:
        try:
            JELLYSEERR_INITIALIZED = True

            # Get the state file path from path manager
            state_file = path_manager.get_path('jellyseerr_state')
            os.makedirs(os.path.dirname(state_file), exist_ok=True)
            state = {
                'initialized': True,
                'url': JELLYSEERR_URL,
                'api_key': bool(JELLYSEERR_API_KEY)
            }
            with open(state_file, 'w') as f:
                json.dump(state, f)
            return True
        except Exception as e:
            logger.error(f"Failed to save Jellyseerr state: {e}")
            JELLYSEERR_INITIALIZED = False
            return False

    JELLYSEERR_INITIALIZED = False

    # Clean up state file if it exists
    try:
        state_file = path_manager.get_path('jellyseerr_state')
        if os.path.exists(state_file):
            os.remove(state_file)
    except Exception as e:
        logger.error(f"Failed to clean up Jellyseerr state file: {e}")

    return False

# Initialize right away
initialize_jellyseerr()

JELLYSEERR_HEADERS = {}

def update_headers():
    """Update headers with current API key"""
    global JELLYSEERR_HEADERS
    if JELLYSEERR_API_KEY:
        JELLYSEERR_HEADERS = {
            'X-Api-Key': JELLYSEERR_API_KEY,
            'Content-Type': 'application/json'
        }

def get_jellyseerr_csrf_token():
    """Gets CSRF token from Jellyseerr."""
    if not JELLYSEERR_INITIALIZED:
        logger.warning("Cannot get CSRF token: Jellyseerr not initialized")
        return None

    try:
        update_headers()
        response = requests.get(f"{JELLYSEERR_URL}/auth/me", headers=JELLYSEERR_HEADERS)
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
    """Sends a request to Jellyseerr to add a movie to the request list."""
    if not JELLYSEERR_INITIALIZED:
        logger.warning("Cannot request movie: Jellyseerr not initialized")
        return None

    try:
        update_headers()
        endpoint = f"{JELLYSEERR_URL}/api/v1/request"
        headers = JELLYSEERR_HEADERS.copy()
        if csrf_token:
            headers['X-CSRF-Token'] = csrf_token

        data = {
            "mediaId": int(movie_id),
            "mediaType": "movie"
        }

        response = requests.post(endpoint, headers=headers, json=data)
        response.raise_for_status()
        return response.json()

    except requests.RequestException as e:
        if hasattr(e.response, 'text'):
            logger.error(f"Error from Jellyseerr: {e.response.text}")
        logger.error(f"Request error: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in request_movie: {str(e)}")
        return None

def get_media_status(tmdb_id):
    """Get media status from Jellyseerr for a specific TMDb ID."""
    if not JELLYSEERR_INITIALIZED:
        logger.warning("Cannot check media: Jellyseerr not initialized")
        return None

    update_headers()
    endpoint = f"{JELLYSEERR_URL}/api/v1/movie/{tmdb_id}"

    try:
        response = requests.get(endpoint, headers=JELLYSEERR_HEADERS)
        response.raise_for_status()
        data = response.json()
        return data
    except requests.RequestException as e:
        logger.error(f"Error checking media status: {e}")
        return None

def update_configuration(url, api_key):
    """Update service configuration"""
    global JELLYSEERR_URL, JELLYSEERR_API_KEY, JELLYSEERR_INITIALIZED
    JELLYSEERR_URL = url
    JELLYSEERR_API_KEY = api_key
    update_headers()
    JELLYSEERR_INITIALIZED = bool(url and api_key)
    return initialize_jellyseerr()
