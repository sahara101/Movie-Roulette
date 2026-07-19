import unittest
from unittest.mock import Mock, patch

from utils import tracking_service


class TrackingProviderTests(unittest.TestCase):
    def test_existing_trakt_user_keeps_trakt_as_provider(self):
        fake_db = Mock()
        fake_db.get_managed_user_by_username.return_value = None
        fake_db.get_user.return_value = {
            'username': 'legacy-user',
            'trakt_enabled': True,
        }

        with patch.object(tracking_service.auth_manager, 'db', fake_db), \
                patch.dict(tracking_service.os.environ, {}, clear=True):
            provider = tracking_service.get_tracking_provider('legacy-user')

        self.assertEqual(provider, 'trakt')

    def test_selecting_simkl_disables_trakt_without_removing_tokens(self):
        fake_db = Mock()
        fake_db.get_managed_user_by_username.return_value = None
        fake_db.get_user.return_value = {
            'username': 'user',
            'tracking_provider': 'trakt',
            'trakt_enabled': True,
            'trakt_access_token': 'keep-me',
        }
        fake_db.update_user_data.return_value = (True, 'updated')

        with patch.object(tracking_service.auth_manager, 'db', fake_db), \
                patch.dict(tracking_service.os.environ, {}, clear=True):
            success, _ = tracking_service.set_tracking_provider('simkl', 'user')

        self.assertTrue(success)
        fake_db.update_user_data.assert_called_once_with('user', {
            'tracking_provider': 'simkl',
            'trakt_enabled': False,
        })

    def test_environment_provider_overrides_user_selection(self):
        with patch.dict(
            tracking_service.os.environ,
            {'TRACKING_PROVIDER': 'simkl'},
            clear=True,
        ):
            provider = tracking_service.get_tracking_provider('any-user')

        self.assertEqual(provider, 'simkl')


if __name__ == '__main__':
    unittest.main()
