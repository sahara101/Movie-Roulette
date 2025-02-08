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
const isScreensaverMode = window.settings?.features?.poster_mode === 'screensaver';
const isPWA = (() => {
    const isStandalone = window.matchMedia('(display-mode: standalone)').matches;
    const isIOSPWA = window.navigator.standalone;
    const isAndroidPWA = document.referrer.includes('android-app://');
    return isStandalone || isIOSPWA || isAndroidPWA;
})();

// Get the initial movie data from the template
const initialStartTime = startTimeFromServer || null;  // This will be set from the template
let startTime = initialStartTime;
let currentStatus = 'UNKNOWN';
let playbackInterval;
let configuredTimezone;
let sessionType = 'NEW';

// Socket.IO connection
const socket = io('/poster', {
    transports: ['websocket'],
    upgrade: false,
    reconnection: true,
    reconnectionAttempts: 5,
    reconnectionDelay: 1000
});

socket.on('connect', function() {
    console.log('Connected to WebSocket');
    fetchTimezoneConfig();  // Move this first
    
    // If we had an active movie, restore the display
    if (movieId) {
        posterContainer.classList.remove('screensaver');
        window.settings.features.poster_mode = 'default';
        document.querySelectorAll('.movie-info').forEach(el => {
            if (el) el.style.display = 'flex';
        });
        
        // Add this block to maintain correct time on reconnect
        if (startTime) {
            updateTimes(startTime, 0, currentStatus);
        }
        
        fetchPlaybackState();
    }
});

socket.on('movie_changed', function(data) {
    console.log('Movie changed:', data);
    isDefaultPoster = false;
    
    // First, reset all classes and states
    posterContainer.classList.remove('screensaver', 'default-poster');
    
    // Hide custom text container explicitly
    if (customTextContainer) {
        customTextContainer.style.display = 'none';
    }

    // Show all movie info elements
    document.querySelectorAll('.movie-info').forEach(el => {
        if (el) el.style.display = 'flex';
    });

    // Update all data
    movieId = data.movie.id;
    movieDuration = data.duration_hours * 3600 + data.duration_minutes * 60;
    startTime = data.start_time;
    sessionType = data.session_type || 'NEW';
    resumePosition = data.resume_position || 0;
    
    // Update visual elements
    posterImage.src = data.movie.poster;
    if (contentRatingElement) contentRatingElement.textContent = data.movie.contentRating || '';
    if (videoFormatElement) videoFormatElement.textContent = data.movie.videoFormat || '';
    if (audioFormatElement) audioFormatElement.textContent = data.movie.audioFormat || '';
    if (playbackStatusElement) playbackStatusElement.textContent = 'NOW PLAYING';
    
    // Initialize times
    updateTimes(startTime, resumePosition, 'PLAYING');
    updatePlaybackStatus('playing');
    
    // Start polling
    clearInterval(playbackInterval);
    playbackInterval = setInterval(fetchPlaybackState, 2000);
});

socket.on('set_default_poster', function(data) {
    console.log('Setting default poster:', data);

    // Clear any existing mode classes first
    posterContainer.classList.remove('screensaver');
    posterContainer.classList.add('default-poster');
    window.settings.features.poster_mode = 'default';

    // Set poster
    posterImage.src = data.poster;
    isDefaultPoster = true;

    // Hide ALL movie info
    document.querySelectorAll('.movie-info').forEach(el => {
        if (el) el.style.display = 'none';
    });

    // Reset movie info text content
    if (startTimeElement) startTimeElement.textContent = '';
    if (endTimeElement) endTimeElement.textContent = '';
    if (playbackStatusElement) playbackStatusElement.textContent = '';
    if (contentRatingElement) contentRatingElement.textContent = '';
    if (videoFormatElement) videoFormatElement.textContent = '';
    if (audioFormatElement) audioFormatElement.textContent = '';

    // Clear state
    movieId = null;
    movieDuration = 0;
    startTime = null;
    currentStatus = 'UNKNOWN';
    clearInterval(playbackInterval);

    // Show and adjust custom text if available
    if (customTextContainer && data.custom_text !== undefined) {
        customTextContainer.style.display = 'flex';
        customText.innerHTML = data.custom_text;
        // Wait for next frame to ensure container is visible
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

        // If we have an active movie
        if (!isDefaultPoster && !isScreensaverMode && movieId) {
            // Refresh playback state which will update all times
            fetchPlaybackState();
        } else {
            // For default poster mode, update custom text
            if (data.custom_text !== undefined && customText) {
                customText.innerHTML = data.custom_text;
                adjustCustomText();
            }
        }
    }

    // Handle mode changes
    if (data.poster_mode === 'default') {
        // Switching to default poster mode
        posterContainer.classList.remove('screensaver');
        posterContainer.classList.add('default-poster');
        window.settings.features.poster_mode = 'default';
        
        // Show custom text
        if (customTextContainer) {
            customTextContainer.style.display = 'flex';
            if (data.custom_text !== undefined && customText) {
                customText.innerHTML = data.custom_text;
                adjustCustomText();
            }
        }

        // Ensure poster gets full height
        if (posterImage) {
            posterImage.style.maxHeight = '100vh';
        }
    } else if (data.poster_mode === 'screensaver') {
        // Similar sizing for screensaver mode
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

    // Immediately set screensaver mode and classes
    window.settings.features.poster_mode = 'screensaver';
    posterContainer.classList.remove('default-poster');
    posterContainer.classList.add('screensaver');

    // Ensure custom text is hidden in screensaver mode
    if (customTextContainer) {
        customTextContainer.style.display = 'none';
    }

    // Store current src for fallback
    const currentSrc = posterImage.src;

    function handleImageLoad() {
        console.log('New poster loaded successfully');
        posterImage.style.opacity = '1';

        // Hide all movie info elements
        document.querySelectorAll('.movie-info').forEach(el => {
            if (el) el.style.display = 'none';
        });

        // Clear movie state
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

    // Start transition
    posterImage.style.opacity = '0';

    // Set up one-time event listeners
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

    // Update the source after a short delay to allow fade out
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
        // The disconnection was initiated by the server, you need to reconnect manually
        socket.connect();
    }
    // Else the socket will automatically try to reconnect
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
            // Wait for next frame to ensure container is visible
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    adjustCustomText();
                });
            });
        }
    } else {
        // Movie playing mode
        posterContainer.classList.remove('default-poster', 'screensaver');
        if (customTextContainer) customTextContainer.style.display = 'none';
    }
}

function adjustCustomText() {
    // Skip if in screensaver mode or elements don't exist
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

    if (!isScreensaverMode) {
        if (contentRatingElement) contentRatingElement.textContent = movieData.movie.contentRating;
        if (videoFormatElement) videoFormatElement.textContent = movieData.movie.videoFormat;
        if (audioFormatElement) audioFormatElement.textContent = movieData.movie.audioFormat;

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
    if (!start || !startTimeElement || !endTimeElement) {
        console.log('Missing required data for updateTimes', { start, status });
        return;
    }

    if (status === 'STOPPED') {
        startTimeElement.textContent = '--:--';
        endTimeElement.textContent = '--:--';
        return;
    }

    // Always show start time if we have it
    startTimeElement.textContent = formatDateToTime(startTime);

    try {
        if (movieDuration) {
            const currentTime = new Date();
            
            // Calculate remaining duration based on current position
            const remainingDuration = movieDuration - position;
            
            // Calculate end time based on current time + remaining duration
            // This ensures it's accurate even after pauses/seeks
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

            // Only process if we have valid data
            if (data.status) {
                if (data.session_type) {
                    sessionType = data.session_type;
                }

                updatePlaybackStatus(data.status);

                // Update progress and times if we have position data
                if (typeof data.position !== 'undefined') {
                    updateProgress(data.position);
                    updateTimes(startTime, data.position, data.status);
                }
            }
        })
        .catch(error => {
            console.error('Error:', error);
            checkCurrentPoster();
        });
}

// Enhanced resize handler
function handleResize() {
    // Force multiple checks for PWA
    const checkCount = isPWA ? 3 : 1;

    function doResize(iteration = 0) {
        const vh = window.innerHeight;
        document.documentElement.style.setProperty('--viewport-height', `${vh}px`);
        document.documentElement.style.setProperty('--safe-height', `${vh}px`);

        // Force layout recalculation
        document.body.style.height = '100%';
        document.body.style.height = '';

        if (customTextContainer && customText) {
            adjustCustomText();
        }

        // For PWA, do multiple checks
        if (isPWA && iteration < checkCount) {
            setTimeout(() => doResize(iteration + 1), 100);
        }
    }

    doResize();
}

function initialize() {
    fetchTimezoneConfig();

    // Force immediate resize for PWA
    if (isPWA) {
        handleResize();
        // Additional resize checks specifically for PWA launch
        setTimeout(handleResize, 100);
        setTimeout(handleResize, 500);
        setTimeout(handleResize, 1000);
    }

    // Rest of your initialization code...
    if (isScreensaverMode && !movieId) {
        posterContainer.classList.add('screensaver');
        posterContainer.classList.remove('default-poster');
        if (customTextContainer) customTextContainer.style.display = 'none';
    } else if (isDefaultPoster) {
        posterContainer.classList.add('default-poster');
        posterContainer.classList.remove('screensaver');
        if (customTextContainer && window.settings?.features?.poster_mode === 'default') {
            customTextContainer.style.display = 'flex';
            if (isPWA) {
                // More aggressive resize checks for PWA
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

    // Start playback monitoring if needed
    if (!isDefaultPoster && movieId) {
        fetchPlaybackState();
        playbackInterval = setInterval(fetchPlaybackState, 2000);
    }
}

// PWA specific handlers
if (isPWA) {
    window.addEventListener('load', () => {
        handleResize();
        // Additional checks for PWA
        [100, 500, 1000].forEach(delay =>
            setTimeout(handleResize, delay)
        );
    });
}

// Common event listeners (don't duplicate these)
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
