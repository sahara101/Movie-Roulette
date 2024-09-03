let currentFilters = {
    genre: '',
    year: '',
    rating: ''
};

let currentService = 'plex';
let currentMovie = null;
let availableServices = [];

document.addEventListener('DOMContentLoaded', async function() {
    await getAvailableServices();
    await getCurrentService();
    await loadRandomMovie();
    if (!window.HOMEPAGE_MODE) {
        await loadFilterOptions();
        setupEventListeners();
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
            if (!window.HOMEPAGE_MODE) {
                await loadFilterOptions();
            }
        }
        updateServiceButton();
    } catch (error) {
        console.error("Error getting current service:", error);
    }
}

async function loadRandomMovie() {
    try {
        const response = await fetch(`/random_movie`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();
        console.log("Loaded random movie from service:", data.service);
        currentMovie = data.movie;
        updateMovieDisplay(data.movie);
    } catch (error) {
        console.error("Error fetching random movie:", error);
    }
}

async function loadFilterOptions() {
    if (window.HOMEPAGE_MODE) return;

    try {
        console.log("Loading filter options for service:", currentService);
        const genresResponse = await fetch(`/get_genres`);
        const yearsResponse = await fetch(`/get_years`);

        if (!genresResponse.ok || !yearsResponse.ok) {
            throw new Error('Failed to fetch filter options');
        }

        const genres = await genresResponse.json();
        const years = await yearsResponse.json();

        console.log("Fetched genres:", genres);
        console.log("Fetched years:", years);

        populateDropdown('genreSelect', genres);
        populateDropdown('yearSelect', years);
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
    if (window.HOMEPAGE_MODE) return;

    const filterButton = document.getElementById("filterButton");
    const filterDropdown = document.getElementById("filterDropdown");

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
    document.getElementById("btn_watch").addEventListener('click', showClients);
    document.getElementById("btn_next_movie").addEventListener('click', loadNextMovie);
    document.getElementById("btn_power").addEventListener('click', showDevices);
    document.getElementById("trailer_popup_close").addEventListener('click', closeTrailerPopup);
    document.getElementById("switch_service").addEventListener('click', switchService);
}

async function applyFilter() {
    if (window.HOMEPAGE_MODE) return;

    currentFilters.genre = document.getElementById("genreSelect").value;
    currentFilters.year = document.getElementById("yearSelect").value;
    currentFilters.rating = document.getElementById("ratingFilter").value;

    try {
        const response = await fetch(`/filter_movies?genre=${encodeURIComponent(currentFilters.genre)}&year=${currentFilters.year}&rating=${currentFilters.rating}`);
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error);
        }
        const data = await response.json();
        console.log("Filtered movie from service:", data.service);
        currentMovie = data.movie;
        updateMovieDisplay(data.movie);
    } catch (error) {
        console.error("Error applying filter:", error);
        alert(error.message);
    }
}

function clearFilter() {
    if (window.HOMEPAGE_MODE) return;

    document.getElementById("genreSelect").value = '';
    document.getElementById("yearSelect").value = '';
    document.getElementById("ratingFilter").value = '';
    currentFilters = {
        genre: '',
        year: '',
        rating: ''
    };
    loadRandomMovie();
}

async function loadNextMovie() {
    if (window.HOMEPAGE_MODE) return;

    try {
        let url = `/next_movie`;
        if (currentFilters.genre || currentFilters.year || currentFilters.rating) {
            url = `/filter_movies?genre=${encodeURIComponent(currentFilters.genre)}&year=${currentFilters.year}&rating=${currentFilters.rating}`;
        }
        const response = await fetch(url);
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error);
        }
        const data = await response.json();
        console.log("Loaded next movie from service:", data.service);
        currentMovie = data.movie;
        updateMovieDisplay(data.movie);
    } catch (error) {
        console.error("Error fetching next movie:", error);
        alert(error.message);
    }
}

function updateMovieDisplay(movieData) {
    if (!movieData) {
        console.error("No movie data to display");
        return;
    }

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
                element.textContent = `${movieData.year} | ${movieData.duration_hours}h ${movieData.duration_minutes}m`;
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
    if (window.HOMEPAGE_MODE) return;

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
    if (window.HOMEPAGE_MODE) return;

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
    if (window.HOMEPAGE_MODE) return;

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
    if (window.HOMEPAGE_MODE) return;

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
        }
