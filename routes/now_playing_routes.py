from flask import Blueprint, jsonify, request, current_app
import logging
from utils.auth import auth_manager

logger = logging.getLogger(__name__)
now_playing_bp = Blueprint('now_playing', __name__)


@now_playing_bp.route('/api/now_playing')
@auth_manager.require_auth
def now_playing():
    try:
        from utils.now_playing_service import get_now_playing

        token = request.cookies.get('auth_token')
        user_data = auth_manager.verify_auth(token)

        if user_data and user_data.get('username'):
            username = user_data['username']
            try:
                card_enabled = auth_manager.db.get_user_preference(
                    username, 'show_now_watching_card', default=True
                )
                if not card_enabled:
                    return jsonify({'active': False, 'card_enabled': False})
            except Exception as pref_err:
                logger.warning(f"Could not read preference for {username}: {pref_err}")

        result = get_now_playing(user_data, current_app._get_current_object())
        if result is None:
            return jsonify({'active': False})
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error in now_playing endpoint: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
