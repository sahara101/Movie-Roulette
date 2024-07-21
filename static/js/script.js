let currentFilters = {
    genre: '',
    year: '',
    rating: ''
};

document.addEventListener('DOMContentLoaded', function() {
    loadInitialMovie();
    loadFilterOptions();
    setupEventListeners();
});

async function loadInitialMovie() {
    try {
        // Fetch random movie data from Flask API
        const response = await fetch('/random_movie');
        const movieData = await response.json();
        updateMovieDisplay(movieData);
    } catch (error) {
        console.error("Error fetching random movie:", error);
    }
}

async function loadFilterOptions() {
    try {
        const [genres, years] = await Promise.all([
            fetch('/get_genres').then(res => res.json()),
            fetch('/get_years').then(res => res.json())
        ]);

        populateDropdown('genreSelect', genres);
        populateDropdown('yearSelect', years);
    } catch (error) {
        console.error("Error loading filter options:", error);
    }
}

function populateDropdown(elementId, options) {
    const select = document.getElementById(elementId);
    select.innerHTML = '<option value="">Any</option>';
    options.forEach(option => {
        if (option) {
            const optionElement = document.createElement('option');
            optionElement.value = option;
            optionElement.textContent = option;
            select.appendChild(optionElement);
        }
    });
}

function setupEventListeners() {
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
}

async function applyFilter() {
    currentFilters.genre = document.getElementById("genreSelect").value;
    currentFilters.year = document.getElementById("yearSelect").value;
    currentFilters.rating = document.getElementById("ratingFilter").value;

    try {
        const response = await fetch(`/filter_movies?genre=${encodeURIComponent(currentFilters.genre)}&year=${currentFilters.year}&rating=${currentFilters.rating}`);
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error);
        }
        const movieData = await response.json();
        updateMovieDisplay(movieData);
    } catch (error) {
        console.error("Error applying filter:", error);
        alert(error.message);
    }
}

function clearFilter() {
    document.getElementById("genreSelect").value = '';
    document.getElementById("yearSelect").value = '';
    document.getElementById("ratingFilter").value = '';
    currentFilters = {
        genre: '',
        year: '',
        rating: ''
    };
    loadInitialMovie();
}

async function loadNextMovie() {
    try {
        let url = '/next_movie';
        if (currentFilters.genre || currentFilters.year || currentFilters.rating) {
            url = `/filter_movies?genre=${encodeURIComponent(currentFilters.genre)}&year=${currentFilters.year}&rating=${currentFilters.rating}`;
        }
        const response = await fetch(url);
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error);
        }
        const movieData = await response.json();
        updateMovieDisplay(movieData);
    } catch (error) {
        console.error("Error fetching next movie:", error);
        alert(error.message);
    }
}

function updateMovieDisplay(movieData) {
    document.getElementById("title").textContent = movieData.title;
    document.getElementById("year_duration").textContent = `${movieData.year} | ${movieData.duration_hours}h ${movieData.duration_minutes}m`;
    document.getElementById("directors").textContent = `Directed by: ${movieData.directors.join(", ")}`;
    document.getElementById("writers").textContent = `Written by: ${movieData.writers.join(", ")}`;
    document.getElementById("actors").textContent = `Cast: ${movieData.actors.join(", ")}`;
    document.getElementById("genres").textContent = `Genres: ${movieData.genres.join(", ")}`;
    document.getElementById("description").textContent = movieData.description;
    document.getElementById("poster_img").src = movieData.poster;
    document.getElementById("img_background").style.backgroundImage = `url(${movieData.background})`;
    document.getElementById("tmdb_link").href = movieData.tmdb_url;
    document.getElementById("trakt_link").href = movieData.trakt_url;
    document.getElementById("imdb_link").href = movieData.imdb_url;
    const trailerLink = document.getElementById("trailer_link");
    if (movieData.trailer_url) {
        trailerLink.style.display = "block";
        trailerLink.onclick = function() {
            document.getElementById("trailer_iframe").src = movieData.trailer_url;
            document.getElementById("trailer_popup").classList.remove("hidden");
        };
    } else {
        trailerLink.style.display = "none";
    }
    document.getElementById("section").classList.remove("hidden");
    setupDescriptionExpander();
    window.dispatchEvent(new Event('resize'));
}

function setupDescriptionExpander() {
    const description = document.getElementById('description');
    const lineHeight = parseInt(window.getComputedStyle(description).lineHeight);
    const maxLines = 4;
    const maxHeight = lineHeight * maxLines;

    function checkTruncation() {
        if (description.scrollHeight > maxHeight) {
            description.classList.add('truncated');
            description.style.cursor = 'pointer';
            description.addEventListener('click', toggleExpand);
        } else {
            description.classList.remove('truncated', 'expanded');
            description.style.cursor = 'default';
            description.removeEventListener('click', toggleExpand);
        }
    }

    function toggleExpand(event) {
        event.stopPropagation();
        description.classList.toggle('expanded');
    }

    checkTruncation();
    window.addEventListener('resize', checkTruncation);
}

// Function to fetch and display a list of clients
async function showClients() {
    try {
        // Fetch list of clients from Flask API
        const response = await fetch('/clients');
        const clients = await response.json();

        // Clear previous client list
        const listContainer = document.getElementById("list_of_clients");
        listContainer.innerHTML = "";

        // Display clients as clickable options
        clients.forEach(client => {
            const clientDiv = document.createElement("div");
            clientDiv.classList.add("client");
            clientDiv.textContent = client.title;
            clientDiv.onclick = function() {
                playMovie(client.title, client.address, client.port);
                closeClientPrompt();
            };
            listContainer.appendChild(clientDiv);
        });

        // Show client prompt
        document.getElementById("client_prompt").classList.remove("hidden");
    } catch (error) {
        console.error("Error fetching clients:", error);
    }
}

// Function to play a movie on a selected client
async function playMovie(clientTitle, clientAddress, clientPort) {
    try {
        // Call Flask API to play movie on the selected client
        const response = await fetch(`/play_movie/${clientTitle}?address=${clientAddress}&port=${clientPort}`);
        const data = await response.json();
        console.log("Response from play_movie API:", data);
    } catch (error) {
        console.error("Error playing movie:", error);
    }
}

// Function to fetch and display a list of devices
async function showDevices() {
    try {
        // Fetch list of devices from Flask API
        const response = await fetch('/devices');
        const devices = await response.json();

        // Clear previous device list
        const listContainer = document.getElementById("list_of_devices");
        listContainer.innerHTML = "";

        // Display devices as clickable options
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

        // Show device prompt
        document.getElementById("device_prompt").classList.remove("hidden");
    } catch (error) {
        console.error("Error fetching devices:", error);
    }
}

// Function to turn on a device
async function turnOnDevice(deviceName) {
    try {
        // Call Flask API to turn on the selected device
        const response = await fetch(`/turn_on_device/${deviceName}`);
        const data = await response.json();
        console.log("Response from turn_on_device API:", data);
    } catch (error) {
        console.error("Error turning on device:", error);
    }
}

// Function to close the client prompt
function closeClientPrompt() {
    document.getElementById("client_prompt").classList.add("hidden");
}

// Function to close the device prompt
function closeDevicePrompt() {
    document.getElementById("device_prompt").classList.add("hidden");
}

// Function to close the trailer popup
function closeTrailerPopup() {
    document.getElementById("trailer_iframe").src = "";
    document.getElementById("trailer_popup").classList.add("hidden");
}
