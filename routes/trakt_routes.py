from flask import Blueprint, jsonify, redirect, request, session
import requests
import json
import os
from datetime import datetime
import logging
from utils.settings import settings 
from utils.auth.manager import auth_manager
from utils.auth.db import AuthDB 

logger = logging.getLogger(__name__)

trakt_bp = Blueprint('trakt_bp', __name__)

HARDCODED_CLIENT_ID = '2203f1d6e97f5f8fcbfc3dcd5a6942ad03559831695939a01f9c44a1c685c4d1'
HARDCODED_CLIENT_SECRET = '3e5c2b9163264d8e9b50b8727c827b49a5ea8cc6cf0331bca931a697c243f508'
REDIRECT_URI = 'urn:ietf:wg:oauth:2.0:oob'  

CLIENT_ID = os.getenv('TRAKT_CLIENT_ID') or HARDCODED_CLIENT_ID
CLIENT_SECRET = os.getenv('TRAKT_CLIENT_SECRET') or HARDCODED_CLIENT_SECRET

@trakt_bp.route('/trakt/status')
@auth_manager.require_auth 
def status():
    """Get Trakt connection status for current user"""
    env_controlled = settings.is_field_env_controlled('trakt.enabled') or \
                     settings.is_field_env_controlled('trakt.client_id') or \
                     settings.is_field_env_controlled('trakt.client_secret') or \
                     settings.is_field_env_controlled('trakt.access_token') or \
                     settings.is_field_env_controlled('trakt.refresh_token')

    if env_controlled:
        global_settings = settings.get('trakt', {})
        is_connected = bool(global_settings.get('access_token'))
        is_enabled = is_connected 

        return jsonify({
            'connected': is_connected,
            'env_controlled': True,
            'enabled': is_enabled
        })
    
    if auth_manager.auth_enabled:
        username = session.get('username')
        if not username:
            return jsonify({'error': 'User session not found'}), 401

        user_data = auth_manager.db.get_user(username)
        if not user_data:
            return jsonify({'error': 'User not found in database'}), 404

        is_connected = bool(user_data.get('trakt_access_token'))
        is_enabled = user_data.get('trakt_enabled', False)

        return jsonify({
            'connected': is_connected,
            'env_controlled': False,
            'enabled': is_enabled,
            'username': username 
        })
    else:
        trakt_settings = settings.get('trakt', {})
        is_connected = bool(trakt_settings.get('access_token'))
        is_enabled = trakt_settings.get('enabled', False)

        return jsonify({
            'connected': is_connected,
            'env_controlled': False,
            'enabled': is_enabled,
            'auth_disabled': True
        })

@trakt_bp.route('/trakt/authorize')
@auth_manager.require_auth 
def authorize():
    """Start the Trakt authorization flow"""
    auth_url = 'https://trakt.tv/oauth/authorize'
    full_auth_url = f"{auth_url}?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
    logger.info(f"Authorization URL: {full_auth_url}")

    return jsonify({
        'auth_url': full_auth_url,
        'oob': True
    })

@trakt_bp.route('/trakt/token', methods=['POST'])
@auth_manager.require_auth 
def get_token():
    """Handle the authorization code and get tokens"""
    code = request.json.get('code')
    if not code:
        logger.error("No code provided")
        return jsonify({'error': 'No code provided'}), 400

    try:
        request_data = {
            'code': code,
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'redirect_uri': REDIRECT_URI,
            'grant_type': 'authorization_code'
        }
        
        if auth_manager.auth_enabled:
            username = session.get('username')
            if not username:
                return jsonify({'error': 'User session not found'}), 401
            
            logger.info(f"Making token request with data for user {username}")
        else:
            logger.info("Making token request with data (auth disabled, using global settings)")
        
        response = requests.post('https://api.trakt.tv/oauth/token', json=request_data)

        logger.info(f"Token response status: {response.status_code}")
        logger.info(f"Token response text: {response.text}")

        if response.ok:
            token_data = response.json()
            
            if auth_manager.auth_enabled:
                update_data = {
                    'trakt_access_token': token_data['access_token'],
                    'trakt_refresh_token': token_data['refresh_token'],
                    'trakt_enabled': True
                }
                success, message = auth_manager.db.update_user_data(username, update_data)

                if success:
                    logger.info(f"Successfully saved Trakt tokens and enabled for user {username}")
                    return jsonify({'status': 'success'})
                else:
                    logger.error(f"Failed to save Trakt tokens for user {username}: {message}")
                    return jsonify({'error': f'Failed to save tokens: {message}'}), 500
            else:
                trakt_data = {
                    'access_token': token_data['access_token'],
                    'refresh_token': token_data['refresh_token'],
                    'enabled': True
                }
                try:
                    settings.update('trakt', trakt_data)
                    logger.info("Successfully saved Trakt tokens to global settings")
                    return jsonify({'status': 'success'})
                except Exception as e:
                    logger.error(f"Failed to save Trakt tokens to global settings: {e}")
                    return jsonify({'error': f'Failed to save tokens: {str(e)}'}), 500
        else:
            logger.error(f"Token request failed: {response.text}")
            return jsonify({'error': 'Failed to get access token'}), 500

    except Exception as e:
        logger.error(f"Trakt token error: {e}")
        return jsonify({'error': str(e)}), 500

@trakt_bp.route('/trakt/disconnect')
@auth_manager.require_auth 
def disconnect():
    """Disconnect Trakt account for current user"""
    try:
        env_controlled = settings.is_field_env_controlled('trakt.enabled') or \
                         settings.is_field_env_controlled('trakt.client_id') or \
                         settings.is_field_env_controlled('trakt.client_secret') or \
                         settings.is_field_env_controlled('trakt.access_token') or \
                         settings.is_field_env_controlled('trakt.refresh_token')

        if env_controlled:
            logger.warning("Attempted to disconnect Trakt while ENV controlled.")
            return jsonify({
                'status': 'env_controlled',
                'message': 'Cannot disconnect while Trakt is configured via environment variables'
            }), 400

        if auth_manager.auth_enabled:
            username = session.get('username')
            if not username:
                return jsonify({'error': 'User session not found'}), 401

            update_data = {
                'trakt_access_token': None,
                'trakt_refresh_token': None,
                'trakt_enabled': False
            }
            success, message = auth_manager.db.update_user_data(username, update_data)

            if success:
                logger.info(f"Successfully disconnected Trakt for user {username}")
                return jsonify({'status': 'success'})
            else:
                logger.error(f"Failed to disconnect Trakt for user {username}: {message}")
                return jsonify({'error': f'Failed to disconnect Trakt: {message}'}), 500
        else:
            trakt_data = {
                'access_token': None,  
                'refresh_token': None,
                'enabled': False
            }
            try:
                settings.update('trakt', trakt_data)
                logger.info("Successfully disconnected Trakt in global settings")
                return jsonify({'status': 'success'})
            except Exception as e:
                logger.error(f"Failed to disconnect Trakt in global settings: {e}")
                return jsonify({'error': f'Failed to disconnect Trakt: {str(e)}'}), 500
            
    except Exception as e:
        logger.error(f"Error during Trakt disconnect: {str(e)}")
        return jsonify({'error': str(e)}), 500

@trakt_bp.route('/trakt/settings', methods=['PUT'])
@auth_manager.require_auth
def update_trakt_settings():
    """Update the Trakt enabled status for the current user."""
    env_controlled = settings.is_field_env_controlled('trakt.enabled') or \
                     settings.is_field_env_controlled('trakt.client_id') or \
                     settings.is_field_env_controlled('trakt.client_secret') or \
                     settings.is_field_env_controlled('trakt.access_token') or \
                     settings.is_field_env_controlled('trakt.refresh_token')

    if env_controlled:
        logger.warning("Attempted to update Trakt settings while ENV controlled.")
        return jsonify({
            'status': 'env_controlled',
            'message': 'Cannot update Trakt settings while configured via environment variables'
        }), 400

    data = request.get_json()
    enabled_state = data.get('enabled')

    if enabled_state is None or not isinstance(enabled_state, bool):
        return jsonify({'error': 'Invalid or missing "enabled" field in request (must be true or false)'}), 400

    if auth_manager.auth_enabled:
        username = session.get('username')
        if not username:
            return jsonify({'error': 'User session not found'}), 401

        update_data = {'trakt_enabled': enabled_state}
        success, message = auth_manager.db.update_user_data(username, update_data)

        if success:
            logger.info(f"Successfully updated Trakt enabled status to {enabled_state} for user {username}")
            return jsonify({'status': 'success', 'enabled': enabled_state})
        else:
            logger.error(f"Failed to update Trakt enabled status for user {username}: {message}")
            return jsonify({'error': f'Failed to update settings: {message}'}), 500
    else:
        try:
            settings.update('trakt', {'enabled': enabled_state})
            logger.info(f"Successfully updated Trakt enabled status to {enabled_state} in global settings")
            return jsonify({'status': 'success', 'enabled': enabled_state})
        except Exception as e:
            logger.error(f"Failed to update Trakt enabled status in global settings: {e}")
            return jsonify({'error': f'Failed to update settings: {str(e)}'}), 500
