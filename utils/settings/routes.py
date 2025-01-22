from flask import Blueprint, jsonify, request, render_template, current_app, redirect, url_for
from . import settings
import logging
import json
import traceback
import os
from utils.version import VERSION

logger = logging.getLogger(__name__)

# Define the blueprint
settings_bp = Blueprint('settings', __name__)

def initialize_services():
    """Initialize or reinitialize media services"""
    try:
        # Get the initialize_services function from the main app
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
def settings_page():
    """Render the settings page"""
    settings_disabled = settings.get('system', {}).get('disable_settings', False)

    # Check both ENV and settings-configured services
    plex_configured = (
        # Check ENV configuration
        all([
            os.getenv('PLEX_URL'),
            os.getenv('PLEX_TOKEN'),
            os.getenv('PLEX_MOVIE_LIBRARIES')
        ]) or
        # Check settings configuration
        (settings.get('plex', {}).get('enabled') and
         bool(settings.get('plex', {}).get('url')) and
         bool(settings.get('plex', {}).get('token')) and
         bool(settings.get('plex', {}).get('movie_libraries')))
    )

    jellyfin_configured = (
        # Check ENV configuration
        all([
            os.getenv('JELLYFIN_URL'),
            os.getenv('JELLYFIN_API_KEY'),
            os.getenv('JELLYFIN_USER_ID')
        ]) or
        # Check settings configuration
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

@settings_bp.route('/api/settings', methods=['GET'])
def get_settings():
    """Get all settings, marking which ones are from ENV"""
    disabled_check = check_settings_enabled()
    if disabled_check:
        return disabled_check

    try:
        all_settings = settings.get_all()
        env_overrides = settings.get_env_overrides()
        return jsonify({
            'settings': all_settings,
            'env_overrides': env_overrides
        })
    except Exception as e:
        logger.error(f"Error getting settings: {str(e)}")
        return jsonify({'error': str(e)}), 500

@settings_bp.route('/api/settings/<category>', methods=['POST'])
def update_settings(category):
    """Update settings that aren't controlled by ENV"""
    disabled_check = check_settings_enabled()
    if disabled_check:
        return disabled_check

    try:
        data = request.json

        # Check if specific field is controlled by ENV
        for key in data:
            field_path = f"{category}.{key}"
            logger.info(f"Checking field {field_path} for ENV control")
            if settings.is_field_env_controlled(field_path):
                logger.warning(f"Field {field_path} is controlled by environment variable")
                return jsonify({
                    'status': 'error',
                    'message': f'Field {key} is controlled by environment variable'
                }), 400

        # Validate and update
        try:
            if settings.update(category, data):
                logger.info(f"Settings updated successfully for category {category}")

                # Clear TMDB cache if TMDB settings changed
                if category == 'tmdb':
                    from utils.tmdb_service import tmdb_service
                    tmdb_service.clear_cache()

                # Check if we need to reinitialize services
                needs_reinit = False

                # If this is a media service update
                if category in ['plex', 'jellyfin', 'emby']:
                    needs_reinit = True
                    logger.info("Media service settings changed, will reinitialize services")

                # If this is a homepage mode update
                if category == 'homepage' and 'mode' in data:
                    needs_reinit = True
                    logger.info("Homepage mode changed, will reinitialize services")

                # If these are feature settings
                if category == 'features':
                    needs_reinit = True
                    logger.info("Feature settings changed, will reinitialize services")

                    # Update poster settings immediately
                    from utils.poster_view import handle_settings_update
                    handle_settings_update(settings.get_all())  

                # Get PlaybackMonitor from app config
                playback_monitor = current_app.config.get('PLAYBACK_MONITOR')
                if playback_monitor:
                    # Update poster users
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

                # Handle default poster text changes
                if data.get('default_poster_text') is not None:
                    logger.info("Default poster text changed, updating poster views")
                    from utils.poster_view import handle_settings_update
                    handle_settings_update(settings.get_all())

                # If these are client settings
                if category == 'clients':
                    needs_reinit = True
                    logger.info("Client settings changed, will reinitialize services")

                # If these are integration settings
                if category in ['overseerr', 'jellyseerr', 'ombi', 'tmdb', 'trakt', 'request_services']:
                    needs_reinit = True
                    logger.info("Integration settings changed, will reinitialize services")

                # Perform reinitialization if needed
                if needs_reinit:
                    success = initialize_services()
                    if not success:
                        logger.error("Service reinitialization failed")
                        return jsonify({
                            'status': 'error',
                            'message': 'Failed to reinitialize services'
                        }), 500
                    logger.info("Services reinitialization successful")

                    # Update PlaybackMonitor status after service reinitialization
                    playback_monitor = current_app.config.get('PLAYBACK_MONITOR')
                    if playback_monitor and hasattr(playback_monitor, 'update_service_status'):
                        logger.info("Updating PlaybackMonitor service status")
                        playback_monitor.update_service_status()

                # Force settings to save to disk
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
def settings_status():
    """Get the current status of the settings page"""
    return jsonify({
        'disabled': is_settings_disabled(),
        'env_controlled': bool(settings.get_env_overrides().get('system.disable_settings', False))
    })
