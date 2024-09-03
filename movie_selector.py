import os
import subprocess
import logging
from flask import Flask, jsonify, render_template, send_from_directory, request, session

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static', template_folder='web')
app.secret_key = 'your_secret_key_here'  # Replace with a real secret key

# Check which services are available
PLEX_AVAILABLE = all([os.getenv('PLEX_URL'), os.getenv('PLEX_TOKEN'), os.getenv('MOVIES_LIBRARY_NAME')])
JELLYFIN_AVAILABLE = all([os.getenv('JELLYFIN_URL'), os.getenv('JELLYFIN_API_KEY')])
HOMEPAGE_MODE = os.getenv('HOMEPAGE_MODE', 'FALSE').upper() == 'TRUE'

if not (PLEX_AVAILABLE or JELLYFIN_AVAILABLE):
    raise EnvironmentError("At least one service (Plex or Jellyfin) must be configured.")

# Initialize Plex and Jellyfin services if available
if PLEX_AVAILABLE:
    from utils.plex_service import PlexService
    plex = PlexService()
else:
    plex = None

if JELLYFIN_AVAILABLE:
    from utils.jellyfin_service import JellyfinService
    jellyfin = JellyfinService()
else:
    jellyfin = None

from utils.fetch_movie_links import fetch_movie_links
from utils.youtube_trailer import search_youtube_trailer

def get_available_service():
    if PLEX_AVAILABLE:
        return 'plex'
    elif JELLYFIN_AVAILABLE:
        return 'jellyfin'
    else:
        raise EnvironmentError("No media service is available")

@app.route('/')
def index():
    return render_template('index.html', homepage_mode=HOMEPAGE_MODE)

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
    current_service = session.get('current_service', get_available_service())
    try:
        if current_service == 'plex' and PLEX_AVAILABLE:
            movie_data = plex.get_random_movie()
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            movie_data = jellyfin.get_random_movie()
        else:
            return jsonify({"error": "No available media service"}), 400
        
        if movie_data:
            movie_data = enrich_movie_data(movie_data)
            return jsonify({"service": current_service, "movie": movie_data})
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
    rating = request.args.get('rating')

    try:
        if current_service == 'plex' and PLEX_AVAILABLE:
            movie_data = plex.filter_movies(genre, year, rating)
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            movie_data = jellyfin.filter_movies(genre, year, rating)
        else:
            return jsonify({"error": "No available media service"}), 400
        
        if movie_data:
            movie_data = enrich_movie_data(movie_data)
            return jsonify({"service": current_service, "movie": movie_data})
        else:
            return jsonify({"error": "No movies found matching the filter"}), 404
    except Exception as e:
        logger.error(f"Error in filter_movies: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/next_movie')
def next_movie():
    current_service = session.get('current_service', get_available_service())
    try:
        if current_service == 'plex' and PLEX_AVAILABLE:
            movie_data = plex.get_random_movie()
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            movie_data = jellyfin.get_random_movie()
        else:
            return jsonify({"error": "No available media service"}), 400
        
        if movie_data:
            movie_data = enrich_movie_data(movie_data)
            return jsonify({"service": current_service, "movie": movie_data})
        else:
            return jsonify({"error": "No movie found"}), 404
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
            genres = plex.get_genres()
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
            years = plex.get_years()
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            years = jellyfin.get_years()
        else:
            return jsonify({"error": "No available media service"}), 400
        logger.debug(f"Fetched years: {years}")
        return jsonify(years)
    except Exception as e:
        logger.error(f"Error in get_years: {str(e)}")
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
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            result = jellyfin.play_movie(movie_id, client_id)
        else:
            return jsonify({"error": "No available media service"}), 400
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

if __name__ == '__main__':
    app.run(debug=True)
