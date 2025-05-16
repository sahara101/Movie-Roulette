import os
import json
import logging
import random
from threading import Thread
from flask import Blueprint, jsonify, request, session, current_app
from utils.tmdb_service import TMDBService
from utils.settings import settings as app_settings
from utils.auth.manager import auth_manager
from utils.auth.db import AuthDB

logger = logging.getLogger(__name__)

user_cache_bp = Blueprint('user_cache', __name__)

auth_db_instance = AuthDB()

def get_display_username_from_internal(internal_username, all_managed_users_details):
    """
    Determines the display username.
    For managed users, it looks up the display name using plex_user_id.
    For others, it strips known service prefixes.
    """
    if internal_username == 'global':
        return 'Global Cache'

    if internal_username.startswith('plex_managed_'):
        try:
            plex_user_id_from_key = internal_username[len('plex_managed_'):]
            for managed_username, details in all_managed_users_details.items():
                if str(details.get('plex_user_id')) == plex_user_id_from_key:
                    return managed_username
            logger.warning(f"Managed user display name not found for internal key {internal_username}. Falling back.")
            return internal_username
        except Exception as e:
            logger.error(f"Error looking up managed user display name for {internal_username}: {e}")
            return internal_username
        
    if internal_username.startswith('plex_'):
        return internal_username[len('plex_'):]
    elif internal_username.startswith('jellyfin_'):
        return internal_username[len('jellyfin_'):]
    elif internal_username.startswith('emby_'):
        return internal_username[len('emby_'):]
    return internal_username

@user_cache_bp.route('/api/user_cache/stats')
@auth_manager.require_admin
def get_user_cache_stats():
    """Get cache statistics for all users (admin only)"""
    try:
        user_cache_manager = current_app.config.get('USER_CACHE_MANAGER')
        if not user_cache_manager:
            return jsonify({"error": "User cache manager not initialized"}), 500

        cached_users_internal_keys = user_cache_manager.list_cached_users()
        
        auth_db_instance.load_db()
        all_managed_users_details = auth_db_instance.get_all_managed_users()

        user_stats_list = []
        for internal_key in cached_users_internal_keys:
            display_name = get_display_username_from_internal(internal_key, all_managed_users_details)
            
            user_stats = user_cache_manager.get_user_stats(internal_key)
            user_stats_list.append({
                'internal_username': internal_key,
                'display_username': display_name,
                'stats': user_stats
            })

        global_stats = {
            'username': 'global',
            'plex': {
                'unwatched_count': 0,
                'all_count': 0,
                'cache_exists': False
            },
            'jellyfin': {
                'all_count': 0,
                'cache_exists': False
            },
            'emby': {
                'all_count': 0,
                'cache_exists': False
            }
        }

        if os.path.exists('/app/data/plex_unwatched_movies.json'):
            global_stats['plex']['cache_exists'] = True
            try:
                with open('/app/data/plex_unwatched_movies.json', 'r') as f:
                    data = json.load(f)
                    global_stats['plex']['unwatched_count'] = len(data)
            except Exception as e:
                logger.error(f"Error reading global Plex unwatched cache: {e}")

        if os.path.exists('/app/data/plex_all_movies.json'):
            try:
                with open('/app/data/plex_all_movies.json', 'r') as f:
                    data = json.load(f)
                    global_stats['plex']['all_count'] = len(data)
            except Exception as e:
                logger.error(f"Error reading global Plex all movies cache: {e}")

        if os.path.exists('/app/data/jellyfin_all_movies.json'):
            global_stats['jellyfin']['cache_exists'] = True
            try:
                with open('/app/data/jellyfin_all_movies.json', 'r') as f:
                    data = json.load(f)
                    global_stats['jellyfin']['all_count'] = len(data)
            except Exception as e:
                logger.error(f"Error reading global Jellyfin cache: {e}")

        if os.path.exists('/app/data/emby_all_movies.json'):
            global_stats['emby']['cache_exists'] = True
            try:
                with open('/app/data/emby_all_movies.json', 'r') as f:
                    data = json.load(f)
                    global_stats['emby']['all_count'] = len(data)
            except Exception as e:
                logger.error(f"Error reading global Emby cache: {e}")
        
        global_display_name = get_display_username_from_internal('global', all_managed_users_details)
        global_stats_entry = {
             'internal_username': 'global',
             'display_username': global_display_name,
             'stats': global_stats
        }


        return jsonify({
            "users": user_stats_list,
            "global_cache": global_stats_entry,
            "total_users": len(cached_users_internal_keys)
        })
    except Exception as e:
        logger.error(f"Error getting user cache stats: {e}")
        return jsonify({"error": str(e)}), 500

@user_cache_bp.route('/api/clear_global_cache', methods=['POST'])
@auth_manager.require_admin
def clear_global_cache_route():
    """Clear global cache files (all or specific service)"""
    try:
        data = request.get_json()
        service_to_clear = data.get('service') 

        files_to_remove = []
        if service_to_clear == 'plex':
            files_to_remove.extend([
                '/app/data/plex_unwatched_movies.json',
                '/app/data/plex_all_movies.json'
            ])
            message_service = "Plex"
        elif service_to_clear == 'jellyfin':
            files_to_remove.append('/app/data/jellyfin_all_movies.json')
            message_service = "Jellyfin"
        elif service_to_clear == 'emby':
            files_to_remove.append('/app/data/emby_all_movies.json')
            message_service = "Emby"
        elif service_to_clear is None: 
            files_to_remove.extend([
                '/app/data/plex_unwatched_movies.json',
                '/app/data/plex_all_movies.json',
                '/app/data/jellyfin_all_movies.json',
                '/app/data/emby_all_movies.json'
            ])
            message_service = "All"
        else:
            return jsonify({"success": False, "message": f"Invalid service specified: {service_to_clear}"}), 400

        removed_count = 0
        errors = []
        for file_path in files_to_remove:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"Removed global cache file: {file_path}")
                    removed_count += 1
            except Exception as e:
                logger.error(f"Error removing global cache file {file_path}: {e}")
                errors.append(str(e))

        if errors:
            return jsonify({
                "success": False, 
                "message": f"Errors occurred while clearing {message_service} global cache: {'; '.join(errors)}"
            }), 500
        elif removed_count == 0 and files_to_remove:
             return jsonify({
                "success": True, 
                "message": f"{message_service} global cache files not found."
            })
        else:
            return jsonify({
                "success": True,
                "message": f"{message_service} global cache cleared successfully."
            })

    except Exception as e:
        logger.error(f"Error in clear_global_cache route: {e}")
        return jsonify({"error": str(e)}), 500

@user_cache_bp.route('/api/refresh_global_cache', methods=['POST'])
@auth_manager.require_admin
def refresh_global_cache_route():
    """Trigger a refresh for a specific global service cache"""
    try:
        data = request.get_json()
        service_to_refresh = data.get('service')

        if not service_to_refresh:
            return jsonify({"success": False, "message": "Service name not provided"}), 400

        plex_service = current_app.config.get('PLEX_SERVICE')
        jellyfin_service = current_app.config.get('JELLYFIN_SERVICE')
        emby_service = current_app.config.get('EMBY_SERVICE')
        global_cache_manager = current_app.config.get('GLOBAL_CACHE_MANAGER')

        if service_to_refresh == 'plex':
            if global_cache_manager and global_cache_manager.plex_service:
                logger.info(f"Triggering force_refresh on GLOBAL_CACHE_MANAGER for Plex.")
                Thread(target=global_cache_manager.force_refresh).start()
                return jsonify({"success": True, "message": "Global Plex cache refresh started."})
            else:
                logger.error("Global Cache Manager or its Plex service not found for Plex refresh.")
                return jsonify({"success": False, "message": "Global Plex cache setup issue."}), 500
        elif service_to_refresh == 'jellyfin':
            if jellyfin_service and hasattr(jellyfin_service, 'initialize_cache'):
                logger.info(f"Triggering initialize_cache on JELLYFIN_SERVICE.")
                Thread(target=jellyfin_service.initialize_cache).start()
                return jsonify({"success": True, "message": "Global Jellyfin cache refresh started."})
            else:
                logger.error("Jellyfin service not available or no initialize_cache method.")
                return jsonify({"success": False, "message": "Jellyfin service refresh unavailable."}), 500
        elif service_to_refresh == 'emby':
            if emby_service and hasattr(emby_service, 'initialize_cache'):
                logger.info(f"Triggering initialize_cache on EMBY_SERVICE.")
                Thread(target=emby_service.initialize_cache).start()
                return jsonify({"success": True, "message": "Global Emby cache refresh started."})
            else:
                logger.error("Emby service not available or no initialize_cache method.")
                return jsonify({"success": False, "message": "Emby service refresh unavailable."}), 500
        else:
            return jsonify({"success": False, "message": f"Invalid service specified for global refresh: {service_to_refresh}"}), 400

    except Exception as e:
        logger.error(f"Error in refresh_global_cache route: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@user_cache_bp.route('/api/user_cache/clear/<username>', methods=['POST'])
@auth_manager.require_auth
def clear_user_cache(username):
    """Clear a user's cache files (self or admin only)"""
    try:
        current_user = session.get('username')
        is_admin = session.get('is_admin', False) 

        if not is_admin and current_user != username:
            return jsonify({
                "success": False,
                "message": "Permission denied"
            }), 403

        data = request.get_json() or {}
        service = data.get('service')

        user_cache_manager = current_app.config.get('USER_CACHE_MANAGER')
        if not user_cache_manager:
            return jsonify({"error": "User cache manager not initialized"}), 500

        success = user_cache_manager.clear_user_cache(username, service)

        if success:
            return jsonify({
                "success": True,
                "message": f"Cache {'for ' + service if service else ''} cleared for user {username}"
            })
        else:
            return jsonify({
                "success": False,
                "message": f"Failed to clear cache for user {username}"
            }), 400
    except Exception as e:
        logger.error(f"Error clearing user cache: {e}")
        return jsonify({"error": str(e)}), 500

@user_cache_bp.route('/api/user_cache/build/<username>', methods=['POST'])
@auth_manager.require_admin
def build_user_cache(username):
    """Trigger a cache build for a specific user (admin only)"""
    try:
        users = auth_manager.get_users()
        if username not in users:
            return jsonify({
                "success": False,
                "message": f"User {username} not found"
            }), 404

        get_user_cache_manager = current_app.config.get('get_user_cache_manager')
        user_cache_managers = current_app.config.get('user_cache_managers', {})
        
        if not get_user_cache_manager:
            return jsonify({
                "success": False,
                "message": "Cache manager function not available"
            }), 500

        if username not in user_cache_managers:
            cm = get_user_cache_manager(username)
        else:
            cm = user_cache_managers[username]

        Thread(target=cm.start_cache_build).start()

        return jsonify({
            "success": True,
            "message": f"Cache build started for user {username}"
        })
    except Exception as e:
        logger.error(f"Error building user cache: {e}")
        return jsonify({"error": str(e)}), 500

@user_cache_bp.route('/api/user_cache/current_user')
@auth_manager.require_auth
def get_current_user_cache_stats():
    """Get cache statistics for the current logged-in user"""
    try:
        username = session.get('username')
        if not username:
            return jsonify({
                "success": False,
                "message": "No user logged in"
            }), 401

        user_cache_manager = current_app.config.get('USER_CACHE_MANAGER')
        if not user_cache_manager:
            return jsonify({"error": "User cache manager not initialized"}), 500

        stats = user_cache_manager.get_user_stats(username)

        user_cache_managers = current_app.config.get('user_cache_managers', {})
        has_user_cache = username in user_cache_managers
        
        return jsonify({
            "username": username,
            "stats": stats,
            "has_cache_manager": has_user_cache,
            "current_service": session.get('current_service', 'plex')
        })
    except Exception as e:
        logger.error(f"Error getting current user cache stats: {e}")
        return jsonify({"error": str(e)}), 500

@user_cache_bp.route('/api/user_cache/refresh_current')
@auth_manager.require_auth
def refresh_current_user_cache():
    """Refresh the cache for the current logged-in user"""
    try:
        username = session.get('username')
        if not username:
            return jsonify({
                "success": False,
                "message": "No user logged in"
            }), 401

        get_user_cache_manager = current_app.config.get('get_user_cache_manager')
        user_cache_managers = current_app.config.get('user_cache_managers', {})
        
        if not get_user_cache_manager:
            return jsonify({
                "success": False,
                "message": "Cache manager function not available"
            }), 500

        if username not in user_cache_managers:
            cm = get_user_cache_manager(username)
        else:
            cm = user_cache_managers[username]

        Thread(target=cm.force_refresh).start()

        return jsonify({
            "success": True,
            "message": f"Cache refresh started for user {username}"
        })
    except Exception as e:
        logger.error(f"Error refreshing current user cache: {e}")
        return jsonify({"error": str(e)}), 500

@user_cache_bp.route('/api/random_backdrops', methods=['GET'])
def get_random_backdrops():
    """Get a list of random movie backdrop URLs for the login page."""
    try:
        tmdb_service = current_app.config.get('TMDB_SERVICE')
        if not tmdb_service:
            logger.info("TMDBService not in app.config, initializing for random_backdrops.")
            tmdb_api_key = app_settings.get('tmdb', {}).get('api_key')
            if not tmdb_api_key and not app_settings.get('tmdb', {}).get('enabled'):
                tmdb_api_key = os.getenv('TMDB_API_KEY_DEFAULT', TMDBService.DEFAULT_API_KEY)
            
            if not tmdb_api_key:
                 logger.error("Critical: TMDB API key is somehow still not available.")
                 return jsonify({"error": "TMDB API key configuration is missing"}), 500

            tmdb_service = TMDBService()

        cache_file_path = None
        service_movies = []

        movies_data_for_processing = []
        
        plex_enabled = app_settings.get('plex', {}).get('enabled')
        jellyfin_enabled = app_settings.get('jellyfin', {}).get('enabled')
        emby_enabled = app_settings.get('emby', {}).get('enabled')

        used_plex_all_movies_cache = False
        if plex_enabled:
            plex_all_movies_file_path = '/app/data/plex_all_movies.json'
            if os.path.exists(plex_all_movies_file_path) and os.path.getsize(plex_all_movies_file_path) > 0:
                logger.info("Login backdrops: Attempting to use Plex all_movies cache.")
                try:
                    with open(plex_all_movies_file_path, 'r') as f:
                        plex_all_movies_data = json.load(f)
                        if isinstance(plex_all_movies_data, list):
                            for movie_obj in plex_all_movies_data:
                                tmdb_id = movie_obj.get('tmdb_id')
                                if tmdb_id:
                                    movies_data_for_processing.append({'tmdb_id': str(tmdb_id), 'title': movie_obj.get('title', 'N/A')})
                            if movies_data_for_processing:
                                used_plex_all_movies_cache = True
                                logger.info(f"Login backdrops: Successfully processed {len(movies_data_for_processing)} items from Plex all_movies cache.")
                        else:
                            logger.warning("Plex all_movies cache is not a list, falling back.")
                except Exception as e:
                    logger.error(f"Error loading or processing Plex all_movies cache: {e}", exc_info=True)
            
            if not used_plex_all_movies_cache and os.path.exists('/app/data/plex_metadata_cache.json'):
                logger.info("Login backdrops: Using Plex metadata cache (fallback or all_movies not available/suitable).")
                try:
                    with open('/app/data/plex_metadata_cache.json', 'r') as f:
                        plex_metadata = json.load(f)
                        for movie_obj in plex_metadata.values():
                            tmdb_id_from_guid = None
                            guids = movie_obj.get('Guid', [])
                            if isinstance(guids, list):
                                for guid_entry in guids:
                                    if isinstance(guid_entry, dict) and isinstance(guid_entry.get('id'), str) and guid_entry.get('id','').startswith('tmdb://'):
                                        tmdb_id_from_guid = guid_entry['id'].replace('tmdb://', '')
                                        break
                            if tmdb_id_from_guid:
                                movies_data_for_processing.append({'tmdb_id': tmdb_id_from_guid, 'title': movie_obj.get('title', 'N/A')})
                except Exception as e:
                    logger.error(f"Error loading Plex metadata cache: {e}", exc_info=True)

        if not movies_data_for_processing and jellyfin_enabled and os.path.exists('/app/data/jellyfin_all_movies.json'):
            logger.info("Login backdrops: Using Jellyfin all_movies cache.")
            try:
                with open('/app/data/jellyfin_all_movies.json', 'r') as f:
                    jellyfin_movies = json.load(f)
                    for movie_obj in jellyfin_movies:
                        if movie_obj.get('tmdb_id'):
                            movies_data_for_processing.append({'tmdb_id': str(movie_obj['tmdb_id']), 'title': movie_obj.get('title', 'N/A')})
            except Exception as e:
                logger.error(f"Error loading Jellyfin all_movies cache: {e}", exc_info=True)

        elif emby_enabled and os.path.exists('/app/data/emby_all_movies.json'):
            logger.info("Login backdrops: Using Emby all_movies cache.")
            try:
                with open('/app/data/emby_all_movies.json', 'r') as f:
                    emby_movies = json.load(f) 
                    for movie_obj in emby_movies:
                        if movie_obj.get('tmdb_id'):
                            movies_data_for_processing.append({'tmdb_id': str(movie_obj['tmdb_id']), 'title': movie_obj.get('title', 'N/A')})
            except Exception as e:
                logger.error(f"Error loading Emby all_movies cache: {e}", exc_info=True)
        
        else:
            logger.warning("No suitable media service cache found for login backdrops (Plex all_movies, Plex metadata, or Jellyfin/Emby all_movies).")

        if not movies_data_for_processing:
            logger.warning("No movie data with TMDB IDs found in any selected cache. Cannot provide backdrops.")
            return jsonify([])

        random.shuffle(movies_data_for_processing)

        backdrop_urls = []
        processed_tmdb_ids = set()

        for item_data in movies_data_for_processing:
            if len(backdrop_urls) >= 20:
                break

            tmdb_id = item_data.get('tmdb_id')
            movie_title_from_cache = item_data.get('title', 'N/A')

            if tmdb_id and tmdb_id not in processed_tmdb_ids:
                processed_tmdb_ids.add(tmdb_id)
                logger.debug(f"Attempting to fetch TMDB details for ID: {tmdb_id} (from cached movie: {movie_title_from_cache})")
                try:
                    movie_details_from_tmdb = tmdb_service.get_movie_details(tmdb_id)
                    
                    if movie_details_from_tmdb:
                        tmdb_movie_title = movie_details_from_tmdb.get('title', 'N/A')
                        tmdb_backdrop_path_val = movie_details_from_tmdb.get('backdrop_path')
                        logger.debug(f"TMDB details for {tmdb_id} ('{tmdb_movie_title}'): backdrop_path is '{tmdb_backdrop_path_val}'")

                        if tmdb_backdrop_path_val:
                            backdrop_url = tmdb_service.get_image_url(tmdb_backdrop_path_val, size='original')
                            if backdrop_url:
                                logger.debug(f"Successfully got backdrop URL for TMDB ID {tmdb_id}: {backdrop_url}")
                                backdrop_urls.append(backdrop_url)
                            else:
                                logger.warning(f"get_image_url returned None for TMDB ID {tmdb_id}, path: {tmdb_backdrop_path_val}")
                    else:
                        logger.warning(f"Failed to fetch TMDB details for tmdb_id: {tmdb_id} (get_movie_details returned None).")
                except Exception as e_tmdb:
                    logger.error(f"Exception while fetching TMDB details or constructing image URL for tmdb_id {tmdb_id}: {e_tmdb}", exc_info=True)
            
            elif not tmdb_id:
                 logger.debug(f"Skipping item due to missing TMDB ID: {movie_title_from_cache}")


        if not backdrop_urls:
            logger.warning("No backdrop URLs constructed from service cache for login page. Final count: 0.")
            
        return jsonify(backdrop_urls)

    except Exception as e:
        logger.error(f"Error getting random backdrops from service cache: {e}", exc_info=True)
        return jsonify({"error": "Failed to fetch random backdrops"}), 500
