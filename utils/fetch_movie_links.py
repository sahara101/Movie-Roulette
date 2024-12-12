import os
import json
import requests
from plexapi.server import PlexServer
from utils.settings import settings
import logging
from functools import lru_cache
from utils.tmdb_service import tmdb_service
from threading import Lock

logger = logging.getLogger(__name__)

# Add cache for TMDb IDs
TMDB_ID_CACHE = {}
TMDB_ID_CACHE_LOCK = Lock()
BATCH_SIZE = 20  # Process movies in batches

def initialize_services():
    """Initialize services based on settings"""
    global PLEX_AVAILABLE, JELLYFIN_AVAILABLE, plex, PLEX_MOVIE_LIBRARIES

    # Get settings
    plex_settings = settings.get('plex', {})
    jellyfin_settings = settings.get('jellyfin', {})

    # First check ENV variables for Plex
    plex_url = os.getenv('PLEX_URL')
    plex_token = os.getenv('PLEX_TOKEN')
    plex_libraries = os.getenv('PLEX_MOVIE_LIBRARIES')

    # If not in ENV, check settings
    if not all([plex_url, plex_token, plex_libraries]):
        plex_url = plex_settings.get('url')
        plex_token = plex_settings.get('token')
        plex_libraries = plex_settings.get('movie_libraries')

    # Set PLEX_AVAILABLE based on having all required config
    PLEX_AVAILABLE = bool(plex_url and plex_token and plex_libraries)

    JELLYFIN_AVAILABLE = (
        bool(jellyfin_settings.get('enabled')) or
        all([
            os.getenv('JELLYFIN_URL'),
            os.getenv('JELLYFIN_API_KEY'),
            os.getenv('JELLYFIN_USER_ID')
        ])
    )

    if PLEX_AVAILABLE:
        try:
            # Convert libraries to list if it's a string
            if isinstance(plex_libraries, str):
                PLEX_MOVIE_LIBRARIES = plex_libraries.split(',')
            else:
                PLEX_MOVIE_LIBRARIES = plex_libraries

            # Clean up library names
            PLEX_MOVIE_LIBRARIES = [lib.strip() for lib in PLEX_MOVIE_LIBRARIES if lib.strip()]

            # Initialize Plex
            plex = PlexServer(plex_url, plex_token)
            logger.info(f"Plex initialized with URL: {plex_url}, Libraries: [REDACTED]")
        except Exception as e:
            logger.error(f"Error initializing Plex: {e}")
            PLEX_AVAILABLE = False
            plex = None
            PLEX_MOVIE_LIBRARIES = []
    else:
        plex = None
        PLEX_MOVIE_LIBRARIES = []

# Initialize global variables
PLEX_AVAILABLE = False
JELLYFIN_AVAILABLE = False
plex = None
PLEX_MOVIE_LIBRARIES = []

# Initialize services
initialize_services()

@lru_cache(maxsize=1000)
def get_tmdb_id_from_plex(movie_id, title):
    """Cached TMDb ID lookup from Plex"""
    cache_key = f"{movie_id}:{title}"
    
    with TMDB_ID_CACHE_LOCK:
        if cache_key in TMDB_ID_CACHE:
            return TMDB_ID_CACHE[cache_key]

    if not PLEX_AVAILABLE or not plex:
        return None

    try:
        for library_name in PLEX_MOVIE_LIBRARIES:
            try:
                library = plex.library.section(library_name.strip())
                # Try by ID first
                try:
                    movie = library.fetchItem(int(movie_id))
                    for guid in movie.guids:
                        if 'tmdb://' in guid.id:
                            tmdb_id = guid.id.split('//')[1]
                            TMDB_ID_CACHE[cache_key] = tmdb_id
                            return tmdb_id
                except Exception:
                    pass

                # Fallback to title search
                movie = library.get(title)
                for guid in movie.guids:
                    if 'tmdb://' in guid.id:
                        tmdb_id = guid.id.split('//')[1]
                        TMDB_ID_CACHE[cache_key] = tmdb_id
                        return tmdb_id
            except Exception as e:
                logger.debug(f"Error searching in library {library_name}: {e}")
                continue
    except Exception as e:
        logger.error(f"Error getting TMDB ID from Plex: {e}")
    
    TMDB_ID_CACHE[cache_key] = None
    return None

def get_tmdb_id_from_jellyfin(movie_data):
    """Get TMDb ID from Jellyfin provider IDs"""
    provider_ids = movie_data.get('ProviderIds', {})
    return provider_ids.get('Tmdb')

@lru_cache(maxsize=1000)
def fetch_movie_links_from_tmdb_id(tmdb_id):
    """Cached version of link fetching with optimized Trakt request"""
    if not tmdb_id:
        return None, None, None

    tmdb_url = f"https://www.themoviedb.org/movie/{tmdb_id}"

    try:
        # Get TMDB details and Trakt info in parallel
        movie = tmdb_service.get_movie_details(tmdb_id)
        if not movie:
            return tmdb_url, None, None

        imdb_id = movie.get('imdb_id')
        imdb_url = f"https://www.imdb.com/title/{imdb_id}" if imdb_id else None

        # Optimized Trakt lookup
        trakt_url = None
        trakt_client_id = os.getenv('TRAKT_CLIENT_ID', '')
        if trakt_client_id:
            try:
                response = requests.get(
                    f"https://api.trakt.tv/search/tmdb/{tmdb_id}?type=movie",
                    headers={
                        'Content-Type': 'application/json',
                        'trakt-api-version': '2',
                        'trakt-api-key': trakt_client_id
                    },
                    timeout=2  # Add timeout
                )
                if response.ok and response.json():
                    trakt_id = response.json()[0]['movie']['ids']['slug']
                    trakt_url = f"https://trakt.tv/movies/{trakt_id}"
            except (requests.RequestException, KeyError, IndexError) as e:
                logger.debug(f"Trakt lookup failed for TMDb ID {tmdb_id}: {e}")

        return tmdb_url, trakt_url, imdb_url
    except Exception as e:
        logger.error(f"Error fetching movie links for TMDb ID {tmdb_id}: {e}")
        return tmdb_url, None, None

def fetch_movie_links(movie_data, service):
    """Optimized function to fetch movie links using centralized TMDB service"""
    # Use TMDb ID if available
    tmdb_id = movie_data.get('tmdb_id')

    if not tmdb_id:
        # Only lookup if necessary
        if service == 'plex' and PLEX_AVAILABLE:
            tmdb_id = get_tmdb_id_from_plex(movie_data.get('id'), movie_data.get('title'))
        elif service == 'jellyfin' and JELLYFIN_AVAILABLE:
            tmdb_id = get_tmdb_id_from_jellyfin(movie_data)

    if tmdb_id:
        logger.debug(f"Found TMDb ID {tmdb_id} for movie {movie_data.get('title', '')}")
        return tmdb_service.get_movie_links(tmdb_id)
    
    logger.debug(f"No TMDb ID found for movie {movie_data.get('title', '')}")
    return None, None, None
