import os
import subprocess
import logging
import json
import random
import traceback
import threading
import time
from datetime import datetime, timedelta
import pytz
from flask import Flask, jsonify, render_template, send_from_directory, request, session
from flask_socketio import SocketIO, emit
from utils.cache_manager import CacheManager
from utils.poster_view import set_current_movie, poster_bp, init_socket
from utils.default_poster_manager import init_default_poster_manager, default_poster_manager
from utils.playback_monitor import PlaybackMonitor
from utils.fetch_movie_links import fetch_movie_links

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static', template_folder='web')
app.secret_key = 'your_secret_key_here'  # Replace with a real secret key
socketio = SocketIO(app)
init_socket(socketio)

# Initialize the default poster manager
default_poster_manager = init_default_poster_manager(socketio)

# Add the default_poster_manager to the app config
app.config['DEFAULT_POSTER_MANAGER'] = default_poster_manager

# Check which services are available
PLEX_AVAILABLE = all([os.getenv('PLEX_URL'), os.getenv('PLEX_TOKEN'), os.getenv('PLEX_MOVIE_LIBRARIES')])
JELLYFIN_AVAILABLE = all([os.getenv('JELLYFIN_URL'), os.getenv('JELLYFIN_API_KEY')])
HOMEPAGE_MODE = os.getenv('HOMEPAGE_MODE', 'FALSE').upper() == 'TRUE'

if not (PLEX_AVAILABLE or JELLYFIN_AVAILABLE):
    raise EnvironmentError("At least one service (Plex or Jellyfin) must be configured.")

cache_file_path = '/app/data/plex_unwatched_movies.json'

# Initialize Plex and Jellyfin services if available
if PLEX_AVAILABLE:
    from utils.plex_service import PlexService
    plex = PlexService()
    cache_manager = CacheManager(plex, cache_file_path)
    cache_manager.start()
    app.config['PLEX_SERVICE'] = plex
else:
    plex = None
    cache_manager = None

if JELLYFIN_AVAILABLE:
    from utils.jellyfin_service import JellyfinService
    jellyfin = JellyfinService()
    app.config['JELLYFIN_SERVICE'] = jellyfin
else:
    jellyfin = None

from utils.fetch_movie_links import fetch_movie_links
from utils.youtube_trailer import search_youtube_trailer

# Global variables for Plex caching
all_plex_unwatched_movies = []
movies_loaded_from_cache = False
loading_in_progress = False

# Register the poster blueprint
app.register_blueprint(poster_bp)

# Start the PlaybackMonitor
playback_monitor = PlaybackMonitor(app, interval=10)
playback_monitor.start()

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
            cache_manager.update_cache()
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

@app.route('/')
def index():
    return render_template('index.html', homepage_mode=HOMEPAGE_MODE)

@app.route('/start_loading')
def start_loading():
    if PLEX_AVAILABLE:
        socketio.start_background_task(resync_cache)
        return jsonify({"status": "Loading started for Plex"})
    return jsonify({"status": "Loading not required"})

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
        logger.error(f"Error in random_movie: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/filter_movies')
def filter_movies():
    current_service = session.get('current_service', get_available_service())
    genre = request.args.get('genre')
    year = request.args.get('year')
    pg_rating = request.args.get('pg_rating')

    logger.debug(f"Filtering movies with genre: {genre}, year: {year}, pg_rating: {pg_rating}")

    try:
        if current_service == 'plex' and PLEX_AVAILABLE:
            movie_data = plex.filter_movies(genre, year, pg_rating)
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            movie_data = jellyfin.filter_movies(genre, year, pg_rating)
        else:
            return jsonify({"error": "No available media service"}), 400

        if movie_data:
            logger.debug(f"Filtered movie: {movie_data['title']} ({movie_data['year']}) - PG Rating: {movie_data.get('contentRating', 'N/A')}")
            movie_data = enrich_movie_data(movie_data)
            return jsonify({"service": current_service, "movie": movie_data})
        else:
            logger.warning("No movies found matching the filter")
            return jsonify({"error": "No movies found matching the filter"}), 204
    except Exception as e:
        logger.error(f"Error in filter_movies: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/next_movie')
def next_movie():
    global all_plex_unwatched_movies
    current_service = session.get('current_service', get_available_service())
    genre = request.args.get('genre')
    year = request.args.get('year')
    pg_rating = request.args.get('pg_rating')

    logger.debug(f"Next movie request with filters - genre: {genre}, year: {year}, pg_rating: {pg_rating}")

    try:
        if current_service == 'plex' and PLEX_AVAILABLE:
            if not all_plex_unwatched_movies:
                all_plex_unwatched_movies = plex.get_all_unwatched_movies()

            filtered_movies = all_plex_unwatched_movies
            if genre:
                filtered_movies = [m for m in filtered_movies if genre in m['genres']]
            if year:
                filtered_movies = [m for m in filtered_movies if m['year'] == int(year)]
            if pg_rating:
                filtered_movies = [m for m in filtered_movies if m['contentRating'] == pg_rating]

            if filtered_movies:
                movie_data = random.choice(filtered_movies)
            else:
                movie_data = None
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            movie_data = jellyfin.filter_movies(genre, year, pg_rating)
        else:
            return jsonify({"error": "No available media service"}), 400

        if movie_data:
            logger.debug(f"Next movie selected: {movie_data['title']} ({movie_data['year']}) - PG Rating: {movie_data.get('contentRating', 'N/A')}")
            movie_data = enrich_movie_data(movie_data)
            return jsonify({"service": current_service, "movie": movie_data})
        else:
            logger.warning("No movies found matching the criteria")
            return jsonify({"error": "No movies found matching the criteria"}), 204
    except Exception as e:
        logger.error(f"Error in next_movie: {str(e)}")
        return jsonify({"error": str(e)}), 500

def enrich_movie_data(movie_data):
    current_service = session.get('current_service', get_available_service())
    tmdb_url, trakt_url, imdb_url = fetch_movie_links(movie_data, current_service)
    trailer_url = search_youtube_trailer(movie_data['title'], movie_data['year'])

    movie_data.update({
        "tmdb_url": tmdb_url,
        "trakt_url": trakt_url,
        "imdb_url": imdb_url,
        "trailer_url": trailer_url
    })

    return movie_data

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
        logger.debug(f"Fetched genres: {genres}")
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
        logger.debug(f"Fetched years: {years}")
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
        logger.debug(f"Fetched clients for {current_service}: {client_list}")
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

        logger.debug(f"Play movie result for {current_service}: {result}")
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error in play_movie: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/devices')
def devices():
    devices = []

    if os.getenv('APPLE_TV_ID'):
        devices.append({"name": "apple_tv", "displayName": "Apple TV"})

    if os.getenv('LGTV_IP') and os.getenv('LGTV_MAC'):
        devices.append({"name": "lg_tv", "displayName": "LG TV (webOS)"})

    return jsonify(devices)

@app.route('/turn_on_device/<device>')
def turn_on_device(device):
    current_service = session.get('current_service', get_available_service())
    if device == "apple_tv":
        subprocess.run(["atvremote", "turn_on", "--id", os.getenv('APPLE_TV_ID')])
        return jsonify({"status": "Apple TV turned on"})
    elif device == "lg_tv":
        try:
            app_to_launch = 'plex' if current_service == 'plex' else 'jellyfin'
            result = subprocess.run(["python3", "utils/lgtv_control.py", app_to_launch], capture_output=True, text=True)
            if result.returncode == 0:
                return jsonify({"status": f"LG TV turned on and {app_to_launch.capitalize()} app launched"})
            else:
                return jsonify({"status": f"Failed to control LG TV: {result.stderr}"}), 500
        except Exception as e:
            return jsonify({"error": f"Failed to control LG TV: {str(e)}"}), 500
    else:
        return jsonify({"error": "Unknown device"}), 400

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

@app.route('/debug_plex')
def debug_plex():
    if not PLEX_AVAILABLE:
        return jsonify({"error": "Plex is not available"}), 400

    try:
        update_cache_status()
        total_movies = plex.get_total_unwatched_movies()
        cached_movies = len(cache_manager.get_cached_movies()) if cache_manager else 0
        return jsonify({
            "total_unwatched_movies": total_movies,
            "cached_movies": cached_movies,
            "loaded_from_cache": movies_loaded_from_cache,
            "plex_url": os.getenv('PLEX_URL'),
            "movies_library_name": os.getenv('MOVIES_LIBRARY_NAME'),
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

@socketio.on('connect', namespace='/poster')
def poster_connect():
    print('Client connected to poster namespace')

@socketio.on('disconnect', namespace='/poster')
def poster_disconnect():
    print('Client disconnected from poster namespace')

if __name__ == '__main__':
    logger.info("Application starting")
    logger.info("Application setup complete")
    socketio.run(app, host='0.0.0.0', port=4000, debug=True)
