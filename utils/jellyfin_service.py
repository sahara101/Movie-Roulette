import os
import requests
import json
import logging
import random
import time
import threading
from threading import Thread, Lock
from datetime import datetime, timedelta
from .settings import settings

from utils.path_manager import path_manager
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class JellyfinService:
    def __init__(self, url=None, api_key=None, user_id=None, update_interval=600):
        # Try settings first, then fall back to ENV
        self.server_url = url or settings.get('jellyfin', 'url') or os.getenv('JELLYFIN_URL')
        self.api_key = api_key or settings.get('jellyfin', 'api_key') or os.getenv('JELLYFIN_API_KEY')
        self.user_id = user_id or settings.get('jellyfin', 'user_id') or os.getenv('JELLYFIN_USER_ID')

        # Only validate if service is enabled
        if settings.get('jellyfin', 'enabled'):
            if not all([self.server_url, self.api_key, self.user_id]):
                raise ValueError("Jellyfin URL, API key, and user ID are required when enabled")

        # Initialize headers
        self.headers = {
            'X-Emby-Token': self.api_key,
            'Content-Type': 'application/json'
        }

        self.update_interval = update_interval
        self.last_cache_update = 0
        self.cache_path = path_manager.get_path('jellyfin_movies')
        self.is_updating = False
        self._cache_lock = threading.Lock()
        self.running = False
        self._start_cache_updater()

        self.playback_start_times = {}

    def _start_cache_updater(self):
        """Start the cache updater thread"""
        self.running = True
        Thread(target=self._update_loop, daemon=True).start()
        logger.info("Jellyfin cache updater thread started")

    def stop_cache_updater(self):
        """Stop the cache updater thread"""
        self.running = False

    def _update_loop(self):
        """Background thread that periodically updates the cache"""
        while self.running:
            try:
                current_time = time.time()
                if current_time - self.last_cache_update >= self.update_interval:
                    with self._cache_lock:
                        logger.info("Starting Jellyfin cache update")
                        self.cache_all_jellyfin_movies()
                        self.last_cache_update = current_time
                        logger.info("Jellyfin cache update completed")
                time.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Error in Jellyfin cache update loop: {e}")
                time.sleep(5)  # Short sleep on error

    def cache_all_jellyfin_movies(self):
        """Cache all movies for Jellyfin badge checking"""
        if self.is_updating:
            logger.info("Jellyfin cache update already in progress, skipping")
            return

        try:
            self.is_updating = True
            movies_url = f"{self.server_url}/Users/{self.user_id}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'Fields': 'ProviderIds'
            }
            response = requests.get(movies_url, headers=self.headers, params=params)
            response.raise_for_status()
            movies = response.json().get('Items', [])

            all_movies = []
            for movie in movies:
                all_movies.append({
                    "jellyfin_id": movie['Id'],
                    "tmdb_id": movie.get('ProviderIds', {}).get('Tmdb')  # This can be None
                })

            # Save to disk atomically
            temp_path = f"{self.cache_path}.tmp"
            with open(temp_path, 'w') as f:
                json.dump(all_movies, f)
            os.replace(temp_path, self.cache_path)

            logger.info(f"Cached {len(all_movies)} total Jellyfin movies")
            return all_movies
        except Exception as e:
            logger.error(f"Error caching all Jellyfin movies: {e}")
            return []
        finally:
            self.is_updating = False

    def get_unwatched_count(self):
        """Get count of unwatched movies"""
        try:
            movies_url = f"{self.server_url}/Users/{self.user_id}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'IsPlayed': 'false'  # Get only unwatched movies
            }
            response = requests.get(movies_url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get('TotalRecordCount', 0)
        except Exception as e:
            logger.error(f"Error getting unwatched count: {e}")
            return 0

    def get_random_movie(self, watch_status='unwatched'):
        try:
            movies_url = f"{self.server_url}/Users/{self.user_id}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'SortBy': 'Random',
                'Limit': '1',
                'Fields': 'Overview,People,Genres,CommunityRating,RunTimeTicks,ProviderIds,UserData,OfficialRating',
                'IsPlayed': 'false'
            }

            # Handle watch status
            if watch_status == 'unwatched':
                params['IsPlayed'] = 'false'
            elif watch_status == 'watched':
                params['IsPlayed'] = 'true'

            response = requests.get(movies_url, headers=self.headers, params=params)
            response.raise_for_status()
            movies = response.json()

            if movies.get('Items'):
                movie_data = self.get_movie_data(movies['Items'][0])
                logger.debug(f"Fetched unwatched movie data: {movie_data}")
                return movie_data
            logger.warning("No unwatched movies found")
            return None
        except Exception as e:
            logger.error(f"Error fetching random unwatched movie: {e}")
            return None

    def filter_movies(self, genres=None, years=None, pg_ratings=None, watch_status='unwatched'):
        try:
            movies_url = f"{self.server_url}/Users/{self.user_id}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'SortBy': 'Random',
                'Limit': '1',
                'Fields': 'Overview,People,Genres,RunTimeTicks,ProviderIds,UserData,OfficialRating',
                'IsPlayed': 'false'
            }

            # Handle watch status
            if watch_status == 'unwatched':
                params['IsPlayed'] = 'false'
            elif watch_status == 'watched':
                params['IsPlayed'] = 'true'

            # Handle empty lists as None
            genres = genres if genres and genres[0] else None
            years = years if years and years[0] else None
            pg_ratings = pg_ratings if pg_ratings and pg_ratings[0] else None

            if genres:
                params['Genres'] = genres
            if years:
                params['Years'] = years
            if pg_ratings:
                params['OfficialRatings'] = pg_ratings

            logger.debug(f"Jellyfin API request params: {params}")

            response = requests.get(movies_url, headers=self.headers, params=params)
            response.raise_for_status()
            movies = response.json().get('Items', [])

            logger.debug(f"Jellyfin API returned {len(movies)} movies")

            # If no movies are returned, we can't proceed
            if not movies:
                logger.warning("No unwatched movies found matching the criteria")
                return None

            # Randomly select a movie from the returned list
            chosen_movie = random.choice(movies)
            return self.get_movie_data(chosen_movie)
        except Exception as e:
            logger.error(f"Error filtering movies: {str(e)}")
            return None

    def movie_matches_criteria(self, movie, genres, years, pg_ratings):
        if genres and not any(genre in movie.get('Genres', []) for genre in genres):
            return False
        if years and str(movie.get('ProductionYear', '')) not in years:
            return False
        if pg_ratings and movie.get('OfficialRating', '') not in pg_ratings:
            return False
        return True

    def get_movie_data(self, movie):
        run_time_ticks = movie.get('RunTimeTicks', 0)
        total_minutes = run_time_ticks // 600000000  # Convert ticks to minutes
        hours = total_minutes // 60
        minutes = total_minutes % 60

        # Extract video format information
        video_format = "Unknown"
        audio_format = "Unknown"

        if 'MediaSources' in movie and movie['MediaSources']:
            media_sources = movie['MediaSources']
            if media_sources and isinstance(media_sources, list):
                media_source = media_sources[0]

                if 'MediaStreams' in media_source:
                    # Video format extraction
                    video_streams = [s for s in media_source['MediaStreams'] if s['Type'] == 'Video']
                    if video_streams:
                        video_stream = video_streams[0]
                        height = video_stream.get('Height', 0)

                        if height <= 480:
                            resolution = "SD"
                        elif height <= 720:
                            resolution = "HD"
                        elif height <= 1080:
                            resolution = "FHD"
                        elif height > 1080:
                            resolution = "4K"
                        else:
                            resolution = "Unknown"

                        hdr_types = []
                        if video_stream.get('VideoRange') == 'HDR':
                            if 'DV' in video_stream.get('Title', ''):
                                hdr_types.append('DV')
                            if video_stream.get('VideoRangeType') == 'HDR10':
                                hdr_types.append('HDR10')
                            elif video_stream.get('VideoRangeType') == 'HDR10+':
                                hdr_types.append('HDR10+')
                            elif not hdr_types:  # If no specific type is identified, just add HDR
                                hdr_types.append('HDR')

                        video_format_parts = [resolution]
                        if hdr_types:
                            video_format_parts.append('/'.join(hdr_types))

                        video_format = ' '.join(video_format_parts)

                    # Audio format extraction
                    audio_streams = [s for s in media_source['MediaStreams'] if s['Type'] == 'Audio']
                    if audio_streams:
                        audio_stream = audio_streams[0]

                        # Start with the Profile information
                        profile = audio_stream.get('Profile', '')
                        if profile:
                            # Split the profile into its components
                            profile_parts = [part.strip() for part in profile.split('+')]

                            # Remove redundant "Dolby" from TrueHD if Atmos is present
                            if "Dolby TrueHD" in profile_parts and "Dolby Atmos" in profile_parts:
                                profile_parts = ["TrueHD" if part == "Dolby TrueHD" else part for part in profile_parts]

                            audio_format = ' + '.join(profile_parts)
                        else:
                            # Fallback to Codec if Profile is not available
                            codec = audio_stream.get('Codec', '').upper()
                            codec_map = {
                                'AC3': 'Dolby Digital',
                                'EAC3': 'Dolby Digital Plus',
                                'TRUEHD': 'Dolby TrueHD',
                                'DTS': 'DTS',
                                'DTSHD': 'DTS-HD',
                                'AAC': 'AAC',
                                'FLAC': 'FLAC'
                            }
                            audio_format = codec_map.get(codec, codec)

                        # Add layout if available and not already included
                        layout = audio_stream.get('Layout', '')
                        if layout and layout not in audio_format:
                            audio_format += f" {layout}"

                        # Remove any duplicate words
                        parts = audio_format.split()
                        audio_format = ' '.join(dict.fromkeys(parts))

        # Get all people and process them by type
        all_people = movie.get('People', [])
    
        directors = [
            {
                "name": p.get('Name', ''),
                "id": p.get('ProviderIds', {}).get('Tmdb'),
                "type": "director",
                "job": p.get('Role', ''),
                "department": "Directing"
            }
            for p in all_people if p.get('Type') == 'Director'
        ]

        writers = [
            {
                "name": p.get('Name', ''),
                "id": p.get('ProviderIds', {}).get('Tmdb'),
                "type": "writer",
                "job": p.get('Role', ''),
                "department": "Writing"
            }
            for p in all_people if p.get('Type') == 'Writer'
        ]

        actors = [
            {
                "name": p.get('Name', ''),
                "id": p.get('ProviderIds', {}).get('Tmdb'),
                "type": "actor",
                "character": p.get('Role', ''),
                "department": "Acting"
            }
            for p in all_people if p.get('Type') == 'Actor'
        ]

        return {
            "id": movie.get('Id', ''),
            "title": movie.get('Name', ''),
            "year": movie.get('ProductionYear', ''),
            "duration_hours": hours,
            "duration_minutes": minutes,
            "description": movie.get('Overview', ''),
            "genres": movie.get('Genres', []),
            "poster": f"{self.server_url}/Items/{movie['Id']}/Images/Primary?api_key={self.api_key}",
            "background": f"{self.server_url}/Items/{movie['Id']}/Images/Backdrop?api_key={self.api_key}" if movie.get('BackdropImageTags') else None,
            "ProviderIds": movie.get('ProviderIds', {}),
            "contentRating": movie.get('OfficialRating', ''),
            "videoFormat": video_format,
            "audioFormat": audio_format,
            "tmdb_id": movie.get('ProviderIds', {}).get('Tmdb'),
            # Return enriched data for all roles
            "directors_enriched": directors,
            "writers_enriched": writers,
            "actors_enriched": actors,
            # Keep original arrays for backwards compatibility
            "directors": [d["name"] for d in directors],
            "writers": [w["name"] for w in writers],
            "actors": [a["name"] for a in actors]
        }

    def get_genres(self):
        try:
            items_url = f"{self.server_url}/Items"
            params = {
                'Recursive': 'true',
                'Fields': 'Genres',
                'IncludeItemTypes': 'Movie'
            }

            response = requests.get(items_url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()

            all_genres = set()
            for item in data.get('Items', []):
                all_genres.update(item.get('Genres', []))

            genre_list = sorted(list(all_genres))
            logger.debug(f"Extracted genre list: {genre_list}")
            return genre_list
        except Exception as e:
            logger.error(f"Error fetching genres: {e}")
            return []

    def get_years(self):
        try:
            movies_url = f"{self.server_url}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'Fields': 'ProductionYear'
            }
            response = requests.get(movies_url, headers=self.headers, params=params)
            response.raise_for_status()
            movies = response.json()
            years = set(movie.get('ProductionYear') for movie in movies.get('Items', []) if movie.get('ProductionYear'))
            year_list = sorted(list(years), reverse=True)
            logger.debug(f"Fetched years: {year_list}")
            return year_list
        except Exception as e:
            logger.error(f"Error fetching years: {e}")
            return []

    def get_pg_ratings(self):
        try:
            items_url = f"{self.server_url}/Items"
            params = {
                'Recursive': 'true',
                'Fields': 'OfficialRating',
                'IncludeItemTypes': 'Movie'
            }

            response = requests.get(items_url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()

            all_ratings = set()
            for item in data.get('Items', []):
                rating = item.get('OfficialRating')
                if rating:
                    all_ratings.add(rating)

            rating_list = sorted(list(all_ratings))
            logger.debug(f"Extracted PG rating list: {rating_list}")
            return rating_list
        except Exception as e:
            logger.error(f"Error fetching PG ratings: {e}")
            return []

    def get_playback_info(self, item_id):
        try:
            sessions_url = f"{self.server_url}/Sessions"
            response = requests.get(sessions_url, headers=self.headers)
            response.raise_for_status()
            sessions = response.json()
            for session in sessions:
                if session.get('NowPlayingItem', {}).get('Id') == item_id:
                    playstate = session.get('PlayState', {})
                    position_ticks = playstate.get('PositionTicks', 0)
                    is_paused = playstate.get('IsPaused', False)

                    position_seconds = position_ticks / 10_000_000
                    total_duration = session['NowPlayingItem']['RunTimeTicks'] / 10_000_000

                    # Use stored start time or current time if not available
                    if item_id not in self.playback_start_times:
                        self.playback_start_times[item_id] = datetime.now()

                    start_time = self.playback_start_times[item_id]
                    end_time = start_time + timedelta(seconds=total_duration)

                    # Check if the session is inactive or if NowPlayingItem is None
                    is_stopped = session.get('PlayState', {}).get('PlayMethod') is None or session.get('NowPlayingItem') is None

                    return {
                        'is_playing': not is_paused and not is_stopped,
                        'IsPaused': is_paused,
                        'IsStopped': is_stopped,
                        'position': position_seconds,
                        'start_time': start_time.isoformat(),
                        'end_time': end_time.isoformat(),
                        'duration': total_duration
                    }
            # If we didn't find a matching session, the movie is stopped
            return {
                'is_playing': False,
                'IsPaused': False,
                'IsStopped': True,
                'position': 0,
                'start_time': None,
                'end_time': None,
                'duration': 0
            }
        except requests.RequestException as e:
            logger.error(f"Error fetching playback info: {e}")
        return None

    def get_clients(self):
        try:
            sessions_url = f"{self.server_url}/Sessions"
            response = requests.get(sessions_url, headers=self.headers)
            response.raise_for_status()
            sessions = response.json()

            logger.debug(f"Raw sessions data: {json.dumps(sessions, indent=2)}")

            castable_clients = []
            for session in sessions:
                if session.get('SupportsRemoteControl', False) and session.get('DeviceName') != 'Jellyfin Server':
                    client = {
                        "title": session.get('DeviceName', 'Unknown Device'),
                        "id": session.get('Id'),
                        "client": session.get('Client'),
                        "username": session.get('UserName'),
                        "device_id": session.get('DeviceId'),
                        "supports_media_control": session.get('SupportsMediaControl', False),
                    }
                    castable_clients.append(client)

            if not castable_clients:
                logger.warning("No castable clients found.")
            else:
                logger.info(f"Found {len(castable_clients)} castable clients")

            logger.debug(f"Fetched castable clients: {json.dumps(castable_clients, indent=2)}")
            return castable_clients
        except Exception as e:
            logger.error(f"Error fetching clients: {e}")
            return []

    def get_movie_by_id(self, movie_id):
        try:
            item_url = f"{self.server_url}/Users/{self.user_id}/Items/{movie_id}"
            params = {
                'Fields': 'Overview,People,Genres,RunTimeTicks,ProviderIds,UserData,OfficialRating'
            }
            response = requests.get(item_url, headers=self.headers, params=params)
            response.raise_for_status()
            movie = response.json()
            return self.get_movie_data(movie)
        except Exception as e:
            logger.error(f"Error fetching movie by ID: {e}")
            return None

    def get_current_playback(self):
        try:
            sessions_url = f"{self.server_url}/Sessions"
            response = requests.get(sessions_url, headers=self.headers)
            response.raise_for_status()
            sessions_json = response.json()
            logger.debug(f"Sessions JSON Response: {json.dumps(sessions_json, indent=2)}")

            # Check if the response is a list
            if isinstance(sessions_json, list):
                sessions = sessions_json
            elif isinstance(sessions_json, dict):
                sessions = sessions_json.get('Items', [])
            else:
                logger.error("Unexpected JSON structure for sessions.")
                return None

            for session in sessions:
                if not isinstance(session, dict):
                    logger.warning("Session item is not a dictionary. Skipping.")
                    continue

                now_playing = session.get('NowPlayingItem')
                if now_playing:
                    return {
                        'id': now_playing.get('Id'),
                        'position': session.get('PlayState', {}).get('PositionTicks', 0) / 10_000_000  # Convert ticks to seconds
                    }
            return None
        except Exception as e:
            logger.error(f"Error fetching current playback: {e}")
            return None

    def play_movie(self, movie_id, session_id):
        try:
            playback_url = f"{self.server_url}/Sessions/{session_id}/Playing"
            params = {
                'ItemIds': movie_id,
                'PlayCommand': 'PlayNow'
            }
            response = requests.post(playback_url, headers=self.headers, params=params)
            response.raise_for_status()
            logger.debug(f"Playing movie {movie_id} on session {session_id}")
            logger.debug(f"Response: {response.text}")

            # Set the start time for the movie
            self.playback_start_times[movie_id] = datetime.now()

            # Fetch movie data
            movie_data = self.get_movie_by_id(movie_id)
            if movie_data:
                start_time = self.playback_start_times[movie_id]
                end_time = start_time + timedelta(hours=movie_data['duration_hours'], minutes=movie_data['duration_minutes'])

                from flask import session
                session['current_movie'] = movie_data
                session['movie_start_time'] = start_time.isoformat()
                session['movie_end_time'] = end_time.isoformat()
                session['current_service'] = 'jellyfin'

            return {
                "status": "playing",
                "response": response.text,
                "movie_id": movie_id,
                "session_id": session_id,
                "start_time": self.playback_start_times[movie_id].isoformat(),
                "movie_data": movie_data
            }
        except Exception as e:
            logger.error(f"Error playing movie: {e}")
            return {"error": str(e)}

    def get_active_sessions(self):
        try:
            sessions_url = f"{self.server_url}/Sessions"
            response = requests.get(sessions_url, headers=self.headers)
            response.raise_for_status()
            sessions = response.json()

            active_sessions = []
            for session in sessions:
                if session.get('NowPlayingItem'):
                    active_sessions.append(session)

            logger.debug(f"Found {len(active_sessions)} active Jellyfin sessions")
            return active_sessions
        except Exception as e:
            logger.error(f"Error fetching active Jellyfin sessions: {e}")
            return []

    def get_current_username(self):
        try:
            sessions_url = f"{self.server_url}/Sessions"
            response = requests.get(sessions_url, headers=self.headers)
            response.raise_for_status()
            sessions = response.json()
            for session in sessions:
                if session.get('NowPlayingItem'):
                    return session.get('UserName')
            return None
        except Exception as e:
            logger.error(f"Error getting current Jellyfin username: {e}")
            return None

    def search_movies(self, query):
        """Search for movies matching the query in titles only"""
        try:
            movies_url = f"{self.server_url}/Users/{self.user_id}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'SearchTerm': query,
                'Fields': 'Overview,People,Genres,MediaSources,MediaStreams,RunTimeTicks,ProviderIds,UserData,OfficialRating,ProductionYear',
                'SearchFields': 'Name',
                'EnableTotalRecordCount': True,
                'Limit': 50
            }

            logger.info(f"Searching Jellyfin movies with query: {query}")
            response = requests.get(movies_url, headers=self.headers, params=params)
            response.raise_for_status()
            movies = response.json().get('Items', [])

            # Double check title match and process results
            results = []
            for movie in movies:
                if query.lower() in movie.get('Name', '').lower():
                    movie_data = self.get_movie_data(movie)
                    results.append(movie_data)

            logger.info(f"Found {len(results)} Jellyfin movies matching title: {query}")
            return results

        except Exception as e:
            logger.error(f"Error searching Jellyfin movies: {str(e)}")
            return []
