document.addEventListener('DOMContentLoaded', () => {
    const movieGrid = document.getElementById('movie-grid');
    const genreFilter = document.getElementById('genre-filter');
    const yearFilter = document.getElementById('year-filter');
    const ratingFilter = document.getElementById('rating-filter');
    const refreshBtn = document.getElementById('refresh-btn');

    let allMovies = [];
    let filteredMovies = [];

    const fetchMovies = async () => {
        const url = '/all_movies_grid';
        try {
            const response = await fetch(url);
            const data = await response.json();
            allMovies = data.movies || [];
            populateFilters();
            renderMovies();
        } catch (error) {
            console.error('Error fetching movies:', error);
        }
    };

    const populateFilters = () => {
        const genres = new Set();
        const years = new Set();
        const ratings = new Set();

        allMovies.forEach(movie => {
            if (movie.genres) {
                movie.genres.forEach(genre => genres.add(genre));
            }
            if (movie.year) {
                years.add(movie.year);
            }
            if (movie.contentRating) {
                ratings.add(movie.contentRating);
            }
        });

        const sortedGenres = Array.from(genres).sort();
        sortedGenres.forEach(genre => {
            const option = document.createElement('option');
            option.value = genre;
            option.textContent = genre;
            genreFilter.appendChild(option);
        });

        const sortedYears = Array.from(years).sort((a, b) => b - a);
        sortedYears.forEach(year => {
            const option = document.createElement('option');
            option.value = year;
            option.textContent = year;
            yearFilter.appendChild(option);
        });

        const sortedRatings = Array.from(ratings).sort();
        sortedRatings.forEach(rating => {
            const option = document.createElement('option');
            option.value = rating;
            option.textContent = rating;
            ratingFilter.appendChild(option);
        });
    };

    const filterMovies = () => {
        const selectedGenre = genreFilter.value;
        const selectedYear = yearFilter.value;
        const selectedRating = ratingFilter.value;

        let movies = allMovies;

        if (selectedGenre) {
            movies = movies.filter(movie => movie.genres && movie.genres.includes(selectedGenre));
        }
        if (selectedYear) {
            movies = movies.filter(movie => movie.year == selectedYear);
        }
        if (selectedRating) {
            movies = movies.filter(movie => movie.contentRating === selectedRating);
        }

        filteredMovies = movies;
        renderMovies();
    };

    const renderMovies = () => {
        movieGrid.innerHTML = '';
        const selectedGenre = genreFilter.value;
        const selectedYear = yearFilter.value;
        const selectedRating = ratingFilter.value;

        let sourceMovies;

        if (selectedGenre || selectedYear || selectedRating) {
            sourceMovies = filteredMovies;
        } else {
            sourceMovies = allMovies;
        }

        const shuffled = sourceMovies.sort(() => 0.5 - Math.random());
        const moviesToRender = shuffled.slice(0, 9);

        moviesToRender.forEach(movie => {
            const movieCard = document.createElement('div');
            movieCard.className = 'movie-card group';
            movieCard.dataset.movieId = movie.id;

            const posterContainer = document.createElement('div');
            posterContainer.className = 'movie-poster-container';

            const poster = document.createElement('img');
            poster.src = movie.poster;
            poster.alt = movie.title;
            poster.className = 'movie-poster';
            posterContainer.appendChild(poster);

            movieCard.appendChild(posterContainer);

            const cardContent = document.createElement('div');
            cardContent.className = 'movie-card-content';

            const watchButton = document.createElement('button');
            watchButton.className = 'watch-button';
            watchButton.textContent = 'Watch';
            watchButton.onclick = (e) => {
                e.stopPropagation();
                showClients(movie);
            };
            cardContent.appendChild(watchButton);
            movieCard.appendChild(cardContent);

            movieCard.addEventListener('click', () => {
                showContextLoadingOverlay('movie');
                openMovieDataOverlay(movie.id);
            });

            movieGrid.appendChild(movieCard);
        });
    };

    const showClients = async (movie) => {
        const response = await fetch('/clients');
        const clients = await response.json();
        const clientPrompt = document.getElementById('client_prompt');
        const clientList = document.getElementById('list_of_clients');
        
        clientList.innerHTML = '';
        if (clients.length === 0) {
            clientList.innerHTML = "<div class='no-clients-message'>No available clients found.</div>";
        } else {
            clients.forEach(client => {
                const clientElement = document.createElement('div');
                clientElement.className = 'client';
                clientElement.textContent = client.title;
                clientElement.dataset.id = client.id;
                clientElement.onclick = () => {
                    playMovie(movie.id, client.id);
                    closeClientPrompt();
                };
                clientList.appendChild(clientElement);
            });
        }

        clientPrompt.classList.remove('hidden');
    };

    const closeClientPrompt = () => {
        const clientPrompt = document.getElementById('client_prompt');
        clientPrompt.classList.add('hidden');
    };

    window.closeClientPrompt = closeClientPrompt;

    const playMovie = async (movieId, clientId) => {
        await fetch(`/play_movie/${clientId}?movie_id=${movieId}`);
    };

    genreFilter.addEventListener('change', filterMovies);
    yearFilter.addEventListener('change', filterMovies);
    ratingFilter.addEventListener('change', filterMovies);

    refreshBtn.addEventListener('click', () => {
        renderMovies();
    });

    fetchMovies();
});
