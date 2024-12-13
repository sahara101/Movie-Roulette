import os
from flask import Blueprint, request, jsonify, session
from utils.tmdb_service import tmdb_service
from utils.settings import settings
from utils.overseerr_service import request_movie, get_overseerr_csrf_token, get_media_status, OVERSEERR_INITIALIZED
from utils.jellyseerr_service import request_movie as jellyseerr_request_movie, get_jellyseerr_csrf_token, get_media_status as jellyseerr_get_media_status, JELLYSEERR_INITIALIZED
from movie_selector import PLEX_AVAILABLE, JELLYFIN_AVAILABLE

overseerr_bp = Blueprint('overseerr_bp', __name__)

def get_request_service():
    """Get the appropriate request service based on current media server"""
    current_service = session.get('current_service', 'plex')
    
    # Get settings
    overseerr_settings = settings.get('overseerr', {})
    jellyseerr_settings = settings.get('jellyseerr', {})
    
    # Check if Jellyseerr is configured via ENV
    has_jellyseerr_env = bool(os.getenv('JELLYSEERR_URL') and os.getenv('JELLYSEERR_API_KEY'))
    
    # If using Jellyfin, only Jellyseerr can be used
    if current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
        if (jellyseerr_settings.get('enabled') and JELLYSEERR_INITIALIZED) or has_jellyseerr_env:
            return 'jellyseerr'
        return None  # No Jellyseerr = no request service for Jellyfin
        
    # If using Plex
    if current_service == 'plex' and PLEX_AVAILABLE:
        # Check if Jellyseerr is forced
        force_jellyseerr = (jellyseerr_settings.get('force_use') or 
                           os.getenv('JELLYSEERR_FORCE_USE', '').upper() == 'TRUE')
        if ((jellyseerr_settings.get('enabled') and JELLYSEERR_INITIALIZED) or has_jellyseerr_env) and force_jellyseerr:
            return 'jellyseerr'
            
        # Otherwise use Overseerr if available
        if overseerr_settings.get('enabled') and OVERSEERR_INITIALIZED:
            return 'overseerr'
            
    return None

@overseerr_bp.route('/api/overseerr/status')
def get_overseerr_status():
    """Check if any request service is available and properly configured"""
    service = get_request_service()
    
    # Get settings for service details
    overseerr_settings = settings.get('overseerr', {})
    jellyseerr_settings = settings.get('jellyseerr', {})
    
    has_jellyseerr_env = bool(os.getenv('JELLYSEERR_URL') and os.getenv('JELLYSEERR_API_KEY'))
    has_overseerr_env = bool(os.getenv('OVERSEERR_URL') and os.getenv('OVERSEERR_API_KEY'))

    return jsonify({
        "available": bool(service),
        "service": service,
        "overseerr_enabled": overseerr_settings.get('enabled', False) or has_overseerr_env,
        "jellyseerr_enabled": jellyseerr_settings.get('enabled', False) or has_jellyseerr_env
    })

@overseerr_bp.route('/api/search_person', methods=['GET'])
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
def get_overseerr_csrf():
    """
    Endpoint to get CSRF token from appropriate service.
    """
    service = get_request_service()
    if not service:
        return jsonify({'error': 'No request service available or enabled'}), 404

    token = None
    if service == 'overseerr':
        token = get_overseerr_csrf_token()
    else:
        token = get_jellyseerr_csrf_token()

    if token:
        session[f'{service}_csrf_token'] = token
        return jsonify({'token': token}), 200
    else:
        return jsonify({'message': 'CSRF token not available. Requests will be made without CSRF.'}), 200

@overseerr_bp.route('/api/request_movie', methods=['POST'])
def request_movie_route():
    """
    Endpoint to request a movie via appropriate service.
    """
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
    else:
        result = jellyseerr_request_movie(movie_id, csrf_token)

    if result:
        return jsonify(result), 200
    else:
        return jsonify({"error": "Failed to request movie. Check server logs for details."}), 500

@overseerr_bp.route('/api/overseerr/media/<int:tmdb_id>')
def get_media_status_route(tmdb_id):
    """Check media status in appropriate service"""
    service = get_request_service()
    if not service:
        return jsonify({"error": "No request service available or enabled"}), 404

    result = None
    if service == 'overseerr':
        result = get_media_status(tmdb_id)
    else:
        result = jellyseerr_get_media_status(tmdb_id)

    if result:
        return jsonify(result), 200
    return jsonify({"error": "Failed to get media status"}), 500
