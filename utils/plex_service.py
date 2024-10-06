import os
import random
import logging
import requests
from plexapi.server import PlexServer
from datetime import datetime, timedelta
from utils.poster_view import set_current_movie

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class PlexService:
    def __init__(self):
        self.PLEX_URL = os.getenv('PLEX_URL')
        self.PLEX_TOKEN = os.getenv('PLEX_TOKEN')
        self.PLEX_MOVIE_LIBRARIES = os.getenv('PLEX_MOVIE_LIBRARIES', 'Movies').split(',')
        self.plex = PlexServer(self.PLEX_URL, self.PLEX_TOKEN)
        self.libraries = [self.plex.library.section(lib.strip()) for lib in self.PLEX_MOVIE_LIBRARIES]
        self.playback_start_times = {}

    def get_random_movie(self):
        all_unwatched = []
        for library in self.libraries:
            all_unwatched.extend(library.search(unwatched=True))
        if not all_unwatched:
            return None
        chosen_movie = random.choice(all_unwatched)
        return self.get_movie_data(chosen_movie)

    def filter_movies(self, genre=None, year=None, pg_rating=None):
        filters = {'unwatched': True}
        if genre:
            filters['genre'] = genre
        if year:
            filters['year'] = int(year)
        if pg_rating:
            filters['contentRating'] = pg_rating

        filtered_movies = []
        for library in self.libraries:
            filtered_movies.extend(library.search(**filters))

        if filtered_movies:
            chosen_movie = random.choice(filtered_movies)
            return self.get_movie_data(chosen_movie)
        return None

    def get_movie_data(self, movie):
        movie_duration_hours = (movie.duration / (1000 * 60 * 60)) % 24
        movie_duration_minutes = (movie.duration / (1000 * 60)) % 60

        # Extract video format information
        video_format = "Unknown"
        audio_format = "Unknown"

        # Make an additional API call to get extended metadata
        metadata_url = f"{self.PLEX_URL}/library/metadata/{movie.ratingKey}?includeChildren=1"
        headers = {"X-Plex-Token": self.PLEX_TOKEN, "Accept": "application/json"}
        response = requests.get(metadata_url, headers=headers)
        if response.status_code == 200:
            metadata = response.json()
            media_info = metadata['MediaContainer']['Metadata'][0]['Media'][0]['Part'][0]['Stream']

            # Video format extraction
            video_stream = next((s for s in media_info if s['streamType'] == 1), None)
            if video_stream:
                # Determine resolution
                height = video_stream.get('height', 0)
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

                # Check for HDR and Dolby Vision
                hdr_types = []
                if video_stream.get('DOVIPresent'):
                    hdr_types.append("DV")
                if video_stream.get('colorTrc') == 'smpte2084' and video_stream.get('colorSpace') == 'bt2020nc':
                    hdr_types.append("HDR10")

                # Combine resolution and HDR info
                video_format = f"{resolution} {'/'.join(hdr_types)}".strip()

            # Audio format extraction
            audio_stream = next((s for s in media_info if s['streamType'] == 2), None)
            if audio_stream:
                codec = audio_stream.get('codec', '').lower()
                channels = audio_stream.get('channels', 0)

                codec_map = {
                    'ac3': 'Dolby Digital',
                    'eac3': 'Dolby Digital Plus',
                    'truehd': 'Dolby TrueHD',
                    'dca': 'DTS',
                    'dts': 'DTS',
                    'aac': 'AAC',
                    'flac': 'FLAC'
                }

                audio_format = codec_map.get(codec, codec.upper())

                if audio_stream.get('audioChannelLayout'):
                    channel_layout = audio_stream['audioChannelLayout'].split('(')[0]  # Remove (side) or similar
                    audio_format += f" {channel_layout}"
                elif channels:
                    if channels == 8:
                        audio_format += ' 7.1'
                    elif channels == 6:
                        audio_format += ' 5.1'
                    elif channels == 2:
                        audio_format += ' 2.0'

        return {
            "id": movie.ratingKey,
            "title": movie.title,
            "year": movie.year,
            "duration_hours": int(movie_duration_hours),
            "duration_minutes": int(movie_duration_minutes),
            "directors": [director.tag for director in movie.directors],
            "description": movie.summary,
            "writers": [writer.tag for writer in movie.writers][:3],  # Limit to first 3 writers
            "actors": [actor.tag for actor in movie.actors][:3],  # Limit to first 3 actors
            "genres": [genre.tag for genre in movie.genres],
            "poster": movie.thumbUrl,
            "background": movie.artUrl,
            "contentRating": movie.contentRating,
            "videoFormat": video_format,
            "audioFormat": audio_format,
        }

    def get_genres(self):
        all_genres = set()
        for library in self.libraries:
            for movie in library.search(unwatched=True):
                all_genres.update([genre.tag for genre in movie.genres])
        return sorted(list(all_genres))

    def get_years(self):
        all_years = set()
        for library in self.libraries:
            for movie in library.search(unwatched=True):
                all_years.add(movie.year)
        return sorted(list(all_years), reverse=True)

    def get_pg_ratings(self):
        ratings = set()
        for library in self.libraries:
            for movie in library.search(unwatched=True):
                if movie.contentRating:
                    ratings.add(movie.contentRating)
        return sorted(list(ratings))

    def get_clients(self):
        return [{"id": client.machineIdentifier, "title": client.title} for client in self.plex.clients()]

    def play_movie(self, movie_id, client_id):
        try:
            movie = None
            for library in self.libraries:
                try:
                    movie = library.fetchItem(int(movie_id))
                    if movie:
                        break
                except:
                    continue
            
            if not movie:
                raise ValueError(f"Movie with id {movie_id} not found in any library")

            client = next((c for c in self.plex.clients() if c.machineIdentifier == client_id), None)
            if not client:
                raise ValueError(f"Unknown client id: {client_id}")
            
            client.proxyThroughServer()
            client.playMedia(movie)

            # Set the start time for the movie
            self.playback_start_times[movie_id] = datetime.now()

            # Fetch movie data
            movie_data = self.get_movie_data(movie)
            if movie_data:
                # Set current movie
                set_current_movie(movie_data, service='plex', resume_position=0)
            return {"status": "playing"}
        except Exception as e:
            logger.error(f"Error playing movie: {e}")
            return {"error": str(e)}

    def get_total_unwatched_movies(self):
        return sum(len(library.search(unwatched=True)) for library in self.libraries)

    def get_all_unwatched_movies(self):
        all_unwatched = []
        for library in self.libraries:
            all_unwatched.extend(library.search(unwatched=True))
        return [self.get_movie_data(movie) for movie in all_unwatched]

    def get_movie_by_id(self, movie_id):
        for library in self.libraries:
            try:
                movie = library.fetchItem(int(movie_id))
                return self.get_movie_data(movie)
            except:
                continue
        logger.error(f"Movie with id {movie_id} not found in any library")
        return None

    def get_playback_info(self, item_id):
        try:
            for session in self.plex.sessions():
                if str(session.ratingKey) == str(item_id):
                    position_ms = session.viewOffset or 0
                    duration_ms = session.duration or 0
                    position_seconds = position_ms / 1000
                    total_duration_seconds = duration_ms / 1000

                    # Correctly access the playback state
                    session_state = session.player.state.lower()
                    is_paused = session_state == 'paused'
                    is_playing = session_state == 'playing'
                    is_buffering = session_state == 'buffering'

                    # Handle buffering state if necessary
                    if is_buffering:
                        is_playing = True
                        is_paused = False

                    # Use stored start time or current time if not available
                    if item_id not in self.playback_start_times:
                        self.playback_start_times[item_id] = datetime.now()

                    start_time = self.playback_start_times[item_id]
                    end_time = start_time + timedelta(seconds=total_duration_seconds)

                    return {
                        'id': str(item_id),
                        'is_playing': is_playing,
                        'IsPaused': is_paused,
                        'IsStopped': False,
                        'position': position_seconds,
                        'start_time': start_time.isoformat(),
                        'end_time': end_time.isoformat(),
                        'duration': total_duration_seconds
                    }
            # If no matching session found, the movie is stopped
            return {
                'id': str(item_id),
                'is_playing': False,
                'IsPaused': False,
                'IsStopped': True,
                'position': 0,
                'start_time': None,
                'end_time': None,
                'duration': 0
            }
        except Exception as e:
            logger.error(f"Error fetching playback info: {e}")
            return None

# You might want to keep this function outside the class if it's used elsewhere
def get_playback_state(movie_id):
    from flask import current_app
    default_poster_manager = current_app.config.get('DEFAULT_POSTER_MANAGER')
    current_movie = load_current_movie()
    service = current_movie['service'] if current_movie else None

    playback_info = None

    if service == 'jellyfin':
        jellyfin_service = current_app.config.get('JELLYFIN_SERVICE')
        if jellyfin_service:
            playback_info = jellyfin_service.get_playback_info(movie_id)
    elif service == 'plex':
        plex_service = current_app.config.get('PLEX_SERVICE')
        if plex_service:
            playback_info = plex_service.get_playback_info(movie_id)
    else:
        playback_info = None

    if playback_info:
        current_position = playback_info.get('position', 0)
        total_duration = playback_info.get('duration', 0)
        is_playing = playback_info.get('is_playing', False)
        is_paused = playback_info.get('IsPaused', False)
        is_stopped = playback_info.get('IsStopped', False)
        # Determine the current state
        if is_stopped:
            current_state = 'STOPPED'
        elif total_duration > 0 and (total_duration - current_position) <= 10:
            current_state = 'ENDED'
        elif is_paused:
            current_state = 'PAUSED'
        elif is_playing:
            current_state = 'PLAYING'
        else:
            current_state = 'UNKNOWN'
        if default_poster_manager:
            default_poster_manager.handle_playback_state(current_state)
        playback_info['status'] = current_state
        return playback_info
    else:
        # Fallback to the current movie data if no real-time info is available
        if current_movie and current_movie['movie']['id'] == movie_id:
            start_time = datetime.fromisoformat(current_movie['start_time'])
            duration = timedelta(hours=current_movie['duration_hours'], minutes=current_movie['duration_minutes'])
            current_time = datetime.now()
            resume_position = current_movie.get('resume_position', 0)
            elapsed_time = (current_time - start_time).total_seconds()
            current_position = min(elapsed_time + resume_position, duration.total_seconds())
            if current_position >= duration.total_seconds() - 10:
                current_state = 'ENDED'
            elif elapsed_time >= 0:
                current_state = 'PLAYING'
            else:
                current_state = 'STOPPED'
            if default_poster_manager:
                default_poster_manager.handle_playback_state(current_state)
            return {
                'status': current_state,
                'position': current_position,
                'start_time': start_time.isoformat(),
                'duration': duration.total_seconds()
            }
    return None
