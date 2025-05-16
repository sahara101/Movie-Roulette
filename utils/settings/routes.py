from flask import Blueprint, jsonify, request, render_template, current_app, redirect, url_for
from . import settings
import logging
import json
import traceback
import os
import requests 
import uuid     
from utils.version import VERSION
from utils.auth import auth_bp, auth_manager
from utils.emby_service import authenticate_emby_server_direct

logger = logging.getLogger(__name__)

settings_bp = Blueprint('settings', __name__)

def initialize_services():
    """Initialize or reinitialize media services"""
    try:
        init_func = current_app.config.get('initialize_services')
        if init_func and callable(init_func):
            return init_func()
        else:
            logger.warning("initialize_services function not found in app config")
            return False
    except Exception as e:
        logger.error(f"Error reinitializing services: {e}")
        return False

def is_settings_disabled():
    """Check if settings page is disabled via ENV or settings"""
    return settings.get('system', {}).get('disable_settings', False)

def settings_disabled_response():
    """Return appropriate response when settings are disabled"""
    if request.headers.get('Accept') == 'application/json':
        return jsonify({'error': 'Settings page is disabled'}), 403
    return render_template('settings_disabled.html')

def check_settings_enabled():
    """Check if settings are enabled and return appropriate response if not"""
    if is_settings_disabled():
        return settings_disabled_response()
    return None

@settings_bp.route('/settings')
@auth_manager.require_auth 
def settings_page():
    """Render the settings page"""
    settings_disabled = settings.get('system', {}).get('disable_settings', False)

    plex_configured = (
        all([
            os.getenv('PLEX_URL'),
            os.getenv('PLEX_TOKEN'),
            os.getenv('PLEX_MOVIE_LIBRARIES')
        ]) or
        (settings.get('plex', {}).get('enabled') and
         bool(settings.get('plex', {}).get('url')) and
         bool(settings.get('plex', {}).get('token')) and
         bool(settings.get('plex', {}).get('movie_libraries')))
    )

    jellyfin_configured = (
        all([
            os.getenv('JELLYFIN_URL'),
            os.getenv('JELLYFIN_API_KEY'),
            os.getenv('JELLYFIN_USER_ID')
        ]) or
        (settings.get('jellyfin', {}).get('enabled') and
         bool(settings.get('jellyfin', {}).get('url')) and
         bool(settings.get('jellyfin', {}).get('api_key')) and
         bool(settings.get('jellyfin', {}).get('user_id')))
    )

    no_services = not (plex_configured or jellyfin_configured)

    return render_template(
        'settings.html',
        settings_disabled=settings_disabled,
        no_services_configured=no_services,
        version=VERSION
    )

from flask import session 

@settings_bp.route('/api/settings', methods=['GET'])
@auth_manager.require_auth 
def get_settings():
    """Get all settings, merging user-specific overrides and marking ENV controls"""
    disabled_check = check_settings_enabled()
    if disabled_check:
        return disabled_check

    try:
        all_settings = settings.get_all()
        env_overrides = settings.get_env_overrides()

        username = session.get('username')
        if username:
            user_data = auth_manager.db.get_user(username)
            if user_data:
                trakt_env_controlled = settings.is_field_env_controlled('trakt.enabled') or \
                                     settings.is_field_env_controlled('trakt.client_id') or \
                                     settings.is_field_env_controlled('trakt.client_secret') or \
                                     settings.is_field_env_controlled('trakt.access_token') or \
                                     settings.is_field_env_controlled('trakt.refresh_token')

                if not trakt_env_controlled and 'trakt_enabled' in user_data:
                    if 'trakt' not in all_settings:
                        all_settings['trakt'] = {} 
                    user_trakt_enabled = user_data.get('trakt_enabled')
                    if user_trakt_enabled is not None:
                         logger.debug(f"Applying user '{username}' specific trakt_enabled: {user_trakt_enabled}")
                         all_settings['trakt']['enabled'] = user_trakt_enabled
                    else:
                         all_settings['trakt']['enabled'] = settings.get('trakt', {}).get('enabled', False)


        return jsonify({
            'settings': all_settings,
            'env_overrides': env_overrides
        })
    except Exception as e:
        logger.error(f"Error getting settings: {str(e)}")
        return jsonify({'error': str(e)}), 500

@settings_bp.route('/api/settings/<category>', methods=['POST'])
@auth_manager.require_admin
def update_settings(category):
    """Update settings that aren't controlled by ENV"""
    disabled_check = check_settings_enabled()
    if disabled_check:
        return disabled_check

    try:
        data = request.json

        for key in data:
            field_path = f"{category}.{key}"
            logger.info(f"Checking field {field_path} for ENV control")
            if settings.is_field_env_controlled(field_path):
                logger.warning(f"Field {field_path} is controlled by environment variable")
                return jsonify({
                    'status': 'error',
                    'message': f'Field {key} is controlled by environment variable'
                }), 400
                
        needs_admin_setup = False
        if category == 'auth' and data.get('enabled') is True:
            plex_enabled = settings.get('plex', {}).get('enabled', False)
            jellyfin_enabled = settings.get('jellyfin', {}).get('enabled', False)
            emby_enabled = settings.get('emby', {}).get('enabled', False)

            if not (plex_enabled or jellyfin_enabled or emby_enabled):
                logger.warning("Attempted to enable authentication without a configured media service.")
                return jsonify({
                    'status': 'error',
                    'message': 'Please enable and configure a media service (Plex, Jellyfin, or Emby) before enabling authentication.'
                }), 400

            if not auth_manager.auth_enabled or auth_manager.needs_admin():
                needs_admin_setup = True
                logger.info("Auth being enabled with no admin user, will redirect to setup")

        try:
            if settings.update(category, data):
                logger.info(f"Settings updated successfully for category {category}")
                
                if category == 'auth' and 'enabled' in data:
                    auth_manager.update_auth_enabled(data['enabled'])
                    
                if needs_admin_setup:
                    return jsonify({
                        'status': 'redirect',
                        'message': 'Authentication enabled, admin setup required',
                        'redirect': url_for('auth.setup')
                    })

                if category == 'tmdb':
                    from utils.tmdb_service import tmdb_service
                    tmdb_service.clear_cache()

                needs_reinit = False

                if category in ['plex', 'jellyfin', 'emby']:
                    needs_reinit = True
                    logger.info("Media service settings changed, will reinitialize services")

                if category == 'homepage' and 'mode' in data:
                    needs_reinit = True
                    logger.info("Homepage mode changed, will reinitialize services")

                if category == 'features':
                    needs_reinit = True
                    logger.info("Feature settings changed, will reinitialize services")

                    from utils.poster_view import handle_settings_update
                    handle_settings_update(settings.get_all())  

                playback_monitor = current_app.config.get('PLAYBACK_MONITOR')
                if playback_monitor:
                    features_settings = settings.get('features', {})
                    poster_users = features_settings.get('poster_users', {})

                    playback_monitor.plex_poster_users = (
                        poster_users.get('plex', []) if isinstance(poster_users.get('plex'), list)
                        else os.getenv('PLEX_POSTER_USERS', '').split(',')
                    )

                    playback_monitor.jellyfin_poster_users = (
                        poster_users.get('jellyfin', []) if isinstance(poster_users.get('jellyfin'), list)
                        else os.getenv('JELLYFIN_POSTER_USERS', '').split(',')
                    )

                    playback_monitor.emby_poster_users = (
                        poster_users.get('emby', []) if isinstance(poster_users.get('emby'), list)
                        else os.getenv('EMBY_POSTER_USERS', '').split(',')
                    )

                    logger.info(f"Updated PlaybackMonitor poster users:")
                    logger.info(f"Plex: {playback_monitor.plex_poster_users}")
                    logger.info(f"Jellyfin: {playback_monitor.jellyfin_poster_users}")
                    logger.info(f"Emby: {playback_monitor.emby_poster_users}")

                if data.get('default_poster_text') is not None:
                    logger.info("Default poster text changed, updating poster views")
                    from utils.poster_view import handle_settings_update
                    handle_settings_update(settings.get_all())

                if category == 'clients':
                    needs_reinit = True
                    logger.info("Client settings changed, will reinitialize services")

                if category in ['overseerr', 'jellyseerr', 'ombi', 'tmdb', 'trakt', 'request_services']:
                    needs_reinit = True
                    logger.info("Integration settings changed, will reinitialize services")

                if needs_reinit:
                    success = initialize_services()
                    if not success:
                        logger.error("Service reinitialization failed")
                        return jsonify({
                            'status': 'error',
                            'message': 'Failed to reinitialize services'
                        }), 500
                    logger.info("Services reinitialization successful")

                    update_poster_manager_func = current_app.config.get('update_default_poster_manager_service')
                    if update_poster_manager_func and callable(update_poster_manager_func):
                        logger.info("Updating default_poster_manager service after settings change.")
                        update_poster_manager_func()
                    else:
                        logger.warning("update_default_poster_manager_service function not found in app config.")

                    playback_monitor = current_app.config.get('PLAYBACK_MONITOR')
                    if playback_monitor and hasattr(playback_monitor, 'update_service_status'):
                        logger.info("Updating PlaybackMonitor service status")
                        playback_monitor.update_service_status()

                settings.save_settings()
                logger.info("Settings saved to disk")

                return jsonify({'status': 'success'})

        except Exception as e:
            logger.error(f"Error in settings update: {str(e)}")
            logger.error(f"Stack trace: {traceback.format_exc()}")
            raise

        logger.error(f"Invalid category: {category}")
        return jsonify({
            'status': 'error',
            'message': 'Invalid category'
        }), 400

    except Exception as e:
        logger.error(f"Error updating settings: {str(e)}")
        logger.error(f"Stack trace: {traceback.format_exc()}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@settings_bp.route('/api/settings/status')
@auth_manager.require_auth 
def settings_status():
    """Get the current status of the settings page"""
    return jsonify({
        'disabled': is_settings_disabled(),
        'env_controlled': bool(settings.get_env_overrides().get('system.disable_settings', False))
    })

@settings_bp.route('/api/settings/emby/authenticate', methods=['POST'])
@auth_manager.require_auth 
def authenticate_emby_settings():
    """Authenticate with provided Emby details and return credentials"""
    disabled_check = check_settings_enabled()
    if disabled_check:
        return disabled_check

    data = request.json
    url = data.get('url')
    username = data.get('username')
    password = data.get('password')

    if not all([url, username, password]):
        return jsonify({'success': False, 'message': 'URL, Username, and Password are required'}), 400

    try:
        success, result = authenticate_emby_server_direct(url, username, password)

        if success:
            return jsonify({
                'success': True,
                'message': 'Authentication successful!',
                **result 
            })
        else:
            status_code = 400 
            if "Invalid username or password" in result:
                status_code = 401 
            elif "timed out" in result:
                status_code = 408 
            elif "unexpected response format" in result:
                 status_code = 502 
            elif "returned an error" in result or "returned status code" in result:
                 status_code = 502 

            return jsonify({'success': False, 'message': result}), status_code

    except Exception as e: 
        logger.error(f"Unexpected error in /api/settings/emby/authenticate route: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'An unexpected error occurred: {e}'}), 500
        return jsonify({'success': False, 'message': 'Connection timed out'}), 408
    except requests.exceptions.RequestException as e: 
        logger.error(f"Error during Emby settings authentication to {url}: {e}")
        error_message = f"Could not connect or communicate with Emby server at {url}. Please check the URL and network."
        if "Name or service not known" in str(e) or "Connection refused" in str(e):
             error_message = f"Could not resolve or connect to Emby server at {url}. Please check the URL."
        return jsonify({'success': False, 'message': error_message}), 400
    except Exception as e: 
        logger.error(f"Unexpected error during Emby settings authentication: {e}", exc_info=True)
        return jsonify({'success': False, 'message': f'An unexpected error occurred: {e}'}), 500
