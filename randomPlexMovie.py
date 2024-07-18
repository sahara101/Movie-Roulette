import os
import subprocess
from flask import Flask, jsonify, render_template, send_from_directory, request
from plexapi.server import PlexServer
from random import choice
from utils.fetch_movie_links import fetch_movie_links
from utils.youtube_trailer import search_youtube_trailer


# Plex authorization
PLEX_URL = os.getenv('PLEX_URL')
PLEX_TOKEN = os.getenv('PLEX_TOKEN')
APPLE_TV_ID = os.getenv('APPLE_TV_ID')
MOVIES_LIBRARY_NAME = os.getenv('MOVIES_LIBRARY_NAME', 'Movies')  # Default to 'Movies' if not set

plex = PlexServer(PLEX_URL, PLEX_TOKEN)
movies = plex.library.section(MOVIES_LIBRARY_NAME)

app = Flask(__name__, static_folder='static', template_folder='web')

# Global variable to store the chosen movie
chosen_movie = None

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/style/<path:filename>')
def style(filename):
    return send_from_directory('static/style', filename)

@app.route('/js/<path:filename>')
def js(filename):
    return send_from_directory('static/js', filename)

@app.route('/logos/<path:filename>')
def logos(filename):
    return send_from_directory('static/logos', filename)

# REST API endpoints
@app.route('/random_movie')
def random_movie():
    '''Generates a list of unwatched movies. Randomly selects one to be displayed.
    Pulls movie information and returns movie data for display'''
    global chosen_movie
    chosen_movie = choice(movies.search(unwatched=True))
    chosen_movie_duration_hours = (chosen_movie.duration / (1000 * 60 * 60)) % 24
    chosen_movie_duration_minutes = (chosen_movie.duration / (1000 * 60)) % 60

    actors = [actor.tag for actor in chosen_movie.actors]
    writers = [writer.tag for writer in chosen_movie.writers]
    directors = [director.tag for director in chosen_movie.directors]
    movie_description = chosen_movie.summary

    tmdb_url, trakt_url, imdb_url = fetch_movie_links(chosen_movie.title)

    # Fetch trailer URL from YouTube
    trailer_url = search_youtube_trailer(chosen_movie.title, chosen_movie.year)

    return jsonify({
        "title": chosen_movie.title,
        "year": chosen_movie.year,
        "duration_hours": int(chosen_movie_duration_hours),
        "duration_minutes": int(chosen_movie_duration_minutes),
        "directors": directors,
        "description": movie_description,
        "writers": writers,
        "actors": actors,
        "poster": chosen_movie.posterUrl,
        "background": chosen_movie.artUrl,
        "tmdb_url": tmdb_url,
        "trakt_url": trakt_url,
        "imdb_url": imdb_url,
        "trailer_url": trailer_url
    })

@app.route('/clients')
def clients():
    '''Return list of clients'''    
    client_list = []
    for client in plex.clients():
        client_info = {
            "title": client.title,
            "address": client._baseurl.split('http://')[1].split(':')[0],  # Extract the IP address
            "port": client._baseurl.split(':')[2].split('/')[0]  # Extract the port
        }
        client_list.append(client_info)
    return jsonify(client_list)

@app.route('/play_movie/<client_name>')
def play_movie(client_name):
    '''Play movie on the specified client'''
    global chosen_movie
    if chosen_movie is None:
        return jsonify({"error": "No movie selected"}), 400
    
    client_ip = request.args.get('address')
    client_port = request.args.get('port')
    
    if not client_ip or not client_port:
        return jsonify({"error": "Client not available"}), 400
    
    client = plex.client(client_name)
    client.proxyThroughServer()  # Call proxyThroughServer as a method
    client.playMedia(chosen_movie)
    return jsonify({"status": "playing"})

@app.route('/devices')
def devices():
    '''Return list of devices with ENV set'''
    devices = []

    if os.getenv('APPLE_TV_ID'):
        devices.append({"name": "apple_tv", "displayName": "Apple TV"})

    if os.getenv('LGTV_IP') and os.getenv('LGTV_MAC'):
        devices.append({"name": "lg_tv", "displayName": "LG TV (webOS)"})
    # Add more devices here if needed, following the same pattern

    return jsonify(devices)

@app.route('/turn_on_device/<device>')
def turn_on_device(device):
    '''Turn on the specified device'''
    if device == "apple_tv":
        subprocess.run(["atvremote", "turn_on", "--id", APPLE_TV_ID])
        return jsonify({"status": "Apple TV turned on"})
    elif device == "lg_tv":
        try:
            result = subprocess.run(["python3", "utils/lgtv_control.py"], capture_output=True, text=True)
            if result.returncode == 0:
                return jsonify({"status": "LG TV turned on and Plex app launched"})
            else:
                return jsonify({"status": f"Failed to control LG TV: {result.stderr}"}), 500
        except Exception as e:
            return jsonify({"status": f"Failed to control LG TV: {str(e)}"}), 500
    else:
        return jsonify({"status": "Unknown device"}), 400
