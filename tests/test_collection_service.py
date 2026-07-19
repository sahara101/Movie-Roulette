import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from utils.collection_service import CollectionService


class FakeCacheManager:
    def __init__(self, cache_path, build_cache=True):
        self.all_movies_cache_path = str(cache_path)
        self.build_cache = build_cache
        self.build_calls = []

    def cache_all_plex_movies(self, synchronous=False):
        self.build_calls.append(synchronous)
        if self.build_cache:
            with open(self.all_movies_cache_path, 'w') as cache_file:
                cache_file.write('[]')


class CollectionCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cache_path = Path(self.temp_dir.name) / 'plex_all_movies.json'

    def test_builds_missing_cache(self):
        cache_manager = FakeCacheManager(self.cache_path)

        CollectionService._ensure_plex_all_movies_cache(cache_manager)

        self.assertEqual(cache_manager.build_calls, [True])

    def test_reuses_existing_cache(self):
        self.cache_path.write_text('[]')
        cache_manager = FakeCacheManager(self.cache_path)

        CollectionService._ensure_plex_all_movies_cache(cache_manager)

        self.assertEqual(cache_manager.build_calls, [])

    def test_requires_cache_manager(self):
        for cache_manager in (
            None,
            SimpleNamespace(all_movies_cache_path=None),
        ):
            with self.subTest(cache_manager=cache_manager):
                with self.assertRaises(RuntimeError):
                    CollectionService._ensure_plex_all_movies_cache(cache_manager)

    def test_fails_when_build_does_not_write(self):
        cache_manager = FakeCacheManager(self.cache_path, build_cache=False)

        with self.assertRaisesRegex(RuntimeError, 'could not be built'):
            CollectionService._ensure_plex_all_movies_cache(cache_manager)


class CollectionStatusTests(unittest.TestCase):
    def test_returns_complete_collection_in_release_order(self):
        service = CollectionService()
        parts = [
            {'id': 1, 'title': 'First', 'release_date': '2020-01-01'},
            {'id': 2, 'title': 'Current', 'release_date': '2021-01-01'},
            {'id': 3, 'title': 'Later', 'release_date': '2022-01-01'},
        ]
        library_movies = [
            {'tmdb_id': 1, 'watched': True},
            {'tmdb_id': 2, 'watched': False},
        ]

        with patch(
            'utils.collection_service.tmdb_service.get_movie_details',
            return_value={
                'belongs_to_collection': {
                    'id': 99,
                    'name': 'Example Collection',
                    'poster_path': '/collection.jpg',
                }
            },
        ), patch.object(
            service,
            'get_collection_info',
            return_value={'parts': parts},
        ), patch.object(
            service,
            '_is_movie_in_plex',
            side_effect=lambda movie_id: movie_id in {1, 2},
        ), patch.object(
            service,
            'get_all_movies',
            return_value=library_movies,
        ) as all_movies_mock, patch.object(
            service,
            'check_request_status',
            side_effect=lambda movie_id: movie_id == 3,
        ) as request_mock, patch(
            'utils.collection_service.is_movie_watched_on_tracker',
            side_effect=lambda movie_id: movie_id == 3,
        ), patch(
            'utils.collection_service.get_tracking_provider',
            return_value='simkl',
        ):
            result = service.check_collection_status(2, 'plex')

        self.assertEqual(
            [movie['id'] for movie in result['collection_movies']],
            [1, 2, 3],
        )
        self.assertEqual(
            [movie['relation'] for movie in result['collection_movies']],
            ['previous', 'current', 'later'],
        )
        self.assertEqual([movie['id'] for movie in result['previous_movies']], [1])
        self.assertEqual([movie['id'] for movie in result['other_movies']], [3])
        self.assertTrue(result['collection_movies'][0]['is_watched'])
        self.assertTrue(result['collection_movies'][2]['is_watched_on_tracker'])
        self.assertTrue(result['collection_movies'][2]['is_requested'])
        self.assertEqual(result['current_movie_id'], 2)
        all_movies_mock.assert_called_once_with()
        request_mock.assert_called_once_with(3)


if __name__ == '__main__':
    unittest.main()
