import os
import requests
from plexapi.server import PlexServer

# Plex authorization
PLEX_URL = os.getenv('PLEX_URL')
PLEX_TOKEN = os.getenv('PLEX_TOKEN')
MOVIES_LIBRARY_NAME = os.getenv('MOVIES_LIBRARY_NAME', 'Movies')  # Default to 'Movies' if not set

plex = PlexServer(PLEX_URL, PLEX_TOKEN)

def get_tmdb_id_from_plex(movie_title):
    movies_library = plex.library.section(MOVIES_LIBRARY_NAME)
    for movie in movies_library.all():
        if movie.title.lower() == movie_title.lower():
            for guid in movie.guids:
                if 'tmdb://' in guid.id:
                    return guid.id.split('//')[1]
    return None

def fetch_movie_links(movie_title):
    tmdb_id = get_tmdb_id_from_plex(movie_title)
    if not tmdb_id:
        return None, None, None

    tmdb_url = f"https://www.themoviedb.org/movie/{tmdb_id}"
    trakt_api_url = f"https://api.trakt.tv/search/tmdb/{tmdb_id}?type=movie"

    try:
        response = requests.get(trakt_api_url)
        if response.status_code == 200:
            data = response.json()
            if data:
                trakt_id = data[0]['movie']['ids']['slug']
                imdb_id = data[0]['movie']['ids']['imdb'] if 'imdb' in data[0]['movie']['ids'] else None
                trakt_url = f"https://trakt.tv/movies/{trakt_id}"
                imdb_url = f"https://www.imdb.com/title/{imdb_id}" if imdb_id else None
                return tmdb_url, trakt_url, imdb_url
    except requests.RequestException as e:
        print(f"Error fetching Trakt data: {e}")

    return tmdb_url, None, None
