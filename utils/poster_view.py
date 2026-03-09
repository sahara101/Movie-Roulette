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
from utils.auth import auth_manager 

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

poster_bp = Blueprint('poster', __name__)
socketio = None

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

def get_poster_proxy_url(poster_url, service):
    """Convert a raw media-server poster URL to a same-origin proxy URL."""
    if not poster_url:
        return ''
    if service == 'plex' and '/library/metadata/' in poster_url:
        parts = poster_url.split('/library/metadata/')[1].split('?')[0]
        return f"/proxy/poster/plex/{parts}"
    if service in ('jellyfin', 'emby') and '/Items/' in poster_url:
        item_id = poster_url.split('/Items/')[1].split('/Images')[0]
        return f"/proxy/poster/{service}/{item_id}"
    return poster_url

def get_backdrop_proxy_url(background_url, service):
    """Convert a raw media-server backdrop URL to a same-origin proxy URL."""
    if not background_url:
        return ''
    if service == 'plex' and '/library/metadata/' in background_url:
        item_id = background_url.split('/library/metadata/')[1].split('/')[0]
        return f"/proxy/backdrop/plex/{item_id}"
    if service in ('jellyfin', 'emby') and '/Items/' in background_url:
        item_id = background_url.split('/Items/')[1].split('/Images')[0]
        return f"/proxy/backdrop/{service}/{item_id}"
    return ''

def _parse_imdb_id(imdb_url):
    """Extract tt-ID from a full IMDb URL, e.g. https://www.imdb.com/title/tt1234567"""
    if imdb_url and '/title/' in imdb_url:
        return imdb_url.split('/title/')[-1].strip('/')
    return ''

def emit_now_playing_update(data, room=None):
    """Emit now_playing_update to a specific room (or globally if room is None)."""
    if socketio:
        if room:
            socketio.emit('now_playing_update', data, room=room, namespace='/')
        else:
            socketio.emit('now_playing_update', data, namespace='/')
    else:
        logger.warning("SocketIO not initialized in poster_view")

def set_current_movie(movie_data, service, resume_position=0, session_type='NEW', username=None, room='nw_global'):
    """Set current movie with authorization check"""
    current_time = datetime.now(get_current_timezone())

    if username:  
        playback_monitor = current_app.config.get('PLAYBACK_MONITOR')
        if playback_monitor:
            if not playback_monitor.is_poster_user(username, service):
                logger.info(f"Unauthorized {service} playback by user {username} - not updating poster")
                return
            logger.info(f"Authorized {service} user {username} - updating poster")
        else:
            logger.warning("PlaybackMonitor not available for authorization check")

    preserve_start_time = None
    if os.path.exists(CURRENT_MOVIE_FILE) and session_type != 'NEW':
        try:
            with open(CURRENT_MOVIE_FILE, 'r') as f:
                existing_data = json.load(f)
                if existing_data.get('movie', {}).get('id') == movie_data.get('id'):
                    preserve_start_time = existing_data.get('start_time')
                    logger.info(f"Preserving original start time: {preserve_start_time}")
        except Exception as e:
            logger.error(f"Error reading existing movie file: {e}")

    total_duration = timedelta(hours=movie_data['duration_hours'],
                             minutes=movie_data['duration_minutes'])

    if preserve_start_time:
        start_time = datetime.fromisoformat(preserve_start_time)
        logger.info(f"Using preserved start time: {start_time}")
    elif session_type in ['NEW', 'PAUSE']:
        if resume_position > 0:
            elapsed = timedelta(seconds=resume_position)
            start_time = current_time - elapsed
        else:
            start_time = current_time
    else:  
        start_time = current_time

    current_movie = {
        'movie': movie_data,
        'start_time': start_time.isoformat(),
        'duration_hours': movie_data['duration_hours'],
        'duration_minutes': movie_data['duration_minutes'],
        'service': service,
        'resume_position': resume_position,
        'session_type': session_type,
        'username': username or '',
    }
    save_current_movie(current_movie)

    default_poster_manager = current_app.config.get('DEFAULT_POSTER_MANAGER')
    if default_poster_manager:
        default_poster_manager.is_default_poster_active = False
        logger.info("Reset default poster flag before movie change notification")

    if socketio:
        socketio.emit('movie_changed', current_movie, namespace='/poster')
        emit_now_playing_update({
            'active': True,
            'status': 'PLAYING',
            'title': movie_data.get('title', ''),
            'year': movie_data.get('year', ''),
            'poster': movie_data.get('poster', ''),
            'service': service,
            'start_time': start_time.isoformat(),
            'total_seconds': int(total_duration.total_seconds()),
            'username': username or '',
            'tmdb_id': movie_data.get('tmdb_id', ''),
            'imdb_id': _parse_imdb_id(movie_data.get('imdb_url', '')),
            'poster_proxy': get_poster_proxy_url(movie_data.get('poster', ''), service),
            'backdrop_proxy': get_backdrop_proxy_url(movie_data.get('background', ''), service),
        }, room=room)
    else:
        logger.warning("SocketIO not initialized in poster_view")

def notify_now_playing_stopped(room='nw_global'):
    """Notify clients that playback has stopped"""
    emit_now_playing_update({'active': False}, room=room)

def notify_now_playing_status(status, position_seconds=0, room='nw_global'):
    """Notify clients of a playback status change (PAUSED/PLAYING/ENDING/UNKNOWN)"""
    emit_now_playing_update({
        'active': True,
        'status': status,
        'position_seconds': int(position_seconds),
    }, room=room)

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
        'features': features  
    }

def handle_settings_update(settings_data=None):
    """Update settings and notify connected clients"""
    if socketio:
        if settings_data is None:
            settings_data = settings.get_all()

        settings_to_send = get_poster_settings()
        default_poster_manager = current_app.config.get('DEFAULT_POSTER_MANAGER')
        if default_poster_manager:
            logger.info("Applying immediate settings update to poster manager")
            default_poster_manager.configure(settings_data)
        socketio.emit('settings_updated', settings_to_send, namespace='/poster')
    else:
        logger.warning("SocketIO not initialized in poster_view")

@poster_bp.route('/playback_state/<movie_id>')
@auth_manager.require_auth 
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
@auth_manager.require_auth 
def poster():
    logger.info("Poster route called")
    try:
        playback_monitor = current_app.config.get('PLAYBACK_MONITOR')

        try:
            from movie_selector import get_available_service
            current_service = get_available_service()  
            if hasattr(session, 'get'):  
                current_service = session.get('current_service', current_service)
            logger.info(f"Current service: {current_service}")
        except Exception as e:
            logger.error(f"Error getting service: {e}", exc_info=True)
            current_service = 'plex'  

        default_poster_manager = current_app.config.get('DEFAULT_POSTER_MANAGER')
        plex = current_app.config.get('PLEX_SERVICE')
        jellyfin = current_app.config.get('JELLYFIN_SERVICE')
        emby = current_app.config.get('EMBY_SERVICE')

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
        heroui_theme = features.get('heroui_theme', False)

        poster_data = get_poster_data()
        active_movie_found = False

        if poster_data:
            logger.info("Active movie found from file - forcing playback mode")
            if default_poster_manager:
                default_poster_manager.is_default_poster_active = False

            movie_poster_url = None
            if os.path.exists(CURRENT_MOVIE_FILE):
                try:
                    with open(CURRENT_MOVIE_FILE, 'r') as f:
                        movie_data = json.load(f)
                        raw_poster_url = movie_data['movie']['poster']

                        if '/library/metadata/' in raw_poster_url:  
                            parts = raw_poster_url.split('/library/metadata/')[1].split('?')[0]
                            movie_poster_url = f"/proxy/poster/plex/{parts}"
                        elif '/Items/' in raw_poster_url:  
                            item_id = raw_poster_url.split('/Items/')[1].split('/Images')[0]
                            if jellyfin and jellyfin.server_url in raw_poster_url:
                                movie_poster_url = f"/proxy/poster/jellyfin/{item_id}"
                            elif emby and emby.server_url in raw_poster_url:
                                movie_poster_url = f"/proxy/poster/emby/{item_id}"
                            else:
                                movie_poster_url = raw_poster_url
                        else:
                            movie_poster_url = raw_poster_url
                        logger.info(f"Using direct movie poster URL: {movie_poster_url}")
                except Exception as e:
                    logger.error(f"Error processing movie poster URL: {e}")

            current_poster = movie_poster_url if movie_poster_url else default_poster_manager.get_current_poster()
            active_movie_found = True

            return render_template('poster.html',
                                movie=poster_data['movie'],
                                start_time=poster_data['start_time'],
                                end_time=poster_data['end_time'],
                                service=poster_data['service'],
                                current_poster=current_poster,
                                custom_text=custom_text,
                                heroui_theme=heroui_theme,
                                features={
                                    'poster_mode': 'default',
                                    'screensaver_interval': features.get('screensaver_interval', 300),
                                    'poster_cinema_overlay': features.get('poster_cinema_overlay', True)
                                })

        if not active_movie_found:
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
                if default_poster_manager:
                    default_poster_manager.is_default_poster_active = False
                set_current_movie(active_movie, current_service)
                playback_monitor.current_movie_id = active_movie.get('id')

                poster_data = get_poster_data()
                if poster_data:
                    movie_poster_url = active_movie.get('poster', '')

                    if '/library/metadata/' in movie_poster_url:  
                        parts = movie_poster_url.split('/library/metadata/')[1].split('?')[0]
                        movie_poster_url = f"/proxy/poster/plex/{parts}"
                    elif '/Items/' in movie_poster_url:  
                        item_id = movie_poster_url.split('/Items/')[1].split('/Images')[0]
                        if jellyfin and jellyfin.server_url in movie_poster_url:
                            movie_poster_url = f"/proxy/poster/jellyfin/{item_id}"
                        elif emby and emby.server_url in movie_poster_url:
                            movie_poster_url = f"/proxy/poster/emby/{item_id}"

                    return render_template('poster.html',
                                        movie=poster_data['movie'],
                                        start_time=poster_data['start_time'],
                                        end_time=poster_data['end_time'],
                                        service=poster_data['service'],
                                        current_poster=movie_poster_url,
                                        custom_text=custom_text,
                                        heroui_theme=heroui_theme,
                                        features={
                                            'poster_mode': 'default',
                                            'screensaver_interval': features.get('screensaver_interval', 300),
                                            'poster_cinema_overlay': features.get('poster_cinema_overlay', True)
                                        })

        current_poster = default_poster_manager.get_current_poster()

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

                    if '/library/metadata' in original_url:  
                        parts = original_url.split('/library/metadata/')[1].split('?')[0]
                        proxy_url = f"/proxy/poster/plex/{parts}"
                    elif '/Items/' in original_url:  
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
                                        heroui_theme=heroui_theme,
                                        initial_directors=random_movie.get('directors', []),
                                        initial_description=random_movie.get('description') or None,
                                        initial_tagline=random_movie.get('tagline') or None,
                                        initial_actors=random_movie.get('actors', [])[:4],
                                        initial_content_rating=random_movie.get('contentRating') or None,
                                        initial_video_format=random_movie.get('videoFormat') or None,
                                        initial_audio_format=random_movie.get('audioFormat') or None,
                                        features={
                                            'poster_mode': 'screensaver',
                                            'screensaver_interval': features.get('screensaver_interval', 300),
                                            'poster_cinema_overlay': features.get('poster_cinema_overlay', True)
                                        })
                else:
                    logger.warning("Failed to get random movie for screensaver")

        if current_poster == default_poster_manager.default_poster:
            logger.info("Rendering default poster")
            return render_template('poster.html',
                                current_poster=current_poster,
                                movie=None,
                                custom_text=custom_text,
                                heroui_theme=heroui_theme,
                                features={
                                    'poster_mode': features.get('poster_mode', 'default'),
                                    'screensaver_interval': features.get('screensaver_interval', 300),
                                    'poster_cinema_overlay': features.get('poster_cinema_overlay', True)
                                })

        logger.info("Fallback to default poster")
        return render_template('poster.html',
                            current_poster=default_poster_manager.default_poster,
                            movie=None,
                            custom_text=custom_text,
                            heroui_theme=heroui_theme,
                            features={
                                'poster_mode': features.get('poster_mode', 'default'),
                                'screensaver_interval': features.get('screensaver_interval', 300),
                                'poster_cinema_overlay': features.get('poster_cinema_overlay', True)
                            })

    except Exception as e:
        logger.error(f"Error in poster route: {e}", exc_info=True)
        return render_template('poster.html',
                            current_poster="/static/images/default_poster.png",
                            movie=None,
                            custom_text="Error loading poster",
                            heroui_theme=False,
                            features={
                                'poster_mode': 'default',
                                'screensaver_interval': 300,
                                'poster_cinema_overlay': True
                            })

@poster_bp.route('/current_poster')
@auth_manager.require_auth 
def current_poster():
    default_poster_manager = current_app.config.get('DEFAULT_POSTER_MANAGER')
    current_poster = default_poster_manager.get_current_poster()
    logger.debug(f"Current poster route called, returning: {current_poster}")
    return jsonify({'poster': current_poster})

@poster_bp.route('/poster_settings')
@auth_manager.require_auth 
def poster_settings():
    settings = get_poster_settings()
    return jsonify(settings)

@poster_bp.route('/proxy/poster/<service>/<path:poster_id>')
@auth_manager.require_auth 
def proxy_poster(service, poster_id):
    try:
        if service == 'plex':
            plex_service = current_app.config.get('PLEX_SERVICE')
            if not plex_service:
                logger.error("Plex service not available")
                return Response(status=400)

            base_url = plex_service.PLEX_URL
            token = plex_service.PLEX_TOKEN
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
            token = jellyfin_service.admin_api_key
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

@poster_bp.route('/proxy/backdrop/<service>/<path:item_id>')
@auth_manager.require_auth
def proxy_backdrop(service, item_id):
    try:
        if service == 'plex':
            plex_service = current_app.config.get('PLEX_SERVICE')
            if not plex_service:
                return Response(status=400)
            full_url = f"{plex_service.PLEX_URL}/library/metadata/{item_id}/art?X-Plex-Token={plex_service.PLEX_TOKEN}"

        elif service == 'jellyfin':
            jellyfin_service = current_app.config.get('JELLYFIN_SERVICE')
            if not jellyfin_service:
                return Response(status=400)
            full_url = f"{jellyfin_service.server_url}/Items/{item_id}/Images/Backdrop?api_key={jellyfin_service.admin_api_key}"

        elif service == 'emby':
            emby_service = current_app.config.get('EMBY_SERVICE')
            if not emby_service:
                return Response(status=400)
            full_url = f"{emby_service.server_url}/Items/{item_id}/Images/Backdrop?api_key={emby_service.api_key}"

        else:
            return Response(status=400)

        response = requests.get(full_url)
        if response.status_code == 200:
            return Response(response.content, mimetype=response.headers['content-type'])
        return Response(status=response.status_code)

    except Exception as e:
        logger.error(f"Error proxying backdrop: {e}")
        return Response(status=500)
