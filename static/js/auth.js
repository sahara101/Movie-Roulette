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

function getCsrfToken() {
    const token = document.querySelector('meta[name="csrf-token"]');
    return token ? token.getAttribute('content') : null;
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
            
            sessionStorage.setItem('plex-pin-id', this.pinId);

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
        const pinId = this.pinId || sessionStorage.getItem('plex-pin-id');
        if (!pinId) return;

        try {
            this.pinCheckAttempts++;

            if (this.pinCheckAttempts > this.maxPinCheckAttempts) {
                clearInterval(this.pinCheckInterval);
                throw new Error('Authentication timed out. Please try again.');
            }

            console.log(`Checking PIN ${pinId} - attempt ${this.pinCheckAttempts}`);

            const response = await fetch(`/api/auth/plex/check_pin/${pinId}`);

            if (!response.ok) {
                throw new Error(`HTTP error ${response.status}`);
            }

            const data = await response.json();

            if (data.status === 'success') {
                clearInterval(this.pinCheckInterval);

                if (data.token) {
                    this.authToken = data.token;
                    localStorage.setItem('plex-auth-token', data.token);
                    localStorage.setItem('is-plex-user', 'true');
                    console.log('Stored authentication token for fallback');
                }

                this.showAuthSuccess();

                console.log('Authentication successful, redirecting...');

                if (this.plexWindow && !this.plexWindow.closed) {
                    this.plexWindow.close();
                }

                setTimeout(() => {
                    let redirectUrl = `/plex/callback?pinID=${pinId}`;
                    if (this.authToken) {
                        redirectUrl += `&token=${encodeURIComponent(this.authToken)}`;
                    }

                    const urlParams = new URLSearchParams(window.location.search);
                    const nextUrl = urlParams.get('next');
                    if (nextUrl) {
                        redirectUrl += `&next=${encodeURIComponent(nextUrl)}`;
                    }

                    console.log(`Redirecting to: ${redirectUrl}`);
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

                const closeButton = document.getElementById('close-error');
                if (closeButton) {
                    closeButton.addEventListener('click', () => this.cancelAuth());
                }
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

document.addEventListener('DOMContentLoaded', function() {
    console.log("DOM Content Loaded - Setting up authentication JS");
    initUserMenu();
    checkAuthStatus();
    attachLogoutHandler();
    handlePlexCallback();
});

function handlePlexCallback() {
    if (window.location.pathname.includes('/plex/callback')) {
        const urlParams = new URLSearchParams(window.location.search);
        const pinId = urlParams.get('pinID') || sessionStorage.getItem('plex-pin-id');
        
        if (!urlParams.get('pinID') && pinId) {
            const newUrl = `${window.location.pathname}?pinID=${pinId}`;
            
            const token = urlParams.get('token');
            const next = urlParams.get('next');
            
            if (token) newUrl += `&token=${token}`;
            if (next) newUrl += `&next=${next}`;
            
            window.history.replaceState({}, document.title, newUrl);
            console.log("Added PIN ID to URL:", newUrl);
        }
    }
}

function initUserMenu() {
    const userMenu = document.querySelector('.user-menu');
    const userMenuTrigger = document.querySelector('.user-menu-trigger');
    
    if (userMenu && userMenuTrigger) {
        console.log("Found user menu elements");
        
        userMenuTrigger.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            
            userMenu.classList.toggle('active');
            console.log("Toggled user menu active state:", userMenu.classList.contains('active'));
        });
        
        document.addEventListener('click', function(e) {
            if (userMenu.classList.contains('active') && !userMenu.contains(e.target)) {
                userMenu.classList.remove('active');
                console.log("Closing dropdown due to outside click");
            }
        });
        
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && userMenu.classList.contains('active')) {
                userMenu.classList.remove('active');
                console.log("Closing dropdown due to escape key");
            }
        });
        
        const menuItems = userMenu.querySelectorAll('.dropdown-item');
        menuItems.forEach(item => {
            item.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    this.click();
                }
            });
        });

        if (localStorage.getItem('is-plex-user') === 'true') {
            const changePasswordLink = document.querySelector('.dropdown-item[onclick*="openChangePasswordModal"]');
            if (changePasswordLink) {
                changePasswordLink.style.display = 'none';
                console.log("Hidden change password button for Plex user");
            }
        }
    } else {
        console.warn("User menu elements not found");
    }
}

function checkAuthStatus() {
    fetch('/api/auth/check')
        .then(response => response.json())
        .then(data => {
            if (!data.authenticated) {
                localStorage.removeItem('is-plex-user');
            }
            updateAuthUI(data);
        })
        .catch(error => {
            localStorage.removeItem('is-plex-user');
            console.error('Error checking authentication status:', error);
        });
}

function attachLogoutHandler() {
    const logoutLink = document.querySelector('a[href="/logout"]');
    if (logoutLink) {
        logoutLink.addEventListener('click', function() {
            localStorage.removeItem('is-plex-user');
            console.log("Clearing Plex user flag on logout");
        });
    }
}

function updateAuthUI(authData) {
    const userMenu = document.querySelector('.user-menu');
    const userName = document.querySelector('.user-name');

    if (userMenu && userName) {
        if (authData.authenticated) {
            userMenu.style.display = 'flex';
            userName.textContent = authData.username;

            const isPlexUser = authData.is_plex_user || localStorage.getItem('is-plex-user') === 'true';
            console.log("Is Plex user:", isPlexUser);

            if (isPlexUser) {
                const changePasswordLink = document.querySelector('a[onclick*="openChangePasswordModal"]');
                if (changePasswordLink) {
                    changePasswordLink.style.display = 'none';
                    console.log("Hidden change password button for Plex user");
                } else {
                    console.warn("Could not find change password link");

                    const allLinks = document.querySelectorAll('.dropdown-item');
                    allLinks.forEach(link => {
                        if (link.textContent.includes('Change Password')) {
                            link.style.display = 'none';
                            console.log("Hidden change password button using text content");
                        }
                    });
                }

                localStorage.setItem('is-plex-user', 'true');
            } else {
                localStorage.removeItem('is-plex-user');
                
                const changePasswordLink = document.querySelector('a[onclick*="openChangePasswordModal"]');
                if (changePasswordLink) {
                    changePasswordLink.style.display = '';
                    console.log("Showing change password button for local user");
                } else {
                    const allLinks = document.querySelectorAll('.dropdown-item');
                    allLinks.forEach(link => {
                        if (link.textContent.includes('Change Password')) {
                            link.style.display = '';
                            console.log("Showing change password button using text content");
                        }
                    });
                }
            }

            const adminElements = document.querySelectorAll('.admin-only');
            adminElements.forEach(element => {
                element.style.display = authData.is_admin ? '' : 'none';
            });
        } else {
            userMenu.style.display = 'none';
            localStorage.removeItem('is-plex-user');
        }
    }
}

function openChangePasswordModal() {
    if (localStorage.getItem('is-plex-user') === 'true') {
        showNotification('Plex users cannot change password, please use Plex to manage your account', 'info');
        return;
    }
    
    const modal = document.getElementById('change-password-modal');
    if (modal) {
        modal.classList.remove('hidden');
        // Focus first input
        setTimeout(() => {
            document.getElementById('current-password').focus();
        }, 100);
    }
}

function closeChangePasswordModal() {
    const modal = document.getElementById('change-password-modal');
    if (modal) {
        modal.classList.add('hidden');
        document.getElementById('current-password').value = '';
        document.getElementById('new-password').value = '';
        document.getElementById('confirm-password').value = '';
        const errorElement = document.getElementById('password-error');
        if (errorElement) {
            errorElement.style.display = 'none';
        }
    }
}

function submitChangePassword() {
    if (localStorage.getItem('is-plex-user') === 'true') {
        showNotification('Plex users cannot change password', 'error');
        closeChangePasswordModal();
        return;
    }
    
    const currentPassword = document.getElementById('current-password').value;
    const newPassword = document.getElementById('new-password').value;
    const confirmPassword = document.getElementById('confirm-password').value;
    const errorElement = document.getElementById('password-error');

    if (!currentPassword || !newPassword || !confirmPassword) {
        errorElement.textContent = 'All fields are required';
        errorElement.style.display = 'block';
        return;
    }

    if (newPassword !== confirmPassword) {
        errorElement.textContent = 'New passwords do not match';
        errorElement.style.display = 'block';
        return;
    }

    fetch('/api/auth/change-password', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken() 
        },
        body: JSON.stringify({
            current_password: currentPassword,
            new_password: newPassword
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification('Password changed successfully', 'success');
            closeChangePasswordModal();
        } else {
            errorElement.textContent = data.message || 'Password change failed';
            errorElement.style.display = 'block';
        }
    })
    .catch(error => {
        console.error('Error changing password:', error);
        errorElement.textContent = 'An error occurred. Please try again.';
        errorElement.style.display = 'block';
    });
}

function showNotification(message, type = 'info') {
    let notification = document.getElementById('notification');
    if (!notification) {
        notification = document.createElement('div');
        notification.id = 'notification';
        notification.className = 'notification';
        document.body.appendChild(notification);
    }

    notification.textContent = message;
    notification.className = `notification ${type}`;

    notification.style.display = 'block';

    setTimeout(() => {
        notification.style.display = 'none';
    }, 3000);
}
