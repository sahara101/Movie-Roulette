document.addEventListener('DOMContentLoaded', () => {
    const movieGrid = document.getElementById('movie-grid');
    const genreFilter = document.getElementById('genre-filter');
    const yearFilter = document.getElementById('year-filter');
    const ratingFilter = document.getElementById('rating-filter');
    const refreshBtn = document.getElementById('refresh-btn');
    const clearFiltersBtn = document.getElementById('clear-filters-btn');

    let allMovies = [];
    let filteredMovies = [];
    let currentPool = [];

    const fetchMovies = async () => {
        const url = '/all_movies_grid';
        try {
            const response = await fetch(url);
            const data = await response.json();

            if (response.status === 202 && data.status === 'cache_building') {
                document.getElementById('loading-overlay').classList.remove('hidden');
                return;
            }

            if (!response.ok) {
                movieGrid.innerHTML = `<p style="color:rgba(255,255,255,0.5);text-align:center;padding:2rem;">${data.error || 'Failed to load movies.'}</p>`;
                return;
            }

            allMovies = data.movies || [];
            populateFilters();
            renderMovies();
        } catch (error) {
            movieGrid.innerHTML = `<p style="color:rgba(255,255,255,0.5);text-align:center;padding:2rem;">Failed to load movies.</p>`;
        }
    };

    if (typeof socket !== 'undefined') {
        socket.on('loading_progress', (data) => {
            const overlay = document.getElementById('loading-overlay');
            const progressBar = document.getElementById('loading-progress');
            const loadingCount = document.querySelector('.loading-count');
            const loadingStatus = document.querySelector('.loading-status');

            if (overlay) overlay.classList.remove('hidden');
            if (progressBar) progressBar.style.width = `${data.progress * 100}%`;
            if (loadingCount) {
                loadingCount.textContent = data.total === 0 ? 'Initializing...' : `${data.current}/${data.total}`;
            }
            if (loadingStatus) {
                if (data.progress >= 0.95) loadingStatus.textContent = 'Loading into memory';
                else if (data.progress >= 0.90) loadingStatus.textContent = 'Saving cache to disk';
                else loadingStatus.textContent = 'Loading movies';
            }
        });

        socket.on('loading_complete', fetchMovies);
    }

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

    const updateClearVisibility = () => {
        if (!clearFiltersBtn) return;
        const hasActive = genreFilter.value || yearFilter.value || ratingFilter.value;
        clearFiltersBtn.classList.toggle('hidden', !hasActive);
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
        updateClearVisibility();
        renderMovies();
    };

    const createMovieCard = (movie) => {
        const movieCard = document.createElement('div');
        movieCard.className = 'movie-card';
        movieCard.dataset.movieId = movie.id;

        const posterWrap = document.createElement('div');
        posterWrap.className = 'movie-poster-wrap';

        const posterBg = document.createElement('img');
        posterBg.src = movie.poster;
        posterBg.alt = '';
        posterBg.setAttribute('aria-hidden', 'true');
        posterBg.className = 'movie-poster-bg';
        posterWrap.appendChild(posterBg);

        const poster = document.createElement('img');
        poster.src = movie.poster;
        poster.alt = movie.title;
        poster.className = 'movie-poster';
        posterWrap.appendChild(poster);

        const hoverOverlay = document.createElement('div');
        hoverOverlay.className = 'movie-card-hover';

        const watchButton = document.createElement('button');
        watchButton.className = 'watch-button';
        watchButton.textContent = 'Watch';
        watchButton.onclick = (e) => {
            e.stopPropagation();
            showClients(movie);
        };
        hoverOverlay.appendChild(watchButton);
        posterWrap.appendChild(hoverOverlay);
        movieCard.appendChild(posterWrap);

        const info = document.createElement('div');
        info.className = 'movie-card-info';

        const title = document.createElement('div');
        title.className = 'movie-card-title';
        title.textContent = movie.title;
        info.appendChild(title);

        const metaParts = [];
        if (movie.year) metaParts.push(movie.year);
        if (movie.contentRating) metaParts.push(movie.contentRating);
        if (metaParts.length > 0) {
            const meta = document.createElement('div');
            meta.className = 'movie-card-meta';
            meta.textContent = metaParts.join(' · ');
            info.appendChild(meta);
        }

        movieCard.appendChild(info);

        movieCard.addEventListener('click', () => {
            showContextLoadingOverlay('movie');
            openMovieDataOverlay(movie.tmdb_id);
        });

        return movieCard;
    };

    const trimToFit = () => {
        const firstCard = movieGrid.querySelector('.movie-card');
        if (!firstCard) return;

        movieGrid.style.paddingTop = '';
        const columns = getComputedStyle(movieGrid).gridTemplateColumns.split(' ').length;
        const gap = parseFloat(getComputedStyle(movieGrid).rowGap) || 20;
        const cardHeight = firstCard.getBoundingClientRect().height;
        const gridTop = movieGrid.getBoundingClientRect().top;
        const availableHeight = (window.visualViewport?.height ?? window.innerHeight) - gridTop;
        const rows = Math.max(1, Math.floor((availableHeight + gap) / (cardHeight + gap)));

        const usedHeight = rows * cardHeight + (rows - 1) * gap;
        const leftover = availableHeight - usedHeight;
        if (window.innerWidth <= 768 && leftover > 16) {
            const isStandalone = window.matchMedia('(display-mode: standalone)').matches;
            const maxBoost = isStandalone ? 48 : 24;
            movieGrid.style.paddingTop = `${Math.min(maxBoost, Math.floor(leftover * 0.35))}px`;
        }

        const targetCount = Math.min(columns * rows, currentPool.length);

        const cards = movieGrid.querySelectorAll('.movie-card');
        if (cards.length > targetCount) {
            [...cards].slice(targetCount).forEach(el => el.remove());
        } else if (cards.length < targetCount) {
            currentPool.slice(cards.length, targetCount).forEach(movie => {
                movieGrid.appendChild(createMovieCard(movie));
            });
        }
    };

    const renderMovies = () => {
        movieGrid.innerHTML = '';
        const selectedGenre = genreFilter.value;
        const selectedYear = yearFilter.value;
        const selectedRating = ratingFilter.value;

        const sourceMovies = (selectedGenre || selectedYear || selectedRating)
            ? filteredMovies
            : allMovies;

        currentPool = [...sourceMovies].sort(() => 0.5 - Math.random());

        currentPool.slice(0, 40).forEach(movie => {
            movieGrid.appendChild(createMovieCard(movie));
        });

        requestAnimationFrame(trimToFit);
    };

    const showClients = async (movie) => {
        const [clientsResp, webInfoResp] = await Promise.all([
            fetch('/clients'),
            fetch('/api/web_client_info')
        ]);
        const clients = await clientsResp.json();
        const webClientInfo = webInfoResp.ok ? await webInfoResp.json() : null;
        const clientPrompt = document.getElementById('client_prompt');
        const clientList = document.getElementById('list_of_clients');

        clientList.innerHTML = '';
        const validWebClient = webClientInfo && !webClientInfo.error;
        if (clients.length === 0 && !validWebClient) {
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
            if (validWebClient) {
                addWebClientEntry(clientList, webClientInfo, () => {
                    const webId = (webClientInfo.service === 'emby' && movie.emby_internal_id)
                        ? movie.emby_internal_id
                        : movie.id;
                    const url = buildWebClientUrl(webClientInfo, webId);
                    if (url) window.open(url, '_blank');
                    closeClientPrompt();
                });
            }
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

    if (clearFiltersBtn) {
        clearFiltersBtn.addEventListener('click', () => {
            genreFilter.value = '';
            yearFilter.value = '';
            ratingFilter.value = '';
            filteredMovies = [];
            updateClearVisibility();
            renderMovies();
        });
    }

    let resizeTimer;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => requestAnimationFrame(trimToFit), 150);
    });

    fetchMovies();
});
