const posterContainer = document.getElementById('posterContainer');
const progressBar = document.getElementById('progress-bar');
const startTimeElement = document.getElementById('start-time');
const endTimeElement = document.getElementById('end-time');
const playbackStatusElement = document.getElementById('playback-status');
const posterImage = document.getElementById('poster-image');
const rotatingInfoItemElement = document.getElementById('rotatingInfoItem');
const customTextContainer = document.getElementById('custom-text-container');
const customText = document.getElementById('custom-text');
const isScreensaverMode = window.settings?.features?.poster_mode === 'screensaver';
const isPWA = (() => {
    const isStandalone = window.matchMedia('(display-mode: standalone)').matches;
    const isIOSPWA = window.navigator.standalone;
    const isAndroidPWA = document.referrer.includes('android-app://');
    return isStandalone || isIOSPWA || isAndroidPWA;
})();

const initialStartTime = startTimeFromServer || null;
let startTime = initialStartTime;
let currentStatus = 'UNKNOWN';
let playbackInterval;
let configuredTimezone;
let sessionType = 'NEW';
let infoRotationInterval;
let currentInfoIndex = 0;
const infoItems = [];
let currentPlaybackPositionSeconds = 0;

const socket = io('/poster', {
    transports: ['websocket'],
    upgrade: false,
    reconnection: true,
    reconnectionAttempts: 5,
    reconnectionDelay: 1000
});

socket.on('connect', function() {
    console.log('Connected to WebSocket');
    fetchTimezoneConfig();
    
    if (movieId) {
        posterContainer.classList.remove('screensaver');
        window.settings.features.poster_mode = 'default';
        document.querySelectorAll('.movie-info').forEach(el => {
            if (el) el.style.display = 'flex';
        });
        
        if (startTime) {
            updateTimes(startTime, 0, currentStatus);
        }
        
        fetchPlaybackState();
    }
});

socket.on('movie_changed', function(data) {
    console.log('Movie changed:', data);
    isDefaultPoster = false;
    
    posterContainer.classList.remove('screensaver', 'default-poster');
    
    if (customTextContainer) {
        customTextContainer.style.display = 'none';
    }

    document.querySelectorAll('.movie-info').forEach(el => {
        if (el) el.style.display = 'flex';
    });

    movieId = data.movie.id;
    movieDuration = data.duration_hours * 3600 + data.duration_minutes * 60;
    startTime = data.start_time;
    sessionType = data.session_type || 'NEW';
    resumePosition = data.resume_position || 0;
    currentPlaybackPositionSeconds = resumePosition || 0;
    
    posterImage.src = data.movie.poster;
    movieContentRating = data.movie.contentRating || null;
    movieVideoFormat = data.movie.videoFormat || null;
    movieAudioFormat = data.movie.audioFormat || null;
    
    setupInfoRotation();
    if (playbackStatusElement) playbackStatusElement.textContent = 'NOW PLAYING';
    
    updateTimes(startTime, resumePosition, 'PLAYING');
    updatePlaybackStatus('playing');
    
    clearInterval(playbackInterval);
    playbackInterval = setInterval(fetchPlaybackState, 2000);
});

socket.on('set_default_poster', function(data) {
    console.log('Setting default poster:', data);

    posterContainer.classList.remove('screensaver');
    posterContainer.classList.add('default-poster');
    window.settings.features.poster_mode = 'default';

    posterImage.src = data.poster;
    isDefaultPoster = true;

    document.querySelectorAll('.movie-info').forEach(el => {
        if (el) el.style.display = 'none';
    });

    if (startTimeElement) startTimeElement.textContent = '';
    if (endTimeElement) endTimeElement.textContent = '';
    if (playbackStatusElement) playbackStatusElement.textContent = '';
    
    if (rotatingInfoItemElement) rotatingInfoItemElement.innerHTML = '';
    clearInterval(infoRotationInterval);
    infoItems.length = 0;

    movieId = null;
    movieDuration = 0;
    startTime = null;
    currentStatus = 'UNKNOWN';
    currentPlaybackPositionSeconds = 0;
    clearInterval(playbackInterval);

    if (customTextContainer && data.custom_text !== undefined) {
        customTextContainer.style.display = 'flex';
        customText.innerHTML = data.custom_text;
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                adjustCustomText();
            });
        });
    }
});

socket.on('settings_updated', function(data) {
    console.log('Settings updated:', data);
    if (data.timezone !== configuredTimezone) {
        console.log('Timezone changed from', configuredTimezone, 'to', data.timezone);
        configuredTimezone = data.timezone;

        if (!isDefaultPoster && !isScreensaverMode && movieId) {
            fetchPlaybackState();
        } else {
            if (data.custom_text !== undefined && customText) {
                customText.innerHTML = data.custom_text;
                adjustCustomText();
            }
        }
    }

    if (data.poster_mode === 'default') {
        posterContainer.classList.remove('screensaver');
        posterContainer.classList.add('default-poster');
        window.settings.features.poster_mode = 'default';
        
        if (customTextContainer) {
            customTextContainer.style.display = 'flex';
            if (data.custom_text !== undefined && customText) {
                customText.innerHTML = data.custom_text;
                adjustCustomText();
            }
        }

        if (posterImage) {
            posterImage.style.maxHeight = '100vh';
        }
    } else if (data.poster_mode === 'screensaver') {
        posterContainer.classList.remove('default-poster');
        posterContainer.classList.add('screensaver');
        window.settings.features.poster_mode = 'screensaver';
        if (customTextContainer) {
            customTextContainer.style.display = 'none';
        }
        if (posterImage) {
            posterImage.style.maxHeight = '100vh';
        }
    }
});

socket.on('update_screensaver', function(data) {
    if (!data || !data.poster) {
        console.error('Invalid screensaver data received');
        return;
    }

    window.settings.features.poster_mode = 'screensaver';
    posterContainer.classList.remove('default-poster');
    posterContainer.classList.add('screensaver');

    if (customTextContainer) {
        customTextContainer.style.display = 'none';
    }

    const currentSrc = posterImage.src;

    function handleImageLoad() {
        console.log('New poster loaded successfully');
        posterImage.style.opacity = '1';

        document.querySelectorAll('.movie-info').forEach(el => {
            if (el) el.style.display = 'none';
        });

        movieId = null;
        movieDuration = 0;
        startTime = null;
        clearInterval(playbackInterval);
    }

    function handleImageError() {
        console.error('Failed to load new poster, reverting to previous');
        posterImage.src = currentSrc;
        posterImage.style.opacity = '1';
    }

    posterImage.style.opacity = '0';

    posterImage.onload = function() {
        handleImageLoad();
        posterImage.onload = null;
        posterImage.onerror = null;
    };

    posterImage.onerror = function() {
        handleImageError();
        posterImage.onload = null;
        posterImage.onerror = null;
    };

    setTimeout(() => {
        posterImage.src = data.poster;
    }, 500);
});

socket.on('connect_error', (error) => {
    console.error('Socket connection error:', error);
});

socket.on('error', (error) => {
    console.error('Socket error:', error);
});

socket.on('disconnect', (reason) => {
    console.log('Socket disconnected:', reason);
    if (reason === 'io server disconnect') {
        socket.connect();
    }
});

socket.on('reconnecting', (attemptNumber) => {
    console.log('Attempting to reconnect...', attemptNumber);
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
    if (isScreensaverMode && !movieId) {
        posterContainer.classList.add('screensaver');
        posterContainer.classList.remove('default-poster');
        if (customTextContainer) customTextContainer.style.display = 'none';
    } else if (isDefaultPoster) {
        posterContainer.classList.add('default-poster');
        posterContainer.classList.remove('screensaver');
        if (customTextContainer && window.settings?.features?.poster_mode === 'default') {
            customTextContainer.style.display = 'flex';
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    adjustCustomText();
                });
            });
        }
    } else {
        posterContainer.classList.remove('default-poster', 'screensaver');
        if (customTextContainer) customTextContainer.style.display = 'none';
    }
}

function adjustCustomText() {
    if (isScreensaverMode || !customTextContainer || !customText) return;
    
    let fontSize = 100;
    customText.style.fontSize = fontSize + 'px';

    while ((customText.scrollWidth > customTextContainer.clientWidth || 
            customText.scrollHeight > customTextContainer.clientHeight) && 
            fontSize > 10) {
        fontSize -= 1;
        customText.style.fontSize = fontSize + 'px';
    }
}

function updatePoster(movieData) {
    document.title = `Now Playing - ${movieData.movie.title}`;
    movieId = movieData.movie.id;
    movieDuration = movieData.duration_hours * 3600 + movieData.duration_minutes * 60;
    posterImage.src = movieData.movie.poster;

    movieContentRating = movieData.movie.contentRating || null;
    movieVideoFormat = movieData.movie.videoFormat || null;
    movieAudioFormat = movieData.movie.audioFormat || null;
    
    if (!isScreensaverMode) {
        startTime = movieData.start_time;
        sessionType = movieData.session_type || 'NEW';
        resumePosition = movieData.resume_position || 0;
        currentPlaybackPositionSeconds = resumePosition || 0;

        setupInfoRotation();

        console.log('Setting initial start time:', startTime);
        console.log('Session type:', sessionType);
        console.log('Resume position:', resumePosition);

        updateTimes(startTime, resumePosition, 'PLAYING');
        updatePlaybackStatus('playing');
        clearInterval(playbackInterval);
        playbackInterval = setInterval(fetchPlaybackState, 2000);
    }
}

function clearMovieInfo() {
    document.title = 'Now Playing';
    movieId = null;
    movieDuration = 0;
    currentPlaybackPositionSeconds = 0;
    if (rotatingInfoItemElement) rotatingInfoItemElement.innerHTML = '';
    clearInterval(infoRotationInterval);
    infoItems.length = 0;
    startTimeElement.textContent = '--:--';
    endTimeElement.textContent = '--:--';
    progressBar.style.width = '0%';
    clearInterval(playbackInterval);
    startTime = null;
}

function updateProgress(position) {
    if (movieDuration > 0) {
        let progress;
        if (sessionType === 'STOP') {
            const elapsedInCurrentSession = position - resumePosition;
            const remainingDuration = movieDuration - resumePosition;
            progress = ((resumePosition + elapsedInCurrentSession) / movieDuration) * 100;
        } else {
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
    if (!start || !startTimeElement || !endTimeElement) {
        console.log('Missing required data for updateTimes', { start, status });
        return;
    }

    if (status === 'STOPPED') {
        startTimeElement.textContent = '--:--';
        endTimeElement.textContent = '--:--';
        return;
    }

    startTimeElement.textContent = formatDateToTime(startTime);

    try {
        if (movieDuration) {
            const currentTime = new Date();
            
            const remainingDuration = movieDuration - position;
            
            const endDate = new Date(currentTime.getTime() + (remainingDuration * 1000));
            
            endTimeElement.textContent = formatDateToTime(endDate.toISOString());
            
            console.log('Time calculation:', {
                position: position,
                movieDuration: movieDuration,
                remainingDuration: remainingDuration,
                calculatedEndTime: endDate
            });
        } else {
            endTimeElement.textContent = '--:--';
        }
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

            if (data.status) {
                if (data.session_type) {
                    sessionType = data.session_type;
                }

                updatePlaybackStatus(data.status);

                if (typeof data.position !== 'undefined') {
                    currentPlaybackPositionSeconds = data.position;
                    updateProgress(data.position);
                    updateTimes(startTime, data.position, data.status);
                    if (rotatingInfoItemElement && infoItems[currentInfoIndex] && infoItems[currentInfoIndex].label === 'Time Left') {
                        const item = infoItems[currentInfoIndex];
                        const value = typeof item.valueGetter === 'function' ? item.valueGetter() : item.value;
                        rotatingInfoItemElement.innerHTML = `<span class="info-label">${item.label}</span><span class="info-value">${value}</span>`;
                    }
                }
            }
        })
        .catch(error => {
            console.error('Error:', error);
            checkCurrentPoster();
        });
}

function handleResize() {
    const checkCount = isPWA ? 3 : 1;

    function doResize(iteration = 0) {
        const vh = window.innerHeight;
        document.documentElement.style.setProperty('--viewport-height', `${vh}px`);
        document.documentElement.style.setProperty('--safe-height', `${vh}px`);

        document.body.style.height = '100%';
        document.body.style.height = '';

        if (customTextContainer && customText) {
            adjustCustomText();
        }

        if (isPWA && iteration < checkCount) {
            setTimeout(() => doResize(iteration + 1), 100);
        }
    }

    doResize();
}

function initialize() {
    fetchTimezoneConfig();

    if (isPWA) {
        handleResize();
        setTimeout(handleResize, 100);
        setTimeout(handleResize, 500);
        setTimeout(handleResize, 1000);
    }

    if (movieId && !isDefaultPoster && !isScreensaverMode) {
        setupInfoRotation();
    }

    if (isScreensaverMode && !movieId) {
        posterContainer.classList.add('screensaver');
        posterContainer.classList.remove('default-poster');
        if (rotatingInfoItemElement) rotatingInfoItemElement.innerHTML = '';
        clearInterval(infoRotationInterval);
        if (customTextContainer) customTextContainer.style.display = 'none';
    } else if (isDefaultPoster) {
        posterContainer.classList.add('default-poster');
        posterContainer.classList.remove('screensaver');
        if (rotatingInfoItemElement) rotatingInfoItemElement.innerHTML = '';
        clearInterval(infoRotationInterval);
        if (customTextContainer && window.settings?.features?.poster_mode === 'default') {
            customTextContainer.style.display = 'flex';
            if (isPWA) {
                const checkResize = () => {
                    handleResize();
                    adjustCustomText();
                };
                setTimeout(checkResize, 0);
                setTimeout(checkResize, 100);
                setTimeout(checkResize, 300);
            } else {
                setTimeout(() => {
                    requestAnimationFrame(() => {
                        requestAnimationFrame(() => {
                            adjustCustomText();
                        });
                    });
                }, 100);
            }
        }
    }

    if (!isDefaultPoster && movieId) {
        fetchPlaybackState();
        playbackInterval = setInterval(fetchPlaybackState, 2000);
    }
}

function setupInfoRotation() {
    if (!rotatingInfoItemElement) return;

    clearInterval(infoRotationInterval);
    infoItems.length = 0;

    if (movieContentRating) {
        infoItems.push({ label: 'Rating', value: movieContentRating });
    }
    if (movieVideoFormat) {
        infoItems.push({ label: 'Video', value: movieVideoFormat });
    }
    if (movieAudioFormat) {
        infoItems.push({ label: 'Audio', value: movieAudioFormat });
    }
    if (movieId && movieDuration > 0) {
        infoItems.push({
            label: 'Time Left',
            valueGetter: () => formatRemainingTime(movieDuration - currentPlaybackPositionSeconds)
        });
    }

    if (infoItems.length === 0) {
        rotatingInfoItemElement.innerHTML = '';
        return;
    }

    currentInfoIndex = 0;

    function displayNextInfo() {
        if (infoItems.length === 0) {
            rotatingInfoItemElement.innerHTML = '';
            return;
        }
        const item = infoItems[currentInfoIndex];
        const value = typeof item.valueGetter === 'function' ? item.valueGetter() : item.value;
        rotatingInfoItemElement.innerHTML = `<span class="info-label">${item.label}</span><span class="info-value">${value}</span>`;
        currentInfoIndex = (currentInfoIndex + 1) % infoItems.length;
    }

    displayNextInfo();
    if (infoItems.length > 1) {
        infoRotationInterval = setInterval(displayNextInfo, 10000);
    }
}

function formatRemainingTime(totalSeconds) {
    if (totalSeconds < 0) totalSeconds = 0;

    if (totalSeconds === 0) {
        return "0m";
    }

    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);

    let parts = [];
    if (hours > 0) {
        parts.push(`${hours}h`);
        parts.push(`${minutes}m`);
    } else {
        if (minutes > 0) {
            parts.push(`${minutes}m`);
        } else {
            parts.push("1m");
        }
    }
    return parts.join(' ');
}

if (isPWA) {
    window.addEventListener('load', () => {
        handleResize();
        [100, 500, 1000].forEach(delay =>
            setTimeout(handleResize, delay)
        );
    });
}

window.addEventListener('DOMContentLoaded', initialize);
window.addEventListener('orientationchange', () => {
    handleResize();
    setTimeout(handleResize, 300);
});
window.addEventListener('resize', () => {
    handleResize();
    adjustCustomText();
});
document.addEventListener('visibilitychange', handleResize);
window.matchMedia('(display-mode: standalone)').addEventListener('change', handleResize);
