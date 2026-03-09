import os
import json
import logging
from flask import Blueprint, request, jsonify, session
from utils.tmdb_service import tmdb_service
from utils.settings import settings
from utils.seerr_service import request_movie as seerr_request_movie, get_seerr_csrf_token, get_media_status as seerr_get_media_status, SEERR_INITIALIZED
from utils.ombi_service import request_movie as ombi_request_movie, get_ombi_csrf_token, get_media_status as ombi_get_media_status, OMBI_INITIALIZED
from movie_selector import get_available_service, PLEX_AVAILABLE, JELLYFIN_AVAILABLE, EMBY_AVAILABLE
from utils.auth import auth_manager

request_bp = Blueprint('request_bp', __name__)
logger = logging.getLogger(__name__)

def get_request_service():
    """Get the appropriate request service based on current media server and settings"""
    current_service = session.get('current_service', get_available_service())

    request_services = settings.get('request_services', {})

    seerr_initialized = False
    ombi_initialized = False

    try:
        seerr_state_file = '/app/data/seerr_state.json'
        if os.path.exists(seerr_state_file):
            with open(seerr_state_file, 'r') as f:
                state = json.load(f)
                seerr_initialized = state.get('initialized', False)
    except Exception as e:
        logger.error(f"Failed to read Seerr state: {e}")

    try:
        ombi_state_file = '/app/data/ombi_state.json'
        if os.path.exists(ombi_state_file):
            with open(ombi_state_file, 'r') as f:
                state = json.load(f)
                ombi_initialized = state.get('initialized', False)
    except Exception as e:
        logger.error(f"Failed to read Ombi state: {e}")

    has_seerr_env = bool(os.getenv('SEERR_URL') and os.getenv('SEERR_API_KEY'))
    has_ombi_env = bool(os.getenv('OMBI_URL') and os.getenv('OMBI_API_KEY'))

    global_default = request_services.get('default')

    if current_service == 'plex':
        service_pref = request_services.get('plex_override', global_default)
    elif current_service == 'jellyfin':
        service_pref = request_services.get('jellyfin_override', global_default)
    elif current_service == 'emby':
        service_pref = request_services.get('emby_override', global_default)
    else:
        service_pref = global_default

    def check_service_available(service):
        if service == 'seerr':
            return seerr_initialized or has_seerr_env
        elif service == 'ombi':
            return ombi_initialized or has_ombi_env
        return False

    if service_pref in ['seerr', 'ombi'] and check_service_available(service_pref):
        return service_pref

    if global_default in ['seerr', 'ombi'] and check_service_available(global_default):
        return global_default

    if seerr_initialized or has_seerr_env:
        return 'seerr'
    elif ombi_initialized or has_ombi_env:
        return 'ombi'

    return None

@request_bp.route('/api/requests/status')
@auth_manager.require_auth
def get_request_status():
    """Check if any request service is available and properly configured"""
    seerr_settings = settings.get('seerr', {})
    ombi_settings = settings.get('ombi', {})

    has_seerr_env = bool(os.getenv('SEERR_URL') and os.getenv('SEERR_API_KEY'))
    has_ombi_env = bool(os.getenv('OMBI_URL') and os.getenv('OMBI_API_KEY'))

    service = get_request_service()

    return jsonify({
        "available": bool(service),
        "service": service,
        "seerr_enabled": bool(seerr_settings.get('enabled', False) or has_seerr_env),
        "ombi_enabled": bool(ombi_settings.get('enabled', False) or has_ombi_env)
    })

@request_bp.route('/api/search_person', methods=['GET'])
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

@request_bp.route('/api/movies_by_person', methods=['GET'])
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

@request_bp.route('/api/get_request_csrf', methods=['GET'])
@auth_manager.require_auth
def get_request_csrf():
    """Endpoint to get CSRF token from appropriate service."""
    service = get_request_service()
    if not service:
        return jsonify({'error': 'No request service available or enabled'}), 404

    token = None
    if service == 'seerr':
        token = get_seerr_csrf_token()
    else:
        token = get_ombi_csrf_token()

    if token:
        session[f'{service}_csrf_token'] = token
        return jsonify({'token': token}), 200
    else:
        return jsonify({'message': 'CSRF token not available. Requests will be made without CSRF.'}), 200

@request_bp.route('/api/request_movie', methods=['POST'])
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

    if service == 'seerr':
        result = seerr_request_movie(movie_id, csrf_token)
    else:
        result = ombi_request_movie(movie_id, csrf_token)

    if result:
        return jsonify(result), 200
    else:
        return jsonify({"error": "Failed to request movie. Check server logs for details."}), 500

@request_bp.route('/api/requests/media/<int:tmdb_id>')
@auth_manager.require_auth
def get_media_status_route(tmdb_id):
    """Check media status in appropriate service"""
    service = get_request_service()
    if not service:
        return jsonify({"error": "No request service available or enabled"}), 404

    if service == 'seerr':
        result = seerr_get_media_status(tmdb_id)
    else:
        result = ombi_get_media_status(tmdb_id)

    if result:
        return jsonify(result), 200
    return jsonify({"error": "Failed to get media status"}), 500
