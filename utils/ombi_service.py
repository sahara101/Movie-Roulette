import os
import requests
import logging
import json
from dotenv import load_dotenv
from utils.settings import settings
from utils.tmdb_service import tmdb_service

load_dotenv()
logger = logging.getLogger(__name__)

# Global state
OMBI_INITIALIZED = False
OMBI_URL = None
OMBI_API_KEY = None

def write_debug(message):
    """Write debug message to a file"""
    try:
        with open('/app/data/debug.log', 'a') as f:
            f.write(f"{message}\n")
    except Exception as e:
        print(f"Error writing debug: {e}")

def initialize_ombi():
    """Initialize or reinitialize Ombi service"""
    global OMBI_INITIALIZED, OMBI_URL, OMBI_API_KEY
    write_debug("\n=== initialize_ombi called ===")
    
    # First capture current state for logging
    previous_state = {
        'initialized': OMBI_INITIALIZED,
        'has_url': bool(OMBI_URL),
        'has_key': bool(OMBI_API_KEY)
    }
    write_debug(f"Previous state: {previous_state}")

    # Get settings
    ombi_settings = settings.get('ombi', {})
    enabled = ombi_settings.get('enabled', False)
    write_debug(f"Settings: {ombi_settings}")
    write_debug(f"Enabled: {enabled}")

    # Get values from ENV or settings
    OMBI_URL = os.getenv('OMBI_URL') or ombi_settings.get('url', '').strip()
    OMBI_API_KEY = os.getenv('OMBI_API_KEY') or ombi_settings.get('api_key', '').strip()

    # Check if service should be enabled
    is_env_configured = bool(os.getenv('OMBI_URL') and os.getenv('OMBI_API_KEY'))
    is_settings_configured = bool(enabled and OMBI_URL and OMBI_API_KEY)
    write_debug(f"ENV configured: {is_env_configured}")
    write_debug(f"Settings configured: {is_settings_configured}")

    if is_env_configured or is_settings_configured:
        try:
            OMBI_INITIALIZED = True
            
            # Save state to file
            state_file = '/app/data/ombi_state.json'
            os.makedirs(os.path.dirname(state_file), exist_ok=True)
            state = {
                'initialized': True,
                'url': OMBI_URL,
                'api_key': bool(OMBI_API_KEY)
            }
            with open(state_file, 'w') as f:
                json.dump(state, f)
            
            write_debug(f"State file written: {state}")
            write_debug("Ombi service initialized successfully")
            logger.info("Ombi service initialized successfully")
            return True
        except Exception as e:
            write_debug(f"Failed to save Ombi state: {e}")
            logger.error(f"Failed to save Ombi state: {e}")
            OMBI_INITIALIZED = False
            return False

    OMBI_INITIALIZED = False
    
    # Clean up state file if it exists
    try:
        state_file = '/app/data/ombi_state.json'
        if os.path.exists(state_file):
            os.remove(state_file)
            write_debug("State file removed")
    except Exception as e:
        write_debug(f"Failed to clean up Ombi state file: {e}")
    
    write_debug("Ombi service not initialized - missing configuration or disabled")
    logger.info("Ombi service not initialized - missing configuration or disabled")
    return False

# Initialize right away
initialize_ombi()

OMBI_HEADERS = {}

def update_headers():
    """Update headers with current API key"""
    global OMBI_HEADERS
    if OMBI_API_KEY:
        OMBI_HEADERS = {
            'ApiKey': OMBI_API_KEY,  # Note: Ombi uses 'ApiKey' instead of 'X-Api-Key'
            'Content-Type': 'application/json'
        }

def get_ombi_csrf_token():
    """Gets CSRF token from Ombi if needed."""
    if not OMBI_INITIALIZED:
        logger.warning("Cannot get CSRF token: Ombi not initialized")
        return None

    try:
        update_headers()
        response = requests.get(f"{OMBI_URL}/api/v1/Settings/about", headers=OMBI_HEADERS)
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
    """Sends a request to Ombi to add a movie to the request list."""
    if not OMBI_INITIALIZED:
        logger.warning("Cannot request movie: Ombi not initialized")
        return None

    try:
        update_headers()
        endpoint = f"{OMBI_URL}/api/v1/Request/movie"
        headers = OMBI_HEADERS.copy()
        if csrf_token:
            headers['X-CSRF-Token'] = csrf_token

        data = {
            "theMovieDbId": int(movie_id),
            "languageCode": "string",  # Default to system language
            "is4KRequest": False,
            "rootFolderOverride": 0,
            "qualityPathOverride": 0
        }

        logger.info(f"Making request to Ombi - URL: {endpoint}")
        logger.debug(f"Request data: {data}")

        response = requests.post(endpoint, headers=headers, json=data)

        # Log the response for debugging
        logger.debug(f"Response status code: {response.status_code}")
        logger.debug(f"Response content: {response.text}")

        response.raise_for_status()
        return response.json()

    except requests.RequestException as e:
        if hasattr(e.response, 'text'):
            logger.error(f"Error from Ombi: {e.response.text}")
        logger.error(f"Request error: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in request_movie: {str(e)}")
        return None

def get_media_status(tmdb_id):
    """Get media status from Ombi for a specific TMDb ID."""
    if not OMBI_INITIALIZED:
        logger.warning("Cannot check media: Ombi not initialized")
        return None

    update_headers()

    try:
        # First try to get the movie request status
        response = requests.get(
            f"{OMBI_URL}/api/v1/Request/movie",
            headers=OMBI_HEADERS
        )
        response.raise_for_status()
        all_requests = response.json()

        # Find the request matching our tmdb_id
        for request in all_requests:
            if request.get('theMovieDbId') == int(tmdb_id):
                # Convert Ombi status to match Overseerr/Jellyseerr format
                status = 4 if request.get('approved') else 3  # 4=approved, 3=requested
                if request.get('available'):
                    status = 5  # available
                if request.get('denied'):
                    status = 2  # denied

                return {
                    "mediaInfo": {
                        "status": status,
                        "requested": True,
                        "available": request.get('available', False),
                        "approved": request.get('approved', False)
                    }
                }

        # If no request found, return standard format with no request
        return {
            "mediaInfo": {
                "status": 1,  # not requested
                "requested": False
            }
        }

    except requests.RequestException as e:
        logger.error(f"Error checking media status: {e}")
        if hasattr(e.response, 'text'):
            logger.error(f"Response content: {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in get_media_status: {str(e)}")
        return None

def get_user_requests():
    """Get all movie requests for the current user."""
    if not OMBI_INITIALIZED:
        logger.warning("Cannot get requests: Ombi not initialized")
        return None

    update_headers()
    try:
        response = requests.get(f"{OMBI_URL}/api/v1/Request/movie", headers=OMBI_HEADERS)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Error getting user requests: {e}")
        return None

def update_configuration(url, api_key):
    """Update service configuration"""
    global OMBI_URL, OMBI_API_KEY, OMBI_INITIALIZED
    OMBI_URL = url
    OMBI_API_KEY = api_key
    update_headers()
    OMBI_INITIALIZED = bool(url and api_key)
    return initialize_ombi()
