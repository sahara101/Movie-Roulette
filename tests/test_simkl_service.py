import json
import os
import tempfile
import unittest
from unittest.mock import patch

from utils import simkl_service


class FakeResponse:
    def __init__(self, payload=None, status_code=200, headers=None):
        self._payload = payload or {}
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.headers = headers or {}

    def json(self):
        return self._payload


class SimklSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path_patches = [
            patch.object(simkl_service, 'DATA_DIR', self.temp_dir.name),
            patch.object(
                simkl_service,
                'USER_DATA_DIR',
                os.path.join(self.temp_dir.name, 'user_data'),
            ),
            patch.object(
                simkl_service,
                'DEFAULT_WATCHED_FILE',
                os.path.join(self.temp_dir.name, 'simkl_watched_movies.json'),
            ),
            patch.object(
                simkl_service,
                'DEFAULT_STATE_FILE',
                os.path.join(self.temp_dir.name, 'simkl_sync_state.json'),
            ),
            patch('utils.tracking_service.get_tracking_provider', return_value='simkl'),
            patch.object(simkl_service, 'get_user_simkl_token', return_value='token'),
        ]
        for path_patch in self.path_patches:
            path_patch.start()
            self.addCleanup(path_patch.stop)

    def write_cache(self, watched, state):
        with open(simkl_service.DEFAULT_WATCHED_FILE, 'w') as handle:
            json.dump(watched, handle)
        with open(simkl_service.DEFAULT_STATE_FILE, 'w') as handle:
            json.dump(state, handle)

    def test_initial_sync_downloads_completed_movies(self):
        activities = FakeResponse({
            'movies': {
                'all': '2026-07-18T10:00:00.000Z',
                'removed_from_list': '2026-07-18T09:00:00.000Z',
            }
        })
        completed = FakeResponse({
            'movies': [
                {'status': 'completed', 'movie': {'ids': {'tmdb': 22}}},
                {'status': 'completed', 'movie': {'ids': {'tmdb': '11'}}},
                {'status': 'completed', 'movie': {'ids': {'tmdb': None}}},
            ]
        })

        with patch.object(
            simkl_service,
            'make_simkl_request',
            side_effect=[activities, completed],
        ) as request_mock:
            result = simkl_service.sync_watched_status('global')

        self.assertEqual(result, [11, 22])
        self.assertEqual(request_mock.call_count, 2)
        self.assertEqual(request_mock.call_args_list[1].args[1], 'sync/all-items/movies/completed')

    def test_unchanged_activity_skips_all_items_request(self):
        state = {
            'movies_all': '2026-07-18T10:00:00.000Z',
            'movies_removed': '2026-07-18T09:00:00.000Z',
        }
        self.write_cache([11, 22], state)
        activities = FakeResponse({
            'movies': {
                'all': state['movies_all'],
                'removed_from_list': state['movies_removed'],
            }
        })

        with patch.object(
            simkl_service,
            'make_simkl_request',
            return_value=activities,
        ) as request_mock:
            result = simkl_service.sync_watched_status('global')

        self.assertEqual(result, [11, 22])
        request_mock.assert_called_once()
        self.assertEqual(request_mock.call_args.args[1], 'sync/activities')

    def test_delta_adds_completed_and_removes_other_statuses(self):
        old_all = '2026-07-18T10:00:00.000Z'
        removed = '2026-07-18T09:00:00.000Z'
        self.write_cache([11, 22], {
            'movies_all': old_all,
            'movies_removed': removed,
        })
        activities = FakeResponse({
            'movies': {
                'all': '2026-07-18T11:00:00.000Z',
                'removed_from_list': removed,
            }
        })
        delta = FakeResponse({
            'movies': [
                {'status': 'completed', 'movie': {'ids': {'tmdb': 33}}},
                {'status': 'watching', 'movie': {'ids': {'tmdb': 22}}},
            ]
        })

        with patch.object(
            simkl_service,
            'make_simkl_request',
            side_effect=[activities, delta],
        ) as request_mock:
            result = simkl_service.sync_watched_status('global')

        self.assertEqual(result, [11, 33])
        delta_call = request_mock.call_args_list[1]
        self.assertEqual(delta_call.args[1], 'sync/all-items/movies')
        self.assertEqual(delta_call.kwargs['params']['date_from'], old_all)


class SimklApiTests(unittest.TestCase):
    def tearDown(self):
        simkl_service._resolve_simkl_movie.cache_clear()

    def test_client_id_uses_built_in_app_by_default(self):
        with patch.dict(simkl_service.os.environ, {}, clear=True), \
                patch.object(simkl_service.settings, 'get', return_value={}):
            client_id = simkl_service.get_simkl_client_id()

        self.assertEqual(client_id, simkl_service.HARDCODED_SIMKL_CLIENT_ID)

    def test_client_id_can_be_overridden_by_environment(self):
        with patch.dict(
            simkl_service.os.environ,
            {'SIMKL_CLIENT_ID': 'custom-client-id'},
            clear=True,
        ):
            client_id = simkl_service.get_simkl_client_id()

        self.assertEqual(client_id, 'custom-client-id')

    def test_requests_include_required_application_parameters(self):
        response = FakeResponse()
        with patch.object(simkl_service, 'get_simkl_client_id', return_value='client-id'), \
                patch.object(simkl_service.requests, 'request', return_value=response) as request_mock:
            result = simkl_service.make_simkl_request(
                'GET',
                'sync/activities',
                authenticated=False,
            )

        self.assertIs(result, response)
        kwargs = request_mock.call_args.kwargs
        self.assertEqual(kwargs['params']['client_id'], 'client-id')
        self.assertEqual(kwargs['params']['app-name'], 'movie-roulette')
        self.assertIn('app-version', kwargs['params'])
        self.assertIn('Movie-Roulette/', kwargs['headers']['User-Agent'])

    def test_rating_is_converted_from_ten_to_one_hundred(self):
        redirect = FakeResponse(
            status_code=302,
            headers={'Location': 'https://simkl.com/movies/42/example'},
        )
        details = FakeResponse({'ratings': {'simkl': {'rating': 7.6}}})
        with patch.object(
            simkl_service,
            'make_simkl_request',
            side_effect=[redirect, details],
        ):
            rating = simkl_service.get_simkl_rating(123)

        self.assertEqual(rating, 76)


if __name__ == '__main__':
    unittest.main()
