import os
import requests
import json
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class JellyfinService:
    def __init__(self):
        self.server_url = os.getenv('JELLYFIN_URL')
        self.api_key = os.getenv('JELLYFIN_API_KEY')
        self.user_id = os.getenv('JELLYFIN_USER_ID')
        self.headers = {
            'X-Emby-Token': self.api_key,
            'Content-Type': 'application/json'
        }

    def get_random_movie(self):
        try:
            movies_url = f"{self.server_url}/Users/{self.user_id}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'SortBy': 'Random',
                'Limit': '1',
                'Fields': 'Overview,People,Genres,CommunityRating,RunTimeTicks,ProviderIds,UserData,OfficialRating',
                'IsPlayed': 'false'
            }
            response = requests.get(movies_url, headers=self.headers, params=params)
            response.raise_for_status()
            movies = response.json()
            
            if movies.get('Items'):
                movie_data = self.get_movie_data(movies['Items'][0])
                logger.debug(f"Fetched unwatched movie data: {movie_data}")
                return movie_data
            logger.warning("No unwatched movies found")
            return None
        except Exception as e:
            logger.error(f"Error fetching random unwatched movie: {e}")
            return None

    def filter_movies(self, genre=None, year=None, pg_rating=None):
        try:
            movies_url = f"{self.server_url}/Users/{self.user_id}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'SortBy': 'Random',
                'Limit': '1',
                'Fields': 'Overview,People,Genres,RunTimeTicks,ProviderIds,UserData,OfficialRating',
                'IsPlayed': 'false'
            }
            if genre:
                params['Genres'] = genre
            if year:
                params['Years'] = year
            if pg_rating:
                params['OfficialRatings'] = pg_rating

            logger.debug(f"Jellyfin API request params: {params}")
            
            response = requests.get(movies_url, headers=self.headers, params=params)
            response.raise_for_status()
            movies = response.json().get('Items', [])
            
            logger.debug(f"Jellyfin API returned {len(movies)} movies")
            
            if movies:
                return self.get_movie_data(movies[0])
            
            logger.warning("No unwatched movies found matching the criteria")
            return None
        except Exception as e:
            logger.error(f"Error filtering movies: {e}")
            return None

    def get_movie_data(self, movie):
        run_time_ticks = movie.get('RunTimeTicks', 0)
        total_minutes = run_time_ticks // 600000000  # Convert ticks to minutes
        hours = total_minutes // 60
        minutes = total_minutes % 60

        return {
            "title": movie.get('Name', ''),
            "year": movie.get('ProductionYear', ''),
            "duration_hours": hours,
            "duration_minutes": minutes,
            "directors": [p.get('Name', '') for p in movie.get('People', []) if p.get('Type') == 'Director'],
            "description": movie.get('Overview', ''),
            "writers": [p.get('Name', '') for p in movie.get('People', []) if p.get('Type') == 'Writer'][:3],  # Limit to first 3 writers
            "actors": [p.get('Name', '') for p in movie.get('People', []) if p.get('Type') == 'Actor'][:3],  # Limit to first 3 actors
            "genres": movie.get('Genres', []),
            "poster": f"{self.server_url}/Items/{movie['Id']}/Images/Primary?api_key={self.api_key}",
            "background": f"{self.server_url}/Items/{movie['Id']}/Images/Backdrop?api_key={self.api_key}",
            "id": movie.get('Id', ''),
            "ProviderIds": movie.get('ProviderIds', {}),
            "contentRating": movie.get('OfficialRating', '')
        }

    def get_genres(self):
        try:
            items_url = f"{self.server_url}/Items"
            params = {
                'Recursive': 'true',
                'Fields': 'Genres',
                'IncludeItemTypes': 'Movie'
            }
            
            response = requests.get(items_url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()
            
            all_genres = set()
            for item in data.get('Items', []):
                all_genres.update(item.get('Genres', []))
            
            genre_list = sorted(list(all_genres))
            logger.debug(f"Extracted genre list: {genre_list}")
            return genre_list
        except Exception as e:
            logger.error(f"Error fetching genres: {e}")
            return []

    def get_years(self):
        try:
            movies_url = f"{self.server_url}/Items"
            params = {
                'IncludeItemTypes': 'Movie',
                'Recursive': 'true',
                'Fields': 'ProductionYear'
            }
            response = requests.get(movies_url, headers=self.headers, params=params)
            response.raise_for_status()
            movies = response.json()
            years = set(movie.get('ProductionYear') for movie in movies.get('Items', []) if movie.get('ProductionYear'))
            year_list = sorted(list(years), reverse=True)
            logger.debug(f"Fetched years: {year_list}")
            return year_list
        except Exception as e:
            logger.error(f"Error fetching years: {e}")
            return []

    def get_pg_ratings(self):
        try:
            items_url = f"{self.server_url}/Items"
            params = {
                'Recursive': 'true',
                'Fields': 'OfficialRating',
                'IncludeItemTypes': 'Movie'
            }

            response = requests.get(items_url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()

            all_ratings = set()
            for item in data.get('Items', []):
                rating = item.get('OfficialRating')
                if rating:
                    all_ratings.add(rating)

            rating_list = sorted(list(all_ratings))
            logger.debug(f"Extracted PG rating list: {rating_list}")
            return rating_list
        except Exception as e:
            logger.error(f"Error fetching PG ratings: {e}")
            return []

    def get_clients(self):
        try:
            sessions_url = f"{self.server_url}/Sessions"
            response = requests.get(sessions_url, headers=self.headers)
            response.raise_for_status()
            sessions = response.json()
            
            logger.debug(f"Raw sessions data: {json.dumps(sessions, indent=2)}")
            
            castable_clients = []
            for session in sessions:
                if session.get('SupportsRemoteControl', False) and session.get('DeviceName') != 'Jellyfin Server':
                    client = {
                        "title": session.get('DeviceName', 'Unknown Device'),
                        "id": session.get('Id'),
                        "client": session.get('Client'),
                        "username": session.get('UserName'),
                        "device_id": session.get('DeviceId'),
                        "supports_media_control": session.get('SupportsMediaControl', False),
                    }
                    castable_clients.append(client)
            
            if not castable_clients:
                logger.warning("No castable clients found.")
            else:
                logger.info(f"Found {len(castable_clients)} castable clients")
            
            logger.debug(f"Fetched castable clients: {json.dumps(castable_clients, indent=2)}")
            return castable_clients
        except Exception as e:
            logger.error(f"Error fetching clients: {e}")
            return []

    def play_movie(self, movie_id, session_id):
        try:
            playback_url = f"{self.server_url}/Sessions/{session_id}/Playing"
            params = {
                'ItemIds': movie_id,
                'PlayCommand': 'PlayNow'
            }
            response = requests.post(playback_url, headers=self.headers, params=params)
            response.raise_for_status()
            logger.debug(f"Playing movie {movie_id} on session {session_id}")
            logger.debug(f"Response: {response.text}")
            return {"status": "playing", "response": response.text}
        except Exception as e:
            logger.error(f"Error playing movie: {e}")
            return {"error": str(e)}

# For testing purposes
if __name__ == "__main__":
    jellyfin = JellyfinService()
    
    print("\nFetching random unwatched movie:")
    movie = jellyfin.get_random_movie()
    if movie:
        print(f"Title: {movie['title']}")
        print(f"Year: {movie['year']}")
        print(f"Directors: {', '.join(movie['directors'])}")
        print(f"Writers: {', '.join(movie['writers'])}")
        print(f"Actors: {', '.join(movie['actors'])}")
        print(f"Genres: {', '.join(movie['genres'])}")
    else:
        print("No unwatched movie found")

    # Test clients
    print("\nFetching castable clients:")
    clients = jellyfin.get_clients()
    print(json.dumps(clients, indent=2))

    # Test playing a movie
    if clients and movie:
        print("\nAvailable castable clients:")
        for i, client in enumerate(clients):
            print(f"{i+1}. {client['title']} ({client['client']}) - ID: {client['id']}")
        
        choice = int(input("Choose a client number to play the movie (or 0 to skip): ")) - 1
        if 0 <= choice < len(clients):
            selected_client = clients[choice]
            print(f"\nAttempting to play movie {movie['title']} on {selected_client['title']} (Session ID: {selected_client['id']})")
            result = jellyfin.play_movie(movie['id'], selected_client['id'])
            print(result)
        elif choice != -1:
            print("Invalid client selection.")
    elif not clients:
        print("No castable clients available to play on.")
    elif not movie:
        print("No movie available to play.")
