window.onload = async function() {
    await showRandomMovie(); // Load a random movie on page load
};

// Function to fetch and display a random movie
async function showRandomMovie() {
    try {
        // Fetch random movie data from Flask API
        const response = await fetch('/random_movie');
        const movieData = await response.json();

        // Update HTML elements with movie details
        document.getElementById("title").textContent = movieData.title;
        document.getElementById("year_duration").textContent = `${movieData.year} | ${movieData.duration_hours}h ${movieData.duration_minutes}m`;
        document.getElementById("directors").textContent = `Directed by: ${movieData.directors.join(", ")}`;
        document.getElementById("writers").textContent = `Written by: ${movieData.writers.join(", ")}`;
        document.getElementById("actors").textContent = `Cast: ${movieData.actors.join(", ")}`;
        document.getElementById("description").textContent = `Description: ${movieData.description}`;

        document.getElementById("poster_img").src = movieData.poster;
        document.getElementById("img_background").style.backgroundImage = `url(${movieData.background})`;

        document.getElementById("tmdb_link").href = movieData.tmdb_url;
        document.getElementById("trakt_link").href = movieData.trakt_url;
        document.getElementById("imdb_link").href = movieData.imdb_url;

        // Show trailer link if available
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

        // Show the main section after loading movie details
        document.getElementById("section").classList.remove("hidden");
    } catch (error) {
        console.error("Error fetching random movie:", error);
    }
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
document.getElementById("trailer_popup_close").onclick = function() {
    document.getElementById("trailer_iframe").src = ""; // Stop the trailer video
    document.getElementById("trailer_popup").classList.add("hidden");
};

// Event listener for WATCH button to show client prompt
document.getElementById("btn_watch").onclick = function() {
    showClients();
};

// Event listener for NEXT button to show next random movie
document.getElementById("btn_next_movie").onclick = function() {
    showRandomMovie();
};

// Event listener for TURN ON DEVICE button to show device prompt
document.getElementById("btn_start_appletv").onclick = function() {
    showDevices();
};
