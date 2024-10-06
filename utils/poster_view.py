# utils/poster_view.py
from flask import render_template, session, jsonify, Blueprint, current_app
from flask_socketio import emit
from datetime import datetime, timedelta
import pytz
import os
import json
import time
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

poster_bp = Blueprint('poster', __name__)
socketio = None

# Get the timezone from environment variable
TZ = os.environ.get('TZ', 'UTC')
timezone = pytz.timezone(TZ)

# File to store current movie data
CURRENT_MOVIE_FILE = '/app/data/current_movie.json'

def init_socket(socket):
    global socketio
    socketio = socket

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

    # Convert to the desired timezone
    if start_time.tzinfo is None:
        start_time = timezone.localize(start_time)
    else:
        start_time = start_time.astimezone(timezone)

    duration = timedelta(hours=current_movie['duration_hours'], minutes=current_movie['duration_minutes'])
    end_time = start_time + duration

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
    current_time = datetime.now(timezone)
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
        # Determine the current state
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
            current_time = datetime.now(timezone)
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
    custom_text = os.environ.get('DEFAULT_POSTER_TEXT', '')
    logger.debug(f"Custom text from environment: '{custom_text}'")

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
