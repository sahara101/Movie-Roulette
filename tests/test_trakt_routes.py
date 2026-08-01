import time
import unittest
from unittest.mock import Mock, patch

from flask import Flask

from routes import trakt_routes


class TraktDeviceAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = 'test-secret'
        self.app.register_blueprint(trakt_routes.trakt_bp)
        self.client = self.app.test_client()
        self.original_auth_enabled = trakt_routes.auth_manager._auth_enabled
        trakt_routes.auth_manager._auth_enabled = False

    def tearDown(self):
        trakt_routes.auth_manager._auth_enabled = self.original_auth_enabled

    def test_authorize_starts_device_flow_and_stores_private_device_code(self):
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {
            'device_code': 'private-device-code',
            'user_code': 'ABCD1234',
            'verification_url': 'https://auth.trakt.tv/activate',
            'expires_in': 600,
            'interval': 5,
        }

        with patch.object(trakt_routes, 'get_trakt_client_id', return_value='client-id'), \
                patch.object(trakt_routes, 'get_trakt_client_secret', return_value='client-secret'), \
                patch.object(trakt_routes.requests, 'post', return_value=response) as post:
            result = self.client.post('/trakt/authorize')

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.get_json()['user_code'], 'ABCD1234')
        self.assertNotIn('device_code', result.get_json())
        post.assert_called_once_with(
            'https://auth.trakt.tv/oauth/device/code',
            json={'client_id': 'client-id'},
            timeout=20,
        )
        with self.client.session_transaction() as flask_session:
            self.assertEqual(
                flask_session[trakt_routes.TRAKT_DEVICE_SESSION_KEY]['device_code'],
                'private-device-code',
            )

    def test_authorize_requires_server_side_client_secret(self):
        with patch.object(trakt_routes, 'get_trakt_client_secret', return_value=None):
            result = self.client.post('/trakt/authorize')

        self.assertEqual(result.status_code, 503)
        self.assertIn('TRAKT_CLIENT_SECRET', result.get_json()['error'])

    def test_poll_saves_tokens_and_runs_initial_sync(self):
        now = time.time()
        with self.client.session_transaction() as flask_session:
            flask_session[trakt_routes.TRAKT_DEVICE_SESSION_KEY] = {
                'device_code': 'private-device-code',
                'expires_at': now + 600,
                'interval': 5,
                'last_poll': 0,
                'username': 'global',
                'user_type': 'global',
            }

        response = Mock(ok=True, status_code=200)
        response.json.return_value = {
            'access_token': 'new-access',
            'refresh_token': 'new-refresh',
        }

        with patch.object(trakt_routes, 'get_trakt_client_id', return_value='client-id'), \
                patch.object(trakt_routes, 'get_trakt_client_secret', return_value='client-secret'), \
                patch.object(trakt_routes.requests, 'post', return_value=response) as post, \
                patch.object(trakt_routes.settings, 'update') as settings_update, \
                patch('utils.tracking_service.sync_watched_status') as sync:
            result = self.client.post('/trakt/poll')

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.get_json()['status'], 'success')
        post.assert_called_once_with(
            'https://auth.trakt.tv/oauth/device/token',
            json={
                'code': 'private-device-code',
                'client_id': 'client-id',
                'client_secret': 'client-secret',
            },
            timeout=20,
        )
        settings_update.assert_any_call('trakt', {
            'access_token': 'new-access',
            'refresh_token': 'new-refresh',
            'enabled': True,
        })
        settings_update.assert_any_call('tracking', {'provider': 'trakt'})
        sync.assert_called_once_with('global', force=True)
        with self.client.session_transaction() as flask_session:
            self.assertNotIn(trakt_routes.TRAKT_DEVICE_SESSION_KEY, flask_session)


if __name__ == '__main__':
    unittest.main()
