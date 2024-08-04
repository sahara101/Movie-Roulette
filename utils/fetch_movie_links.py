import os
import requests

# Check which services are available
PLEX_AVAILABLE = all([os.getenv('PLEX_URL'), os.getenv('PLEX_TOKEN'), os.getenv('MOVIES_LIBRARY_NAME')])
JELLYFIN_AVAILABLE = all([os.getenv('JELLYFIN_URL'), os.getenv('JELLYFIN_API_KEY')])

if not (PLEX_AVAILABLE or JELLYFIN_AVAILABLE):
    raise EnvironmentError("At least one service (Plex or Jellyfin) must be configured.")

# Initialize Plex if available
if PLEX_AVAILABLE:
    from plexapi.server import PlexServer
    PLEX_URL = os.getenv('PLEX_URL')
    PLEX_TOKEN = os.getenv('PLEX_TOKEN')
    MOVIES_LIBRARY_NAME = os.getenv('MOVIES_LIBRARY_NAME', 'Movies')  # Default to 'Movies' if not set
    plex = PlexServer(PLEX_URL, PLEX_TOKEN)

def get_tmdb_id_from_plex(movie_data):
    if not PLEX_AVAILABLE:
        return None
    try:
        movies_library = plex.library.section(MOVIES_LIBRARY_NAME)
        movie = movies_library.get(movie_data['title'])
        for guid in movie.guids:
            if 'tmdb://' in guid.id:
                return guid.id.split('//')[1]
    except Exception as e:
        print(f"Error getting TMDB ID from Plex: {e}")
    return None

def fetch_movie_links_plex(movie_data):
    if not PLEX_AVAILABLE:
        return None, None, None
    tmdb_id = get_tmdb_id_from_plex(movie_data)
    return fetch_movie_links_from_tmdb_id(tmdb_id)

def fetch_movie_links_jellyfin(movie_data):
    if not JELLYFIN_AVAILABLE:
        return None, None, None
    provider_ids = movie_data.get('ProviderIds', {})
    tmdb_id = provider_ids.get('Tmdb')
    return fetch_movie_links_from_tmdb_id(tmdb_id)

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
    if service == 'plex' and PLEX_AVAILABLE:
        return fetch_movie_links_plex(movie_data)
    elif service == 'jellyfin' and JELLYFIN_AVAILABLE:
        return fetch_movie_links_jellyfin(movie_data)
    else:
        print(f"Unsupported or unavailable service: {service}")
        return None, None, None
