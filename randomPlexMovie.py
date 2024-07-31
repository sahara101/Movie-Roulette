import os
import subprocess
import random
from flask import Flask, jsonify, render_template, send_from_directory, request
from plexapi.server import PlexServer
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

# Global variables
chosen_movie = None
filtered_movies = []
last_movie = None

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
    global chosen_movie, filtered_movies, last_movie
    try:
        all_unwatched = movies.search(unwatched=True)
        available_movies = [movie for movie in all_unwatched if movie != last_movie]

        if not available_movies:
            available_movies = all_unwatched

        chosen_movie = random.choice(available_movies)
        last_movie = chosen_movie
        filtered_movies = all_unwatched
        movie_data = get_movie_data(chosen_movie)
        print("Movie data:", movie_data)  # Print the movie data
        return movie_data
    except Exception as e:
        print(f"Error in random_movie: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/filter_movies')
def filter_movies():
    global chosen_movie, filtered_movies, last_movie
    genre = request.args.get('genre')
    year = request.args.get('year')
    rating = request.args.get('rating')

    filters = {'unwatched': True}

    if genre:
        filters['genre'] = genre
    if year:
        filters['year'] = int(year)

    filtered_movies = movies.search(**filters)

    if rating:
        rating_floor = float(rating)
        rating_ceiling = rating_floor + 0.9
        filtered_movies = [movie for movie in filtered_movies if movie.rating and rating_floor <= float(movie.rating) < rating_ceiling]

    if len(filtered_movies) == 0:
        return jsonify({"error": "No movies found matching the filter"}), 404
    elif len(filtered_movies) == 1:
        chosen_movie = filtered_movies[0]
        last_movie = chosen_movie
        return get_movie_data(chosen_movie)
    else:
        available_movies = [movie for movie in filtered_movies if movie != last_movie]
        if not available_movies:
            available_movies = filtered_movies
        chosen_movie = random.choice(available_movies)
        last_movie = chosen_movie
        return get_movie_data(chosen_movie)

@app.route('/next_movie')
def next_movie():
    global chosen_movie, filtered_movies, last_movie

    if not filtered_movies:  # If no filter is applied
        return random_movie()

    available_movies = [movie for movie in filtered_movies if movie != last_movie]
    if not available_movies:
        available_movies = filtered_movies

    chosen_movie = random.choice(available_movies)
    last_movie = chosen_movie
    return get_movie_data(chosen_movie)

def get_movie_data(movie):
    try:
        movie_duration_hours = (movie.duration / (1000 * 60 * 60)) % 24
        movie_duration_minutes = (movie.duration / (1000 * 60)) % 60

        actors = [actor.tag for actor in movie.actors]
        writers = [writer.tag for writer in movie.writers]
        directors = [director.tag for director in movie.directors]
        genres = [genre.tag for genre in movie.genres]
        movie_description = movie.summary

        tmdb_url, trakt_url, imdb_url = fetch_movie_links(movie.title)
        trailer_url = search_youtube_trailer(movie.title, movie.year)

        return jsonify({
            "title": movie.title,
            "year": movie.year,
            "duration_hours": int(movie_duration_hours),
            "duration_minutes": int(movie_duration_minutes),
            "directors": directors,
            "description": movie_description,
            "writers": writers,
            "actors": actors,
            "genres": genres,
            "poster": movie.posterUrl,
            "background": movie.artUrl,
            "tmdb_url": tmdb_url,
            "trakt_url": trakt_url,
            "imdb_url": imdb_url,
            "trailer_url": trailer_url,
            "rating": movie.rating
        })
    except Exception as e:
        print(f"Error in get_movie_data: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/get_genres')
def get_genres():
    all_genres = set()
    for movie in movies.search(unwatched=True):
        all_genres.update([genre.tag for genre in movie.genres])
    genre_list = sorted(list(all_genres))
    print("Available genres:", genre_list)  # Debugging line
    return jsonify(genre_list)

@app.route('/get_years')
def get_years():
    all_years = set()
    for movie in movies.search(unwatched=True):
        all_years.add(movie.year)
    year_list = sorted(list(all_years), reverse=True)
    print("Available years:", year_list)  # Debugging line
    return jsonify(year_list)

@app.route('/clients')
def clients():
    client_list = []
    for client in plex.clients():
        client_info = {
            "title": client.title,
            "address": client._baseurl.split('http://')[1].split(':')[0],
            "port": client._baseurl.split(':')[2].split('/')[0]
        }
        client_list.append(client_info)
    return jsonify(client_list)

@app.route('/play_movie/<client_name>')
def play_movie(client_name):
    global chosen_movie
    if chosen_movie is None:
        return jsonify({"error": "No movie selected"}), 400

    client_ip = request.args.get('address')
    client_port = request.args.get('port')

    if not client_ip or not client_port:
        return jsonify({"error": "Client not available"}), 400

    client = plex.client(client_name)
    client.proxyThroughServer()
    client.playMedia(chosen_movie)
    return jsonify({"status": "playing"})

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

if __name__ == '__main__':
    app.run(debug=True)
