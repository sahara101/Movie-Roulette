# youtube_trailer.py

import requests

def search_youtube_trailer(movie_title, movie_year):
    """Fetch a trailer URL from YouTube using a direct search query."""
    
    # Format the movie title for the YouTube search query
    formatted_title = f'{movie_title.replace(" ", "+")}+{movie_year}+trailer'
    search_url = f'https://www.youtube.com/results?search_query={formatted_title}'

    try:
        # Make a request to the YouTube search URL
        response = requests.get(search_url)
        response.raise_for_status()
        
        # Check if response contains any trailer link (simplistic approach)
        if 'watch?v=' in response.text:
            start_index = response.text.find('watch?v=') + 8
            end_index = response.text.find('"', start_index)
            trailer_id = response.text[start_index:end_index]
            trailer_url = f'https://www.youtube.com/embed/{trailer_id}'
            return trailer_url
        else:
            return "Trailer not found on YouTube."

    except requests.RequestException as e:
        return f"Error fetching YouTube trailer: {e}"

