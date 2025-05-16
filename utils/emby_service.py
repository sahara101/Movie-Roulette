import os
import requests
import json
import logging
import random
import time
import threading
import uuid
from threading import Thread, Lock
from datetime import datetime, timedelta
from .settings import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def authenticate_emby_user(username, password):
   """
   Authenticates a user directly against the configured Emby server.
   Returns (True, auth_data) on success, (False, error_message) on failure.
   auth_data contains {'AccessToken': ..., 'UserId': ...}
   """
   server_url = settings.get('emby', {}).get('url') or os.getenv('EMBY_URL') 
   if not server_url:
       logger.error("Emby server URL is not configured.")
       return False, "Emby server URL is not configured."

   try:

       auth_url = f"{server_url}/Users/AuthenticateByName"
       auth_data = {
           "Username": username,
           "Pw": password,
       }

       device_id = str(uuid.uuid4()) 
       auth_header = (f'MediaBrowser Client="Movie Roulette Auth", '
                      f'Device="Movie Roulette", '
                      f'DeviceId="{device_id}", '
                      f'Version="1.0.0"')

       headers = {
           'X-Emby-Authorization': auth_header,
           'Content-Type': 'application/json',
           'Accept': 'application/json'
       }

       logger.info(f"Attempting Emby authentication for user '{username}' at {server_url}")
       response = requests.post(auth_url, json=auth_data, headers=headers, timeout=10) 

       if response.status_code == 401:
            logger.warning(f"Emby authentication failed for user '{username}': Invalid credentials.")
            return False, "Invalid username or password."
       elif response.status_code == 404: 
            logger.error(f"Emby authentication endpoint not found ({auth_url}). Check Emby server version or URL.")
            return False, "Authentication endpoint not found on Emby server."

       response.raise_for_status() 

       data = response.json()

       if 'AccessToken' not in data or 'User' not in data or 'Id' not in data['User']:
            logger.error(f"Emby authentication response for '{username}' is missing expected fields: {data}")
            return False, "Authentication succeeded but received an unexpected response from Emby."

       auth_result = {
           'AccessToken': data['AccessToken'],
           'UserId': data['User']['Id'],
           'UserName': data['User'].get('Name', username) 
       }

       logger.info(f"Emby authentication successful for user '{username}' (ID: {auth_result['UserId']})")
       return True, auth_result

   except requests.exceptions.Timeout:
       logger.error(f"Timeout connecting to Emby server at {server_url} for authentication.")
       return False, "Connection to Emby server timed out."
   except requests.exceptions.RequestException as e:
       logger.error(f"Error during Emby authentication request for user '{username}': {e}")
       if isinstance(e, requests.exceptions.ConnectionError):
            return False, f"Could not connect to Emby server at {server_url}. Please check the URL and network."
       return False, f"An error occurred communicating with the Emby server: {e}"
   except Exception as e:
       logger.error(f"Unexpected error during Emby authentication for user '{username}': {e}", exc_info=True)
       return False, f"An unexpected error occurred during authentication: {e}"

def authenticate_emby_server_direct(url, username, password):
   """
   Authenticates directly against a specific Emby server URL.
   Used for testing/configuring settings.
   Returns (True, {'api_key': ..., 'user_id': ...}) on success,
   (False, error_message) on failure.
   """
   if not all([url, username, password]):
       return False, "URL, Username, and Password are required"

   try:
       test_auth_url = f"{url.rstrip('/')}/Users/AuthenticateByName"
       test_auth_data = { "Username": username, "Pw": password }
       device_id = str(uuid.uuid4()) 
       auth_header = (f'MediaBrowser Client="Movie Roulette Settings Test", '
                      f'Device="Movie Roulette", DeviceId="{device_id}", Version="1.0.0"')
       headers = {
           'X-Emby-Authorization': auth_header,
           'Content-Type': 'application/json',
           'Accept': 'application/json'
       }

       logger.info(f"Attempting direct Emby authentication to {url} for user {username}")
       response = requests.post(test_auth_url, json=test_auth_data, headers=headers, timeout=10)

       if response.status_code == 200:
            auth_response_data = response.json()
            if 'AccessToken' in auth_response_data and 'User' in auth_response_data and 'Id' in auth_response_data['User']:
                api_key = auth_response_data['AccessToken']
                user_id = auth_response_data['User']['Id']
                logger.info(f"Direct Emby authentication successful for {username} at {url}")
                return True, {'api_key': api_key, 'user_id': user_id}
            else:
                logger.warning(f"Direct Emby authentication to {url} succeeded but response format unexpected: {auth_response_data}")
                return False, "Authentication succeeded but received an unexpected response format from Emby."
       elif response.status_code == 401:
           logger.warning(f"Direct Emby authentication failed for {username} at {url}: Invalid credentials")
           return False, "Invalid username or password"
       elif response.status_code == 404:
            logger.error(f"Direct Emby authentication endpoint not found ({test_auth_url}). Check Emby server URL.")
            return False, "Authentication endpoint not found on Emby server. Check URL."
       else:
           logger.error(f"Direct Emby authentication failed for {username} at {url}: Status {response.status_code}, Response: {response.text[:200]}")
           try:
               response.raise_for_status()
           except requests.exceptions.HTTPError as http_err:
                return False, f"Emby server returned an error: {http_err}"
           return False, f"Emby server returned status code {response.status_code}"

   except requests.exceptions.Timeout:
       logger.error(f"Timeout connecting to Emby server at {url} for direct authentication.")
       return False, "Connection to Emby server timed out."
   except requests.exceptions.RequestException as e:
       logger.error(f"Error during direct Emby authentication request to {url}: {e}")
       error_message = f"Could not connect or communicate with Emby server at {url}. Please check the URL and network."
       if isinstance(e, requests.exceptions.ConnectionError):
            if "Name or service not known" in str(e) or "Connection refused" in str(e):
                error_message = f"Could not resolve or connect to Emby server at {url}. Please check the URL."
            elif "CERTIFICATE_VERIFY_FAILED" in str(e):
                 error_message = f"SSL certificate verification failed for {url}. Check server setup or disable SSL verification (not recommended)."
       return False, error_message
   except Exception as e:
       logger.error(f"Unexpected error during direct Emby authentication: {e}", exc_info=True)
       return False, f"An unexpected error occurred: {e}"

def authenticate_with_emby_connect(username, password):
    """
    Authenticates with Emby Connect using username/password and retrieves servers.
    Based on the original implementation.
    Returns (True, {'servers': [...], 'connect_user_id': ...}) on success,
    (False, error_message) on failure.
    """
    connect_auth_url = "https://connect.emby.media/service/user/authenticate"
    app_name = "MovieRoulette" 
    app_version = "1.0"

    try:
        auth_payload = {
            "nameOrEmail": username,
            "rawpw": password 
        }
        headers = {
            'Content-Type': 'application/json',
            'X-Application': f'{app_name}/{app_version}', 
            'Accept': 'application/json' 
        }

        logger.info(f"Attempting Emby Connect authentication for user {username}")
        response = requests.post(connect_auth_url, json=auth_payload, headers=headers, timeout=15)

        if response.status_code == 401:
             logger.warning(f"Emby Connect authentication failed for {username}: Invalid credentials.")
             return False, "Invalid Emby Connect username or password."
        elif response.status_code != 200:
             logger.error(f"Emby Connect authentication failed for {username}: Status {response.status_code}, Response: {response.text[:200]}")
             error_msg = f"Emby Connect authentication failed with status code {response.status_code}"
             try:
                 error_data = response.json()
                 if error_data and isinstance(error_data, dict) and 'message' in error_data:
                     error_msg = f"Emby Connect authentication failed: {error_data['message']} (Status: {response.status_code})"
                 response.raise_for_status() 
             except requests.exceptions.HTTPError as http_err:
                 error_msg = f"Emby Connect authentication failed: {http_err}"
             except json.JSONDecodeError:
                 pass 
             return False, error_msg

        auth_data = response.json()
        connect_token = auth_data.get('AccessToken')
        connect_user_id = auth_data.get('User', {}).get('Id')

        if not connect_token or not connect_user_id:
            logger.error(f"Emby Connect authentication succeeded for {username} but response missing token or user ID: {auth_data}")
            return False, "Authentication succeeded but received an unexpected response from Emby Connect."

        logger.info(f"Emby Connect authentication successful for {username} (Connect User ID: {connect_user_id})")

        connect_servers_url = f"https://connect.emby.media/service/servers?userId={connect_user_id}" 
        server_headers = {
            'X-Application': f'{app_name}/{app_version}', 
            'X-Connect-UserToken': connect_token,
            'Accept': 'application/json' 
        }

        logger.info(f"Fetching linked servers for Emby Connect user {connect_user_id}")
        response = requests.get(connect_servers_url, headers=server_headers, timeout=15)

        if response.status_code != 200:
            logger.error(f"Failed to fetch Emby Connect servers for {connect_user_id}: Status {response.status_code}, Response: {response.text[:200]}")
            error_msg = f"Failed to fetch linked servers with status code {response.status_code}"
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as http_err:
                 error_msg = f"Failed to fetch linked servers: {http_err}"
            return False, error_msg

        servers_data = response.json()
        if not isinstance(servers_data, list):
             logger.error(f"Received unexpected format for server list: {servers_data}")
             return False, "Received unexpected format for server list from Emby Connect."

        logger.info(f"Successfully fetched {len(servers_data)} servers for Emby Connect user {connect_user_id}")

        formatted_servers = []
        for server in servers_data:
             server_url = server.get('LocalAddress') or server.get('RemoteAddress') or server.get('Url')
             formatted_servers.append({
                 'id': server.get('SystemId'),
                 'name': server.get('Name'),
                 'local_url': server.get('LocalAddress'),
                 'remote_url': server.get('RemoteAddress') or server.get('Url'),
                 'access_key': server.get('AccessKey'),
                 'connect_server_id': server.get('ConnectServerId')
             })

        return True, {'servers': formatted_servers, 'connect_user_id': connect_user_id}

    except requests.exceptions.Timeout:
        logger.error(f"Timeout during Emby Connect request for user {username}.")
        return False, "Connection to Emby Connect timed out."
    except requests.exceptions.RequestException as e:
        logger.error(f"Error during Emby Connect request for user {username}: {e}")
        return False, f"Could not connect or communicate with Emby Connect: {e}"
    except Exception as e:
        logger.error(f"Unexpected error during Emby Connect process: {e}", exc_info=True)
        return False, f"An unexpected error occurred during Emby Connect process: {e}"

class EmbyService:
    def __init__(self, url=None, api_key=None, user_id=None, update_interval=600):
        emby_settings = settings.get('emby', {})
        self.server_url = url or emby_settings.get('url') or os.getenv('EMBY_URL')
        self.api_key = api_key or emby_settings.get('api_key') or os.getenv('EMBY_API_KEY')
        self.user_id = user_id or emby_settings.get('user_id') or os.getenv('EMBY_USER_ID')

        if settings.get('emby', {}).get('enabled'): 
            if not all([self.server_url, self.api_key, self.user_id]):
                 logger.error(f"EmbyService validation failed: URL={self.server_url}, Key={'******' if self.api_key else 'None'}, UserID={self.user_id}")
                 raise ValueError("Emby URL, API key, and user ID are required when enabled")

        self._update_headers()

        self.update_interval = update_interval
        self.last_cache_update = 0
        self.cache_path = '/app/data/emby_all_movies.json'
        self.is_updating = False
        self._cache_lock = threading.Lock()
        self.running = False
        self._start_cache_updater()

        self.playback_start_times = {}

    def _update_headers(self):
        """Update request headers with current API key"""
        self.headers = {
            'X-Emby-Token': self.api_key,
            'Content-Type': 'application/json'
        }

    def authenticate(self, username, password):
        """Direct authentication with Emby server"""
        try:
            server_info_url = f"{self.server_url}/System/Info/Public"
            response = requests.get(server_info_url)
            response.raise_for_status()

            auth_url = f"{self.server_url}/Users/AuthenticateByName"
            auth_data = {
                "Username": username,
                "Pw": password,
                "Password": password,
                "PasswordMd5": "",  
                "AuthenticationScheme": "Username"
            }

            response = requests.post(auth_url, json=auth_data, headers={
                'X-Emby-Authorization': ('MediaBrowser Client="Movie Roulette",'
                                       'Device="Movie Roulette",'
                                       'DeviceId="MovieRoulette",'
                                       'Version="1.0.0"')
            })

            response.raise_for_status()
            data = response.json()

            self.api_key = data.get('AccessToken')
            self.user_id = data.get('User', {}).get('Id')
            self._update_headers()

            return {
                "status": "success",
                "api_key": self.api_key,
                "user_id": self.user_id
            }

        except Exception as e:
            logger.error(f"Error in direct authentication: {e}")
            raise

    def get_users(self):
        """Get list of users from Emby server"""
        try:
            users_url = f"{self.server_url}/Users"
            response = requests.get(users_url, headers=self.headers)
            response.raise_for_status()
            users_data = response.json()
            processed_users = []
            for user in users_data:
                user_name = user.get('Name')
                if not user_name:
                    user_id = user.get('Id', 'Unknown ID')
                    logger.warning(f"Emby user found without a 'Name' field. User ID: {user_id}. Using ID as name.")
                    processed_users.append(f"Emby User ({user_id})") 
                else:
                    processed_users.append(user_name)
            return processed_users
        except Exception as e:
            logger.error(f"Error fetching Emby users: {e}")
            return []

    def _start_cache_updater(self):
        """Start the cache updater thread"""
        self.running = True
        Thread(target=self._update_loop, daemon=True).start()
        logger.info("Emby cache updater thread started")

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
                        logger.info("Starting Emby cache update")
                        self.cache_all_emby_movies()
                        self.last_cache_update = current_time
                        logger.info("Emby cache update completed")
                time.sleep(60)  
            except Exception as e:
                logger.error(f"Error in Emby cache update loop: {e}")
                time.sleep(5)  

    def cache_all_emby_movies(self):
        """Cache all movies for Emby badge checking"""
        if not all([self.server_url, self.api_key, self.user_id]):
            logger.info("Emby not fully configured, skipping cache update")
            return

        if self.is_updating:
            logger.info("Emby cache update already in progress, skipping")
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
                    "emby_id": movie['Id'],
                    "tmdb_id": movie.get('ProviderIds', {}).get('Tmdb')
                })

            temp_path = f"{self.cache_path}.tmp"
            with open(temp_path, 'w') as f:
                json.dump(all_movies, f)
            os.replace(temp_path, self.cache_path)

            logger.info(f"Cached {len(all_movies)} total Emby movies")
            return all_movies
        except Exception as e:
            logger.error(f"Error caching all Emby movies: {e}")
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
                'IsPlayed': 'false'  
            }
            response = requests.get(movies_url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get('TotalRecordCount', 0)
        except Exception as e:
            logger.error(f"Error getting unwatched count: {e}")
            return 0

    def get_random_movie(self):
        try:
            movies_url = f"{self.server_url}/Users/{self.user_id}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'SortBy': 'Random',
                'Limit': '1',
                'Fields': 'Overview,People,Genres,CommunityRating,RunTimeTicks,ProviderIds,UserData,OfficialRating,MediaSources,MediaStreams,ProductionYear'
            }

            response = requests.get(movies_url, headers=self.headers, params=params)
            response.raise_for_status()
            movies = response.json()

            if movies.get('Items'):
                movie_data = self.get_movie_data(movies['Items'][0])
                logger.info(f"Selected random Emby movie for screensaver: {movie_data.get('title')}")  
                return movie_data
            logger.warning("No movies found for screensaver")
            return None
        except Exception as e:
            logger.error(f"Error fetching random movie: {e}")
            return None

    def get_movie_data(self, movie):
        run_time_ticks = movie.get('RunTimeTicks', 0)
        total_minutes = run_time_ticks // 600000000  
        hours = total_minutes // 60
        minutes = total_minutes % 60

        video_format = "Unknown"
        audio_format = "Unknown"

        if 'MediaSources' in movie and movie['MediaSources']:
            media_source = movie['MediaSources'][0]

            video_streams = [s for s in media_source.get('MediaStreams', [])
                           if s.get('Type') == 'Video']
            if video_streams:
                video_stream = video_streams[0]
                height = video_stream.get('Height', 0)

                if height <= 480:
                    resolution = "SD"
                elif height <= 720:
                    resolution = "HD"
                elif height <= 1080:
                    resolution = "FHD"
                elif height <= 2160:
                    resolution = "4K"
                else:
                    resolution = "Unknown"

                hdr_types = []
                if 'HDR' in str(video_stream):
                    if 'DolbyVision' in str(video_stream):
                        hdr_types.append('DV')
                    if 'HDR10Plus' in str(video_stream):
                        hdr_types.append('HDR10+')
                    elif 'HDR10' in str(video_stream):
                        hdr_types.append('HDR10')
                    elif not hdr_types:
                        hdr_types.append('HDR')

                video_format_parts = [resolution]
                if hdr_types:
                    video_format_parts.append('/'.join(hdr_types))
                video_format = ' '.join(video_format_parts)

            audio_streams = [s for s in media_source.get('MediaStreams', [])
                           if s.get('Type') == 'Audio']
            if audio_streams:
                audio_stream = audio_streams[0]
                codec = audio_stream.get('Codec', '').upper()

                codec_map = {
                    'AC3': 'Dolby Digital',
                    'EAC3': 'Dolby Digital Plus',
                    'TRUEHD': 'Dolby TrueHD',
                    'DTS': 'DTS',
                    'DTSHD': 'DTS-HD MA',
                    'AAC': 'AAC',
                    'FLAC': 'FLAC'
                }

                audio_format = codec_map.get(codec, codec)

                if any(s in str(audio_stream) for s in ['Atmos', 'ATMOS']):
                    audio_format = 'Dolby Atmos'

                channels = audio_stream.get('Channels', 0)
                if channels > 0:
                    layout_map = {
                        1: 'Mono',
                        2: 'Stereo',
                        6: '5.1',
                        8: '7.1'
                    }
                    layout = layout_map.get(channels, f"{channels}ch")
                    audio_format = f"{audio_format} {layout}"

        all_people = movie.get('People', [])

        directors = [
            {
                "name": p.get('Name', ''),
                "id": p.get('ProviderIds', {}).get('Tmdb'),
                "type": "director",
                "job": "Director",
                "department": "Directing"
            }
            for p in all_people if p.get('Type') == 'Director'
        ]

        writers = [
            {
                "name": p.get('Name', ''),
                "id": p.get('ProviderIds', {}).get('Tmdb'),
                "type": "writer",
                "job": p.get('Role', 'Writer'),
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
            "directors_enriched": directors,
            "writers_enriched": writers,
            "actors_enriched": actors,
            "directors": [d["name"] for d in directors],
            "writers": [w["name"] for w in writers],
            "actors": [a["name"] for a in actors]
        }

    def filter_movies(self, genres=None, years=None, pg_ratings=None, watch_status='unwatched'):
        try:
            movies_url = f"{self.server_url}/Users/{self.user_id}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'SortBy': 'Random',
                'Limit': '1',
                'Fields': 'Overview,People,Genres,MediaSources,MediaStreams,RunTimeTicks,ProviderIds,UserData,OfficialRating,ProductionYear',
                'IsPlayed': 'false'
            }

            logger.info(f"Filter movies called with - genres: {genres}, years: {years}, pg_ratings: {pg_ratings}")

            if watch_status == 'unwatched':
                params['IsPlayed'] = 'false'
            elif watch_status == 'watched':
                params['IsPlayed'] = 'true'

            genres = genres if genres and genres[0] else None
            years = years if years and years[0] else None
            pg_ratings = pg_ratings if pg_ratings and pg_ratings[0] else None

            if genres:
                params['Genres'] = '|'.join(genres)
                logger.info(f"Using genres in request: {params['Genres']}") 

            if years:
                params['Years'] = years
                logger.info(f"Using years in request: {params['Years']}")

            if pg_ratings:
                params['OfficialRatings'] = '|'.join(pg_ratings)
                logger.info(f"Using ratings in request: {params['OfficialRatings']}")

            response = requests.get(movies_url, headers=self.headers, params=params)
            logger.info(f"Response status code: {response.status_code}")

            response.raise_for_status()
            movies = response.json().get('Items', [])
            logger.info(f"Got {len(movies)} movies matching filters")

            if not movies:
                logger.warning("No unwatched movies found matching the criteria")
                return None

            return self.get_movie_data(movies[0])
        except Exception as e:
            logger.error(f"Error filtering movies: {str(e)}")
            return None

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

                    if item_id not in self.playback_start_times:
                        self.playback_start_times[item_id] = datetime.now()

                    is_stopped = session.get('PlayState', {}).get('PlayMethod') is None

                    return {
                        'is_playing': not is_paused and not is_stopped,
                        'IsPaused': is_paused,
                        'IsStopped': is_stopped,
                        'position': position_seconds,
                        'start_time': self.playback_start_times[item_id].isoformat(),
                        'duration': total_duration
                    }

            return {
                'is_playing': False,
                'IsPaused': False,
                'IsStopped': True,
                'position': 0,
                'start_time': None,
                'duration': 0
            }
        except Exception as e:
            logger.error(f"Error getting playback info: {e}")
            return {
                'is_playing': False,
                'IsPaused': False,
                'IsStopped': True,
                'position': 0,
                'start_time': None,
                'duration': 0,
                'error': str(e)
            }

    def get_clients(self):
        """Get list of playable clients/sessions"""
        try:
            sessions_url = f"{self.server_url}/Sessions"
            response = requests.get(sessions_url, headers=self.headers)
            response.raise_for_status()
            sessions = response.json()
            logger.debug(f"Raw /Sessions response from Emby: {json.dumps(sessions, indent=2)}") 

            clients = []
            for session in sessions:
                if session.get('SupportsRemoteControl') and session.get('DeviceName') and 'Movie Roulette' not in session.get('DeviceName'):
                     clients.append({
                         'id': session['Id'],
                         'title': session.get('DeviceName', 'Unknown Device'),
                         'user': session.get('UserName', 'Unknown User')
                     })
            return clients
        except Exception as e:
            logger.error(f"Error fetching clients: {e}")
            return []

    def play_movie(self, movie_id, session_id):
        """Play a movie on a specific client session"""
        try:
            playback_url = f"{self.server_url}/Sessions/{session_id}/Playing"
            params = {
                'ItemIds': movie_id,
                'PlayCommand': 'PlayNow'
            }
            response = requests.post(playback_url, headers=self.headers, params=params)
            response.raise_for_status()
            logger.info(f"Playing movie {movie_id} on session {session_id}")

            self.playback_start_times[movie_id] = datetime.now()

            movie_data = self.get_movie_by_id(movie_id)
            username = None
            try:
                session_details_url = f"{self.server_url}/Sessions?api_key={self.api_key}"
                sessions_response = requests.get(session_details_url, headers={'Accept': 'application/json'})
                sessions_response.raise_for_status()
                sessions_data = sessions_response.json()
                for session_info in sessions_data:
                    if session_info.get('Id') == session_id:
                        username = session_info.get('UserName')
                        if username:
                            logger.info(f"Determined username '{username}' for session {session_id} during play_movie.")
                        else:
                            logger.warning(f"Could not determine username for session {session_id} from Emby API.")
                        break
            except Exception as e_user:
                logger.warning(f"Could not determine username for Emby playback (session {session_id}) for poster context: {e_user}")

            if movie_data:
                from utils.poster_view import set_current_movie as set_global_current_movie
                pass
            
            return {"status": "playing", "username": username}
        except Exception as e:
            logger.error(f"Error playing movie: {e}")
            return {"error": str(e)}

    def get_genres(self):
        """Get list of genres from Emby server"""
        try:
            genres_url = f"{self.server_url}/Genres"
            params = {'UserId': self.user_id} 
            response = requests.get(genres_url, headers=self.headers, params=params)
            response.raise_for_status()
            genres = response.json().get('Items', [])
            return sorted([genre['Name'] for genre in genres if genre.get('Name')])
        except Exception as e:
            logger.error(f"Error fetching genres: {e}")
            return []

    def get_years(self):
        """Get list of production years from Emby server"""
        try:
            items_url = f"{self.server_url}/Users/{self.user_id}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'Fields': 'ProductionYear'
            }
            response = requests.get(items_url, headers=self.headers, params=params)
            response.raise_for_status()
            movies = response.json().get('Items', [])
            years = set(movie.get('ProductionYear') for movie in movies if movie.get('ProductionYear'))
            return sorted(list(years), reverse=True)
        except Exception as e:
            logger.error(f"Error fetching years: {e}")
            return []

    def get_pg_ratings(self):
        """Get list of official ratings from Emby server by aggregating from items"""
        try:
            items_url = f"{self.server_url}/Users/{self.user_id}/Items"
            params = {
                'Recursive': 'true',
                'Fields': 'OfficialRating',
                'IncludeItemTypes': 'Movie'
            }
            logger.debug(f"Fetching items from {items_url} to aggregate PG ratings.")
            response = requests.get(items_url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()

            all_ratings = set()
            for item in data.get('Items', []):
                rating = item.get('OfficialRating')
                if rating:
                    all_ratings.add(rating)

            rating_list = sorted(list(all_ratings))
            logger.debug(f"Extracted PG rating list from items: {rating_list}")
            return rating_list
        except Exception as e:
            logger.error(f"Error fetching PG ratings by aggregating items: {e}")
            return []

    def get_movie_by_id(self, movie_id):
        """Get detailed data for a specific movie by its Emby ID"""
        try:
            movie_url = f"{self.server_url}/Users/{self.user_id}/Items/{movie_id}"
            params = {
                 'Fields': 'Overview,People,Genres,CommunityRating,RunTimeTicks,ProviderIds,UserData,OfficialRating,MediaSources,MediaStreams,ProductionYear'
            }
            response = requests.get(movie_url, headers=self.headers, params=params)
            response.raise_for_status()
            movie = response.json()
            return self.get_movie_data(movie)
        except Exception as e:
            logger.error(f"Error fetching movie by ID {movie_id}: {e}")
            return None

    def check_token_validity(self):
        """Check if the current API token is valid"""
        try:
            info_url = f"{self.server_url}/System/Info"
            response = requests.get(info_url, headers=self.headers, timeout=5)
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"Error checking Emby token validity: {e}")
            return False

    def get_server_info(self):
        """Get basic server information"""
        try:
            info_url = f"{self.server_url}/System/Info"
            response = requests.get(info_url, headers=self.headers, timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error getting Emby server info: {e}")
            return None

    def get_current_username(self):
        """Get the username associated with the configured user ID"""
        try:
            user_url = f"{self.server_url}/Users/{self.user_id}"
            response = requests.get(user_url, headers=self.headers, timeout=5)
            response.raise_for_status()
            user_data = response.json()
            return user_data.get('Name')
        except Exception as e:
            logger.error(f"Error getting current Emby username: {e}")
            return None

    def get_active_sessions(self):
        """Get a list of active playback sessions"""
        try:
            sessions_url = f"{self.server_url}/Sessions"
            response = requests.get(sessions_url, headers=self.headers)
            response.raise_for_status()
            sessions = response.json()
            active_sessions = [s for s in sessions if s.get('NowPlayingItem')]
            return active_sessions
        except Exception as e:
            logger.error(f"Error fetching active Emby sessions: {e}")
            return []

    def search_movies(self, query):
        """Search for movies by title"""
        try:
            search_url = f"{self.server_url}/Users/{self.user_id}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'SearchTerm': query,
                'Fields': 'Overview,People,Genres,MediaSources,MediaStreams,RunTimeTicks,ProviderIds,UserData,OfficialRating,ProductionYear',
                'Limit': 20 
            }
            response = requests.get(search_url, headers=self.headers, params=params)
            response.raise_for_status()
            movies = response.json().get('Items', [])
            return [self.get_movie_data(movie) for movie in movies]
        except Exception as e:
            logger.error(f"Error searching Emby movies: {e}")
            return []

    def get_filtered_movie_count(self, filters):
        """
        Counts movies matching the provided filters by querying the Emby API.
        Uses the user_id and api_key associated with this EmbyService instance.

        Args:
            filters (dict): A dictionary containing filter criteria:
                            {'genres': list, 'years': list, 'pgRatings': list, 'watch_status': str}

        Returns:
            int: The count of matching movies.
        """
        if not all([self.server_url, self.api_key, self.user_id]):
            logger.error("EmbyService not fully configured for get_filtered_movie_count")
            return 0

        try:
            movies_url = f"{self.server_url}/Users/{self.user_id}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'Limit': 0 
            }

            watch_status = filters.get('watch_status', 'unwatched')
            selected_genres = filters.get('genres', [])
            selected_years = filters.get('years', [])
            selected_pg_ratings = filters.get('pgRatings', [])

            if watch_status == 'unwatched':
                params['IsPlayed'] = 'false'
            elif watch_status == 'watched':
                params['IsPlayed'] = 'true'

            if selected_genres:
                params['Genres'] = '|'.join(selected_genres)
            if selected_years:
                params['Years'] = ','.join(map(str, selected_years)) 
            if selected_pg_ratings:
                params['OfficialRatings'] = '|'.join(selected_pg_ratings) 

            logger.debug(f"Emby API count request params (User: {self.user_id}): {params}")

            response = requests.get(movies_url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()

            count = data.get('TotalRecordCount', 0)
            logger.debug(f"Emby API returned count: {count}")
            return count

        except Exception as e:
            logger.error(f"Error getting filtered movie count from Emby (User: {self.user_id}): {str(e)}")
            return 0
