# utils/playback_monitor.py
import threading
import time
import logging
import os
from flask import current_app
from utils.jellyfin_service import JellyfinService
from utils.plex_service import PlexService
from utils.poster_view import set_current_movie

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PlaybackMonitor(threading.Thread):
    def __init__(self, app, interval=10):
        super().__init__()
        self.interval = interval
        self.jellyfin_service = None
        self.plex_service = None
        self.jellyfin_available = all([os.getenv('JELLYFIN_URL'), os.getenv('JELLYFIN_API_KEY')])
        self.plex_available = all([os.getenv('PLEX_URL'), os.getenv('PLEX_TOKEN'), os.getenv('PLEX_MOVIE_LIBRARIES')])
        
        if self.jellyfin_available:
            self.jellyfin_service = JellyfinService()
        if self.plex_available and 'PLEX_SERVICE' in app.config:
            self.plex_service = app.config['PLEX_SERVICE']
        
        self.current_movie_id = None
        self.running = True
        self.app = app
        self.plex_poster_users = os.getenv('PLEX_POSTER_USERS', '').split(',')
        self.jellyfin_poster_users = os.getenv('JELLYFIN_POSTER_USERS', '').split(',')
        logger.info(f"Initialized PlaybackMonitor with Plex poster users: {self.plex_poster_users}")
        logger.info(f"Initialized PlaybackMonitor with Jellyfin poster users: {self.jellyfin_poster_users}")
        logger.info(f"Jellyfin available: {self.jellyfin_available}")
        logger.info(f"Plex available: {self.plex_available}")

    def is_poster_user(self, username, service):
        if service == 'plex':
            is_authorized = username in self.plex_poster_users
        elif service == 'jellyfin':
            is_authorized = username in self.jellyfin_poster_users
        else:
            is_authorized = False
        logger.debug(f"Checking if {username} is a {service} poster user: {is_authorized}")
        return is_authorized

    def run(self):
        while self.running:
            try:
                with self.app.app_context():
                    playback_info = None
                    service = None
                    username = None

                    # Check Jellyfin if available
                    if self.jellyfin_available and self.jellyfin_service:
                        jellyfin_sessions = self.jellyfin_service.get_active_sessions()
                        for session in jellyfin_sessions:
                            now_playing = session.get('NowPlayingItem', {})
                            if now_playing.get('Type') == 'Movie':
                                username = session.get('UserName')
                                if self.is_poster_user(username, 'jellyfin'):
                                    playback_info = {
                                        'id': now_playing.get('Id'),
                                        'position': session.get('PlayState', {}).get('PositionTicks', 0) / 10_000_000
                                    }
                                    service = 'jellyfin'
                                    logger.debug(f"Authorized Jellyfin user {username} is playing a movie. Updating poster.")
                                    break
                                else:
                                    logger.debug(f"Jellyfin user {username} is playing a movie but not authorized for poster updates.")
                            else:
                                logger.debug(f"Jellyfin user is playing non-movie content. Ignoring.")

                    # Check Plex if available and no Jellyfin playback was found
                    if not playback_info and self.plex_available and self.plex_service:
                        sessions = self.plex_service.plex.sessions()
                        for session in sessions:
                            if session.type == 'movie':  # Only consider movie sessions
                                username = session.usernames[0] if session.usernames else None
                                if self.is_poster_user(username, 'plex'):
                                    playback_info = self.plex_service.get_playback_info(session.ratingKey)
                                    service = 'plex'
                                    logger.debug(f"Authorized Plex user {username} is playing a movie. Updating poster.")
                                    break
                                else:
                                    logger.debug(f"Plex user {username} is playing a movie but not authorized for poster updates.")
                            else:
                                logger.debug(f"Plex user {session.usernames[0] if session.usernames else 'Unknown'} is playing non-movie content. Ignoring.")

                    if playback_info:
                        movie_id = playback_info.get('id')
                        if movie_id and movie_id != self.current_movie_id:
                            logger.info(f"Detected new movie playback: {movie_id}")
                            # Fetch detailed movie data
                            if service == 'jellyfin':
                                movie_data = self.jellyfin_service.get_movie_by_id(movie_id)
                            elif service == 'plex':
                                movie_data = self.plex_service.get_movie_by_id(movie_id)

                            if movie_data:
                                # Update the current movie in the poster view
                                set_current_movie(movie_data, service=service, resume_position=playback_info.get('position', 0))
                                self.current_movie_id = movie_id
                    else:
                        # No movie is currently playing by authorized users
                        if self.current_movie_id is not None:
                            logger.info("Playback stopped or no authorized users playing movies.")
                            self.current_movie_id = None
                            # Emit event to set the default poster
                            default_poster_manager = self.app.config.get('DEFAULT_POSTER_MANAGER')
                            if default_poster_manager:
                                default_poster_manager.set_default_poster()
                time.sleep(self.interval)
            except Exception as e:
                logger.error(f"Error in PlaybackMonitor: {e}")
                time.sleep(self.interval)

    def stop(self):
        self.running = False
