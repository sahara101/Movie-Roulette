import os
import json
import logging
from flask import Blueprint, request, jsonify, session
from utils.tmdb_service import tmdb_service
from utils.settings import settings
from utils.overseerr_service import request_movie, get_overseerr_csrf_token, get_media_status, OVERSEERR_INITIALIZED
from utils.jellyseerr_service import request_movie as jellyseerr_request_movie, get_jellyseerr_csrf_token, get_media_status as jellyseerr_get_media_status, JELLYSEERR_INITIALIZED
from utils.ombi_service import request_movie as ombi_request_movie, get_ombi_csrf_token, get_media_status as ombi_get_media_status, OMBI_INITIALIZED
from movie_selector import get_available_service, PLEX_AVAILABLE, JELLYFIN_AVAILABLE, EMBY_AVAILABLE
from utils.auth import auth_manager 

overseerr_bp = Blueprint('overseerr_bp', __name__)
logger = logging.getLogger(__name__)

def write_debug(message):
    """Write debug message to a file"""
    try:
        with open('/app/data/debug.log', 'a') as f:
            f.write(f"{message}\n")
    except Exception as e:
        print(f"Error writing debug: {e}")

def get_request_service():
    """Get the appropriate request service based on current media server and settings"""
    current_service = session.get('current_service', get_available_service())
    write_debug(f"\n=== get_request_service called ===")
    write_debug(f"Current service: {current_service}")

    request_services = settings.get('request_services', {})
    overseerr_settings = settings.get('overseerr', {})
    jellyseerr_settings = settings.get('jellyseerr', {})
    ombi_settings = settings.get('ombi', {})

    write_debug(f"Request services settings: {request_services}")

    overseerr_initialized = False
    jellyseerr_initialized = False
    ombi_initialized = False

    try:
        overseerr_state_file = '/app/data/overseerr_state.json'
        if os.path.exists(overseerr_state_file):
            with open(overseerr_state_file, 'r') as f:
                state = json.load(f)
                overseerr_initialized = state.get('initialized', False)
                write_debug(f"Overseerr state from file: {state}")
    except Exception as e:
        write_debug(f"Failed to read Overseerr state: {e}")

    try:
        jellyseerr_state_file = '/app/data/jellyseerr_state.json'
        if os.path.exists(jellyseerr_state_file):
            with open(jellyseerr_state_file, 'r') as f:
                state = json.load(f)
                jellyseerr_initialized = state.get('initialized', False)
                write_debug(f"Jellyseerr state from file: {state}")
    except Exception as e:
        write_debug(f"Failed to read Jellyseerr state: {e}")

    try:
        ombi_state_file = '/app/data/ombi_state.json'
        if os.path.exists(ombi_state_file):
            with open(ombi_state_file, 'r') as f:
                state = json.load(f)
                ombi_initialized = state.get('initialized', False)
                write_debug(f"Ombi state from file: {state}")
    except Exception as e:
        write_debug(f"Failed to read Ombi state: {e}")

    write_debug(f"Service states - Overseerr: {overseerr_initialized}, Jellyseerr: {jellyseerr_initialized}, Ombi: {ombi_initialized}")

    has_overseerr_env = bool(os.getenv('OVERSEERR_URL') and os.getenv('OVERSEERR_API_KEY'))
    has_jellyseerr_env = bool(os.getenv('JELLYSEERR_URL') and os.getenv('JELLYSEERR_API_KEY'))
    has_ombi_env = bool(os.getenv('OMBI_URL') and os.getenv('OMBI_API_KEY'))
    
    global_default = request_services.get('default')
    write_debug(f"Global default service: {global_default}")
    
    if current_service == 'plex':
        service_pref = request_services.get('plex_override', global_default)
    elif current_service == 'jellyfin':
        service_pref = request_services.get('jellyfin_override', global_default)
    elif current_service == 'emby':
        service_pref = request_services.get('emby_override', global_default)
    else:
        service_pref = global_default

    write_debug(f"Service preference for {current_service}: {service_pref}")
    
    def check_service_available(service):
        """Helper function to check if a service is available"""
        if service == 'overseerr':
            return overseerr_initialized or has_overseerr_env
        elif service == 'jellyseerr':
            return jellyseerr_initialized or has_jellyseerr_env
        elif service == 'ombi':
            return ombi_initialized or has_ombi_env
        return False
    
    if current_service in ['jellyfin', 'emby']:
        write_debug("Processing non-Plex service path")
        
        if service_pref in ['jellyseerr', 'ombi'] and check_service_available(service_pref):
            write_debug(f"Returning {service_pref} (preferred)")
            return service_pref

        if global_default in ['jellyseerr', 'ombi'] and check_service_available(global_default):
            write_debug(f"Returning {global_default} (global default)")
            return global_default

        if jellyseerr_initialized or has_jellyseerr_env:
            write_debug("Returning jellyseerr (fallback)")
            return 'jellyseerr'
        elif ombi_initialized or has_ombi_env:
            write_debug("Returning ombi (fallback)")
            return 'ombi'

    elif current_service == 'plex':
        write_debug("Processing Plex service path")
        
        if service_pref != 'auto' and check_service_available(service_pref):
            write_debug(f"Returning {service_pref} (preferred)")
            return service_pref

        if global_default != 'auto' and check_service_available(global_default):
            write_debug(f"Returning {global_default} (global default)")
            return global_default

        if overseerr_initialized or has_overseerr_env:
            write_debug("Returning overseerr (fallback)")
            return 'overseerr'
        elif jellyseerr_initialized or has_jellyseerr_env:
            write_debug("Returning jellyseerr (fallback)")
            return 'jellyseerr'
        elif ombi_initialized or has_ombi_env:
            write_debug("Returning ombi (fallback)")
            return 'ombi'

    write_debug("No valid request service found")
    return None

@overseerr_bp.route('/api/overseerr/status')
@auth_manager.require_auth 
def get_overseerr_status():
    """Check if any request service is available and properly configured"""
    current_service = session.get('current_service', get_available_service())

    overseerr_settings = settings.get('overseerr', {})
    jellyseerr_settings = settings.get('jellyseerr', {})
    ombi_settings = settings.get('ombi', {})

    has_jellyseerr_env = bool(os.getenv('JELLYSEERR_URL') and os.getenv('JELLYSEERR_API_KEY'))
    has_overseerr_env = bool(os.getenv('OVERSEERR_URL') and os.getenv('OVERSEERR_API_KEY'))
    has_ombi_env = bool(os.getenv('OMBI_URL') and os.getenv('OMBI_API_KEY'))

    service = get_request_service()

    return jsonify({
        "available": bool(service),
        "service": service,
        "jellyseerr_enabled": bool(jellyseerr_settings.get('enabled', False) or has_jellyseerr_env),
        "overseerr_enabled": bool(overseerr_settings.get('enabled', False) or has_overseerr_env),
        "ombi_enabled": bool(ombi_settings.get('enabled', False) or has_ombi_env)
    })

@overseerr_bp.route('/api/search_person', methods=['GET'])
@auth_manager.require_auth 
def search_person_route():
    """Endpoint to search for a person by name."""
    name = request.args.get('name')
    if not name:
        return jsonify({"error": "Name parameter is required"}), 400
    person = tmdb_service.search_person(name)
    if person:
        return jsonify(person), 200
    else:
        return jsonify({"error": "Person not found"}), 404

@overseerr_bp.route('/api/movies_by_person', methods=['GET'])
@auth_manager.require_auth 
def movies_by_person_route():
    """Endpoint to fetch person details and their movies from TMDb."""
    person_id = request.args.get('person_id')
    if not person_id:
        return jsonify({"error": "person_id parameter is required"}), 400
    person_data = tmdb_service.get_person_details_with_credits(person_id)
    if person_data is not None:
        return jsonify(person_data), 200
    else:
        return jsonify({"error": "Failed to fetch person details and credits"}), 500

@overseerr_bp.route('/api/get_overseerr_csrf', methods=['GET'])
@auth_manager.require_auth 
def get_overseerr_csrf():
    """Endpoint to get CSRF token from appropriate service."""
    service = get_request_service()
    if not service:
        return jsonify({'error': 'No request service available or enabled'}), 404

    token = None
    if service == 'overseerr':
        token = get_overseerr_csrf_token()
    elif service == 'jellyseerr':
        token = get_jellyseerr_csrf_token()
    else:
        token = get_ombi_csrf_token()

    if token:
        session[f'{service}_csrf_token'] = token
        return jsonify({'token': token}), 200
    else:
        return jsonify({'message': 'CSRF token not available. Requests will be made without CSRF.'}), 200

@overseerr_bp.route('/api/request_movie', methods=['POST'])
@auth_manager.require_auth 
def request_movie_route():
    """Endpoint to request a movie via appropriate service."""
    service = get_request_service()
    if not service:
        return jsonify({"error": "No request service available or enabled"}), 404

    data = request.get_json()
    movie_id = data.get('movie_id')
    csrf_token = request.headers.get('X-CSRF-Token')

    if not movie_id:
        return jsonify({"error": "movie_id is required"}), 400

    result = None
    if service == 'overseerr':
        result = request_movie(movie_id, csrf_token)
    elif service == 'jellyseerr':
        result = jellyseerr_request_movie(movie_id, csrf_token)
    else:
        result = ombi_request_movie(movie_id, csrf_token)

    if result:
        return jsonify(result), 200
    else:
        return jsonify({"error": "Failed to request movie. Check server logs for details."}), 500

@overseerr_bp.route('/api/overseerr/media/<int:tmdb_id>')
@auth_manager.require_auth 
def get_media_status_route(tmdb_id):
    """Check media status in appropriate service"""
    service = get_request_service()
    if not service:
        return jsonify({"error": "No request service available or enabled"}), 404

    result = None
    if service == 'overseerr':
        result = get_media_status(tmdb_id)
    elif service == 'jellyseerr':
        result = jellyseerr_get_media_status(tmdb_id)
    else:
        result = ombi_get_media_status(tmdb_id)

    if result:
        return jsonify(result), 200
    return jsonify({"error": "Failed to get media status"}), 500
