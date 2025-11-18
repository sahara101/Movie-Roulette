document.addEventListener('DOMContentLoaded', function() {
    const collectionGrid = document.getElementById('collection-grid');
    const searchInput = document.getElementById('search-collections');
    const clearSearchBtn = document.getElementById('clear-search-btn');
    const randomButton = document.getElementById('random-collection-btn');
    const loadingOverlay = document.getElementById('loading-overlay');
    const loadingStatus = document.querySelector('.loading-status');
    const loadingCount = document.querySelector('.loading-count');
    const loadingProgress = document.getElementById('loading-progress');

    const socket = io();

    socket.on('collections_cache_progress', function(data) {
        loadingOverlay.classList.remove('hidden');
        const progress = data.progress || 0;
        loadingProgress.style.width = progress + '%';
        loadingStatus.textContent = 'Building collections cache';
        loadingCount.textContent = `${Math.round(progress)}%`;
    });

    socket.on('collections_cache_complete', function() {
        loadingOverlay.classList.add('hidden');
        fetchCollections();
    });

    let allCollections = [];

    function fetchCollections() {
        fetch('/current_service')
            .then(response => response.json())
            .then(serviceData => {
                const serviceName = serviceData.service;
                if (!serviceName) {
                    console.error("Could not determine the current service.");
                    return;
                }
                fetch(`/api/collections?service_name=${serviceName}`)
                    .then(response => {
                        if (response.status === 202) {
                            return response.json().then(data => {
                                if (data.status === 'retry') {
                                    setTimeout(fetchCollections, 500);
                                } else {
                                    loadingOverlay.classList.remove('hidden');
                                }
                                return null;
                            });
                        }
                        return response.json();
                    })
                    .then(data => {
                        if (data && data.collections) {
                            allCollections = data.collections;
                            displayCollections(allCollections);
                        }
                    });
            });
    }

    function displayCollections(collections) {
        collectionGrid.innerHTML = '';
        collections.forEach(collection => {
            const card = document.createElement('div');
            card.classList.add('collection-card');
            card.dataset.collectionId = collection.id;

            const cardLeft = document.createElement('div');
            cardLeft.classList.add('card_left');
            const img = document.createElement('img');
            if (collection.poster_path) {
                img.src = `https://image.tmdb.org/t/p/w500${collection.poster_path}`;
            } else {
                img.src = '/static/images/default_poster.png';
                img.classList.add('no-poster');
            }
            img.alt = collection.name;
            cardLeft.appendChild(img);

            const cardRight = document.createElement('div');
            cardRight.classList.add('card_right');

            const title = document.createElement('h1');
            title.textContent = collection.name;
            cardRight.appendChild(title);

            const details = document.createElement('div');
            details.classList.add('card_right__details');

            const review = document.createElement('div');
            review.classList.add('card_right__review');
            const p = document.createElement('p');
            const overview = collection.overview || '';
            
            if (overview) {
                p.textContent = overview;
                review.appendChild(p);

                setTimeout(() => {
                    if (p.scrollHeight > p.clientHeight) {
                        const readMore = document.createElement('a');
                        readMore.href = `https://www.themoviedb.org/collection/${collection.id}`;
                        readMore.target = '_blank';
                        readMore.textContent = 'Read more';
                        readMore.classList.add('read-more-link');
                        review.appendChild(readMore);
                    }
                }, 0);
            } else {
                p.textContent = 'No overview available.';
                review.appendChild(p);
            }
            details.appendChild(review);
            cardRight.appendChild(details);

            card.appendChild(cardLeft);
            card.appendChild(cardRight);
            collectionGrid.appendChild(card);

            card.addEventListener('click', (event) => {
                if (event.target.classList.contains('read-more-link')) {
                    return;
                }
                openCollectionModal(collection);
            });

            const readMoreLink = card.querySelector('.read-more-link');
            if (readMoreLink) {
                readMoreLink.addEventListener('click', (event) => {
                    event.stopPropagation();
                });
            }
        });
    }

    async function openCollectionModal(collectionInfo) {
        const modalContainer = document.getElementById('collection_modal');
        const infoContainer = document.getElementById('collection_info_container');

        if (collectionInfo.movies.length === 2) {
            modalContainer.classList.add('two-movie-collection');
        } else {
            modalContainer.classList.remove('two-movie-collection');
        }
    
        const requestServiceStatus = await checkRequestServiceAvailability();
        const isRequestServiceAvailable = requestServiceStatus.available;
    
        let requestServiceName = "";
        if (isRequestServiceAvailable) {
            switch(requestServiceStatus.service) {
                case 'overseerr':
                    requestServiceName = "Overseerr";
                    break;
                case 'jellyseerr':
                    requestServiceName = "Jellyseerr";
                    break;
                case 'ombi':
                    requestServiceName = "Ombi";
                    break;
                default:
                    requestServiceName = requestServiceStatus.service || "";
            }
        }
    
        const moviesToRequest = collectionInfo.movies.filter(movie => !movie.in_library && !movie.is_requested);

        collectionInfo.movies.sort((a, b) => {
            const dateA = a.release_date ? new Date(a.release_date) : new Date('9999-12-31');
            const dateB = b.release_date ? new Date(b.release_date) : new Date('9999-12-31');
            return dateA - dateB;
        });
    
        const createRequestIcon = (movie) => {
            if (isRequestServiceAvailable && !movie.in_library && !movie.is_requested) {
                return `
                    <span class="request-icon-span" data-movie-id="${movie.id}" title="Request ${movie.title} using ${requestServiceName}">
                        <svg class="request-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" width="18px" height="18px">
                            <path d="M0 0h24v24H0z" fill="none"/>
                            <path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/>
                        </svg>
                    </span>`;
            }
            return '';
        };
    
        infoContainer.innerHTML = `
            <div class="collection-info-header">
                <h3>Part of ${collectionInfo.name}</h3>
            </div>
            <div class="collection-movies">
                ${collectionInfo.movies.map(movie => {
                    const year = movie.release_date ? ` (${movie.release_date.substring(0, 4)})` : '';
                    const posterPath = movie.poster_path ? `https://image.tmdb.org/t/p/w500${movie.poster_path}` : '/static/images/default_poster.png';
                    
                    let statusHTML;
                    const movieTitleHTML = !movie.in_library ?
                        `<a href="https://www.themoviedb.org/movie/${movie.id}" target="_blank" rel="noopener noreferrer" class="movie-title-link"><span class="movie-title">${movie.title}${year}</span></a>` :
                        `<span class="movie-title">${movie.title}${year}</span>`;
                    
                    const overview = movie.overview || 'No overview available.';
                    let truncatedOverview = overview;
                    let readMoreHTML = '';

                    const lines = overview.split('\n');
                    if (lines.length > 5) {
                        truncatedOverview = lines.slice(0, 5).join('\n') + '...';
                        readMoreHTML = `<a href="https://www.themoviedb.org/movie/${movie.id}" target="_blank" class="read-more-link">Read more</a>`;
                    } else if (overview.length > 150) {
                        truncatedOverview = overview.substring(0, 150) + '...';
                        readMoreHTML = `<a href="https://www.themoviedb.org/movie/${movie.id}" target="_blank" class="read-more-link">Read more</a>`;
                    }

                    switch (movie.status) {
                        case 'In Library':
                            statusHTML = `<button class="action-button watch-button" onclick="showClientsForPoster(${movie.id})">Watch</button>`;
                            break;
                        case 'Watched':
                            if (movie.in_library) {
                                statusHTML = `<button class="action-button watch-button" onclick="showClientsForPoster(${movie.id})">Watch Again</button>`;
                            } else {
                                statusHTML = `<span class="movie-status status-watched">Watched on Trakt</span><button class="action-button request-button" data-movie-id="${movie.id}">Request</button>`;
                            }
                            break;
                        case 'Requested':
                            statusHTML = `<span class="movie-status status-requested">Requested</span>`;
                            break;
                        case 'Request Watched':
                             statusHTML = `<span class="movie-status status-watched">Watched on Trakt</span><button class="action-button request-button" data-movie-id="${movie.id}">Request</button>`;
                             break;
                        default:
                            statusHTML = `<button class="action-button request-button" data-movie-id="${movie.id}">Request</button>`;
                            break;
                    }

                    return `
                        <div class="collection-card modal-movie-card">
                            <div class="card_left">
                                <img src="${posterPath}" alt="${movie.title}">
                            </div>
                            <div class="card_right">
                                <h1>${movie.title}${year}</h1>
                                <div class="card_right__details">
                                    <div class="card_right__review">
                                        <p>${truncatedOverview}</p>
                                        ${readMoreHTML}
                                    </div>
                                    <div class="collection-movie-actions">
                                        ${statusHTML}
                                    </div>
                                </div>
                            </div>
                        </div>
                    `;
                }).join('')}
            </div>
            <div class="action-buttons">
                ${moviesToRequest.length > 0 ?
                    `<button class="action-button request-button${!isRequestServiceAvailable ? ' disabled' : ''}"
                         id="request_collection_movies"
                         ${!isRequestServiceAvailable ? 'disabled' : ''}
                         title="${isRequestServiceAvailable ?
                            `Request ALL ${moviesToRequest.length} missing movie(s) using ${requestServiceName}` :
                            'Appropriate request service not configured'}">
                        Request Missing Movies (${moviesToRequest.length})
                     </button>` : ''}
                <button class="action-button dismiss-button" id="dismiss_collection">Dismiss</button>
            </div>
        `;
    
        modalContainer.classList.remove('hidden');
    
        const dismissButton = document.getElementById('dismiss_collection');
        if (dismissButton) {
            dismissButton.addEventListener('click', () => {
                modalContainer.classList.add('hidden');
            });
        }

    
        const requestAllButton = document.getElementById('request_collection_movies');
        if (requestAllButton && isRequestServiceAvailable) {
            requestAllButton.addEventListener('click', () => {
                if (moviesToRequest.length > 0 && typeof requestPreviousMovies === 'function') {
                    requestPreviousMovies(moviesToRequest); 
                }
            });
        }
    
        const individualRequestButtons = infoContainer.querySelectorAll('.request-button[data-movie-id]');
        individualRequestButtons.forEach(button => {
            button.addEventListener('click', async (event) => {
                event.stopPropagation();
                const movieId = button.dataset.movieId;
                if (movieId && typeof requestMovie === 'function') {
                    try {
                        const success = await requestMovie(movieId, true);
                        if (success) {
                            const movie = collectionInfo.movies.find(m => m.id == movieId);
                            if (movie) {
                                movie.is_requested = true;
                                movie.status = 'Requested';
                                openCollectionModal(collectionInfo);
                            }
                        }
                    } catch (error) {
                        console.error("Error from individual request button:", error);
                    }
                }
            });
        });
    
        document.getElementById('collection_modal_close').addEventListener('click', () => {
            modalContainer.classList.add('hidden');
        });
    }

    fetchCollections();

    searchInput.addEventListener('input', () => {
        const searchTerm = searchInput.value.toLowerCase();
        clearSearchBtn.style.display = searchTerm ? 'inline' : 'none';
        const filteredCollections = allCollections.filter(collection => {
            return collection.name.toLowerCase().includes(searchTerm);
        });
        displayCollections(filteredCollections);
    });

    clearSearchBtn.addEventListener('click', () => {
        searchInput.value = '';
        searchInput.dispatchEvent(new Event('input'));
    });

    randomButton.addEventListener('click', () => {
        const visibleCards = Array.from(collectionGrid.children);
        if (visibleCards.length > 0) {
            const randomCard = visibleCards[Math.floor(Math.random() * visibleCards.length)];
            const collectionId = parseInt(randomCard.dataset.collectionId, 10);
            const randomCollection = allCollections.find(c => c.id === collectionId);
            if (randomCollection) {
                openCollectionModal(randomCollection);
            }
        }
    });
});

function getCsrfToken() {
    const token = document.querySelector('meta[name="csrf-token"]');
    return token ? token.getAttribute('content') : null;
}

async function checkRequestServiceAvailability() {
    try {
        const response = await fetch('/api/overseerr/status');
        const data = await response.json();

        return {
            available: data.available,
            service: data.service
        };
    } catch (error) {
        console.error('Error checking request service status:', error);
        return { available: false, service: null };
    }
}

async function requestMovie(movieId, showNotification = true) {
    try {
        const requestButtons = document.querySelectorAll(`.request-button[data-movie-id="${movieId}"]`);
        console.log(`Found ${requestButtons.length} request buttons for movie ${movieId}`);

        requestButtons.forEach(button => {
            button.disabled = true;
            button.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Requesting...';
        });

        const requestResponse = await fetch('/api/request_movie', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify({ movie_id: movieId }),
            credentials: 'include'
        });

        if (!requestResponse.ok) {
            const errorData = await requestResponse.json();
            throw new Error(errorData.error || "Failed to request movie.");
        }

        requestButtons.forEach(button => {
            button.innerHTML = 'Requested';
            button.classList.add('requested');
            button.disabled = true;
        });

        if (showNotification) {
            showToast('Movie requested successfully!', 'success');
        }

        return true;
    } catch (error) {
        console.error("Error requesting movie:", error);

        if (showNotification) {
            showToast(error.message, 'error');
        }

        const requestButtons = document.querySelectorAll(`.request-button[data-movie-id="${movieId}"]`);
        requestButtons.forEach(button => {
            button.disabled = false;
            const serviceName = button.textContent.match(/Request \((.*?)\)/)?.[1] || '';
            button.innerHTML = serviceName ? `Request (${serviceName})` : 'Request';
        });

        throw error;
    }
}

async function requestPreviousMovies(movies) {
    if (!movies || movies.length === 0) return;

    try {
        if (movies.length > 1) {
            const confirmDialog = document.createElement('div');
            confirmDialog.className = 'trakt-confirm-dialog';
            confirmDialog.innerHTML = `
                <div class="dialog-content">
                    <h3>Request Multiple Movies</h3>
                    <p>Are you sure you want to request ${movies.length} movies from this collection?</p>
                    <div class="dialog-buttons">
                        <button class="cancel-button">Cancel</button>
                        <button class="submit-button">Request Movies</button>
                    </div>
                </div>
            `;
            document.body.appendChild(confirmDialog);

            return new Promise((resolve) => {
                const cancelButton = confirmDialog.querySelector('.cancel-button');
                cancelButton.addEventListener('click', () => {
                    confirmDialog.remove();
                    resolve(false);
                });

                const submitButton = confirmDialog.querySelector('.submit-button');
                submitButton.addEventListener('click', async () => {
                    confirmDialog.remove();

                    let successCount = 0;
                    for (const movie of movies) {
                        try {
                            const success = await requestMovie(movie.id, false);
                            if (success) {
                                movie.is_requested = true;
                            }
                            successCount++;
                        } catch (error) {
                            console.error(`Error requesting movie ${movie.title}:`, error);
                        }
                    }

                    if (successCount > 0) {
                        showToast(`Successfully requested ${successCount} movie${successCount > 1 ? 's' : ''}!`, 'success');

                        const existingWarning = document.querySelector('.collection-warning');
                        if (existingWarning) {
                            existingWarning.remove();
                        }
                    } else {
                        showToast('Failed to request movies. Please try again.', 'error');
                    }

                    resolve(true);
                });

                confirmDialog.addEventListener('click', (e) => {
                    if (e.target === confirmDialog) {
                        confirmDialog.remove();
                        resolve(false);
                    }
                });
            });
        } else {
            try {
                const success = await requestMovie(movies[0].id, true);
                if (success) {
                    movies[0].is_requested = true;
                }

                const existingWarning = document.querySelector('.collection-warning');
                if (existingWarning) {
                    existingWarning.remove();
                }
            } catch (error) {
                console.error(`Error requesting movie: ${error.message}`);
            }
        }
    } catch (error) {
        showToast(`Error: ${error.message}`, 'error');
    }
}

function showClientsForPoster(movieId) {
    const clientPrompt = document.getElementById('client_prompt');
    if (!clientPrompt) {
        console.error('Client prompt not found');
        return;
    }

    fetch('/clients')
        .then(response => response.json())
        .then(clients => {
            const listContainer = document.getElementById('list_of_clients');
            if (!listContainer) {
                console.error('List of clients container not found');
                return;
            }
            listContainer.innerHTML = '';

            if (clients.length === 0) {
                listContainer.innerHTML = '<div class="no-clients-message">No available clients found.</div>';
            } else {
                clients.forEach(client => {
                    const clientDiv = document.createElement('div');
                    clientDiv.classList.add('client');
                    clientDiv.textContent = client.title;
                    clientDiv.onclick = function() {
                        playMovieFromPoster(client.id, movieId);
                        clientPrompt.classList.add('hidden');
                    };
                    listContainer.appendChild(clientDiv);
                });
            }
            clientPrompt.classList.remove('hidden');
        })
        .catch(error => {
            console.error('Error fetching clients:', error);
            alert('Failed to fetch clients. Please try again.');
        });
}

function playMovieFromPoster(clientId, tmdbId) {
    fetch(`/play_movie/${clientId}?movie_id=${tmdbId}`)
        .then(response => response.json())
        .then(data => {
            if (data.status !== 'playing') {
                throw new Error(data.error || 'Failed to start playback');
            }
        })
        .catch(error => {
            console.error('Error playing movie:', error);
            alert('Failed to play movie. Please try again.');
        });
}

function closeClientPrompt() {
    const clientPrompt = document.getElementById('client_prompt');
    if (clientPrompt) {
        clientPrompt.classList.add('hidden');
    }
}

function showToast(message, type = 'success') {
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    const icon = type === 'success'
        ? '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>'
        : '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>';

    toast.innerHTML = `
        <div class="toast-icon">${icon}</div>
        <div class="toast-message">${message}</div>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('removing');
        setTimeout(() => {
            toast.remove();
            if (!container.children.length) {
                container.remove();
            }
        }, 300);
    }, 3000);
}
