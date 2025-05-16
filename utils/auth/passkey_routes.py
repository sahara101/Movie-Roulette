from flask import Blueprint, request, jsonify, session, make_response, current_app
from datetime import datetime, timedelta
import logging
import json

from .manager import auth_manager
from utils.settings import settings

logger = logging.getLogger(__name__)

passkey_bp = Blueprint('passkey_auth', __name__, url_prefix='/api/auth/passkey')

def _is_passkey_auth_enabled():
    """Check if passkey authentication is enabled in settings."""
    return settings.get('auth', {}).get('passkey_enabled', False)

@passkey_bp.before_request
def check_passkey_enabled_for_management():
    """
    Decorator to ensure passkey auth is enabled before accessing passkey management routes.
    Login option routes should be available even if passkeys are disabled globally,
    as the user might still have a passkey registered from when it was enabled.
    The login verification will ultimately fail if the feature is off.
    """
    if request.endpoint and request.endpoint not in ['passkey_auth.passkey_login_options', 'passkey_auth.passkey_login_verify', 'passkey_auth.passkey_status']:
        if not _is_passkey_auth_enabled():
            logger.warning(f"Passkey route {request.endpoint} accessed but feature not enabled in settings.")
            return jsonify({"error": "Passkey authentication is not enabled."}), 403

@passkey_bp.route('/status', methods=['GET'])
def passkey_status():
    """Returns the status of passkey authentication enablement."""
    return jsonify({"passkeys_enabled": _is_passkey_auth_enabled()}), 200

@passkey_bp.route('/register-options', methods=['POST'])
@auth_manager.require_auth
def passkey_register_options():
    """Generate options for passkey registration."""
    user_data = session.get('user_data')
    if not user_data:
        token = request.cookies.get('auth_token')
        user_data = auth_manager.verify_auth(token)

    if not user_data or user_data.get('service_type') != 'local':
        logger.warning(f"Passkey registration options attempt for non-local user: {user_data.get('username') if user_data else 'Unknown'}")
        return jsonify({"error": "Passkeys can only be registered for local accounts."}), 403
    
    username = user_data['username']
    
    options_json, error_msg = auth_manager.generate_registration_options(username)
    if error_msg:
        return jsonify({"error": error_msg}), 400
    if not options_json:
        return jsonify({"error": "Failed to generate registration options."}), 500
        
    return jsonify(json.loads(options_json)), 200

@passkey_bp.route('/register-verify', methods=['POST'])
@auth_manager.require_auth
def passkey_register_verify():
    """Verify the passkey registration response."""
    user_data = session.get('user_data')
    if not user_data:
        token = request.cookies.get('auth_token')
        user_data = auth_manager.verify_auth(token)

    if not user_data or user_data.get('service_type') != 'local':
        return jsonify({"error": "Passkeys can only be registered for local accounts."}), 403

    username = user_data['username']
    registration_data = request.get_json()

    if not registration_data:
        return jsonify({"error": "Registration response data is required."}), 400
    
    registration_response_json = json.dumps(registration_data)
    passkey_name = registration_data.get('name')

    success, message = auth_manager.verify_registration_response(username, registration_response_json, passkey_name=passkey_name)
    if success:
        return jsonify({"message": message}), 200
    else:
        return jsonify({"error": message}), 400

@passkey_bp.route('/login-options', methods=['POST'])
def passkey_login_options():
    """Generate options for passkey login."""
    data = request.get_json(silent=True) or {}
    username = data.get('username')

    options_json, error_msg = auth_manager.generate_login_options(username)
    if error_msg:
        return jsonify({"error": error_msg}), 400
    if not options_json:
        return jsonify({"error": "Failed to generate login options."}), 500
        
    return jsonify(json.loads(options_json)), 200

@passkey_bp.route('/login-verify', methods=['POST'])
def passkey_login_verify():
    """Verify the passkey login response and create a session."""
    login_response_json = request.get_data(as_text=True)
    if not login_response_json:
        return jsonify({"error": "Login response data is required."}), 400

    success, message, session_token = auth_manager.verify_login_response(login_response_json)
    
    if success and session_token:
        resp = make_response(jsonify({"message": message}), 200)
        try:
            session_lifetime_seconds = int(settings.get('auth', {}).get('session_lifetime', 86400))
        except (ValueError, TypeError):
            session_lifetime_seconds = 86400
        
        expires = datetime.now() + timedelta(seconds=session_lifetime_seconds)
        resp.set_cookie(
            'auth_token',
            session_token,
            expires=expires,
            max_age=session_lifetime_seconds,
            httponly=True,
            secure=request.is_secure,
            samesite='Lax'
        )
        logger.info(f"Passkey login successful, session cookie set for user identified by passkey.")
        return resp
    else:
        logger.warning(f"Passkey login verification failed: {message}")
        return jsonify({"error": message or "Passkey login failed."}), 401

@passkey_bp.route('/list', methods=['GET'])
@auth_manager.require_auth
def list_user_passkeys_route():
    """List passkeys for the currently authenticated local user."""

    user_data = session.get('user_data')
    if not user_data:
        token = request.cookies.get('auth_token')
        user_data = auth_manager.verify_auth(token)

    if not user_data or user_data.get('service_type') != 'local':
        return jsonify({"error": "Passkeys can only be listed for local accounts."}), 403
    
    username = user_data['username']
    passkeys = auth_manager.list_user_passkeys(username)
    return jsonify(passkeys), 200

@passkey_bp.route('/remove', methods=['POST'])
@auth_manager.require_auth
def remove_user_passkey_route():
    """Remove a passkey for the currently authenticated local user."""
    user_data = session.get('user_data')
    if not user_data:
        token = request.cookies.get('auth_token')
        user_data = auth_manager.verify_auth(token)

    if not user_data or user_data.get('service_type') != 'local':
        return jsonify({"error": "Passkeys can only be removed for local accounts."}), 403

    username = user_data['username']
    data = request.get_json()
    if not data or 'credential_id' not in data:
        return jsonify({"error": "Credential ID is required."}), 400
    
    credential_id_b64_str = data['credential_id']
    success, message = auth_manager.remove_user_passkey(username, credential_id_b64_str)
    
    if success:
        return jsonify({"message": message}), 200
    else:
        return jsonify({"error": message}), 400

def register_passkey_routes(app):
    """Function to register this blueprint with the Flask app."""
    app.register_blueprint(passkey_bp)
