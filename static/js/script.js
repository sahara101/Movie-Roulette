let currentFilters = {
    genre: '',
    year: '',
    pgRating: ''
};

let currentService = 'plex';
let currentMovie = null;
let availableServices = [];
let socket = io();

document.addEventListener('DOMContentLoaded', async function() {
    await getAvailableServices();
    await getCurrentService();
    await loadRandomMovie();
    await loadFilterOptions();
    setupEventListeners();
    checkAndLoadCache();
});

function showLoadingOverlay() {
    document.getElementById('loading-overlay').classList.remove('hidden');
}

function hideLoadingOverlay() {
    document.getElementById('loading-overlay').classList.add('hidden');
}

function updateLoadingProgress(progress) {
    const progressBar = document.getElementById('loading-progress');
    progressBar.style.width = `${progress * 100}%`;
    console.log(`Loading progress: ${progress * 100}%`);
}

socket.on('loading_progress', function(data) {
    console.log('Received loading progress:', data);
    updateLoadingProgress(data.progress);
    showLoadingOverlay();
});

socket.on('loading_complete', function() {
    console.log('Loading complete');
    updateLoadingProgress(1.0);  // Ensure we reach 100%
    setTimeout(() => {
        hideLoadingOverlay();
        loadRandomMovie();
    }, 500);  // Give a moment for 100% to be visible
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
        if (!response.ok) {
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
    const filterButton = document.getElementById("filterButton");
    const filterDropdown = document.getElementById("filterDropdown");

    if (filterButton && filterDropdown) {
        filterButton.addEventListener('click', function(event) {
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

        document.getElementById("applyFilter").addEventListener('click', applyFilter);
        document.getElementById("clearFilter").addEventListener('click', clearFilter);
    }

    if (!window.HOMEPAGE_MODE) {
        document.getElementById("btn_watch").addEventListener('click', showClients);
        document.getElementById("btn_next_movie").addEventListener('click', loadNextMovie);
        document.getElementById("btn_power").addEventListener('click', showDevices);
        document.getElementById("trailer_popup_close").addEventListener('click', closeTrailerPopup);
        document.getElementById("switch_service").addEventListener('click', switchService);
    }
}

async function applyFilter() {
    currentFilters.genre = document.getElementById("genreSelect").value;
    currentFilters.year = document.getElementById("yearSelect").value;
    currentFilters.pgRating = document.getElementById("pgRatingSelect").value;

    try {
        const response = await fetch(`/filter_movies?genre=${encodeURIComponent(currentFilters.genre)}&year=${currentFilters.year}&pg_rating=${encodeURIComponent(currentFilters.pgRating)}`);
        
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
        updateMovieDisplay(data.movie);
        document.getElementById("filterDropdown").classList.remove("show");
    } catch (error) {
        console.error("Error applying filter:", error);
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

function clearFilter() {
    document.getElementById("genreSelect").value = '';
    document.getElementById("yearSelect").value = '';
    document.getElementById("pgRatingSelect").value = '';
    currentFilters = {
        genre: '',
        year: '',
        pgRating: ''
    };
    hideMessage();
    loadRandomMovie();
    document.getElementById("filterDropdown").classList.remove("show");
}

async function loadNextMovie() {
    try {
        let url = `/next_movie`;
        if (currentFilters.genre || currentFilters.year || currentFilters.pgRating) {
            url += `?genre=${encodeURIComponent(currentFilters.genre || '')}&year=${currentFilters.year || ''}&pg_rating=${encodeURIComponent(currentFilters.pgRating || '')}`;
        }
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

function updateMovieDisplay(movieData) {
    if (!movieData) {
        console.error("No movie data to display");
        return;
    }

    console.log('Movie data:', movieData);

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

    if (!window.HOMEPAGE_MODE) {
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
                element.textContent = `Directed by: ${movieData.directors.join(", ")}`;
                break;
            case "writers":
                element.textContent = `Written by: ${movieData.writers.join(", ")}`;
                break;
            case "actors":
                element.textContent = `Cast: ${movieData.actors.join(", ")}`;
                break;
            case "genres":
                element.textContent = `Genres: ${movieData.genres.join(", ")}`;
                break;
            case "description":
                element.textContent = movieData.description;
                break;
            case "poster_img":
                element.src = movieData.poster;
                break;
            case "img_background":
                element.style.backgroundImage = `url(${movieData.background})`;
                break;
        }
    }

    if (!window.HOMEPAGE_MODE) {
        elements["tmdb_link"].href = movieData.tmdb_url;
        elements["trakt_link"].href = movieData.trakt_url;
        elements["imdb_link"].href = movieData.imdb_url;
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

    document.getElementById("section").classList.remove("hidden");
    setupDescriptionExpander();
    window.dispatchEvent(new Event('resize'));
}

function setupDescriptionExpander() {
    const description = document.getElementById('description');
    if (!description) return;

    const lineHeight = parseInt(window.getComputedStyle(description).lineHeight);
    const maxLines = 4;
    const maxHeight = lineHeight * maxLines;

    function checkTruncation() {
        description.style.webkitLineClamp = '4';
        description.style.display = '-webkit-box';
        
        if (description.scrollHeight > description.clientHeight) {
            description.classList.add('truncated');
            description.style.cursor = 'pointer';
            description.addEventListener('click', toggleExpand);
        } else {
            description.classList.remove('truncated', 'expanded');
            description.style.cursor = 'default';
            description.removeEventListener('click', toggleExpand);
        }
    }

    function toggleExpand() {
        description.classList.toggle('expanded');
        if (description.classList.contains('expanded')) {
            description.style.webkitLineClamp = 'unset';
            description.style.maxHeight = 'none';
        } else {
            description.style.webkitLineClamp = '4';
            description.style.maxHeight = `${maxHeight}px`;
        }
    }

    checkTruncation();
    window.addEventListener('resize', checkTruncation);
}

async function showClients() {
    try {
        document.getElementById("btn_watch").disabled = true;
        const response = await fetch(`/clients`);
        const clients = await response.json();

        const listContainer = document.getElementById("list_of_clients");
        listContainer.innerHTML = "";

        if (clients.length === 0) {
            listContainer.innerHTML = "<div>No available clients found.</div>";
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
    } catch (error) {
        console.error("Error playing movie:", error);
	alert("Failed to play movie. Please try again.");
    } finally {
        const playButton = document.getElementById("btn_watch");
        playButton.disabled = false;
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

// Socket.IO event listeners
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
        // Wait for the loading_complete event
        await new Promise((resolve) => {
            socket.once('loading_complete', resolve);
        });
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
            await refreshMovieCache();
        }
    } catch (error) {
        console.error('Error checking cache:', error);
    }
}

// Call this function when the page loads
document.addEventListener('DOMContentLoaded', checkAndLoadCache);
