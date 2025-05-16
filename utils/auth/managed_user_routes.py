import logging
from flask import Blueprint, request, jsonify, current_app, g
from utils.auth.manager import auth_manager
from utils.auth.db import AuthDB

logger = logging.getLogger(__name__)

managed_user_routes = Blueprint('managed_user_routes', __name__)

@managed_user_routes.route('/api/settings/managed_users', methods=['GET'])
@auth_manager.require_admin
def get_managed_users_route():
    """Get all managed users stored in the database."""
    try:
        users = auth_manager.db.get_all_managed_users()
        return jsonify(users), 200
    except Exception as e:
        logger.error(f"Error fetching managed users: {e}", exc_info=True)
        return jsonify({"error": "Failed to fetch managed users"}), 500

@managed_user_routes.route('/api/settings/managed_users', methods=['POST'])
@auth_manager.require_admin
def add_managed_user_route():
    """Add a new managed user with a password."""
    data = request.get_json()
    if not data or 'plex_user_id' not in data or 'username' not in data or 'password' not in data:
        return jsonify({"error": "Missing required fields (plex_user_id, username, password)"}), 400

    plex_user_id = data['plex_user_id']
    username = data['username']
    password = data['password']

    if not isinstance(password, str) or len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters long"}), 400

    try:
        if auth_manager.db.is_plex_user_added(plex_user_id):
             return jsonify({"error": "This Plex user is already added as a managed user."}), 409
        if auth_manager.db.get_managed_user_by_username(username):
             return jsonify({"error": "This username is already taken by another managed user."}), 409

        success, message = auth_manager.db.add_managed_user(username=username, password=password, plex_user_id=plex_user_id)
        if success:
            new_user_data = auth_manager.db.get_managed_user_by_username(username)
            safe_user_data = new_user_data.copy() if new_user_data else {}
            if 'password' in safe_user_data:
                del safe_user_data['password']
            return jsonify(safe_user_data), 201
        else:
            return jsonify({"error": message or "Failed to add managed user"}), 500
    except Exception as e:
        logger.error(f"Error adding managed user {username}: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred while adding the managed user"}), 500

@managed_user_routes.route('/api/settings/managed_users/<username>', methods=['DELETE'])
@auth_manager.require_admin
def delete_managed_user_route(username):
    """Delete a managed user by their username."""
    try:
        success, message = auth_manager.db.delete_managed_user(username)
        if success:
            return jsonify({"message": message}), 200
        else:
            return jsonify({"error": message or "Managed user not found"}), 404
    except Exception as e:
        logger.error(f"Error deleting managed user '{username}': {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred while deleting the managed user"}), 500

@managed_user_routes.route('/api/settings/managed_users/available', methods=['GET'])
@auth_manager.require_admin
def get_available_managed_users():
    """Get Plex managed users that haven't been added to the password system yet."""
    try:
        plex_service = current_app.config.get('PLEX_SERVICE')
        if not plex_service or not hasattr(plex_service, 'plex'):
             logger.error("Plex service instance or underlying plex connection not found in Flask app config.")
             return jsonify({"error": "Plex service is not configured or available."}), 503

        all_plex_users = []
        try:
            admin_account = plex_service.plex.myPlexAccount()
            all_users_list = admin_account.users()

            all_plex_users = []
            for user in all_users_list:
                 is_managed = (
                     hasattr(user, 'home') and user.home and
                     (not hasattr(user, 'email') or not user.email)
                 )

                 if is_managed and hasattr(user, 'id') and hasattr(user, 'title'):
                     logger.info(f"Identified managed user: {user.title} (ID: {user.id})")
                     all_plex_users.append({'id': str(user.id), 'name': user.title})
                 else:
                      pass

            logger.info(f"Successfully fetched and filtered {len(all_plex_users)} managed users from Plex.")

        except Exception as plex_api_error:
            logger.warning(f"Could not fetch or filter managed users from Plex API (possibly none exist or API error): {plex_api_error}", exc_info=False)
            pass

        added_users = auth_manager.db.get_all_managed_users()
        added_plex_ids = {user_data['plex_user_id'] for user_data in added_users.values() if user_data and 'plex_user_id' in user_data}

        available_users = [user for user in all_plex_users if user.get('id') not in added_plex_ids]

        return jsonify(available_users), 200

    except Exception as e:
        logger.error(f"Unexpected error fetching available managed users: {e}", exc_info=True)
        return jsonify({"error": "An unexpected error occurred while fetching available managed users"}), 500

@managed_user_routes.route('/api/managed_user/change_password', methods=['POST'])
@auth_manager.require_auth
def change_managed_user_password_route():
    """Allows a logged-in managed user to change their own password."""
    user_data = getattr(g, 'user', None)
    if not user_data or user_data.get('service_type') != 'plex_managed':
        return jsonify({"error": "Not authorized or not a managed user"}), 403

    data = request.get_json()
    current_password = data.get('current_password')
    new_password = data.get('new_password')

    if not current_password or not new_password:
        return jsonify({"error": "Current password and new password are required"}), 400

    if len(new_password) < 6:
        return jsonify({"error": "New password must be at least 6 characters long"}), 400

    username = user_data['internal_username']

    valid_current_password, message, _ = auth_manager.db.verify_managed_user_password(username, current_password)
    if not valid_current_password:
        return jsonify({"error": message or "Incorrect current password"}), 400

    success, message = auth_manager.db.update_managed_user_password(username, new_password)
    if success:
        return jsonify({"message": "Password updated successfully"}), 200
    else:
        return jsonify({"error": message or "Failed to update password"}), 500
