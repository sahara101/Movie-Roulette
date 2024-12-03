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
from flask import Flask, jsonify, render_template, send_from_directory, request, session, redirect
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
from utils.lgtv_discovery import scan_network, test_tv_connection, is_valid_ip, is_valid_mac, LG_MAC_PREFIXES
from utils.appletv_discovery import scan_for_appletv, pair_appletv, submit_pin, clear_pairing, ROOT_CONFIG_PATH, turn_on_apple_tv, fix_config_format, check_credentials
from utils.tmdb_service import tmdb_service
from routes.trakt_routes import trakt_bp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app first
app = Flask(__name__, static_folder='static', template_folder='web')
app.secret_key = 'your_secret_key_here'
socketio = SocketIO(app)
init_socket(socketio)

HOMEPAGE_SETTINGS = {}
FEATURE_SETTINGS = {}
CLIENT_SETTINGS = {}
APPLE_TV_SETTINGS = {}
LG_TV_SETTINGS = {}
PLEX_SETTINGS = {}
JELLYFIN_SETTINGS = {}

# Global flags
HOMEPAGE_MODE = False
USE_LINKS = True
USE_FILTER = True
USE_WATCH_BUTTON = True
USE_NEXT_BUTTON = True
PLEX_AVAILABLE = False
JELLYFIN_AVAILABLE = False

# Other globals
all_plex_unwatched_movies = []
movies_loaded_from_cache = False
loading_in_progress = False
cache_file_path = '/app/data/plex_unwatched_movies.json'
plex = None
jellyfin = None
cache_manager = None
_plex_pin_logins = {}

def load_settings():
    """Load all settings and update global variables"""
    global FEATURE_SETTINGS, CLIENT_SETTINGS, APPLE_TV_SETTINGS
    global LG_TV_SETTINGS, PLEX_SETTINGS, JELLYFIN_SETTINGS
    global HOMEPAGE_MODE, USE_LINKS, USE_FILTER, USE_WATCH_BUTTON, USE_NEXT_BUTTON
    global PLEX_AVAILABLE, JELLYFIN_AVAILABLE

    # Load all settings first
    FEATURE_SETTINGS = settings.get('features', {})
    CLIENT_SETTINGS = settings.get('clients', {})
    APPLE_TV_SETTINGS = CLIENT_SETTINGS.get('apple_tv', {})
    LG_TV_SETTINGS = CLIENT_SETTINGS.get('lg_tv', {})
    PLEX_SETTINGS = settings.get('plex', {})
    JELLYFIN_SETTINGS = settings.get('jellyfin', {})

    # Update feature flags
    HOMEPAGE_MODE = FEATURE_SETTINGS.get('homepage_mode', False)
    USE_LINKS = FEATURE_SETTINGS.get('use_links', True)
    USE_FILTER = FEATURE_SETTINGS.get('use_filter', True)
    USE_WATCH_BUTTON = FEATURE_SETTINGS.get('use_watch_button', True)
    USE_NEXT_BUTTON = FEATURE_SETTINGS.get('use_next_button', True)

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

    logger.info(f"Settings loaded - Homepage Mode: {HOMEPAGE_MODE}")
    logger.info(f"Service availability - Plex: {PLEX_AVAILABLE}, Jellyfin: {JELLYFIN_AVAILABLE}")

def initialize_services():
    """Initialize or reinitialize media services based on current settings"""
    global plex, jellyfin, PLEX_AVAILABLE, JELLYFIN_AVAILABLE, cache_manager
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
            cache_manager.start()

            # If no cache file exists, start async initialization
            if not os.path.exists(cache_file_path):
                socketio.start_background_task(plex.initialize_cache_async, socketio)

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
    logger.info(f"- Overseerr: {overseerr_enabled}")
    logger.info(f"- Trakt: {trakt_enabled}")

    return True

def get_available_service():
    if PLEX_AVAILABLE:
        return 'plex'
    elif JELLYFIN_AVAILABLE:
        return 'jellyfin'
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

# Start the PlaybackMonitor
playback_monitor = PlaybackMonitor(app, interval=10)
playback_monitor.start()

# Flask Routes
@app.route('/')
def index():
    # Only redirect if no services are configured
    if not (PLEX_AVAILABLE or JELLYFIN_AVAILABLE):
        return redirect('/settings')

    return render_template(
        'index.html',
        homepage_mode=HOMEPAGE_MODE,
        use_links=USE_LINKS,
        use_filter=USE_FILTER,
        use_watch_button=USE_WATCH_BUTTON,
        use_next_button=USE_NEXT_BUTTON
    )

@app.route('/start_loading')
def start_loading():
    if PLEX_AVAILABLE:
        if not os.path.exists(cache_file_path):
            # Only start async initialization if no cache exists
            plex_service = app.config['PLEX_SERVICE']
            socketio.start_background_task(plex_service.initialize_cache_async, socketio)
            return jsonify({"status": "Cache building started"})
        return jsonify({"status": "Cache already exists"})
    return jsonify({"status": "Loading not required"})

def any_service_available():
    return PLEX_AVAILABLE or JELLYFIN_AVAILABLE

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
    if PLEX_AVAILABLE:
        services.append('plex')
    if JELLYFIN_AVAILABLE:
        services.append('jellyfin')
    return jsonify(services)

@app.route('/current_service')
def get_current_service():
    if 'current_service' not in session or session['current_service'] not in ['plex', 'jellyfin']:
        session['current_service'] = get_available_service()

    # Check if the current service is still available
    if (session['current_service'] == 'plex' and not PLEX_AVAILABLE) or \
       (session['current_service'] == 'jellyfin' and not JELLYFIN_AVAILABLE):
        session['current_service'] = get_available_service()

    return jsonify({"service": session['current_service']})

@app.route('/switch_service')
def switch_service():
    if PLEX_AVAILABLE and JELLYFIN_AVAILABLE:
        current = session.get('current_service', 'plex')
        new_service = 'jellyfin' if current == 'plex' else 'plex'
        session['current_service'] = new_service
        return jsonify({"service": new_service})
    else:
        return jsonify({"service": get_available_service()})

@app.route('/api/reinitialize_services')
def reinitialize_services():
    try:
        if PLEX_AVAILABLE and plex:
            plex.refresh_cache()  # This should reload the cache into memory
            if cache_manager:
                cache_manager._init_memory_cache()  # Reload the cache manager
        return jsonify({"status": "success"})
    except Exception as e:
        logger.error(f"Error reinitializing services: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/random_movie')
def random_movie():
    global all_plex_unwatched_movies, loading_in_progress, movies_loaded_from_cache
    current_service = session.get('current_service', get_available_service())
    try:
        if current_service == 'plex' and PLEX_AVAILABLE:
            if not all_plex_unwatched_movies:
                initialize_cache()
            if loading_in_progress:
                return jsonify({"loading_in_progress": True}), 202
            if not all_plex_unwatched_movies:
                return jsonify({"error": "No unwatched movies available"}), 404
            movie_data = random.choice(all_plex_unwatched_movies)
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            movie_data = jellyfin.get_random_movie()
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

@app.route('/filter_movies')
def filter_movies():
    current_service = session.get('current_service', get_available_service())
    genres = request.args.get('genres', '').split(',') if request.args.get('genres') else None
    years = request.args.get('years', '').split(',') if request.args.get('years') else None
    pg_ratings = request.args.get('pg_ratings', '').split(',') if request.args.get('pg_ratings') else None

    try:
        if current_service == 'plex' and PLEX_AVAILABLE:
            movie_data = plex.filter_movies(genres, years, pg_ratings)
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            movie_data = jellyfin.filter_movies(genres, years, pg_ratings)
        else:
            return jsonify({"error": "No available media service"}), 400

        if movie_data:
            # Enrich the movie data with TMDb information
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

@app.route('/next_movie')
def next_movie():
    current_service = session.get('current_service', get_available_service())
    genres = request.args.get('genres', '').split(',') if request.args.get('genres') else None
    years = request.args.get('years', '').split(',') if request.args.get('years') else None
    pg_ratings = request.args.get('pg_ratings', '').split(',') if request.args.get('pg_ratings') else None

    try:
        if current_service == 'plex' and PLEX_AVAILABLE:
            movie_data = plex.get_next_movie(genres, years, pg_ratings)
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            movie_data = jellyfin.filter_movies(genres, years, pg_ratings)
        else:
            return jsonify({"error": "No available media service"}), 400

        if movie_data:
            # Enrich the movie data with TMDb information
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

@app.route('/get_genres')
def get_genres():
    current_service = session.get('current_service', get_available_service())
    try:
        logger.debug(f"Fetching genres for service: {current_service}")
        if current_service == 'plex' and PLEX_AVAILABLE:
            genres = set()
            for movie in all_plex_unwatched_movies:
                genres.update(movie['genres'])
            genres = sorted(list(genres))
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            genres = jellyfin.get_genres()
        else:
            return jsonify({"error": "No available media service"}), 400
        return jsonify(genres)
    except Exception as e:
        logger.error(f"Error in get_genres: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/get_years')
def get_years():
    current_service = session.get('current_service', get_available_service())
    try:
        logger.debug(f"Fetching years for service: {current_service}")
        if current_service == 'plex' and PLEX_AVAILABLE:
            years = sorted(set(movie['year'] for movie in all_plex_unwatched_movies if movie['year']), reverse=True)
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            years = jellyfin.get_years()
        else:
            return jsonify({"error": "No available media service"}), 400
        return jsonify(years)
    except Exception as e:
        logger.error(f"Error in get_years: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/get_pg_ratings')
def get_pg_ratings():
    current_service = session.get('current_service', get_available_service())
    try:
        if current_service == 'plex' and PLEX_AVAILABLE:
            ratings = plex.get_pg_ratings()
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            ratings = jellyfin.get_pg_ratings()
        else:
            return jsonify({"error": "No available media service"}), 400
        return jsonify(ratings)
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
        else:
            return jsonify({"error": "No available media service"}), 400

        if result.get("status") == "playing" and movie_data:
            set_current_movie(movie_data, current_service)

        return jsonify(result)
    except Exception as e:
        logger.error(f"Error in play_movie: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/devices')
def devices():
    devices = []

    # Check Apple TV
    apple_tv_id_env = os.getenv('APPLE_TV_ID')
    if apple_tv_id_env:
        # If ENV is set, show it and mark as ENV controlled
        devices.append({
            "name": "apple_tv",
            "displayName": "Apple TV",
            "env_controlled": True
        })
    elif APPLE_TV_SETTINGS.get('enabled') and APPLE_TV_SETTINGS.get('id'):
        # If no ENV but settings are enabled and have ID
        devices.append({
            "name": "apple_tv",
            "displayName": "Apple TV",
            "env_controlled": False
        })

    # Check LG TV
    env_lg_ip = os.getenv('LGTV_IP')
    env_lg_mac = os.getenv('LGTV_MAC')

    if env_lg_ip and env_lg_mac:
        # If ENV is set, show it and mark as ENV controlled
        devices.append({
            "name": "lg_tv",
            "displayName": "LG TV (webOS)",
            "env_controlled": True
        })
    elif (LG_TV_SETTINGS.get('enabled') and
          LG_TV_SETTINGS.get('ip') and
          LG_TV_SETTINGS.get('mac')):
        # If no ENV but settings are enabled and have all required fields
        devices.append({
            "name": "lg_tv",
            "displayName": "LG TV (webOS)",
            "env_controlled": False
        })

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
    elif device == "lg_tv" and (LG_TV_SETTINGS.get('enabled') or os.getenv('LGTV_MAC')):
        try:
            from utils.lgtv_control import get_tv_config, send_wol
            tv_ip, tv_mac = get_tv_config()

            if not tv_mac:
                return jsonify({"error": "LG TV MAC address not configured"}), 400

            current_service = session.get('current_service', get_available_service())

            if send_wol(tv_mac):
                # Start a background task to launch the app after TV wakes up
                def delayed_app_launch(service):
                    time.sleep(10)  # Give TV time to wake up
                    try:
                        app_to_launch = 'plex' if current_service == 'plex' else 'jellyfin'
                        from utils.lgtv_control import main
                        main(app_to_launch)
                    except Exception as e:
                        logger.error(f"Failed to launch app: {e}")

                thread = threading.Thread(target=delayed_app_launch, args=(current_service,))
                thread.daemon = True
                thread.start()

                return jsonify({"status": "LG TV wake-on-LAN sent successfully"})
            else:
                return jsonify({"error": "Failed to send wake-on-LAN packet"}), 500
        except Exception as e:
            return jsonify({"error": f"Failed to control LG TV: {str(e)}"}), 500
    else:
        return jsonify({"error": "Unknown or disabled device"}), 400

@app.route('/debug_plex')
def debug_plex():
    if not PLEX_AVAILABLE:
        return jsonify({"error": "Plex is not available"}), 400

    try:
        update_cache_status()
        total_movies = plex.get_total_unwatched_movies() if plex else 0
        all_movies_count = len(cache_manager.get_all_plex_movies()) if cache_manager else 0
        cached_movies = len(cache_manager.get_cached_movies()) if cache_manager else 0

        # Get settings-based URL and libraries
        plex_url = PLEX_SETTINGS.get('url') or os.getenv('PLEX_URL')
        movie_libraries = PLEX_SETTINGS.get('movie_libraries') or os.getenv('PLEX_MOVIE_LIBRARIES', '')

        # If movie_libraries is a list, join it
        if isinstance(movie_libraries, list):
            movie_libraries = ','.join(movie_libraries)

        return jsonify({
            "total_movies": all_movies_count,
            "total_unwatched_movies": total_movies,
            "cached_movies": cached_movies,
            "loaded_from_cache": movies_loaded_from_cache,
            "plex_url": plex_url,
            "movies_library_name": movie_libraries,
            "cache_file_exists": os.path.exists(cache_file_path)
        })
    except Exception as e:
        logger.error(f"Error in debug_plex: {str(e)}")
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
            if str(movie['tmdb_id']) == str(tmdb_id):
                return jsonify({"plexId": movie['plex_id']})
        return jsonify({"error": "Movie not found in Plex"}), 404
    except Exception as e:
        logger.error(f"Error getting Plex ID: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/lgtv/scan')
def scan_for_lgtvs():
    """Scan network for LG TVs and provide detailed discovery information"""
    try:
        logger.info("Starting LG TV network scan")
        devices = scan_network()

        # Format response with detailed information
        formatted_devices = []
        for device in devices:
            formatted_devices.append({
                'ip': device['ip'],
                'mac': device['mac'],
                'name': device.get('description', 'LG TV'),
                'device_type': device.get('device_type', 'LG Device'),
                'reachable': test_tv_connection(device['ip'])
            })

        logger.info(f"Scan complete. Found {len(formatted_devices)} LG devices")
        for device in formatted_devices:
            logger.info(f"Device found: {device['name']} at {device['ip']} ({device['mac']}) - {'Reachable' if device['reachable'] else 'Not reachable'}")

        return jsonify({
            'devices': formatted_devices,
            'found': len(formatted_devices) > 0,
            'scan_info': {
                'timestamp': datetime.now().isoformat(),
                'total_devices': len(formatted_devices),
                'reachable_devices': sum(1 for d in formatted_devices if d['reachable']),
                'scan_successful': True
            }
        })

    except subprocess.CalledProcessError as e:
        logger.error(f"arp-scan execution failed: {str(e)}")
        return jsonify({
            'error': 'Network scan failed. Please ensure arp-scan is installed and you have necessary permissions.',
            'devices': [],
            'scan_info': {
                'timestamp': datetime.now().isoformat(),
                'error_details': str(e),
                'scan_successful': False
            }
        }), 500
    except Exception as e:
        logger.error(f"Error during LG TV scan: {str(e)}")
        return jsonify({
            'error': 'Failed to scan for LG TVs',
            'devices': [],
            'scan_info': {
                'timestamp': datetime.now().isoformat(),
                'error_details': str(e),
                'scan_successful': False
            }
        }), 500

@app.route('/api/lgtv/validate')
def validate_tv():
    """Validate TV connection and configuration"""
    ip = request.args.get('ip')
    mac = request.args.get('mac')

    if not ip or not mac:
        return jsonify({
            'error': 'Both IP and MAC address are required',
            'validation': {
                'ip': bool(ip),
                'mac': bool(mac)
            }
        }), 400

    # Get just the prefix part for comparison
    mac_prefix = ':'.join(mac.upper().split(':')[:3])

    validation_results = {
        'ip': {
            'valid': is_valid_ip(ip),
            'value': ip
        },
        'mac': {
            'valid': is_valid_mac(mac),
            'value': mac,
            'is_lg_device': mac_prefix in LG_MAC_PREFIXES,
            'device_type': LG_MAC_PREFIXES.get(mac_prefix, 'Unknown LG Device')
        },
        'connection': {
            'reachable': False,
            'tested_at': datetime.now().isoformat()
        }
    }

    # Only test connection if IP and MAC are valid
    if validation_results['ip']['valid'] and validation_results['mac']['valid']:
        validation_results['connection']['reachable'] = test_tv_connection(ip)

    if validation_results['connection']['reachable']:
        return jsonify({
            'status': 'valid',
            'validation': validation_results
        })
    elif validation_results['ip']['valid'] and validation_results['mac']['valid']:
        return jsonify({
            'error': 'TV found but not reachable. Please ensure:',
            'checks': [
                'TV is powered on',
                'TV is connected to the network',
                'No firewall is blocking the connection',
                'TV is on the same network as Movie Roulette'
            ],
            'validation': validation_results
        }), 404
    else:
        return jsonify({
            'error': 'Invalid IP or MAC address format',
            'validation': validation_results
        }), 400

# Remove the global variables _process_lock and _active_processes, they're not needed anymore

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
        'services_configured': bool(PLEX_AVAILABLE or JELLYFIN_AVAILABLE),
        'plex_available': PLEX_AVAILABLE,
        'jellyfin_available': JELLYFIN_AVAILABLE
    })

@app.route('/api/service_status')
def service_status():
    """Return the current status of media services"""
    return jsonify({
        'services_configured': bool(PLEX_AVAILABLE or JELLYFIN_AVAILABLE),
        'plex_available': PLEX_AVAILABLE,
        'jellyfin_available': JELLYFIN_AVAILABLE
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

        logger.info(f"Plex auth initiated with PIN: {pin_login.pin}")

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

        # Get all users who have access to the server
        users = [user.title for user in server.myPlexAccount().users()]
        # Add the admin user
        users.insert(0, server.myPlexAccount().title)

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
    if PLEX_AVAILABLE and cache_manager:
        cache_manager.stop()

atexit.register(cleanup_services)

# Application startup
if __name__ == '__main__':
    logger.info("Application starting")
    logger.info("Application setup complete")
    socketio.run(app, host='0.0.0.0', port=4000, debug=True)
