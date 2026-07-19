import logging
import time

from flask import Blueprint, jsonify, make_response, request, session

from utils.auth.manager import auth_manager
from utils.simkl_service import (
    clear_simkl_token,
    get_simkl_client_id,
    get_user_simkl_token,
    is_simkl_env_controlled,
    make_simkl_request,
    save_simkl_token,
)
from utils.tracking_service import (
    PROVIDER_LABELS,
    VALID_TRACKING_PROVIDERS,
    get_current_user_id,
    get_local_watched_movies,
    get_tracking_provider,
    get_tracking_status,
    is_tracking_enabled,
    set_tracking_provider,
    sync_watched_status,
)


logger = logging.getLogger(__name__)
tracking_bp = Blueprint('tracking_bp', __name__)


def _no_cache_json(payload, status=200):
    response = make_response(jsonify(payload), status)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@tracking_bp.route('/api/tracking/status')
@auth_manager.require_auth
def tracking_status():
    return _no_cache_json(get_tracking_status(get_current_user_id()))


@tracking_bp.route('/api/tracking/provider', methods=['PUT'])
@auth_manager.require_auth
def update_tracking_provider():
    data = request.get_json(silent=True) or {}
    provider = str(data.get('provider', '')).strip().lower()
    if provider not in VALID_TRACKING_PROVIDERS:
        return jsonify({'error': 'Provider must be none, trakt, or simkl'}), 400

    if provider == 'simkl' and not get_simkl_client_id():
        return jsonify({'error': 'Configure a Simkl Client ID before selecting Simkl'}), 400

    success, message = set_tracking_provider(provider, get_current_user_id())
    if not success:
        return jsonify({'error': message}), 400
    return jsonify({
        'status': 'success',
        'provider': provider,
        'tracking': get_tracking_status(get_current_user_id()),
    })


@tracking_bp.route('/api/tracking/watched')
@auth_manager.require_auth
def tracking_watched():
    user_id = get_current_user_id()
    provider = get_tracking_provider(user_id)
    return jsonify({
        'provider': provider,
        'provider_label': PROVIDER_LABELS[provider],
        'enabled': is_tracking_enabled(user_id),
        'watched_tmdb_ids': get_local_watched_movies(user_id),
    })


@tracking_bp.route('/api/tracking/sync', methods=['POST'])
@auth_manager.require_auth
def sync_tracking_watched():
    user_id = get_current_user_id()
    watched = sync_watched_status(user_id)
    provider = get_tracking_provider(user_id)
    return jsonify({
        'provider': provider,
        'provider_label': PROVIDER_LABELS[provider],
        'enabled': is_tracking_enabled(user_id),
        'watched_tmdb_ids': watched,
    })


@tracking_bp.route('/api/collections/tracking_watched', methods=['POST'])
@auth_manager.require_auth
def collection_tracking_watched():
    user_id = get_current_user_id()
    provider = get_tracking_provider(user_id)
    if not is_tracking_enabled(user_id):
        return jsonify({
            'provider': provider,
            'provider_label': PROVIDER_LABELS[provider],
            'enabled': False,
            'watched_tmdb_ids': [],
        })

    data = request.get_json(silent=True) or {}
    try:
        requested_ids = {int(value) for value in data.get('tmdb_ids', [])}
    except (TypeError, ValueError):
        return jsonify({'error': 'tmdb_ids must contain integers'}), 400

    watched = get_local_watched_movies(user_id)
    if requested_ids:
        watched = [tmdb_id for tmdb_id in watched if tmdb_id in requested_ids]
    return jsonify({
        'provider': provider,
        'provider_label': PROVIDER_LABELS[provider],
        'enabled': True,
        'watched_tmdb_ids': watched,
    })


@tracking_bp.route('/simkl/status')
@auth_manager.require_auth
def simkl_status():
    user_id = get_current_user_id()
    return _no_cache_json({
        'connected': bool(get_user_simkl_token(user_id)),
        'configured': bool(get_simkl_client_id()),
        'enabled': get_tracking_provider(user_id) == 'simkl' and bool(get_user_simkl_token(user_id)),
        'env_controlled': is_simkl_env_controlled(),
    })


@tracking_bp.route('/simkl/authorize', methods=['POST'])
@auth_manager.require_auth
def simkl_authorize():
    if not get_simkl_client_id():
        return jsonify({'error': 'Configure a Simkl Client ID first'}), 400
    if is_simkl_env_controlled():
        return jsonify({'error': 'Simkl access is controlled by SIMKL_ACCESS_TOKEN'}), 400

    response = make_simkl_request('GET', 'oauth/pin', authenticated=False)
    if not response or not response.ok:
        return jsonify({'error': 'Unable to request a Simkl PIN'}), 502
    payload = response.json()
    user_code = payload.get('user_code')
    if not user_code:
        return jsonify({'error': 'Simkl did not return a PIN'}), 502

    interval = max(int(payload.get('interval', 5)), 5)
    expires_in = int(payload.get('expires_in', 900))
    session['simkl_pin'] = {
        'user_code': user_code,
        'interval': interval,
        'expires_at': time.time() + expires_in,
        'last_poll': 0,
    }
    return jsonify({
        'user_code': user_code,
        'verification_uri': payload.get('verification_uri') or 'https://simkl.com/pin',
        'expires_in': expires_in,
        'interval': interval,
    })


@tracking_bp.route('/simkl/poll', methods=['POST'])
@auth_manager.require_auth
def simkl_poll():
    pin_data = session.get('simkl_pin') or {}
    user_code = pin_data.get('user_code')
    if not user_code or time.time() >= pin_data.get('expires_at', 0):
        session.pop('simkl_pin', None)
        return jsonify({'error': 'Simkl PIN expired. Start again.'}), 410

    interval = pin_data.get('interval', 5)
    if time.time() - pin_data.get('last_poll', 0) < interval:
        return jsonify({'status': 'pending', 'interval': interval}), 202
    pin_data['last_poll'] = time.time()
    session['simkl_pin'] = pin_data

    response = make_simkl_request('GET', f'oauth/pin/{user_code}', authenticated=False)
    if not response or not response.ok:
        return jsonify({'error': 'Unable to check Simkl authorization'}), 502
    payload = response.json()
    access_token = payload.get('access_token')
    if not access_token:
        if payload.get('device_code'):
            session.pop('simkl_pin', None)
            return jsonify({'error': 'Simkl PIN is no longer valid'}), 410
        return jsonify({'status': 'pending', 'interval': interval}), 202

    user_id = get_current_user_id()
    success, message = save_simkl_token(access_token, user_id)
    if not success:
        return jsonify({'error': message}), 500
    session.pop('simkl_pin', None)

    try:
        sync_watched_status(user_id, force=True)
    except Exception as exc:
        logger.warning('Initial Simkl sync failed for %s: %s', user_id, exc)
    return jsonify({'status': 'success', 'provider': 'simkl'})


@tracking_bp.route('/simkl/disconnect', methods=['POST'])
@auth_manager.require_auth
def simkl_disconnect():
    success, message = clear_simkl_token(get_current_user_id())
    if not success:
        return jsonify({'error': message}), 400
    return jsonify({'status': 'success'})
