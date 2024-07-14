window.onload = document.getElementById('btn_watch').onclick = async function showMovieInHTML() {
    // Get movie data from Flask API
    var response = await fetch('/random_movie');
    var py_movie = await response.json();

    // After loading all data, show content of the app
    document.getElementById("section").classList.remove("hidden");

    // Changing data in HTML to movie details:
    // Title
    document.getElementById("title").innerHTML = py_movie["title"];

    // Year and duration
    document.getElementById("year_duration").innerHTML = py_movie["year"] + " <span style=\"font-weight:300\">|</span> " + py_movie["duration_hours"] + "h" + " " + py_movie["duration_minutes"] + "m";

    // Director/s
    var directors_p = document.getElementById("directors");
    directors_p.innerHTML = "<span style=\"font-weight:700\">Directed by:</span>";
    py_movie["directors"].forEach(element => {
        directors_p.innerHTML += " " + element + ", ";
    });
    directors_p.innerHTML = directors_p.innerHTML.replace(/(\s+)?..$/, '');

    // Writer/s
    var writers_p = document.getElementById("writers");
    writers_p.innerHTML = "<span style=\"font-weight:700\">Written by:</span>";
    py_movie["writers"].forEach(element => {
        writers_p.innerHTML += " " + element + ", ";
    });
    writers_p.innerHTML = writers_p.innerHTML.replace(/(\s+)?..$/, '');

    // Actors
    var actors_p = document.getElementById("actors");
    actors_p.innerHTML = "<span style=\"font-weight:700\">Cast:</span>";
    py_movie["actors"].forEach(element => {
        actors_p.innerHTML += " " + element + ", ";
    });
    actors_p.innerHTML = actors_p.innerHTML.replace(/(\s+)?..$/, '');

	// Description
    document.getElementById("description").innerHTML = "<span style=\"font-weight:700\">Description:</span> " + py_movie["description"];

    // Poster
    document.getElementById("poster_img").src = py_movie["poster"];

    // BG Art
    document.getElementById("img_background").style.background = 'url(' + py_movie["background"] + ')';

    // Update TMDB, IMDB and Trakt links
    document.getElementById("tmdb_link").href = py_movie["tmdb_url"];
    document.getElementById("trakt_link").href = py_movie["trakt_url"];
    document.getElementById("imdb_link").href = py_movie["imdb_url"];
    // Update trailer button with trailer URL
    if (py_movie["trailer_url"]) {
        document.getElementById("trailer_link").onclick = function() {
            var trailerPopup = document.getElementById("trailer_popup");
            var trailerIframe = document.getElementById("trailer_iframe");
            trailerIframe.src = py_movie["trailer_url"];
            trailerPopup.classList.remove("hidden");
        };
    }
};

// This sections makes the "WATCH" button work...
// Hides client prompt
function closeClientPrompt() {
    document.getElementById("client_prompt").classList.add("hidden");
}

// Takes list of clients and display them as options for choosing where to watch content
document.getElementById("btn_next_movie").addEventListener("click", async function() {
    // Get list of clients from Flask API
    var response = await fetch('/clients');
    var clients = await response.json();

    // Clear the list of clients
    document.getElementById("list_of_clients").innerHTML = "";
    // Make client prompt visible
    document.getElementById("client_prompt").classList.remove("hidden");

    // For each client make new div
    clients.forEach(client => {
        document.getElementById("list_of_clients").innerHTML += 
		`<div class="client" onclick="playMovie('${client.title}', '${client.address}', '${client.port}');closeClientPrompt()">
                <p>${client.title}</p>
            </div>`;
    });
});

function playMovie(client, address, port) {
    // Play movie on the specified client using Flask API
    fetch(`/play_movie/${client}?address=${address}&port=${port}`)
        .then(response => response.json())
        .then(data => console.log(data)); // Optionally handle response
}

// Event listener to close trailer popup
    document.getElementById("trailer_popup_close").onclick = function() {
        document.getElementById("trailer_popup").classList.add("hidden");
        document.getElementById("trailer_iframe").src = "";
    };

// This section makes the "START APPLE TV" button work...
document.getElementById("btn_start_appletv").addEventListener("click", async function() {
    // Start Apple TV using Flask API
    fetch('/start_apple_tv')
        .then(response => response.json())
        .then(data => console.log(data)); // Optionally handle response
});
