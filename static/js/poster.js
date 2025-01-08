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

// Get the initial movie data from the template
const initialStartTime = startTimeFromServer || null;  // This will be set from the template
let startTime = initialStartTime;
let currentStatus = 'UNKNOWN';
let playbackInterval;
let configuredTimezone;
let sessionType = 'NEW';

// Socket.IO connection
const socket = io('/poster');

socket.on('connect', function() {
    console.log('Connected to WebSocket');
    fetchTimezoneConfig();
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

socket.on('settings_updated', function(data) {
    console.log('Settings updated:', data);

    if (data.timezone !== configuredTimezone) {
        console.log('Timezone changed from', configuredTimezone, 'to', data.timezone);
        configuredTimezone = data.timezone;

        // If we have an active movie
        if (!isDefaultPoster && movieId) {
            // Refresh playback state which will update all times
            fetchPlaybackState();
        } else {
            // For default poster, just reload the page
            location.reload();
        }
    }
});

function fetchTimezoneConfig() {
    fetch('/poster_settings')
        .then(response => response.json())
        .then(data => {
            configuredTimezone = data.timezone;
            console.log('Configured timezone:', configuredTimezone);
            if (startTime && !isDefaultPoster) {
                updateTimes(startTime, 0, currentStatus);
            }
        })
        .catch(error => console.error('Error fetching timezone config:', error));
}

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
    let fontSize = 100;

    textElement.style.fontSize = fontSize + 'px';

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

    // Store the original ISO string with timezone
    startTime = movieData.start_time;
    sessionType = movieData.session_type || 'NEW';
    resumePosition = movieData.resume_position || 0;

    console.log('Setting initial start time:', startTime);
    console.log('Session type:', sessionType);
    console.log('Resume position:', resumePosition);

    updateTimes(startTime, resumePosition, 'PLAYING');
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
    startTime = null;  // Clear the start time
}

function updateProgress(position) {
    if (movieDuration > 0) {
        let progress;
        if (sessionType === 'STOP') {
            // For STOP resume, calculate based on remaining duration
            const elapsedInCurrentSession = position - resumePosition;
            const remainingDuration = movieDuration - resumePosition;
            progress = ((resumePosition + elapsedInCurrentSession) / movieDuration) * 100;
        } else {
            // For NEW or PAUSE, use total duration from start
            progress = (position / movieDuration) * 100;
        }
        progressBar.style.width = `${Math.min(progress, 100)}%`;
    } else {
        progressBar.style.width = '0%';
    }
}

function formatDateToTime(isoString) {
    if (!configuredTimezone || !isoString) return '--:--';
    
    try {
        const date = new Date(isoString);
        console.log('Formatting date:', isoString, 'in timezone:', configuredTimezone);
        
        return date.toLocaleTimeString('en-US', {
            hour: 'numeric',
            minute: '2-digit',
            hour12: true,
            timeZone: configuredTimezone
        }).replace(/\s*(AM|PM)/, ' $1');
    } catch (e) {
        console.error('Error formatting time:', e);
        return '--:--';
    }
}

function updateTimes(start, position, status) {
    if (status === 'STOPPED' || !start) {
        startTimeElement.textContent = '--:--';
        endTimeElement.textContent = '--:--';
        return;
    }

    // Format start time
    startTimeElement.textContent = formatDateToTime(start);

    // Calculate and format end time
    try {
        const currentTime = new Date();
        const remainingDuration = movieDuration - position;
        let endDate;

        // Same calculation for both PLAYING and PAUSED
        endDate = new Date(currentTime.getTime() + (remainingDuration * 1000));

        endTimeElement.textContent = formatDateToTime(endDate.toISOString());
    } catch (e) {
        console.error('Error calculating end time:', e);
        endTimeElement.textContent = '--:--';
    }
}

function updatePlaybackStatus(status) {
    playbackStatusElement.classList.remove('paused', 'ending', 'stopped');

    switch(status.toLowerCase()) {
        case 'playing':
            playbackStatusElement.textContent = "NOW PLAYING";
            playbackStatusElement.classList.remove('paused', 'ending', 'stopped');
            currentStatus = 'PLAYING';
            break;
        case 'paused':
            playbackStatusElement.textContent = "PAUSED";
            playbackStatusElement.classList.add('paused');
            playbackStatusElement.classList.remove('ending', 'stopped');
            currentStatus = 'PAUSED';
            break;
        case 'ending':
            playbackStatusElement.textContent = "ENDING";
            playbackStatusElement.classList.add('ending');
            playbackStatusElement.classList.remove('paused', 'stopped');
            currentStatus = 'ENDING';
            break;
        case 'stopped':
            playbackStatusElement.textContent = "STOPPED";
            playbackStatusElement.classList.add('stopped');
            playbackStatusElement.classList.remove('paused', 'ending');
            currentStatus = 'STOPPED';
            break;
        default:
            playbackStatusElement.textContent = status.toUpperCase();
            playbackStatusElement.classList.remove('paused', 'ending', 'stopped');
            currentStatus = 'UNKNOWN';
    }

    // Only clear times if we don't have a valid start time
    if (currentStatus === 'STOPPED' && !startTime) {
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
            console.log('Received playback state:', data);
            
            // Update session type if provided
            if (data.session_type) {
                sessionType = data.session_type;
            }
            
            updateProgress(data.position);
            updatePlaybackStatus(data.status);

            if (data.status.toUpperCase() === 'STOPPED') {
                startTimeElement.textContent = '--:--';
                endTimeElement.textContent = '--:--';
            } else {
                const timeToUse = startTime || data.start_time;
                updateTimes(timeToUse, data.position, data.status.toUpperCase());
            }
        })
        .catch(error => {
            console.error('Error:', error);
            checkCurrentPoster();
        });
}

function initialize() {
    updatePosterDisplay();
    fetchTimezoneConfig();
    if (!isDefaultPoster && movieId) {
        fetchPlaybackState();
        playbackInterval = setInterval(fetchPlaybackState, 2000);
    }
}

window.addEventListener('load', initialize);
window.addEventListener('resize', adjustCustomText);
