class JellyfinAuth {
    constructor() {
        this.modalElement = document.getElementById('jellyfin-auth-modal');
        this.formElement = document.getElementById('jellyfin-auth-form');
        this.usernameInput = document.getElementById('jellyfin-username');
        this.passwordInput = document.getElementById('jellyfin-password');
        this.loginButton = document.getElementById('jellyfin-login-btn'); 
        this.cancelButton = document.getElementById('cancel-jellyfin-auth');
        this.submitButton = this.formElement ? this.formElement.querySelector('button[type="submit"]') : null;

        document.addEventListener('DOMContentLoaded', () => this.initEventListeners());
    }

    getCsrfToken() {
        const token = document.querySelector('meta[name="csrf-token"]');
        return token ? token.getAttribute('content') : null;
    }

    initEventListeners() {
        if (this.loginButton) {
            this.loginButton.addEventListener('click', () => this.showModal());
        }

        if (this.formElement) {
            this.formElement.addEventListener('submit', (event) => this.handleSubmit(event));
        }

        if (this.cancelButton) {
            this.cancelButton.addEventListener('click', () => this.hideModal());
        }

        if (this.modalElement) {
            this.modalElement.addEventListener('click', (event) => {
                if (event.target === this.modalElement) {
                    this.hideModal();
                }
            });
        }
    }

    showModal() {
        if (this.modalElement) {
            this.clearError(); 
            this.usernameInput.value = ''; 
            this.passwordInput.value = '';
            this.modalElement.style.display = 'flex';
            this.usernameInput.focus(); 
        }
    }

    hideModal() {
        if (this.modalElement) {
            this.modalElement.style.display = 'none';
        }
    }

    async handleSubmit(event) {
        event.preventDefault(); 

        const username = this.usernameInput.value.trim();
        const password = this.passwordInput.value;
        const csrfToken = this.getCsrfToken();

        if (!username || !password) {
            this.showError('Username and password are required.');
            return;
        }
        if (!csrfToken) {
            this.showError('Security token missing. Please refresh the page.');
            return;
        }


        this.setLoading(true); 

        try {
            const headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-CSRFToken': csrfToken 
            };

            const response = await fetch('/api/auth/jellyfin/login', {
                method: 'POST',
                headers: headers,
                body: JSON.stringify({ username, password })
            });

            if (response.ok) {
                const result = await response.json(); 
                if (result.success) {
                    this.showSuccessAndRedirect();
                } else {
                    this.showError(result.message || 'Jellyfin authentication failed.');
                }
            } else {
                let errorMessage = `Authentication failed (Status: ${response.status})`;
                 if (response.status === 400 && response.headers.get('Content-Type')?.includes('text/html')) {
                     errorMessage = 'Security token validation failed. Please refresh the page and try again.';
                 } else {
                    try {
                        const errorResult = await response.json();
                        errorMessage = errorResult.message || errorMessage;
                    } catch (e) {
                        try {
                             const textError = await response.text();
                             if (textError && !textError.trim().startsWith('<')) {
                                 errorMessage = textError.trim(); // Trim whitespace
                             }
                        } catch (e2) {
                        }
                        console.warn("Could not parse Jellyfin error response as JSON. Status:", response.status);
                    }
                 }
                this.showError(errorMessage); 
            }

        } catch (error) {
            console.error('Jellyfin auth error:', error);
            this.showError(error.message || 'A network or unexpected error occurred.');
        } finally {
             this.setLoading(false); 
        }
    }

    setLoading(isLoading) {
        if (this.submitButton && this.cancelButton && this.usernameInput && this.passwordInput) {
            this.submitButton.disabled = isLoading;
            this.cancelButton.disabled = isLoading;
            this.usernameInput.disabled = isLoading;
            this.passwordInput.disabled = isLoading;

            if (isLoading) {
                this.submitButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Signing In...';
            } else {
                this.submitButton.innerHTML = 'Sign In';
            }
        }
    }

    showError(message) {
        this.clearError(); 
        const errorDiv = document.createElement('div');
        errorDiv.className = 'error-message modal-error'; 
        errorDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${message}`;

        const formButtons = this.formElement.querySelector('.form-buttons');
        if (formButtons) {
            this.formElement.insertBefore(errorDiv, formButtons);
        } else {
            this.formElement.appendChild(errorDiv);
        }
    }

    clearError() {
        const existingError = this.formElement.querySelector('.modal-error');
        if (existingError) {
            existingError.remove();
        }
    }

    showSuccessAndRedirect() {
        if (this.modalElement) {
            const modalContent = this.modalElement.querySelector('.modal-content');
            if (modalContent) {
                modalContent.innerHTML = `
                    <h2>Authentication Successful</h2>
                    <p>You've successfully logged in with Jellyfin!</p>
                    <div class="modal-loader">
                        <i class="fas fa-check-circle" style="color: #4CAF50;"></i>
                        <span>Redirecting...</span>
                    </div>
                `;
            }
            setTimeout(() => {
                 const nextUrlInput = document.querySelector('input[name="next"]'); 
                 const redirectUrl = nextUrlInput ? nextUrlInput.value : '/';
                 window.location.href = redirectUrl;
            }, 1500);
        }
    }
}

const jellyfinAuth = new JellyfinAuth();
