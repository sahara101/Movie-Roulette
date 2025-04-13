import os
import sys
import subprocess
import logging
import json
import random
import traceback
import threading
import time
import requests
from datetime import datetime, timedelta
from plexapi.myplex import MyPlexPinLogin
from plexapi.exceptions import Unauthorized 
from plexapi.server import PlexServer 
import uuid
import pytz
import asyncio
import secrets 
from flask import Flask, jsonify, render_template, send_from_directory, request, session, redirect, flash, g, url_for
from flask_wtf.csrf import CSRFProtect 
from flask_socketio import SocketIO, emit
from utils.poster_view import set_current_movie, poster_bp, init_socket
from utils.default_poster_manager import init_default_poster_manager, default_poster_manager
from utils.playback_monitor import PlaybackMonitor
from utils.fetch_movie_links import fetch_movie_links
from functools import lru_cache
from utils.settings.routes import settings_bp
from utils.settings import settings
from utils.cache_manager import CacheManager
from utils.youtube_trailer import search_youtube_trailer
from utils.appletv_discovery import scan_for_appletv, pair_appletv, submit_pin, clear_pairing, ROOT_CONFIG_PATH, turn_on_apple_tv, fix_config_format, check_credentials
from utils.tmdb_service import tmdb_service
from routes.trakt_routes import trakt_bp
from utils.emby_service import EmbyService
from utils.jellyfin_service import JellyfinService 
from utils.tv import TVFactory
from utils.tv.base.tv_discovery import TVDiscoveryFactory
from utils.auth import auth_bp, auth_manager
from routes.user_cache_routes import user_cache_bp
from utils.collection_service import collection_service 

logging.basicConfig(level=logging.INFO) 
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='static', template_folder='web')

flask_secret = os.environ.get('FLASK_SECRET_KEY')
if not flask_secret:
    logger.warning("FLASK_SECRET_KEY environment variable not set. Generating a random key for this session.") 
    flask_secret = secrets.token_hex(32)
app.secret_key = flask_secret

csrf = CSRFProtect() 
csrf.init_app(app) 
socketio = SocketIO(app, cors_allowed_origins="*")
init_socket(socketio)

HOMEPAGE_SETTINGS = {}
FEATURE_SETTINGS = {}
CLIENT_SETTINGS = {}
APPLE_TV_SETTINGS = {}
PLEX_SETTINGS = {}
JELLYFIN_SETTINGS = {}
EMBY_SETTINGS = {}

HOMEPAGE_MODE = False
USE_LINKS = True
USE_FILTER = True
USE_WATCH_BUTTON = True
USE_NEXT_BUTTON = True
PLEX_AVAILABLE = False
JELLYFIN_AVAILABLE = False
MOBILE_TRUNCATION = False
EMBY_AVAILABLE = False
ENABLE_MOVIE_LOGOS = True 

all_plex_unwatched_movies = []
movies_loaded_from_cache = False
loading_in_progress = False
cache_file_path = '/app/data/plex_unwatched_movies.json'
plex = None
jellyfin = None
emby = None
cache_manager = None
_plex_pin_logins = {}

def load_settings():
    """Load all settings and update global variables"""
    global FEATURE_SETTINGS, CLIENT_SETTINGS, APPLE_TV_SETTINGS
    global PLEX_SETTINGS, JELLYFIN_SETTINGS, EMBY_SETTINGS
    global HOMEPAGE_MODE, USE_LINKS, USE_FILTER, USE_WATCH_BUTTON, USE_NEXT_BUTTON, ENABLE_MOVIE_LOGOS
    global PLEX_AVAILABLE, JELLYFIN_AVAILABLE, EMBY_AVAILABLE, MOBILE_TRUNCATION 

    FEATURE_SETTINGS = settings.get('features', {})
    CLIENT_SETTINGS = settings.get('clients', {})
    APPLE_TV_SETTINGS = CLIENT_SETTINGS.get('apple_tv', {})
    PLEX_SETTINGS = settings.get('plex', {})
    JELLYFIN_SETTINGS = settings.get('jellyfin', {})
    EMBY_SETTINGS = settings.get('emby', {})

    HOMEPAGE_MODE = FEATURE_SETTINGS.get('homepage_mode', False)
    USE_LINKS = FEATURE_SETTINGS.get('use_links', True)
    USE_FILTER = FEATURE_SETTINGS.get('use_filter', True)
    USE_WATCH_BUTTON = FEATURE_SETTINGS.get('use_watch_button', True)
    USE_NEXT_BUTTON = FEATURE_SETTINGS.get('use_next_button', True)
    MOBILE_TRUNCATION = FEATURE_SETTINGS.get('mobile_truncation', False)
    ENABLE_MOVIE_LOGOS = FEATURE_SETTINGS.get('enable_movie_logos', True) 

    PLEX_AVAILABLE = (
        bool(PLEX_SETTINGS.get('enabled')) or
        all([
            os.getenv('PLEX_URL'),
            os.getenv('PLEX_TOKEN'),
            os.getenv('PLEX_MOVIE_LIBRARIES')
        ])
    )

    JELLYFIN_AVAILABLE = (
        bool(JELLYFIN_SETTINGS.get('enabled')) or
        all([
            os.getenv('JELLYFIN_URL'),
            os.getenv('JELLYFIN_API_KEY'),
            os.getenv('JELLYFIN_USER_ID')
        ])
    )

    EMBY_AVAILABLE = (
        bool(EMBY_SETTINGS.get('enabled')) or
        all([
            os.getenv('EMBY_URL'),
            os.getenv('EMBY_API_KEY'),
            os.getenv('EMBY_USER_ID')
        ])
    )

    logger.info(f"Settings loaded - Homepage Mode: {HOMEPAGE_MODE}")
    logger.info(f"Service availability - Plex: {PLEX_AVAILABLE}, Jellyfin: {JELLYFIN_AVAILABLE}, Emby: {EMBY_AVAILABLE}")

user_cache_managers = {}
global_cache_manager = None

def initialize_services():
    """Initialize or reinitialize media services based on current settings"""
    global plex, jellyfin, emby, PLEX_AVAILABLE, JELLYFIN_AVAILABLE, EMBY_AVAILABLE
    global cache_manager, global_cache_manager
    global HOMEPAGE_MODE, USE_LINKS, USE_FILTER, USE_WATCH_BUTTON, USE_NEXT_BUTTON

    load_settings()

    logger.info("Initializing TMDB service...")
    try:
        from utils.tmdb_service import tmdb_service
        tmdb_service.initialize_service()
        app.config['TMDB_SERVICE'] = tmdb_service
        logger.info("TMDB service initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize TMDB service: {e}")

    overseerr_settings = settings.get('overseerr', {})
    tmdb_settings = settings.get('tmdb', {})

    logger.info("Starting services initialization")

    logger.info("Initializing global cache manager instance...")
    global_cache_manager = CacheManager(None, cache_file_path, socketio, app, update_interval=600)
    app.config['GLOBAL_CACHE_MANAGER'] = global_cache_manager
    cache_manager = global_cache_manager
    app.config['CACHE_MANAGER'] = cache_manager
    first_service_initialized = False 

    logger.info("Current settings state:")

    from utils.appletv_discovery import fix_config_format
    try:
        fix_config_format()
    except Exception as e:
        logger.error(f"Failed to fix Apple TV config: {e}")

    plex_enabled = bool(PLEX_SETTINGS.get('enabled')) or all([
        os.getenv('PLEX_URL'),
        os.getenv('PLEX_TOKEN'),
        os.getenv('PLEX_MOVIE_LIBRARIES')
    ])
    jellyfin_enabled = bool(JELLYFIN_SETTINGS.get('enabled')) or all([
        os.getenv('JELLYFIN_URL'),
        os.getenv('JELLYFIN_API_KEY'),
        os.getenv('JELLYFIN_USER_ID')
    ])
    emby_enabled = bool(EMBY_SETTINGS.get('enabled')) or all([
        os.getenv('EMBY_URL'),
        os.getenv('EMBY_API_KEY'),
        os.getenv('EMBY_USER_ID')
    ])

    if plex_enabled:
        logger.info("Initializing Plex service...")
        try:
            from utils.plex_service import PlexService
            
            plex = PlexService(
                url=os.getenv('PLEX_URL') or PLEX_SETTINGS.get('url'),
                token=os.getenv('PLEX_TOKEN') or PLEX_SETTINGS.get('token'),
                libraries=os.getenv('PLEX_MOVIE_LIBRARIES', '').split(',') if os.getenv('PLEX_MOVIE_LIBRARIES') else PLEX_SETTINGS.get('movie_libraries', []),
                username=None,  
                cache_manager=global_cache_manager  
            )
            app.config['PLEX_SERVICE'] = plex
            PLEX_AVAILABLE = True

            if not first_service_initialized:
                logger.info("Plex is the first service, associating with global cache manager.")
                global_cache_manager.plex_service = plex 
                global_cache_manager.start()
                first_service_initialized = True

            logger.info("Plex service initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Plex service: {e}")
            plex = None
            PLEX_AVAILABLE = False

    else:
        logger.info("Plex service is not configured")
        plex = None
        PLEX_AVAILABLE = False

    if jellyfin_enabled:
        logger.info("Initializing Jellyfin service...")
        try:
            from utils.jellyfin_service import JellyfinService
            jellyfin = JellyfinService(
                url=os.getenv('JELLYFIN_URL') or JELLYFIN_SETTINGS.get('url'),
                api_key=os.getenv('JELLYFIN_API_KEY') or JELLYFIN_SETTINGS.get('api_key'),
                user_id=os.getenv('JELLYFIN_USER_ID') or JELLYFIN_SETTINGS.get('user_id'),
                update_interval=600
            )
            app.config['JELLYFIN_SERVICE'] = jellyfin
            JELLYFIN_AVAILABLE = True
            logger.info("Jellyfin service initialized successfully")

            if not first_service_initialized:
                logger.info("Jellyfin is the first service, associating with global cache manager.")
                global_cache_manager.jellyfin_service = jellyfin 
                global_cache_manager.start()
                first_service_initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize Jellyfin service: {e}")
            jellyfin = None 
            JELLYFIN_AVAILABLE = False
    else:
        logger.info("Jellyfin service is not configured")
        jellyfin = None 
        JELLYFIN_AVAILABLE = False

    if emby_enabled:
        logger.info("Initializing Emby service...")
        try:
            from utils.emby_service import EmbyService
            emby = EmbyService(
                url=os.getenv('EMBY_URL') or EMBY_SETTINGS.get('url'),
                api_key=os.getenv('EMBY_API_KEY') or EMBY_SETTINGS.get('api_key'),
                user_id=os.getenv('EMBY_USER_ID') or EMBY_SETTINGS.get('user_id')
            )
            app.config['EMBY_SERVICE'] = emby
            EMBY_AVAILABLE = True
            logger.info("Emby service initialized successfully")

            if not first_service_initialized:
                logger.info("Emby is the first service, associating with global cache manager.")
                global_cache_manager.emby_service = emby 
                global_cache_manager.start()
                first_service_initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize Emby service: {e}")
            emby = None 
            EMBY_AVAILABLE = False
    else:
        logger.info("Emby service is not configured")
        emby = None 
        EMBY_AVAILABLE = False

    if not first_service_initialized:
        logger.warning("No primary media service (Plex, Jellyfin, Emby) could be initialized successfully.")
        global_cache_manager = None 
        cache_manager = None 
        app.config['GLOBAL_CACHE_MANAGER'] = None
        app.config['CACHE_MANAGER'] = None

    overseerr_enabled = (
        (bool(os.getenv('OVERSEERR_URL')) and bool(os.getenv('OVERSEERR_API_KEY'))) or
        (bool(overseerr_settings.get('enabled')) and
         bool(overseerr_settings.get('url', '').strip()) and
         bool(overseerr_settings.get('api_key', '').strip()))
    )

    if overseerr_enabled:
        logger.info("Initializing Overseerr service...")
        try:
            from utils.overseerr_service import update_configuration
            success = update_configuration(
                url=os.getenv('OVERSEERR_URL') or overseerr_settings.get('url', ''),
                api_key=os.getenv('OVERSEERR_API_KEY') or overseerr_settings.get('api_key', ''),
            )
            if success:
                logger.info("Overseerr service initialized successfully")
            else:
                logger.error("Failed to initialize Overseerr service")
        except Exception as e:
            logger.error(f"Failed to initialize Overseerr service: {e}")
    else:
        logger.info("Overseerr service is disabled or not configured")
        try:
            from utils.overseerr_service import update_configuration
            update_configuration(url='', api_key='')
        except Exception as e:
            logger.error(f"Failed to reset Overseerr configuration: {e}")

    jellyseerr_settings = settings.get('jellyseerr', {})
    jellyseerr_enabled = (
        (bool(os.getenv('JELLYSEERR_URL')) and bool(os.getenv('JELLYSEERR_API_KEY'))) or
        (bool(jellyseerr_settings.get('enabled')) and
         bool(jellyseerr_settings.get('url', '').strip()) and
         bool(jellyseerr_settings.get('api_key', '').strip()))
    )

    if jellyseerr_enabled:
        logger.info("Initializing Jellyseerr service...")
        try:
            from utils.jellyseerr_service import update_configuration
            if update_configuration(
                url=os.getenv('JELLYSEERR_URL') or jellyseerr_settings.get('url', ''),
                api_key=os.getenv('JELLYSEERR_API_KEY') or jellyseerr_settings.get('api_key', '')
            ):
                logger.info("Jellyseerr service initialized successfully")
            else:
                logger.error("Failed to initialize Jellyseerr service")
        except Exception as e:
            logger.error(f"Failed to initialize Jellyseerr service: {e}")
    else:
        logger.info("Jellyseerr service is disabled or not configured")

    logger.info(f"- Jellyseerr: {jellyseerr_enabled}")

    ombi_settings = settings.get('ombi', {})
    ombi_enabled = (
        (bool(os.getenv('OMBI_URL')) and bool(os.getenv('OMBI_API_KEY'))) or
        (bool(ombi_settings.get('enabled')) and
         bool(ombi_settings.get('url', '').strip()) and
         bool(ombi_settings.get('api_key', '').strip()))
    )

    if ombi_enabled:
        logger.info("Initializing Ombi service...")
        try:
            from utils.ombi_service import update_configuration
            if update_configuration(
                url=os.getenv('OMBI_URL') or ombi_settings.get('url', ''),
                api_key=os.getenv('OMBI_API_KEY') or ombi_settings.get('api_key', '')
            ):
                logger.info("Ombi service initialized successfully")
            else:
                logger.error("Failed to initialize Ombi service")
        except Exception as e:
            logger.error(f"Failed to initialize Ombi service: {e}")
    else:
        logger.info("Ombi service is disabled or not configured")

    trakt_settings = settings.get('trakt', {})
    trakt_enabled = (
        bool(all([
            os.getenv('TRAKT_CLIENT_ID'),
            os.getenv('TRAKT_CLIENT_SECRET'),
            os.getenv('TRAKT_ACCESS_TOKEN'),
            os.getenv('TRAKT_REFRESH_TOKEN')
        ])) or
        (bool(trakt_settings.get('enabled')) and os.path.exists('/app/data/trakt_tokens.json'))
    )

    if trakt_enabled:
        logger.info("Initializing Trakt service...")
        try:
            if 'utils.trakt_service' in sys.modules:
                del sys.modules['utils.trakt_service']
            from utils.trakt_service import initialize_trakt
            if not initialize_trakt():
                logger.error("Failed to initialize Trakt service")
                trakt_enabled = False
        except Exception as e:
            logger.error(f"Failed to initialize Trakt service: {e}")
            trakt_enabled = False

    logger.info(f"Services initialization complete:")
    logger.info(f"- Plex: {PLEX_AVAILABLE}")
    logger.info(f"- Jellyfin: {JELLYFIN_AVAILABLE}")
    logger.info(f"- Emby: {EMBY_AVAILABLE}")
    logger.info(f"- Overseerr: {overseerr_enabled}")
    logger.info(f"- Ombi: {ombi_enabled}")
    logger.info(f"- Jellyseerr: {jellyseerr_enabled}")
    logger.info(f"- Trakt: {trakt_enabled}")

    return True

@app.before_request
def load_user_context_and_cache():
    """Load user data and the appropriate cache manager before each request."""
    g.user = None
    g.media_service = plex or jellyfin or emby 
    g.cache_manager = global_cache_manager

    if auth_manager.auth_enabled:
        token = request.cookies.get('auth_token')
        user_data = auth_manager.verify_auth(token) 

        if user_data:
            internal_username = user_data['username']
            is_admin = user_data['is_admin']
            service_type = user_data.get('service_type', 'local')

            display_username = internal_username
            if internal_username.startswith('plex_'):
                display_username = internal_username[len('plex_'):]
            elif internal_username.startswith('emby_'):
                display_username = internal_username[len('emby_'):]
            elif internal_username.startswith('jellyfin_'):
                display_username = internal_username[len('jellyfin_'):]

            g.user = {
                'internal_username': internal_username,
                'display_username': display_username,
                'is_admin': is_admin,
                'service_type': service_type
            }
            logger.debug(f"Before request: Set g.user = {g.user}")

            user_cm = get_user_cache_manager(internal_username)
            if user_cm:
                g.cache_manager = user_cm
                user_service = None
                if service_type == 'plex' and hasattr(user_cm, 'plex_service'):
                    user_service = user_cm.plex_service
                elif service_type == 'jellyfin' and hasattr(user_cm, 'jellyfin_service'):
                    user_service = user_cm.jellyfin_service
                elif service_type == 'emby' and hasattr(user_cm, 'emby_service'):
                    user_service = user_cm.emby_service
                elif service_type == 'local': 
                    user_service = getattr(user_cm, 'plex_service', None) or \
                                   getattr(user_cm, 'jellyfin_service', None) or \
                                   getattr(user_cm, 'emby_service', None)

                if user_service:
                    g.media_service = user_service
                    logger.debug(f"Before request: Set g.cache_manager and g.media_service ({service_type}) for user '{display_username}'")
                else:
                    g.media_service = plex or jellyfin or emby
                    logger.warning(f"Before request: Set g.cache_manager for user '{display_username}', but couldn't find specific service instance. Falling back to global media service.")
            else:
                 logger.warning(f"Before request: Failed to get cache manager for user '{display_username}', using global defaults.")
        else:
             logger.debug("Before request: No valid user session found, using global defaults.")
    else:
        g.user = {'internal_username': 'admin', 'display_username': 'admin', 'is_admin': True, 'service_type': 'local'}
        logger.debug("Before request: Auth disabled, using admin context and global defaults.")


def get_current_jellyfin_user_creds():
    """Retrieves Jellyfin user_id and api_key for the current session user."""
    user_id = None
    api_key = None
    if auth_manager.auth_enabled and 'username' in session and session.get('service_type') == 'jellyfin':
        username = session['username']
        user_data = auth_manager.db.get_user(username)
        if user_data:
            user_id = user_data.get('jellyfin_user_id')
            api_key = user_data.get('jellyfin_token') 
            if not user_id or not api_key:
                 logger.warning(f"Jellyfin user '{username}' found in session, but missing ID or token in DB.")
                 user_id = None
                 api_key = None
        else:
            logger.warning(f"User '{username}' from session not found in AuthDB.")
    return user_id, api_key

from utils.user_cache import UserCacheManager
user_cache_manager = UserCacheManager(app)
app.config['USER_CACHE_MANAGER'] = user_cache_manager

def get_user_cache_manager(internal_username=None): 
    """Get or create a cache manager for the specified user (using internal username for lookup)"""
    global user_cache_managers, global_cache_manager, plex, cache_manager
    from flask import g as request_context 

    display_username = None
    if hasattr(request_context, 'user') and request_context.user:
         display_username = request_context.user.get('display_username')
         internal_username = request_context.user.get('internal_username') 
         logger.debug(f"get_user_cache_manager: Using display_username '{display_username}' from request context.")
    elif internal_username:
         if internal_username.startswith('plex_'):
             display_username = internal_username[len('plex_'):]
         elif internal_username.startswith('emby_'):
             display_username = internal_username[len('emby_'):]
         elif internal_username.startswith('jellyfin_'):
             display_username = internal_username[len('jellyfin_'):]
         else:
             display_username = internal_username 
         logger.debug(f"get_user_cache_manager: Derived display_username '{display_username}' from internal_username '{internal_username}'.")
    else:
         logger.debug("get_user_cache_manager: No username provided and not in request context.")

    if not display_username or not auth_manager.auth_enabled or display_username == 'admin':
        log_reason = "no user" if not display_username else "auth disabled" if not auth_manager.auth_enabled else "user is admin"
        logger.debug(f"get_user_cache_manager: Returning global cache manager ({log_reason}).")
        if not global_cache_manager:
            logger.warning("Global cache manager is None, attempting to reinitialize services")
            initialize_services()
            if not global_cache_manager:
                 logger.error("Global cache manager is still None after reinitialization attempt.")
                 return None 
        return global_cache_manager

    if internal_username in user_cache_managers:
        logger.debug(f"get_user_cache_manager: Returning existing manager for internal user '{internal_username}'.")
        return user_cache_managers[internal_username]

    logger.info(f"Creating new cache manager for display user: '{display_username}' (internal: '{internal_username}')")

    if not plex:
        logger.error(f"Cannot create user cache manager for '{display_username}': Global plex service is None")
        logger.warning("Attempting to reinitialize services...")
        initialize_services()
        if not plex:
            logger.error("Service reinitialization failed, still no global plex service")
            return global_cache_manager
        logger.info("Services reinitialized successfully, continuing with user cache creation")

    try:
        from utils.plex_service import PlexService

        plex_instance_to_use = global_plex_service = plex 
        service_type = getattr(request_context, 'user', {}).get('service_type', 'local')

        if service_type == 'plex' and display_username != 'admin':
             logger.info(f"Creating user-specific PlexService for Plex user '{display_username}'")
             temp_cache_path_for_plex = None 
             temp_cm_for_plex = CacheManager(None, temp_cache_path_for_plex, socketio, app, username=display_username, service_type=service_type)

             user_plex = PlexService(
                 url=global_plex_service.PLEX_URL,
                 token=global_plex_service.PLEX_TOKEN,
                 libraries=global_plex_service.PLEX_MOVIE_LIBRARIES,
                 username=display_username, 
                 cache_manager=temp_cm_for_plex
             )
             plex_instance_to_use = user_plex
             logger.info(f"Using user-specific Plex instance for cache manager of '{display_username}'")
        else:
             logger.info(f"Using global Plex instance for cache manager of '{display_username}' (service type: {service_type})")

        user_cm = CacheManager.get_user_cache_manager(
             plex_service=plex_instance_to_use, 
             socketio=socketio,
             app=app,
             username=display_username, 
             service_type=service_type 
        )

        if global_cache_manager:
             user_cm._original_cache_manager = global_cache_manager

        user_cm.start()

        user_cache_managers[internal_username] = user_cm

        if user_cm.all_movies_cache_path and not os.path.exists(user_cm.all_movies_cache_path):
            logger.info(f"All movies cache missing for {display_username} at {user_cm.all_movies_cache_path}. Triggering build.")
            socketio.start_background_task(user_cm.cache_all_plex_movies)

        if user_cm.cache_file_path and not os.path.exists(user_cm.cache_file_path):
            logger.info(f"Unwatched cache missing for {display_username} at {user_cm.cache_file_path}. Triggering build.")
            if global_cache_manager:
                 global_cache_manager._initializing = False
            socketio.start_background_task(user_cm.start_cache_build)
        return user_cm
        
    except Exception as e:
        logger.error(f"Error creating user-specific plex service: {e}")
        logger.exception("Stack trace:")
        return global_cache_manager

app.config['user_cache_managers'] = user_cache_managers
app.config['get_user_cache_manager'] = get_user_cache_manager

@app.before_request
def setup_user_cache():
    """Set the appropriate cache manager based on the current user"""
    global cache_manager, plex 

    if request.path.startswith('/static/') or \
       request.path.startswith('/style/') or \
       request.path.startswith('/js/') or \
       request.path.startswith('/logos/') or \
       request.path.startswith('/api/'):
        return

    pass 
    app.config['CACHE_MANAGER'] = cache_manager

@app.before_request
def check_auth_first_run():
    """Redirect to setup if authentication is enabled but no admin exists"""
    if request.path.startswith('/static/') or \
       request.path.startswith('/style/') or \
       request.path.startswith('/js/') or \
       request.path.startswith('/logos/') or \
       request.path.startswith('/login') or \
       request.path.startswith('/setup') or \
       request.path.startswith('/api/auth/'):
        return

    auth_enabled = auth_manager.auth_enabled
    
    if auth_enabled and auth_manager.is_first_run():
        return redirect(url_for('auth.setup'))
    
    if not auth_enabled and request.cookies.get('auth_token'):
        g.clear_auth_cookie = True

def get_available_service():
    if PLEX_AVAILABLE:
        return 'plex'
    elif JELLYFIN_AVAILABLE:
        return 'jellyfin'
    elif EMBY_AVAILABLE:
        return 'emby'
    else:
        raise EnvironmentError("No media service is available")

def resync_cache():
    global all_plex_unwatched_movies, movies_loaded_from_cache, loading_in_progress
    if loading_in_progress:
        return
    loading_in_progress = True
    try:
        if cache_manager:
            cache_manager.update_cache(emit_progress=True)
            all_plex_unwatched_movies = cache_manager.get_cached_movies()
        movies_loaded_from_cache = True
        update_cache_status()
    except Exception as e:
        logger.error(f"Error in resync_cache: {str(e)}")
    finally:
        loading_in_progress = False
        socketio.emit('loading_complete')

def initialize_cache():
    global all_plex_unwatched_movies, movies_loaded_from_cache
    if PLEX_AVAILABLE and cache_manager:
        all_plex_unwatched_movies = cache_manager.get_cached_movies()
        movies_loaded_from_cache = True
        logger.info(f"Loaded {len(all_plex_unwatched_movies)} movies from cache for {getattr(cache_manager, 'username', 'global user')}")
    else:
        logger.info("Cache initialization not required or not available.")

def initialize_user_cache_manager():
    user_cache_manager = UserCacheManager(app)
    app.config['USER_CACHE_MANAGER'] = user_cache_manager
    return user_cache_manager

def update_cache_status():
    global movies_loaded_from_cache

    current_cache_path = cache_manager.cache_file_path if cache_manager else cache_file_path

    if os.path.exists(current_cache_path):
        with open(current_cache_path, 'r') as f:
            cached_movies = json.load(f)
        if cached_movies:
            movies_loaded_from_cache = True
            logger.info(f"Updated cache status: {len(cached_movies)} movies loaded from cache.")
        else:
            movies_loaded_from_cache = False
            logger.info("Cache file exists but is empty.")
    else:
        movies_loaded_from_cache = False
        logger.info(f"Cache file does not exist at {current_cache_path}.")

@lru_cache(maxsize=128)
def cached_search_person(name):
    return tmdb_service.search_person_by_name(name)

def enrich_movie_data(movie_data):
    """Enriches movie data with URLs, correct cast from TMDB, and collection information"""
    current_service = session.get('current_service', get_available_service())
    tmdb_url, trakt_url, imdb_url = fetch_movie_links(movie_data, current_service)
    trailer_url = search_youtube_trailer(movie_data['title'], movie_data['year'])

    tmdb_id = movie_data.get('tmdb_id')
    if tmdb_id:
        credits = tmdb_service.get_movie_cast(tmdb_id)
        if credits:
            movie_data['actors_enriched'] = [
                {
                    "name": actor['name'],
                    "id": actor['id'],
                    "type": "actor",
                    "character": actor.get('character', '')
                }
                for actor in credits['cast']
            ]

            directors_map = {}
            for person in credits['crew']:
                if person['job'] == 'Director' or person['department'] == 'Directing':
                    director_id = person['id']
                    if director_id in directors_map:
                        directors_map[director_id]['jobs'].append(person.get('job', ''))
                    else:
                        directors_map[director_id] = {
                            "name": person['name'],
                            "id": person['id'],
                            "type": "director",
                            "job": person.get('job', ''),
                            "jobs": [person.get('job', '')],
                            "is_primary": person['job'] == 'Director'
                        }

            movie_data['directors_enriched'] = sorted(
                list(directors_map.values()),
                key=lambda x: (not x['is_primary'], x['name'])
            )

            writers_map = {}
            for person in credits['crew']:
                if person['department'] == 'Writing':
                    writer_id = person['id']
                    if writer_id in writers_map:
                        writers_map[writer_id]['jobs'].append(person.get('job', ''))
                    else:
                        writers_map[writer_id] = {
                            "name": person['name'],
                            "id": person['id'],
                            "type": "writer",
                            "job": person.get('job', ''),
                            "jobs": [person.get('job', '')],
                            "is_primary": person['job'] in ['Writer', 'Screenplay']
                        }

            movie_data['writers_enriched'] = sorted(
                list(writers_map.values()),
                key=lambda x: (not x['is_primary'], x['name'])
            )

        try:
            logo_url = tmdb_service.get_movie_logo_url(tmdb_id)
            movie_data['logo_url'] = logo_url
        except Exception as e:
            logger.error(f"Error getting logo URL for movie {tmdb_id}: {e}")
            movie_data['logo_url'] = None

        try:
            from utils.collection_service import collection_service
            collection_status = collection_service.check_collection_status(tmdb_id, current_service)
            movie_data['collection_info'] = collection_status
            logger.info(f"Added collection info for movie {movie_data['title']}: {collection_status['is_in_collection']}")
        except Exception as e:
            logger.error(f"Error getting collection info for movie {tmdb_id}: {e}")
            movie_data['collection_info'] = {'is_in_collection': False, 'previous_movies': []}
    else:
        movie_data.update({
            "actors_enriched": [{"name": name, "id": None, "type": "actor"}
                             for name in movie_data.get('actors', [])],
            "directors_enriched": [{"name": name, "id": None, "type": "director"}
                                for name in movie_data.get('directors', [])],
            "writers_enriched": [{"name": name, "id": None, "type": "writer"}
                                for name in movie_data.get('writers', [])]
        })
        movie_data['collection_info'] = {'is_in_collection': False, 'previous_movies': []}
        movie_data['logo_url'] = None 

    movie_data.update({
        "tmdb_url": tmdb_url,
        "trakt_url": trakt_url,
        "imdb_url": imdb_url,
        "trailer_url": trailer_url,
        "logo_url": movie_data.get('logo_url') 
    })

    return movie_data

def fetch_movie_links_for_overlay(tmdb_id):
    """Get movie links using centralized TMDB service"""
    return tmdb_service.get_movie_links(tmdb_id)

def get_movie_details(movie_id):
    overseerr_settings = settings.get('overseerr', {})
    tmdb_api_key = os.getenv('TMDB_API_KEY') or overseerr_settings.get('tmdb_api_key', '')
    tmdb_url = f"https://api.themoviedb.org/3/movie/{movie_id}?api_key={tmdb_api_key}&append_to_response=credits,release_dates"

    try:
        response = requests.get(tmdb_url)
        response.raise_for_status()
        movie_data = response.json()

        title = movie_data['title']
        year = movie_data['release_date'][:4]
        runtime = movie_data['runtime']
        duration_hours = runtime // 60
        duration_minutes = runtime % 60
        genres = [genre['name'] for genre in movie_data['genres']]
        description = movie_data['overview']
        tmdb_rating = movie_data['vote_average']

        content_rating = "Not rated"
        for release_date in movie_data['release_dates']['results']:
            if release_date['iso_3166_1'] == 'US':
                certifications = release_date['release_dates']
                if certifications and 'certification' in certifications[0]:
                    content_rating = certifications[0]['certification']
                    break

        from utils.trakt_service import get_current_user_id
        user_id = get_current_user_id()
        trakt_rating = get_trakt_rating(movie_id, user_id)
        tmdb_url, trakt_url, imdb_url = fetch_movie_links_for_overlay(movie_id)
        trailer_url = search_youtube_trailer(title, year)

        return {
            "title": title,
            "year": year,
            "duration_hours": duration_hours,
            "duration_minutes": duration_minutes,
            "contentRating": content_rating,
            "genres": genres,
            "tmdb_rating": tmdb_rating,
            "trakt_rating": trakt_rating,
            "description": description,
            "tmdb_url": tmdb_url,
            "trakt_url": trakt_url,
            "imdb_url": imdb_url,
            "trailer_url": trailer_url
        }
    except requests.RequestException as e:
        logger.error(f"Error fetching movie details from TMDb: {e}")
        return None

load_settings()

from routes.overseerr_routes import overseerr_bp
from utils.trakt_service import get_local_watched_movies, sync_watched_status, get_movie_ratings, get_trakt_rating, get_current_user_id

app.register_blueprint(overseerr_bp)
app.register_blueprint(settings_bp)
app.register_blueprint(poster_bp)
app.register_blueprint(trakt_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(user_cache_bp)

default_poster_manager = init_default_poster_manager(socketio)
app.config['DEFAULT_POSTER_MANAGER'] = default_poster_manager
app.config['initialize_services'] = initialize_services

initialize_services()

try:
   logger.info("Setting up movie service for poster manager...")
   current_service = get_available_service()  
   if current_service == 'plex' and PLEX_AVAILABLE and plex:
       logger.info("Using Plex as movie service for poster manager")
       plex.cache_manager = app.config['CACHE_MANAGER']
       default_poster_manager.set_movie_service(plex)
   elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE and jellyfin:
       logger.info("Using Jellyfin as movie service for poster manager")
       default_poster_manager.set_movie_service(jellyfin)
   elif current_service == 'emby' and EMBY_AVAILABLE and emby:
       logger.info("Using Emby as movie service for poster manager")
       default_poster_manager.set_movie_service(emby)
except EnvironmentError:
   logger.warning("No media services available during initialization")

playback_monitor = PlaybackMonitor(app, interval=10)
app.config['PLAYBACK_MONITOR'] = playback_monitor
playback_monitor.start()

@app.route('/')
@auth_manager.require_auth
def index():
    features_settings = settings.get('features', {})
    load_movie_on_start = features_settings.get('load_movie_on_start', False)
    enabled_but_unconfigured = []

    if PLEX_SETTINGS.get('enabled') and not all([
        PLEX_SETTINGS.get('url'),
        PLEX_SETTINGS.get('token'),
        PLEX_SETTINGS.get('movie_libraries')
    ]):
        enabled_but_unconfigured.append('Plex')

    if JELLYFIN_SETTINGS.get('enabled') and not all([
        JELLYFIN_SETTINGS.get('url'),
        JELLYFIN_SETTINGS.get('api_key'),
        JELLYFIN_SETTINGS.get('user_id')
    ]):
        enabled_but_unconfigured.append('Jellyfin')

    if EMBY_SETTINGS.get('enabled') and not all([
        EMBY_SETTINGS.get('url'),
        EMBY_SETTINGS.get('api_key'),
        EMBY_SETTINGS.get('user_id')
    ]):
        enabled_but_unconfigured.append('Emby')

    if enabled_but_unconfigured:
        session.pop('_flashes', None)
        services_list = ', '.join(enabled_but_unconfigured)
        flash(f"The following services are enabled but not fully configured: {services_list}. Please complete the configuration or disable the service.", "error")
        return redirect('/settings')

    if not (PLEX_AVAILABLE or JELLYFIN_AVAILABLE or EMBY_AVAILABLE):
        return redirect('/settings')

    service_type = session.get('service_type', 'local') if auth_manager.auth_enabled else 'local'

    return render_template(
        'index.html',
        service_type=service_type, 
        auth_enabled=auth_manager.auth_enabled,
        homepage_mode=HOMEPAGE_MODE,
        use_links=USE_LINKS,
        use_filter=USE_FILTER,
        use_watch_button=USE_WATCH_BUTTON,
        use_next_button=USE_NEXT_BUTTON,
        mobile_truncation=MOBILE_TRUNCATION,
        enable_movie_logos=ENABLE_MOVIE_LOGOS, 
        load_movie_on_start=load_movie_on_start, 
        settings_disabled=settings.get('system', {}).get('disable_settings', False)
    )

@app.route('/start_loading')
@auth_manager.require_auth 
def start_loading():
    if PLEX_AVAILABLE:
        cache_manager = app.config['CACHE_MANAGER']
        current_cache_path = cache_manager.cache_file_path if cache_manager else cache_file_path
        
        if not os.path.exists(current_cache_path):
            logger.info(f"Cache file does not exist at {current_cache_path}, starting build")
            socketio.start_background_task(cache_manager.start_cache_build)
            return jsonify({"status": "Cache building started"})
        else:
            logger.info(f"Cache exists at {current_cache_path}, validating content")
            if not cache_manager._verify_cache_validity():
                logger.info("Cache validation failed, rebuilding")
                socketio.start_background_task(cache_manager.start_cache_build)
                return jsonify({"status": "Cache validation failed, rebuilding"})
            return jsonify({"status": "Cache already exists and is valid"})
    return jsonify({"status": "Loading not required"})

def any_service_available():
    return PLEX_AVAILABLE or JELLYFIN_AVAILABLE or EMBY_AVAILABLE

@app.after_request
def handle_auth_cookie_clearing(response):
    """Clear auth cookie if auth was just disabled"""
    if hasattr(g, 'clear_auth_cookie') and g.clear_auth_cookie:
        logger.info("Clearing auth cookie as authentication is now disabled")
        response.delete_cookie('auth_token')
    return response

@app.route('/style/<path:filename>')
def style(filename):
    return send_from_directory('static/style', filename)

@app.route('/js/<path:filename>')
def js(filename):
    return send_from_directory('static/js', filename)

@app.route('/logos/<path:filename>')
def logos(filename):
    return send_from_directory('static/logos', filename)

@app.route('/available_services')
@auth_manager.require_auth 
def get_available_services():
    services = []
    service_type = session.get('service_type', 'local')
    is_local_admin = service_type == 'local' 

    plex_configured = PLEX_AVAILABLE and bool(
        PLEX_SETTINGS.get('url') and
        PLEX_SETTINGS.get('token') and
        PLEX_SETTINGS.get('movie_libraries')
    )

    jellyfin_configured = JELLYFIN_AVAILABLE and bool(
        JELLYFIN_SETTINGS.get('url') and
        JELLYFIN_SETTINGS.get('api_key') and
        JELLYFIN_SETTINGS.get('user_id')
    )

    emby_configured = EMBY_AVAILABLE and bool(
        EMBY_SETTINGS.get('url') and
        EMBY_SETTINGS.get('api_key') and
        EMBY_SETTINGS.get('user_id')
    )

    if is_local_admin:
        if plex_configured:
            services.append('plex')
        if jellyfin_configured:
            services.append('jellyfin')
        if emby_configured:
            services.append('emby')
        logger.info(f"Local admin user '{session.get('username')}': Available services: {services}")
    else:
        if service_type == 'plex' and plex_configured:
            services.append('plex')
        elif service_type == 'jellyfin' and jellyfin_configured:
            services.append('jellyfin')
        elif service_type == 'emby' and emby_configured:
            services.append('emby')
        logger.info(f"Non-admin user '{session.get('username')}' (type: {service_type}): Available services: {services}")

    return jsonify(services)

@app.route('/current_service')
@auth_manager.require_auth 
def get_current_service():
    service_type = session.get('service_type', 'local')
    is_local_admin = service_type == 'local' 
    user_available_services = [] 

    plex_configured = PLEX_AVAILABLE and bool(PLEX_SETTINGS.get('url') and PLEX_SETTINGS.get('token') and PLEX_SETTINGS.get('movie_libraries'))
    jellyfin_configured = JELLYFIN_AVAILABLE and bool(JELLYFIN_SETTINGS.get('url') and JELLYFIN_SETTINGS.get('api_key') and JELLYFIN_SETTINGS.get('user_id'))
    emby_configured = EMBY_AVAILABLE and bool(EMBY_SETTINGS.get('url') and EMBY_SETTINGS.get('api_key') and EMBY_SETTINGS.get('user_id'))

    if is_local_admin:
        if plex_configured: user_available_services.append('plex')
        if jellyfin_configured: user_available_services.append('jellyfin')
        if emby_configured: user_available_services.append('emby')
    else:
        if service_type == 'plex' and plex_configured: user_available_services.append('plex')
        elif service_type == 'jellyfin' and jellyfin_configured: user_available_services.append('jellyfin')
        elif service_type == 'emby' and emby_configured: user_available_services.append('emby')

    if not user_available_services:
        logger.warning(f"User {session.get('username')} has no configured services available.")
        first_globally_available = None
        if plex_configured: first_globally_available = 'plex'
        elif jellyfin_configured: first_globally_available = 'jellyfin'
        elif emby_configured: first_globally_available = 'emby'

        if first_globally_available:
             session['current_service'] = first_globally_available
             logger.warning(f"Defaulting user {session.get('username')} to first available service: {first_globally_available}")
             return jsonify({"service": first_globally_available})
        else:
             logger.error("No media services configured globally.")
             return jsonify({"error": "No media services configured"}), 503


    current_service = session.get('current_service')

    if not current_service or current_service not in user_available_services:
        session['current_service'] = user_available_services[0] 
        logger.info(f"Setting current service for user {session.get('username')} to {session['current_service']}")

    return jsonify({"service": session['current_service']})

@app.route('/switch_service')
@auth_manager.require_auth 
def switch_service():
    service_type = session.get('service_type', 'local')
    is_local_admin = service_type == 'local'

    if not is_local_admin:
        logger.info(f"User '{session.get('username')}' (type: {service_type}) attempted to switch service. Denied.")
        return get_current_service() 

    available_services = []
    if PLEX_AVAILABLE and bool(PLEX_SETTINGS.get('url') and PLEX_SETTINGS.get('token') and PLEX_SETTINGS.get('movie_libraries')):
        available_services.append('plex')
    if JELLYFIN_AVAILABLE and bool(JELLYFIN_SETTINGS.get('url') and JELLYFIN_SETTINGS.get('api_key') and JELLYFIN_SETTINGS.get('user_id')):
        available_services.append('jellyfin')
    if EMBY_AVAILABLE and bool(EMBY_SETTINGS.get('url') and EMBY_SETTINGS.get('api_key') and EMBY_SETTINGS.get('user_id')):
        available_services.append('emby')

    if len(available_services) > 1:
        current = session.get('current_service', available_services[0]) 
        try:
            current_index = available_services.index(current)
            next_index = (current_index + 1) % len(available_services)
            new_service = available_services[next_index]
        except ValueError:
            new_service = available_services[0] 

        session['current_service'] = new_service
        logger.info(f"Admin user {session.get('username')} switched service to {new_service}")

        if default_poster_manager:
            new_service_instance = None
            if new_service == 'plex' and PLEX_AVAILABLE and plex:
                logger.info("Switching screensaver to Plex service")
                if global_cache_manager:
                    plex.set_cache_manager(global_cache_manager)
                new_service_instance = plex
            elif new_service == 'jellyfin' and JELLYFIN_AVAILABLE and jellyfin:
                logger.info("Switching screensaver to Jellyfin service")
                new_service_instance = jellyfin
            elif new_service == 'emby' and EMBY_AVAILABLE and emby:
                logger.info("Switching screensaver to Emby service")
                new_service_instance = emby

            if new_service_instance:
                default_poster_manager.set_movie_service(new_service_instance)

        return jsonify({"service": new_service})
    elif len(available_services) == 1:
         session['current_service'] = available_services[0]
         return jsonify({"service": available_services[0]})
    else:
        logger.error("Admin user has no available services during switch attempt.")
        return jsonify({"error": "No services available"}), 503

@app.route('/api/reinitialize_services')
@auth_manager.require_auth 
def reinitialize_services():
    try:
        global emby, EMBY_AVAILABLE, jellyfin, JELLYFIN_AVAILABLE

        if PLEX_AVAILABLE and plex:
            plex.refresh_cache()  
            if cache_manager:
                cache_manager._init_memory_cache()  

        if EMBY_AVAILABLE and emby:
            emby.stop_cache_updater()
            emby = None
            EMBY_AVAILABLE = False

        if JELLYFIN_AVAILABLE and jellyfin:
            jellyfin.stop_cache_updater()
            jellyfin = None
            JELLYFIN_AVAILABLE = False

        if initialize_services():
            return jsonify({"status": "success"})
        else:
            return jsonify({"error": "Failed to reinitialize services"}), 500
    except Exception as e:
        logger.error(f"Error reinitializing services: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/random_movie')
@auth_manager.require_auth 
def random_movie():
   current_service = session.get('current_service', get_available_service())
   global all_plex_unwatched_movies, loading_in_progress, movies_loaded_from_cache
   watch_status = request.args.get('watch_status', 'unwatched')

   try: 
       current_plex_service = getattr(g, 'plex_service', plex) 

       if current_service == 'plex' and PLEX_AVAILABLE and current_plex_service:
           if watch_status == 'unwatched':
               unwatched_movies = current_plex_service._movies_cache
               if not unwatched_movies:
                   current_plex_service._initialize_cache()
                   unwatched_movies = current_plex_service._movies_cache

               if loading_in_progress: 
                   return jsonify({"loading_in_progress": True}), 202
               if not unwatched_movies:
                   return jsonify({"error": "No unwatched movies available"}), 404
               movie_data = random.choice(unwatched_movies)
           else: 
               movie_data = current_plex_service.filter_movies(watch_status=watch_status)
               if not movie_data:
                   return jsonify({"error": "No movies available for this status"}), 404

       elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
           movie_data = jellyfin.filter_movies(watch_status=watch_status)
       elif current_service == 'emby' and EMBY_AVAILABLE:
           emby_instance = None 
           movie_data = None 

           if hasattr(g, 'user') and g.user: 
               if g.user['service_type'] == 'emby': 
                   user_creds = auth_manager.db.get_user(g.user['internal_username']) 
                   if user_creds and user_creds.get('service_user_id') and user_creds.get('service_token'): 
                       try: 
                           emby_url = settings.get('emby', {}).get('url') or os.getenv('EMBY_URL') 
                           if not emby_url: raise ValueError("Emby URL not configured") 
                           emby_instance = EmbyService( 
                               url=emby_url,
                               api_key=user_creds['service_token'],
                               user_id=user_creds['service_user_id']
                           )
                           logger.info(f"Created temporary EmbyService instance for user {g.user['display_username']}") 
                       except Exception as e: 
                           logger.error(f"Failed to create EmbyService instance for user {g.user['display_username']}: {e}") 
                   else: 
                       logger.warning(f"Emby user {g.user['display_username']} found, but missing credentials in DB.") 
               elif g.user['service_type'] == 'local' and g.user['is_admin']: 
                   try: 
                       emby_url = settings.get('emby', {}).get('url') or os.getenv('EMBY_URL') 
                       emby_api_key = settings.get('emby', {}).get('api_key') or os.getenv('EMBY_API_KEY') 
                       emby_user_id = settings.get('emby', {}).get('user_id') or os.getenv('EMBY_USER_ID') 
                       if not all([emby_url, emby_api_key, emby_user_id]): 
                           raise ValueError("Emby not fully configured in settings for admin access.") 
                       emby_instance = EmbyService( 
                           url=emby_url,
                           api_key=emby_api_key,
                           user_id=emby_user_id
                       )
                       logger.info(f"Created temporary EmbyService instance for admin using settings.") 
                   except Exception as e: 
                       logger.error(f"Failed to create EmbyService instance for admin from settings: {e}") 

           if emby_instance: 
               if hasattr(emby_instance, 'get_random_movie'): 
                    movie_data = emby_instance.get_random_movie() 
               elif hasattr(emby_instance, 'filter_movies'): 
                    movie_data = emby_instance.filter_movies(watch_status=watch_status) 
               else: 
                    logger.error("EmbyService instance has neither get_random_movie nor filter_movies method.") 
           else: 
               logger.error("Could not get random movie: Failed to get Emby service instance for user/admin.") 
       else: 
           return jsonify({"error": "No available media service"}), 400 
 
       if movie_data: 
           if 'tmdb_id' not in movie_data: 
                 logger.warning(f"tmdb_id missing for movie {movie_data.get('title')}. Enrichment skipped.") 
                 pass 
           return jsonify({ 
               "service": current_service,
               "movie": movie_data, 
               "cache_loaded": movies_loaded_from_cache,
               "loading_in_progress": loading_in_progress,
               "skip_cache_rebuild": True
           })
       else: 
           return jsonify({"error": "No movie found"}), 404 
   except Exception as e: 
       logger.error(f"Error in random_movie: {str(e)}", exc_info=True) 
       return jsonify({"error": str(e)}), 500 

@app.route('/next_movie')
@auth_manager.require_auth 
def next_movie():
   current_service = session.get('current_service', get_available_service())
   genres = request.args.get('genres', '').split(',') if request.args.get('genres') else None
   years = request.args.get('years', '').split(',') if request.args.get('years') else None
   pg_ratings = request.args.get('pg_ratings', '').split(',') if request.args.get('pg_ratings') else None
   watch_status = request.args.get('watch_status', 'unwatched')

   try: 
       current_plex_service = getattr(g, 'plex_service', plex) 

       if current_service == 'plex' and PLEX_AVAILABLE and current_plex_service:
           movie_data = current_plex_service.filter_movies(genres, years, pg_ratings, watch_status)
       elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
           movie_data = jellyfin.filter_movies(genres, years, pg_ratings, watch_status) 
       elif current_service == 'emby' and EMBY_AVAILABLE:
           emby_instance = None 
           movie_data = None 

           if hasattr(g, 'user') and g.user: 
               if g.user['service_type'] == 'emby': 
                   user_creds = auth_manager.db.get_user(g.user['internal_username']) 
                   if user_creds and user_creds.get('service_user_id') and user_creds.get('service_token'): 
                       try: 
                           emby_url = settings.get('emby', {}).get('url') or os.getenv('EMBY_URL') 
                           if not emby_url: raise ValueError("Emby URL not configured") 
                           emby_instance = EmbyService( 
                               url=emby_url,
                               api_key=user_creds['service_token'],
                               user_id=user_creds['service_user_id']
                           )
                           logger.info(f"Created temporary EmbyService instance for user {g.user['display_username']} (next_movie)") 
                       except Exception as e: 
                           logger.error(f"Failed to create EmbyService instance for user {g.user['display_username']} (next_movie): {e}") 
                   else: 
                       logger.warning(f"Emby user {g.user['display_username']} found, but missing credentials in DB (next_movie).") 
               elif g.user['service_type'] == 'local' and g.user['is_admin']: 
                   try: 
                       emby_url = settings.get('emby', {}).get('url') or os.getenv('EMBY_URL') 
                       emby_api_key = settings.get('emby', {}).get('api_key') or os.getenv('EMBY_API_KEY') 
                       emby_user_id = settings.get('emby', {}).get('user_id') or os.getenv('EMBY_USER_ID') 
                       logger.info(f"Admin Emby Settings Check: URL={emby_url}, Key={'******' if emby_api_key else 'None'}, UserID={emby_user_id}") 
                       if not all([emby_url, emby_api_key, emby_user_id]): 
                           logger.error(f"Admin Emby access failed: Settings incomplete. URL={emby_url}, Key={'******' if emby_api_key else 'None'}, UserID={emby_user_id}") 
                           raise ValueError("Emby not fully configured in settings for admin access.") 
                       emby_instance = EmbyService( 
                           url=emby_url,
                           api_key=emby_api_key,
                           user_id=emby_user_id
                       )
                       logger.info(f"Created temporary EmbyService instance for admin using settings (next_movie).") 
                   except Exception as e: 
                       logger.error(f"Failed to create EmbyService instance for admin from settings (next_movie): {e}") 

           if emby_instance: 
               movie_data = emby_instance.filter_movies(genres, years, pg_ratings, watch_status) 
           else: 
               logger.error("Could not get next movie: Failed to get Emby service instance for user/admin.") 
       else: 
           return jsonify({"error": "No available media service"}), 400 
 
       if movie_data: 
           if 'tmdb_id' not in movie_data: 
                logger.warning(f"tmdb_id missing for movie {movie_data.get('title')} in next_movie. Enrichment skipped.") 
                pass 
           return jsonify({ 
               "service": current_service,
               "movie": movie_data 
           })
       else: 
           return jsonify({"error": "No movies found matching the criteria"}), 204 
   except Exception as e: 
       logger.error(f"Error in next_movie: {str(e)}") 
       return jsonify({"error": str(e)}), 500 

@app.route('/filter_movies')
@auth_manager.require_auth 
def filter_movies():
   current_service = session.get('current_service', get_available_service())
   genres = request.args.get('genres', '').split(',') if request.args.get('genres') else None
   years = request.args.get('years', '').split(',') if request.args.get('years') else None
   pg_ratings = request.args.get('pg_ratings', '').split(',') if request.args.get('pg_ratings') else None
   watch_status = request.args.get('watch_status', 'unwatched')

   try: 
       current_plex_service = getattr(g, 'plex_service', plex) 

       if current_service == 'plex' and PLEX_AVAILABLE and current_plex_service:
           movie_data = current_plex_service.filter_movies(genres, years, pg_ratings, watch_status)
       elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
           user_id, api_key = get_current_jellyfin_user_creds()
           movie_data = jellyfin.filter_movies(genres, years, pg_ratings, watch_status, user_id=user_id, api_key=api_key)
       elif current_service == 'emby' and EMBY_AVAILABLE:
           emby_instance = None 
           movie_data = None 

           if hasattr(g, 'user') and g.user: 
               if g.user['service_type'] == 'emby': 
                   user_creds = auth_manager.db.get_user(g.user['internal_username']) 
                   if user_creds and user_creds.get('service_user_id') and user_creds.get('service_token'): 
                       try: 
                           emby_url = settings.get('emby', {}).get('url') or os.getenv('EMBY_URL') 
                           if not emby_url: raise ValueError("Emby URL not configured") 
                           emby_instance = EmbyService( 
                               url=emby_url,
                               api_key=user_creds['service_token'],
                               user_id=user_creds['service_user_id']
                           )
                           logger.info(f"Created temporary EmbyService instance for user {g.user['display_username']} (filter_movies)") 
                       except Exception as e: 
                           logger.error(f"Failed to create EmbyService instance for user {g.user['display_username']} (filter_movies): {e}") 
                   else: 
                       logger.warning(f"Emby user {g.user['display_username']} found, but missing credentials in DB (filter_movies).") 
               elif g.user['service_type'] == 'local' and g.user['is_admin']: 
                   try: 
                       emby_url = settings.get('emby', {}).get('url') or os.getenv('EMBY_URL') 
                       emby_api_key = settings.get('emby', {}).get('api_key') or os.getenv('EMBY_API_KEY') 
                       emby_user_id = settings.get('emby', {}).get('user_id') or os.getenv('EMBY_USER_ID') 
                       if not all([emby_url, emby_api_key, emby_user_id]): 
                           raise ValueError("Emby not fully configured in settings for admin access.") 
                       emby_instance = EmbyService( 
                           url=emby_url,
                           api_key=emby_api_key,
                           user_id=emby_user_id
                       )
                       logger.info(f"Created temporary EmbyService instance for admin using settings (filter_movies).") 
                   except Exception as e: 
                       logger.error(f"Failed to create EmbyService instance for admin from settings (filter_movies): {e}") 

           if emby_instance: 
               movie_data = emby_instance.filter_movies(genres, years, pg_ratings, watch_status) 
           else: 
               logger.error("Could not filter movies: Failed to get Emby service instance for user/admin.") 
       else: 
           return jsonify({"error": "No available media service"}), 400 
 
       if movie_data: 
           if 'tmdb_id' not in movie_data: 
                logger.warning(f"tmdb_id missing for movie {movie_data.get('title')} in filter_movies. Enrichment skipped.") 
                pass 
           return jsonify({ 
               "service": current_service,
               "movie": movie_data 
           })
       else: 
           return jsonify({"error": "No movies found matching the filter"}), 204 
   except Exception as e: 
       logger.error(f"Error in filter_movies: {str(e)}") 
       return jsonify({"error": str(e)}), 500 

@app.route('/get_genres')
@auth_manager.require_auth 
def get_genres():
    current_service = session.get('current_service', get_available_service())
    watch_status = request.args.get('watch_status', 'unwatched')
    try:
        logger.debug(f"Fetching genres for service: {current_service}")
        current_plex_service = getattr(g, 'plex_service', plex)

        if current_service == 'plex' and PLEX_AVAILABLE and current_plex_service:
            genres_list = current_plex_service.get_genres(watch_status)
            logger.info(f"Found genres: {genres_list}")
            return jsonify(genres_list)
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            genres = jellyfin.get_genres() 
            return jsonify(genres)
        elif current_service == 'emby' and EMBY_AVAILABLE:
            genres = emby.get_genres()
            return jsonify(genres)
        else:
            return jsonify({"error": "No available media service"}), 400
    except Exception as e:
        logger.error(f"Error in get_genres: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/get_years')
@auth_manager.require_auth 
def get_years():
    current_service = session.get('current_service', get_available_service())
    watch_status = request.args.get('watch_status', 'unwatched')
    try:
        logger.debug(f"Fetching years for service: {current_service}")
        current_plex_service = getattr(g, 'plex_service', plex)

        if current_service == 'plex' and PLEX_AVAILABLE and current_plex_service:
            years_list = current_plex_service.get_years(watch_status)
            logger.info(f"Found years: {years_list}")
            return jsonify(years_list)
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            years = jellyfin.get_years() 
            return jsonify(years)
        elif current_service == 'emby' and EMBY_AVAILABLE:
            years = emby.get_years()
            return jsonify(years)
        else:
            return jsonify({"error": "No available media service"}), 400
    except Exception as e:
        logger.error(f"Error in get_years: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/get_pg_ratings')
@auth_manager.require_auth 
def get_pg_ratings():
    current_service = session.get('current_service', get_available_service())
    watch_status = request.args.get('watch_status', 'unwatched')
    try:
        current_plex_service = getattr(g, 'plex_service', plex)

        if current_service == 'plex' and PLEX_AVAILABLE and current_plex_service:
            ratings = current_plex_service.get_pg_ratings(watch_status)
            return jsonify(ratings)
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            ratings = jellyfin.get_pg_ratings() 
            return jsonify(ratings)
        elif current_service == 'emby' and EMBY_AVAILABLE:
            emby_instance = None
            ratings = [] 

            if hasattr(g, 'user') and g.user:
                if g.user['service_type'] == 'emby':
                    user_creds = auth_manager.db.get_user(g.user['internal_username'])
                    if user_creds and user_creds.get('service_user_id') and user_creds.get('service_token'):
                        try:
                            emby_url = settings.get('emby', {}).get('url') or os.getenv('EMBY_URL')
                            if not emby_url: raise ValueError("Emby URL not configured")
                            emby_instance = EmbyService(
                                url=emby_url,
                                api_key=user_creds['service_token'],
                                user_id=user_creds['service_user_id']
                            )
                            logger.info(f"Created temporary EmbyService instance for user {g.user['display_username']} (get_pg_ratings)")
                        except Exception as e:
                            logger.error(f"Failed to create EmbyService instance for user {g.user['display_username']} (get_pg_ratings): {e}")
                    else:
                        logger.warning(f"Emby user {g.user['display_username']} found, but missing credentials in DB (get_pg_ratings).")
                elif g.user['service_type'] == 'local' and g.user['is_admin']:
                    try:
                        emby_url = settings.get('emby', {}).get('url') or os.getenv('EMBY_URL')
                        emby_api_key = settings.get('emby', {}).get('api_key') or os.getenv('EMBY_API_KEY')
                        emby_user_id = settings.get('emby', {}).get('user_id') or os.getenv('EMBY_USER_ID')
                        if not all([emby_url, emby_api_key, emby_user_id]):
                            raise ValueError("Emby not fully configured in settings for admin access.")
                        emby_instance = EmbyService(
                            url=emby_url,
                            api_key=emby_api_key,
                            user_id=emby_user_id
                        )
                        logger.info(f"Created temporary EmbyService instance for admin using settings (get_pg_ratings).")
                    except Exception as e:
                        logger.error(f"Failed to create EmbyService instance for admin from settings (get_pg_ratings): {e}")

            if emby_instance:
                ratings = emby_instance.get_pg_ratings()
            else:
                logger.error("Could not get PG ratings: Failed to get Emby service instance for user/admin.")

            return jsonify(ratings)
        else:
            return jsonify({"error": "No available media service"}), 400
    except Exception as e:
        logger.error(f"Error in get_pg_ratings: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/filtered_movie_count')
@auth_manager.require_auth 
def filtered_movie_count():
    """Returns the count of movies matching the provided filters, respecting the current service."""
    current_service = session.get('current_service', get_available_service())
    logger.info(f"Request for filtered count for service: {current_service}, User: {getattr(g, 'user', 'None')}")

    try:
        genres = request.args.getlist('genres')
        years_str = request.args.getlist('years')
        pg_ratings = request.args.getlist('pgRatings') 
        watch_status = request.args.get('watch_status', 'unwatched')

        try:
            years = [int(y) for y in years_str if y]
        except ValueError:
            logger.warning("Invalid year format received in filters.")
            years = []

        filters = {
            'genres': genres,
            'years': years,
            'pgRatings': pg_ratings,
            'watch_status': watch_status
        }
        logger.debug(f"Parsed filters for count: {filters}")

        count = 0
        if current_service == 'plex':
            if not hasattr(g, 'cache_manager') or not g.cache_manager:
                logger.warning("Plex selected, but cache manager not available for count.")
                return jsonify({"count": 0, "error": "Plex cache not ready"}), 503
            count = g.cache_manager.get_filtered_movie_count(filters)
            logger.debug(f"Plex cache manager returned count: {count}")

        elif current_service == 'jellyfin':
            jellyfin_instance = None
            user_id = None
            api_key = None
            if hasattr(g, 'user') and g.user:
                if g.user['service_type'] == 'jellyfin':
                    user_creds = auth_manager.db.get_user(g.user['internal_username'])
                    if user_creds and user_creds.get('service_user_id') and user_creds.get('service_token'):
                        user_id = user_creds['service_user_id']
                        api_key = user_creds['service_token']
                        logger.debug(f"Using Jellyfin user credentials for count: {g.user['display_username']}")
                    else:
                        logger.warning(f"Jellyfin user {g.user['display_username']} missing credentials for count.")
                elif g.user['is_admin']: 
                    user_id = None 
                    api_key = None
                    logger.debug("Using default/admin Jellyfin credentials for count (admin user).")
            else: 
                 user_id = None
                 api_key = None
                 logger.debug("Using default/admin Jellyfin credentials for count (no user context).")

            try:
                jellyfin_url = settings.get('jellyfin', {}).get('url') or os.getenv('JELLYFIN_URL')
                if not jellyfin_url:
                    raise ValueError("Jellyfin URL is not configured.")

                jellyfin_instance = JellyfinService(url=jellyfin_url, user_id=user_id, api_key=api_key)
                count = jellyfin_instance.get_filtered_movie_count(filters, user_id=user_id, api_key=api_key)
                logger.debug(f"Jellyfin service returned count: {count}")
            except Exception as e:
                 logger.error(f"Failed to instantiate or use JellyfinService for count: {e}")
                 return jsonify({"count": 0, "error": "Failed to connect to Jellyfin"}), 500

        elif current_service == 'emby':
            emby_instance = None
            user_id = None
            api_key = None
            if hasattr(g, 'user') and g.user:
                if g.user['service_type'] == 'emby':
                    user_creds = auth_manager.db.get_user(g.user['internal_username'])
                    if user_creds and user_creds.get('service_user_id') and user_creds.get('service_token'):
                        user_id = user_creds['service_user_id']
                        api_key = user_creds['service_token']
                        logger.debug(f"Using Emby user credentials for count: {g.user['display_username']}")
                    else:
                        logger.warning(f"Emby user {g.user['display_username']} missing credentials for count.")
                elif g.user['is_admin']: 
                    user_id = None 
                    api_key = None
                    logger.debug("Using default/admin Emby credentials for count (admin user).")
            else: 
                 user_id = None
                 api_key = None
                 logger.debug("Using default/admin Emby credentials for count (no user context).")

            try:
                emby_instance = EmbyService(user_id=user_id, api_key=api_key)
                count = emby_instance.get_filtered_movie_count(filters) 
                logger.debug(f"Emby service returned count: {count}")
            except Exception as e:
                 logger.error(f"Failed to instantiate or use EmbyService for count: {e}")
                 return jsonify({"count": 0, "error": "Failed to connect to Emby"}), 500

        else:
            logger.warning(f"Unknown service '{current_service}' requested for filtered count.")
            return jsonify({"count": 0, "error": f"Unsupported service: {current_service}"}), 400

        return jsonify({"count": count})

    except Exception as e:
        logger.error(f"Error in filtered_movie_count route: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"count": 0, "error": "Internal server error"}), 500

@app.route('/clients')
@auth_manager.require_auth 
def clients():
    current_service = session.get('current_service', get_available_service())
    try:
        current_plex_service = getattr(g, 'plex_service', plex)

        if current_service == 'plex' and PLEX_AVAILABLE and current_plex_service:
            client_list = current_plex_service.get_clients()
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            user_id, api_key = get_current_jellyfin_user_creds()
            client_list = jellyfin.get_clients(user_id=user_id, api_key=api_key)
        elif current_service == 'emby' and EMBY_AVAILABLE:
            emby_instance = None
            client_list = [] 

            if hasattr(g, 'user') and g.user:
                if g.user['service_type'] == 'emby':
                    user_creds = auth_manager.db.get_user(g.user['internal_username'])
                    if user_creds and user_creds.get('service_user_id') and user_creds.get('service_token'):
                        try:
                            emby_url = settings.get('emby', {}).get('url') or os.getenv('EMBY_URL')
                            if not emby_url: raise ValueError("Emby URL not configured")
                            emby_instance = EmbyService(
                                url=emby_url,
                                api_key=user_creds['service_token'],
                                user_id=user_creds['service_user_id']
                            )
                            logger.info(f"Created temporary EmbyService instance for user {g.user['display_username']} (clients)")
                        except Exception as e:
                            logger.error(f"Failed to create EmbyService instance for user {g.user['display_username']} (clients): {e}")
                    else:
                        logger.warning(f"Emby user {g.user['display_username']} found, but missing credentials in DB (clients).")
                elif g.user['service_type'] == 'local' and g.user['is_admin']:
                    try:
                        emby_url = settings.get('emby', {}).get('url') or os.getenv('EMBY_URL')
                        emby_api_key = settings.get('emby', {}).get('api_key') or os.getenv('EMBY_API_KEY')
                        emby_user_id = settings.get('emby', {}).get('user_id') or os.getenv('EMBY_USER_ID')
                        if not all([emby_url, emby_api_key, emby_user_id]):
                            raise ValueError("Emby not fully configured in settings for admin access.")
                        emby_instance = EmbyService(
                            url=emby_url,
                            api_key=emby_api_key,
                            user_id=emby_user_id
                        )
                        logger.info(f"Created temporary EmbyService instance for admin using settings (clients).")
                    except Exception as e:
                        logger.error(f"Failed to create EmbyService instance for admin from settings (clients): {e}")

            if emby_instance:
                client_list = emby_instance.get_clients()
            else:
                logger.error("Could not get clients: Failed to get Emby service instance for user/admin.")
        else:
            return jsonify({"error": "No available media service"}), 400
        return jsonify(client_list)
    except Exception as e:
        logger.error(f"Error in clients: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/play_movie/<client_id>')
@auth_manager.require_auth 
def play_movie(client_id):
    movie_id = request.args.get('movie_id')
    if not movie_id:
        return jsonify({"error": "No movie selected"}), 400
    current_service = session.get('current_service', get_available_service())
    try:
        current_plex_service = getattr(g, 'plex_service', plex)

        if current_service == 'plex' and PLEX_AVAILABLE and current_plex_service:
            result = current_plex_service.play_movie(movie_id, client_id)
            if result.get("status") == "playing":
                movie_data = current_plex_service.get_movie_by_id(movie_id)
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            user_id, api_key = get_current_jellyfin_user_creds()
            result = jellyfin.play_movie(movie_id, client_id, user_id=user_id, api_key=api_key)
            if result.get("status") == "playing":
                movie_data = jellyfin.get_movie_by_id(movie_id)
        elif current_service == 'emby' and EMBY_AVAILABLE:
            emby_instance = None
            result = {"status": "error", "error": "Failed to initialize Emby service"} 
            movie_data = None 

            if hasattr(g, 'user') and g.user:
                if g.user['service_type'] == 'emby':
                    user_creds = auth_manager.db.get_user(g.user['internal_username'])
                    if user_creds and user_creds.get('service_user_id') and user_creds.get('service_token'):
                        try:
                            emby_url = settings.get('emby', {}).get('url') or os.getenv('EMBY_URL')
                            if not emby_url: raise ValueError("Emby URL not configured")
                            emby_instance = EmbyService(
                                url=emby_url,
                                api_key=user_creds['service_token'],
                                user_id=user_creds['service_user_id']
                            )
                            logger.info(f"Created temporary EmbyService instance for user {g.user['display_username']} (play_movie)")
                        except Exception as e:
                            logger.error(f"Failed to create EmbyService instance for user {g.user['display_username']} (play_movie): {e}")
                            result = {"status": "error", "error": f"Failed to create Emby service instance: {e}"}
                    else:
                        logger.warning(f"Emby user {g.user['display_username']} found, but missing credentials in DB (play_movie).")
                        result = {"status": "error", "error": "Missing Emby credentials for user"}
                elif g.user['service_type'] == 'local' and g.user['is_admin']:
                    try:
                        emby_url = settings.get('emby', {}).get('url') or os.getenv('EMBY_URL')
                        emby_api_key = settings.get('emby', {}).get('api_key') or os.getenv('EMBY_API_KEY')
                        emby_user_id = settings.get('emby', {}).get('user_id') or os.getenv('EMBY_USER_ID')
                        if not all([emby_url, emby_api_key, emby_user_id]):
                            raise ValueError("Emby not fully configured in settings for admin access.")
                        emby_instance = EmbyService(
                            url=emby_url,
                            api_key=emby_api_key,
                            user_id=emby_user_id
                        )
                        logger.info(f"Created temporary EmbyService instance for admin using settings (play_movie).")
                    except Exception as e:
                        logger.error(f"Failed to create EmbyService instance for admin from settings (play_movie): {e}")
                        result = {"status": "error", "error": f"Failed to create Emby service instance from settings: {e}"}

            if emby_instance:
                result = emby_instance.play_movie(movie_id, client_id)
                if result.get("status") == "playing":
                    movie_data = emby_instance.get_movie_by_id(movie_id)
            else:
                logger.error("Could not play movie: Failed to get Emby service instance for user/admin.")
        else:
            return jsonify({"error": "No available media service"}), 400

        if result.get("status") == "playing" and movie_data and result.get("username"):
            set_current_movie(movie_data, current_service, username=result.get("username"))
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error in play_movie: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/devices')
@auth_manager.require_auth 
def devices():
    """Returns list of all available TV devices"""
    devices = []
    apple_tv_id_env = os.getenv('APPLE_TV_ID')
    if apple_tv_id_env:
        devices.append({
            "name": "apple_tv",
            "displayName": "Apple TV",
            "env_controlled": True
        })
    elif APPLE_TV_SETTINGS.get('enabled') and APPLE_TV_SETTINGS.get('id'):
        devices.append({
            "name": "apple_tv",
            "displayName": "Apple TV",
            "env_controlled": False
        })
    tv_instances = settings.get('clients', {}).get('tvs', {}).get('instances', {})
    for tv_id, tv in tv_instances.items():
        if tv and not isinstance(tv, str) and tv.get('enabled', True):
            try:
                words = tv_id.split('_')
                display_name = ' '.join(word.capitalize() for word in words)

                devices.append({
                    "name": tv_id,
                    "displayName": display_name,  
                    "env_controlled": False,
                    "type": tv.get('type'),
                    "ip": tv.get('ip'),
                    "mac": tv.get('mac')
                })
            except Exception as e:
                logger.error(f"Error adding TV {tv_id} to devices list: {e}")
    logger.debug(f"Available devices: {devices}")
    return jsonify(devices)

@app.route('/turn_on_device/<device>')
@auth_manager.require_auth 
def turn_on_device(device):
    if device == "apple_tv":
        try:
            device_id = APPLE_TV_SETTINGS.get('id') or os.getenv('APPLE_TV_ID')
            if not device_id:
                return jsonify({"error": "Apple TV ID not configured"}), 400

            from utils.appletv_discovery import launch_streaming_app
            result = launch_streaming_app(device_id)
            return jsonify(result)

        except Exception as e:
            logger.error(f"Error turning on Apple TV: {str(e)}")
            return jsonify({"error": f"Failed to turn on Apple TV: {str(e)}"}), 500

    else:  
        try:
            tv = TVFactory.get_tv_controller()
            if not tv:
                return jsonify({"error": "TV not configured or unsupported type"}), 400

            current_service = session.get('current_service', get_available_service())

            async def launch_tv():
                try:
                    success = await tv.turn_on(current_service)
                    if success:
                        return {"status": "success", "message": f"{tv.get_name()} turned on and {current_service} launched"}
                    else:
                        return {"status": "error", "message": "Failed to turn on TV or launch app"}
                except Exception as e:
                    logger.error(f"Failed to launch TV or app: {e}")
                    return {"status": "error", "message": str(e)}

            return jsonify(asyncio.run(launch_tv()))

        except Exception as e:
            return jsonify({"error": f"Failed to control TV: {str(e)}"}), 500

@app.route('/debug_service')
@auth_manager.require_auth
def debug_service():
    """Return debug information based on the authenticated user's service type"""
    global plex, jellyfin, emby, global_cache_manager, user_cache_managers

    user_context = getattr(g, 'user', None)
    if not user_context:
        logger.error("User context (g.user) not found for /debug_service")
        return jsonify({"error": "Authentication context missing"}), 500

    internal_username = user_context.get('internal_username')
    display_username = user_context.get('display_username')
    service_type = user_context.get('service_type', 'local')

    logger.info(f"Debug service request for display_user '{display_username}' (internal: '{internal_username}') with service type '{service_type}'")

    try:
        if service_type == 'plex':
            current_cache_manager = user_cache_managers.get(internal_username, global_cache_manager)
            
            if not current_cache_manager:
                 logger.error(f"No cache manager found for Plex user '{username}' or globally.")
                 return jsonify({"error": "Plex cache manager not available"}), 500
                 
            user_plex = getattr(current_cache_manager, 'plex_service', None)
            if not user_plex:
                 logger.error(f"Plex service instance not found in cache manager for user '{username}'.")
                 user_plex = plex
                 if not user_plex:
                     logger.error("Global Plex service instance also not found.")
                     return jsonify({"error": "Plex service not available"}), 500
                 logger.warning("Falling back to global Plex instance for debug_service.")

            cache_status = current_cache_manager.get_cache_status()
            unwatched_count = 0
            unwatched_cache_path = current_cache_manager.cache_file_path
            if unwatched_cache_path and os.path.exists(unwatched_cache_path):
                try:
                    with open(unwatched_cache_path, 'r') as f:
                        unwatched_data = json.load(f)
                        unwatched_count = len(unwatched_data)
                except Exception as e:
                    logger.error(f"Error reading unwatched cache for debug: {e}")
            all_movies_cache_path = current_cache_manager.all_movies_cache_path
            all_movies_cache_exists = os.path.exists(all_movies_cache_path)
            total_movies = 0
            if all_movies_cache_exists:
                try:
                    with open(all_movies_cache_path, 'r') as f:
                        total_movies = len(json.load(f))
                except Exception as json_e:
                    logger.error(f"Error reading Plex all movies cache ({all_movies_cache_path}): {json_e}")

            unwatched_cache_path = current_cache_manager.cache_file_path
            all_movies_cache_path = current_cache_manager.all_movies_cache_path
            metadata_cache_path = current_cache_manager.metadata_cache_path

            return jsonify({
                "service": "plex",
                "plex_url": user_plex.PLEX_URL,
                "total_movies": total_movies,
                "total_unwatched_movies": unwatched_count,
                "cache_file_exists": cache_status.get('cache_file_exists', False), 
                "all_movies_cache_exists": all_movies_cache_exists, 
                "username": display_username, 
                "user_specific_cache": display_username is not None and display_username != 'admin',
                "unwatched_cache_path": unwatched_cache_path, 
                "all_movies_cache_path": all_movies_cache_path, 
                "metadata_cache_path": metadata_cache_path 
            })

        elif service_type == 'jellyfin':
            if not jellyfin:
                logger.error("Jellyfin service not initialized for debug_service")
                return jsonify({"error": "Jellyfin service not available"}), 500

            config_user_id = settings.get('jellyfin.user_id', 'Not Set')
            unwatched_count = jellyfin.get_unwatched_count() 

            all_movies_cache_path = jellyfin.cache_path 
            cache_exists = os.path.exists(all_movies_cache_path)
            total_movies = 0
            if cache_exists:
                 try:
                     with open(all_movies_cache_path, 'r') as f:
                         total_movies = len(json.load(f))
                 except Exception as json_e:
                     logger.error(f"Error reading Jellyfin all movies cache ({all_movies_cache_path}): {json_e}")

            return jsonify({
                "service": "jellyfin",
                "jellyfin_url": jellyfin.server_url,
                "total_movies": total_movies,
                "total_unwatched_movies": unwatched_count, 
                "cache_file_exists": cache_exists, 
                "username": display_username, 
                "configured_user_id": config_user_id, 
                "cache_path": jellyfin.cache_path, 
                "user_specific_cache": False 
            })

        elif service_type == 'emby':
            if not emby:
                logger.error("Emby service not initialized for debug_service")
                return jsonify({"error": "Emby service not available"}), 500

            config_user_id = emby.user_id
            unwatched_count = emby.get_unwatched_count()

            all_movies_cache_path = emby.cache_path 
            cache_exists = os.path.exists(all_movies_cache_path)
            total_movies = 0
            if cache_exists:
                 try:
                     with open(all_movies_cache_path, 'r') as f:
                         total_movies = len(json.load(f))
                 except Exception as json_e:
                     logger.error(f"Error reading Emby all movies cache ({all_movies_cache_path}): {json_e}")

            return jsonify({
                "service": "emby",
                "emby_url": emby.server_url,
                "total_movies": total_movies,
                "total_unwatched_movies": unwatched_count,
                "cache_file_exists": cache_exists, 
                "username": display_username, 
                "configured_user_id": config_user_id, 
                "cache_path": emby.cache_path, 
                "user_specific_cache": False 
            })

        elif service_type == 'local' and display_username == 'admin':
             logger.info(f"Debug service request for admin user.")
             admin_debug_info = {"service": "admin_overview", "username": "admin"}
             if PLEX_AVAILABLE and plex and global_cache_manager:
                 try:
                     plex_status = {}
                     plex_status['plex_url'] = plex.PLEX_URL
                     plex_status['cache_status'] = global_cache_manager.get_cache_status()
                     plex_status['total_unwatched_movies'] = plex.get_total_unwatched_movies() 

                     all_movies_cache_path = global_cache_manager.all_movies_cache_path
                     all_movies_cache_exists = os.path.exists(all_movies_cache_path)
                     plex_status['all_movies_cache_exists'] = all_movies_cache_exists
                     total_movies = 0
                     if all_movies_cache_exists:
                         try: 
                              with open(all_movies_cache_path, 'r') as f: total_movies = len(json.load(f))
                         except Exception as json_e:
                              logger.error(f"Error reading Plex all movies cache for admin debug ({all_movies_cache_path}): {json_e}")
                              plex_status['total_movies_error'] = str(json_e)
                     plex_status['total_movies'] = total_movies
                     plex_status['unwatched_cache_path'] = global_cache_manager.cache_file_path
                     plex_status['all_movies_cache_path'] = global_cache_manager.all_movies_cache_path
                     plex_status['metadata_cache_path'] = global_cache_manager.metadata_cache_path
                     admin_debug_info['plex_global'] = plex_status
                 except Exception as e:
                     logger.error(f"Failed to get Plex global debug info for admin: {str(e)}")
                     admin_debug_info['plex_global'] = {"error": f"Failed to get Plex global debug info: {str(e)}"}

             if JELLYFIN_AVAILABLE and jellyfin:
                 try:
                     jellyfin_status = {}
                     jellyfin_status['jellyfin_url'] = jellyfin.server_url
                     jellyfin_status['configured_user_id'] = jellyfin.admin_user_id 
                     jellyfin_status['total_unwatched_movies'] = jellyfin.get_unwatched_count() 

                     cache_path = jellyfin.cache_path
                     cache_exists = os.path.exists(cache_path)
                     jellyfin_status['cache_file_exists'] = cache_exists
                     total_movies = 0
                     if cache_exists:
                         try: 
                              with open(cache_path, 'r') as f: total_movies = len(json.load(f))
                         except Exception as json_e:
                              logger.error(f"Error reading Jellyfin all movies cache for admin debug ({cache_path}): {json_e}")
                              jellyfin_status['total_movies_error'] = str(json_e)
                     jellyfin_status['total_movies'] = total_movies
                     jellyfin_status['cache_path'] = jellyfin.cache_path 
                     admin_debug_info['jellyfin_global'] = jellyfin_status
                 except Exception as e:
                     logger.error(f"Failed to get Jellyfin global debug info for admin: {str(e)}")
                     admin_debug_info['jellyfin_global'] = {"error": f"Failed to get Jellyfin global debug info: {str(e)}"}

             if EMBY_AVAILABLE and emby:
                 try:
                     emby_status = {}
                     emby_status['emby_url'] = emby.server_url
                     emby_status['configured_user_id'] = emby.user_id 
                     emby_status['total_unwatched_movies'] = emby.get_unwatched_count() 

                     cache_path = emby.cache_path
                     cache_exists = os.path.exists(cache_path)
                     emby_status['cache_file_exists'] = cache_exists
                     total_movies = 0
                     if cache_exists:
                         try: 
                              with open(cache_path, 'r') as f: total_movies = len(json.load(f))
                         except Exception as json_e:
                              logger.error(f"Error reading Emby all movies cache for admin debug ({cache_path}): {json_e}")
                              emby_status['total_movies_error'] = str(json_e)
                     emby_status['total_movies'] = total_movies
                     emby_status['cache_path'] = emby.cache_path 
                     admin_debug_info['emby_global'] = emby_status
                 except Exception as e:
                     logger.error(f"Failed to get Emby global debug info for admin: {str(e)}")
                     admin_debug_info['emby_global'] = {"error": f"Failed to get Emby global debug info: {str(e)}"}

             return jsonify(admin_debug_info)

        elif service_type == 'local': 
             logger.info(f"Debug service request for local user '{display_username}'")
             return jsonify({
                 "service": "local",
                 "username": display_username,
                 "message": "Local users do not have media service debug information."
             })

        else:
            logger.error(f"Unknown service type '{service_type}' for user '{display_username}' (internal: '{internal_username}') in debug_service")
            return jsonify({"error": f"Unknown service type: {service_type}"}), 400

    except Exception as e:
        logger.error(f"Error in debug_service for user '{display_username}' (internal: '{internal_username}', service: {service_type}): {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/resync_cache')
@auth_manager.require_auth 
def trigger_resync():
    resync_cache()
    return jsonify({"status": "Cache resync completed"})

@app.route('/trakt_watched_status')
def trakt_watched_status():
    """Get Trakt watched status for current user"""
    user_id = get_current_user_id()
    watched_movies = get_local_watched_movies(user_id)
    return jsonify(watched_movies)

@app.route('/sync_trakt_watched')
def sync_trakt_watched():
    """Sync watched status for current user"""
    user_id = get_current_user_id()
    watched_movies = sync_watched_status(user_id)
    return jsonify(watched_movies)

@app.route('/api/movie_ratings/<int:tmdb_id>')
def movie_ratings(tmdb_id):
    try:
        user_id = get_current_user_id()
        ratings = get_movie_ratings(tmdb_id, user_id)
        return jsonify(ratings)
    except Exception as e:
        logger.error(f"Error fetching movie ratings: {str(e)}")
        return jsonify({"error": "Failed to fetch ratings"}), 500

@app.route('/api/batch_movie_ratings', methods=['POST'])
def batch_movie_ratings():
    movie_ids = request.json.get('movie_ids', [])
    ratings = {}
    for movie_id in movie_ids:
        user_id = get_current_user_id()
        ratings[movie_id] = get_movie_ratings(movie_id, user_id)
    return jsonify(ratings)

@app.route('/api/youtube_trailer')
def youtube_trailer():
    title = request.args.get('title')
    year = request.args.get('year')
    if not title or not year:
        return "Missing title or year parameter", 400

    trailer_url = search_youtube_trailer(title, year)
    return trailer_url

@app.route('/is_movie_in_plex/<int:tmdb_id>')
def is_movie_in_plex(tmdb_id):
    current_plex_service = getattr(g, 'plex_service', plex)
    cm = getattr(g, 'cache_manager', cache_manager)

    if not PLEX_AVAILABLE or not current_plex_service or not cm:
        return jsonify({"available": False})

    try:
        all_plex_movies = cm.get_all_plex_movies()
        is_available = any(
            str(movie.get('tmdb_id')) == str(tmdb_id)
            for movie in all_plex_movies 
        )
        return jsonify({"available": is_available})
    except Exception as e:
        logger.error(f"Error checking Plex availability: {str(e)}")
        return jsonify({"available": False, "error": str(e)})

@app.route('/api/get_plex_id/<tmdb_id>')
def get_plex_id(tmdb_id):
    cm = getattr(g, 'cache_manager', cache_manager)
    if not cm:
         return jsonify({"error": "Cache manager not available"}), 500

    try:
        all_movies = cm.get_all_plex_movies() 
        for movie in all_movies:
            if str(movie.get('tmdb_id')) == str(tmdb_id):
                return jsonify({"plexId": movie['id']})  

        logger.warning(f"Movie with TMDb ID {tmdb_id} not found in Plex")
        return jsonify({"error": "Movie not found in Plex"}), 404

    except Exception as e:
        logger.error(f"Error getting Plex ID: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/get_jellyfin_id/<tmdb_id>')
def get_jellyfin_id(tmdb_id):
    try:
        if not JELLYFIN_AVAILABLE or not jellyfin:
            return jsonify({"error": "Jellyfin not available"}), 404

        cache_path = '/app/data/jellyfin_all_movies.json'
        if not os.path.exists(cache_path):
            return jsonify({"error": "Jellyfin cache not found"}), 404

        with open(cache_path, 'r') as f:
            all_movies = json.load(f)

        for movie in all_movies:
            if str(movie.get('tmdb_id')) == str(tmdb_id):
                return jsonify({"jellyfinId": movie['jellyfin_id']})

        return jsonify({"error": "Movie not found in Jellyfin"}), 404

    except Exception as e:
        logger.error(f"Error getting Jellyfin ID: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/get_emby_id/<tmdb_id>')
def get_emby_id(tmdb_id):
    try:
        if not EMBY_AVAILABLE or not emby:
            return jsonify({"error": "Emby not available"}), 404

        cache_path = '/app/data/emby_all_movies.json'
        if not os.path.exists(cache_path):
            return jsonify({"error": "Emby cache not found"}), 404

        with open(cache_path, 'r') as f:
            all_movies = json.load(f)

        for movie in all_movies:
            if str(movie.get('tmdb_id')) == str(tmdb_id):
                return jsonify({"embyId": movie['emby_id']})

        return jsonify({"error": "Movie not found in Emby"}), 404

    except Exception as e:
        logger.error(f"Error getting Emby ID: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/tv/scan/<tv_type>')
def scan_for_tv(tv_type):
    """Scan for TVs of specified type"""
    try:
        from utils.tv.base import TVDiscoveryFactory

        discovery = TVDiscoveryFactory.get_discovery(tv_type)
        if not discovery:
            return jsonify({
                "error": f"Unsupported TV type: {tv_type}",
                "devices": []
            }), 400

        devices = discovery.scan_network()

        return jsonify({
            "devices": devices,
            "found": len(devices) > 0
        })

    except Exception as e:
        logger.error(f"Error scanning for {tv_type} TVs: {str(e)}")
        return jsonify({
            "error": str(e),
            "devices": []
        }), 500

@app.route('/api/tv/test/<tv_id>')
def test_tv_connection(tv_id):
    """Test connection to a specific TV"""
    try:
        logger.info(f"Starting TV connection test for device ID: {tv_id}")

        controller = TVFactory.get_tv_controller(tv_id)
        if not controller:
            logger.error(f"Failed to get TV controller for ID: {tv_id}")
            return jsonify({"error": "TV not found"}), 404

        logger.info(f"Got controller for {controller.manufacturer} {controller.tv_type} TV at IP: {controller.ip}")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            logger.info(f"Starting availability check for {controller.ip}...")
            is_available = loop.run_until_complete(controller.is_available())
            logger.info(f"TV connection test complete for {controller.ip} - Available: {is_available}")

            if not is_available:
                logger.warning(f"TV at {controller.ip} is not available. Check TV power state and network connection.")

            return jsonify({"success": is_available})
        finally:
            loop.close()

    except Exception as e:
        logger.error(f"Error during TV connection test: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@app.route('/api/appletv/scan')
def scan_for_appletv_devices():
    """Scan for Apple TVs on the network"""
    try:
        devices = scan_for_appletv()
        return jsonify({
            'devices': devices,
            'found': len(devices) > 0
        })
    except Exception as e:
        logger.error(f"Error scanning for Apple TVs: {str(e)}")
        return jsonify({
            'error': str(e),
            'devices': []
        }), 500

@app.route('/api/appletv/pair/<device_id>')
def start_appletv_pairing(device_id):
    """Start pairing process with Apple TV"""
    try:
        result = pair_appletv(device_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error starting pairing: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/appletv/pin/<device_id>', methods=['POST'])
def submit_appletv_pin(device_id):
    """Submit PIN for Apple TV pairing"""
    try:
        pin = request.json.get('pin')
        if not pin:
            return jsonify({
                'status': 'error',
                'message': 'PIN is required'
            }), 400

        result = submit_pin(device_id, pin)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error submitting PIN: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/appletv/cancel/<device_id>')
def cancel_appletv_pairing(device_id):
    """Cancel ongoing pairing process"""
    try:
        from utils.appletv_discovery import _pairing_process
        if _pairing_process:
            _pairing_process.close()
            return jsonify({
                'status': 'success',
                'message': 'Pairing cancelled'
            })
        return jsonify({
            'status': 'success',
            'message': 'No active pairing to cancel'
        })
    except Exception as e:
        logger.error(f"Error cancelling pairing: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/appletv/check_credentials', methods=['POST'])
def check_appletv_credentials():
    try:
        data = request.get_json()
        device_id = data.get('device_id')

        if not device_id:
            return jsonify({"error": "No device ID provided"}), 400

        from utils.appletv_discovery import check_credentials
        has_credentials = check_credentials(device_id)

        return jsonify({"has_credentials": has_credentials})

    except Exception as e:
        logger.error(f"Error checking Apple TV credentials: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/settings')
def settings_page():
    return render_template('settings.html')

@app.route('/setup_status')
def setup_status():
    return jsonify({
        'services_configured': bool(PLEX_AVAILABLE or JELLYFIN_AVAILABLE or EMBY_AVAILABLE),
        'plex_available': PLEX_AVAILABLE,
        'jellyfin_available': JELLYFIN_AVAILABLE,
        'emby_available': EMBY_AVAILABLE
    })

@app.route('/api/service_status')
def service_status():
    """Return the current status of media services"""
    return jsonify({
        'services_configured': bool(PLEX_AVAILABLE or JELLYFIN_AVAILABLE or EMBY_AVAILABLE),
        'plex_available': PLEX_AVAILABLE,
        'jellyfin_available': JELLYFIN_AVAILABLE,
        'emby_available': EMBY_AVAILABLE
    })

@app.route('/api/plex/get_token', methods=['POST'])
def get_plex_token():
    try:
        client_id = str(uuid.uuid4())
        headers = {
            'X-Plex-Client-Identifier': client_id,
            'X-Plex-Product': 'Movie Roulette',
            'X-Plex-Version': '1.0',
            'X-Plex-Device': 'Web',
            'X-Plex-Device-Name': 'Movie Roulette Web Client',
            'X-Plex-Platform': 'Web',
            'X-Plex-Platform-Version': '1.0'
        }

        pin_login = MyPlexPinLogin(headers=headers)

        _plex_pin_logins[client_id] = pin_login

        logger.info("Plex auth initiated with PIN: ****")

        return jsonify({
            "auth_url": "https://plex.tv/link",
            "pin": pin_login.pin,
            "client_id": client_id
        })
    except Exception as e:
        logger.error(f"Error in get_plex_token: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route('/api/plex/check_auth/<client_id>')
def check_plex_auth(client_id):
    try:
        pin_login = _plex_pin_logins.get(client_id)

        if not pin_login:
            logger.warning("No PIN login instance found for this client")
            return jsonify({"token": None})

        if pin_login.checkLogin():
            token = pin_login.token
            logger.info("Successfully retrieved Plex token")
            del _plex_pin_logins[client_id]
            return jsonify({"token": token})

        return jsonify({"token": None})

    except Exception as e:
        logger.error(f"Error in check_plex_auth: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route('/api/plex/libraries', methods=['POST'])
def get_plex_libraries():
    try:
        data = request.json
        plex_url = data.get('plex_url')
        plex_token = data.get('plex_token')

        if not plex_url or not plex_token:
            return jsonify({"error": "Missing Plex URL or token"}), 400

        from plexapi.server import PlexServer
        server = PlexServer(plex_url, plex_token)

        libraries = [
            section.title
            for section in server.library.sections()
            if section.type == 'movie'
        ]

        return jsonify({"libraries": libraries})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/jellyfin/auth', methods=['POST'])
def jellyfin_auth():
    try:
        data = request.json
        server_url = data.get('server_url')
        username = data.get('username')
        password = data.get('password')

        if not all([server_url, username, password]):
            return jsonify({"error": "Missing required fields"}), 400

        if server_url.endswith('/'):
            server_url = server_url[:-1]

        auth_data = {
            "Username": username,
            "Pw": password
        }

        auth_response = requests.post(
            f"{server_url}/Users/AuthenticateByName",
            json=auth_data,
            headers={
                "X-Emby-Authorization": 'MediaBrowser Client="Movie Roulette", Device="Script", DeviceId="Script", Version="1.0.0"'
            }
        )

        if not auth_response.ok:
            return jsonify({"error": "Invalid credentials"}), 401

        auth_result = auth_response.json()

        return jsonify({
            "api_key": auth_result['AccessToken'],
            "user_id": auth_result['User']['Id']
        })

    except Exception as e:
        logger.error(f"Error in jellyfin_auth: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500

@app.route('/api/plex/users', methods=['POST'])
@auth_manager.require_admin 
def get_plex_users():
    """Fetch Plex users (owner + managed) for a given server/token."""
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400

    data = request.get_json()
    plex_url = data.get('plex_url')
    plex_token = data.get('plex_token')

    if not plex_url or not plex_token:
        return jsonify({"error": "Plex URL and token are required"}), 400

    logger.info(f"Attempting to fetch users from Plex server: {plex_url}")

    try:
        temp_plex = PlexServer(plex_url, plex_token, timeout=20)
        
        owner_account = temp_plex.myPlexAccount()
        owner_username = owner_account.username if owner_account else None
        
        users = []
        if owner_username:
            owner_id = owner_account.id if hasattr(owner_account, 'id') and owner_account.id else 'owner_placeholder_id'
            users.append({"id": owner_id, "username": owner_username})
            logger.info(f"Found owner account: {owner_username} (ID: {owner_id})")
        else:
            logger.warning("Could not retrieve owner username from Plex.")

        managed_users = temp_plex.myPlexAccount().users() 
        if managed_users:
            for user in managed_users:
                 managed_id = user.id if hasattr(user, 'id') and user.id else f'managed_placeholder_{user.title}'
                 users.append({"id": managed_id, "username": user.title})
            logger.info(f"Found {len(managed_users)} managed users.")
        else:
             logger.info("No managed users found for this account.")

        logger.info(f"Returning users: {[u['username'] for u in users]}")
        return jsonify({"users": users})

    except Unauthorized:
        logger.error(f"Unauthorized: Invalid Plex token for URL {plex_url}")
        return jsonify({"error": "Invalid Plex token"}), 401
    except requests.exceptions.Timeout:
         logger.error(f"Timeout: Connection to Plex server at {plex_url} timed out.")
         return jsonify({"error": f"Connection to Plex server timed out"}), 504 
    except requests.exceptions.ConnectionError as ce:
         logger.error(f"Connection Error: Could not connect to Plex server at {plex_url}: {ce}")
         return jsonify({"error": f"Could not connect to Plex server at {plex_url}"}), 502 
    except Exception as e:
        logger.error(f"Error fetching Plex users from {plex_url}: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": "An unexpected error occurred while fetching Plex users."}), 500

@app.route('/api/jellyfin/users', methods=['POST'])
def get_jellyfin_users():
    try:
        data = request.json
        jellyfin_url = data.get('jellyfin_url')
        api_key = data.get('api_key')

        if not jellyfin_url or not api_key:
            return jsonify({"error": "Missing Jellyfin URL or API key"}), 400

        if jellyfin_url.endswith('/'):
            jellyfin_url = jellyfin_url[:-1]

        response = requests.get(
            f"{jellyfin_url}/Users",
            headers={
                'X-MediaBrowser-Token': api_key
            }
        )

        if not response.ok:
            return jsonify({"error": "Failed to fetch users"}), response.status_code

        users = [user['Name'] for user in response.json()]
        return jsonify({"users": users})
    except Exception as e:
        logger.error(f"Error fetching Jellyfin users: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/emby/connect/auth', methods=['POST'])
def emby_connect_auth():
    """Handle Emby Connect authentication"""
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')

        if not all([username, password]):
            return jsonify({"error": "Username and password are required"}), 400

        emby = EmbyService()
        auth_result = emby.authenticate_with_connect(username, password)
        return jsonify(auth_result)
    except Exception as e:
        logger.error(f"Error in Emby Connect auth: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/emby/connect/check', methods=['POST'])
def emby_connect_check():
    """Check Emby Connect authentication status"""
    try:
        data = request.json
        server_url = data.get('server_url')
        connect_token = data.get('connect_token')

        if not server_url or not connect_token:
            return jsonify({"error": "Server URL and Connect token are required"}), 400

        emby = EmbyService(url=server_url)
        auth_result = emby.check_connect_auth(connect_token)
        return jsonify(auth_result)
    except Exception as e:
        logger.error(f"Error checking Emby Connect auth: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/emby/connect/select_server', methods=['POST'])  
def emby_select_server():
    try:
        data = request.json
        server_info = data.get('server')
        connect_user_id = data.get('connect_user_id')

        if not all([server_info, connect_user_id]):
            return jsonify({"error": "Server info and connect user ID required"}), 400

        server_url = server_info.get('url')  
        if not server_url:
            return jsonify({"error": "Missing server URL"}), 400

        emby = EmbyService(url=server_url)

        exchange_headers = {
            'X-Emby-Token': server_info.get('access_key'),  
            'X-Emby-Authorization': ('MediaBrowser Client="Movie Roulette",'
                                   'Device="Movie Roulette",'
                                   'DeviceId="MovieRoulette",'
                                   'Version="1.0.0"')
        }

        exchange_response = requests.get(
            f"{server_url}/Connect/Exchange?format=json&ConnectUserId={connect_user_id}",
            headers=exchange_headers
        )
        exchange_response.raise_for_status()
        exchange_data = exchange_response.json()

        return jsonify({
            "status": "success",
            "api_key": exchange_data['AccessToken'],
            "user_id": exchange_data['LocalUserId'],
            "server_url": server_url
        })
    except Exception as e:
        logger.error(f"Error selecting Emby server: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/emby/auth', methods=['POST'])
def emby_direct_auth():
    """Handle direct Emby authentication"""
    try:
        data = request.json
        server_url = data.get('server_url')
        username = data.get('username')
        password = data.get('password')

        if not all([server_url, username, password]):
            return jsonify({"error": "Server URL, username, and password are required"}), 400

        emby = EmbyService(url=server_url)
        auth_result = emby.authenticate(username, password)

        return jsonify(auth_result)
    except Exception as e:
        logger.error(f"Error in Emby direct auth: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/emby/users', methods=['POST'])
def get_emby_users():
    try:
        data = request.json
        emby_url = data.get('emby_url')
        api_key = data.get('api_key')

        if not emby_url or not api_key:
            return jsonify({"error": "Missing Emby URL or API key"}), 400

        emby = EmbyService(url=emby_url, api_key=api_key)
        users = emby.get_users()
        return jsonify({"users": users})
    except Exception as e:
        logger.error(f"Error fetching Emby users: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/search_person')
def search_person_api():
    """Search for a person and return their details with TMDb and IMDb links"""
    name = request.args.get('name')
    if not name:
        return jsonify({"error": "Name parameter is required"}), 400

    try:
        person = tmdb_service.search_person(name)
        if person:
            tmdb_url, imdb_url = tmdb_service.get_person_links(person['id'])

            return jsonify({
                **person,
                'links': {
                    'tmdb': tmdb_url,
                    'imdb': imdb_url
                }
            })
        return jsonify({"error": "Person not found"}), 404
    except Exception as e:
        logger.error(f"Error searching for person: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/movies_by_person')
def get_movies_by_person():
    person_id = request.args.get('person_id')
    person_type = request.args.get('person_type', 'actor')

    if not person_id:
        return jsonify({"error": "Person ID is required"}), 400

    try:
        movies = tmdb_service.get_person_movies(person_id)
        if movies:
            logger.debug(f"Before filtering - Total movies: {len(movies)}")
            logger.debug("Departments and jobs:")
            for m in movies:
                logger.debug(f"Department: {m.get('department')}, Job: {m.get('job')}")

            if person_type == 'director':
                movies = [m for m in movies if m.get('department') == 'Directing']
                logger.debug(f"Found {len(movies)} directing credits")
            elif person_type == 'writer':
                movies = [m for m in movies if m.get('department') == 'Writing']
                logger.debug(f"Found {len(movies)} writing credits")
            elif person_type == 'actor':
                movies = [m for m in movies if m.get('department') == 'Acting']
                logger.debug(f"Found {len(movies)} acting credits")

            return jsonify({
                "credits": {
                    "cast" if person_type == 'actor' else 'crew': movies
                }
            })
        return jsonify({"error": "No movies found"}), 404
    except Exception as e:
        logger.error(f"Error getting person movies: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/person_details_with_external_ids/<person_id>')
def get_person_details_with_external_ids(person_id):
    details = tmdb_service.get_person_details_with_external_ids(person_id)
    if details:
        return jsonify(details)
    return jsonify({'error': 'Person not found'}), 404

@app.route('/api/movie_details/<movie_id>')
def movie_details(movie_id):
    """Get movie details using centralized TMDB service"""
    try:
        from utils.tmdb_service import tmdb_service

        movie_data = tmdb_service.get_movie_details(movie_id)
        if not movie_data:
            return jsonify({"error": "Movie not found"}), 404

        credits = tmdb_service.get_movie_credits(movie_id)
        if credits:
            movie_data['credits'] = credits

        title = movie_data['title']
        year = movie_data['release_date'][:4] if movie_data.get('release_date') else ''
        runtime = movie_data.get('runtime', 0)
        duration_hours = runtime // 60
        duration_minutes = runtime % 60
        genres = [genre['name'] for genre in movie_data.get('genres', [])]
        description = movie_data.get('overview', '')
        tmdb_rating = movie_data.get('vote_average', 0)

        content_rating = "Not rated"
        if 'release_dates' in movie_data:
            for release_date in movie_data['release_dates'].get('results', []):
                if release_date['iso_3166_1'] == 'US':
                    certifications = release_date.get('release_dates', [])
                    if certifications and 'certification' in certifications[0]:
                        content_rating = certifications[0]['certification']
                        break

        from utils.trakt_service import get_current_user_id
        user_id = get_current_user_id()
        trakt_rating = get_trakt_rating(movie_id, user_id)
        tmdb_url, trakt_url, imdb_url = tmdb_service.get_movie_links(movie_id)
        trailer_url = search_youtube_trailer(title, year)
        logo_url = tmdb_service.get_movie_logo_url(movie_id) 

        collection_info = {'is_in_collection': False, 'previous_movies': []} 
        try:
            current_service = session.get('current_service', get_available_service())
            collection_info = collection_service.check_collection_status(movie_id, current_service)
            logger.info(f"Fetched collection info for movie {movie_id} in API route: {collection_info.get('is_in_collection')}")
        except Exception as e:
            logger.error(f"Error getting collection info in API route for movie {movie_id}: {e}")

        formatted_data = {
            "title": title,
            "year": year,
            "duration_hours": duration_hours,
            "duration_minutes": duration_minutes,
            "contentRating": content_rating,
            "genres": genres,
            "tmdb_rating": tmdb_rating,
            "trakt_rating": trakt_rating,
            "description": description,
            "tmdb_url": tmdb_url,
            "trakt_url": trakt_url,
            "imdb_url": imdb_url,
            "trailer_url": trailer_url,
            "logo_url": logo_url, 
            "credits": credits,
            "collection_info": collection_info 
        }

        return jsonify(formatted_data)
    except Exception as e:
        logger.error(f"Error getting movie details: {e}", exc_info=True)
        return jsonify({"error": "Failed to fetch movie details"}), 500

@app.route('/api/movie_external_ids/<person_id>')
def get_person_external_ids(person_id):
    """Get external IDs for a person"""
    try:
        url = f"person/{person_id}/external_ids"
        external_ids = tmdb_service._make_request(url)
        if external_ids:
            return jsonify(external_ids)
        return jsonify({"error": "No external IDs found"}), 404
    except Exception as e:
        logger.error(f"Error getting external IDs: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/is_movie_in_jellyfin/<int:tmdb_id>')
def is_movie_in_jellyfin(tmdb_id):
    if not JELLYFIN_AVAILABLE:
        return jsonify({"available": False})

    try:
        cache_path = '/app/data/jellyfin_all_movies.json'
        if os.path.exists(cache_path):
            with open(cache_path, 'r') as f:
                all_jellyfin_movies = json.load(f)

            is_available = any(
                str(movie.get('tmdb_id')) == str(tmdb_id)
                for movie in all_jellyfin_movies
            )
            return jsonify({"available": is_available})
    except Exception as e:
        logger.error(f"Error checking Jellyfin availability: {str(e)}")
        return jsonify({"available": False})

@app.route('/is_movie_in_emby/<int:tmdb_id>')
def is_movie_in_emby(tmdb_id):
    if not EMBY_AVAILABLE:
        return jsonify({"available": False})

    try:
        cache_path = '/app/data/emby_all_movies.json'
        if os.path.exists(cache_path):
            with open(cache_path, 'r') as f:
                all_emby_movies = json.load(f)

            is_available = any(
                str(movie.get('tmdb_id')) == str(tmdb_id)
                for movie in all_emby_movies
            )
            return jsonify({"available": is_available})
    except Exception as e:
        logger.error(f"Error checking Emby availability: {str(e)}")
        return jsonify({"available": False})

from utils.version import VERSION

VERSION_FILE = '/app/data/version_info.json'

def get_version_info():
    if os.path.exists(VERSION_FILE):
        try:
            with open(VERSION_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {"last_version_seen": VERSION}

def save_version_info(info):
    os.makedirs(os.path.dirname(VERSION_FILE), exist_ok=True)
    with open(VERSION_FILE, 'w') as f:
        json.dump(info, f)

@app.route('/api/check_version')
def check_version():
    try:
        version_info = get_version_info()
        manual_check = request.args.get('manual', 'false') == 'true'
        response = requests.get(
            "https://api.github.com/repos/sahara101/Movie-Roulette/releases/latest",
            headers={'Accept': 'application/vnd.github.v3+json'}
        )
        if response.ok:
            release = response.json()
            latest_version = release['tag_name'].lstrip('v')
            current_parts = [int(x) for x in VERSION.split('.')]
            latest_parts = [int(x) for x in latest_version.split('.')]
            is_newer = latest_parts > current_parts
            show_popup = is_newer and latest_version != version_info["last_version_seen"]
            if manual_check or show_popup:
                version_info["last_version_seen"] = latest_version
                save_version_info(version_info)
            return jsonify({
                'update_available': is_newer,
                'current_version': VERSION,
                'latest_version': latest_version,
                'changelog': release['body'],
                'download_url': release['html_url'],
                'show_popup': show_popup or manual_check
            })
        else:
            return jsonify({'error': 'Failed to check version: GitHub API returned error'}), response.status_code
    except Exception as e:
        print(f"Error checking version: {e}")
        return jsonify({'error': 'Failed to check version'}), 500

@app.route('/api/dismiss_update')
def dismiss_update():
    try:
        with open('/app/data/last_update_check.json', 'w') as f:
            json.dump({
                'last_checked': datetime.now().isoformat(),
                'dismissed': True
            }, f)
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/search_movies')
def search_movies():
    """Search for movies in the current active service"""
    try:
        current_service = session.get('current_service', get_available_service())
        query = request.args.get('query', '').strip()

        if not query:
            return jsonify({"error": "No search query provided"}), 400

        logger.info(f"Searching movies in {current_service} with query: {query}")

        current_plex_service = getattr(g, 'plex_service', plex)

        results = [] 

        if current_service == 'plex' and PLEX_AVAILABLE and current_plex_service:
            try:
                hub_search_results = []
                unique_movie_ids = set()

                plex_instance = current_plex_service._get_user_plex_instance()
                user_switched = (plex_instance != current_plex_service.plex)
                logger.debug(f"Performing Plex Hub Search for query '{query}' using {'user (' + (current_plex_service.username or 'N/A') + ')' if user_switched else 'default'} perspective.")

                try:
                    hubs = plex_instance.search(query, mediatype='movie', limit=50) 
                    logger.debug(f"Hub search returned {len(hubs)} items directly.")
                    hub_search_results = [item for item in hubs if item.type == 'movie']

                except AttributeError:
                     logger.warning("plex_instance.search failed, trying plex_instance.library.hubSearch")
                     hubs = plex_instance.library.hubSearch(query, libtype='movie', limit=50)
                     logger.debug(f"Hub search returned {len(hubs)} hubs.")
                     for hub in hubs:
                         if hasattr(hub, 'items'):
                             for item in hub.items:
                                 if item.type == 'movie' and item.ratingKey not in unique_movie_ids:
                                     unique_movie_ids.add(item.ratingKey)
                                     hub_search_results.append(item)
                         elif hub.type == 'movie' and hub.ratingKey not in unique_movie_ids: 
                              unique_movie_ids.add(hub.ratingKey)
                              hub_search_results.append(hub)


                logger.info(f"Found {len(hub_search_results)} unique movies via Hub Search for query: {query}")

                results = [current_plex_service.get_movie_data(movie) for movie in hub_search_results]

            except Exception as search_error:
                logger.error(f"Plex Hub Search failed: {search_error}")

                results = [current_plex_service.get_movie_data(movie) for movie in all_plex_results]

            except Exception as search_error:
                logger.error(f"Plex library search failed: {search_error}")
                results = [] 
        elif current_service == 'jellyfin' and JELLYFIN_AVAILABLE:
            user_id, api_key = get_current_jellyfin_user_creds()
            results = jellyfin.search_movies(query, user_id=user_id, api_key=api_key)
        elif current_service == 'emby' and EMBY_AVAILABLE:
            results = emby.search_movies(query)
        else:
            logger.error(f"No available media service (current: {current_service})")
            return jsonify({"error": "No available media service"}), 400

        if results:
            logger.info(f"Found {len(results)} movies matching query: {query}")
            enriched_results = [enrich_movie_data(movie) for movie in results]
            return jsonify({
                "service": current_service,
                "results": enriched_results
            })

        logger.info(f"No movies found for query: {query}")
        return jsonify({"error": "No movies found"}), 404

    except Exception as e:
        logger.error(f"Error in search_movies: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/user_cache_admin')
@auth_manager.require_admin
def user_cache_admin():
    """Admin panel for managing user caches (admin only)"""
    return render_template('user_cache_admin.html')

@app.route('/api/clear_global_cache', methods=['POST'])
@auth_manager.require_admin
def clear_global_cache():
    """Clear global cache files (admin only)"""
    try:
        data = request.json
        files = data.get('files', [])

        deleted_files = []
        for file_path in files:
            if file_path.startswith('/app/data/') and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    deleted_files.append(file_path)
                except Exception as e:
                    logger.error(f"Error deleting file {file_path}: {e}")

        if deleted_files:
            logger.info(f"Deleted global cache files: {deleted_files}")

        if plex:
            plex.reload()

        return jsonify({
            "success": True,
            "message": f"Deleted {len(deleted_files)} global cache files",
            "deleted_files": deleted_files
        })
    except Exception as e:
        logger.error(f"Error clearing global cache: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/profile')
@auth_manager.require_auth
def get_user_profile():
    """Get the current user's profile information"""
    try:
        token = request.cookies.get('auth_token')
        if not token:
            return jsonify({"authenticated": False}), 401

        user_data = auth_manager.verify_auth(token)
        if not user_data:
            return jsonify({"authenticated": False}), 401

        username = user_data['username']
        is_admin = user_data['is_admin']

        user_cache_manager = app.config.get('USER_CACHE_MANAGER')
        cache_stats = None
        if user_cache_manager:
            cache_stats = user_cache_manager.get_user_stats(username)

        current_service = session.get('current_service', get_available_service())

        return jsonify({
            "authenticated": True,
            "username": username,
            "is_admin": is_admin,
            "cache_stats": cache_stats,
            "current_service": current_service
        })
    except Exception as e:
        logger.error(f"Error getting user profile: {e}")
        return jsonify({"error": str(e)}), 500

@socketio.on('connect', namespace='/poster')
def poster_connect():
    print('Client connected to poster namespace')

@socketio.on('disconnect', namespace='/poster')
def poster_disconnect():
    print('Client disconnected from poster namespace')

import atexit

def cleanup_services():
    if JELLYFIN_AVAILABLE and jellyfin:
        jellyfin.stop_cache_updater()
    if EMBY_AVAILABLE and emby:
        emby.stop_cache_updater()
    if PLEX_AVAILABLE and cache_manager:
        cache_manager.stop()

atexit.register(cleanup_services)

if __name__ == '__main__':
    logger.info("Application starting")
    logger.info("Application setup complete")
    socketio.run(app, host='0.0.0.0', port=4000, debug=True)
