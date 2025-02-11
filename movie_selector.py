import os
import sys
import subprocess
import logging
import json
import random
import traceback
import threading
import time
import requests
from datetime import datetime, timedelta
from plexapi.myplex import MyPlexPinLogin
import uuid
import pytz
import asyncio
from flask import Flask, jsonify, render_template, send_from_directory, request, session, redirect, flash
from flask_socketio import SocketIO, emit
from utils.poster_view import set_current_movie, poster_bp, init_socket
from utils.default_poster_manager import init_default_poster_manager, default_poster_manager
from utils.playback_monitor import PlaybackMonitor
from utils.fetch_movie_links import fetch_movie_links
from functools import lru_cache
from utils.settings.routes import settings_bp
from utils.settings import settings
from utils.cache_manager import CacheManager
from utils.youtube_trailer import search_youtube_trailer
from utils.appletv_discovery import scan_for_appletv, pair_appletv, submit_pin, clear_pairing, ROOT_CONFIG_PATH, turn_on_apple_tv, fix_config_format, check_credentials
from utils.tmdb_service import tmdb_service
from routes.trakt_routes import trakt_bp
from utils.emby_service import EmbyService
from utils.tv import TVFactory
from utils.tv.base.tv_discovery import TVDiscoveryFactory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app first
app = Flask(__name__, static_folder='static', template_folder='web')
app.secret_key = 'your_secret_key_here'
socketio = SocketIO(app, cors_allowed_origins="*")
init_socket(socketio)

HOMEPAGE_SETTINGS = {}
FEATURE_SETTINGS = {}
CLIENT_SETTINGS = {}
APPLE_TV_SETTINGS = {}
PLEX_SETTINGS = {}
JELLYFIN_SETTINGS = {}
EMBY_SETTINGS = {}

# Global flags
HOMEPAGE_MODE = False
USE_LINKS = True
USE_FILTER = True
USE_WATCH_BUTTON = True
USE_NEXT_BUTTON = True
PLEX_AVAILABLE = False
JELLYFIN_AVAILABLE = False
MOBILE_TRUNCATION = False
EMBY_AVAILABLE = False

# Other globals
all_plex_unwatched_movies = []
movies_loaded_from_cache = False
loading_in_progress = False
cache_file_path = '/app/data/plex_unwatched_movies.json'
plex = None
jellyfin = None
emby = None
cache_manager = None
_plex_pin_logins = {}

def load_settings():
    """Load all settings and update global variables"""
    global FEATURE_SETTINGS, CLIENT_SETTINGS, APPLE_TV_SETTINGS
    global PLEX_SETTINGS, JELLYFIN_SETTINGS, EMBY_SETTINGS
    global HOMEPAGE_MODE, USE_LINKS, USE_FILTER, USE_WATCH_BUTTON, USE_NEXT_BUTTON
    global PLEX_AVAILABLE, JELLYFIN_AVAILABLE, EMBY_AVAILABE, MOBILE_TRUNCATION

    # Load all settings first
    FEATURE_SETTINGS = settings.get('features', {})
    CLIENT_SETTINGS = settings.get('clients', {})
    APPLE_TV_SETTINGS = CLIENT_SETTINGS.get('apple_tv', {})
    PLEX_SETTINGS = settings.get('plex', {})
    JELLYFIN_SETTINGS = settings.get('jellyfin', {})
    EMBY_SETTINGS = settings.get('emby', {})

    # Update feature flags
    HOMEPAGE_MODE = FEATURE_SETTINGS.get('homepage_mode', False)
    USE_LINKS = FEATURE_SETTINGS.get('use_links', True)
    USE_FILTER = FEATURE_SETTINGS.get('use_filter', True)
    USE_WATCH_BUTTON = FEATURE_SETTINGS.get('use_watch_button', True)
    USE_NEXT_BUTTON = FEATURE_SETTINGS.get('use_next_button', True)
    MOBILE_TRUNCATION = FEATURE_SETTINGS.get('mobile_truncation', False)

    # Update service availability flags
    PLEX_AVAILABLE = (
        bool(PLEX_SETTINGS.get('enabled')) or
        all([
            os.getenv('PLEX_URL'),
            os.getenv('PLEX_TOKEN'),
            os.getenv('PLEX_MOVIE_LIBRARIES')
        ])
    )

    JELLYFIN_AVAILABLE = (
        bool(JELLYFIN_SETTINGS.get('enabled')) or
        all([
            os.getenv('JELLYFIN_URL'),
            os.getenv('JELLYFIN_API_KEY'),
            os.getenv('JELLYFIN_USER_ID')
        ])
    )

    EMBY_AVAILABLE = (
        bool(EMBY_SETTINGS.get('enabled')) or
        all([
            os.getenv('EMBY_URL'),
            os.getenv('EMBY_API_KEY'),
            os.getenv('EMBY_USER_ID')
        ])
    )

    logger.info(f"Settings loaded - Homepage Mode: {HOMEPAGE_MODE}")
    logger.info(f"Service availability - Plex: {PLEX_AVAILABLE}, Jellyfin: {JELLYFIN_AVAILABLE}, Emby: {EMBY_AVAILABLE}")

def initialize_services():
    """Initialize or reinitialize media services based on current settings"""
    global plex, jellyfin, emby, PLEX_AVAILABLE, JELLYFIN_AVAILABLE, EMBY_AVAILABLE
    global cache_manager
    global HOMEPAGE_MODE, USE_LINKS, USE_FILTER, USE_WATCH_BUTTON, USE_NEXT_BUTTON

    load_settings()

    # Initialize TMDB service
    logger.info("Initializing TMDB service...")
    try:
        from utils.tmdb_service import tmdb_service
        tmdb_service.initialize_service()
        app.config['TMDB_SERVICE'] = tmdb_service
        logger.info("TMDB service initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize TMDB service: {e}")

    # Get settings first
    overseerr_settings = settings.get('overseerr', {})
    tmdb_settings = settings.get('tmdb', {})

    logger.info("Starting services initialization")
    logger.info("Current settings state:")

    # Fix Apple TV configuration
    from utils.appletv_discovery import fix_config_format
    try:
        fix_config_format()
    except Exception as e:
        logger.error(f"Failed to fix Apple TV config: {e}")

    # Initialize Plex if enabled
    plex_enabled = bool(PLEX_SETTINGS.get('enabled')) or all([
        os.getenv('PLEX_URL'),
        os.getenv('PLEX_TOKEN'),
        os.getenv('PLEX_MOVIE_LIBRARIES')
    ])

    if plex_enabled:
        logger.info("Initializing Plex service...")
        try:
            from utils.plex_service import PlexService
            plex = PlexService(
                url=os.getenv('PLEX_URL') or PLEX_SETTINGS.get('url'),
                token=os.getenv('PLEX_TOKEN') or PLEX_SETTINGS.get('token'),
                libraries=os.getenv('PLEX_MOVIE_LIBRARIES', '').split(',') if os.getenv('PLEX_MOVIE_LIBRARIES') else PLEX_SETTINGS.get('movie_libraries', [])
            )
            app.config['PLEX_SERVICE'] = plex
            PLEX_AVAILABLE = True

            # Initialize cache manager
            logger.info("Initializing Plex cache manager...")
            cache_manager = CacheManager(plex, cache_file_path, socketio, app)
            app.config['CACHE_MANAGER'] = cache_manager
            cache_manager.start()

            plex.set_cache_manager(cache_manager)

            logger.info("Plex service initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Plex service: {e}")
            plex = None
            cache_manager = None
            PLEX_AVAILABLE = False
    else:
        logger.info("Plex service is not configured")
        plex = None
        cache_manager = None
        PLEX_AVAILABLE = False

    # Initialize Jellyfin if enabled
    jellyfin_enabled = bool(JELLYFIN_SETTINGS.get('enabled')) or all([
        os.getenv('JELLYFIN_URL'),
        os.getenv('JELLYFIN_API_KEY'),
        os.getenv('JELLYFIN_USER_ID')
    ])

    if jellyfin_enabled:
        logger.info("Initializing Jellyfin service...")
        try:
            from utils.jellyfin_service import JellyfinService
            jellyfin = JellyfinService(
                url=os.getenv('JELLYFIN_URL') or JELLYFIN_SETTINGS.get('url'),
                api_key=os.getenv('JELLYFIN_API_KEY') or JELLYFIN_SETTINGS.get('api_key'),
                user_id=os.getenv('JELLYFIN_USER_ID') or JELLYFIN_SETTINGS.get('user_id'),
                update_interval=600  # Same as Plex default
            )
            app.config['JELLYFIN_SERVICE'] = jellyfin
            JELLYFIN_AVAILABLE = True
            logger.info("Jellyfin service initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Jellyfin service: {e}")
            jellyfin = None
            JELLYFIN_AVAILABLE = False
    else:
        logger.info("Jellyfin service is not configured")
        jellyfin = None
        JELLYFIN_AVAILABLE = False

    emby_enabled = bool(EMBY_SETTINGS.get('enabled')) or all([
        os.getenv('EMBY_URL'),
        os.getenv('EMBY_API_KEY'),
        os.getenv('EMBY_USER_ID')
    ])

    if emby_enabled:
        logger.info("Initializing Emby service...")
        try:
            from utils.emby_service import EmbyService
            emby = EmbyService(
                url=os.getenv('EMBY_URL') or EMBY_SETTINGS.get('url'),
                api_key=os.getenv('EMBY_API_KEY') or EMBY_SETTINGS.get('api_key'),
                user_id=os.getenv('EMBY_USER_ID') or EMBY_SETTINGS.get('user_id')
            )
            app.config['EMBY_SERVICE'] = emby
            EMBY_AVAILABLE = True
            logger.info("Emby service initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Emby service: {e}")
            emby = None
            EMBY_AVAILABLE = False
    else:
        logger.info("Emby service is not configured")
        emby = None
        EMBY_AVAILABLE = False

    # Initialize Overseerr if enabled
    overseerr_enabled = (
        (bool(os.getenv('OVERSEERR_URL')) and bool(os.getenv('OVERSEERR_API_KEY'))) or
        (bool(overseerr_settings.get('enabled')) and
         bool(overseerr_settings.get('url', '').strip()) and
         bool(overseerr_settings.get('api_key', '').strip()))
    )

    if overseerr_enabled:
        logger.info("Initializing Overseerr service...")
        try:
            from utils.overseerr_service import update_configuration
            success = update_configuration(
                url=os.getenv('OVERSEERR_URL') or overseerr_settings.get('url', ''),
                api_key=os.getenv('OVERSEERR_API_KEY') or overseerr_settings.get('api_key', ''),
            )
            if success:
                logger.info("Overseerr service initialized successfully")
            else:
                logger.error("Failed to initialize Overseerr service")
        except Exception as e:
            logger.error(f"Failed to initialize Overseerr service: {e}")
    else:
        logger.info("Overseerr service is disabled or not configured")
        # Reset Overseerr configuration
        try:
            from utils.overseerr_service import update_configuration
            update_configuration(url='', api_key='')
        except Exception as e:
            logger.error(f"Failed to reset Overseerr configuration: {e}")

    # Initialize Jellyseerr if enabled
    jellyseerr_settings = settings.get('jellyseerr', {})
    jellyseerr_enabled = (
        (bool(os.getenv('JELLYSEERR_URL')) and bool(os.getenv('JELLYSEERR_API_KEY'))) or
        (bool(jellyseerr_settings.get('enabled')) and
         bool(jellyseerr_settings.get('url', '').strip()) and
         bool(jellyseerr_settings.get('api_key', '').strip()))
    )

    if jellyseerr_enabled:
        logger.info("Initializing Jellyseerr service...")
        try:
            from utils.jellyseerr_service import update_configuration
            if update_configuration(
                url=os.getenv('JELLYSEERR_URL') or jellyseerr_settings.get('url', ''),
                api_key=os.getenv('JELLYSEERR_API_KEY') or jellyseerr_settings.get('api_key', '')
            ):
                logger.info("Jellyseerr service initialized successfully")
            else:
                logger.error("Failed to initialize Jellyseerr service")
        except Exception as e:
            logger.error(f"Failed to initialize Jellyseerr service: {e}")
    else:
        logger.info("Jellyseerr service is disabled or not configured")

    logger.info(f"- Jellyseerr: {jellyseerr_enabled}")

    # Initialize Ombi if enabled
    ombi_settings = settings.get('ombi', {})
    ombi_enabled = (
        (bool(os.getenv('OMBI_URL')) and bool(os.getenv('OMBI_API_KEY'))) or
        (bool(ombi_settings.get('enabled')) and
         bool(ombi_settings.get('url', '').strip()) and
         bool(ombi_settings.get('api_key', '').strip()))
    )

    if ombi_enabled:
        logger.info("Initializing Ombi service...")
        try:
            from utils.ombi_service import update_configuration
            if update_configuration(
                url=os.getenv('OMBI_URL') or ombi_settings.get('url', ''),
                api_key=os.getenv('OMBI_API_KEY') or ombi_settings.get('api_key', '')
            ):
                logger.info("Ombi service initialized successfully")
            else:
                logger.error("Failed to initialize Ombi service")
        except Exception as e:
            logger.error(f"Failed to initialize Ombi service: {e}")
    else:
        logger.info("Ombi service is disabled or not configured")

    # Initialize Trakt if enabled
    trakt_settings = settings.get('trakt', {})
    trakt_enabled = (
        # Check ENV configuration
        bool(all([
            os.getenv('TRAKT_CLIENT_ID'),
            os.getenv('TRAKT_CLIENT_SECRET'),
            os.getenv('TRAKT_ACCESS_TOKEN'),
            os.getenv('TRAKT_REFRESH_TOKEN')
        ])) or
        # Check if tokens file exists and 'enabled' is True in settings
        (bool(trakt_settings.get('enabled')) and os.path.exists('/app/data/trakt_tokens.json'))
    )

    if trakt_enabled:
        logger.info("Initializing Trakt service...")
        try:
            if 'utils.trakt_service' in sys.modules:
                del sys.modules['utils.trakt_service']
            from utils.trakt_service import initialize_trakt
            if not initialize_trakt():
                logger.error("Failed to initialize Trakt service")
                trakt_enabled = False
        except Exception as e:
            logger.error(f"Failed to initialize Trakt service: {e}")
            trakt_enabled = False

    # Log the final status
    logger.info(f"Services initialization complete:")
    logger.info(f"- Plex: {PLEX_AVAILABLE}")
    logger.info(f"- Jellyfin: {JELLYFIN_AVAILABLE}")
    logger.info(f"- Emby: {EMBY_AVAILABLE}")
    logger.info(f"- Overseerr: {overseerr_enabled}")
    logger.info(f"- Ombi: {ombi_enabled}")
    logger.info(f"- Jellyseerr: {jellyseerr_enabled}")
    logger.info(f"- Trakt: {trakt_enabled}")

    return True

def get_available_service():
    if PLEX_AVAILABLE:
        return 'plex'
    elif JELLYFIN_AVAILABLE:
        return 'jellyfin'
    elif EMBY_AVAILABLE:
        return 'emby'
    else:
        raise EnvironmentError("No media service is available")

def resync_cache():
    global all_plex_unwatched_movies, movies_loaded_from_cache, loading_in_progress
    if loading_in_progress:
        return
    loading_in_progress = True
    try:
        if cache_manager:
            cache_manager.update_cache(emit_progress=True)
            all_plex_unwatched_movies = cache_manager.get_cached_movies()
        movies_loaded_from_cache = True
        update_cache_status()
    except Exception as e:
        logger.error(f"Error in resync_cache: {str(e)}")
    finally:
        loading_in_progress = False
        socketio.emit('loading_complete')

def initialize_cache():
    global all_plex_unwatched_movies, movies_loaded_from_cache
    if PLEX_AVAILABLE and cache_manager:
        all_plex_unwatched_movies = cache_manager.get_cached_movies()
        movies_loaded_from_cache = True
        logger.info(f"Loaded {len(all_plex_unwatched_movies)} movies from cache.")
    else:
        logger.info("Cache initialization not required or not available.")

def update_cache_status():
    global movies_loaded_from_cache
    if os.path.exists(cache_file_path):
        with open(cache_file_path, 'r') as f:
            cached_movies = json.load(f)
        if cached_movies:
            movies_loaded_from_cache = True
            logger.info(f"Updated cache status: {len(cached_movies)} movies loaded from cache.")
        else:
            movies_loaded_from_cache = False
            logger.info("Cache file exists but is empty.")
    else:
        movies_loaded_from_cache = False
        logger.info("Cache file does not exist.")

@lru_cache(maxsize=128)
def cached_search_person(name):
    return tmdb_service.search_person_by_name(name)

def enrich_movie_data(movie_data):
    """Enriches movie data with URLs and correct cast from TMDB"""
    current_service = session.get('current_service', get_available_service())
    tmdb_url, trakt_url, imdb_url = fetch_movie_links(movie_data, current_service)
    trailer_url = search_youtube_trailer(movie_data['title'], movie_data['year'])

    tmdb_id = movie_data.get('tmdb_id')
    if tmdb_id:
        credits = tmdb_service.get_movie_cast(tmdb_id)
        if credits:
            movie_data['actors_enriched'] = [
                {
                    "name": actor['name'],
                    "id": actor['id'],
                    "type": "actor",
                    "character": actor.get('character', '')
                }
                for actor in credits['cast']
            ]

            directors_map = {}
            for person in credits['crew']:
                if person['job'] == 'Director' or person['department'] == 'Directing':
                    director_id = person['id']
                    if director_id in directors_map:
                        directors_map[director_id]['jobs'].append(person.get('job', ''))
                    else:
                        directors_map[director_id] = {
                            "name": person['name'],
                            "id": person['id'],
                            "type": "director",
                            "job": person.get('job', ''),
                            "jobs": [person.get('job', '')],
                            "is_primary": person['job'] == 'Director'
                        }

            # Sort directors so primary directors come first
            movie_data['directors_enriched'] = sorted(
                list(directors_map.values()),
                key=lambda x: (not x['is_primary'], x['name'])
            )

            writers_map = {}
            for person in credits['crew']:
                if person['department'] == 'Writing':
                    writer_id = person['id']
                    if writer_id in writers_map:
                        writers_map[writer_id]['jobs'].append(person.get('job', ''))
                    else:
                        writers_map[writer_id] = {
                            "name": person['name'],
                            "id": person['id'],
                            "type": "writer",
                            "job": person.get('job', ''),
                            "jobs": [person.get('job', '')],
                            "is_primary": person['job'] in ['Writer', 'Screenplay']
                        }

            movie_data['writers_enriched'] = sorted(
                list(writers_map.values()),
                key=lambda x: (not x['is_primary'], x['name'])
            )
    else:
        movie_data.update({
            "actors_enriched": [{"name": name, "id": None, "type": "actor"}
                             for name in movie_data.get('actors', [])],
            "directors_enriched": [{"name": name, "id": None, "type": "director"}
                                for name in movie_data.get('directors', [])]
        })

    movie_data.update({
        "tmdb_url": tmdb_url,
        "trakt_url": trakt_url,
        "imdb_url": imdb_url,
        "trailer_url": trailer_url
    })

    return movie_data

def fetch_movie_links_for_overlay(tmdb_id):
    """Get movie links using centralized TMDB service"""
    return tmdb_service.get_movie_links(tmdb_id)

def get_movie_details(movie_id):
    overseerr_settings = settings.get('overseerr', {})
    tmdb_api_key = os.getenv('TMDB_API_KEY') or overseerr_settings.get('tmdb_api_key', '')
    tmdb_url = f"https://api.themoviedb.org/3/movie/{movie_id}?api_key={tmdb_api_key}&append_to_response=credits,release_dates"

    try:
        response = requests.get(tmdb_url)
        response.raise_for_status()
        movie_data = response.json()

        title = movie_data['title']
        year = movie_data['release_date'][:4]
        runtime = movie_data['runtime']
        duration_hours = runtime // 60
        duration_minutes = runtime % 60
        genres = [genre['name'] for genre in movie_data['genres']]
        description = movie_data['overview']
        tmdb_rating = movie_data['vote_average']

        content_rating = "Not rated"
        for release_date in movie_data['release_dates']['results']:
            if release_date['iso_3166_1'] == 'US':
                certifications = release_date['release_dates']
                if certifications and 'certification' in certifications[0]:
                    content_rating = certifications[0]['certification']
                    break

        trakt_rating = get_trakt_rating(movie_id)
        tmdb_url, trakt_url, imdb_url = fetch_movie_links_for_overlay(movie_id)
        trailer_url = search_youtube_trailer(title, year)

        return {
            "title": title,
            "year": year,
            "duration_hours": duration_hours,
            "duration_minutes": duration_minutes,
            "contentRating": content_rating,
            "genres": genres,
            "tmdb_rating": tmdb_rating,
            "trakt_rating": trakt_rating,
            "description": description,
            "tmdb_url": tmdb_url,
            "trakt_url": trakt_url,
            "imdb_url": imdb_url,
            "trailer_url": trailer_url
        }
    except requests.RequestException as e:
        logger.error(f"Error fetching movie details from TMDb: {e}")
        return None

# Load initial settings
load_settings()

# Register blueprints first
from routes.overseerr_routes import overseerr_bp
from utils.trakt_service import get_local_watched_movies, sync_watched_status, get_movie_ratings, get_trakt_rating

app.register_blueprint(overseerr_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(poster_bp)
app.register_blueprint(trakt_bp)

# Initialize other components
default_poster_manager = init_default_poster_manager(socketio)
app.config['DEFAULT_POSTER_MANAGER'] = default_poster_manager
app.config['initialize_services'] = initialize_services

# Initialize services
initialize_services()

try:
   # Set up movie service for poster manager
   logger.info("Setting up movie service for poster manager...")
   current_service = get_available_service()  # Get current service
   if current_service == 'plex' and PLEX_AVAILABLE and plex:
       logger.info("Using Plex as movie service for poster manager")
       # Store cache manager reference
       plex.cache_manager = app.config['CACHE_MANAGER']
       default_poster_manager.set_movie_service(plex)
   elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE and jellyfin:
       logger.info("Using Jellyfin as movie service for poster manager")
       default_poster_manager.set_movie_service(jellyfin)
   elif current_service == 'emby' and EMBY_AVAILABLE and emby:
       logger.info("Using Emby as movie service for poster manager")
       default_poster_manager.set_movie_service(emby)
except EnvironmentError:
   logger.warning("No media services available during initialization")

# Start the PlaybackMonitor
playback_monitor = PlaybackMonitor(app, interval=10)
app.config['PLAYBACK_MONITOR'] = playback_monitor
playback_monitor.start()

# Flask Routes
@app.route('/')
def index():
    # First check if any services are enabled but not fully configured
    enabled_but_unconfigured = []

    if PLEX_SETTINGS.get('enabled') and not all([
        PLEX_SETTINGS.get('url'),
        PLEX_SETTINGS.get('token'),
        PLEX_SETTINGS.get('movie_libraries')
    ]):
        enabled_but_unconfigured.append('Plex')

    if JELLYFIN_SETTINGS.get('enabled') and not all([
        JELLYFIN_SETTINGS.get('url'),
        JELLYFIN_SETTINGS.get('api_key'),
        JELLYFIN_SETTINGS.get('user_id')
    ]):
        enabled_but_unconfigured.append('Jellyfin')

    if EMBY_SETTINGS.get('enabled') and not all([
        EMBY_SETTINGS.get('url'),
        EMBY_SETTINGS.get('api_key'),
        EMBY_SETTINGS.get('user_id')
    ]):
        enabled_but_unconfigured.append('Emby')

    if enabled_but_unconfigured:
        # Clear any existing flash messages
        session.pop('_flashes', None)
        services_list = ', '.join(enabled_but_unconfigured)
        flash(f"The following services are enabled but not fully configured: {services_list}. Please complete the configuration or disable the service.", "error")
        return redirect('/settings')

    # If no services are configured, always redirect to settings
    if not (PLEX_AVAILABLE or JELLYFIN_AVAILABLE or EMBY_AVAILABLE):
        return redirect('/settings')

    # If we have services configured, show the normal page
    return render_template(
        'index.html',
        homepage_mode=HOMEPAGE_MODE,
        use_links=USE_LINKS,
        use_filter=USE_FILTER,
        use_watch_button=USE_WATCH_BUTTON,
        use_next_button=USE_NEXT_BUTTON,
        mobile_truncation=MOBILE_TRUNCATION,
        settings_disabled=settings.get('system', {}).get('disable_settings', False)
    )

@app.route('/start_loading')
def start_loading():
    if PLEX_AVAILABLE:
        if not os.path.exists(cache_file_path):
            cache_manager = app.config['CACHE_MANAGER']
            socketio.start_background_task(cache_manager.start_cache_build)
            return jsonify({"status": "Cache building started"})
        return jsonify({"status": "Cache already exists"})
    return jsonify({"status": "Loading not required"})

def any_service_available():
    return PLEX_AVAILABLE or JELLYFIN_AVAILABLE or EMBY_AVAILABLE

@app.route('/style/<path:filename>')
def style(filename):
    return send_from_directory('static/style', filename)

@app.route('/js/<path:filename>')
def js(filename):
    return send_from_directory('static/js', filename)

@app.route('/logos/<path:filename>')
def logos(filename):
    return send_from_directory('static/logos', filename)

@app.route('/available_services')
def get_available_services():
    services = []

    # Check Plex - all required fields must be present
    if PLEX_AVAILABLE:
        plex_configured = bool(
            PLEX_SETTINGS.get('url') and
            PLEX_SETTINGS.get('token') and
            PLEX_SETTINGS.get('movie_libraries')
        )
        if plex_configured:
            services.append('plex')

    # Check Jellyfin - all required fields must be present
    if JELLYFIN_AVAILABLE:
        jellyfin_configured = bool(
            JELLYFIN_SETTINGS.get('url') and
            JELLYFIN_SETTINGS.get('api_key') and
            JELLYFIN_SETTINGS.get('user_id')
        )
        if jellyfin_configured:
            services.append('jellyfin')

    # Check Emby - all required fields must be present
    if EMBY_AVAILABLE:
        emby_configured = bool(
            EMBY_SETTINGS.get('url') and
            EMBY_SETTINGS.get('api_key') and
            EMBY_SETTINGS.get('user_id')
        )
        if emby_configured:
            services.append('emby')

    logger.info(f"Available and configured services: {services}")
    return jsonify(services)

@app.route('/current_service')
def get_current_service():
    if 'current_service' not in session or session['current_service'] not in ['plex', 'jellyfin', 'emby']:
        session['current_service'] = get_available_service()

    # Check if the current service is still available
    if (session['current_service'] == 'plex' and not PLEX_AVAILABLE) or \
       (session['current_service'] == 'jellyfin' and not JELLYFIN_AVAILABLE) or \
       (session['current_service'] == 'emby' and not EMBY_AVAILABLE):
        session['current_service'] = get_available_service()

    return jsonify({"service": session['current_service']})

@app.route('/switch_service')
def switch_service():
    # Get list of properly configured services
    available_services = []
    if PLEX_AVAILABLE and bool(PLEX_SETTINGS.get('url') and
                              PLEX_SETTINGS.get('token') and
                              PLEX_SETTINGS.get('movie_libraries')):
        available_services.append('plex')
    if JELLYFIN_AVAILABLE and bool(JELLYFIN_SETTINGS.get('url') and
                                  JELLYFIN_SETTINGS.get('api_key') and
                                  JELLYFIN_SETTINGS.get('user_id')):
        available_services.append('jellyfin')
    if EMBY_AVAILABLE and bool(EMBY_SETTINGS.get('url') and
                              EMBY_SETTINGS.get('api_key') and
                              EMBY_SETTINGS.get('user_id')):
        available_services.append('emby')

    if len(available_services) > 1:
        current = session.get('current_service', 'plex')
        current_index = available_services.index(current)
        next_index = (current_index + 1) % len(available_services)
        new_service = available_services[next_index]
        session['current_service'] = new_service

        # Update poster manager service
        if default_poster_manager:
            new_service_instance = None
            if new_service == 'plex' and PLEX_AVAILABLE and plex:
                logger.info("Switching screensaver to Plex service")
                plex.cache_manager = app.config['CACHE_MANAGER']
                new_service_instance = plex
            elif new_service == 'jellyfin' and JELLYFIN_AVAILABLE and jellyfin:
                logger.info("Switching screensaver to Jellyfin service")
                new_service_instance = jellyfin
            elif new_service == 'emby' and EMBY_AVAILABLE and emby:
                logger.info("Switching screensaver to Emby service")
                new_service_instance = emby

            if new_service_instance:
                # This will handle stopping/restarting screensaver if needed
                default_poster_manager.set_movie_service(new_service_instance)

        return jsonify({"service": new_service})
    else:
        return jsonify({"service": get_available_service()})

@app.route('/api/reinitialize_services')
def reinitialize_services():
    try:
        global emby, EMBY_AVAILABLE, jellyfin, JELLYFIN_AVAILABLE

        # Handle Plex cache refresh
        if PLEX_AVAILABLE and plex:
            plex.refresh_cache()  # This should reload the cache into memory
            if cache_manager:
                cache_manager._init_memory_cache()  # Reload the cache manager

        # Stop Emby if it exists
        if EMBY_AVAILABLE and emby:
            emby.stop_cache_updater()
            emby = None
            EMBY_AVAILABLE = False

        # Stop Jellyfin if it exists
        if JELLYFIN_AVAILABLE and jellyfin:
            jellyfin.stop_cache_updater()
            jellyfin = None
            JELLYFIN_AVAILABLE = False

        # Reinitialize all services
        if initialize_services():
            return jsonify({"status": "success"})
        else:
            return jsonify({"error": "Failed to reinitialize services"}), 500
    except Exception as e:
        logger.error(f"Error reinitializing services: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/random_movie')
def random_movie():
   current_service = session.get('current_service', get_available_service())
   global all_plex_unwatched_movies, loading_in_progress, movies_loaded_from_cache
   watch_status = request.args.get('watch_status', 'unwatched')

   try:
       if current_service == 'plex' and PLEX_AVAILABLE:
           if watch_status == 'unwatched':
               if not all_plex_unwatched_movies:
                   initialize_cache()
               if loading_in_progress:
                   return jsonify({"loading_in_progress": True}), 202
               if not all_plex_unwatched_movies:
                   return jsonify({"error": "No unwatched movies available"}), 404
               movie_data = random.choice(all_plex_unwatched_movies)
           else:
               movie_data = plex.filter_movies(watch_status=watch_status)
               if not movie_data:
                   return jsonify({"error": "No movies available"}), 404

       elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
           movie_data = jellyfin.filter_movies(watch_status=watch_status)
       elif current_service == 'emby' and EMBY_AVAILABLE:
           movie_data = emby.filter_movies(watch_status=watch_status)
       else:
           return jsonify({"error": "No available media service"}), 400

       if movie_data:
           movie_data = enrich_movie_data(movie_data)
           return jsonify({
               "service": current_service,
               "movie": movie_data,
               "cache_loaded": movies_loaded_from_cache,
               "loading_in_progress": loading_in_progress
           })
       else:
           return jsonify({"error": "No movie found"}), 404
   except Exception as e:
       logger.error(f"Error in random_movie: {str(e)}", exc_info=True)
       return jsonify({"error": str(e)}), 500

@app.route('/next_movie')
def next_movie():
   current_service = session.get('current_service', get_available_service())
   genres = request.args.get('genres', '').split(',') if request.args.get('genres') else None
   years = request.args.get('years', '').split(',') if request.args.get('years') else None
   pg_ratings = request.args.get('pg_ratings', '').split(',') if request.args.get('pg_ratings') else None
   watch_status = request.args.get('watch_status', 'unwatched')

   try:
       if current_service == 'plex' and PLEX_AVAILABLE:
           movie_data = plex.get_next_movie(genres, years, pg_ratings, watch_status)
       elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
           movie_data = jellyfin.filter_movies(genres, years, pg_ratings, watch_status)
       elif current_service == 'emby' and EMBY_AVAILABLE:
           movie_data = emby.filter_movies(genres, years, pg_ratings, watch_status)
       else:
           return jsonify({"error": "No available media service"}), 400

       if movie_data:
           movie_data = enrich_movie_data(movie_data)
           return jsonify({
               "service": current_service,
               "movie": movie_data
           })
       else:
           return jsonify({"error": "No movies found matching the criteria"}), 204
   except Exception as e:
       logger.error(f"Error in next_movie: {str(e)}")
       return jsonify({"error": str(e)}), 500

@app.route('/filter_movies')
def filter_movies():
   current_service = session.get('current_service', get_available_service())
   genres = request.args.get('genres', '').split(',') if request.args.get('genres') else None
   years = request.args.get('years', '').split(',') if request.args.get('years') else None
   pg_ratings = request.args.get('pg_ratings', '').split(',') if request.args.get('pg_ratings') else None
   watch_status = request.args.get('watch_status', 'unwatched')

   try:
       if current_service == 'plex' and PLEX_AVAILABLE:
           movie_data = plex.filter_movies(genres, years, pg_ratings, watch_status)
       elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
           movie_data = jellyfin.filter_movies(genres, years, pg_ratings, watch_status)
       elif current_service == 'emby' and EMBY_AVAILABLE:
           movie_data = emby.filter_movies(genres, years, pg_ratings, watch_status)
       else:
           return jsonify({"error": "No available media service"}), 400

       if movie_data:
           movie_data = enrich_movie_data(movie_data)
           return jsonify({
               "service": current_service,
               "movie": movie_data
           })
       else:
           return jsonify({"error": "No movies found matching the filter"}), 204
   except Exception as e:
       logger.error(f"Error in filter_movies: {str(e)}")
       return jsonify({"error": str(e)}), 500

@app.route('/get_genres')
def get_genres():
    current_service = session.get('current_service', get_available_service())
    watch_status = request.args.get('watch_status', 'unwatched')
    try:
        logger.debug(f"Fetching genres for service: {current_service}")
        if current_service == 'plex' and PLEX_AVAILABLE:
            genres_list = plex.get_genres(watch_status)
            logger.info(f"Found genres: {genres_list}")
            return jsonify(genres_list)
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            genres = jellyfin.get_genres()
            return jsonify(genres)
        elif current_service == 'emby' and EMBY_AVAILABLE:
            genres = emby.get_genres()
            return jsonify(genres)
        else:
            return jsonify({"error": "No available media service"}), 400
    except Exception as e:
        logger.error(f"Error in get_genres: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/get_years')
def get_years():
    current_service = session.get('current_service', get_available_service())
    watch_status = request.args.get('watch_status', 'unwatched')
    try:
        logger.debug(f"Fetching years for service: {current_service}")
        if current_service == 'plex' and PLEX_AVAILABLE:
            years_list = plex.get_years(watch_status)
            logger.info(f"Found years: {years_list}")
            return jsonify(years_list)
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            years = jellyfin.get_years()
            return jsonify(years)
        elif current_service == 'emby' and EMBY_AVAILABLE:
            years = emby.get_years()
            return jsonify(years)
        else:
            return jsonify({"error": "No available media service"}), 400
    except Exception as e:
        logger.error(f"Error in get_years: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/get_pg_ratings')
def get_pg_ratings():
    current_service = session.get('current_service', get_available_service())
    watch_status = request.args.get('watch_status', 'unwatched')
    try:
        if current_service == 'plex' and PLEX_AVAILABLE:
            ratings = plex.get_pg_ratings(watch_status)
            return jsonify(ratings)
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            ratings = jellyfin.get_pg_ratings()
            return jsonify(ratings)
        elif current_service == 'emby' and EMBY_AVAILABLE:
            ratings = emby.get_pg_ratings()
            return jsonify(ratings)
        else:
            return jsonify({"error": "No available media service"}), 400
    except Exception as e:
        logger.error(f"Error in get_pg_ratings: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/clients')
def clients():
    current_service = session.get('current_service', get_available_service())
    try:
        if current_service == 'plex' and PLEX_AVAILABLE:
            client_list = plex.get_clients()
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            client_list = jellyfin.get_clients()
        elif current_service == 'emby' and EMBY_AVAILABLE:
            client_list = emby.get_clients()
        else:
            return jsonify({"error": "No available media service"}), 400
        return jsonify(client_list)
    except Exception as e:
        logger.error(f"Error in clients: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/play_movie/<client_id>')
def play_movie(client_id):
    movie_id = request.args.get('movie_id')
    if not movie_id:
        return jsonify({"error": "No movie selected"}), 400
    current_service = session.get('current_service', get_available_service())
    try:
        if current_service == 'plex' and PLEX_AVAILABLE:
            result = plex.play_movie(movie_id, client_id)
            if result.get("status") == "playing":
                movie_data = plex.get_movie_by_id(movie_id)
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            result = jellyfin.play_movie(movie_id, client_id)
            if result.get("status") == "playing":
                movie_data = jellyfin.get_movie_by_id(movie_id)
        elif current_service == 'emby' and EMBY_AVAILABLE:
            result = emby.play_movie(movie_id, client_id)
            if result.get("status") == "playing":
                movie_data = emby.get_movie_by_id(movie_id)
        else:
            return jsonify({"error": "No available media service"}), 400

        # Only set current movie if we have result["username"] from the service
        if result.get("status") == "playing" and movie_data and result.get("username"):
            set_current_movie(movie_data, current_service, username=result.get("username"))
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error in play_movie: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/devices')
def devices():
    """Returns list of all available TV devices"""
    devices = []
    # Check Apple TV (still needed)
    apple_tv_id_env = os.getenv('APPLE_TV_ID')
    if apple_tv_id_env:
        devices.append({
            "name": "apple_tv",
            "displayName": "Apple TV",
            "env_controlled": True
        })
    elif APPLE_TV_SETTINGS.get('enabled') and APPLE_TV_SETTINGS.get('id'):
        devices.append({
            "name": "apple_tv",
            "displayName": "Apple TV",
            "env_controlled": False
        })
    # Add all configured TVs
    tv_instances = settings.get('clients', {}).get('tvs', {}).get('instances', {})
    for tv_id, tv in tv_instances.items():
        # Only add TVs that exist and are enabled
        if tv and not isinstance(tv, str) and tv.get('enabled', True):
            try:
                # Format TV name from instance ID
                words = tv_id.split('_')
                display_name = ' '.join(word.capitalize() for word in words)

                devices.append({
                    "name": tv_id,
                    "displayName": display_name,  # Use formatted name
                    "env_controlled": False,
                    "type": tv.get('type'),
                    "ip": tv.get('ip'),
                    "mac": tv.get('mac')
                })
            except Exception as e:
                logger.error(f"Error adding TV {tv_id} to devices list: {e}")
    logger.debug(f"Available devices: {devices}")
    return jsonify(devices)

@app.route('/turn_on_device/<device>')
def turn_on_device(device):
    if device == "apple_tv":
        try:
            device_id = APPLE_TV_SETTINGS.get('id') or os.getenv('APPLE_TV_ID')
            if not device_id:
                return jsonify({"error": "Apple TV ID not configured"}), 400

            from utils.appletv_discovery import launch_streaming_app
            result = launch_streaming_app(device_id)
            return jsonify(result)

        except Exception as e:
            logger.error(f"Error turning on Apple TV: {str(e)}")
            return jsonify({"error": f"Failed to turn on Apple TV: {str(e)}"}), 500

    else:  # TV devices
        try:
            # Get TV controller
            tv = TVFactory.get_tv_controller()
            if not tv:
                return jsonify({"error": "TV not configured or unsupported type"}), 400

            current_service = session.get('current_service', get_available_service())

            async def launch_tv():
                try:
                    # Turn on TV and launch appropriate app
                    success = await tv.turn_on(current_service)
                    if success:
                        return {"status": "success", "message": f"{tv.get_name()} turned on and {current_service} launched"}
                    else:
                        return {"status": "error", "message": "Failed to turn on TV or launch app"}
                except Exception as e:
                    logger.error(f"Failed to launch TV or app: {e}")
                    return {"status": "error", "message": str(e)}

            return jsonify(asyncio.run(launch_tv()))

        except Exception as e:
            return jsonify({"error": f"Failed to control TV: {str(e)}"}), 500

@app.route('/debug_service')
def debug_service():
    """Return debug information for the current media service"""
    current_service = session.get('current_service', get_available_service())
    try:
        if current_service == 'plex' and PLEX_AVAILABLE:
            update_cache_status()

            # Force reload all movies count from disk
            all_movies_count = 0
            if os.path.exists(cache_manager.all_movies_cache_path):
                try:
                    with open(cache_manager.all_movies_cache_path, 'r') as f:
                        all_movies = json.load(f)
                        all_movies_count = len(all_movies)
                except Exception as e:
                    logger.error(f"Error reading all movies cache: {e}")

            cached_movies = len(cache_manager.get_cached_movies()) if cache_manager else 0

            plex_url = PLEX_SETTINGS.get('url') or os.getenv('PLEX_URL')
            movie_libraries = PLEX_SETTINGS.get('movie_libraries') or os.getenv('PLEX_MOVIE_LIBRARIES', '')

            if isinstance(movie_libraries, list):
                movie_libraries = ','.join(movie_libraries)

            return jsonify({
                "service": "plex",
                "total_movies": all_movies_count,
                "total_unwatched_movies": cached_movies,
                "cached_movies": cached_movies,
                "loaded_from_cache": movies_loaded_from_cache,
                "plex_url": plex_url,
                "movies_library_name": movie_libraries,
                "cache_file_exists": os.path.exists(cache_file_path)
            })

        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            try:
                # Get total movies from cache
                cache_file = '/app/data/jellyfin_all_movies.json'
                if os.path.exists(cache_file):
                    with open(cache_file, 'r') as f:
                        all_movies = json.load(f)
                    total_movies = len(all_movies)
                else:
                    total_movies = 0

                # Get unwatched count directly from Jellyfin API
                unwatched_count = jellyfin.get_unwatched_count() if jellyfin else 0

                return jsonify({
                    "service": "jellyfin",
                    "total_movies": total_movies,
                    "total_unwatched_movies": unwatched_count,
                    "cache_file_exists": os.path.exists(cache_file),
                    "jellyfin_url": JELLYFIN_SETTINGS.get('url') or os.getenv('JELLYFIN_URL')
                })
            except Exception as e:
                logger.error(f"Error getting Jellyfin debug info: {str(e)}")
                return jsonify({
                    "service": "jellyfin",
                    "error": str(e)
                }), 500

        elif current_service == 'emby' and EMBY_AVAILABLE:
            try:
                # Get total movies from cache
                cache_file = '/app/data/emby_all_movies.json'
                if os.path.exists(cache_file):
                    with open(cache_file, 'r') as f:
                        all_movies = json.load(f)
                    total_movies = len(all_movies)
                else:
                    total_movies = 0

                # Get unwatched count directly from Emby API
                unwatched_count = emby.get_unwatched_count() if emby else 0

                return jsonify({
                    "service": "emby",
                    "total_movies": total_movies,
                    "total_unwatched_movies": unwatched_count,
                    "cache_file_exists": os.path.exists(cache_file),
                    "emby_url": EMBY_SETTINGS.get('url') or os.getenv('EMBY_URL')
                })
            except Exception as e:
                logger.error(f"Error getting Emby debug info: {str(e)}")
                return jsonify({
                    "service": "emby",
                    "error": str(e)
                }), 500
        else:
            return jsonify({"error": "No available media service"}), 400
    except Exception as e:
        logger.error(f"Error in debug_service: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route('/resync_cache')
def trigger_resync():
    resync_cache()
    return jsonify({"status": "Cache resync completed"})

@app.route('/trakt_watched_status')
def trakt_watched_status():
    watched_movies = get_local_watched_movies()
    return jsonify(watched_movies)

@app.route('/sync_trakt_watched')
def sync_trakt_watched():
    sync_watched_status()
    return jsonify({"status": "Trakt watched status synced"})

@app.route('/api/movie_ratings/<int:tmdb_id>')
def movie_ratings(tmdb_id):
    try:
        ratings = get_movie_ratings(tmdb_id)
        return jsonify(ratings)
    except Exception as e:
        logger.error(f"Error fetching movie ratings: {str(e)}")
        return jsonify({"error": "Failed to fetch ratings"}), 500

@app.route('/api/batch_movie_ratings', methods=['POST'])
def batch_movie_ratings():
    movie_ids = request.json.get('movie_ids', [])
    ratings = {}
    for movie_id in movie_ids:
        ratings[movie_id] = get_movie_ratings(movie_id)
    return jsonify(ratings)

@app.route('/api/youtube_trailer')
def youtube_trailer():
    title = request.args.get('title')
    year = request.args.get('year')
    if not title or not year:
        return "Missing title or year parameter", 400

    trailer_url = search_youtube_trailer(title, year)
    return trailer_url

@app.route('/is_movie_in_plex/<int:tmdb_id>')
def is_movie_in_plex(tmdb_id):
    if not PLEX_AVAILABLE:
        return jsonify({"available": False})

    try:
        all_plex_movies = cache_manager.get_all_plex_movies()
        is_available = any(
            str(movie.get('tmdb_id')) == str(tmdb_id)
            for movie in all_plex_movies
        )
        return jsonify({"available": is_available})
    except Exception as e:
        logger.error(f"Error checking Plex availability: {str(e)}")
        return jsonify({"available": False, "error": str(e)})

@app.route('/api/get_plex_id/<tmdb_id>')
def get_plex_id(tmdb_id):
    try:
        all_movies = cache_manager.get_all_plex_movies()
        for movie in all_movies:
            if str(movie.get('tmdb_id')) == str(tmdb_id):
                return jsonify({"plexId": movie['id']})  # Return the Plex ratingKey as plexId
        
        # If we get here, we didn't find the movie
        logger.warning(f"Movie with TMDb ID {tmdb_id} not found in Plex")
        return jsonify({"error": "Movie not found in Plex"}), 404
        
    except Exception as e:
        logger.error(f"Error getting Plex ID: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/get_jellyfin_id/<tmdb_id>')
def get_jellyfin_id(tmdb_id):
    try:
        if not JELLYFIN_AVAILABLE or not jellyfin:
            return jsonify({"error": "Jellyfin not available"}), 404

        cache_path = '/app/data/jellyfin_all_movies.json'
        if not os.path.exists(cache_path):
            return jsonify({"error": "Jellyfin cache not found"}), 404

        with open(cache_path, 'r') as f:
            all_movies = json.load(f)

        for movie in all_movies:
            if str(movie.get('tmdb_id')) == str(tmdb_id):
                return jsonify({"jellyfinId": movie['jellyfin_id']})

        return jsonify({"error": "Movie not found in Jellyfin"}), 404

    except Exception as e:
        logger.error(f"Error getting Jellyfin ID: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/get_emby_id/<tmdb_id>')
def get_emby_id(tmdb_id):
    try:
        if not EMBY_AVAILABLE or not emby:
            return jsonify({"error": "Emby not available"}), 404

        cache_path = '/app/data/emby_all_movies.json'
        if not os.path.exists(cache_path):
            return jsonify({"error": "Emby cache not found"}), 404

        with open(cache_path, 'r') as f:
            all_movies = json.load(f)

        for movie in all_movies:
            if str(movie.get('tmdb_id')) == str(tmdb_id):
                return jsonify({"embyId": movie['emby_id']})

        return jsonify({"error": "Movie not found in Emby"}), 404

    except Exception as e:
        logger.error(f"Error getting Emby ID: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/tv/scan/<tv_type>')
def scan_for_tv(tv_type):
    """Scan for TVs of specified type"""
    try:
        # Import and use the appropriate discovery class
        from utils.tv.base import TVDiscoveryFactory

        discovery = TVDiscoveryFactory.get_discovery(tv_type)
        if not discovery:
            return jsonify({
                "error": f"Unsupported TV type: {tv_type}",
                "devices": []
            }), 400

        # Run the scan
        devices = discovery.scan_network()

        return jsonify({
            "devices": devices,
            "found": len(devices) > 0
        })

    except Exception as e:
        logger.error(f"Error scanning for {tv_type} TVs: {str(e)}")
        return jsonify({
            "error": str(e),
            "devices": []
        }), 500

@app.route('/api/tv/test/<tv_id>')
def test_tv_connection(tv_id):
    """Test connection to a specific TV"""
    try:
        logger.info(f"Starting TV connection test for device ID: {tv_id}")

        controller = TVFactory.get_tv_controller(tv_id)
        if not controller:
            logger.error(f"Failed to get TV controller for ID: {tv_id}")
            return jsonify({"error": "TV not found"}), 404

        logger.info(f"Got controller for {controller.manufacturer} {controller.tv_type} TV at IP: {controller.ip}")

        # Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            logger.info(f"Starting availability check for {controller.ip}...")
            is_available = loop.run_until_complete(controller.is_available())
            logger.info(f"TV connection test complete for {controller.ip} - Available: {is_available}")

            if not is_available:
                logger.warning(f"TV at {controller.ip} is not available. Check TV power state and network connection.")

            return jsonify({"success": is_available})
        finally:
            loop.close()

    except Exception as e:
        logger.error(f"Error during TV connection test: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/api/appletv/scan')
def scan_for_appletv_devices():
    """Scan for Apple TVs on the network"""
    try:
        devices = scan_for_appletv()
        return jsonify({
            'devices': devices,
            'found': len(devices) > 0
        })
    except Exception as e:
        logger.error(f"Error scanning for Apple TVs: {str(e)}")
        return jsonify({
            'error': str(e),
            'devices': []
        }), 500

@app.route('/api/appletv/pair/<device_id>')
def start_appletv_pairing(device_id):
    """Start pairing process with Apple TV"""
    try:
        result = pair_appletv(device_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error starting pairing: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/appletv/pin/<device_id>', methods=['POST'])
def submit_appletv_pin(device_id):
    """Submit PIN for Apple TV pairing"""
    try:
        pin = request.json.get('pin')
        if not pin:
            return jsonify({
                'status': 'error',
                'message': 'PIN is required'
            }), 400

        result = submit_pin(device_id, pin)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error submitting PIN: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/appletv/cancel/<device_id>')
def cancel_appletv_pairing(device_id):
    """Cancel ongoing pairing process"""
    try:
        # Access the global _pairing_process from appletv_discovery
        from utils.appletv_discovery import _pairing_process
        if _pairing_process:
            _pairing_process.close()
            return jsonify({
                'status': 'success',
                'message': 'Pairing cancelled'
            })
        return jsonify({
            'status': 'success',
            'message': 'No active pairing to cancel'
        })
    except Exception as e:
        logger.error(f"Error cancelling pairing: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/appletv/check_credentials', methods=['POST'])
def check_appletv_credentials():
    try:
        data = request.get_json()
        device_id = data.get('device_id')

        if not device_id:
            return jsonify({"error": "No device ID provided"}), 400

        from utils.appletv_discovery import check_credentials
        has_credentials = check_credentials(device_id)

        return jsonify({"has_credentials": has_credentials})

    except Exception as e:
        logger.error(f"Error checking Apple TV credentials: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/settings')
def settings_page():
    return render_template('settings.html')

@app.route('/setup_status')
def setup_status():
    return jsonify({
        'services_configured': bool(PLEX_AVAILABLE or JELLYFIN_AVAILABLE or EMBY_AVAILABLE),
        'plex_available': PLEX_AVAILABLE,
        'jellyfin_available': JELLYFIN_AVAILABLE,
        'emby_available': EMBY_AVAILABLE
    })

@app.route('/api/service_status')
def service_status():
    """Return the current status of media services"""
    return jsonify({
        'services_configured': bool(PLEX_AVAILABLE or JELLYFIN_AVAILABLE or EMBY_AVAILABLE),
        'plex_available': PLEX_AVAILABLE,
        'jellyfin_available': JELLYFIN_AVAILABLE,
        'emby_available': EMBY_AVAILABLE
    })

@app.route('/api/plex/get_token', methods=['POST'])
def get_plex_token():
    try:
        client_id = str(uuid.uuid4())
        headers = {
            'X-Plex-Client-Identifier': client_id,
            'X-Plex-Product': 'Movie Roulette',
            'X-Plex-Version': '1.0',
            'X-Plex-Device': 'Web',
            'X-Plex-Device-Name': 'Movie Roulette Web Client',
            'X-Plex-Platform': 'Web',
            'X-Plex-Platform-Version': '1.0'
        }

        # Initialize the PIN login
        pin_login = MyPlexPinLogin(headers=headers)

        # Store in global dict
        _plex_pin_logins[client_id] = pin_login

        logger.info("Plex auth initiated with PIN: ****")

        return jsonify({
            "auth_url": "https://plex.tv/link",
            "pin": pin_login.pin,
            "client_id": client_id
        })
    except Exception as e:
        logger.error(f"Error in get_plex_token: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route('/api/plex/check_auth/<client_id>')
def check_plex_auth(client_id):
    try:
        # Get the pin_login instance from global dict
        pin_login = _plex_pin_logins.get(client_id)

        if not pin_login:
            logger.warning("No PIN login instance found for this client")
            return jsonify({"token": None})

        if pin_login.checkLogin():
            token = pin_login.token
            logger.info("Successfully retrieved Plex token")
            # Clean up
            del _plex_pin_logins[client_id]
            return jsonify({"token": token})

        return jsonify({"token": None})

    except Exception as e:
        logger.error(f"Error in check_plex_auth: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route('/api/plex/libraries', methods=['POST'])
def get_plex_libraries():
    try:
        data = request.json
        plex_url = data.get('plex_url')
        plex_token = data.get('plex_token')

        if not plex_url or not plex_token:
            return jsonify({"error": "Missing Plex URL or token"}), 400

        from plexapi.server import PlexServer
        server = PlexServer(plex_url, plex_token)

        libraries = [
            section.title
            for section in server.library.sections()
            if section.type == 'movie'
        ]

        return jsonify({"libraries": libraries})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/jellyfin/auth', methods=['POST'])
def jellyfin_auth():
    try:
        data = request.json
        server_url = data.get('server_url')
        username = data.get('username')
        password = data.get('password')

        if not all([server_url, username, password]):
            return jsonify({"error": "Missing required fields"}), 400

        # Clean up the server URL
        if server_url.endswith('/'):
            server_url = server_url[:-1]

        # First, get the authentication header
        auth_data = {
            "Username": username,
            "Pw": password
        }

        # Make the auth request
        auth_response = requests.post(
            f"{server_url}/Users/AuthenticateByName",
            json=auth_data,
            headers={
                "X-Emby-Authorization": 'MediaBrowser Client="Movie Roulette", Device="Script", DeviceId="Script", Version="1.0.0"'
            }
        )

        if not auth_response.ok:
            return jsonify({"error": "Invalid credentials"}), 401

        auth_result = auth_response.json()

        return jsonify({
            "api_key": auth_result['AccessToken'],
            "user_id": auth_result['User']['Id']
        })

    except Exception as e:
        logger.error(f"Error in jellyfin_auth: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route('/api/plex/users', methods=['POST'])
def get_plex_users():
    try:
        data = request.json
        plex_url = data.get('plex_url')
        plex_token = data.get('plex_token')
        if not plex_url or not plex_token:
            return jsonify({"error": "Missing Plex URL or token"}), 400
        from plexapi.server import PlexServer
        server = PlexServer(plex_url, plex_token)
        # Get all users who have access to the server - use username instead of title
        users = [user.username for user in server.myPlexAccount().users()]
        # Add the admin user's username
        users.insert(0, server.myPlexAccount().username)
        return jsonify({"users": users})
    except Exception as e:
        logger.error(f"Error fetching Plex users: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/jellyfin/users', methods=['POST'])
def get_jellyfin_users():
    try:
        data = request.json
        jellyfin_url = data.get('jellyfin_url')
        api_key = data.get('api_key')

        if not jellyfin_url or not api_key:
            return jsonify({"error": "Missing Jellyfin URL or API key"}), 400

        # Clean up the server URL
        if jellyfin_url.endswith('/'):
            jellyfin_url = jellyfin_url[:-1]

        # Get all users
        response = requests.get(
            f"{jellyfin_url}/Users",
            headers={
                'X-MediaBrowser-Token': api_key
            }
        )

        if not response.ok:
            return jsonify({"error": "Failed to fetch users"}), response.status_code

        users = [user['Name'] for user in response.json()]
        return jsonify({"users": users})
    except Exception as e:
        logger.error(f"Error fetching Jellyfin users: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/emby/connect/auth', methods=['POST'])
def emby_connect_auth():
    """Handle Emby Connect authentication"""
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')

        if not all([username, password]):
            return jsonify({"error": "Username and password are required"}), 400

        # Initialize EmbyService without URL for Connect auth
        emby = EmbyService()
        auth_result = emby.authenticate_with_connect(username, password)
        return jsonify(auth_result)
    except Exception as e:
        logger.error(f"Error in Emby Connect auth: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/emby/connect/check', methods=['POST'])
def emby_connect_check():
    """Check Emby Connect authentication status"""
    try:
        data = request.json
        server_url = data.get('server_url')
        connect_token = data.get('connect_token')

        if not server_url or not connect_token:
            return jsonify({"error": "Server URL and Connect token are required"}), 400

        emby = EmbyService(url=server_url)
        auth_result = emby.check_connect_auth(connect_token)
        return jsonify(auth_result)
    except Exception as e:
        logger.error(f"Error checking Emby Connect auth: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/emby/connect/select_server', methods=['POST'])  # Make sure POST is allowed
def emby_select_server():
    try:
        data = request.json
        server_info = data.get('server')
        connect_user_id = data.get('connect_user_id')

        if not all([server_info, connect_user_id]):
            return jsonify({"error": "Server info and connect user ID required"}), 400

        # Initialize EmbyService with selected server URL
        server_url = server_info.get('url')  # Use the correct field from server_info
        if not server_url:
            return jsonify({"error": "Missing server URL"}), 400

        emby = EmbyService(url=server_url)

        # Exchange Connect access key for server token
        exchange_headers = {
            'X-Emby-Token': server_info.get('access_key'),  # Use access_key from server_info
            'X-Emby-Authorization': ('MediaBrowser Client="Movie Roulette",'
                                   'Device="Movie Roulette",'
                                   'DeviceId="MovieRoulette",'
                                   'Version="1.0.0"')
        }

        exchange_response = requests.get(
            f"{server_url}/Connect/Exchange?format=json&ConnectUserId={connect_user_id}",
            headers=exchange_headers
        )
        exchange_response.raise_for_status()
        exchange_data = exchange_response.json()

        return jsonify({
            "status": "success",
            "api_key": exchange_data['AccessToken'],
            "user_id": exchange_data['LocalUserId'],
            "server_url": server_url
        })
    except Exception as e:
        logger.error(f"Error selecting Emby server: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/emby/auth', methods=['POST'])
def emby_direct_auth():
    """Handle direct Emby authentication"""
    try:
        data = request.json
        server_url = data.get('server_url')
        username = data.get('username')
        password = data.get('password')

        if not all([server_url, username, password]):
            return jsonify({"error": "Server URL, username, and password are required"}), 400

        emby = EmbyService(url=server_url)
        auth_result = emby.authenticate(username, password)

        return jsonify(auth_result)
    except Exception as e:
        logger.error(f"Error in Emby direct auth: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/emby/users', methods=['POST'])
def get_emby_users():
    try:
        data = request.json
        emby_url = data.get('emby_url')
        api_key = data.get('api_key')

        if not emby_url or not api_key:
            return jsonify({"error": "Missing Emby URL or API key"}), 400

        emby = EmbyService(url=emby_url, api_key=api_key)
        users = emby.get_users()
        return jsonify({"users": users})
    except Exception as e:
        logger.error(f"Error fetching Emby users: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/search_person')
def search_person_api():
    """Search for a person and return their details with TMDb and IMDb links"""
    name = request.args.get('name')
    if not name:
        return jsonify({"error": "Name parameter is required"}), 400

    try:
        person = tmdb_service.search_person(name)
        if person:
            # Get the TMDb and IMDb links
            tmdb_url, imdb_url = tmdb_service.get_person_links(person['id'])

            return jsonify({
                **person,
                'links': {
                    'tmdb': tmdb_url,
                    'imdb': imdb_url
                }
            })
        return jsonify({"error": "Person not found"}), 404
    except Exception as e:
        logger.error(f"Error searching for person: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/movies_by_person')
def get_movies_by_person():
    person_id = request.args.get('person_id')
    person_type = request.args.get('person_type', 'actor')

    if not person_id:
        return jsonify({"error": "Person ID is required"}), 400

    try:
        # Use TMDb service directly
        movies = tmdb_service.get_person_movies(person_id)
        if movies:
            logger.debug(f"Before filtering - Total movies: {len(movies)}")
            logger.debug("Departments and jobs:")
            for m in movies:
                logger.debug(f"Department: {m.get('department')}, Job: {m.get('job')}")

            # Filter movies by department
            if person_type == 'director':
                movies = [m for m in movies if m.get('department') == 'Directing']
                logger.debug(f"Found {len(movies)} directing credits")
            elif person_type == 'writer':
                movies = [m for m in movies if m.get('department') == 'Writing']
                logger.debug(f"Found {len(movies)} writing credits")
            elif person_type == 'actor':
                movies = [m for m in movies if m.get('department') == 'Acting']
                logger.debug(f"Found {len(movies)} acting credits")

            return jsonify({
                "credits": {
                    "cast" if person_type == 'actor' else 'crew': movies
                }
            })
        return jsonify({"error": "No movies found"}), 404
    except Exception as e:
        logger.error(f"Error getting person movies: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/person_details_with_external_ids/<person_id>')
def get_person_details_with_external_ids(person_id):
    details = tmdb_service.get_person_details_with_external_ids(person_id)
    if details:
        return jsonify(details)
    return jsonify({'error': 'Person not found'}), 404

@app.route('/api/movie_details/<movie_id>')
def movie_details(movie_id):
    """Get movie details using centralized TMDB service"""
    try:
        # Import at the top of the file with other imports
        from utils.tmdb_service import tmdb_service

        movie_data = tmdb_service.get_movie_details(movie_id)
        if not movie_data:
            return jsonify({"error": "Movie not found"}), 404

        credits = tmdb_service.get_movie_credits(movie_id)
        if credits:
            movie_data['credits'] = credits

        title = movie_data['title']
        year = movie_data['release_date'][:4] if movie_data.get('release_date') else ''
        runtime = movie_data.get('runtime', 0)
        duration_hours = runtime // 60
        duration_minutes = runtime % 60
        genres = [genre['name'] for genre in movie_data.get('genres', [])]
        description = movie_data.get('overview', '')
        tmdb_rating = movie_data.get('vote_average', 0)

        content_rating = "Not rated"
        if 'release_dates' in movie_data:
            for release_date in movie_data['release_dates'].get('results', []):
                if release_date['iso_3166_1'] == 'US':
                    certifications = release_date.get('release_dates', [])
                    if certifications and 'certification' in certifications[0]:
                        content_rating = certifications[0]['certification']
                        break

        trakt_rating = get_trakt_rating(movie_id)
        tmdb_url, trakt_url, imdb_url = tmdb_service.get_movie_links(movie_id)
        trailer_url = search_youtube_trailer(title, year)

        formatted_data = {
            "title": title,
            "year": year,
            "duration_hours": duration_hours,
            "duration_minutes": duration_minutes,
            "contentRating": content_rating,
            "genres": genres,
            "tmdb_rating": tmdb_rating,
            "trakt_rating": trakt_rating,
            "description": description,
            "tmdb_url": tmdb_url,
            "trakt_url": trakt_url,
            "imdb_url": imdb_url,
            "trailer_url": trailer_url,
            "credits": credits
        }

        return jsonify(formatted_data)
    except Exception as e:
        logger.error(f"Error getting movie details: {e}", exc_info=True)
        return jsonify({"error": "Failed to fetch movie details"}), 500

@app.route('/api/movie_external_ids/<person_id>')
def get_person_external_ids(person_id):
    """Get external IDs for a person"""
    try:
        url = f"person/{person_id}/external_ids"
        external_ids = tmdb_service._make_request(url)
        if external_ids:
            return jsonify(external_ids)
        return jsonify({"error": "No external IDs found"}), 404
    except Exception as e:
        logger.error(f"Error getting external IDs: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/is_movie_in_jellyfin/<int:tmdb_id>')
def is_movie_in_jellyfin(tmdb_id):
    if not JELLYFIN_AVAILABLE:
        return jsonify({"available": False})

    try:
        cache_path = '/app/data/jellyfin_all_movies.json'
        if os.path.exists(cache_path):
            with open(cache_path, 'r') as f:
                all_jellyfin_movies = json.load(f)

            is_available = any(
                str(movie.get('tmdb_id')) == str(tmdb_id)
                for movie in all_jellyfin_movies
            )
            return jsonify({"available": is_available})
    except Exception as e:
        logger.error(f"Error checking Jellyfin availability: {str(e)}")
        return jsonify({"available": False})

@app.route('/is_movie_in_emby/<int:tmdb_id>')
def is_movie_in_emby(tmdb_id):
    if not EMBY_AVAILABLE:
        return jsonify({"available": False})

    try:
        cache_path = '/app/data/emby_all_movies.json'
        if os.path.exists(cache_path):
            with open(cache_path, 'r') as f:
                all_emby_movies = json.load(f)

            is_available = any(
                str(movie.get('tmdb_id')) == str(tmdb_id)
                for movie in all_emby_movies
            )
            return jsonify({"available": is_available})
    except Exception as e:
        logger.error(f"Error checking Emby availability: {str(e)}")
        return jsonify({"available": False})

from utils.version import VERSION

VERSION_FILE = '/app/data/version_info.json'

def get_version_info():
    if os.path.exists(VERSION_FILE):
        try:
            with open(VERSION_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {"last_version_seen": VERSION}

def save_version_info(info):
    os.makedirs(os.path.dirname(VERSION_FILE), exist_ok=True)
    with open(VERSION_FILE, 'w') as f:
        json.dump(info, f)

@app.route('/api/check_version')
def check_version():
    try:
        version_info = get_version_info()
        manual_check = request.args.get('manual', 'false') == 'true'
        response = requests.get(
            "https://api.github.com/repos/sahara101/Movie-Roulette/releases/latest",
            headers={'Accept': 'application/vnd.github.v3+json'}
        )
        if response.ok:
            release = response.json()
            latest_version = release['tag_name'].lstrip('v')
            # Compare version numbers properly
            current_parts = [int(x) for x in VERSION.split('.')]
            latest_parts = [int(x) for x in latest_version.split('.')]
            is_newer = latest_parts > current_parts
            show_popup = is_newer and latest_version != version_info["last_version_seen"]
            if manual_check or show_popup:
                version_info["last_version_seen"] = latest_version
                save_version_info(version_info)
            return jsonify({
                'update_available': is_newer,
                'current_version': VERSION,
                'latest_version': latest_version,
                'changelog': release['body'],
                'download_url': release['html_url'],
                'show_popup': show_popup or manual_check
            })
        else:
            # Add return statement for non-OK responses
            return jsonify({'error': 'Failed to check version: GitHub API returned error'}), response.status_code
    except Exception as e:
        print(f"Error checking version: {e}")
        return jsonify({'error': 'Failed to check version'}), 500

@app.route('/api/dismiss_update')
def dismiss_update():
    try:
        with open('/app/data/last_update_check.json', 'w') as f:
            json.dump({
                'last_checked': datetime.now().isoformat(),
                'dismissed': True
            }, f)
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/search_movies')
def search_movies():
    """Search for movies in the current active service"""
    try:
        current_service = session.get('current_service', get_available_service())
        query = request.args.get('query', '').strip()

        if not query:
            return jsonify({"error": "No search query provided"}), 400

        logger.info(f"Searching movies in {current_service} with query: {query}")

        if current_service == 'plex' and PLEX_AVAILABLE:
            results = plex.search_movies(query)
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            results = jellyfin.search_movies(query)
        elif current_service == 'emby' and EMBY_AVAILABLE:
            results = emby.search_movies(query)
        else:
            logger.error(f"No available media service (current: {current_service})")
            return jsonify({"error": "No available media service"}), 400

        if results:
            logger.info(f"Found {len(results)} movies matching query: {query}")
            enriched_results = [enrich_movie_data(movie) for movie in results]
            return jsonify({
                "service": current_service,
                "results": enriched_results
            })

        logger.info(f"No movies found for query: {query}")
        return jsonify({"error": "No movies found"}), 404

    except Exception as e:
        logger.error(f"Error in search_movies: {str(e)}")
        return jsonify({"error": str(e)}), 500

@socketio.on('connect', namespace='/poster')
def poster_connect():
    print('Client connected to poster namespace')

@socketio.on('disconnect', namespace='/poster')
def poster_disconnect():
    print('Client disconnected from poster namespace')

# Register cleanup function
import atexit

def cleanup_services():
    if JELLYFIN_AVAILABLE and jellyfin:
        jellyfin.stop_cache_updater()
    if EMBY_AVAILABLE and emby:
        emby.stop_cache_updater()
    if PLEX_AVAILABLE and cache_manager:
        cache_manager.stop()

atexit.register(cleanup_services)

# Application startup
if __name__ == '__main__':
    logger.info("Application starting")
    logger.info("Application setup complete")
    socketio.run(app, host='0.0.0.0', port=4000, debug=True)
