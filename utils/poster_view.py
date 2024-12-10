from flask import render_template, session, jsonify, Blueprint, current_app
from flask_socketio import emit
from datetime import datetime, timedelta
import pytz
import os
import json
import time
import logging
from utils.settings import settings

from utils.path_manager import path_manager
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

poster_bp = Blueprint('poster', __name__)
socketio = None

# File to store current movie data
CURRENT_MOVIE_FILE = path_manager.get_path('current_movie')

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

def set_current_movie(movie_data, service, resume_position=0):
    current_time = datetime.now(get_current_timezone())
    total_duration = timedelta(hours=movie_data['duration_hours'], minutes=movie_data['duration_minutes'])

    if resume_position > 0:
        elapsed = timedelta(seconds=resume_position)
        start_time = current_time - elapsed
    else:
        start_time = current_time

    current_movie = {
        'movie': movie_data,
        'start_time': start_time.isoformat(),
        'duration_hours': movie_data['duration_hours'],
        'duration_minutes': movie_data['duration_minutes'],
        'service': service,
        'resume_position': resume_position
    }
    save_current_movie(current_movie)

    if socketio:
        socketio.emit('movie_changed', current_movie, namespace='/poster')
    else:
        logger.warning("SocketIO not initialized in poster_view")

    default_poster_manager = current_app.config.get('DEFAULT_POSTER_MANAGER')
    if default_poster_manager:
        default_poster_manager.cancel_default_poster_timer()
    else:
        logger.warning("DEFAULT_POSTER_MANAGER not found in app config")

def get_playback_state(movie_id):
    default_poster_manager = current_app.config.get('DEFAULT_POSTER_MANAGER')
    current_movie = load_current_movie()
    service = current_movie['service'] if current_movie else None

    playback_info = None

    if service == 'jellyfin':
        jellyfin_service = current_app.config.get('JELLYFIN_SERVICE')
        if jellyfin_service:
            playback_info = jellyfin_service.get_playback_info(movie_id)
    elif service == 'plex':
        plex_service = current_app.config.get('PLEX_SERVICE')
        if plex_service:
            playback_info = plex_service.get_playback_info(movie_id)
    else:
        playback_info = None

    if playback_info:
        current_position = playback_info.get('position', 0)
        total_duration = playback_info.get('duration', 0)
        is_playing = playback_info.get('is_playing', False)
        is_paused = playback_info.get('IsPaused', False)
        is_stopped = playback_info.get('IsStopped', False)

        if is_stopped:
            current_state = 'STOPPED'
        elif total_duration > 0 and (total_duration - current_position) <= 10:
            current_state = 'ENDED'
        elif is_paused:
            current_state = 'PAUSED'
        elif is_playing:
            current_state = 'PLAYING'
        else:
            current_state = 'UNKNOWN'

        if default_poster_manager:
            default_poster_manager.handle_playback_state(current_state)
        playback_info['status'] = current_state
        return playback_info
    else:
        # Fallback to the current movie data if no real-time info is available
        if current_movie and current_movie['movie']['id'] == movie_id:
            start_time = datetime.fromisoformat(current_movie['start_time'])
            duration = timedelta(hours=current_movie['duration_hours'], minutes=current_movie['duration_minutes'])
            current_time = datetime.now(get_current_timezone())
            resume_position = current_movie.get('resume_position', 0)
            elapsed_time = (current_time - start_time).total_seconds()
            current_position = min(elapsed_time + resume_position, duration.total_seconds())
            if current_position >= duration.total_seconds() - 10:
                current_state = 'ENDED'
            elif elapsed_time >= 0:
                current_state = 'PLAYING'
            else:
                current_state = 'STOPPED'
            if default_poster_manager:
                default_poster_manager.handle_playback_state(current_state)
            return {
                'status': current_state,
                'position': current_position,
                'start_time': start_time.isoformat(),
                'duration': duration.total_seconds()
            }
    return None

def get_poster_settings():
    from utils.settings import settings
    features_settings = settings.get('features', {})

    # Get values in order of precedence: ENV -> settings -> default
    custom_text = os.environ.get('DEFAULT_POSTER_TEXT') or features_settings.get('default_poster_text', '')
    timezone = os.environ.get('TZ') or features_settings.get('timezone', 'UTC')
    plex_users = os.environ.get('PLEX_POSTER_USERS', '').split(',') if os.environ.get('PLEX_POSTER_USERS') else features_settings.get('poster_users', {}).get('plex', [])
    jellyfin_users = os.environ.get('JELLYFIN_POSTER_USERS', '').split(',') if os.environ.get('JELLYFIN_POSTER_USERS') else features_settings.get('poster_users', {}).get('jellyfin', [])

    return {
        'custom_text': custom_text,
        'timezone': timezone,
        'plex_users': [u.strip() for u in plex_users if u.strip()],
        'jellyfin_users': [u.strip() for u in jellyfin_users if u.strip()]
    }

def handle_timezone_update():
    """Update timezone settings and notify connected clients"""
    if socketio:
        settings = get_poster_settings()
        socketio.emit('settings_updated', settings, namespace='/poster')
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
    logger.debug("Poster route called")
    default_poster_manager = current_app.config.get('DEFAULT_POSTER_MANAGER')

    # Get settings
    poster_settings = get_poster_settings()
    custom_text = poster_settings['custom_text']

    logger.debug(f"Custom text from settings: '{custom_text}'")

    current_poster = default_poster_manager.get_current_poster()
    logger.debug(f"Current poster: {current_poster}")

    if current_poster == default_poster_manager.default_poster:
        logger.debug("Rendering default poster with custom text")
        return render_template('poster.html',
                             current_poster=current_poster,
                             custom_text=custom_text)
    else:
        poster_data = get_poster_data()
        if poster_data:
            logger.debug("Rendering movie poster")
            return render_template('poster.html',
                                 movie=poster_data['movie'],
                                 start_time=poster_data['start_time'],
                                 end_time=poster_data['end_time'],
                                 service=poster_data['service'],
                                 current_poster=current_poster,
                                 custom_text=custom_text)
        else:
            logger.debug("No poster data, rendering default poster with custom text")
            return render_template('poster.html',
                                 current_poster=default_poster_manager.default_poster,
                                 custom_text=custom_text)

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
