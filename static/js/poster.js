const posterContainer = document.getElementById('posterContainer');
const progressBar = document.getElementById('progress-bar');
const startTimeElement = document.getElementById('start-time');
const endTimeElement = document.getElementById('end-time');
const playbackStatusElement = document.getElementById('playback-status');
const posterImage = document.getElementById('poster-image');
const contentRatingElement = document.getElementById('content-rating');
const videoFormatElement = document.getElementById('video-format');
const audioFormatElement = document.getElementById('audio-format');
const customTextContainer = document.getElementById('custom-text-container');
const customText = document.getElementById('custom-text');

let startTime;
let currentStatus = 'UNKNOWN'; // Track current status
let playbackInterval;

// Socket.IO connection
const socket = io('/poster');

socket.on('connect', function() {
    console.log('Connected to WebSocket');
});

socket.on('movie_changed', function(data) {
    console.log('Movie changed:', data);
    isDefaultPoster = false;
    updatePoster(data);
    updatePosterDisplay();
});

socket.on('set_default_poster', function(data) {
    console.log('Setting default poster:', data);
    posterImage.src = data.poster;
    isDefaultPoster = true;
    updatePosterDisplay();
    clearMovieInfo();
});

function updatePosterDisplay() {
    if (isDefaultPoster) {
        posterContainer.classList.add('default-poster');
        customTextContainer.style.display = 'flex';
        adjustCustomText();
    } else {
        posterContainer.classList.remove('default-poster');
        customTextContainer.style.display = 'none';
    }
}

function adjustCustomText() {
    const container = customTextContainer;
    const textElement = customText;
    let fontSize = 100; // Start with a large font size

    textElement.style.fontSize = fontSize + 'px';

    // Reduce font size until text fits within the container
    while ((textElement.scrollWidth > container.clientWidth || textElement.scrollHeight > container.clientHeight) && fontSize > 10) {
        fontSize -= 1;
        textElement.style.fontSize = fontSize + 'px';
    }
}

function updatePoster(movieData) {
    document.title = `Now Playing - ${movieData.movie.title}`;
    movieId = movieData.movie.id;
    movieDuration = movieData.duration_hours * 3600 + movieData.duration_minutes * 60;
    posterImage.src = movieData.movie.poster;
    contentRatingElement.textContent = movieData.movie.contentRating;
    videoFormatElement.textContent = movieData.movie.videoFormat;
    audioFormatElement.textContent = movieData.movie.audioFormat;
    startTime = new Date(movieData.start_time);
    updateTimes(movieData.start_time, 0, 'PLAYING'); // Assume status is PLAYING initially
    updatePlaybackStatus('playing');
    clearInterval(playbackInterval);
    playbackInterval = setInterval(fetchPlaybackState, 2000);
}

function clearMovieInfo() {
    document.title = 'Now Playing';
    movieId = null;
    movieDuration = 0;
    contentRatingElement.textContent = '';
    videoFormatElement.textContent = '';
    audioFormatElement.textContent = '';
    startTimeElement.textContent = '--:--';
    endTimeElement.textContent = '--:--';
    progressBar.style.width = '0%';
    clearInterval(playbackInterval);
}

function updateProgress(position) {
    if (movieDuration > 0) {
        const progress = (position / movieDuration) * 100;
        progressBar.style.width = `${progress}%`;
    } else {
        progressBar.style.width = '0%';
    }
}

function updateTimes(start, position, status) {
    if (status === 'STOPPED') {
        startTimeElement.textContent = '--:--';
        endTimeElement.textContent = '--:--';
        return;
    }

    const formatTime = (time) => new Date(time).toLocaleTimeString([], {hour: 'numeric', minute:'2-digit', hour12: true}).replace('am', 'AM').replace('pm', 'PM');

    if (!startTime) {
        startTime = new Date(start);
    }
    startTimeElement.textContent = formatTime(startTime);

    const currentTime = new Date();
    const remainingDuration = movieDuration - position;
    const newEndTime = new Date(currentTime.getTime() + remainingDuration * 1000);
    endTimeElement.textContent = formatTime(newEndTime);
}

function updatePlaybackStatus(status) {
    playbackStatusElement.classList.remove('paused', 'ended', 'stopped');

    switch(status.toLowerCase()) {
        case 'playing':
            playbackStatusElement.textContent = "NOW PLAYING";
            playbackStatusElement.classList.remove('paused', 'ended', 'stopped');
            currentStatus = 'PLAYING';
            break;
        case 'paused':
            playbackStatusElement.textContent = "PAUSED";
            playbackStatusElement.classList.add('paused');
            playbackStatusElement.classList.remove('ended', 'stopped');
            currentStatus = 'PAUSED';
            break;
        case 'ended':
            playbackStatusElement.textContent = "ENDED";
            playbackStatusElement.classList.add('ended');
            playbackStatusElement.classList.remove('paused', 'stopped');
            currentStatus = 'ENDED';
            break;
        case 'stopped':
            playbackStatusElement.textContent = "STOPPED";
            playbackStatusElement.classList.add('stopped');
            playbackStatusElement.classList.remove('paused', 'ended');
            currentStatus = 'STOPPED';
            break;
        default:
            playbackStatusElement.textContent = status.toUpperCase();
            playbackStatusElement.classList.remove('paused', 'ended', 'stopped');
            currentStatus = 'UNKNOWN';
    }

    // If status is STOPPED, set times to --:--
    if (currentStatus === 'STOPPED') {
        startTimeElement.textContent = '--:--';
        endTimeElement.textContent = '--:--';
    }
}

function fetchPlaybackState() {
    if (!movieId) {
        return;
    }
    fetch(`/playback_state/${movieId}`)
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                console.error('Playback state error:', data.error);
                return;
            }
            updateProgress(data.position);
            updatePlaybackStatus(data.status);

            if (data.status.toUpperCase() === 'STOPPED') {
                // Set times to --:--
                startTimeElement.textContent = '--:--';
                endTimeElement.textContent = '--:--';
            } else {
                updateTimes(data.start_time, data.position, data.status.toUpperCase());
            }
        })
        .catch(error => {
            console.error('Error:', error);
            fetch('/current_poster')
                .then(response => response.json())
                .then(data => {
                    posterImage.src = data.poster;
                    isDefaultPoster = data.poster === defaultPosterUrl;
                    updatePosterDisplay();
                    clearMovieInfo();
                })
                .catch(error => console.error('Error fetching current poster:', error));
        });
}

function initialize() {
    updatePosterDisplay();
    if (!isDefaultPoster && movieId) {
        fetchPlaybackState();
        playbackInterval = setInterval(fetchPlaybackState, 2000);
    }
}

window.addEventListener('load', initialize);
window.addEventListener('resize', adjustCustomText);
