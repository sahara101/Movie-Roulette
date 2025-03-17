const SORT_OPTIONS = {
    YEAR_DESC: 'year_desc',
    YEAR_ASC: 'year_asc',
    RATING_DESC: 'rating_desc',
    RATING_ASC: 'rating_asc',
    TITLE_ASC: 'title_asc'
};

let currentSort = SORT_OPTIONS.YEAR_DESC;

let lastTraktSync = 0;
let plexFilterMode = 'all'; // 'all', 'inPlex', or 'notInPlex'
const TRAKT_FRONTEND_SYNC_MIN_INTERVAL = 30 * 1000;

let currentFilters = {
    genres: [],
    years: [],
    pgRatings: []
};

let currentSettings = {};
let currentService = 'plex';
let currentMovie = null;
let availableServices = [];
let socket = io({
    transports: ['polling'],
    reconnectionAttempts: 5,
});

// Make functions globally accessible
window.openPersonDetailsOverlay = openPersonDetailsOverlay;
window.closePersonDetailsOverlay = closePersonDetailsOverlay;
window.openMovieDataOverlay = openMovieDataOverlay;

document.addEventListener('DOMContentLoaded', async function() {
    await getAvailableServices();
    await getCurrentService();
    await loadRandomMovie();
    if (!window.HOMEPAGE_MODE) {
        if (window.USE_FILTER) {
            await loadFilterOptions();
            setupFilterEventListeners();
        }
    }
    setupEventListeners();
    checkAndLoadCache();
    try {
        // Check current client configuration
        const response = await fetch('/devices');
        const devices = await response.json();
        const powerButton = document.getElementById("btn_power");
        const nextButton = document.getElementById("btn_next_movie");
        if (powerButton && nextButton) {
            if (devices.length > 0) {
                powerButton.style.display = 'flex';
                nextButton.style.flex = '';
            } else {
                powerButton.style.display = 'none';
                if (window.matchMedia('(max-width: 767px)').matches) {
                    nextButton.style.flex = '0 0 100%';
                    nextButton.style.marginRight = '0';
                }
            }
        }
    } catch (error) {
        console.error("Error checking devices:", error);
        const powerButton = document.getElementById("btn_power");
        const nextButton = document.getElementById("btn_next_movie");
        if (powerButton && nextButton) {
            powerButton.style.display = 'none';
            if (window.matchMedia('(max-width: 767px)').matches) {
                nextButton.style.flex = '0 0 100%';
                nextButton.style.marginRight = '0';
            }
        }
    }
    await syncTraktWatched(false);
    startVersionChecker();

    // Hook into the movie display function to handle collection warnings
    const originalUpdateMovieDisplay = updateMovieDisplay;
    window.updateMovieDisplay = function(movieData) {
        // Call the original function first
        originalUpdateMovieDisplay(movieData);
        // Then handle collection warning
        handleCollectionWarning(movieData);
    };

    // Collection modal close button
    const closeCollectionModal = document.getElementById('collection_modal_close');
    if (closeCollectionModal) {
        closeCollectionModal.addEventListener('click', function() {
            document.getElementById('collection_modal').classList.add('hidden');
        });
    }

    // Click outside to close the collection modal
    const collectionModal = document.getElementById('collection_modal');
    if (collectionModal) {
        collectionModal.addEventListener('click', function(e) {
            if (e.target === collectionModal) {
                collectionModal.classList.add('hidden');
            }
        });
    }
});

document.addEventListener('visibilitychange', function() {
    if (!document.hidden) {
        syncTraktWatched(false);
    }
});

document.getElementById('movies_overlay_close').addEventListener('click', closeMoviesOverlay);

function showLoadingOverlay() {
    document.getElementById('loading-overlay').classList.remove('hidden');
}

function hideLoadingOverlay() {
    document.getElementById('loading-overlay').classList.add('hidden');
}

socket.on('loading_progress', function(data) {
    const overlay = document.getElementById('loading-overlay');
    const progressBar = document.getElementById('loading-progress');
    const loadingCount = document.querySelector('.loading-count');
    const loadingStatus = document.querySelector('.loading-status');

    if (overlay) {
        overlay.classList.remove('hidden');
        window.cacheBuilding = true;
    }

    if (progressBar) {
        progressBar.style.width = `${data.progress * 100}%`;
    }

    if (loadingCount && data.total > 0) {
        loadingCount.textContent = `${data.current}/${data.total}`;
    }

    // Update status text based on progress
    if (loadingStatus) {
        if (data.progress >= 0.95) {
            loadingStatus.textContent = 'Loading into memory';
        } else if (data.progress >= 0.90) {
            loadingStatus.textContent = 'Saving cache to disk';
        } else {
            loadingStatus.textContent = 'Loading movies';
        }
    }
});

socket.on('loading_complete', async function() {
    console.log('Loading complete');
    const overlay = document.getElementById('loading-overlay');
    if (overlay) {
        overlay.classList.add('hidden');
        window.cacheBuilding = false;

        // Load a random movie first
        await loadRandomMovie();

        // Check for updates
        checkVersion(false);

        // Reinitialize filters if needed
        if (!window.HOMEPAGE_MODE && window.USE_FILTER) {
            console.log('Reinitializing filters after cache build');
            await loadFilterOptions();

            const filterButton = document.getElementById("filterButton");
            const filterDropdown = document.getElementById("filterDropdown");

            // Remove existing event listeners
            const newFilterButton = filterButton.cloneNode(true);
            filterButton.parentNode.replaceChild(newFilterButton, filterButton);

            // Re-setup filter event listeners
            newFilterButton.addEventListener('click', function(event) {
                event.stopPropagation();
                filterDropdown.classList.toggle("show");
            });

            document.addEventListener('click', function(event) {
                if (!event.target.matches('.filter-button') && !filterDropdown.contains(event.target)) {
                    filterDropdown.classList.remove("show");
                }
            });

            filterDropdown.addEventListener('click', function(event) {
                event.stopPropagation();
            });

            // Reinitialize other filter-related functionality
            setupFilterEventListeners();
            updateFilters();
        }
    }
});

async function getAvailableServices() {
    try {
        const response = await fetch('/available_services');
        availableServices = await response.json();
	console.log("Available services:", availableServices);
        updateServiceButton();
    } catch (error) {
        console.error("Error getting available services:", error);
    }
}

async function getCurrentService() {
    try {
        const response = await fetch('/current_service');
        const data = await response.json();
        if (data.service !== currentService) {
            currentService = data.service;
            console.log("Service changed to:", currentService);
            await loadFilterOptions();
	    console.log("Current and available services:", {
                current: currentService,
                available: availableServices
            }); // Add debug logging
        }
        updateServiceButton();
    } catch (error) {
        console.error("Error getting current service:", error);
    }
}

async function loadRandomMovie() {
    // Don't try to load if cache is building
    if (window.cacheBuilding) {
        console.log('Cache still building, skipping movie load');
        return;
    }

    try {
        const watchStatusSelect = document.getElementById("watchStatusSelect");
        const watchStatus = watchStatusSelect ? watchStatusSelect.value : 'unwatched';

        const queryParams = new URLSearchParams();
        queryParams.append('watch_status', watchStatus);
        const response = await fetch(`/random_movie?${queryParams}`);

        if (!response.ok) {
            if (response.status === 404) {
                console.log('No movies available yet');
                return;
            }
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        currentMovie = data.movie;
        updateMovieDisplay(data.movie);
    } catch (error) {
        console.error("Error fetching random movie:", error);
    }
}

async function loadFilterOptions() {
    try {
        console.log("Loading filter options for service:", currentService);
	const watchStatus = document.getElementById("watchStatusSelect").value;
	const genresResponse = await fetch(`/get_genres?watch_status=${watchStatus}`);
        const yearsResponse = await fetch(`/get_years?watch_status=${watchStatus}`);
        const pgRatingsResponse = await fetch(`/get_pg_ratings`);

        if (!genresResponse.ok || !yearsResponse.ok || !pgRatingsResponse.ok) {
            throw new Error('Failed to fetch filter options');
        }

        const genres = await genresResponse.json();
        const years = await yearsResponse.json();
        const pgRatings = await pgRatingsResponse.json();

        console.log("Fetched genres:", genres);
        console.log("Fetched years:", years);
        console.log("Fetched PG ratings:", pgRatings);

        populateDropdown('genreSelect', genres);
        populateDropdown('yearSelect', years);
        populateDropdown('pgRatingSelect', pgRatings);
    } catch (error) {
        console.error("Error loading filter options:", error);
    }
}

function populateDropdown(elementId, options) {
    const select = document.getElementById(elementId);
    if (!select) {
        console.error(`Element with id "${elementId}" not found`);
        return;
    }
    console.log(`Populating ${elementId} with options:`, options);
    select.innerHTML = '<option value="">Any</option>';
    options.forEach(option => {
        if (option) {
            const optionElement = document.createElement('option');
            optionElement.value = option;
            optionElement.textContent = option;
            select.appendChild(optionElement);
        }
    });
    console.log(`${elementId} populated with ${select.options.length} options`);
}

function closeSearchModal() {
    document.getElementById('search_modal').classList.add('hidden');
    document.getElementById('movie_search').value = '';
    document.getElementById('search_results').innerHTML = '';
}

function setupEventListeners() {
    if (!window.HOMEPAGE_MODE) {
        if (window.USE_WATCH_BUTTON) {
            const watchButton = document.getElementById("btn_watch");
            if (watchButton) {
                watchButton.addEventListener('click', showClients);
            }
        }

        if (window.USE_NEXT_BUTTON) {
            const nextButton = document.getElementById("btn_next_movie");
            if (nextButton) {
                nextButton.addEventListener('click', loadNextMovie);
            }
        }

        const powerButton = document.getElementById("btn_power");
        if (powerButton) {
            powerButton.addEventListener('click', showDevices);
        }

        const trailerClose = document.getElementById("trailer_popup_close");
        if (trailerClose) {
            trailerClose.addEventListener('click', closeTrailerPopup);
        }

        const switchServiceButton = document.getElementById("switch_service");
        if (switchServiceButton) {
            switchServiceButton.addEventListener('click', switchService);
        }

	const clientPromptClose = document.getElementById('client_prompt_close');
    	if (clientPromptClose) {
            clientPromptClose.addEventListener('click', closeClientPrompt);
    	}

    	const devicePromptClose = document.getElementById('device_prompt_close');
    	if (devicePromptClose) {
            devicePromptClose.addEventListener('click', closeDevicePrompt);
    	}
    }

    document.body.addEventListener('click', async (event) => {
    console.log("Click event target:", event.target);
    console.log("Click event target classes:", event.target.classList);

	// Handle person image clicks
    	if (event.target.closest('.person-image-link')) {
            console.log("Person image link clicked");
            event.preventDefault();
            const link = event.target.closest('.person-image-link');
            const personId = link.dataset.personId;
            const personName = link.dataset.personName;
            console.log("Opening person details:", { personId, personName });
            openPersonDetailsOverlay(personId, personName);
            return;
    	}

    	if (event.target.classList.contains('clickable-person')) {
            const personId = event.target.getAttribute('data-id');
            const personType = event.target.getAttribute('data-type');
            const personName = event.target.textContent;

            if (personId) {
                // If we already have an ID, use it directly
                await openMoviesOverlay(personId, personType, personName);
            } else {
                // If no ID, get it first
                const enrichedPerson = await enrichPersonData(personName, personType);
                if (enrichedPerson.id) {
                    // Set the ID for future use
                    event.target.setAttribute('data-id', enrichedPerson.id);
                    await openMoviesOverlay(enrichedPerson.id, personType, personName);
                }
            }
        }
    });

    const moviesOverlayClose = document.getElementById('movies_overlay_close');
    if (moviesOverlayClose) {
        moviesOverlayClose.addEventListener('click', closeMoviesOverlay);
    }

    const searchButton = document.getElementById('searchButton');
    const searchModal = document.getElementById('search_modal');
    const searchInput = document.getElementById('movie_search');
    const closeSearchBtn = document.getElementById('search_modal_close');

    if (searchButton && searchModal && searchInput && closeSearchBtn) {
    	// Search button click
    	searchButton.addEventListener('click', () => {
            searchModal.classList.remove('hidden');
            searchInput.focus();
    	});

    	// Close button click
    	closeSearchBtn.addEventListener('click', closeSearchModal);

    	// Handle search input with debounce
    	let searchTimeout;
    	searchInput.addEventListener('input', () => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
            	const query = searchInput.value.trim();
            	if (query.length >= 2) { // Only search if 2 or more characters
                    performSearch(query);
            	} else {
                    document.getElementById('search_results').innerHTML = '';
            	}
            }, 300); // 300ms debounce
        });

        // Close on escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !searchModal.classList.contains('hidden')) {
                closeSearchModal();
            }
        });
    }
}

async function performSearch(query) {
    const searchResults = document.getElementById('search_results');
    searchResults.className = '';  // Clear any existing classes
    searchResults.innerHTML = '<div class="loading-indicator">Searching...</div>';

    try {
        const response = await fetch(`/search_movies?query=${encodeURIComponent(query)}`);
        const data = await response.json();

        if (response.status === 404) {
            searchResults.innerHTML = `
                <div class="no-results">
                    <div>No movies found matching "${query}"</div>
                    <div>Try adjusting your search term</div>
                </div>`;
            return;
        }

        if (!response.ok) {
            throw new Error(data.error || 'Search failed');
        }

        if (!data.results || data.results.length === 0) {
            searchResults.innerHTML = `
                <div class="no-results">
                    <div>No movies found matching "${query}"</div>
                    <div>Try adjusting your search term</div>
                </div>`;
            return;
        }

        searchResults.className = 'has-results';
        searchResults.innerHTML = '';

        data.results.forEach(movie => {
            const movieCard = document.createElement('div');
            movieCard.className = 'movie-card';
            movieCard.dataset.movieId = movie.id;

            // Create poster link
            const posterLink = document.createElement('a');
            posterLink.href = '#';
            posterLink.className = 'movie-poster-link';

            // Add poster image
            const poster = document.createElement('img');
            if (movie.poster) {
                poster.src = movie.poster;
                poster.alt = `${movie.title} Poster`;
                poster.className = 'movie-poster';
            } else {
                poster.src = 'https://www.themoviedb.org/assets/2/v4/glyphicons/basic/glyphicons-basic-38-picture-grey-c2ebdbb057f2a7614185931650f8cee23fa137b93812ccb132b9df511df1cfac.svg';
                poster.alt = 'No Poster Available';
                poster.className = 'movie-poster no-poster';
            }
            posterLink.appendChild(poster);

            // Create and add title
            const title = document.createElement('p');
            title.textContent = movie.title;
            if (movie.year) {
                title.textContent += ` (${movie.year})`;
            }

            // Create watch button
            const watchButton = document.createElement('button');
            watchButton.className = 'request-button';
            watchButton.textContent = 'Watch';
	    watchButton.addEventListener('click', () => {
	        showClientsForSelected(movie);
	    });

            // Add event listener to poster link
            posterLink.addEventListener('click', (e) => {
                e.preventDefault();
		currentMovie = {
                    ...movie,
                    actors_enriched: movie.actors_enriched,
                    directors_enriched: movie.directors_enriched,
                    writers_enriched: movie.writers_enriched
                };
                updateMovieDisplay(currentMovie);
                closeSearchModal();
            });

            // Assemble movie card in the correct order
            movieCard.appendChild(posterLink);
            movieCard.appendChild(title);
            movieCard.appendChild(watchButton);
            searchResults.appendChild(movieCard);
        });
    } catch (error) {
        console.error('Search error:', error);
        searchResults.innerHTML = '<div class="search-error">An error occurred while searching. Please try again.</div>';
    }
}

async function showClientsForSelected(selectedMovie) {
    try {
        const response = await fetch(`/clients`);
        const clients = await response.json();

        const listContainer = document.getElementById("list_of_clients");
        listContainer.innerHTML = "";

        if (clients.length === 0) {
	        listContainer.innerHTML = "<div class='no-clients-message'>No available clients found.</div>";
        } else {
            clients.forEach(client => {
                const clientDiv = document.createElement("div");
                clientDiv.classList.add("client");
                clientDiv.textContent = client.title;
                clientDiv.onclick = function() {
                    playSelectedMovie(client.id, selectedMovie.id);  // Pass the selected movie's ID
                    closeClientPrompt();
                };
                listContainer.appendChild(clientDiv);
            });
        }

        document.getElementById("client_prompt").classList.remove("hidden");
    } catch (error) {
        console.error("Error fetching clients:", error);
        alert("Failed to fetch clients. Please try again.");
    }
}

async function playSelectedMovie(clientId, movieId) {
    try {
        const response = await fetch(`/play_movie/${clientId}?movie_id=${movieId}`);
        const data = await response.json();

        if (data.status !== "playing") {
            throw new Error(data.error || "Failed to start playback");
        }

        setTimeout(() => syncTraktWatched(false), 30000);
    } catch (error) {
        console.error("Error playing movie:", error);
        alert("Failed to play movie. Please try again.");
    }
}

function setupFilterEventListeners() {
    console.log('Setting up filter event listeners');
    if (!window.USE_FILTER) {
        console.log('Filters disabled, skipping setup');
        return;
    }

    const filterButton = document.getElementById("filterButton");
    const filterDropdown = document.getElementById("filterDropdown");

    if (filterButton && filterDropdown) {
        console.log('Found filter elements, attaching listeners');

	const watchStatusSelect = document.getElementById("watchStatusSelect");
        if (watchStatusSelect) {
            watchStatusSelect.addEventListener('change', async function() {
                await loadFilterOptions();
            });
        }

        // Remove any existing listeners by cloning and replacing
        const newFilterButton = filterButton.cloneNode(true);
        filterButton.parentNode.replaceChild(newFilterButton, filterButton);

        // Setup filter button click
        newFilterButton.addEventListener('click', function(event) {
            console.log('Filter button clicked');
            event.stopPropagation();
            filterDropdown.classList.toggle("show");
        });

        // Setup document click to close dropdown
        document.addEventListener('click', function(event) {
            if (!event.target.matches('.filter-button') && !filterDropdown.contains(event.target)) {
                filterDropdown.classList.remove("show");
            }
        });

        // Prevent dropdown clicks from closing
        filterDropdown.addEventListener('click', function(event) {
            event.stopPropagation();
        });

        // Setup apply filter button
        const applyFilterBtn = document.getElementById("applyFilter");
        if (applyFilterBtn) {
            applyFilterBtn.addEventListener('click', applyFilter);
        } else {
            console.log('Apply filter button not found');
        }

        // Setup clear filter button
        const clearFilterBtn = document.getElementById("clearFilter");
        if (clearFilterBtn) {
            clearFilterBtn.addEventListener('click', clearFilter);
        } else {
            console.log('Clear filter button not found');
        }

        updateFilters();
        console.log('Filter event listeners setup complete');
    } else {
        console.log('Could not find filter elements', {
            filterButton: !!filterButton,
            filterDropdown: !!filterDropdown
        });
    }
}

async function applyFilter() {
    currentFilters.genres = Array.from(document.getElementById("genreSelect").selectedOptions).map(option => option.value);
    currentFilters.years = Array.from(document.getElementById("yearSelect").selectedOptions).map(option => option.value);
    currentFilters.pgRatings = Array.from(document.getElementById("pgRatingSelect").selectedOptions).map(option => option.value);
    currentFilters.watchStatus = document.getElementById("watchStatusSelect").value || 'unwatched';

    await fetchFilteredMovies();
    await loadFilterOptions();
}

async function fetchFilteredMovies() {
    try {
        const queryParams = new URLSearchParams();
        if (currentFilters.genres.length) queryParams.append('genres', currentFilters.genres.join(','));
        if (currentFilters.years.length) queryParams.append('years', currentFilters.years.join(','));
        if (currentFilters.pgRatings.length) queryParams.append('pg_ratings', currentFilters.pgRatings.join(','));
	queryParams.append('watch_status', currentFilters.watchStatus);

        const response = await fetch(`/filter_movies?${queryParams}`);

        if (response.status === 204) {
            showNoMoviesMessage();
            return;
        }

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        console.log("Filtered movie from service:", data.service);
        currentMovie = data.movie;
        await updateMovieDisplay(data.movie);
        document.getElementById("filterDropdown").classList.remove("show");
    } catch (error) {
        console.error("Error applying filter:", error);
        showErrorMessage(error.message);
    }
}

function clearFilter() {
    document.getElementById("genreSelect").selectedIndex = -1;
    document.getElementById("yearSelect").selectedIndex = -1;
    document.getElementById("pgRatingSelect").selectedIndex = -1;
    document.getElementById("watchStatusSelect").value = "unwatched";
    currentFilters = {
        genres: [],
        years: [],
        pgRatings: [],
	watchStatus: 'unwatched'
    };
    traktFilterMode = 'unwatched';
    plexFilterMode = 'all';
    updateFilters();
    hideMessage();
    loadRandomMovie();
    document.getElementById("filterDropdown").classList.remove("show");
}

async function loadNextMovie() {
    try {
        const watchStatusSelect = document.getElementById("watchStatusSelect");
        const watchStatus = watchStatusSelect ? watchStatusSelect.value : 'unwatched';

        const queryParams = new URLSearchParams();
        if (currentFilters.genres.length) queryParams.append('genres', currentFilters.genres.join(','));
        if (currentFilters.years.length) queryParams.append('years', currentFilters.years.join(','));
        if (currentFilters.pgRatings.length) queryParams.append('pg_ratings', currentFilters.pgRatings.join(','));
        queryParams.append('watch_status', watchStatus);

        const url = `/next_movie?${queryParams}`;
        console.log("Requesting next movie with URL:", url);
        const response = await fetch(url);

        if (response.status === 204) {
            showNoMoviesMessage();
            return;
        }
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        console.log("Loaded next movie from service:", data.service);
        currentMovie = data.movie;
        updateMovieDisplay(data.movie);
    } catch (error) {
        console.error("Error fetching next movie:", error);
        showErrorMessage(error.message);
    }
}

function showMessage() {
    document.getElementById("movieContent").classList.add("hidden");
    document.getElementById("messageContainer").classList.remove("hidden");
}

function hideMessage() {
    document.getElementById("movieContent").classList.remove("hidden");
    document.getElementById("messageContainer").classList.add("hidden");
}

function showNoMoviesMessage() {
    const messageContainer = document.getElementById("messageContainer");
    messageContainer.innerHTML = `
        <div class="no-movies-message">
            <h2>No Movies Found</h2>
            <p>Sorry, we couldn't find any movies matching your current filters.</p>
            <button onclick="clearFilter()" class="button">Clear Filters</button>
        </div>
    `;
    showMessage();
}

function showErrorMessage(message) {
    const messageContainer = document.getElementById("messageContainer");
    messageContainer.innerHTML = `
        <div class="error-message">
            <h2>Oops! Something went wrong</h2>
            <p>${message}</p>
            <button onclick="clearFilter()" class="button">Clear Filters and Try Again</button>
        </div>
    `;
    showMessage();
}

function updateMovieDisplay(movieData) {
    if (!movieData) {
        console.error("No movie data to display");
        return;
    }

//    console.log('Movie data received:', movieData);

    hideMessage();

    const elements = {
        "title": document.getElementById("title"),
        "year_duration": document.getElementById("year_duration"),
        "directors": document.getElementById("directors"),
        "writers": document.getElementById("writers"),
        "actors": document.getElementById("actors"),
        "genres": document.getElementById("genres"),
        "description": document.getElementById("description"),
        "poster_img": document.getElementById("poster_img"),
        "img_background": document.getElementById("img_background"),
    };

    if (!window.HOMEPAGE_MODE && window.USE_LINKS) {
        elements["tmdb_link"] = document.getElementById("tmdb_link");
        elements["trakt_link"] = document.getElementById("trakt_link");
        elements["imdb_link"] = document.getElementById("imdb_link");
        elements["trailer_link"] = document.getElementById("trailer_link");
    }

    for (const [key, element] of Object.entries(elements)) {
        if (!element) {
            console.warn(`Element with id "${key}" not found`);
            continue;
        }

        switch (key) {
            case "title":
                element.textContent = movieData.title;
                break;

            case "year_duration":
                let yearDurationText = `${movieData.year} | ${movieData.duration_hours}h ${movieData.duration_minutes}m`;
                if (movieData.contentRating) {
                    yearDurationText += ` | ${movieData.contentRating}`;
                }
                element.textContent = yearDurationText;
                break;

	    case "directors":
    		if (movieData.directors_enriched && movieData.directors_enriched.length > 0) {
        	    const mainDirectors = movieData.directors_enriched.slice(0, 3);
        	    const remainingCount = movieData.directors_enriched.length - 3;

        	    const directorLinks = mainDirectors.map(director => {
            		if (window.HOMEPAGE_MODE) {
                	    return director.name;
            		}
            		return `<span class="clickable-person" data-id="${director.id || ''}" data-type="director">${director.name}</span>`;
        	    }).join(', ');

        	    element.innerHTML = `Directing: ${directorLinks}${
            	    	remainingCount > 0 ?
            		window.HOMEPAGE_MODE ?
			    '' :
			    ` <span class="more-directors">and ${remainingCount} more</span>` :
            		''
        	    }`;

        	    if (!window.HOMEPAGE_MODE && remainingCount > 0) {
            		const moreDirectors = element.querySelector('.more-directors');
            		if (moreDirectors) {
                	    moreDirectors.style.cursor = 'pointer';
                	    moreDirectors.addEventListener('click', (e) => {
                    		e.stopPropagation();
                    		showAllDirectors(movieData.directors_enriched);
                	    });
            		}
       		    }
    		} else {
        	    element.textContent = 'Directors: Not available';
    	 	}
    	    break;

	    case "writers":
    		if (movieData.writers_enriched && movieData.writers_enriched.length > 0) {
        	    const mainWriters = movieData.writers_enriched.slice(0, 3);
        	    const remainingCount = movieData.writers_enriched.length - 3;

        	    const writerLinks = mainWriters.map(writer => {
            	    	if (window.HOMEPAGE_MODE) {
			    return writer.name;
            		}
			return `<span class="clickable-person" data-id="${writer.id || ''}" data-type="writer">${writer.name}</span>`;
        	    }).join(', ');

        	    element.innerHTML = `Writing: ${writerLinks}${
            		remainingCount > 0 ?
            		window.HOMEPAGE_MODE ?
			    '' :
			    ` <span class="more-writers">and ${remainingCount} more</span>` :
            		''
        	    }`;

        	    if (!window.HOMEPAGE_MODE && remainingCount > 0) {
            		const moreWriters = element.querySelector('.more-writers');
            		if (moreWriters) {
                	    moreWriters.style.cursor = 'pointer';
                	    moreWriters.addEventListener('click', (e) => {
                    		e.stopPropagation();
                    		showAllWriters(movieData.writers_enriched);
                	    });
            		}
        	    }
    	     } else {
        	element.textContent = 'Writers: Not available';
    	    }
    	    break;

            case "actors":
                if (movieData.actors_enriched && movieData.actors_enriched.length > 0) {
                    console.log('Processing actors for', movieData.title);
                    const mainActors = movieData.actors_enriched.slice(0, 3);
                    const remainingCount = movieData.actors_enriched.length - 3;

                    console.log('Total actors:', movieData.actors_enriched.length);
                    console.log('Main actors:', mainActors);
                    console.log('Remaining count:', remainingCount);

		    const actorLinks = mainActors.map(actor => {
			if (window.HOMEPAGE_MODE) {
                	    return actor.name;
			}

                        return `<span class="clickable-person" data-id="${actor.id || ''}" data-type="actor">${actor.name}</span>`;
                    }).join(', ');

                    element.innerHTML = `Cast: ${actorLinks}${
                        remainingCount > 0 ?
			window.HOMEPAGE_MODE ?
			    '' :
			    ` <span class="more-actors">and ${remainingCount} more</span>` :
			''
                    }`;

		    if (!window.HOMEPAGE_MODE && remainingCount > 0) {
                        const moreActors = element.querySelector('.more-actors');
                        if (moreActors) {
                            moreActors.style.cursor = 'pointer';
                            moreActors.addEventListener('click', (e) => {
                                e.stopPropagation();
                                showAllActors(movieData.actors_enriched);
                            });
                        }
                    }
                } else {
                    element.textContent = 'Cast: No cast information available';
                }
                break;

            case "genres":
                element.textContent = `Genres: ${movieData.genres.join(", ")}`;
                break;

	    case "description":
    		element.textContent = movieData.description;
    		requestAnimationFrame(() => {
        	    setupDescriptionExpander();
    		});
    	    break;

            case "poster_img":
                element.src = movieData.poster;
                break;

            case "img_background":
                element.style.backgroundImage = `url(${movieData.background})`;
                break;
        }
    }

    if (!window.HOMEPAGE_MODE && window.USE_LINKS) {
        if (elements["tmdb_link"]) elements["tmdb_link"].href = movieData.tmdb_url;
        if (elements["trakt_link"]) elements["trakt_link"].href = movieData.trakt_url;
        if (elements["imdb_link"]) elements["imdb_link"].href = movieData.imdb_url;

        if (elements["trailer_link"]) {
            if (movieData.trailer_url) {
                elements["trailer_link"].style.display = "block";
                elements["trailer_link"].onclick = function() {
                    document.getElementById("trailer_iframe").src = movieData.trailer_url;
                    document.getElementById("trailer_popup").classList.remove("hidden");
                };
            } else {
                elements["trailer_link"].style.display = "none";
            }
        }
    }

    document.getElementById("section").classList.remove("hidden");
    setupDescriptionExpander();
    window.dispatchEvent(new Event('resize'));
}

function handleCollectionWarning(movieData) {
    // Get the collection button
    const collectionButton = document.getElementById('collectionButton');

    // Reset any existing collection warnings
    const existingWarning = document.querySelector('.collection-warning');
    if (existingWarning) {
        existingWarning.remove();
    }

    // If no collection info, hide button and exit
    if (!movieData.collection_info || !movieData.collection_info.is_in_collection) {
        collectionButton.classList.add('hidden');
        return;
    }

    const previousMovies = movieData.collection_info.previous_movies || [];
    const otherMovies = movieData.collection_info.other_movies || [];

    // Filter for unwatched previous movies
    const unwatchedMovies = previousMovies.filter(movie => !movie.is_watched);

    // Filter for other movies not in library
    const requestableOtherMovies = otherMovies.filter(movie => !movie.in_library);

    // Show button if there are ANY unwatched previous movies OR requestable other movies
    if (unwatchedMovies.length === 0 && requestableOtherMovies.length === 0) {
        collectionButton.classList.add('hidden');
        return;
    }

    // Show the collection button
    collectionButton.classList.remove('hidden');

    // Update badge count to show total number of interesting movies
    const badge = collectionButton.querySelector('.badge');
    if (badge) {
        badge.textContent = unwatchedMovies.length + requestableOtherMovies.length;
    }

    // Set collection data and click handler
    collectionButton.dataset.collectionName = movieData.collection_info.collection_name;
    collectionButton.dataset.collectionId = movieData.collection_info.collection_id;
    collectionButton.onclick = function() {
        showCollectionModal(movieData.collection_info, unwatchedMovies, otherMovies);
    };
}

async function showCollectionModal(collectionInfo, unwatchedMovies, otherMovies) {
    const modalContainer = document.getElementById('collection_modal');
    const infoContainer = document.getElementById('collection_info_container');

    // Check if a request service is available
    const requestServiceStatus = await checkRequestServiceAvailability();
    const isRequestServiceAvailable = requestServiceStatus.available;

    // Get request service name if available
    let requestServiceName = "";
    if (isRequestServiceAvailable) {
        switch(requestServiceStatus.service) {
            case 'overseerr':
                requestServiceName = "Overseerr";
                break;
            case 'jellyseerr':
                requestServiceName = "Jellyseerr";
                break;
            case 'ombi':
                requestServiceName = "Ombi";
                break;
            default:
                requestServiceName = requestServiceStatus.service || "";
        }
    }

    // Count movies that need requesting (not in library and not already requested)
    const moviesToRequest = [
        ...unwatchedMovies.filter(movie => !movie.in_library && !movie.is_requested),
        ...(otherMovies ? otherMovies.filter(movie => !movie.in_library && !movie.is_requested) : [])
    ];

    // Create the modal content
    infoContainer.innerHTML = `
        <div class="collection-info-header">
            <h3>Part of ${collectionInfo.collection_name}</h3>
        </div>
        <div class="unwatched-movies">
            <p>You have ${unwatchedMovies.length} unwatched previous movie${unwatchedMovies.length > 1 ? 's' : ''} in this collection.</p>
            <ul class="movie-list">
                ${unwatchedMovies.map(movie => {
                    const year = movie.release_date ? ` (${movie.release_date.substring(0, 4)})` : '';

                    // Properly formatted ternary operator for status class
                    const statusClass = movie.in_library ? 'status-in-library' :
                                      (movie.is_requested ? 'status-requested' : 'status-not-in-library');

                    // Properly formatted ternary operator for status text
                    const statusText = movie.in_library ? 'In library' :
                                     (movie.is_requested ? 'Requested' : 'Not in library');

                    return `
                        <li class="movie-item">
                            <span class="movie-title">${movie.title}${year}</span>
                            <span class="movie-status ${statusClass}">${statusText}</span>
                        </li>
                    `;
                }).join('')}
            </ul>
        </div>
        ${otherMovies && otherMovies.length > 0 ? `
            <div class="other-movies">
                <h4>Other movies in this collection:</h4>
                <ul class="movie-list">
                    ${otherMovies.map(movie => {
                        const year = movie.release_date ? ` (${movie.release_date.substring(0, 4)})` : '';

                        // Same corrected format for other movies section
                        const statusClass = movie.in_library ? 'status-in-library' :
                                          (movie.is_requested ? 'status-requested' : 'status-not-in-library');
                        const statusText = movie.in_library ? 'In library' :
                                         (movie.is_requested ? 'Requested' : 'Not in library');

                        return `
                            <li class="movie-item">
                                <span class="movie-title">${movie.title}${year}</span>
                                <span class="movie-status ${statusClass}">${statusText}</span>
                            </li>
                        `;
                    }).join('')}
                </ul>
            </div>
        ` : ''}
        <div class="action-buttons">
            ${unwatchedMovies.some(movie => movie.in_library) ?
                `<button class="action-button watch-button" id="watch_collection_movie">Watch Previous Movie</button>` : ''}
            ${moviesToRequest.length > 0 ?
                `<button class="action-button request-button${!isRequestServiceAvailable ? ' disabled' : ''}"
                     id="request_collection_movies"
                     ${!isRequestServiceAvailable ? 'disabled' : ''}
                     title="${isRequestServiceAvailable ?
                        `Request using ${requestServiceName}` :
                        currentService === 'plex' ?
                            'No request service available' :
                            'Appropriate request service not configured'}">
                    Request Missing Movies
                 </button>` : ''}
            <button class="action-button dismiss-button" id="dismiss_collection">Dismiss</button>
        </div>
    `;

    // Show the modal
    modalContainer.classList.remove('hidden');

    // Add event listeners for the buttons
    const dismissButton = document.getElementById('dismiss_collection');
    if (dismissButton) {
        dismissButton.addEventListener('click', () => {
            modalContainer.classList.add('hidden');
        });
    }

    const watchButton = document.getElementById('watch_collection_movie');
    if (watchButton) {
        watchButton.addEventListener('click', () => {
            // Get the first unwatched movie that's in the library
            const movieToWatch = unwatchedMovies.find(movie => movie.in_library);
            if (movieToWatch && typeof showClientsForPoster === 'function') {
                showClientsForPoster(movieToWatch.id);
                modalContainer.classList.add('hidden');
            }
        });
    }

    // Only add request button listener if request service is available
    const requestButton = document.getElementById('request_collection_movies');
    if (requestButton && isRequestServiceAvailable) {
        requestButton.addEventListener('click', () => {
            if (moviesToRequest.length > 0 && typeof requestPreviousMovies === 'function') {
                requestPreviousMovies(moviesToRequest);
                modalContainer.classList.add('hidden');
            }
        });
    }

    // Close button event listener
    document.getElementById('collection_modal_close').addEventListener('click', () => {
        modalContainer.classList.add('hidden');
    });
}

async function requestPreviousMovies(movies) {
    if (!movies || movies.length === 0) return;

    try {
        // Show confirmation dialog if there are multiple movies
        if (movies.length > 1) {
            // Create styled confirmation dialog instead of using browser confirm()
            const confirmDialog = document.createElement('div');
            confirmDialog.className = 'trakt-confirm-dialog'; // Reuse existing dialog style
            confirmDialog.innerHTML = `
                <div class="dialog-content">
                    <h3>Request Multiple Movies</h3>
                    <p>Are you sure you want to request ${movies.length} movies from this collection?</p>
                    <div class="dialog-buttons">
                        <button class="cancel-button">Cancel</button>
                        <button class="submit-button">Request Movies</button>
                    </div>
                </div>
            `;
            document.body.appendChild(confirmDialog);

            // Create a promise that will be resolved when the user makes a choice
            return new Promise((resolve) => {
                // Handle cancel button
                const cancelButton = confirmDialog.querySelector('.cancel-button');
                cancelButton.addEventListener('click', () => {
                    confirmDialog.remove();
                    resolve(false);
                });

                // Handle submit/confirm button
                const submitButton = confirmDialog.querySelector('.submit-button');
                submitButton.addEventListener('click', async () => {
                    confirmDialog.remove();

                    // Now continue with the request process
                    // No loading overlay, just process the requests

                    let successCount = 0;
                    for (const movie of movies) {
                        try {
                            await requestMovie(movie.id, false); // Don't show individual notifications
                            successCount++;
                        } catch (error) {
                            console.error(`Error requesting movie ${movie.title}:`, error);
                        }
                    }

                    // Show a single summary notification
                    if (successCount > 0) {
                        showToast(`Successfully requested ${successCount} movie${successCount > 1 ? 's' : ''}!`, 'success');

                        // Remove or update the collection warning
                        const existingWarning = document.querySelector('.collection-warning');
                        if (existingWarning) {
                            existingWarning.remove();
                        }
                    } else {
                        showToast('Failed to request movies. Please try again.', 'error');
                    }

                    resolve(true);
                });

                // Handle click outside dialog to cancel
                confirmDialog.addEventListener('click', (e) => {
                    if (e.target === confirmDialog) {
                        confirmDialog.remove();
                        resolve(false);
                    }
                });
            });
        } else {
            // Single movie, no confirmation needed
            try {
                await requestMovie(movies[0].id, true); // Use the regular notification for single movie

                // Remove or update the collection warning
                const existingWarning = document.querySelector('.collection-warning');
                if (existingWarning) {
                    existingWarning.remove();
                }
            } catch (error) {
                // Error handling already done in requestMovie function
                console.error(`Error requesting movie: ${error.message}`);
            }
        }
    } catch (error) {
        showToast(`Error: ${error.message}`, 'error');
    }
}

async function checkRequestServiceAvailability() {
    try {
        const response = await fetch('/api/overseerr/status');
        const data = await response.json();

        // If Overseerr is selected but we're not using Plex, don't allow it
        if (data.service === 'overseerr' && currentService !== 'plex') {
            return { available: false, service: null };
        }

        return {
            available: data.available,
            service: data.service  // Will be either 'overseerr', 'jellyseerr', or 'ombi'
        };
    } catch (error) {
        console.error('Error checking request service status:', error);
        return { available: false, service: null };
    }
}

async function enrichPersonData(personName, personType) {
    try {
        // Try to get TMDb ID for the person
        const response = await fetch(`/api/search_person?name=${encodeURIComponent(personName)}`);
        if (response.ok) {
            const person = await response.json();
            if (person && person.id) {
                console.log(`Found TMDb ID ${person.id} for ${personName}`);
                return {
                    id: person.id,
                    name: personName,
                    type: personType
                };
            }
        }
        return {
            id: null,
            name: personName,
            type: personType
        };
    } catch (e) {
        console.error(`Error enriching person data for ${personName}:`, e);
        return {
            id: null,
            name: personName,
            type: personType
        };
    }
}

async function handlePersonClick(e) {
    const name = e.target.textContent;
    const type = e.target.getAttribute('data-type') || 'actor';

    // Only do enrichment if we don't already have an ID
    if (!e.target.getAttribute('data-id')) {
        const enrichedPerson = await enrichPersonData(name, type);
        if (enrichedPerson.id) {
            e.target.setAttribute('data-id', enrichedPerson.id);
            await openMoviesOverlay(enrichedPerson.id, type, name);
        }
    } else {
        await openMoviesOverlay(e.target.getAttribute('data-id'), type, name);
    }
}

function showAllActors(actors) {
    showContextLoadingOverlay('cast');
    const tmdbId = currentMovie.tmdb_id;
    const castDialog = document.querySelector('.cast-dialog');
    const wasCastDialogVisible = castDialog !== null;

    fetch(`/api/movie_details/${tmdbId}`)
        .then(response => response.json())
        .then(data => {
            hideLoadingOverlay();
            const enrichedCast = data.credits.cast;
            const dialog = document.createElement('div');
            dialog.className = 'cast-dialog';

            dialog.innerHTML = `
                <div class="cast-dialog-content">
                    <button class="close-button" aria-label="Close dialog">
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
                            <path d="M24 20.188l-8.315-8.209 8.2-8.282-3.697-3.697-8.212 8.318-8.31-8.203-3.666 3.666 8.312 8.203-8.204 8.278 3.684 3.684 8.215-8.316 8.311 8.202z" />
                        </svg>
                    </button>
                    <h3>Cast</h3>
                    <input type="text"
                           class="cast-search"
                           placeholder="Search by actor name or character...">
                    <div class="cast-list">
                        ${enrichedCast.map(actor => `
                            <div class="cast-item"
                                 data-actor="${actor.name.toLowerCase()}"
                                 data-character="${(actor.character || '').toLowerCase()}"
                                 data-person-id="${actor.id}"
                                 data-person-type="actor"
                                 data-person-name="${actor.name}">
                                <img src="https://image.tmdb.org/t/p/w185${actor.profile_path}"
                                     alt="${actor.name}"
                                     class="actor-image"
                                     onerror="this.onerror=null; this.src='data:image/svg+xml;charset=utf-8,<svg viewBox=\\'0 0 100 100\\' xmlns=\\'http://www.w3.org/2000/svg\\'%3E%3Ccircle cx=\\'50\\' cy=\\'40\\' r=\\'20\\' fill=\\'%23E5A00D\\'/%3E%3Cpath d=\\'M50 65 C 30 65, 20 80, 20 100 L 80 100 C 80 80, 70 65, 50 65 Z\\' fill=\\'%23E5A00D\\'/%3E%3C/svg%3E';">
                                <div class="actor-info">
                                    <div class="actor-name">${actor.name}</div>
                                    ${actor.character ?
                                        `<div class="actor-character">as ${actor.character}</div>`
                                        : ''}
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;

            dialog.querySelectorAll('.cast-item').forEach(item => {
                item.addEventListener('click', async () => {
                    const personId = item.dataset.personId;
                    const personType = item.dataset.personType;
                    const personName = item.dataset.personName;
                    const existingDialog = document.querySelector('.cast-dialog');
                    if (existingDialog) {
                        existingDialog.style.display = 'none';
                    }
                    await openMoviesOverlay(personId, personType, personName);
                });
            });

            const closeMoviesHandler = () => {
                document.getElementById('movies_overlay').classList.add('hidden');
                if (existingDialog) {
                    existingDialog.style.display = 'flex';
                }
            };

            document.body.appendChild(dialog);

            dialog.querySelector('.close-button').addEventListener('click', () => {
                dialog.remove();
            });

            addSearchFunctionality(dialog);
        })
        .catch(error => {
            hideLoadingOverlay();
            console.error('Error loading cast details:', error);
        });
}

function showAllDirectors(directors) {
   showContextLoadingOverlay('directors');
   const tmdbId = currentMovie.tmdb_id;
   const castDialog = document.querySelector('.cast-dialog');
   const wasCastDialogVisible = castDialog !== null;

   fetch(`/api/movie_details/${tmdbId}`)
       .then(response => response.json())
       .then(data => {
           hideLoadingOverlay('directors');

           const directorsMap = new Map();
           const enrichedDirectors = data.credits.crew.filter(person =>
               person.department === 'Directing'
           );

           enrichedDirectors.forEach(director => {
               const key = director.id || director.name;
               if (directorsMap.has(key)) {
                   const existingDirector = directorsMap.get(key);
                   if (!existingDirector.jobs.includes(director.job)) {
                       existingDirector.jobs.push(director.job);
                   }
               } else {
                   directorsMap.set(key, {
                       ...director,
                       jobs: [director.job]
                   });
               }
           });

           const uniqueDirectors = Array.from(directorsMap.values());
           const dialog = document.createElement('div');
           dialog.className = 'cast-dialog';

           dialog.innerHTML = `
               <div class="cast-dialog-content">
                   <button class="close-button" aria-label="Close dialog">
                       <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
                           <path d="M24 20.188l-8.315-8.209 8.2-8.282-3.697-3.697-8.212 8.318-8.31-8.203-3.666 3.666 8.312 8.203-8.204 8.278 3.684 3.684 8.215-8.316 8.311 8.202z" />
                       </svg>
                   </button>
                   <h3>Directing</h3>
                   <input type="text"
                          class="cast-search"
                          placeholder="Search directors...">
                   <div class="cast-list">
                       ${uniqueDirectors.sort((a,b) => a.name.localeCompare(b.name)).map(director => `
                           <div class="cast-item"
                                data-director="${director.name.toLowerCase()}"
                                data-person-id="${director.id}"
                                data-person-type="director"
                                data-person-name="${director.name}">
                               <img src="${director.profile_path ?
                                   `https://image.tmdb.org/t/p/w185${director.profile_path}` :
                                   "data:image/svg+xml;charset=utf-8,%3Csvg viewBox='0 0 100 100' xmlns='http://www.w3.org/2000/svg'%3E%3Ccircle cx='50' cy='40' r='20' fill='%23E5A00D'/%3E%3Cpath d='M50 65 C 30 65, 20 80, 20 100 L 80 100 C 80 80, 70 65, 50 65 Z' fill='%23E5A00D'/%3E%3C/svg%3E"}"
                                    alt="${director.name}"
                                    class="actor-image"
                                    onerror="this.onerror=null; this.src='data:image/svg+xml;charset=utf-8,%3Csvg viewBox=\\'0 0 100 100\\' xmlns=\\'http://www.w3.org/2000/svg\\'%3E%3Ccircle cx=\\'50\\' cy=\\'40\\' r=\\'20\\' fill=\\'%23E5A00D\\'/%3E%3Cpath d=\\'M50 65 C 30 65, 20 80, 20 100 L 80 100 C 80 80, 70 65, 50 65 Z\\' fill=\\'%23E5A00D\\'/%3E%3C/svg%3E'">
                               <div class="actor-info">
                                   <div class="actor-name">${director.name}</div>
                                   <div class="actor-character">${director.jobs.join(', ')}</div>
                               </div>
                           </div>
                       `).join('')}
                   </div>
               </div>
           `;

           dialog.querySelectorAll('.cast-item').forEach(item => {
                item.addEventListener('click', async () => {
                    const personId = item.dataset.personId;
                    const personType = item.dataset.personType;
                    const personName = item.dataset.personName;
                    const existingDialog = document.querySelector('.cast-dialog');
                    if (existingDialog) {
                        existingDialog.style.display = 'none';
                    }
                    await openMoviesOverlay(personId, personType, personName);
                });
           });

           const closeMoviesHandler = () => {
               document.getElementById('movies_overlay').classList.add('hidden');
               if (existingDialog) {
                   existingDialog.style.display = 'flex';
               }
           };

           document.body.appendChild(dialog);

           dialog.querySelector('.close-button').addEventListener('click', () => {
               dialog.remove();
           });

           addSearchFunctionality(dialog);
           hideLoadingOverlay();
       })
       .catch(error => {
           console.error('Error loading directors:', error);
           hideLoadingOverlay();
       });
}

function showAllWriters(writers) {
   showContextLoadingOverlay('writers');
   const tmdbId = currentMovie.tmdb_id;
   const castDialog = document.querySelector('.cast-dialog');
   const wasCastDialogVisible = castDialog !== null;

   fetch(`/api/movie_details/${tmdbId}`)
       .then(response => response.json())
       .then(data => {
           hideLoadingOverlay('writers');

           const writersMap = new Map();
           const enrichedWriters = data.credits.crew.filter(person =>
               person.department === 'Writing'
           );

           enrichedWriters.forEach(writer => {
               const key = writer.id || writer.name;
               if (writersMap.has(key)) {
                   const existingWriter = writersMap.get(key);
                   if (!existingWriter.jobs.includes(writer.job)) {
                       existingWriter.jobs.push(writer.job);
                   }
               } else {
                   writersMap.set(key, {
                       ...writer,
                       jobs: [writer.job]
                   });
               }
           });

           const uniqueWriters = Array.from(writersMap.values());
           const dialog = document.createElement('div');
           dialog.className = 'cast-dialog';

           dialog.innerHTML = `
               <div class="cast-dialog-content">
                   <button class="close-button" aria-label="Close dialog">
                       <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
                           <path d="M24 20.188l-8.315-8.209 8.2-8.282-3.697-3.697-8.212 8.318-8.31-8.203-3.666 3.666 8.312 8.203-8.204 8.278 3.684 3.684 8.215-8.316 8.311 8.202z" />
                       </svg>
                   </button>
                   <h3>Writing</h3>
                   <input type="text"
                          class="cast-search"
                          placeholder="Search writers...">
                   <div class="cast-list">
                       ${uniqueWriters.sort((a,b) => a.name.localeCompare(b.name)).map(writer => `
                           <div class="cast-item"
                                data-writer="${writer.name.toLowerCase()}"
                                data-person-id="${writer.id}"
                                data-person-type="writer"
                                data-person-name="${writer.name}">
                               <img src="${writer.profile_path ?
                                   `https://image.tmdb.org/t/p/w185${writer.profile_path}` :
                                   "data:image/svg+xml;charset=utf-8,%3Csvg viewBox='0 0 100 100' xmlns='http://www.w3.org/2000/svg'%3E%3Ccircle cx='50' cy='40' r='20' fill='%23E5A00D'/%3E%3Cpath d='M50 65 C 30 65, 20 80, 20 100 L 80 100 C 80 80, 70 65, 50 65 Z' fill='%23E5A00D'/%3E%3C/svg%3E"}"
                                    alt="${writer.name}"
                                    class="actor-image"
                                    onerror="this.onerror=null; this.src='data:image/svg+xml;charset=utf-8,%3Csvg viewBox=\\'0 0 100 100\\' xmlns=\\'http://www.w3.org/2000/svg\\'%3E%3Ccircle cx=\\'50\\' cy=\\'40\\' r=\\'20\\' fill=\\'%23E5A00D\\'/%3E%3Cpath d=\\'M50 65 C 30 65, 20 80, 20 100 L 80 100 C 80 80, 70 65, 50 65 Z\\' fill=\\'%23E5A00D\\'/%3E%3C/svg%3E'">
                               <div class="actor-info">
                                   <div class="actor-name">${writer.name}</div>
                                   <div class="actor-character">${writer.jobs.join(', ')}</div>
                               </div>
                           </div>
                       `).join('')}
                   </div>
               </div>
           `;

           dialog.querySelectorAll('.cast-item').forEach(item => {
                item.addEventListener('click', async () => {
                    const personId = item.dataset.personId;
                    const personType = item.dataset.personType;
                    const personName = item.dataset.personName;
                    const existingDialog = document.querySelector('.cast-dialog');
                    if (existingDialog) {
                        existingDialog.style.display = 'none';
                    }
                    await openMoviesOverlay(personId, personType, personName);
                });
           });

           const closeMoviesHandler = () => {
               document.getElementById('movies_overlay').classList.add('hidden');
               if (existingDialog) {
                   existingDialog.style.display = 'flex';
               }
           };

           document.body.appendChild(dialog);

           dialog.querySelector('.close-button').addEventListener('click', () => {
               dialog.remove();
           });

           addSearchFunctionality(dialog);
           hideLoadingOverlay();
       })
       .catch(error => {
           console.error('Error loading writers:', error);
           hideLoadingOverlay();
       });
}

function addSearchFunctionality(dialog) {
    const searchInput = dialog.querySelector('.cast-search');
    searchInput.addEventListener('input', (e) => {
        const searchTerm = e.target.value.toLowerCase();
        const castItems = dialog.querySelectorAll('.cast-item');
        let hasVisibleItems = false;

        castItems.forEach(item => {
            const personName = item.dataset.actor || item.dataset.director || item.dataset.writer || '';
            const characterInfo = item.dataset.character || item.querySelector('.actor-character')?.textContent || '';
            const isMatch = personName.includes(searchTerm) || characterInfo.toLowerCase().includes(searchTerm);

            item.style.display = isMatch ? 'flex' : 'none';
            if (isMatch) hasVisibleItems = true;
        });

        const existingNoResults = dialog.querySelector('.no-results');
        if (!hasVisibleItems && !existingNoResults) {
            const noResults = document.createElement('div');
            noResults.className = 'no-results';
            noResults.textContent = 'No matching results found';
            dialog.querySelector('.cast-list').appendChild(noResults);
        } else if (hasVisibleItems && existingNoResults) {
            existingNoResults.remove();
        }
    });
}

class ExpandableText {
    constructor(elementId) {
        this.elementId = elementId;
        this.boundToggle = this.toggle.bind(this);
        this.state = {
            expanded: false,
            truncated: false
        };
    }

    init() {
        this.element = document.getElementById(this.elementId);
        if (!this.element) return;

        this.reset();
        this.checkTruncation();
        this.bindEvents();
    }

    reset() {
    	if (!this.element) return;
    	this.element.removeEventListener('click', this.boundToggle);
    	this.element.classList.remove('truncated', 'expanded');

    	// Check for mobile and truncation setting
    	const isMobileOrPWA = window.matchMedia('(max-width: 767px)').matches;
    	if (isMobileOrPWA) {
            // On mobile, respect the MOBILE_TRUNCATION setting
            if (window.MOBILE_TRUNCATION) {
            	this.element.style.webkitLineClamp = '1';
            	this.element.style.display = '-webkit-box';
            } else {
            	this.element.style.webkitLineClamp = 'unset';
            	this.element.style.display = 'block';
            }
    	} else {
            // On desktop, always use truncation
            this.element.style.webkitLineClamp = '1';
            this.element.style.display = '-webkit-box';
    	}

    	this.element.style.maxHeight = '';
    	this.element.style.cursor = 'default';
    	this.state.expanded = false;
    }

    checkTruncation() {
    	if (!this.element) return;

    	requestAnimationFrame(() => {
            void this.element.offsetHeight;

            const isMobileOrPWA = window.matchMedia('(max-width: 767px)').matches;

            // If on mobile and truncation is disabled, don't truncate
            if (isMobileOrPWA && !window.MOBILE_TRUNCATION) {
            	this.state.truncated = false;
            	this.element.classList.remove('truncated');
            	this.element.style.cursor = 'default';
            	return;
            }

            const truncated = this.element.scrollHeight > this.element.clientHeight;
            this.state.truncated = truncated;

            if (truncated) {
            	this.element.classList.add('truncated');
            	this.element.style.cursor = 'pointer';
            }
    	});
    }

    bindEvents() {
        if (!this.element) return;
        this.element.addEventListener('click', this.boundToggle);
    }

    checkTruncation() {
    	if (!this.element) return;

    	requestAnimationFrame(() => {
            void this.element.offsetHeight;

            // Add check for mobile and truncation setting
            const isMobileOrPWA = window.matchMedia('(max-width: 768px)').matches || window.navigator.standalone;
            const shouldTruncate = !isMobileOrPWA || window.MOBILE_TRUNCATION;

            const truncated = shouldTruncate && this.element.scrollHeight > this.element.clientHeight;
            this.state.truncated = truncated;

            if (truncated) {
            	this.element.classList.add('truncated');
            	this.element.style.cursor = 'pointer';
            }

            console.log('Truncation check:', {
            	scrollHeight: this.element.scrollHeight,
            	clientHeight: this.element.clientHeight,
            	isTruncated: truncated,
            	isMobile: isMobileOrPWA,
            	truncationEnabled: window.MOBILE_TRUNCATION,
            	text: this.element.textContent.substring(0, 50) + '...'
            });
    	});
    }

    toggle(e) {
        if (e) e.stopPropagation();
        if (!this.state.truncated || !this.element) return;

        this.state.expanded = !this.state.expanded;

        if (this.state.expanded) {
            this.element.classList.add('expanded');
            this.element.style.webkitLineClamp = 'unset';
            this.element.style.maxHeight = 'none';
        } else {
            this.element.classList.remove('expanded');
            this.element.style.webkitLineClamp = '1';
            this.element.style.maxHeight = '';
        }
    }

    refresh() {
        this.init();
    }
}

let descriptionExpander = null;

function setupDescriptionExpander() {
    if (!descriptionExpander) {
        descriptionExpander = new ExpandableText('description');
    }
    if (!window.HOMEPAGE_MODE) {
        descriptionExpander.init();
    }
}

function renderClickablePersons(persons) {
    console.log('Rendering clickable persons:', persons);
    if (!persons || persons.length === 0) {
        console.warn('No persons data to render');
        return '';
    }
    return persons.map(person => {
        if (person.id) {
            return `<span class="clickable-person" data-id="${person.id}" data-type="${person.type}">${person.name}</span>`;
        } else {
            return `<span>${person.name}</span>`;
        }
    }).join(", ");
}

async function renderMovies(movies) {
    const moviesContainer = document.getElementById('movies_container');
    moviesContainer.innerHTML = '';

    if (movies.length === 0) {
        moviesContainer.innerHTML = `<p>No movies found.</p>`;
    } else {
        const movieCards = await Promise.all(
            movies.map(movie => {
                if (movie.media_type === 'movie') {
                    return createMovieCard(movie);
                }
            })
        );

        movieCards.filter(card => card).forEach(card => {
            moviesContainer.appendChild(card);
        });

        // Update counts AFTER the movies are rendered
        await updateFilterCounts();

        // Then apply filters
        applyAllFilters();
    }
}

function closePersonDetailsOverlay() {
    const overlay = document.getElementById('person_details_overlay');
    if (overlay) {
        overlay.classList.remove('visible');
        overlay.classList.add('hidden');
    }
}

async function openPersonDetailsOverlay(personId, personName) {
    try {
        // Store current state of movies overlay
        const moviesOverlay = document.getElementById('movies_overlay');
        const wasMoviesOverlayVisible = !moviesOverlay.classList.contains('hidden');

        // Get full person details and external IDs
        const response = await fetch(`/api/person_details_with_external_ids/${personId}`);
        if (!response.ok) {
            throw new Error(`Failed to fetch person details: ${response.status}`);
        }
        const person = await response.json();

        const overlay = document.getElementById('person_details_overlay');

        overlay.innerHTML = `
            <div class="person-details-content">
                <button class="close-button" onclick="closePersonDetailsOverlay()">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
                        <path d="M24 20.188l-8.315-8.209 8.2-8.282-3.697-3.697-8.212 8.318-8.31-8.203-3.666 3.666 8.312 8.203-8.204 8.278 3.684 3.684 8.215-8.316 8.311 8.202z" />
                    </svg>
                </button>
                <div class="person-details-header">
                    ${person.profile_path ?
                        `<img src="https://image.tmdb.org/t/p/w185${person.profile_path}"
                             alt="${person.name}"
                             class="person-details-image">` :
                        `<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" class="person-details-image">
                             <circle cx="50" cy="50" r="48.5" fill="#3A3C41" stroke="#E5A00D" stroke-width="3"/>
                             <circle cx="50" cy="40" r="18" fill="#E5A00D"/>
                             <path d="M50 65 C 30 65, 20 80, 20 100 L 80 100 C 80 80, 70 65, 50 65 Z" fill="#E5A00D"/>
                         </svg>`}
                    <div class="person-details-info">
                        <h2>${person.name}</h2>
                        ${person.known_for_department ? `<p class="person-role">${person.known_for_department}</p>` : ''}
                    </div>
                </div>
                <div class="movie-links">
                    <a href="https://www.themoviedb.org/person/${person.id}" target="_blank">TMDb</a>
                    ${person.imdb_id ? `<a href="https://www.imdb.com/name/${person.imdb_id}" target="_blank">IMDb</a>` : ''}
                </div>
                ${person.biography ?
                    `<p class="person-biography">${person.biography}</p>` :
                    '<p class="person-biography">No biography available.</p>'}
            </div>
        `;

        overlay.classList.remove('hidden');
        overlay.classList.add('visible');

        // If movies overlay was visible, keep it visible
        if (wasMoviesOverlayVisible) {
            moviesOverlay.classList.remove('hidden');
        }

    } catch (error) {
        console.error('Error opening person details:', error);
    }
}

async function createMovieCard(movie) {
    const movieCard = document.createElement('div');
    movieCard.classList.add('movie-card');
    movieCard.dataset.movieId = movie.id;
    movieCard.dataset.year = movie.release_date?.substring(0, 4) || '0';
    movieCard.dataset.rating = movie.vote_average || '0';

    // Create poster container
    const posterLink = document.createElement('a');
    posterLink.href = '#';
    posterLink.classList.add('movie-poster-link');
    posterLink.addEventListener('click', async (e) => {
        e.preventDefault();
        console.log('Poster clicked, movieId:', movie.id);
        console.log('About to show loading overlay');
        showContextLoadingOverlay('movie');
        console.log('Loading overlay shown');
        try {
            console.log('Starting to open movie details');
            await openMovieDataOverlay(movie.id);
            console.log('Movie details opened successfully');
        } catch (error) {
            console.error('Error opening movie details:', error);
            hideLoadingOverlay();
        }
    });

    // Check if movie is in library and add badge if it is
    let isInLibrary = false;
    if (currentService === 'plex') {
        isInLibrary = await isMovieInPlex(movie.id);
    } else if (currentService === 'jellyfin') {
        isInLibrary = await isMovieInJellyfin(movie.id);
    } else if (currentService === 'emby') {
        isInLibrary = await isMovieInEmby(movie.id);
    }

    if (isInLibrary) {
        const badge = document.createElement('div');
        badge.classList.add(`${currentService}-badge`);
        badge.textContent = currentService.toUpperCase();
        posterLink.appendChild(badge);
    }

    // Add poster image or placeholder
    if (movie.poster_path) {
        const poster = document.createElement('img');
        poster.src = `https://image.tmdb.org/t/p/w200${movie.poster_path}`;
        poster.alt = `${movie.title} Poster`;
        poster.classList.add('movie-poster');
        posterLink.appendChild(poster);
    } else {
        const poster = document.createElement('img');
        poster.src = 'https://www.themoviedb.org/assets/2/v4/glyphicons/basic/glyphicons-basic-38-picture-grey-c2ebdbb057f2a7614185931650f8cee23fa137b93812ccb132b9df511df1cfac.svg';
        poster.alt = `${movie.title} Poster`;
        poster.classList.add('movie-poster', 'no-poster');
        poster.style.width = '80px';
        poster.style.margin = 'auto';
        poster.style.display = 'block';
        posterLink.appendChild(poster);
    }

    // Create info container for title and character/job 
    const infoContainer = document.createElement('div');
    infoContainer.className = 'movie-info';

    // Add movie title
    const movieTitle = document.createElement('p');
    movieTitle.className = 'movie-title';
    movieTitle.textContent = movie.title;
    infoContainer.appendChild(movieTitle);

    const characterInfo = document.createElement('p');
    characterInfo.className = 'movie-character';

    // Add character or job info if available
    if (movie.character) {
    	let characterText = movie.character;
    	characterText = characterText.replace(/\n/g, ' ').trim();
    	characterInfo.textContent = `as ${characterText}`;
    } else if (movie.job) {
    	let jobText = movie.job;
    	jobText = jobText.replace(/\n/g, ' ').trim();
    	characterInfo.textContent = jobText;
    } else {
    	characterInfo.innerHTML = '&nbsp;'; // Non-breaking space
    	characterInfo.style.visibility = 'hidden'; // Hide but keep the space
    }

    infoContainer.appendChild(characterInfo);

    // Create request/watch button
    const requestButton = document.createElement('button');
    requestButton.classList.add('request-button');
    requestButton.dataset.movieId = movie.id;

    if (isInLibrary) {
        requestButton.textContent = "Watch";
        requestButton.addEventListener('click', () => showClientsForPoster(movie.id));
    } else {
        const serviceStatus = await checkRequestServiceAvailability();
        if (serviceStatus.available) {
            const mediaStatus = await fetch(`/api/overseerr/media/${movie.id}`).then(r => r.json());
            console.log('Media status:', mediaStatus);
            const isRequested = mediaStatus?.mediaInfo?.status === 3 || mediaStatus?.mediaInfo?.status === 4;

            if (isRequested) {
                requestButton.textContent = "Requested";
                requestButton.classList.add('requested');
                requestButton.disabled = true;
            } else {
                // Use the proper service name
                let serviceName = '';
                switch(serviceStatus.service) {
                    case 'overseerr':
                        serviceName = 'Overseerr';
                        break;
                    case 'jellyseerr':
                        serviceName = 'Jellyseerr';
                        break;
                    case 'ombi':
                        serviceName = 'Ombi';
                        break;
                }
                requestButton.textContent = `Request (${serviceName})`;
                requestButton.addEventListener('click', () => requestMovie(movie.id));
            }
        } else {
            requestButton.textContent = "Request";
            requestButton.disabled = true;
            if (currentService === 'jellyfin' || currentService === 'emby') {
                requestButton.title = "Jellyseerr/Ombi is not configured";
            } else if (currentService === 'plex') {
                requestButton.title = "No request service available";
            }
        }
    }

    // Assemble the movie card
    movieCard.appendChild(posterLink);
    movieCard.appendChild(infoContainer);
    movieCard.appendChild(requestButton);

    return movieCard;
}

async function openMoviesOverlay(personId, personType, personName) {
    console.log("Opening movies overlay");
    showContextLoadingOverlay('person');
    try {
        const response = await fetch(`/api/movies_by_person?person_id=${personId}&person_type=${personType}`);
        if (!response.ok) {
            throw new Error(`Failed to fetch movies: ${response.status} ${response.statusText}`);
        }
        const personData = await response.json();

	console.log("Person Data received:", personData);
        if (personData.credits && personData.credits.crew) {
            console.log("Crew entries:", personData.credits.crew.map(movie => ({
                title: movie.title,
                department: movie.department,
                job: movie.job
            })));
        }

        // Clear the existing overlay content first
        const overlayContent = document.getElementById('movies_overlay_content');
        overlayContent.innerHTML = `
            <button id="movies_overlay_close" class="close-button" aria-label="Close overlay">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
                    <path d="M24 20.188l-8.315-8.209 8.2-8.282-3.697-3.697-8.212 8.318-8.31-8.203-3.666 3.666 8.312 8.203-8.204 8.278 3.684 3.684 8.215-8.316 8.311 8.202z" />
                </svg>
            </button>
            <div id="person_header">
                ${personData.profile_path
                    ? `<a href="#" class="person-image-link" data-person-id="${personId}" data-person-name="${personName}">
                         <img src="https://image.tmdb.org/t/p/w185${personData.profile_path}"
                              alt="${personName}"
                              class="person-image">
                       </a>`
                    : `<a href="#" class="person-image-link" data-person-id="${personId}" data-person-name="${personName}">
                         <svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" class="person-image">
                           <circle cx="50" cy="50" r="48.5" fill="#3A3C41" stroke="#E5A00D" stroke-width="3"/>
                           <circle cx="50" cy="40" r="18" fill="#E5A00D"/>
                           <path d="M50 65 C 30 65, 20 80, 20 100 L 80 100 C 80 80, 70 65, 50 65 Z" fill="#E5A00D"/>
                         </svg>
                       </a>`}
                <h2>${personName}</h2>
            </div>
            <div id="sort_and_filter"></div>
            <div id="movies_container"></div>
        `;

        // Set up the close button event listener
        const closeButton = document.getElementById('movies_overlay_close');
        if (closeButton) {
            closeButton.addEventListener('click', closeMoviesOverlay);
        }

        // Set up sort controls and filters
        const sortAndFilter = document.getElementById('sort_and_filter');
        sortAndFilter.appendChild(createSortControls());
        await setupFilters();
        setupMovieSearch();

        // Filter and render movies
        const moviesContainer = document.getElementById('movies_container');
	const movies = Array.from(
    	    personData.credits[personType === 'actor' ? 'cast' : 'crew']
    	    .filter(movie =>
        	personType === 'actor' ||
        	(personType === 'writer' && movie.department === 'Writing') ||
		(personType === 'director' && movie.department === 'Directing') ||
        	movie.job.toLowerCase() === personType
    	    )
    	    .reduce((map, movie) => {
        	const key = movie.id;
        	if (!map.has(key)) {
            	    map.set(key, { ...movie, jobs: [] });
        	}
        	if (movie.job) {
            	    map.get(key).jobs.push(movie.job);
        	}
                return map;
    	    }, new Map())
	).map(([_, movie]) => ({
    	    ...movie,
    	    job: movie.jobs.join(', ')
	}));

        await renderMovies(movies);
        sortMovies();

        // Show the overlay
        document.getElementById('movies_overlay').classList.remove("hidden");
    } catch (error) {
        console.error('Error in openMoviesOverlay:', error);
        alert(error.message);
    } finally {
        hideLoadingOverlay();
    }
}

async function openMovieDataOverlay(movieId) {
    console.log('openMovieDataOverlay started for movieId:', movieId);
    try {
        const [movieResponse, plexAvailable, requestServiceStatus, mediaStatus] = await Promise.all([
            fetch(`/api/movie_details/${movieId}`),
            fetch(`/is_movie_in_plex/${movieId}`).then(r => r.json()),
            checkRequestServiceAvailability(),
            fetch(`/api/overseerr/media/${movieId}`).then(r => r.json()).catch(() => null)
        ]);

        console.log('Media status in overlay:', mediaStatus);

        if (!movieResponse.ok) {
            throw new Error(`Failed to fetch movie details: ${movieResponse.status} ${movieResponse.statusText}`);
        }

        const movieData = await movieResponse.json();
        const isInPlex = plexAvailable.available;
        const isRequested = mediaStatus?.mediaInfo?.status === 3 || mediaStatus?.mediaInfo?.status === 4;

        const overlayContent = document.getElementById('movie_data_overlay_content');
        overlayContent.innerHTML = `
            <button id="movie_data_overlay_close" class="close-button" aria-label="Close overlay">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
                    <path d="M24 20.188l-8.315-8.209 8.2-8.282-3.697-3.697-8.212 8.318-8.31-8.203-3.666 3.666 8.312 8.203-8.204 8.278 3.684 3.684 8.215-8.316 8.311 8.202z" />
                </svg>
            </button>
            <h2>${movieData.title}</h2>
            <p><span class="movie-data-label">Year:</span><span class="movie-data-value">${movieData.year}</span></p>
            <p><span class="movie-data-label">Duration:</span><span class="movie-data-value">${movieData.duration_hours}h ${movieData.duration_minutes}m</span></p>
            <p><span class="movie-data-label">Rating:</span><span class="movie-data-value">${movieData.contentRating}</span></p>
            <p><span class="movie-data-label">Genres:</span><span class="movie-data-value">${movieData.genres.join(', ')}</span></p>
            <p><span class="movie-data-label">TMDb Rating:</span><span class="movie-data-value">${movieData.tmdb_rating.toFixed(1)}/10</span></p>
            <p><span class="movie-data-label">Trakt Rating:</span><span class="movie-data-value">${Math.round(movieData.trakt_rating)}%</span></p>
            <p><span class="movie-data-label">Description:</span><span class="movie-data-value">${movieData.description}</span></p>
            <div class="movie-links">
                <a href="${movieData.tmdb_url}" target="_blank">TMDb</a>
                <a href="${movieData.trakt_url}" target="_blank">Trakt</a>
                <a href="${movieData.imdb_url}" target="_blank">IMDb</a>
            </div>`;

        // Create action button based on movie status
        if (isInPlex) {
            const watchButton = document.createElement('button');
            watchButton.id = 'watch_movie_button';
            watchButton.className = 'action-button';
            watchButton.textContent = 'Watch Movie';
            watchButton.addEventListener('click', () => showClientsForPoster(movieId));
            overlayContent.appendChild(watchButton);
        } else if (requestServiceStatus.available) {
            const requestButton = document.createElement('button');
	    requestButton.className = 'action-button request-button';
	    requestButton.dataset.movieId = movieId;
            if (isRequested) {
                requestButton.textContent = 'Requested';
                requestButton.disabled = true;
                requestButton.classList.add('requested');
	    } else {
                requestButton.id = 'request_movie_button';
                requestButton.dataset.movieId = movieId;  // Add data attribute
		let serviceName;
                switch(requestServiceStatus.service) {
                    case 'overseerr':
                        serviceName = 'Overseerr';
                        break;
                    case 'jellyseerr':
                        serviceName = 'Jellyseerr';
                        break;
                    case 'ombi':
                        serviceName = 'Ombi';
                        break;
                    default:
                        serviceName = requestServiceStatus.service;
                }
                requestButton.textContent = `Request (${serviceName})`;
		requestButton.addEventListener('click', (e) => {
                    e.preventDefault();
                    requestMovie(movieId);
                });
            }
            overlayContent.appendChild(requestButton);
        } else {
            const disabledButton = document.createElement('button');
            disabledButton.className = 'action-button';
            disabledButton.textContent = 'Request Movie';
            disabledButton.disabled = true;
            disabledButton.title = 'No request service available';
	    if (currentService === 'jellyfin') {
                disabledButton.title = "Jellyseerr is not configured";
            } else {
                disabledButton.title = "No request service available";
            }
            overlayContent.appendChild(disabledButton);
        }

        // Add trailer container
        const trailerContainer = document.createElement('div');
        trailerContainer.id = 'trailer_container';
        overlayContent.appendChild(trailerContainer);

        document.getElementById('movie_data_overlay_close').addEventListener('click', closeMovieDataOverlay);

        // Load and display the trailer
        const trailerUrl = await getYoutubeTrailer(movieData.title, movieData.year);
        if (trailerUrl !== "Trailer not found on YouTube.") {
            trailerContainer.innerHTML = `<iframe width="560" height="315" src="${trailerUrl}" frameborder="0" allowfullscreen></iframe>`;
        } else {
            trailerContainer.innerHTML = "<p>No trailer available</p>";
        }

        document.getElementById('movie_data_overlay').classList.remove("hidden");
    } catch (error) {
        console.error('Error in openMovieDataOverlay:', error);
        throw error;
    } finally {
        hideLoadingOverlay();
    }
}

function closeMovieDataOverlay() {
    document.getElementById('movie_data_overlay').classList.add('hidden');
}

async function getYoutubeTrailer(title, year) {
    const response = await fetch(`/api/youtube_trailer?title=${encodeURIComponent(title)}&year=${year}`);
    if (response.ok) {
        return await response.text();
    } else {
        console.error('Failed to fetch YouTube trailer');
        return "Trailer not found on YouTube.";
    }
}

function closeMoviesOverlay() {
    const moviesOverlay = document.getElementById('movies_overlay');
    const existingDialog = document.querySelector('.cast-dialog');

    if (moviesOverlay) {
        moviesOverlay.classList.add('hidden');
    }

    if (existingDialog) {
        existingDialog.style.display = 'flex';
    }
}

async function requestMovie(movieId, showNotification = true) {
    try {
        // Find all request buttons for this movie
        const requestButtons = document.querySelectorAll(`.request-button[data-movie-id="${movieId}"]`);
        console.log(`Found ${requestButtons.length} request buttons for movie ${movieId}`);

        // Update buttons to requesting state
        requestButtons.forEach(button => {
            button.disabled = true;
            button.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Requesting...';
        });

        const tokenResponse = await fetch('/api/get_overseerr_csrf', {
            method: 'GET',
            credentials: 'include'
        });

        if (!tokenResponse.ok) {
            throw new Error('Failed to get CSRF token');
        }

        const { token } = await tokenResponse.json();

        const requestResponse = await fetch('/api/request_movie', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': token
            },
            body: JSON.stringify({ movie_id: movieId }),
            credentials: 'include'
        });

        if (!requestResponse.ok) {
            const errorData = await requestResponse.json();
            throw new Error(errorData.error || "Failed to request movie.");
        }

        // Update all instances of the request button for this movie
        requestButtons.forEach(button => {
            button.innerHTML = 'Requested';
            button.classList.add('requested');
            button.disabled = true;
        });

        // Only show toast notification if specifically requested
        if (showNotification) {
            showToast('Movie requested successfully!', 'success');
        }

        return true;
    } catch (error) {
        console.error("Error requesting movie:", error);

        // Only show toast notification if specifically requested
        if (showNotification) {
            showToast(error.message, 'error');
        }

        // Restore button states on error
        const requestButtons = document.querySelectorAll(`.request-button[data-movie-id="${movieId}"]`);
        requestButtons.forEach(button => {
            button.disabled = false;
            const serviceName = button.textContent.match(/Request \((.*?)\)/)?.[1] || '';
            button.innerHTML = serviceName ? `Request (${serviceName})` : 'Request';
        });

        throw error;
    }
}

async function showClients() {
    try {
        document.getElementById("btn_watch").disabled = true;
        const response = await fetch(`/clients`);
        const clients = await response.json();

        const listContainer = document.getElementById("list_of_clients");
        listContainer.innerHTML = "";

        if (clients.length === 0) {
	        listContainer.innerHTML = "<div class='no-clients-message'>No available clients found.</div>";
        } else {
            clients.forEach(client => {
                const clientDiv = document.createElement("div");
                clientDiv.classList.add("client");
                clientDiv.textContent = client.title;
                clientDiv.onclick = function() {
                    playMovie(client.id);  // Use playMovie directly
                    closeClientPrompt();
                };
                listContainer.appendChild(clientDiv);
            });
        }

        document.getElementById("client_prompt").classList.remove("hidden");
    } catch (error) {
        console.error("Error fetching clients:", error);
        alert("Failed to fetch clients. Please try again.");
    } finally {
        document.getElementById("btn_watch").disabled = false;
    }
}

async function playMovie(clientId) {
    try {
        const playButton = document.getElementById("btn_watch");
        playButton.disabled = true;

        const response = await fetch(`/play_movie/${clientId}?movie_id=${currentMovie.id}`);
        const data = await response.json();
        console.log("Response from play_movie API:", data);

        if (data.status !== "playing") {
            throw new Error(data.error || "Failed to start playback");
        }

        setTimeout(() => syncTraktWatched(false), 30000);

    } catch (error) {
        console.error("Error playing movie:", error);
        alert("Failed to play movie. Please try again.");
    } finally {
        const playButton = document.getElementById("btn_watch");
        playButton.disabled = false;
    }
}

async function getPlexIdFromTmdbId(tmdbId) {
    try {
        const response = await fetch(`/api/get_plex_id/${tmdbId}`);
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.error || 'Failed to get Plex ID');
        }
        return data.plexId;
    } catch (error) {
        console.error('Error getting Plex ID:', error);
        return null;
    }
}

async function playMovieFromPoster(clientId, tmdbId) {
    try {
        const movieCard = document.querySelector(`.movie-card[data-movie-id="${tmdbId}"]`);
        let serviceId;
        let apiEndpoint;

        // Determine correct endpoint based on service
        switch(currentService) {
            case 'plex':
                apiEndpoint = '/api/get_plex_id/';
                break;
            case 'jellyfin':
                apiEndpoint = '/api/get_jellyfin_id/';
                break;
            case 'emby':
                apiEndpoint = '/api/get_emby_id/';
                break;
            default:
                throw new Error(`Unknown service: ${currentService}`);
        }

        // First try to get stored ID from card
        if (movieCard?.dataset[`${currentService}Id`]) {
            serviceId = movieCard.dataset[`${currentService}Id`];
        } else {
            // Fallback to API call if not stored
            const response = await fetch(`${apiEndpoint}${tmdbId}`);
            if (!response.ok) {
                throw new Error(`Failed to get ${currentService} ID`);
            }
            const data = await response.json();
            serviceId = data[`${currentService}Id`] || data.mediaId; // Handle different response formats

            // Store ID in dataset for future use
            if (movieCard && serviceId) {
                movieCard.dataset[`${currentService}Id`] = serviceId;
            }
        }

        if (!serviceId) {
            throw new Error(`Movie not found in ${currentService}`);
        }

        const playResponse = await fetch(`/play_movie/${clientId}?movie_id=${serviceId}`);
        const playData = await playResponse.json();

        if (playData.status !== "playing") {
            throw new Error(playData.error || "Failed to start playback");
        }

        // Update Trakt after successful playback start
        setTimeout(() => syncTraktWatched(false), 30000);

    } catch (error) {
        console.error("Error playing movie:", error);
        showToast(`Failed to play movie: ${error.message}`, "error");
    }
}

async function showClientsForPoster(movieId) {
    try {
        const response = await fetch(`/clients`);
        const clients = await response.json();

        const listContainer = document.getElementById("list_of_clients");
        listContainer.innerHTML = "";

        if (clients.length === 0) {
	        listContainer.innerHTML = "<div class='no-clients-message'>No available clients found.</div>";
        } else {
            clients.forEach(client => {
                const clientDiv = document.createElement("div");
                clientDiv.classList.add("client");
                clientDiv.textContent = client.title;
                clientDiv.onclick = function() {
                    playMovieFromPoster(client.id, movieId);
                    closeClientPrompt();
                };
                listContainer.appendChild(clientDiv);
            });
        }

        document.getElementById("client_prompt").classList.remove("hidden");
    } catch (error) {
        console.error("Error fetching clients:", error);
        alert("Failed to fetch clients. Please try again.");
    }
}

async function showDevices() {
    try {
        const response = await fetch('/devices');
        const devices = await response.json();

        const listContainer = document.getElementById("list_of_devices");
        listContainer.innerHTML = "";

        devices.forEach(device => {
            const deviceDiv = document.createElement("div");
            deviceDiv.classList.add("device");
            deviceDiv.textContent = device.displayName;
            deviceDiv.onclick = function() {
                turnOnDevice(device.name);
                closeDevicePrompt();
            };
            listContainer.appendChild(deviceDiv);
        });

        document.getElementById("device_prompt").classList.remove("hidden");
    } catch (error) {
        console.error("Error fetching devices:", error);
    }
}

async function turnOnDevice(deviceName) {
    try {
        const response = await fetch(`/turn_on_device/${deviceName}`);
        const data = await response.json();
        console.log("Response from turn_on_device API:", data);
    } catch (error) {
        console.error("Error turning on device:", error);
    }
}

function closeClientPrompt() {
    document.getElementById("client_prompt").classList.add("hidden");
}

function closeDevicePrompt() {
    document.getElementById("device_prompt").classList.add("hidden");
}

function closeTrailerPopup() {
    document.getElementById("trailer_iframe").src = "";
    document.getElementById("trailer_popup").classList.add("hidden");
}

function updateServiceButton() {
    if (window.HOMEPAGE_MODE) return;

    const switchButton = document.getElementById("switch_service");
    if (switchButton) {
        if (availableServices.length > 1) {
            const currentIndex = availableServices.indexOf(currentService);
            const nextService = availableServices.find((service, index) =>
                index > currentIndex && service !== currentService
            ) || availableServices[0];

            const serviceNames = {
                'plex': 'Plex',
                'jellyfin': 'Jellyfin',
                'emby': 'Emby'
            };

            // Restructured HTML for better centering
            switchButton.innerHTML = `
                <div class="service-info">
                    <span class="service-name">${serviceNames[currentService]}</span>
                    <span class="service-count">${currentIndex + 1}/${availableServices.length}</span>
                </div>
                <svg class="switch-icon" width="24" height="24" viewBox="0 0 24 24">
                    <path d="M12 4l-1.41 1.41L16.17 11H4v2h12.17l-5.58 5.59L12 20l8-8z"/>
                </svg>
            `;
            switchButton.style.display = 'flex';
        } else {
            switchButton.style.display = 'none';
        }
    }
}

async function switchService() {
    if (window.HOMEPAGE_MODE) return;

    if (availableServices.length > 1) {
        try {
            const response = await fetch('/switch_service');
            const data = await response.json();
            if (data.service && data.service !== currentService) {
                currentService = data.service;
                console.log("Switched to service:", currentService);
                updateServiceButton();
                await loadRandomMovie();
                await loadFilterOptions();
            }
        } catch (error) {
            console.error("Error switching service:", error);
            showError("Failed to switch service"); // Add error message to user
            // Revert button state to show correct next service
            updateServiceButton();
        }
    }
}

socket.on('movie_added', function(data) {
    console.log('New movie added:', data.movie);
});

socket.on('movie_removed', function(data) {
    console.log('Movie removed:', data.id);
});

async function refreshMovieCache() {
    // First check if this is Plex service
    try {
        const serviceResponse = await fetch('/current_service');
        const serviceData = await serviceResponse.json();

        // Only show loading and build cache for Plex
        if (serviceData.service === 'plex') {
            showLoadingOverlay();
            try {
                const response = await fetch('/start_loading');
                const data = await response.json();
                console.log(data.status);
                await new Promise((resolve) => {
                    socket.once('loading_complete', resolve);
                });
                // After cache is complete, reinitialize services
                await fetch('/api/reinitialize_services');
                await loadRandomMovie();
            } catch (error) {
                console.error('Error refreshing movie cache:', error);
            } finally {
                hideLoadingOverlay();
            }
        } else {
            // For non-Plex services, just reinitialize
            await fetch('/api/reinitialize_services');
            await loadRandomMovie();
        }
    } catch (error) {
        console.error('Error checking service:', error);
    }
}

function handleError(error) {
    console.error('An error occurred:', error);
    alert('An error occurred. Please try again or refresh the page.');
    hideLoadingOverlay();
}

async function checkAndLoadCache() {
    try {
        const response = await fetch('/debug_service');
        const data = await response.json();

        // Only check cache for Plex service
        if (data.service === 'plex' && data.cached_movies === 0) {
            console.log('Plex cache is empty. Starting to load movies...');

            // First remove existing event listeners to prevent duplicates
            const filterButton = document.getElementById("filterButton");
            if (filterButton) {
                const newFilterButton = filterButton.cloneNode(true);
                filterButton.parentNode.replaceChild(newFilterButton, filterButton);
            }

            await refreshMovieCache();

            // Re-initialize everything after cache is built
            console.log('Reinitializing after cache build');
            await loadFilterOptions();
            setupFilterEventListeners();
            setupEventListeners();
        }
    } catch (error) {
        console.error('Error checking cache:', error);
    }
}

let traktFilterMode = 'all'; // 'all', 'watched', or 'unwatched'
let watchedMovies = [];

function updateFilters() {
    // Check if we're in the main view by looking for filterButton
    const filterButton = document.getElementById("filterButton");
    if (!filterButton) {
        // We're not in the main filter view, skip this
        return;
    }

    const plexFilter = document.getElementById('plexFilter');
    if (!plexFilter) {
        console.log('Main app filter initialization - skipping Plex filter');
        return;
    }

    // Rest of your existing updateFilters code for the main app
    plexFilter.innerHTML = `
        <div class="filter-section">
            <label>
                <input type="radio" name="plex" value="all" ${plexFilterMode === 'all' ? 'checked' : ''}>
                All Movies
            </label>
            <label>
                <input type="radio" name="plex" value="inPlex" ${plexFilterMode === 'inPlex' ? 'checked' : ''}>
                In Library
            </label>
            <label>
                <input type="radio" name="plex" value="notInPlex" ${plexFilterMode === 'notInPlex' ? 'checked' : ''}>
                Not in Library
            </label>
        </div>
    `;

    plexFilter.addEventListener('change', (event) => {
        plexFilterMode = event.target.value;
        applyAllFilters();
    });
}

async function setupFilters() {
    const filterButtons = document.querySelector('.filter-buttons') || document.createElement('div');
    filterButtons.className = 'filter-buttons';
    filterButtons.style.display = 'flex';
    filterButtons.innerHTML = `
        <button class="filter-dropdown-button" id="libraryStatusButton">Library Status</button>
    `;

    // Check Trakt status before adding Watch Status filter
    try {
        const response = await fetch('/trakt/status');
        const data = await response.json();

        if (data.connected && (data.env_controlled || data.enabled)) {
            filterButtons.innerHTML += `
                <button class="filter-dropdown-button" id="watchStatusButton">Watch Status</button>
            `;
        }
    } catch (error) {
        console.error('Error checking Trakt status:', error);
    }

    // Find sort controls container and append our new buttons
    const sortButtons = document.querySelector('.sort-controls');
    if (sortButtons) {
        sortButtons.appendChild(filterButtons);
    }

    // Get all movies and counts
    const moviesContainer = document.getElementById('movies_container');
    const movieCards = moviesContainer ? moviesContainer.querySelectorAll('.movie-card') : [];
    const totalMovies = movieCards.length;
    const inLibraryCount = Array.from(movieCards).filter(card =>
        card.querySelector('.plex-badge, .jellyfin-badge, .emby-badge')
    ).length;
    const notInLibraryCount = totalMovies - inLibraryCount;

    // Create Library Status dropdown
    const libraryStatusDropdown = document.createElement('div');
    libraryStatusDropdown.className = 'filter-dropdown-content hidden';
    libraryStatusDropdown.innerHTML = `
        <div class="filter-options">
            <label>
                <input type="radio" name="libraryStatus" value="all" ${plexFilterMode === 'all' ? 'checked' : ''}>
                Show All <span class="count">(0)</span>
            </label>
            <label>
                <input type="radio" name="libraryStatus" value="inPlex" ${plexFilterMode === 'inPlex' ? 'checked' : ''}>
                In Library <span class="count">(0)</span>
            </label>
            <label>
                <input type="radio" name="libraryStatus" value="notInPlex" ${plexFilterMode === 'notInPlex' ? 'checked' : ''}>
                Not in Library <span class="count">(0)</span>
            </label>
        </div>
    `;

    // Create Watch Status dropdown
    const watchStatusDropdown = document.createElement('div');
    if (document.getElementById('watchStatusButton')) {
        watchStatusDropdown.className = 'filter-dropdown-content hidden';
        watchStatusDropdown.innerHTML = `
            <div class="filter-options">
                <label>
                    <input type="radio" name="watchStatus" value="all" ${traktFilterMode === 'all' ? 'checked' : ''}>
                    Show All <span class="count">(0)</span>
                </label>
                <label>
                    <input type="radio" name="watchStatus" value="watched" ${traktFilterMode === 'watched' ? 'checked' : ''}>
                    Show Watched <span class="count">(0)</span>
                </label>
                <label>
                    <input type="radio" name="watchStatus" value="unwatched" ${traktFilterMode === 'unwatched' ? 'checked' : ''}>
                    Show Unwatched <span class="count">(0)</span>
                </label>
            </div>
        `;
    }

    const moviesOverlayContent = document.getElementById('movies_overlay_content');
    if (moviesOverlayContent) {
        moviesOverlayContent.appendChild(libraryStatusDropdown);
        moviesOverlayContent.appendChild(watchStatusDropdown);

        libraryStatusDropdown.style.position = 'fixed';
        watchStatusDropdown.style.position = 'fixed';
    }

    // Handle library status button
    const libraryButton = document.getElementById('libraryStatusButton');
    if (libraryButton) {
        libraryButton.addEventListener('click', (e) => {
            e.stopPropagation();
            const rect = libraryButton.getBoundingClientRect();

            libraryStatusDropdown.style.top = `${rect.bottom + 4}px`;
            libraryStatusDropdown.style.left = `${rect.left}px`;
            libraryStatusDropdown.classList.toggle('hidden');
            watchStatusDropdown.classList.add('hidden');

            libraryButton.classList.toggle('active');
            document.getElementById('watchStatusButton')?.classList.remove('active');
        });
    }

    // Handle watch status button
    const watchButton = document.getElementById('watchStatusButton');
    if (watchButton) {
        watchButton.addEventListener('click', (e) => {
            e.stopPropagation();
            const rect = watchButton.getBoundingClientRect();

            watchStatusDropdown.style.top = `${rect.bottom + 4}px`;
            watchStatusDropdown.style.left = `${rect.left}px`;
            watchStatusDropdown.classList.toggle('hidden');
            libraryStatusDropdown.classList.add('hidden');

            watchButton.classList.toggle('active');
            document.getElementById('libraryStatusButton').classList.remove('active');
        });
    }

    // Close dropdowns when clicking outside
    document.addEventListener('click', () => {
        libraryStatusDropdown.classList.add('hidden');
        watchStatusDropdown.classList.add('hidden');
        document.getElementById('libraryStatusButton')?.classList.remove('active');
        watchButton?.classList.remove('active');
    });

    // Handle library status changes
    libraryStatusDropdown.addEventListener('change', (e) => {
        plexFilterMode = e.target.value;
        document.getElementById('libraryStatusButton').classList.add('active');
        applyAllFilters();
    });

    // Handle watch status changes
    if (watchButton) {
        watchStatusDropdown.addEventListener('change', (e) => {
            traktFilterMode = e.target.value;
            watchButton.classList.add('active');
            applyAllFilters();
        });
    }
}

async function updateFilterCounts() {
    const moviesContainer = document.getElementById('movies_container');
    const movieCards = moviesContainer ? moviesContainer.querySelectorAll('.movie-card') : [];
    const visibleCards = Array.from(movieCards).filter(card => card.style.display !== 'none');
    const totalVisible = visibleCards.length;

    // Update library status counts
    const inLibraryCount = visibleCards.filter(card =>
        card.querySelector('.plex-badge, .jellyfin-badge, .emby-badge')
    ).length;
    const notInLibraryCount = totalVisible - inLibraryCount;

    // Update watch status counts
    const watchedMovies = await getWatchedMovies();
    const watchedCount = visibleCards.filter(card =>
        watchedMovies.includes(parseInt(card.dataset.movieId))
    ).length;
    const unwatchedCount = totalVisible - watchedCount;

    // Update the count displays in dropdowns
    const updateCounts = (dropdown, counts) => {
        const labels = dropdown.querySelectorAll('label');
        labels.forEach(label => {
            const span = label.querySelector('.count');
            if (span) {
                const input = label.querySelector('input');
                if (input) {
                    switch (input.value) {
                        case 'all':
                            span.textContent = `(${counts.total})`;
                            break;
                        case 'inPlex':
                        case 'watched':
                            span.textContent = `(${counts.first})`;
                            break;
                        case 'notInPlex':
                        case 'unwatched':
                            span.textContent = `(${counts.second})`;
                            break;
                    }
                }
            }
        });
    };

    const libraryDropdown = document.querySelector('.filter-dropdown-content');
    if (libraryDropdown) {
        updateCounts(libraryDropdown, {
            total: totalVisible,
            first: inLibraryCount,
            second: notInLibraryCount
        });
    }

    const watchDropdown = document.querySelectorAll('.filter-dropdown-content')[1];
    if (watchDropdown) {
        updateCounts(watchDropdown, {
            total: totalVisible,
            first: watchedCount,
            second: unwatchedCount
        });
    }
}

async function applyAllFilters() {
    try {
        const watchedMovies = await getWatchedMovies();
        const moviesContainer = document.getElementById('movies_container');
        if (!moviesContainer) return;

        const movieCards = moviesContainer.querySelectorAll('.movie-card');
        movieCards.forEach(card => {
            const movieId = card.dataset.movieId;
            const isWatched = watchedMovies.includes(parseInt(movieId));
            const isHiddenBySearch = card.dataset.hiddenBySearch === 'true';
            const hasServiceBadge = card.querySelector('.plex-badge, .jellyfin-badge, .emby-badge') !== null;

            let shouldShowByTrakt = true;
            let shouldShowByPlex = true;

            // Apply Trakt filter
            switch (traktFilterMode) {
                case 'watched':
                    shouldShowByTrakt = isWatched;
                    break;
                case 'unwatched':
                    shouldShowByTrakt = !isWatched;
                    break;
                // 'all' case is handled by default shouldShow = true
            }

            // Apply Library filter
            switch (plexFilterMode) {
                case 'inPlex':
                    shouldShowByPlex = hasServiceBadge;
                    break;
                case 'notInPlex':
                    shouldShowByPlex = !hasServiceBadge;
                    break;
                // 'all' case is handled by default shouldShow = true
            }

            card.style.display = (shouldShowByTrakt && shouldShowByPlex && !isHiddenBySearch) ? 'block' : 'none';
        });
    } catch (error) {
        console.error('Error applying filters:', error);
    }
}

async function getWatchedMovies() {
    if (watchedMovies.length === 0) {
        const response = await fetch('/trakt_watched_status');
        if (response.ok) {
            watchedMovies = await response.json();
        } else {
            console.error("Failed to fetch Trakt watched status");
        }
    }
    return watchedMovies;
}

async function syncTraktWatched() {
    showContextLoadingOverlay('trakt');
    const response = await fetch('/sync_trakt_watched');
    if (response.ok) {
        console.log("Trakt watched status synced");
        // Clear the cache so we fetch the updated list next time
        watchedMovies = [];
    } else {
        console.error("Failed to sync Trakt watched status");
    }
    hideLoadingOverlay();
}

async function isMovieInService(tmdbId) {
    try {
        let apiEndpoint;
        switch(currentService) {
            case 'plex':
                apiEndpoint = '/is_movie_in_plex/';
                break;
            case 'jellyfin':
                apiEndpoint = '/is_movie_in_jellyfin/';
                break;
            case 'emby':
                apiEndpoint = '/is_movie_in_emby/';
                break;
            default:
                throw new Error(`Unknown service: ${currentService}`);
        }

        const response = await fetch(`${apiEndpoint}${tmdbId}`);
        if (!response.ok) {
            return false;
        }
        const data = await response.json();
        return data.available;  // All endpoints return {available: true/false}

    } catch (error) {
        console.error(`Error checking ${currentService} availability:`, error);
        return false;
    }
}

// Use the unified function for individual service checks
async function isMovieInJellyfin(tmdbId) {
    const currentServiceTemp = currentService;
    currentService = 'jellyfin';
    const result = await isMovieInService(tmdbId);
    currentService = currentServiceTemp;
    return result;
}

async function isMovieInEmby(tmdbId) {
    const currentServiceTemp = currentService;
    currentService = 'emby';
    const result = await isMovieInService(tmdbId);
    currentService = currentServiceTemp;
    return result;
}

async function isMovieInPlex(tmdbId) {
    const currentServiceTemp = currentService;
    currentService = 'plex';
    const result = await isMovieInService(tmdbId);
    currentService = currentServiceTemp;
    return result;
}

// Keep the getServiceId function separate for playback
async function getServiceId(tmdbId) {
    try {
        let apiEndpoint;
        switch(currentService) {
            case 'plex':
                apiEndpoint = '/api/get_plex_id/';
                break;
            case 'jellyfin':
                apiEndpoint = '/api/get_jellyfin_id/';
                break;
            case 'emby':
                apiEndpoint = '/api/get_emby_id/';
                break;
            default:
                throw new Error(`Unknown service: ${currentService}`);
        }

        const response = await fetch(`${apiEndpoint}${tmdbId}`);
        if (!response.ok) {
            throw new Error(`Failed to get ${currentService} ID`);
        }
        const data = await response.json();
        return data[`${currentService}Id`] || data.mediaId;
    } catch (error) {
        console.error(`Error getting ${currentService} ID:`, error);
        return null;
    }
}

function setupMovieSearch() {
    const searchInput = document.createElement('input');
    searchInput.type = 'text';
    searchInput.placeholder = 'Search movies...';
    searchInput.classList.add('search-input');

    const searchContainer = document.createElement('div');
    searchContainer.classList.add('search-container');
    searchContainer.appendChild(searchInput);

    const sortAndFilter = document.getElementById('sort_and_filter');
    if (sortAndFilter) {
	sortAndFilter.insertBefore(searchContainer, sortAndFilter.firstChild);
    }

    // Debounce function to avoid too many updates
    let searchTimeout;
    searchInput.addEventListener('input', function() {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            const searchTerm = this.value.toLowerCase();
            const movieCards = document.querySelectorAll('.movie-card');

            movieCards.forEach(card => {
                const title = card.querySelector('p').textContent.toLowerCase();
                const matches = title.includes(searchTerm);

                // Check if the movie would be hidden by Trakt filter
                const isHiddenByTraktFilter = card.style.display === 'none' &&
                    !card.dataset.hiddenBySearch;

                if (searchTerm === '') {
                    // If search is cleared, respect only Trakt filter
                    card.style.display = isHiddenByTraktFilter ? 'none' : 'block';
                    delete card.dataset.hiddenBySearch;
                } else {
                    if (!matches) {
                        card.style.display = 'none';
                        card.dataset.hiddenBySearch = 'true';
                    } else {
                        // Only show if not hidden by Trakt filter
                        card.style.display = isHiddenByTraktFilter ? 'none' : 'block';
                        delete card.dataset.hiddenBySearch;
                    }
                }
            });
        }, 300); // 300ms debounce
    });
}

function createSortControls() {
    const sortContainer = document.createElement('div');
    sortContainer.className = 'sort-controls';

    // Create Year sort button
    const yearButton = document.createElement('button');
    yearButton.className = 'sort-button active';
    yearButton.dataset.sort = 'year';
    yearButton.innerHTML = `
    	<span class="sort-text">Year</span>
    	<span class="sort-direction">(Newest)</span>
    `;

    // Create Rating sort button
    const ratingButton = document.createElement('button');
    ratingButton.className = 'sort-button';
    ratingButton.dataset.sort = 'rating';
    ratingButton.innerHTML = `
    	<span class="sort-text">Rating</span>
    	<span class="sort-direction">(Highest)</span>
    `;

    sortContainer.appendChild(yearButton);
    sortContainer.appendChild(ratingButton);

    // Add event listeners
    yearButton.addEventListener('click', () => toggleSort('year'));
    ratingButton.addEventListener('click', () => toggleSort('rating'));

    return sortContainer;
}

function toggleSort(type) {
    const buttons = document.querySelectorAll('.sort-button');
    buttons.forEach(button => {
        if (button.dataset.sort === type) {
            button.classList.add('active');

            if (currentSort === `${type}_desc`) {
                currentSort = `${type}_asc`;
                button.classList.remove('desc');
                updateSortButtonText(button, type, 'asc');
            } else {
                currentSort = `${type}_desc`;
                button.classList.add('desc');
                updateSortButtonText(button, type, 'desc');
            }
        } else {
            button.classList.remove('active', 'desc');
        }
    });

    sortMovies();
}

function updateSortButtonText(button, type, direction) {
    let textSpan = button.querySelector('.sort-text');
    let directionSpan = button.querySelector('.sort-direction');

    if (!textSpan) {
        textSpan = document.createElement('span');
        textSpan.className = 'sort-text';
        button.prepend(textSpan);
    }

    if (!directionSpan) {
        directionSpan = document.createElement('span');
        directionSpan.className = 'sort-direction';
        button.appendChild(directionSpan);
    }

    if (type === 'year') {
        textSpan.textContent = 'Year';
        directionSpan.textContent = direction === 'desc' ? '(Newest)' : '(Oldest)';
    } else if (type === 'rating') {
        textSpan.textContent = 'Rating';
        directionSpan.textContent = direction === 'desc' ? '(Highest)' : '(Lowest)';
    }
}

function initializeSortButtons() {
    document.querySelectorAll('.sort-button').forEach(button => {
        const type = button.dataset.sort;
        if (button.classList.contains('active')) {
            const direction = button.classList.contains('desc') ? 'desc' : 'asc';
            updateSortButtonText(button, type, direction);
        } else {
            updateSortButtonText(button, type, 'desc');
        }
    });
}

function sortMovies() {
    const moviesContainer = document.getElementById('movies_container');
    const movies = Array.from(moviesContainer.children);

    movies.sort((a, b) => {
        const movieAData = a.dataset;
        const movieBData = b.dataset;

        switch (currentSort) {
            case SORT_OPTIONS.YEAR_DESC:
                return parseInt(movieBData.year) - parseInt(movieAData.year);
            case SORT_OPTIONS.YEAR_ASC:
                return parseInt(movieAData.year) - parseInt(movieBData.year);
            case SORT_OPTIONS.RATING_DESC:
                return parseFloat(movieBData.rating) - parseFloat(movieAData.rating);
            case SORT_OPTIONS.RATING_ASC:
                return parseFloat(movieAData.rating) - parseFloat(movieBData.rating);
            default:
                return 0;
        }
    });

    // Clear and re-append sorted movies
    moviesContainer.innerHTML = '';
    movies.forEach(movie => moviesContainer.appendChild(movie));
}

function showContextLoadingOverlay(context) {
    const loadingContent = document.getElementById('loading-content');
    const getLoadingContent = (title, message) => `
        <div class="custom-loading">
            <h3>${title}</h3>
            <svg class="progress-ring" viewBox="0 0 50 50">
                <circle cx="25" cy="25" r="20" />
            </svg>
            <div class="loading-status">
                <div>${message}</div>
            </div>
        </div>
    `;

    switch (context) {
        case 'person':
            loadingContent.innerHTML = getLoadingContent(
                'Loading Filmography',
                'Fetching movies and checking availability...'
            );
            break;
        case 'cast':
            loadingContent.innerHTML = getLoadingContent(
                'Loading Cast',
                'Fetching cast details...'
            );
            break;
	case 'directors':
            loadingContent.innerHTML = getLoadingContent(
                'Loading Directors',
                'Fetching director details...'
            );
            break;
        case 'writers':
            loadingContent.innerHTML = getLoadingContent(
                'Loading Writers',
                'Fetching writer details...'
            );
            break;
        case 'movie':
            loadingContent.innerHTML = getLoadingContent(
                'Loading Movie Details',
                'Fetching movie information...'
            );
            break;
        case 'trakt':
            loadingContent.innerHTML = getLoadingContent(
                'Syncing Watch Status',
                'Updating watch history from Trakt...'
            );
            break;
        default:
            loadingContent.innerHTML = getLoadingContent(
                'Loading',
                'Please wait...'
            );
    }
    document.getElementById('loading-overlay').classList.remove('hidden');
}

function showToast(message, type = 'success') {
    // Create container if it doesn't exist
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }

    // Create toast
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    // Add icon based on type
    const icon = type === 'success'
        ? '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>'
        : '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>';

    toast.innerHTML = `
        <div class="toast-icon">${icon}</div>
        <div class="toast-message">${message}</div>
    `;

    // Add to container
    container.appendChild(toast);

    // Remove after delay
    setTimeout(() => {
        toast.classList.add('removing');
        setTimeout(() => {
            toast.remove();
            // Remove container if empty
            if (!container.children.length) {
                container.remove();
            }
        }, 300); // Match animation duration
    }, 3000);
}

async function syncTraktWatched(showLoading = false) {
    // Prevent rapid repeated syncs
    const now = Date.now();
    if (now - lastTraktSync < TRAKT_FRONTEND_SYNC_MIN_INTERVAL) {
        console.log("Skipping sync - too soon since last sync");
        return;
    }

    if (showLoading) {
        showContextLoadingOverlay('trakt');
    }

    try {
        const response = await fetch('/sync_trakt_watched');
        if (response.ok) {
            console.log("Trakt watched status synced at", new Date().toLocaleTimeString());
            lastTraktSync = now;
            watchedMovies = []; // Clear cache to force refresh

            // If we're in the movies overlay, reapply the current filter
            const moviesOverlay = document.getElementById('movies_overlay');
            if (moviesOverlay && !moviesOverlay.classList.contains('hidden')) {
		await applyAllFilters();
            }
        } else {
            console.error("Failed to sync Trakt watched status");
        }
    } catch (error) {
        console.error("Error syncing Trakt watched status:", error);
    } finally {
        if (showLoading) {
            hideLoadingOverlay();
        }
    }
}

function startVersionChecker() {
    // Check on page load
    checkVersion(false);

    // Then check every hour
    setInterval(() => {
        checkVersion(false);
    }, 60 * 60 * 1000);
}

function showUpdateDialog(updateInfo) {
    const dialog = document.createElement('div');
    dialog.className = 'trakt-confirm-dialog';
    dialog.innerHTML = `
        <div class="dialog-content">
            <h3>Update Available!</h3>
            <p class="version-info">Version ${updateInfo.latest_version} is now available (you have ${updateInfo.current_version})</p>
            <div class="changelog">
                <h4>Changelog:</h4>
                <div class="changelog-content">${updateInfo.changelog}</div>
            </div>
            <div class="dialog-buttons">
                <button class="cancel-button">Dismiss</button>
                <a href="${updateInfo.download_url}"
                   target="_blank"
                   rel="noopener noreferrer"
                   class="submit-button">View Release</a>
            </div>
        </div>
    `;

    document.body.appendChild(dialog);

    // Handle close/dismiss
    const closeDialog = () => {
        dialog.remove();
        fetch('/api/dismiss_update').catch(console.error);
    };

    dialog.querySelector('.cancel-button').addEventListener('click', closeDialog);
    dialog.addEventListener('click', (e) => {
        if (e.target === dialog) {
            closeDialog();
        }
    });
}

async function checkVersion(manual = false) {
    try {
        const response = await fetch('/api/check_version');
        const data = await response.json();

        if (data.update_available && (data.show_popup || manual)) {
            showUpdateDialog(data);
        } else if (manual) {
            showSuccess('You are running the latest version!');
        }
    } catch (error) {
        console.error('Error checking version:', error);
        if (manual) {
            showError('Failed to check for updates');
        }
    }
}
