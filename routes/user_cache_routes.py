import os
import json
import logging
from threading import Thread
from flask import Blueprint, jsonify, request, session, current_app

from utils.auth.manager import auth_manager

logger = logging.getLogger(__name__)

user_cache_bp = Blueprint('user_cache', __name__)

def get_display_username(internal_username):
    """Removes known service prefixes from the internal username."""
    if internal_username == 'global': 
        return 'Global Cache'
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

        cached_users = user_cache_manager.list_cached_users()

        user_stats_list = []
        for username in cached_users:
            display_name = get_display_username(username)
            user_stats = user_cache_manager.get_user_stats(username)
            user_stats_list.append({
                'internal_username': username,
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

        global_display_name = get_display_username('global')
        global_stats_entry = {
             'internal_username': 'global',
             'display_username': global_display_name,
             'stats': global_stats
        }


        return jsonify({
            "users": user_stats_list,
            "global_cache": global_stats_entry,
            "total_users": len(cached_users)
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

        service_instance = None
        if service_to_refresh == 'plex' and plex_service:
            service_instance = plex_service
        elif service_to_refresh == 'jellyfin' and jellyfin_service:
            service_instance = jellyfin_service
        elif service_to_refresh == 'emby' and emby_service:
            service_instance = emby_service
        else:
            return jsonify({"success": False, "message": f"Invalid or unconfigured service: {service_to_refresh}"}), 400

        if hasattr(service_instance, 'initialize_cache'):
            Thread(target=service_instance.initialize_cache).start()
            logger.info(f"Started background refresh for global {service_to_refresh} cache.")
            return jsonify({
                "success": True,
                "message": f"Global {service_to_refresh} cache refresh started."
            })
        else:
            logger.error(f"Service '{service_to_refresh}' does not have an 'initialize_cache' method.")
            return jsonify({"success": False, "message": f"Refresh function not available for service: {service_to_refresh}"}), 500

    except Exception as e:
        logger.error(f"Error in refresh_global_cache route: {e}")
        return jsonify({"error": str(e)}), 500


@user_cache_bp.route('/api/user_cache/clear/<username>')
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
            
        service = request.args.get('service')

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

@user_cache_bp.route('/api/user_cache/build/<username>')
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
