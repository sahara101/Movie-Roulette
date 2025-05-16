import os
import logging
import requests
import json
from functools import lru_cache
from utils.settings import settings

logger = logging.getLogger(__name__)

class TMDBService:
    """Centralized service for TMDB API operations"""

    DEFAULT_API_KEY = "896235c937dfa129af11760d5e57c366"
    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(self):
        self.initialize_service()

    def initialize_service(self):
        """Initialize or reinitialize service with current settings"""
        self._clear_caches()
        logger.info("TMDB service initialized")

    def _clear_caches(self):
        """Clear all cached data"""
        self.get_api_key.cache_clear()
        self.search_person.cache_clear()
        self.get_person_details.cache_clear()
        self.get_movie_details.cache_clear()
        self.get_movie_credits.cache_clear()
        self.get_configuration.cache_clear() 
        if hasattr(self, 'get_collection_details'):
            self.get_collection_details.cache_clear()
        if hasattr(self, 'get_movie_collection_info'):
            self.get_movie_collection_info.cache_clear()

    def clear_cache(self):
        """Public method to clear all caches"""
        self._clear_caches()

    @lru_cache(maxsize=1)
    def get_api_key(self):
        """Get the TMDB API key with priority:
        1. Environment variable
        2. User configured key (if enabled)
        3. Built-in key
        """
        env_key = os.getenv('TMDB_API_KEY')
        if env_key:
            logger.debug("Using TMDB API key from environment")
            return env_key

        tmdb_settings = settings.get('tmdb', {})
        if tmdb_settings.get('enabled') and tmdb_settings.get('api_key'):
            logger.debug("Using TMDB API key from user settings")
            return tmdb_settings['api_key']

        logger.debug("Using built-in TMDB API key")
        return self.DEFAULT_API_KEY

    @lru_cache(maxsize=100)
    def get_movie_cast(self, tmdb_id):
        """Get the correct cast for a movie using its TMDB ID"""
        try:
            credits = self._make_request(f"movie/{tmdb_id}/credits")
            if credits and 'cast' in credits:
                return {
                    'cast': credits['cast'],
                    'crew': credits.get('crew', [])
                }
            return None
        except Exception as e:
            logger.error(f"Error getting movie cast: {e}")
            return None

    def get_person_external_ids(self, person_id):
        """Get external IDs for a person"""
        logger.debug(f"Getting external IDs for person ID: {person_id}")
        return self._make_request(f"person/{person_id}/external_ids")

    @lru_cache(maxsize=100)
    def get_person_details_with_external_ids(self, person_id):
        """Get detailed information about a person including IMDb ID"""
        logger.debug(f"Getting person details with external IDs for ID: {person_id}")
        try:
            data = self._make_request(f"person/{person_id}")
            if data:
                external_ids = self.get_person_external_ids(person_id)

                return {
                    'id': data.get('id'),
                    'name': data.get('name'),
                    'profile_path': data.get('profile_path'),
                    'biography': data.get('biography'),
                    'known_for_department': data.get('known_for_department'),
                    'imdb_id': external_ids.get('imdb_id') if external_ids else None
                }
            return None
        except Exception as e:
            logger.error(f"Error getting person details with external IDs: {e}")
            return None

    def get_person_links(self, person_id):
        """Get TMDB and IMDB URLs for a person"""
        person = self.get_person_details_with_external_ids(person_id)
        if not person:
            return None, None

        tmdb_url = f"https://www.themoviedb.org/person/{person_id}"
        imdb_id = person.get('imdb_id')
        imdb_url = f"https://www.imdb.com/name/{imdb_id}" if imdb_id else None

        return tmdb_url, imdb_url

    def _make_request(self, endpoint, params=None):
        """Make a request to TMDB API with proper error handling"""
        if params is None:
            params = {}

        params['api_key'] = self.get_api_key()
        url = f"{self.BASE_URL}/{endpoint}"

        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error making TMDB request to {endpoint}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error making TMDB request to {endpoint}: {e}")
            return None

    @lru_cache(maxsize=100)
    def search_person(self, name):
        """Search for a person by name"""
        logger.debug(f"Searching for person: {name}")
        data = self._make_request("search/person", {"query": name})
        if data and data.get('results'):
            return data['results'][0]
        return None

    @lru_cache(maxsize=100)
    def get_person_details_with_credits(self, person_id):
        """Get person details and credits in one call"""
        try:
            person_url = f"{self.BASE_URL}/person/{person_id}"
            credits_url = f"{self.BASE_URL}/person/{person_id}/combined_credits"
            params = {'api_key': self.get_api_key()}

            person_response = requests.get(person_url, params=params)
            person_response.raise_for_status()
            person_data = person_response.json()
            logger.debug(f"TMDb person response for ID {person_id}: {json.dumps(person_data, indent=2)}")

            credits_response = requests.get(credits_url, params=params)
            credits_response.raise_for_status()
            credits_data = credits_response.json()
            logger.debug(f"TMDb credits response for ID {person_id}: {json.dumps(credits_data, indent=2)}")

            person_data['credits'] = credits_data
            return person_data
        except requests.RequestException as e:
            logger.error(f"Error fetching person details for ID {person_id}: {str(e)}")
            if hasattr(e.response, 'text'):
                logger.error(f"Response content: {e.response.text}")
            return None

    @lru_cache(maxsize=100)
    def get_person_details(self, person_id):
        """Get detailed information about a person"""
        logger.debug(f"Getting person details for ID: {person_id}")
        return self._make_request(f"person/{person_id}")

    @lru_cache(maxsize=100)
    def get_movie_details(self, movie_id):
        """Get detailed information about a movie"""
        logger.debug(f"Getting movie details for ID: {movie_id}")
        params = {'append_to_response': 'images'}
        return self._make_request(f"movie/{movie_id}", params=params)

    @lru_cache(maxsize=100)
    def get_movie_credits(self, movie_id):
        """Get cast and crew information for a movie"""
        logger.debug(f"Getting movie credits for ID: {movie_id}")
        try:
            data = self._make_request(f"movie/{movie_id}/credits")
            if data and 'crew' in data:
                jobs = set(member['job'] for member in data['crew'])
                logger.debug(f"Found job types in crew: {jobs}")
            return data
        except Exception as e:
            logger.error(f"Error getting movie credits: {e}")
            return None

    @lru_cache(maxsize=1)
    def get_configuration(self):
        """Fetch and cache the TMDB API configuration"""
        logger.debug("Fetching TMDB API configuration")
        return self._make_request("configuration")

    def get_image_url(self, image_path, size='original'):
        """Construct the full URL for an image given its path and size."""
        if not image_path:
            return None
        config = self.get_configuration()
        if not config or 'images' not in config:
            logger.error("Failed to get TMDB configuration for image URLs")
            return None

        base_url = config['images'].get('secure_base_url', 'https://image.tmdb.org/t/p/')
        
        possible_size_keys = ['backdrop_sizes', 'poster_sizes', 'profile_sizes', 'logo_sizes']
        image_size = size
        
        found_specific_size = False
        for size_key in possible_size_keys:
            if size in config['images'].get(size_key, []):
                image_size = size
                found_specific_size = True
                break
        
        if not found_specific_size and size != 'original':
            pass


        return f"{base_url}{image_size}{image_path}"

    @lru_cache(maxsize=10)
    def get_popular_movies(self, page=1):
        """Get a list of popular movies from TMDB."""
        logger.debug(f"Fetching popular movies, page {page}")
        data = self._make_request("movie/popular", {"page": page})
        if data and 'results' in data:
            return data['results']
        return []

    @lru_cache(maxsize=100)
    def get_movie_logo_url(self, movie_id):
        """Get the best available movie logo URL (preferring English or no language)"""
        logger.debug(f"Getting movie logo for ID: {movie_id}")
        details = self.get_movie_details(movie_id) 
        config = self.get_configuration()

        if not details or 'images' not in details or 'logos' not in details['images']:
            logger.warning(f"No image or logo data found for movie ID: {movie_id}")
            return None
        if not config or 'images' not in config:
            logger.error("Failed to get TMDB configuration for image URLs")
            return None

        logos = details['images']['logos']
        if not logos:
            logger.info(f"No logos available in TMDB data for movie ID: {movie_id}")
            return None

        def sort_key(logo):
            lang = logo.get('iso_639_1')
            if lang == 'en':
                return 0 
            elif lang is None or lang == 'null' or lang == '': 
                 return 1 
            else:
                 return 2 

        sorted_logos = sorted(logos, key=sort_key)

        base_url = config['images'].get('secure_base_url', 'https://image.tmdb.org/t/p/')
        logo_sizes = config['images'].get('logo_sizes', ['original'])
        logo_size = 'w500' if 'w500' in logo_sizes else logo_sizes[-1] if logo_sizes else 'original'

        logo_path = sorted_logos[0].get('file_path')

        if logo_path:
            full_logo_url = f"{base_url}{logo_size}{logo_path}"
            logger.info(f"Constructed logo URL for movie ID {movie_id}: {full_logo_url}") 
            return full_logo_url
        else:
            logger.warning(f"Selected logo has no file_path for movie ID: {movie_id}")
            return None

    @lru_cache(maxsize=100)
    def get_person_movies(self, person_id):
        """Get complete filmography for a person"""
        try:
            movie_credits_url = f"person/{person_id}/movie_credits"
            credits = self._make_request(movie_credits_url)

            if credits:
                movies = []

                if 'crew' in credits:
                    for crew_entry in credits['crew']:
                        if crew_entry.get('media_type') == 'movie':
                            movies.append({
                                **crew_entry,
                                'department': crew_entry.get('department', ''),
                                'job': crew_entry.get('job', '')
                            })

                if 'cast' in credits:
                    cast_movies = [
                        {
                            **cast_entry,
                            'department': 'Acting',
                            'job': 'Actor',
                            'character': cast_entry.get('character', '')
                        }
                        for cast_entry in credits['cast']
                        if cast_entry.get('media_type') == 'movie'
                    ]
                    movies.extend(cast_movies)

                return movies
            return None
        except Exception as e:
            logger.error(f"Error getting person movies: {e}")
            return None

    def get_movie_links(self, movie_id):
        """Get TMDB, IMDB and Trakt URLs for a movie"""
        movie = self.get_movie_details(movie_id)
        if not movie:
            return None, None, None

        tmdb_url = f"https://www.themoviedb.org/movie/{movie_id}"
        imdb_id = movie.get('imdb_id')
        imdb_url = f"https://www.imdb.com/title/{imdb_id}" if imdb_id else None

        try:
            trakt_api_url = f"https://api.trakt.tv/search/tmdb/{movie_id}?type=movie"
            headers = {
                'Content-Type': 'application/json',
                'trakt-api-version': '2',
                'trakt-api-key': os.getenv('TRAKT_CLIENT_ID', '')
            }
            response = requests.get(trakt_api_url, headers=headers)
            if response.ok:
                data = response.json()
                if data:
                    trakt_id = data[0]['movie']['ids']['slug']
                    trakt_url = f"https://trakt.tv/movies/{trakt_id}"
                    return tmdb_url, trakt_url, imdb_url
        except Exception as e:
            logger.error(f"Error getting Trakt URL: {e}")

        return tmdb_url, None, imdb_url

    @lru_cache(maxsize=100)
    def get_collection_details(self, collection_id):
        """Get detailed information about a movie collection by ID"""
        logger.debug(f"Getting collection details for ID: {collection_id}")
        return self._make_request(f"collection/{collection_id}")

    @lru_cache(maxsize=100)
    def get_movie_collection_info(self, movie_id):
        """Check if a movie belongs to a collection and return collection info"""
        logger.debug(f"Checking if movie ID {movie_id} belongs to a collection")
        movie = self.get_movie_details(movie_id)
        if movie and movie.get('belongs_to_collection'):
            collection_id = movie['belongs_to_collection']['id']
            return self.get_collection_details(collection_id)
        return None

tmdb_service = TMDBService()
