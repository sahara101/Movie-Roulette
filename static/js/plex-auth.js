function getClientId() {
    let clientId = localStorage.getItem('plex-client-id');
    if (!clientId) {
        clientId = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
            const r = Math.random() * 16 | 0;
            const v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
        localStorage.setItem('plex-client-id', clientId);
    }
    return clientId;
}

class PlexAuth {
    constructor() {
        this.pinCheckInterval = null;
        this.pinId = null;
        this.authToken = null; 
        this.plexWindow = null;
        this.modalElement = document.getElementById('plex-auth-modal');
        this.maxPinCheckAttempts = 30; 
        this.pinCheckAttempts = 0;

        document.addEventListener('DOMContentLoaded', () => this.initEventListeners());
    }

    initEventListeners() {
        const plexLoginBtn = document.getElementById('plex-login-btn');
        const cancelPlexAuth = document.getElementById('cancel-plex-auth');

        if (plexLoginBtn) {
            plexLoginBtn.addEventListener('click', () => this.startAuth());
        }

        if (cancelPlexAuth) {
            cancelPlexAuth.addEventListener('click', () => this.cancelAuth());
        }
    }

    startAuth() {
        this.preparePopup();

        setTimeout(() => this.requestPlexAuth(), 500);
    }

    preparePopup() {
        const width = 600;
        const height = 700;
        const left = (window.screen.width / 2) - (width / 2);
        const top = (window.screen.height / 2) - (height / 2);

        this.plexWindow = window.open(
            'about:blank',
            'PlexAuth',
            `width=${width},height=${height},top=${top},left=${left}`
        );

        if (this.modalElement) {
            this.modalElement.style.display = 'flex';
        }
    }

    async requestPlexAuth() {
        try {
            const clientId = getClientId();

            const response = await fetch('/plex/auth', {
                method: 'GET',
                headers: {
                    'Accept': 'application/json',
                    'X-Plex-Client-Identifier': clientId
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP error ${response.status}`);
            }

            const data = await response.json();

            if (!data.auth_url) {
                throw new Error('Invalid response from server');
            }

            this.pinId = data.pin_id;
            console.log(`Starting authentication with PIN ID: ${this.pinId}`);

            if (this.plexWindow && !this.plexWindow.closed) {
                this.plexWindow.location.href = data.auth_url;

                this.pinCheckAttempts = 0;

                this.pinCheckInterval = setInterval(() => this.checkPlexPin(), 2000);

                const windowCheckInterval = setInterval(() => {
                    if (this.plexWindow.closed) {
                        clearInterval(windowCheckInterval);
                        this.cancelAuth();
                    }
                }, 1000);
            } else {
                throw new Error('Authentication window was closed');
            }
        } catch (error) {
            console.error('Error starting Plex auth:', error);
            this.showAuthError(error.message || 'An error occurred during authentication');
        }
    }

    async checkPlexPin() {
        if (!this.pinId) return;

        try {
            this.pinCheckAttempts++;

            if (this.pinCheckAttempts > this.maxPinCheckAttempts) {
                clearInterval(this.pinCheckInterval);
                throw new Error('Authentication timed out. Please try again.');
            }

            const response = await fetch(`/api/auth/plex/check_pin/${this.pinId}`);

            if (!response.ok) {
                throw new Error(`HTTP error ${response.status}`);
            }

            const data = await response.json();

            if (data.status === 'success') {
                clearInterval(this.pinCheckInterval);
                
                if (data.token) {
                    this.authToken = data.token;
                    localStorage.setItem('plex-auth-token', data.token);
                }
                
                this.showAuthSuccess();

                console.log('Authentication successful, redirecting...');

                if (this.plexWindow && !this.plexWindow.closed) {
                    this.plexWindow.close();
                }

                setTimeout(() => {
                    let redirectUrl = `/plex/callback?pinID=${this.pinId}`;
                    if (this.authToken) {
                        redirectUrl += `&token=${encodeURIComponent(this.authToken)}`;
                    }
                    window.location.href = redirectUrl;
                }, 1500);
            } else {
                console.log(`PIN check result: ${data.status} - ${data.message}`);
            }
        } catch (error) {
            console.error('Error checking PIN:', error);

            if (this.pinCheckAttempts >= this.maxPinCheckAttempts) {
                this.showAuthError(`Authentication error: ${error.message}`);
                this.cancelAuth();
            }
        }
    }

    cancelAuth() {
        if (this.pinCheckInterval) {
            clearInterval(this.pinCheckInterval);
            this.pinCheckInterval = null;
        }

        if (this.modalElement) {
            this.modalElement.style.display = 'none';
        }

        if (this.plexWindow && !this.plexWindow.closed) {
            this.plexWindow.close();
            this.plexWindow = null;
        }
    }

    showAuthError(message) {
        if (this.modalElement) {
            const modalContent = this.modalElement.querySelector('.modal-content');
            if (modalContent) {
                modalContent.innerHTML = `
                    <h2>Authentication Error</h2>
                    <p>${message}</p>
                    <button id="close-error" class="cancel-button">Close</button>
                `;

                document.getElementById('close-error').addEventListener('click', () => this.cancelAuth());
            }
        }
    }

    showAuthSuccess() {
        if (this.modalElement) {
            const modalContent = this.modalElement.querySelector('.modal-content');
            if (modalContent) {
                modalContent.innerHTML = `
                    <h2>Authentication Successful</h2>
                    <p>You've successfully logged in with Plex!</p>
                    <div class="modal-loader">
                        <i class="fas fa-check-circle" style="color: #4CAF50;"></i>
                        <span>Redirecting...</span>
                    </div>
                `;
            }
        }
    }
}

const plexAuth = new PlexAuth();
