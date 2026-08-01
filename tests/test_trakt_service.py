import os
import unittest
from unittest.mock import Mock, patch

from utils import trakt_credentials, trakt_service


class TraktRefreshTests(unittest.TestCase):
    def test_invalid_grant_clears_tokens_and_active_provider(self):
        fake_db = Mock()
        fake_db.get_managed_user_by_username.return_value = None
        fake_db.get_user.return_value = {'trakt_enabled': True}
        response = Mock(ok=False, status_code=400, text='invalid grant')
        response.json.return_value = {
            'error': 'invalid_grant',
            'error_description': 'session not found',
        }

        with patch.object(trakt_service.auth_manager, 'db', fake_db), \
                patch.object(trakt_service, 'is_trakt_env_controlled', return_value=False), \
                patch.object(trakt_service, 'get_user_trakt_tokens', return_value={
                    'access_token': 'old-access',
                    'refresh_token': 'old-refresh',
                }), \
                patch.object(trakt_service.requests, 'post', return_value=response):
            refreshed = trakt_service.refresh_user_trakt_token(
                'plex_user',
                stale_access_token='old-access',
            )

        self.assertFalse(refreshed)
        fake_db.update_user_data.assert_called_once_with('plex_user', {
            'trakt_access_token': None,
            'trakt_refresh_token': None,
            'trakt_enabled': False,
            'tracking_provider': 'none',
        })

    def test_refresh_sends_configured_secret_and_saves_rotated_tokens(self):
        fake_db = Mock()
        fake_db.get_managed_user_by_username.return_value = None
        fake_db.get_user.return_value = {'trakt_enabled': True}
        fake_db.update_user_data.return_value = (True, 'updated')
        response = Mock(ok=True, status_code=200)
        response.json.return_value = {
            'access_token': 'new-access',
            'refresh_token': 'new-refresh',
        }

        with patch.object(trakt_service.auth_manager, 'db', fake_db), \
                patch.object(trakt_service, 'is_trakt_env_controlled', return_value=False), \
                patch.object(trakt_service, 'get_user_trakt_tokens', return_value={
                    'access_token': 'old-access',
                    'refresh_token': 'old-refresh',
                }), \
                patch.object(trakt_service, 'get_trakt_client_id', return_value='client-id'), \
                patch.object(trakt_service, 'get_trakt_client_secret', return_value='client-secret'), \
                patch.object(trakt_service.requests, 'post', return_value=response) as post:
            refreshed = trakt_service.refresh_user_trakt_token(
                'plex_user',
                stale_access_token='old-access',
            )

        self.assertTrue(refreshed)
        post.assert_called_once_with(
            'https://api.trakt.tv/oauth/token',
            json={
                'refresh_token': 'old-refresh',
                'client_id': 'client-id',
                'grant_type': 'refresh_token',
                'client_secret': 'client-secret',
            },
            timeout=20,
        )
        fake_db.update_user_data.assert_called_once_with('plex_user', {
            'trakt_access_token': 'new-access',
            'trakt_refresh_token': 'new-refresh',
        })


class TraktCredentialTests(unittest.TestCase):
    def test_built_in_app_provides_both_id_and_secret(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(trakt_credentials.settings, 'get', return_value={}):
            self.assertEqual(
                trakt_credentials.get_trakt_client_id(),
                trakt_credentials.HARDCODED_CLIENT_ID,
            )
            self.assertEqual(
                trakt_credentials.get_trakt_client_secret(),
                trakt_credentials.HARDCODED_CLIENT_SECRET,
            )

    def test_custom_client_id_never_inherits_built_in_secret(self):
        with patch.dict(os.environ, {'TRAKT_CLIENT_ID': 'custom-id'}, clear=True), \
                patch.object(trakt_credentials.settings, 'get', return_value={}):
            self.assertIsNone(trakt_credentials.get_trakt_client_secret())

    def test_configured_secret_takes_priority(self):
        with patch.dict(os.environ, {'TRAKT_CLIENT_SECRET': 'env-secret'}, clear=True), \
                patch.object(trakt_credentials.settings, 'get', return_value={}):
            self.assertEqual(trakt_credentials.get_trakt_client_secret(), 'env-secret')


class TraktPeriodicSyncTests(unittest.TestCase):
    def test_regular_users_are_checked_using_full_database_records(self):
        fake_db = Mock()
        fake_db.get_users.return_value = {
            'plex_user': {'service_type': 'plex'},
        }
        fake_db.get_user.return_value = {
            'trakt_enabled': True,
            'trakt_access_token': 'access-token',
        }
        fake_db.get_all_managed_users.return_value = {}

        with patch.object(trakt_service.auth_manager, 'db', fake_db), \
                patch.object(trakt_service.auth_manager, '_auth_enabled', True), \
                patch.object(trakt_service, 'sync_watched_status') as sync:
            trakt_service.update_watched_status_for_users()

        sync.assert_called_once_with(user_id='plex_user')


if __name__ == '__main__':
    unittest.main()
