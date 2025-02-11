from flask import render_template, session, jsonify, Blueprint, current_app
from flask_socketio import emit
from datetime import datetime, timedelta
import pytz
import os
import json
import time
import logging
import requests
from flask import Response
from utils.settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

poster_bp = Blueprint('poster', __name__)
socketio = None

# File to store current movie data
CURRENT_MOVIE_FILE = '/app/data/current_movie.json'

def init_socket(socket):
    global socketio
    socketio = socket

def get_current_timezone():
    """Get current timezone based on settings or ENV"""
    features_settings = settings.get('features', {})
    tz = os.environ.get('TZ') or features_settings.get('timezone', 'UTC')
    return pytz.timezone(tz)

def save_current_movie(movie_data):
    with open(CURRENT_MOVIE_FILE, 'w') as f:
        json.dump(movie_data, f)

def load_current_movie():
    if os.path.exists(CURRENT_MOVIE_FILE):
        with open(CURRENT_MOVIE_FILE, 'r') as f:
            return json.load(f)
    return None

def get_poster_data():
    current_movie = load_current_movie()
    if not current_movie:
        return None

    start_time = datetime.fromisoformat(current_movie['start_time'])
    current_tz = get_current_timezone()
    logger.debug(f"Original start_time: {start_time}, timezone: {current_tz}")

    # Convert to the desired timezone
    if start_time.tzinfo is None:
        start_time = current_tz.localize(start_time)
        logger.debug(f"Localized naive time to: {start_time}")
    else:
        start_time = start_time.astimezone(current_tz)
        logger.debug(f"Converted aware time to: {start_time}")

    duration = timedelta(hours=current_movie['duration_hours'], minutes=current_movie['duration_minutes'])
    end_time = start_time + duration
    logger.debug(f"Calculated end_time: {end_time}")

    movie_data = current_movie['movie']
    # Ensure these fields exist, using defaults if not present
    movie_data.update({
        'contentRating': movie_data.get('contentRating', 'Not Rated'),
        'videoFormat': movie_data.get('videoFormat', 'Unknown'),
        'audioFormat': movie_data.get('audioFormat', 'Unknown')
    })

    return {
        'movie': movie_data,
        'start_time': start_time.isoformat(),
        'end_time': end_time.isoformat(),
        'service': current_movie['service'],
    }

def set_current_movie(movie_data, service, resume_position=0, session_type='NEW', username=None):
    """Set current movie with authorization check"""
    current_time = datetime.now(get_current_timezone())

    if username:  # Only do auth check if username is provided
        playback_monitor = current_app.config.get('PLAYBACK_MONITOR')
        if playback_monitor:
            if not playback_monitor.is_poster_user(username, service):
                logger.info(f"Unauthorized {service} playback by user {username} - not updating poster")
                return
            logger.info(f"Authorized {service} user {username} - updating poster")
        else:
            logger.warning("PlaybackMonitor not available for authorization check")

    total_duration = timedelta(hours=movie_data['duration_hours'],
                             minutes=movie_data['duration_minutes'])
    if session_type in ['NEW', 'PAUSE']:
        if resume_position > 0:
            elapsed = timedelta(seconds=resume_position)
            start_time = current_time - elapsed
        else:
            start_time = current_time
    else:  # session_type == 'STOP'
        start_time = current_time

    current_movie = {
        'movie': movie_data,
        'start_time': start_time.isoformat(),
        'duration_hours': movie_data['duration_hours'],
        'duration_minutes': movie_data['duration_minutes'],
        'service': service,
        'resume_position': resume_position,
        'session_type': session_type
    }
    save_current_movie(current_movie)

    if socketio:
        socketio.emit('movie_changed', current_movie, namespace='/poster')
    else:
        logger.warning("SocketIO not initialized in poster_view")

def get_playback_state(movie_id):
    default_poster_manager = current_app.config.get('DEFAULT_POSTER_MANAGER')
    current_movie = load_current_movie()
    service = current_movie['service'] if current_movie else None
    session_type = current_movie.get('session_type', 'NEW') if current_movie else 'NEW'

    playback_info = None

    if service == 'jellyfin':
        jellyfin_service = current_app.config.get('JELLYFIN_SERVICE')
        if jellyfin_service:
            playback_info = jellyfin_service.get_playback_info(movie_id)
    elif service == 'emby':
        emby_service = current_app.config.get('EMBY_SERVICE')
        if emby_service:
            playback_info = emby_service.get_playback_info(movie_id)
    elif service == 'plex':
        plex_service = current_app.config.get('PLEX_SERVICE')
        if plex_service:
            playback_info = plex_service.get_playback_info(movie_id)

    if playback_info:
        playback_info['session_type'] = session_type
        current_position = playback_info.get('position', 0)
        total_duration = playback_info.get('duration', 0)
        is_playing = playback_info.get('is_playing', False)
        is_paused = playback_info.get('IsPaused', False)
        is_stopped = playback_info.get('IsStopped', False)

        if is_stopped:
            current_state = 'STOPPED'
        elif is_paused:
            current_state = 'PAUSED'
        elif total_duration > 0 and (current_position / total_duration) >= 0.90 and is_playing:
            current_state = 'ENDING'
        elif is_playing:
            current_state = 'PLAYING'
        else:
            current_state = 'UNKNOWN'

        if default_poster_manager:
            default_poster_manager.handle_playback_state(current_state)

        playback_info['status'] = current_state
        return playback_info

    return None

def get_poster_settings():
    """Get current poster settings"""
    from utils.settings import settings
    settings_data = settings.get_all()
    features = settings_data.get('features', {})

    custom_text = os.environ.get('DEFAULT_POSTER_TEXT') or features.get('default_poster_text', '')
    timezone = os.environ.get('TZ') or features.get('timezone', 'UTC')
    poster_mode = os.environ.get('POSTER_MODE') or features.get('poster_mode', 'default')
    # Ensure proper type conversion for interval
    try:
        interval_str = os.environ.get('SCREENSAVER_INTERVAL') or str(features.get('screensaver_interval', '300'))
        screensaver_interval = int(interval_str)
        logger.info(f"Loaded screensaver interval: {screensaver_interval} seconds from value: {interval_str}")
    except (ValueError, TypeError) as e:
        logger.error(f"Error converting interval, using default: {e}")
        screensaver_interval = 300

    return {
        'custom_text': custom_text,
        'timezone': timezone,
        'poster_mode': poster_mode,
        'screensaver_interval': screensaver_interval,
        'features': features  # Return all features for reference
    }

def handle_settings_update(settings_data=None):
    """Update settings and notify connected clients"""
    if socketio:
        if settings_data is None:
            settings_data = settings.get_all()

        settings_to_send = get_poster_settings()
        # Update default poster manager configuration
        default_poster_manager = current_app.config.get('DEFAULT_POSTER_MANAGER')
        if default_poster_manager:
            logger.info("Applying immediate settings update to poster manager")
            default_poster_manager.configure(settings_data)
        # Notify clients
        socketio.emit('settings_updated', settings_to_send, namespace='/poster')
    else:
        logger.warning("SocketIO not initialized in poster_view")

@poster_bp.route('/playback_state/<movie_id>')
def playback_state(movie_id):
    try:
        state = get_playback_state(movie_id)
        if state:
            return jsonify(state)
        else:
            return jsonify({"error": "No playback information available"}), 404
    except Exception as e:
        logger.error(f"Error in playback_state: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@poster_bp.route('/poster')
def poster():
    logger.info("Poster route called")
    try:
        # Get PlaybackMonitor first
        playback_monitor = current_app.config.get('PLAYBACK_MONITOR')

        # Get current service more defensively
        try:
            from movie_selector import get_available_service
            current_service = get_available_service()  # Get default first
            if hasattr(session, 'get'):  # Check if session is available
                current_service = session.get('current_service', current_service)
            logger.info(f"Current service: {current_service}")
        except Exception as e:
            logger.error(f"Error getting service: {e}", exc_info=True)
            current_service = 'plex'  # Default to plex if there's an issue

        # Get services from app config
        default_poster_manager = current_app.config.get('DEFAULT_POSTER_MANAGER')
        plex = current_app.config.get('PLEX_SERVICE')
        jellyfin = current_app.config.get('JELLYFIN_SERVICE')
        emby = current_app.config.get('EMBY_SERVICE')

        # Set the correct service for poster manager
        if not default_poster_manager:
            logger.error("Default poster manager not available")
            raise RuntimeError("Poster manager not configured")

        if current_service == 'plex' and plex:
            default_poster_manager.set_movie_service(plex)
        elif current_service == 'jellyfin' and jellyfin:
            default_poster_manager.set_movie_service(jellyfin)
        elif current_service == 'emby' and emby:
            default_poster_manager.set_movie_service(emby)

        poster_settings = get_poster_settings()
        features = poster_settings.get('features', {})
        custom_text = poster_settings['custom_text']

        # Force an immediate check for active playback
        active_movie = None
        if current_service == 'plex' and plex:
            sessions = plex.plex.sessions()
            for session_data in sessions:
                if session_data.type == 'movie' and playback_monitor.is_poster_user(session_data.usernames[0] if session_data.usernames else None, 'plex'):
                    active_movie = plex.get_movie_by_id(session_data.ratingKey)
                    break
        elif current_service == 'jellyfin' and jellyfin:
            sessions = jellyfin.get_active_sessions()
            for session_data in sessions:
                now_playing = session_data.get('NowPlayingItem', {})
                if now_playing.get('Type') == 'Movie' and playback_monitor.is_poster_user(session_data.get('UserName'), 'jellyfin'):
                    active_movie = jellyfin.get_movie_by_id(now_playing.get('Id'))
                    break
        elif current_service == 'emby' and emby:
            sessions = emby.get_active_sessions()
            for session_data in sessions:
                now_playing = session_data.get('NowPlayingItem', {})
                if now_playing.get('Type') == 'Movie' and playback_monitor.is_poster_user(session_data.get('UserName'), 'emby'):
                    active_movie = emby.get_movie_by_id(now_playing.get('Id'))
                    break

        if active_movie:
            logger.info(f"Active movie found from immediate check: {active_movie.get('title')}")
            # Force update of current_movie.json
            set_current_movie(active_movie, current_service)
            playback_monitor.current_movie_id = active_movie.get('id')

        # Check for active movie from file
        poster_data = get_poster_data()
        if poster_data:
            logger.info("Active movie found - forcing playback mode")
            return render_template('poster.html',
                                movie=poster_data['movie'],
                                start_time=poster_data['start_time'],
                                end_time=poster_data['end_time'],
                                service=poster_data['service'],
                                current_poster=default_poster_manager.get_current_poster(),
                                custom_text=custom_text,
                                features={
                                    'poster_mode': 'default',  # Force default mode for active movies
                                    'screensaver_interval': features.get('screensaver_interval', 300)
                                })

        # If no active movie, proceed with normal logic
        current_poster = default_poster_manager.get_current_poster()

        # Check screensaver mode only if no active movie
        if features.get('poster_mode') == 'screensaver':
            logger.info("Configuring screensaver mode")
            settings_data = settings.get_all()

            if default_poster_manager.movie_service:
                logger.info(f"Movie service available: {default_poster_manager.movie_service.__class__.__name__}")
            else:
                logger.warning("No movie service available for screensaver")

            default_poster_manager.configure(settings_data)

            if default_poster_manager.movie_service:
                random_movie = default_poster_manager.movie_service.get_random_movie()
                if random_movie:
                    logger.info(f"Initial screensaver movie: {random_movie.get('title')}")
                    original_url = random_movie.get('poster', '')
                    proxy_url = None

                    if '/library/metadata' in original_url:  # Plex
                        parts = original_url.split('/library/metadata/')[1].split('?')[0]
                        proxy_url = f"/proxy/poster/plex/{parts}"
                    elif '/Items/' in original_url:  # Both Jellyfin and Emby
                        item_id = original_url.split('/Items/')[1].split('/Images')[0]
                        if jellyfin and jellyfin.server_url in original_url:
                            proxy_url = f"/proxy/poster/jellyfin/{item_id}"
                        elif emby and emby.server_url in original_url:
                            proxy_url = f"/proxy/poster/emby/{item_id}"

                    if not proxy_url:
                        logger.warning("Could not create proxy URL, using fallback")
                        proxy_url = original_url

                    logger.info(f"Using poster URL: {proxy_url}")
                    return render_template('poster.html',
                                        current_poster=proxy_url,
                                        movie=None,
                                        custom_text=custom_text,
                                        features={
                                            'poster_mode': 'screensaver',
                                            'screensaver_interval': features.get('screensaver_interval', 300)
                                        })
                else:
                    logger.warning("Failed to get random movie for screensaver")

        # Handle default poster case
        if current_poster == default_poster_manager.default_poster:
            logger.info("Rendering default poster")
            return render_template('poster.html',
                                current_poster=current_poster,
                                movie=None,
                                custom_text=custom_text,
                                features={
                                    'poster_mode': features.get('poster_mode', 'default'),
                                    'screensaver_interval': features.get('screensaver_interval', 300)
                                })

        # Fallback to default poster
        logger.info("Fallback to default poster")
        return render_template('poster.html',
                            current_poster=default_poster_manager.default_poster,
                            movie=None,
                            custom_text=custom_text,
                            features={
                                'poster_mode': features.get('poster_mode', 'default'),
                                'screensaver_interval': features.get('screensaver_interval', 300)
                            })

    except Exception as e:
        logger.error(f"Error in poster route: {e}", exc_info=True)
        return render_template('poster.html',
                            current_poster="/static/images/default_poster.png",
                            movie=None,
                            custom_text="Error loading poster",
                            features={
                                'poster_mode': 'default',
                                'screensaver_interval': 300
                            })

@poster_bp.route('/current_poster')
def current_poster():
    default_poster_manager = current_app.config.get('DEFAULT_POSTER_MANAGER')
    current_poster = default_poster_manager.get_current_poster()
    logger.debug(f"Current poster route called, returning: {current_poster}")
    return jsonify({'poster': current_poster})

@poster_bp.route('/poster_settings')
def poster_settings():
    settings = get_poster_settings()
    return jsonify(settings)

@poster_bp.route('/proxy/poster/<service>/<path:poster_id>')
def proxy_poster(service, poster_id):
    try:
        if service == 'plex':
            plex_service = current_app.config.get('PLEX_SERVICE')
            if not plex_service:
                logger.error("Plex service not available")
                return Response(status=400)

            base_url = plex_service.PLEX_URL
            token = plex_service.PLEX_TOKEN
            # Extract base ID and timestamp if present
            parts = poster_id.split('/')
            base_id = parts[0]
            full_url = f"{base_url}/library/metadata/{base_id}/thumb"
            if len(parts) > 1:
                full_url += f"/{parts[1]}"
            full_url += f"?X-Plex-Token={token}"

        elif service == 'jellyfin':
            jellyfin_service = current_app.config.get('JELLYFIN_SERVICE')
            if not jellyfin_service:
                logger.error("Jellyfin service not available")
                return Response(status=400)

            base_url = jellyfin_service.server_url
            token = jellyfin_service.api_key
            full_url = f"{base_url}/Items/{poster_id}/Images/Primary?api_key={token}"

        elif service == 'emby':
            emby_service = current_app.config.get('EMBY_SERVICE')
            if not emby_service:
                logger.error("Emby service not available")
                return Response(status=400)

            base_url = emby_service.server_url
            token = emby_service.api_key
            full_url = f"{base_url}/Items/{poster_id}/Images/Primary?api_key={token}"

        else:
            logger.error(f"Unknown service: {service}")
            return Response(status=400)

        response = requests.get(full_url)
        if response.status_code == 200:
            return Response(response.content, mimetype=response.headers['content-type'])
        else:
            logger.error(f"Error getting image from {service}: {response.status_code}")
            return Response(status=response.status_code)

    except Exception as e:
        logger.error(f"Error proxying poster: {e}")
        return Response(status=500)
