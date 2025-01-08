import threading
import time
import logging
import os
from flask import current_app
from utils.jellyfin_service import JellyfinService
from utils.plex_service import PlexService
from utils.settings import settings
from utils.poster_view import set_current_movie

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PlaybackMonitor(threading.Thread):
    def __init__(self, app, interval=10):
        super().__init__()
        self.interval = interval
        self.jellyfin_service = None
        self.plex_service = None
        self.emby_service = None
        
        # Get settings instead of checking ENV directly
        plex_settings = settings.get('plex', {})
        jellyfin_settings = settings.get('jellyfin', {})
        emby_settings = settings.get('emby', {})

        # Check for both settings and ENV availability
        self.plex_available = (
            bool(plex_settings.get('enabled')) or
            all([
                os.getenv('PLEX_URL'),
                os.getenv('PLEX_TOKEN'),
                os.getenv('PLEX_MOVIE_LIBRARIES')
            ])
        )

        self.jellyfin_available = (
            bool(jellyfin_settings.get('enabled')) or
            all([
                os.getenv('JELLYFIN_URL'),
                os.getenv('JELLYFIN_API_KEY'),
                os.getenv('JELLYFIN_USER_ID')
            ])
        )

        self.emby_available = (
            bool(emby_settings.get('enabled')) or
            all([
                os.getenv('EMBY_URL'),
                os.getenv('EMBY_API_KEY'),
                os.getenv('EMBY_USER_ID')
            ])
        )

        # Get services from app config
        if self.jellyfin_available:
            self.jellyfin_service = app.config.get('JELLYFIN_SERVICE')
            if not self.jellyfin_service:
                logger.warning("Jellyfin marked as available but service not found in app config")
                self.jellyfin_available = False

        if self.plex_available:
            self.plex_service = app.config.get('PLEX_SERVICE')
            if not self.plex_service:
                logger.warning("Plex marked as available but service not found in app config")
                self.plex_available = False

        if self.emby_available:
            self.emby_service = app.config.get('EMBY_SERVICE')
            if not self.emby_service:
                logger.warning("Emby marked as available but service not found in app config")
                self.emby_available = False

        self.current_movie_id = None
        self.running = True
        self.app = app
        self.settings = settings

        # Get poster users
        features_settings = settings.get('features', {})
        poster_users = features_settings.get('poster_users', {})

        if os.getenv('PLEX_POSTER_USERS'):
            self.plex_poster_users = [u.strip() for u in os.getenv('PLEX_POSTER_USERS', '').split(',') if u.strip()]
        else:
            self.plex_poster_users = poster_users.get('plex', []) if isinstance(poster_users.get('plex'), list) else []
        
        if os.getenv('JELLYFIN_POSTER_USERS'):
            self.jellyfin_poster_users = [u.strip() for u in os.getenv('JELLYFIN_POSTER_USERS', '').split(',') if u.strip()]
        else:
            self.jellyfin_poster_users = poster_users.get('jellyfin', []) if isinstance(poster_users.get('jellyfin'), list) else []

        if os.getenv('EMBY_POSTER_USERS'):
            self.emby_poster_users = [u.strip() for u in os.getenv('EMBY_POSTER_USERS', '').split(',') if u.strip()]
        else:
            self.emby_poster_users = poster_users.get('emby', []) if isinstance(poster_users.get('emby'), list) else []

        logger.info(f"Initialized PlaybackMonitor with settings:")
        logger.info(f"Plex available: {self.plex_available}")
        logger.info(f"Jellyfin available: {self.jellyfin_available}")
        logger.info(f"Emby available: {self.emby_available}")
        logger.info(f"Plex poster users: {self.plex_poster_users}")
        logger.info(f"Jellyfin poster users: {self.jellyfin_poster_users}")
        logger.info(f"Emby poster users: {self.emby_poster_users}")

    def update_service_status(self):
        """Update service availability and instances from app config"""
        # Get current settings
        plex_settings = self.settings.get('plex', {})
        jellyfin_settings = self.settings.get('jellyfin', {})
        emby_settings = self.settings.get('emby', {})

        # Update availability flags
        self.plex_available = (
            bool(plex_settings.get('enabled')) or
            all([
                os.getenv('PLEX_URL'),
                os.getenv('PLEX_TOKEN'),
                os.getenv('PLEX_MOVIE_LIBRARIES')
            ])
        )

        self.jellyfin_available = (
            bool(jellyfin_settings.get('enabled')) or
            all([
                os.getenv('JELLYFIN_URL'),
                os.getenv('JELLYFIN_API_KEY'),
                os.getenv('JELLYFIN_USER_ID')
            ])
        )

        self.emby_available = (
            bool(emby_settings.get('enabled')) or
            all([
                os.getenv('EMBY_URL'),
                os.getenv('EMBY_API_KEY'),
                os.getenv('EMBY_USER_ID')
            ])
        )

        # Update service instances
        if self.plex_available:
            self.plex_service = self.app.config.get('PLEX_SERVICE')
            if not self.plex_service:
                logger.warning("Plex marked as available but service not found in app config")
                self.plex_available = False

        if self.jellyfin_available:
            self.jellyfin_service = self.app.config.get('JELLYFIN_SERVICE')
            if not self.jellyfin_service:
                logger.warning("Jellyfin marked as available but service not found in app config")
                self.jellyfin_available = False

        if self.emby_available:
            self.emby_service = self.app.config.get('EMBY_SERVICE')
            if not self.emby_service:
                logger.warning("Emby marked as available but service not found in app config")
                self.emby_available = False

        # Update authorized users
        self.update_authorized_users()

        logger.info(f"Updated service status:")
        logger.info(f"Plex available: {self.plex_available}")
        logger.info(f"Jellyfin available: {self.jellyfin_available}")
        logger.info(f"Emby available: {self.emby_available}")

    def update_authorized_users(self):
        """Update authorized users list from settings or ENV"""
        features_settings = self.settings.get('features', {})
        poster_users = features_settings.get('poster_users', {})

        # Update poster users with ENV priority
        if os.getenv('PLEX_POSTER_USERS'):
            self.plex_poster_users = [u.strip() for u in os.getenv('PLEX_POSTER_USERS', '').split(',') if u.strip()]
        else:
            self.plex_poster_users = poster_users.get('plex', []) if isinstance(poster_users.get('plex'), list) else []

        if os.getenv('JELLYFIN_POSTER_USERS'):
            self.jellyfin_poster_users = [u.strip() for u in os.getenv('JELLYFIN_POSTER_USERS', '').split(',') if u.strip()]
        else:
            self.jellyfin_poster_users = poster_users.get('jellyfin', []) if isinstance(poster_users.get('jellyfin'), list) else []

        if os.getenv('EMBY_POSTER_USERS'):
            self.emby_poster_users = [u.strip() for u in os.getenv('EMBY_POSTER_USERS', '').split(',') if u.strip()]
        else:
            self.emby_poster_users = poster_users.get('emby', []) if isinstance(poster_users.get('emby'), list) else []

    def is_poster_user(self, username, service):
        if not username:
            return False
            
        if service == 'plex':
            is_authorized = username in self.plex_poster_users
        elif service == 'jellyfin':
            is_authorized = username in self.jellyfin_poster_users
        elif service == 'emby':
            is_authorized = username in self.emby_poster_users
        else:
            is_authorized = False
        
        if not is_authorized:
            logger.debug(f"Unauthorized {service} playback by {username}")
            
        return is_authorized

    def run(self):
        while self.running:
            try:
                with self.app.app_context():
                    playback_info = None
                    service = None
                    username = None

                    # Check Jellyfin first
                    if self.jellyfin_available and self.jellyfin_service:
                        jellyfin_sessions = self.jellyfin_service.get_active_sessions()
                        
                        for session in jellyfin_sessions:
                            now_playing = session.get('NowPlayingItem', {})
                            username = session.get('UserName')
                            if now_playing.get('Type') == 'Movie':
                                if self.is_poster_user(username, 'jellyfin'):
                                    playback_info = {
                                        'id': now_playing.get('Id'),
                                        'position': session.get('PlayState', {}).get('PositionTicks', 0) / 10_000_000
                                    }
                                    service = 'jellyfin'
                                    logger.info(f"Authorized Jellyfin user {username} is playing movie {now_playing.get('Name')}")
                                    break

                    # Check Emby if no Jellyfin playback
                    if not playback_info and self.emby_available and self.emby_service:
                        emby_sessions = self.emby_service.get_active_sessions()
                        
                        for session in emby_sessions:
                            now_playing = session.get('NowPlayingItem', {})
                            username = session.get('UserName')
                            if now_playing.get('Type') == 'Movie':
                                if self.is_poster_user(username, 'emby'):
                                    playback_info = {
                                        'id': now_playing.get('Id'),
                                        'position': session.get('PlayState', {}).get('PositionTicks', 0) / 10_000_000
                                    }
                                    service = 'emby'
                                    logger.info(f"Authorized Emby user {username} is playing movie {now_playing.get('Name')}")
                                    break

                    # Check Plex if no other playback found
                    if not playback_info and self.plex_available and self.plex_service:
                        sessions = self.plex_service.plex.sessions()
                        
                        for session in sessions:
                            username = session.usernames[0] if session.usernames else None
                            if session.type == 'movie':
                                if self.is_poster_user(username, 'plex'):
                                    playback_info = self.plex_service.get_playback_info(session.ratingKey)
                                    service = 'plex'
                                    logger.info(f"Authorized Plex user {username} is playing movie {session.title}")
                                    break

                    if playback_info:
                        movie_id = playback_info.get('id')
                        if movie_id and movie_id != self.current_movie_id:
                            logger.info(f"Detected new movie playback: {movie_id}")
                            # Fetch detailed movie data
                            movie_data = None
                            if service == 'jellyfin':
                                movie_data = self.jellyfin_service.get_movie_by_id(movie_id)
                            elif service == 'emby':
                                movie_data = self.emby_service.get_movie_by_id(movie_id)
                            elif service == 'plex':
                                movie_data = self.plex_service.get_movie_by_id(movie_id)

                            if movie_data:
                                logger.info(f"Setting current movie: {movie_data.get('title')} for service: {service}")
                                set_current_movie(movie_data, service=service, resume_position=playback_info.get('position', 0))
                                self.current_movie_id = movie_id
                    elif self.current_movie_id is not None:
                        logger.info("Playback ended or no authorized playback detected")
                        self.current_movie_id = None
                        default_poster_manager = self.app.config.get('DEFAULT_POSTER_MANAGER')
                        if default_poster_manager:
                            logger.info("Starting timer for default poster")
                            default_poster_manager.handle_playback_state('STOPPED')
                                
                time.sleep(self.interval)
            except Exception as e:
                logger.error(f"Error in PlaybackMonitor: {e}", exc_info=True)
                time.sleep(self.interval)

    def stop(self):
        self.running = False
