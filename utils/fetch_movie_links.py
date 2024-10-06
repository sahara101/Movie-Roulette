import os
import requests
from plexapi.server import PlexServer

# Check which services are available
PLEX_AVAILABLE = all([os.getenv('PLEX_URL'), os.getenv('PLEX_TOKEN'), os.getenv('PLEX_MOVIE_LIBRARIES')])
JELLYFIN_AVAILABLE = all([os.getenv('JELLYFIN_URL'), os.getenv('JELLYFIN_API_KEY')])

if not (PLEX_AVAILABLE or JELLYFIN_AVAILABLE):
    raise EnvironmentError("At least one service (Plex or Jellyfin) must be configured.")

# Initialize Plex if available
if PLEX_AVAILABLE:
    PLEX_URL = os.getenv('PLEX_URL')
    PLEX_TOKEN = os.getenv('PLEX_TOKEN')
    PLEX_MOVIE_LIBRARIES = os.getenv('PLEX_MOVIE_LIBRARIES', 'Movies').split(',')
    plex = PlexServer(PLEX_URL, PLEX_TOKEN)

def get_tmdb_id_from_plex(movie_data):
    if not PLEX_AVAILABLE:
        return None
    try:
        for library_name in PLEX_MOVIE_LIBRARIES:
            try:
                library = plex.library.section(library_name.strip())
                movie = library.get(movie_data['title'])
                for guid in movie.guids:
                    if 'tmdb://' in guid.id:
                        return guid.id.split('//')[1]
            except Exception:
                continue  # If movie not found in this library, try the next one
    except Exception as e:
        print(f"Error getting TMDB ID from Plex: {e}")
    return None

def get_tmdb_id_from_jellyfin(movie_data):
    provider_ids = movie_data.get('ProviderIds', {})
    return provider_ids.get('Tmdb')

def fetch_movie_links_from_tmdb_id(tmdb_id):
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

def fetch_movie_links(movie_data, service):
    tmdb_id = None
    if service == 'plex' and PLEX_AVAILABLE:
        tmdb_id = get_tmdb_id_from_plex(movie_data)
    elif service == 'jellyfin' and JELLYFIN_AVAILABLE:
        tmdb_id = get_tmdb_id_from_jellyfin(movie_data)
    else:
        print(f"Unsupported or unavailable service: {service}")
        return None, None, None

    return fetch_movie_links_from_tmdb_id(tmdb_id)
