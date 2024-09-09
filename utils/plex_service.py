import os
import random
from plexapi.server import PlexServer

class PlexService:
    def __init__(self):
        self.PLEX_URL = os.getenv('PLEX_URL')
        self.PLEX_TOKEN = os.getenv('PLEX_TOKEN')
        self.MOVIES_LIBRARY_NAME = os.getenv('MOVIES_LIBRARY_NAME', 'Movies')
        self.plex = PlexServer(self.PLEX_URL, self.PLEX_TOKEN)
        self.movies = self.plex.library.section(self.MOVIES_LIBRARY_NAME)

    def get_random_movie(self):
        all_unwatched = self.movies.search(unwatched=True)
        chosen_movie = random.choice(all_unwatched)
        return self.get_movie_data(chosen_movie)

    def filter_movies(self, genre=None, year=None, pg_rating=None):
        filters = {'unwatched': True}
        if genre:
            filters['genre'] = genre
        if year:
            filters['year'] = int(year)
        if pg_rating:
            filters['contentRating'] = pg_rating

        filtered_movies = self.movies.search(**filters)

        if filtered_movies:
            chosen_movie = random.choice(filtered_movies)
            return self.get_movie_data(chosen_movie)
        return None

    def get_movie_data(self, movie):
        movie_duration_hours = (movie.duration / (1000 * 60 * 60)) % 24
        movie_duration_minutes = (movie.duration / (1000 * 60)) % 60
        return {
            "id": movie.ratingKey,
            "title": movie.title,
            "year": movie.year,
            "duration_hours": int(movie_duration_hours),
            "duration_minutes": int(movie_duration_minutes),
            "directors": [director.tag for director in movie.directors],
            "description": movie.summary,
            "writers": [writer.tag for writer in movie.writers][:3],  # Limit to first 3 writers
            "actors": [actor.tag for actor in movie.actors][:3],  # Limit to first 3 actors
            "genres": [genre.tag for genre in movie.genres],
            "poster": movie.posterUrl,
            "background": movie.artUrl,
            "contentRating": movie.contentRating
        }

    def get_genres(self):
        all_genres = set()
        for movie in self.movies.search(unwatched=True):
            all_genres.update([genre.tag for genre in movie.genres])
        return sorted(list(all_genres))

    def get_years(self):
        all_years = set()
        for movie in self.movies.search(unwatched=True):
            all_years.add(movie.year)
        return sorted(list(all_years), reverse=True)

    def get_pg_ratings(self):
        ratings = set()
        for movie in self.movies.search(unwatched=True):
            if movie.contentRating:
                ratings.add(movie.contentRating)
        return sorted(list(ratings))

    def get_clients(self):
        return [{"id": client.machineIdentifier, "title": client.title} for client in self.plex.clients()]

    def play_movie(self, movie_id, client_id):
        try:
            movie = self.movies.fetchItem(int(movie_id))
            client = next((c for c in self.plex.clients() if c.machineIdentifier == client_id), None)
            if not client:
                raise ValueError(f"Unknown client id: {client_id}")
            client.proxyThroughServer()
            client.playMedia(movie)
            return {"status": "playing"}
        except Exception as e:
            return {"error": str(e)}

    # Methods to support caching
    def get_total_unwatched_movies(self):
        return len(self.movies.search(unwatched=True))

    def get_all_unwatched_movies(self):
        return [self.get_movie_data(movie) for movie in self.movies.search(unwatched=True)]

    def get_movie_by_id(self, movie_id):
        movie = self.movies.fetchItem(int(movie_id))
        return self.get_movie_data(movie)
