from flask import Blueprint, jsonify, request, session, make_response
import requests
import time
import logging
from utils.settings import settings 
from utils.auth.manager import auth_manager
from utils.tracking_service import get_tracking_provider
from utils.trakt_credentials import get_trakt_client_id, get_trakt_client_secret

logger = logging.getLogger(__name__)

trakt_bp = Blueprint('trakt_bp', __name__)

TRAKT_AUTH_URL = 'https://auth.trakt.tv'
TRAKT_DEVICE_SESSION_KEY = 'trakt_device_auth'

@trakt_bp.route('/trakt/status')
@auth_manager.require_auth 
def status():
    """Get Trakt connection status for current user"""

    env_controlled = settings.is_field_env_controlled('trakt.enabled') or \
                     settings.is_field_env_controlled('trakt.access_token') or \
                     settings.is_field_env_controlled('trakt.refresh_token')

    if env_controlled:
        global_settings = settings.get('trakt', {})
        is_connected = bool(global_settings.get('access_token'))
        is_enabled = is_connected and get_tracking_provider('global') == 'trakt'

        return jsonify({
            'connected': is_connected,
            'env_controlled': True,
            'enabled': is_enabled
        })
    
    if auth_manager.auth_enabled:
        token = request.cookies.get('auth_token')
        session_data = auth_manager.verify_auth(token)
        if not session_data:
            return jsonify({'error': 'User session not found or invalid'}), 401

        username = session_data['username']
        user_type = session_data.get('user_type', 'local')

        user_data = None
        if user_type == 'plex_managed':
            user_data = auth_manager.db.get_managed_user_by_username(username)
            if not user_data:
                logger.error(f"Trakt status: Managed user {username} not found in DB despite valid session.")
                return jsonify({'error': 'Managed user not found in database'}), 404
        else:
            user_data = auth_manager.db.get_user(username)
            if not user_data:
                 logger.error(f"Trakt status: Regular user {username} (type: {user_type}) not found in DB despite valid session.")
                 return jsonify({'error': 'User not found in database'}), 404

        is_connected = bool(user_data.get('trakt_access_token'))
        is_enabled = is_connected and get_tracking_provider(username) == 'trakt'

        status_payload = {
            'connected': is_connected,
            'env_controlled': False,
            'enabled': is_enabled,
            'username': username,
            'user_type': user_type
        }
    else:
        trakt_settings = settings.get('trakt', {})
        is_connected = bool(trakt_settings.get('access_token'))
        is_enabled = is_connected and get_tracking_provider('global') == 'trakt'

        status_payload = {
            'connected': is_connected,
            'env_controlled': False,
            'enabled': is_enabled,
            'auth_disabled': True
        }

    response = make_response(jsonify(status_payload))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

def _current_auth_identity():
    if not auth_manager.auth_enabled:
        return 'global', 'global'

    token = request.cookies.get('auth_token')
    session_data = auth_manager.verify_auth(token)
    if not session_data:
        return None, None
    return session_data['username'], session_data.get('user_type', 'local')


def _save_trakt_tokens(username, user_type, token_data):
    update_data = {
        'trakt_access_token': token_data['access_token'],
        'trakt_refresh_token': token_data['refresh_token'],
        'trakt_enabled': True,
        'tracking_provider': 'trakt',
    }

    if username == 'global':
        settings.update('trakt', {
            'access_token': token_data['access_token'],
            'refresh_token': token_data['refresh_token'],
            'enabled': True,
        })
        settings.update('tracking', {'provider': 'trakt'})
        return True, 'Trakt tokens saved'

    if user_type == 'plex_managed' or auth_manager.db.get_managed_user_by_username(username):
        return auth_manager.db.update_managed_user_data(username, update_data)
    return auth_manager.db.update_user_data(username, update_data)


@trakt_bp.route('/trakt/authorize', methods=['POST'])
@auth_manager.require_auth
def authorize():
    """Start Trakt's portable device-code authorization flow."""
    client_secret = get_trakt_client_secret()
    if not client_secret:
        return jsonify({
            'error': 'A custom TRAKT_CLIENT_ID also requires TRAKT_CLIENT_SECRET.'
        }), 503

    username, user_type = _current_auth_identity()
    if not username:
        return jsonify({'error': 'User session not found or invalid'}), 401

    try:
        response = requests.post(
            f'{TRAKT_AUTH_URL}/oauth/device/code',
            json={'client_id': get_trakt_client_id()},
            timeout=20,
        )
    except requests.RequestException as exc:
        logger.error("Unable to start Trakt device authorization: %s", exc)
        return jsonify({'error': 'Unable to contact Trakt authorization.'}), 502

    if not response.ok:
        logger.error("Trakt device-code request failed: %s - %s", response.status_code, response.text)
        return jsonify({'error': 'Trakt could not start authorization.'}), 502

    payload = response.json()
    device_code = payload.get('device_code')
    user_code = payload.get('user_code')
    verification_url = payload.get('verification_url') or f'{TRAKT_AUTH_URL}/activate'
    if not device_code or not user_code:
        logger.error("Trakt device-code response omitted required fields")
        return jsonify({'error': 'Trakt returned an invalid authorization response.'}), 502
    if not verification_url.startswith(('https://auth.trakt.tv/', 'https://trakt.tv/')):
        verification_url = f'{TRAKT_AUTH_URL}/activate'

    interval = max(int(payload.get('interval', 5)), 5)
    expires_in = max(int(payload.get('expires_in', 600)), interval)
    session[TRAKT_DEVICE_SESSION_KEY] = {
        'device_code': device_code,
        'expires_at': time.time() + expires_in,
        'interval': interval,
        'last_poll': 0,
        'username': username,
        'user_type': user_type,
    }

    return jsonify({
        'user_code': user_code,
        'verification_url': verification_url,
        'expires_in': expires_in,
        'interval': interval,
    })


@trakt_bp.route('/trakt/poll', methods=['POST'])
@auth_manager.require_auth
def poll_device_authorization():
    """Poll Trakt until the user approves or rejects the displayed device code."""
    device_auth = session.get(TRAKT_DEVICE_SESSION_KEY) or {}
    if not device_auth.get('device_code') or time.time() >= device_auth.get('expires_at', 0):
        session.pop(TRAKT_DEVICE_SESSION_KEY, None)
        return jsonify({'error': 'Trakt authorization expired. Start again.'}), 410

    username, user_type = _current_auth_identity()
    if not username or username != device_auth.get('username'):
        session.pop(TRAKT_DEVICE_SESSION_KEY, None)
        return jsonify({'error': 'User session changed. Start Trakt authorization again.'}), 401

    interval = max(int(device_auth.get('interval', 5)), 5)
    if time.time() - device_auth.get('last_poll', 0) < interval:
        return jsonify({'status': 'pending', 'interval': interval}), 202

    client_secret = get_trakt_client_secret()
    if not client_secret:
        session.pop(TRAKT_DEVICE_SESSION_KEY, None)
        return jsonify({'error': 'Trakt client secret is no longer configured.'}), 503

    device_auth['last_poll'] = time.time()
    session[TRAKT_DEVICE_SESSION_KEY] = device_auth
    try:
        response = requests.post(
            f'{TRAKT_AUTH_URL}/oauth/device/token',
            json={
                'code': device_auth['device_code'],
                'client_id': get_trakt_client_id(),
                'client_secret': client_secret,
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        logger.error("Unable to poll Trakt device authorization: %s", exc)
        return jsonify({'error': 'Unable to contact Trakt authorization.'}), 502

    if response.ok:
        token_data = response.json()
        if not token_data.get('access_token') or not token_data.get('refresh_token'):
            session.pop(TRAKT_DEVICE_SESSION_KEY, None)
            return jsonify({'error': 'Trakt returned incomplete tokens.'}), 502

        success, message = _save_trakt_tokens(username, user_type, token_data)
        if not success:
            logger.error("Failed to save Trakt tokens for %s: %s", username, message)
            return jsonify({'error': f'Failed to save Trakt tokens: {message}'}), 500

        session.pop(TRAKT_DEVICE_SESSION_KEY, None)
        try:
            from utils.tracking_service import sync_watched_status
            sync_watched_status(username, force=True)
        except Exception as exc:
            logger.warning("Initial Trakt sync failed for %s: %s", username, exc)
        logger.info("Successfully connected Trakt for user %s", username)
        return jsonify({'status': 'success'})

    if response.status_code == 400:
        return jsonify({'status': 'pending', 'interval': interval}), 202
    if response.status_code == 429:
        interval += 5
        device_auth['interval'] = interval
        session[TRAKT_DEVICE_SESSION_KEY] = device_auth
        return jsonify({'status': 'pending', 'interval': interval}), 202

    session.pop(TRAKT_DEVICE_SESSION_KEY, None)
    errors = {
        404: ('Trakt authorization code is invalid. Start again.', 410),
        409: ('Trakt authorization code was already used. Start again.', 410),
        410: ('Trakt authorization expired. Start again.', 410),
        418: ('Trakt authorization was denied.', 403),
    }
    message, status_code = errors.get(
        response.status_code,
        ('Trakt authorization failed. Start again.', 502),
    )
    logger.warning("Trakt device authorization failed: %s - %s", response.status_code, response.text)
    return jsonify({'error': message}), status_code


@trakt_bp.route('/trakt/token', methods=['POST'])
@auth_manager.require_auth
def get_token():
    """Reject clients using the retired manual out-of-band authorization flow."""
    return jsonify({'error': 'Manual Trakt codes are no longer supported. Start authorization again.'}), 410

@trakt_bp.route('/trakt/disconnect')
@auth_manager.require_auth 
def disconnect():
    """Disconnect Trakt account for current user"""
    try:
        env_controlled = settings.is_field_env_controlled('trakt.enabled') or \
                         settings.is_field_env_controlled('trakt.access_token') or \
                         settings.is_field_env_controlled('trakt.refresh_token')

        if env_controlled:
            logger.warning("Attempted to disconnect Trakt while ENV controlled.")
            return jsonify({
                'status': 'env_controlled',
                'message': 'Cannot disconnect while Trakt is configured via environment variables'
            }), 400

        if auth_manager.auth_enabled:
            token = request.cookies.get('auth_token')
            session_data = auth_manager.verify_auth(token)
            if not session_data:
                return jsonify({'error': 'User session not found or invalid'}), 401
            username = session_data['username']
            user_type = session_data.get('user_type', 'local')

            update_data = {
                'trakt_access_token': None,
                'trakt_refresh_token': None,
                'trakt_enabled': False
            }
            if get_tracking_provider(username) == 'trakt':
                update_data['tracking_provider'] = 'none'

            success = False
            message = "User type not handled"

            if user_type == 'plex_managed':
                success, message = auth_manager.db.update_managed_user_data(username, update_data)
            else:
                success, message = auth_manager.db.update_user_data(username, update_data)

            if success:
                logger.info(f"Successfully disconnected Trakt for user {username} (type: {user_type})")
                return jsonify({'status': 'success'})
            else:
                logger.error(f"Failed to disconnect Trakt for user {username} (type: {user_type}): {message}")
                if "not found" in message.lower():
                     return jsonify({'error': f'Failed to disconnect Trakt: User {username} (type: {user_type}) not found in the expected database.'}), 404
                return jsonify({'error': f'Failed to disconnect Trakt: {message}'}), 500
        else:
            trakt_data = {
                'access_token': None,
                'refresh_token': None,
                'enabled': False
            }
            try:
                settings.update('trakt', trakt_data)
                if get_tracking_provider('global') == 'trakt':
                    settings.update('tracking', {'provider': 'none'})
                logger.info("Successfully disconnected Trakt in global settings")
                return jsonify({'status': 'success'})
            except Exception as e:
                logger.error(f"Failed to disconnect Trakt in global settings: {e}")
                return jsonify({'error': f'Failed to disconnect Trakt: {str(e)}'}), 500
            
    except Exception as e:
        logger.error(f"Error during Trakt disconnect: {str(e)}")
        return jsonify({'error': str(e)}), 500

@trakt_bp.route('/trakt/settings', methods=['PUT'])
@auth_manager.require_auth
def update_trakt_settings():
    """Update the Trakt enabled status for the current user."""
    env_controlled = settings.is_field_env_controlled('trakt.enabled') or \
                     settings.is_field_env_controlled('trakt.access_token') or \
                     settings.is_field_env_controlled('trakt.refresh_token')

    if env_controlled:
        logger.warning("Attempted to update Trakt settings while ENV controlled.")
        return jsonify({
            'status': 'env_controlled',
            'message': 'Cannot update Trakt settings while configured via environment variables'
        }), 400

    data = request.get_json()
    enabled_state = data.get('enabled')

    if enabled_state is None or not isinstance(enabled_state, bool):
        return jsonify({'error': 'Invalid or missing "enabled" field in request (must be true or false)'}), 400

    if auth_manager.auth_enabled:
        token = request.cookies.get('auth_token')
        session_data = auth_manager.verify_auth(token)
        if not session_data:
            return jsonify({'error': 'User session not found or invalid'}), 401
        username = session_data['username']
        user_type = session_data.get('user_type', 'local')

        current_provider = get_tracking_provider(username)
        update_data = {
            'trakt_enabled': enabled_state,
            'tracking_provider': (
                'trakt' if enabled_state
                else ('none' if current_provider == 'trakt' else current_provider)
            )
        }
        success = False
        message = "User type not handled"

        if user_type == 'plex_managed':
             if auth_manager.db.get_managed_user_by_username(username):
                 success, message = auth_manager.db.update_managed_user_data(username, update_data)
             else:
                 success = False
                 message = f"Managed user {username} not found after DB reload during settings update."
                 logger.error(message)
        else:
             if auth_manager.db.get_user(username):
                 success, message = auth_manager.db.update_user_data(username, update_data)
             else:
                 success = False
                 message = f"Regular user {username} not found after DB reload during settings update."
                 logger.error(message)

        if success:
            logger.info(f"Successfully updated Trakt enabled status to {enabled_state} for user {username} (type: {user_type})")
            return jsonify({'status': 'success', 'enabled': enabled_state})
        else:
            logger.error(f"Failed to update Trakt enabled status for user {username} (type: {user_type}): {message}")
            if "not found" in message.lower():
                 return jsonify({'error': f'Failed to update settings: User {username} (type: {user_type}) not found in the expected database.'}), 404
            return jsonify({'error': f'Failed to update settings: {message}'}), 500
    else:
        try:
            settings.update('trakt', {'enabled': enabled_state})
            current_provider = get_tracking_provider('global')
            settings.update('tracking', {
                'provider': (
                    'trakt' if enabled_state
                    else ('none' if current_provider == 'trakt' else current_provider)
                )
            })
            logger.info(f"Successfully updated Trakt enabled status to {enabled_state} in global settings")
            return jsonify({'status': 'success', 'enabled': enabled_state})
        except Exception as e:
            logger.error(f"Failed to update Trakt enabled status in global settings: {e}")
            return jsonify({'error': f'Failed to update settings: {str(e)}'}), 500
