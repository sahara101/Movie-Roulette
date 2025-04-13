class UserCacheProfile {
    constructor() {
        this.containerElement = null;
        this.username = null;
        this.isAdmin = false;
        this.cacheStats = null;
        this.currentService = null;
    }

    init() {
        if (!document.getElementById('userCacheProfile')) {
            const container = document.createElement('div');
            container.id = 'userCacheProfile';
            container.className = 'user-cache-profile hidden';

            const headerEl = document.querySelector('.header');
            if (headerEl) {
                headerEl.appendChild(container);
                this.containerElement = container;

                this.addStyles();

                this.loadUserProfile();
            }
        }
    }

    addStyles() {
        if (!document.getElementById('userCacheProfileStyles')) {
            const styles = document.createElement('style');
            styles.id = 'userCacheProfileStyles';
            styles.textContent = `
                .user-cache-profile {
                    position: absolute;
                    top: 60px;
                    right: 20px;
                    background-color: #2a2c30;
                    border-radius: 10px;
                    padding: 15px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.3);
                    z-index: 100;
                    min-width: 250px;
                    max-width: 350px;
                }

                .user-cache-profile.hidden {
                    display: none;
                }

                .user-cache-profile h3 {
                    margin-top: 0;
                    border-bottom: 1px solid #444;
                    padding-bottom: 8px;
                    margin-bottom: 12px;
                }

                .user-cache-profile .cache-stat {
                    display: flex;
                    justify-content: space-between;
                    margin-bottom: 5px;
                }

                .user-cache-profile .service-stats {
                    margin-top: 10px;
                }

                .user-cache-profile .service-stats h4 {
                    margin: 5px 0;
                    color: #e5a00d;
                    text-transform: capitalize;
                }

                .user-cache-profile .action-buttons {
                    display: flex;
                    justify-content: space-between;
                    margin-top: 15px;
                }

                .user-cache-profile .action-button {
                    padding: 6px 12px;
                    border-radius: 4px;
                    border: none;
                    cursor: pointer;
                    font-weight: 600;
                    background-color: #4a90e2;
                    color: white;
                }

                .user-cache-profile .action-button:hover {
                    opacity: 0.9;
                }

                .user-cache-profile .admin-link {
                    display: block;
                    text-align: center;
                    margin-top: 10px;
                    color: #e5a00d;
                    text-decoration: none;
                }

                .user-cache-profile .admin-link:hover {
                    text-decoration: underline;
                }

                .user-info {
                    position: relative;
                    display: inline-block;
                    margin-left: 15px;
                }

                .user-info-button {
                    background: none;
                    border: none;
                    color: white;
                    font-size: 16px;
                    cursor: pointer;
                    padding: 5px;
                    display: flex;
                    align-items: center;
                }

                .user-info-button svg {
                    margin-right: 5px;
                }
            `;

            document.head.appendChild(styles);
        }

        if (!document.querySelector('.user-info')) {
            const navEl = document.querySelector('.navigation');
            if (navEl) {
                const userInfo = document.createElement('div');
                userInfo.className = 'user-info';
                userInfo.innerHTML = `
                    <button class="user-info-button">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                            <circle cx="12" cy="7" r="4"></circle>
                        </svg>
                        <span class="username">User</span>
                    </button>
                `;

                navEl.appendChild(userInfo);

                const userInfoButton = userInfo.querySelector('.user-info-button');
                userInfoButton.addEventListener('click', () => {
                    this.toggleProfile();
                });

                document.addEventListener('click', (e) => {
                    if (!userInfo.contains(e.target) && this.containerElement) {
                        this.containerElement.classList.add('hidden');
                    }
                });
            }
        }
    }

    async loadUserProfile() {
        try {
            const response = await fetch('/api/profile');

            if (!response.ok) {
                return;
            }

            const data = await response.json();

            if (data.authenticated) {
                this.username = data.username;
                this.isAdmin = data.is_admin;
                this.cacheStats = data.cache_stats;
                this.currentService = data.current_service;

                const usernameEl = document.querySelector('.user-info .username');
                if (usernameEl) {
                    usernameEl.textContent = this.username;
                }

                this.renderProfileContent();
            }
        } catch (error) {
            console.error('Error loading user profile:', error);
        }
    }

    renderProfileContent() {
        if (!this.containerElement) return;

        let content = `
            <h3>User Profile: ${this.username}</h3>
            <div class="cache-stat">
                <span>Current Service:</span>
                <span>${this.currentService}</span>
            </div>
        `;

        if (this.cacheStats) {
            content += `<div class="service-stats">`;

            const currentServiceStats = this.cacheStats[this.currentService];
            if (currentServiceStats) {
                content += `
                    <h4>${this.currentService}</h4>
                    ${this.currentService === 'plex' ? `
                        <div class="cache-stat">
                            <span>Unwatched Movies:</span>
                            <span>${currentServiceStats.unwatched_count}</span>
                        </div>
                    ` : ''}
                    <div class="cache-stat">
                        <span>All Movies:</span>
                        <span>${currentServiceStats.all_count}</span>
                    </div>
                    <div class="cache-stat">
                        <span>Cache Exists:</span>
                        <span>${currentServiceStats.cache_exists ? 'Yes' : 'No'}</span>
                    </div>
                `;
            }

            content += `</div>`;
        }

        content += `
            <div class="action-buttons">
                <button class="action-button" onclick="userCacheProfile.refreshCache()">Refresh Cache</button>
                <button class="action-button" onclick="userCacheProfile.clearCache()">Clear Cache</button>
            </div>
        `;

        if (this.isAdmin) {
            content += `
                <a href="/user_cache_admin" class="admin-link">User Cache Administration</a>
            `;
        }

        this.containerElement.innerHTML = content;
    }

    toggleProfile() {
        if (!this.containerElement) return;

        this.containerElement.classList.toggle('hidden');

        if (!this.containerElement.classList.contains('hidden')) {
            this.loadUserProfile();
        }
    }

    async refreshCache() {
        try {
            const response = await fetch('/api/user_cache/refresh_current');
            const data = await response.json();

            if (data.success) {
                alert('Cache refresh started!');

                this.containerElement.classList.add('hidden');
            } else {
                alert(data.message || 'Failed to refresh cache');
            }
        } catch (error) {
            console.error('Error refreshing cache:', error);
            alert('Error refreshing cache');
        }
    }

    async clearCache() {
        if (!confirm('Are you sure you want to clear your cache? This will remove all cached movies.')) {
            return;
        }

        try {
            const response = await fetch(`/api/user_cache/clear/${this.username}`);
            const data = await response.json();

            if (data.success) {
                alert('Cache cleared successfully!');

                this.containerElement.classList.add('hidden');

                window.location.reload();
            } else {
                alert(data.message || 'Failed to clear cache');
            }
        } catch (error) {
            console.error('Error clearing cache:', error);
            alert('Error clearing cache');
        }
    }
}

const userCacheProfile = new UserCacheProfile();

document.addEventListener('DOMContentLoaded', () => {
    if (typeof auth_manager !== 'undefined' && auth_manager.auth_enabled) {
        userCacheProfile.init();
    }
});

window.userCacheProfile = userCacheProfile;
