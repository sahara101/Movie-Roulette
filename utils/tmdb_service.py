import os
import logging
import requests
import json
from functools import lru_cache
from utils.settings import settings

logger = logging.getLogger(__name__)

class TMDBService:
    """Centralized service for TMDB API operations"""

    # Built-in API key - replace with your actual key
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
        # Clear new collection-related caches
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
        # Check environment variable first
        env_key = os.getenv('TMDB_API_KEY')
        if env_key:
            logger.debug("Using TMDB API key from environment")
            return env_key

        # Check user configuration
        tmdb_settings = settings.get('tmdb', {})
        if tmdb_settings.get('enabled') and tmdb_settings.get('api_key'):
            logger.debug("Using TMDB API key from user settings")
            return tmdb_settings['api_key']

        # Fall back to built-in key
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
            # Get basic person details
            data = self._make_request(f"person/{person_id}")
            if data:
                # Get external IDs in a separate request
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
        return self._make_request(f"movie/{movie_id}")

    @lru_cache(maxsize=100)
    def get_movie_credits(self, movie_id):
        """Get cast and crew information for a movie"""
        logger.debug(f"Getting movie credits for ID: {movie_id}")
        try:
            data = self._make_request(f"movie/{movie_id}/credits")
            if data and 'crew' in data:
                # Debug log to see all unique job types in crew
                jobs = set(member['job'] for member in data['crew'])
                logger.debug(f"Found job types in crew: {jobs}")
            return data
        except Exception as e:
            logger.error(f"Error getting movie credits: {e}")
            return None

    @lru_cache(maxsize=100)
    def get_person_movies(self, person_id):
        """Get complete filmography for a person"""
        try:
            movie_credits_url = f"person/{person_id}/movie_credits"
            credits = self._make_request(movie_credits_url)

            if credits:
                movies = []

                # Add crew credits with department info
                if 'crew' in credits:
                    for crew_entry in credits['crew']:
                        if crew_entry.get('media_type') == 'movie':
                            movies.append({
                                **crew_entry,
                                'department': crew_entry.get('department', ''),
                                'job': crew_entry.get('job', '')
                            })

                # Add cast credits
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

        # Try to get Trakt URL
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

    # New collection-related methods
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

# Create a singleton instance
tmdb_service = TMDBService()
