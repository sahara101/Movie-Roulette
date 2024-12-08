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
        if (powerButton) {
            powerButton.style.display = devices.length > 0 ? 'flex' : 'none';
        }
    } catch (error) {
        console.error("Error checking devices:", error);
        const powerButton = document.getElementById("btn_power");
        if (powerButton) {
            powerButton.style.display = 'none';
        }
    }
    await syncTraktWatched(false);
    startVersionChecker();
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
    console.log('Received loading progress:', data);
    const progressBar = document.getElementById('loading-progress');
    const loadingCount = document.querySelector('.loading-count');

    if (progressBar && loadingCount) {
        progressBar.style.width = `${data.progress * 100}%`;
        loadingCount.textContent = `${data.current}/${data.total}`;
    }
    document.getElementById('loading-overlay').classList.remove('hidden');
});

socket.on('loading_complete', async function() {
    console.log('Loading complete');
    const overlay = document.getElementById('loading-overlay');
    if (overlay) {
        overlay.classList.add('hidden');
        await loadRandomMovie();
	// Check for updates after cache is built
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
        }
        updateServiceButton();
    } catch (error) {
        console.error("Error getting current service:", error);
    }
}

async function loadRandomMovie() {
    try {
        const response = await fetch(`/random_movie`);
        if (response.status === 202) {
            console.log('Loading in progress, waiting for completion');
            return;
        }
        // Add check for cache building
        if (!response.ok && response.status === 404) {
            const debug = await fetch('/debug_plex');
            const data = await debug.json();
            if (!data.cache_file_exists) {
                console.log('Cache still building, ignoring 404');
                return;
            }
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        console.log("Loaded random movie from service:", data.service);
        currentMovie = data.movie;
        updateMovieDisplay(data.movie);
    } catch (error) {
        console.error("Error fetching random movie:", error);
    } finally {
        hideLoadingOverlay();
    }
}

async function loadFilterOptions() {
    try {
        console.log("Loading filter options for service:", currentService);
        const genresResponse = await fetch(`/get_genres`);
        const yearsResponse = await fetch(`/get_years`);
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

    await fetchFilteredMovies();
}

async function fetchFilteredMovies() {
    try {
        const queryParams = new URLSearchParams();
        if (currentFilters.genres.length) queryParams.append('genres', currentFilters.genres.join(','));
        if (currentFilters.years.length) queryParams.append('years', currentFilters.years.join(','));
        if (currentFilters.pgRatings.length) queryParams.append('pg_ratings', currentFilters.pgRatings.join(','));

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
    currentFilters = {
        genres: [],
        years: [],
        pgRatings: []
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
        const queryParams = new URLSearchParams();
        if (currentFilters.genres.length) queryParams.append('genres', currentFilters.genres.join(','));
        if (currentFilters.years.length) queryParams.append('years', currentFilters.years.join(','));
        if (currentFilters.pgRatings.length) queryParams.append('pg_ratings', currentFilters.pgRatings.join(','));

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

    console.log('Movie data received:', movieData);

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

async function checkOverseerrAvailability() {
    try {
        const response = await fetch('/api/overseerr/status');
        const data = await response.json();
        return data.available;
    } catch (error) {
        console.error('Error checking Overseerr status:', error);
        return false;
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
        this.element.style.webkitLineClamp = '1';
        this.element.style.display = '-webkit-box';
        this.element.style.maxHeight = '';
        this.element.style.cursor = 'default';
        this.state.expanded = false;
    }

    checkTruncation() {
        if (!this.element) return;

        requestAnimationFrame(() => {
            void this.element.offsetHeight;

            const truncated = this.element.scrollHeight > this.element.clientHeight;
            this.state.truncated = truncated;

            if (truncated) {
                this.element.classList.add('truncated');
                this.element.style.cursor = 'pointer';
            }

            console.log('Truncation check:', {
                scrollHeight: this.element.scrollHeight,
                clientHeight: this.element.clientHeight,
                isTruncated: truncated,
                text: this.element.textContent.substring(0, 50) + '...'
            });
        });
    }

    bindEvents() {
        if (!this.element) return;
        this.element.addEventListener('click', this.boundToggle);
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

        // Apply filters immediately after rendering
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

    let isInLibrary = false;
    if (currentService === 'plex') {
        isInLibrary = await isMovieInPlex(movie.id);
    } else if (currentService === 'jellyfin') {
        isInLibrary = await isMovieInJellyfin(movie.id);
    }

    if (isInLibrary) {
        const badge = document.createElement('div');
        badge.classList.add(currentService === 'plex' ? 'plex-badge' : 'jellyfin-badge');
        badge.textContent = currentService.toUpperCase();
        posterLink.appendChild(badge);
    }

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

    const movieTitle = document.createElement('p');
    movieTitle.textContent = movie.title;

    const requestButton = document.createElement('button');
    requestButton.classList.add('request-button');

    if (isInLibrary) {
        requestButton.textContent = "Watch";
        requestButton.addEventListener('click', () => showClientsForPoster(movie.id));
    } else {
        const overseerrAvailable = await checkOverseerrAvailability();
        if (overseerrAvailable) {
            const mediaStatus = await fetch(`/api/overseerr/media/${movie.id}`).then(r => r.json());
            console.log('Media status:', mediaStatus);
            // Only check for pending (3) or processing (4) status
            const isRequested = mediaStatus?.mediaInfo?.status === 3 || mediaStatus?.mediaInfo?.status === 4;

            if (isRequested) {
                requestButton.textContent = "Requested";
                requestButton.classList.add('requested');
                requestButton.disabled = true;
            } else {
                requestButton.textContent = "Request";
                requestButton.addEventListener('click', () => requestMovie(movie.id));
            }
        } else {
            requestButton.textContent = "Request";
            requestButton.disabled = true;
            requestButton.title = "Overseerr is not configured or disabled";
        }
    }

    movieCard.appendChild(posterLink);
    movieCard.appendChild(movieTitle);
    movieCard.appendChild(requestButton);

    return movieCard;
}

async function isMovieInJellyfin(movieId) {
    try {
        const response = await fetch(`/is_movie_in_jellyfin/${movieId}`);
        if (!response.ok) {
            throw new Error('Failed to check Jellyfin availability');
        }
        const data = await response.json();
        return data.available;
    } catch (error) {
        console.error("Error checking Jellyfin availability:", error);
        return false;
    }
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
        const [movieResponse, plexAvailable, overseerrAvailable, overseerrStatus] = await Promise.all([
            fetch(`/api/movie_details/${movieId}`),
            fetch(`/is_movie_in_plex/${movieId}`).then(r => r.json()),
            checkOverseerrAvailability(),
            fetch(`/api/overseerr/media/${movieId}`).then(r => r.json()).catch(() => null)
        ]);

        console.log('Media status in overlay:', overseerrStatus);

        if (!movieResponse.ok) {
            throw new Error(`Failed to fetch movie details: ${movieResponse.status} ${movieResponse.statusText}`);
        }

        const movieData = await movieResponse.json();
        const isInPlex = plexAvailable.available;
        const isRequested = overseerrStatus?.mediaInfo?.status === 3 || overseerrStatus?.mediaInfo?.status === 4;

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
        } else if (overseerrAvailable) {
            const requestButton = document.createElement('button');
            requestButton.className = 'action-button';
            if (isRequested) {
                requestButton.textContent = 'Requested';
                requestButton.disabled = true;
                requestButton.classList.add('requested');
            } else {
                requestButton.id = 'request_movie_button';
                requestButton.textContent = 'Request Movie';
                requestButton.addEventListener('click', () => requestMovie(movieId));
            }
            overlayContent.appendChild(requestButton);
        } else {
            const disabledButton = document.createElement('button');
            disabledButton.className = 'action-button';
            disabledButton.textContent = 'Request Movie';
            disabledButton.disabled = true;
            disabledButton.title = 'Overseerr is not configured or disabled';
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

async function requestMovie(movieId) {
    try {
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

        const data = await requestResponse.json();
        showToast('Movie requested successfully!', 'success');
    } catch (error) {
        console.error("Error requesting movie:", error);
        showToast(error.message, 'error');
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
                    playMovie(client.id);
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
        const response = await fetch('/is_movie_in_plex/' + tmdbId);
        const data = await response.json();
        if (data.plexId) {
            return data.plexId;
        }
        throw new Error('Movie not found in Plex');
    } catch (error) {
        console.error('Error getting Plex ID:', error);
        throw error;
    }
}

async function playMovieFromPoster(clientId, tmdbId) {
    try {
        // First get the Plex ID
        const response = await fetch(`/api/get_plex_id/${tmdbId}`);
        if (!response.ok) {
            throw new Error('Failed to get Plex ID');
        }
        const data = await response.json();
        if (!data.plexId) {
            throw new Error('Movie not found in Plex');
        }

        // Now play using the Plex ID
        const playResponse = await fetch(`/play_movie/${clientId}?movie_id=${data.plexId}`);
        const playData = await playResponse.json();

        if (playData.status !== "playing") {
            throw new Error(playData.error || "Failed to start playback");
        }

        setTimeout(() => syncTraktWatched(false), 30000);

    } catch (error) {
        console.error("Error playing movie:", error);
        alert("Failed to play movie. Please try again.");
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
            const otherService = currentService === 'plex' ? 'Jellyfin' : 'Plex';
            switchButton.querySelector('.service-name').textContent = otherService;
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
            if (data.service) {
                currentService = data.service;
                console.log("Switched to service:", currentService);
                updateServiceButton();
                await loadRandomMovie();
                await loadFilterOptions();
            }
        } catch (error) {
            console.error("Error switching service:", error);
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
}

function handleError(error) {
    console.error('An error occurred:', error);
    alert('An error occurred. Please try again or refresh the page.');
    hideLoadingOverlay();
}

async function checkAndLoadCache() {
    try {
        const response = await fetch('/debug_plex');
        const data = await response.json();
        if (data.cached_movies === 0) {
            console.log('Cache is empty. Starting to load movies...');
            
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

let traktFilterMode = 'unwatched'; // 'all', 'watched', or 'unwatched'
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

    // Create and setup the Library Status dropdown
    const libraryStatusDropdown = document.createElement('div');
    libraryStatusDropdown.className = 'filter-dropdown-content hidden';
    libraryStatusDropdown.innerHTML = `
        <div class="filter-options">
            <label><input type="radio" name="libraryStatus" value="all" ${plexFilterMode === 'all' ? 'checked' : ''}>Show All</label>
            <label><input type="radio" name="libraryStatus" value="inPlex" ${plexFilterMode === 'inPlex' ? 'checked' : ''}>In Library</label>
            <label><input type="radio" name="libraryStatus" value="notInPlex" ${plexFilterMode === 'notInPlex' ? 'checked' : ''}>Not in Library</label>
        </div>
    `;

    // Create Watch Status dropdown if button exists
    const watchStatusDropdown = document.createElement('div');
    if (document.getElementById('watchStatusButton')) {
        watchStatusDropdown.className = 'filter-dropdown-content hidden';
        watchStatusDropdown.innerHTML = `
            <div class="filter-options">
                <label><input type="radio" name="watchStatus" value="all" ${traktFilterMode === 'all' ? 'checked' : ''}>Show All</label>
                <label><input type="radio" name="watchStatus" value="watched" ${traktFilterMode === 'watched' ? 'checked' : ''}>Show Watched</label>
                <label><input type="radio" name="watchStatus" value="unwatched" ${traktFilterMode === 'unwatched' ? 'checked' : ''}>Show Unwatched</label>
            </div>
        `;
    }

    // Append dropdowns to the movies overlay content
    const moviesOverlayContent = document.getElementById('movies_overlay_content');
    if (moviesOverlayContent) {
        moviesOverlayContent.appendChild(libraryStatusDropdown);
        moviesOverlayContent.appendChild(watchStatusDropdown);

        // Add necessary CSS
        libraryStatusDropdown.style.position = 'fixed';  // Changed to fixed
        watchStatusDropdown.style.position = 'fixed';    // Changed to fixed
    }

    // Setup click handlers for Library Status
    const libraryButton = document.getElementById('libraryStatusButton');
    if (libraryButton) {
        libraryButton.addEventListener('click', (e) => {
            e.stopPropagation();
            const rect = libraryButton.getBoundingClientRect();
            const overlayRect = moviesOverlayContent.getBoundingClientRect();

            libraryStatusDropdown.style.top = `${rect.bottom + 4}px`;
            libraryStatusDropdown.style.left = `${rect.left}px`;
            libraryStatusDropdown.classList.toggle('hidden');
            watchStatusDropdown.classList.add('hidden');

            libraryButton.classList.toggle('active');
            document.getElementById('watchStatusButton')?.classList.remove('active');
        });
    }

    // Setup click handlers for Watch Status if it exists
    const watchButton = document.getElementById('watchStatusButton');
    if (watchButton) {
        watchButton.addEventListener('click', (e) => {
            e.stopPropagation();
            const rect = watchButton.getBoundingClientRect();
            const overlayRect = moviesOverlayContent.getBoundingClientRect();

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

    // Handle filter changes
    libraryStatusDropdown.addEventListener('change', (e) => {
        plexFilterMode = e.target.value;
        document.getElementById('libraryStatusButton').classList.add('active');
        applyAllFilters();
    });

    if (watchButton) {
        watchStatusDropdown.addEventListener('change', (e) => {
            traktFilterMode = e.target.value;
            watchButton.classList.add('active');
            applyAllFilters();
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
            const hasServiceBadge = card.querySelector('.plex-badge, .jellyfin-badge') !== null;

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

async function isMovieInPlex(movieId) {
    try {
        const response = await fetch(`/is_movie_in_plex/${movieId}`);
        if (!response.ok) {
            throw new Error('Failed to check Plex availability');
        }
        const data = await response.json();
        return data.available;
    } catch (error) {
        console.error("Error checking Plex availability:", error);
        return false;
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
        Year
        <svg class="sort-icon" viewBox="0 0 24 24" fill="currentColor">
            <path d="M7 14l5-5 5 5z"/>
        </svg>
    `;

    // Create Rating sort button
    const ratingButton = document.createElement('button');
    ratingButton.className = 'sort-button';
    ratingButton.dataset.sort = 'rating';
    ratingButton.innerHTML = `
        Rating
        <svg class="sort-icon" viewBox="0 0 24 24" fill="currentColor">
            <path d="M7 14l5-5 5 5z"/>
        </svg>
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
            } else {
                currentSort = `${type}_desc`;
                button.classList.add('desc');
            }
        } else {
            button.classList.remove('active', 'desc');
        }
    });

    sortMovies();
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

    // Only handle the Dismiss button click
    dialog.querySelector('.cancel-button').addEventListener('click', () => {
        dialog.remove();
        fetch('/api/dismiss_update').catch(console.error);
    });
}

async function checkVersion() {
    try {
        const response = await fetch('/api/check_version');
        const data = await response.json();

        if (data.update_available && data.show_popup) {
            showUpdateDialog(data);
        }
    } catch (error) {
        console.error('Error checking version:', error);
    }
}
