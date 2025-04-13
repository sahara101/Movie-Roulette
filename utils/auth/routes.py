from flask import Blueprint, request, jsonify, render_template, redirect, url_for, make_response, session, current_app
import logging
from datetime import datetime, timedelta
from .manager import auth_manager # Import only auth_manager
from utils.settings import settings # Import the global settings object
from utils.emby_service import authenticate_with_emby_connect # Import Emby Connect function
import requests # Add for select_server route
import uuid     # Add for select_server route
import os       # Add missing import for os.getenv

logger = logging.getLogger(__name__)

# Define the blueprint
auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET'])
def login():
    """Render the login page"""
    # Check if auth is enabled
    if not auth_manager.auth_enabled:
        return redirect(url_for('index'))

    # Check if this is first run (no users configured)
    if auth_manager.is_first_run():
        return redirect(url_for('auth.setup'))

    # Check if already authenticated
    token = request.cookies.get('auth_token')
    if token and auth_manager.verify_auth(token):
        return redirect(url_for('index'))

    # Get the next URL from query parameters
    next_url = request.args.get('next', url_for('index'))

    # Check if there's an error message
    error = request.args.get('error', '')

    # Get service status from settings
    from utils.settings import settings
    enabled_services = {
        'plex': settings.get('plex', {}).get('enabled', False),
        'jellyfin': settings.get('jellyfin', {}).get('enabled', False),
        'emby': settings.get('emby', {}).get('enabled', False)
    }
    
    # Check if any service is enabled
    any_service_enabled = any(enabled_services.values())

    return render_template('login.html', 
                          next=next_url, 
                          error=error, 
                          services=enabled_services,
                          any_service_enabled=any_service_enabled)

@auth_bp.route('/login', methods=['POST'])
def login_post():
    """Handle login form submission"""
    username = request.form.get('username')
    password = request.form.get('password')
    # remember = request.form.get('remember') == 'on' # Removed as 'Remember Me' is gone
    next_url = request.form.get('next', url_for('index'))
    if '://' in next_url:
        from urllib.parse import urlparse
        parsed = urlparse(next_url)
        next_url = parsed.path

    if not username or not password:
        return redirect(url_for('auth.login', error='Username and password are required', next=next_url))

    success, result = auth_manager.login(username, password) # Removed remember argument

    if not success:
        return redirect(url_for('auth.login', error=result, next=next_url))

    # Set the auth token in a cookie
    response = redirect(next_url)
    
    # Get session lifetime from settings (convert to int, default to 86400 if invalid)
    try:
        session_lifetime_seconds = int(settings.get('auth', {}).get('session_lifetime', 86400))
    except (ValueError, TypeError):
        session_lifetime_seconds = 86400 # Fallback to 1 day
        logger.warning(f"Invalid session_lifetime setting found, using default {session_lifetime_seconds} seconds for cookie.")

    # Always set a persistent cookie based on the session_lifetime setting
    expires = datetime.now() + timedelta(seconds=session_lifetime_seconds)
    max_age = session_lifetime_seconds
    response.set_cookie(
        'auth_token',
        result,
        expires=expires,
        max_age=max_age,
        httponly=True,
        secure=request.is_secure,
        samesite='Lax'
    )
    # The 'remember' logic was removed previously. Now always setting persistent cookie.

    return response

@auth_bp.route('/logout')
def logout():
    """Log the user out"""
    token = request.cookies.get('auth_token')

    if token:
        auth_manager.logout(token)

    # Clear the auth cookie
    response = redirect(url_for('auth.login'))
    response.delete_cookie('auth_token')

    # Clear Flask session data
    session.pop('username', None)
    session.pop('is_admin', None)

    return response

@auth_bp.route('/setup', methods=['GET'])
def setup():
    """Render the first-time setup page"""
    # Check if auth is enabled
    if not auth_manager.auth_enabled:
        return redirect(url_for('index'))

    # Check if this is first run (no users configured)
    if not auth_manager.is_first_run() and not auth_manager.needs_admin():
        return redirect(url_for('index'))

    return render_template('setup.html')

@auth_bp.route('/setup', methods=['POST'])
def setup_post():
    """Handle setup form submission"""
    # Get username from form input
    username = request.form.get('username')
    password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')

    if not password:
        return render_template('setup.html', error='Password is required')

    if password != confirm_password:
        return render_template('setup.html', error='Passwords do not match')

    # Create admin user
    success, message = auth_manager.create_user(username, password, is_admin=True)

    if not success:
        return render_template('setup.html', error=message)

    # Login the user
    success, token = auth_manager.login(username, password)

    if not success:
        return redirect(url_for('auth.login', error='Account created. Please log in.'))

    # Set the auth token in a cookie
    response = redirect(url_for('index'))
    expires = datetime.now() + timedelta(days=1)
    response.set_cookie('auth_token', token, expires=expires, httponly=True, secure=request.is_secure, samesite='Lax')

    return response

@auth_bp.route('/api/auth/check')
def auth_check():
    """Check if the user is authenticated"""
    token = request.cookies.get('auth_token')
    user_data = auth_manager.verify_auth(token)

    if user_data:
        # Get the user from the database to check if they're a Plex user
        internal_username = user_data['username']
        user = auth_manager.db.users.get(internal_username, {})
        
        # Determine original username by stripping prefix if present
        display_username = internal_username
        if internal_username.startswith('plex_'):
            display_username = internal_username[len('plex_'):]
        elif internal_username.startswith('emby_'):
            display_username = internal_username[len('emby_'):]
        elif internal_username.startswith('jellyfin_'):
            display_username = internal_username[len('jellyfin_'):]

        # Check if it's a plex user based on internal name or service type
        is_plex_user = user.get('service_type') == 'plex'

        return jsonify({
            'authenticated': True,
            'username': display_username, # Return the original username
            'is_admin': user_data['is_admin'],
            'is_plex_user': is_plex_user,
            'service_type': user.get('service_type', 'local') # Also return service type
        })

    return jsonify({
        'authenticated': False
    })

@auth_bp.route('/api/auth/users', methods=['GET'])
@auth_manager.require_admin
def get_users():
    """Get a list of all users (admin only), formatted for display with roles"""
    internal_users = auth_manager.get_users()
    user_list = []

    # No longer need to get owner details from settings here

    for internal_username, data in internal_users.items():
        display_username = internal_username
        service_type = data.get('service_type', 'local')
        is_admin_flag = data.get('is_admin', False)
        display_role = "User" # Default role

        # Determine display username
        if service_type == 'plex':
            display_username = internal_username[len('plex_'):]
        elif service_type == 'emby':
            display_username = internal_username[len('emby_'):]
        elif service_type == 'jellyfin':
            display_username = internal_username[len('jellyfin_'):]

        # Determine display role
        # Check for stored owner flags from the user data
        is_service_owner = False
        if service_type == 'plex' and data.get('is_plex_owner', False):
             is_service_owner = True
        elif service_type == 'jellyfin' and data.get('is_jellyfin_owner', False):
             is_service_owner = True
        elif service_type == 'emby' and data.get('is_emby_owner', False):
             is_service_owner = True

        # Assign display_role based on flags
        # Assign display_role based on the is_admin flag directly
        if is_admin_flag:
            display_role = "Admin"
        elif is_service_owner:
            display_role = "Owner"
        else:
            # All others are regular users
            display_role = "User"

        user_entry = {
            'internal_username': internal_username,
            'display_username': display_username,
            'display_role': display_role, # Add the new display role
            **data # Spread the rest of the user data (includes original is_admin flag)
        }
        user_list.append(user_entry)

    return jsonify(user_list)

@auth_bp.route('/api/auth/users', methods=['POST'])
@auth_manager.require_admin
def create_user():
    """Create a new user (admin only) - now disabled except for service accounts"""
    # This endpoint is intentionally disabled for creating new local accounts
    # Only the default admin account and service logins are allowed
    return jsonify({
        'success': False,
        'message': 'Creating new local accounts is disabled. Only the admin account is allowed.'
    }), 400

@auth_bp.route('/api/auth/users/<username>', methods=['DELETE'])
@auth_manager.require_admin
def delete_user(username):
    """Delete a user (admin only)"""
    # Check if this is the last admin user
    users = auth_manager.get_users()
    admin_count = sum(1 for user, data in users.items() if data.get('is_admin', False))

    if admin_count == 1 and users.get(username, {}).get('is_admin', False):
        return jsonify({
            'success': False,
            'message': 'Cannot delete the last admin user'
        }), 400

    success, message = auth_manager.delete_user(username)

    return jsonify({
        'success': success,
        'message': message
    }), 200 if success else 400

@auth_bp.route('/api/auth/change-password', methods=['POST'])
@auth_manager.require_auth
def change_password():
    """Change current user's password"""
    data = request.json
    current_password = data.get('current_password')
    new_password = data.get('new_password')

    if not current_password or not new_password:
        return jsonify({
            'success': False,
            'message': 'Current and new password are required'
        }), 400

    # Get the current user
    token = request.cookies.get('auth_token')
    user_data = auth_manager.verify_auth(token)

    if not user_data:
        return jsonify({
            'success': False,
            'message': 'Not authenticated'
        }), 401

    # Check if the user is a local user (only local users can change password here)
    if user_data.get('service_type') != 'local':
        return jsonify({
            'success': False,
            'message': 'Password cannot be changed for service-based accounts (e.g., Plex, Jellyfin). Please manage your password through the respective service.'
        }), 403 # Forbidden

    # Verify current password (only for local users)
    success, _ = auth_manager.db.verify_user(user_data['username'], current_password)

    if not success:
        return jsonify({
            'success': False,
            'message': 'Current password is incorrect'
        }), 400

    # Update password
    success, message = auth_manager.update_password(user_data['username'], new_password)

    return jsonify({
        'success': success,
        'message': message
    }), 200 if success else 400

@auth_bp.route('/api/auth/admin/change-password/<username>', methods=['POST'])
@auth_manager.require_admin
def admin_change_password(username):
    """Change a user's password (admin only)"""
    data = request.json
    new_password = data.get('password')

    if not new_password:
        return jsonify({
            'success': False,
            'message': 'New password is required'
        }), 400

    # Update password
    success, message = auth_manager.update_password(username, new_password)

    return jsonify({
        'success': success,
        'message': message
    }), 200 if success else 400

# Plex authentication routes
@auth_bp.route('/plex/auth', methods=['GET'])
def plex_auth():
    """Initiate Plex authentication"""
    success, result = auth_manager.generate_plex_auth_url()

    if success:
        return jsonify(result)
    else:
        return jsonify({'error': result}), 400

@auth_bp.route('/plex/auth_success')
def plex_auth_success():
    """Simple success page for Plex popup"""
    return render_template('plex_auth_success.html')

@auth_bp.route('/plex/callback')
def plex_callback():
    """Handle Plex authentication callback with token fallback"""
    # Get PIN ID and token fallback if available
    pin_id = request.args.get('pinID')
    token = request.args.get('token')
    next_url = request.args.get('next', url_for('index'))
    
    if not pin_id:
        current_app.logger.error("Plex callback missing PIN ID")
        return redirect(url_for('auth.login', error='Authentication failed: Missing PIN ID'))
    
    try:
        # Try to validate the PIN
        success, result = auth_manager.validate_plex_pin(pin_id)
        
        if success:
            # PIN validation succeeded, set cookie and redirect
            response = redirect(next_url)
            expires = datetime.now() + timedelta(days=30)
            response.set_cookie(
                'auth_token', 
                result,
                expires=expires,
                httponly=True, 
                secure=request.is_secure, 
                samesite='Lax',
                max_age=30 * 86400  # 30 days
            )
            current_app.logger.info(f"Plex authentication successful via PIN validation for {pin_id}")
            return response
        elif token:
            # PIN validation failed but we have a token from the URL
            # Verify the token is valid
            user_data = auth_manager.verify_auth(token)
            
            if user_data:
                # Token is valid, set cookie and redirect
                current_app.logger.info(f"Plex authentication successful via token fallback for {user_data['username']}")
                response = redirect(next_url)
                expires = datetime.now() + timedelta(days=30)
                response.set_cookie(
                    'auth_token', 
                    token,
                    expires=expires,
                    httponly=True, 
                    secure=request.is_secure, 
                    samesite='Lax',
                    max_age=30 * 86400  # 30 days
                )
                return response
            else:
                # Token is invalid
                current_app.logger.error("Plex callback token verification failed")
                return redirect(url_for('auth.login', error='Authentication failed: Invalid token'))
        else:
            # PIN validation failed and no token
            current_app.logger.error(f"Plex callback PIN validation failed: {result}")
            return redirect(url_for('auth.login', error=f'Authentication failed: {result}'))
    except Exception as e:
        current_app.logger.error(f"Error in Plex callback: {e}")
        return redirect(url_for('auth.login', error='An error occurred during authentication'))

@auth_bp.route('/api/auth/plex/check_pin/<int:pin_id>')
def check_plex_pin(pin_id):
    """Check if a Plex PIN has been validated"""
    success, result = auth_manager.validate_plex_pin(pin_id)

    if success:
        # Include the token in the response for the fallback mechanism
        return jsonify({'status': 'success', 'token': result})
    else:
        return jsonify({'status': 'waiting', 'message': result})

# Jellyfin Authentication Route
@auth_bp.route('/api/auth/jellyfin/login', methods=['POST'])
def jellyfin_login():
    """Handle Jellyfin login attempt"""
    data = request.json
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'success': False, 'message': 'Username and password are required'}), 400

    try:
        success, result = auth_manager.login_with_jellyfin(username, password)

        if success:
            # Set the auth token in a cookie
            response = make_response(jsonify({'success': True, 'message': 'Login successful'}))
            expires = datetime.now() + timedelta(days=30) # Remember for 30 days
            response.set_cookie(
                'auth_token',
                result, # result is the session token
                expires=expires,
                httponly=True,
                secure=request.is_secure,
                samesite='Lax',
                max_age=30 * 86400 # 30 days
            )
            current_app.logger.info(f"Jellyfin authentication successful for user: {username}")
            return response
        else:
            current_app.logger.warning(f"Jellyfin authentication failed for user {username}: {result}")
            return jsonify({'success': False, 'message': result}), 401 # Unauthorized

    except Exception as e:
        current_app.logger.error(f"Error during Jellyfin login: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred during authentication'}), 500

# --- Emby Connect Authentication Route (Restored) ---
@auth_bp.route('/api/emby/connect/auth', methods=['POST'])
@auth_manager.require_auth # Should require user to be logged into Movie Roulette first
def emby_connect_auth():
    """Authenticate with Emby Connect and return list of servers."""
    data = request.json
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'status': 'error', 'message': 'Emby Connect username and password are required'}), 400

    try:
        success, result = authenticate_with_emby_connect(username, password)

        if success:
            # result contains {'servers': [...], 'connect_user_id': ...}
            logger.info(f"Emby Connect auth successful for {username}, found {len(result['servers'])} servers.")
            return jsonify({
                'status': 'servers_available',
                **result # Spread servers and connect_user_id
            })
        else:
            # result contains error message
            logger.warning(f"Emby Connect auth failed for {username}: {result}")
            return jsonify({'status': 'error', 'message': result}), 401 # Unauthorized or other error

    except Exception as e:
        logger.error(f"Unexpected error during Emby Connect auth route: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': f'An unexpected error occurred: {e}'}), 500
# --- Restored Original Emby Connect Server Selection Logic ---
@auth_bp.route('/api/emby/connect/select_server', methods=['POST'])
@auth_manager.require_auth # Keep auth check
def emby_select_server():
    """Handles the selection of a server after Emby Connect auth using the original /Connect/Exchange logic."""
    try:
        data = request.json
        server_info = data.get('server')
        connect_user_id = data.get('connect_user_id')

        if not all([server_info, connect_user_id]):
            return jsonify({"error": "Server info and connect user ID required"}), 400

        # Use the URL selected by the user (local or remote)
        server_url = server_info.get('url')
        # Use the AccessKey provided by Emby Connect for the selected server
        connect_access_key = server_info.get('access_key')

        if not server_url or not connect_access_key:
            return jsonify({"error": "Missing server URL or Connect Access Key"}), 400

        # Exchange Connect access key for server token using /Connect/Exchange
        exchange_headers = {
            'X-Emby-Token': connect_access_key, # Use the key from Emby Connect
            'X-Emby-Authorization': ('MediaBrowser Client="Movie Roulette",' # Standard auth header
                                   'Device="Movie Roulette",'
                                   'DeviceId="MovieRoulette",' # Consistent DeviceId
                                   'Version="1.0.0"')
        }
        exchange_url = f"{server_url.rstrip('/')}/Connect/Exchange?format=json&ConnectUserId={connect_user_id}"

        logger.info(f"Attempting Emby Connect token exchange for Connect User {connect_user_id} on server {server_url}")
        exchange_response = requests.get(exchange_url, headers=exchange_headers, timeout=15)
        exchange_response.raise_for_status() # Raise exceptions for bad status codes (4xx, 5xx)
        exchange_data = exchange_response.json()

        final_api_key = exchange_data.get('AccessToken')
        local_user_id = exchange_data.get('LocalUserId')

        if not final_api_key or not local_user_id:
             logger.error(f"Emby Connect exchange failed: Missing AccessToken or LocalUserId in response. Data: {exchange_data}")
             return jsonify({"error": "Token exchange with Emby server failed to return necessary credentials."}), 500

        logger.info(f"Emby Connect exchange successful. Local User ID: {local_user_id}, New API Key: {final_api_key[:5]}...")

        # Return the final credentials obtained from the exchange
        return jsonify({
            "status": "success",
            "api_key": final_api_key, # The persistent API key for the server
            "user_id": local_user_id, # The local user ID on the server
            "server_url": server_url
        })

    except requests.exceptions.Timeout:
        logger.error(f"Timeout during Emby Connect token exchange with server {server_url}.")
        return jsonify({'error': f'Connection timed out when contacting the selected server ({server_url}) for token exchange.'}), 408
    except requests.exceptions.RequestException as e:
        logger.error(f"Error during Emby Connect token exchange with server {server_url}: {e}")
        status_code = 500
        error_message = f"Could not connect or communicate with the selected server ({server_url}) for token exchange."
        if isinstance(e, requests.exceptions.HTTPError):
             if e.response.status_code == 401:
                  error_message = "Authentication failed: The key from Emby Connect was rejected by the selected server during token exchange."
                  status_code = 401
             elif e.response.status_code == 404:
                  error_message = "API endpoint not found on the selected server (/Connect/Exchange). Check server version or URL."
                  status_code = 404
             else:
                  error_message = f"Selected server returned an error during token exchange: {e}"
                  status_code = e.response.status_code if e.response.status_code >= 400 else 500
        elif "Name or service not known" in str(e) or "Connection refused" in str(e):
             error_message = f"Could not resolve or connect to the selected server at {server_url}."
             status_code = 400
        return jsonify({'error': error_message}), status_code
    except Exception as e:
        logger.error(f"Unexpected error during Emby Connect server selection/exchange: {e}", exc_info=True)
        return jsonify({"error": f"An unexpected error occurred: {e}"}), 500

# Removed Emby Connect routes as per user request - Keeping this comment temporarily for context

# Emby Authentication Route
@auth_bp.route('/api/auth/emby/login', methods=['POST'])
def emby_login():
    """Handle Emby login attempt"""
    data = request.json
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'success': False, 'message': 'Username and password are required'}), 400

    try:
        # Assume auth_manager will have a login_with_emby method
        success, result = auth_manager.login_with_emby(username, password)

        if success:
            # Set the auth token in a cookie
            response = make_response(jsonify({'success': True, 'message': 'Login successful'}))
            expires = datetime.now() + timedelta(days=30) # Remember for 30 days
            response.set_cookie(
                'auth_token',
                result, # result is the session token
                expires=expires,
                httponly=True,
                secure=request.is_secure,
                samesite='Lax',
                max_age=30 * 86400 # 30 days
            )
            current_app.logger.info(f"Emby authentication successful for user: {username}")
            return response
        else:
            current_app.logger.warning(f"Emby authentication failed for user {username}: {result}")
            return jsonify({'success': False, 'message': result}), 401 # Unauthorized

    except Exception as e:
        current_app.logger.error(f"Error during Emby login: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred during authentication'}), 500
