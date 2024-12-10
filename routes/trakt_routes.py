from flask import Blueprint, jsonify, redirect, request
import requests
import json
import os
from datetime import datetime
import logging
from utils.settings import settings

from utils.path_manager import path_manager
logger = logging.getLogger(__name__)

trakt_bp = Blueprint('trakt_bp', __name__)

# Constants
HARDCODED_CLIENT_ID = '2203f1d6e97f5f8fcbfc3dcd5a6942ad03559831695939a01f9c44a1c685c4d1'
HARDCODED_CLIENT_SECRET = '3e5c2b9163264d8e9b50b8727c827b49a5ea8cc6cf0331bca931a697c243f508'
REDIRECT_URI = 'urn:ietf:wg:oauth:2.0:oob'  # Using OOB flow for portability
TRAKT_TOKENS_FILE = path_manager.get_path('trakt_tokens')

CLIENT_ID = os.getenv('TRAKT_CLIENT_ID') or HARDCODED_CLIENT_ID
CLIENT_SECRET = os.getenv('TRAKT_CLIENT_SECRET') or HARDCODED_CLIENT_SECRET

def save_tokens(access_token, refresh_token):
    """Save Trakt tokens to file"""
    try:
        tokens = {
            'access_token': access_token,
            'refresh_token': refresh_token,
            'created_at': datetime.now().isoformat()
        }
        os.makedirs(os.path.dirname(TRAKT_TOKENS_FILE), exist_ok=True)
        with open(TRAKT_TOKENS_FILE, 'w') as f:
            json.dump(tokens, f)
        return True
    except Exception as e:
        logger.error(f"Failed to save Trakt tokens: {e}")
        return False

def load_tokens():
    """Load Trakt tokens from file or ENV"""
    # First check ENV variables
    env_access_token = os.getenv('TRAKT_ACCESS_TOKEN')
    env_refresh_token = os.getenv('TRAKT_REFRESH_TOKEN')

    if env_access_token and env_refresh_token:
        return {
            'access_token': env_access_token,
            'refresh_token': env_refresh_token
        }

    # Then check file
    try:
        if os.path.exists(TRAKT_TOKENS_FILE):
            with open(TRAKT_TOKENS_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load Trakt tokens: {e}")

    return None

def refresh_token():
    """Refresh Trakt access token"""
    tokens = load_tokens()
    if not tokens:
        return False

    try:
        response = requests.post('https://api.trakt.tv/oauth/token', json={
            'refresh_token': tokens['refresh_token'],
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'grant_type': 'refresh_token'
        })

        if response.ok:
            new_tokens = response.json()
            save_tokens(new_tokens['access_token'], new_tokens['refresh_token'])
            return True

    except Exception as e:
        logger.error(f"Failed to refresh Trakt token: {e}")
    return False

def make_trakt_request(method, endpoint, **kwargs):
    """Make a request to Trakt API with automatic token refresh"""
    tokens = load_tokens()
    if not tokens:
        return None

    try:
        headers = {
            'Authorization': f'Bearer {tokens["access_token"]}',
            'Content-Type': 'application/json',
            'trakt-api-version': '2',
            'trakt-api-key': CLIENT_ID
        }

        if 'headers' in kwargs:
            headers.update(kwargs.pop('headers'))

        response = requests.request(
            method,
            f'https://api.trakt.tv/{endpoint}',
            headers=headers,
            **kwargs
        )

        if response.status_code == 401 and refresh_token():
            # Retry with new token
            tokens = load_tokens()
            headers['Authorization'] = f'Bearer {tokens["access_token"]}'
            response = requests.request(
                method,
                f'https://api.trakt.tv/{endpoint}',
                headers=headers,
                **kwargs
            )

        return response

    except Exception as e:
        logger.error(f"Trakt API request failed: {e}")
        return None

@trakt_bp.route('/trakt/status')
def status():
    """Get Trakt connection status"""
    # Check ENV variables first
    env_access = os.getenv('TRAKT_ACCESS_TOKEN')
    env_refresh = os.getenv('TRAKT_REFRESH_TOKEN')
    env_client_id = os.getenv('TRAKT_CLIENT_ID')
    env_client_secret = os.getenv('TRAKT_CLIENT_SECRET')

    env_controlled = all([
        env_access,
        env_refresh,
        env_client_id,
        env_client_secret
    ])

    if env_controlled:
        return jsonify({
            'connected': True,
            'env_controlled': True,
            'enabled': True  # ENV-controlled means enabled
        })

    # Check settings-based configuration
    trakt_settings = settings.get('trakt', {})
    settings_enabled = bool(trakt_settings.get('enabled'))

    # Check file-based tokens
    tokens = load_tokens()
    is_connected = bool(tokens)

    return jsonify({
        'connected': is_connected,
        'env_controlled': False,
        'enabled': settings_enabled
    })

@trakt_bp.route('/trakt/authorize')
def authorize():
    """Start the Trakt authorization flow"""
    auth_url = 'https://trakt.tv/oauth/authorize'
    full_auth_url = f"{auth_url}?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
    logger.info(f"Authorization URL: {full_auth_url}")
    
    # Check if this is a native app request
    is_native = request.args.get('native') == 'true'
    
    if is_native:
        from movie_selector import trakt_auth_handler
        trakt_auth_handler.show_dialog.emit(full_auth_url)
        
    return jsonify({
        'auth_url': full_auth_url,
        'oob': True,
        'native': is_native
    })

@trakt_bp.route('/trakt/token', methods=['POST'])
def get_token():
    """Handle the authorization code and get tokens"""
    code = request.json.get('code')
    if not code:
        logger.error("No code provided")
        return jsonify({'error': 'No code provided'}), 400

    try:
        # Log the request data
        request_data = {
            'code': code,
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'redirect_uri': REDIRECT_URI,
            'grant_type': 'authorization_code'
        }
        logger.info(f"Making token request with data: {request_data}")
        
        response = requests.post('https://api.trakt.tv/oauth/token', json=request_data)

        logger.info(f"Token response status: {response.status_code}")
        logger.info(f"Token response text: {response.text}")

        if response.ok:
            token_data = response.json()
            if save_tokens(token_data['access_token'], token_data['refresh_token']):
                return jsonify({'status': 'success'})
            else:
                logger.error("Failed to save tokens")
                return jsonify({'error': 'Failed to save tokens'}), 500
        else:
            logger.error(f"Token request failed: {response.text}")
            return jsonify({'error': 'Failed to get access token'}), 500

    except Exception as e:
        logger.error(f"Trakt token error: {e}")
        return jsonify({'error': str(e)}), 500

@trakt_bp.route('/trakt/disconnect')
def disconnect():
    """Disconnect Trakt account"""
    try:
        # Check for ENV variables first
        env_access = os.getenv('TRAKT_ACCESS_TOKEN')
        env_refresh = os.getenv('TRAKT_REFRESH_TOKEN')
        
        if env_access or env_refresh:
            logger.warning("Trakt tokens exist in environment variables")
            return jsonify({
                'status': 'env_controlled',
                'message': 'Cannot disconnect while Trakt is configured via environment variables'
            }), 400
        
        # Remove the tokens file
        if os.path.exists(TRAKT_TOKENS_FILE):
            try:
                os.remove(TRAKT_TOKENS_FILE)
                logger.info("Successfully removed tokens file")
            except Exception as e:
                logger.error(f"Failed to remove tokens file: {e}")
                return jsonify({'error': 'Failed to remove tokens file'}), 500
        
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Error during Trakt disconnect: {str(e)}")
        return jsonify({'error': str(e)}), 500
