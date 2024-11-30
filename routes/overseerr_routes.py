from flask import Blueprint, request, jsonify, session
from utils.tmdb_service import tmdb_service
from utils.overseerr_service import request_movie, get_overseerr_csrf_token

overseerr_bp = Blueprint('overseerr_bp', __name__)

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
    Endpoint to get CSRF token from Overseerr.
    """
    token = get_overseerr_csrf_token()
    if token:
        session['overseerr_csrf_token'] = token
        return jsonify({'token': token}), 200
    else:
        return jsonify({'message': 'CSRF token not available. Requests will be made without CSRF.'}), 200

@overseerr_bp.route('/api/request_movie', methods=['POST'])
def request_movie_route():
    """
    Endpoint to request a movie via Overseerr.
    """
    data = request.get_json()
    movie_id = data.get('movie_id')
    csrf_token = request.headers.get('X-CSRF-Token')
    
    if not movie_id:
        return jsonify({"error": "movie_id is required"}), 400
    
    result = request_movie(movie_id, csrf_token)
    if result:
        return jsonify(result), 200
    else:
        return jsonify({"error": "Failed to request movie. Check server logs for details."}), 500

@overseerr_bp.route('/api/overseerr/status')
def get_overseerr_status():
    """Check if Overseerr is available and properly configured"""
    from utils.overseerr_service import OVERSEERR_INITIALIZED
    return jsonify({
        "available": OVERSEERR_INITIALIZED
    })

@overseerr_bp.route('/api/overseerr/media/<int:tmdb_id>')
def get_media_status_route(tmdb_id):
    """Check media status in Overseerr"""
    from utils.overseerr_service import get_media_status
    result = get_media_status(tmdb_id)
    if result:
        return jsonify(result), 200
    return jsonify({"error": "Failed to get media status"}), 500
