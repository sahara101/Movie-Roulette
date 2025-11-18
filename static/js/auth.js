function getCsrfToken() {
    const token = document.querySelector('meta[name="csrf-token"]');
    return token ? token.getAttribute('content') : null;
}

if (typeof bufferDecode === 'undefined' || typeof bufferEncode === 'undefined') {
    window.bufferDecode = function(value) {
        return Uint8Array.from(atob(value.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0));
    }
    window.bufferEncode = function(value) {
        return btoa(String.fromCharCode.apply(null, new Uint8Array(value)))
            .replace(/\+/g, "-")
            .replace(/\//g, "_")
            .replace(/=/g, "");
    }
}


document.addEventListener('DOMContentLoaded', function() {
    initUserMenu();
    initMediaMenu();
    updateMediaMenuHeader();
    checkAuthStatus(); 
    attachLogoutHandler();
    handlePlexCallback();
    initPasskeyLoginButton();
});

function handlePlexCallback() {
    if (window.location.pathname.includes('/plex/callback')) {
        const urlParams = new URLSearchParams(window.location.search);
        const pinId = urlParams.get('pinID') || sessionStorage.getItem('plex-pin-id');
        
        if (!urlParams.get('pinID') && pinId) {
            let newUrl = `${window.location.pathname}?pinID=${pinId}`; 
            
            const token = urlParams.get('token');
            const next = urlParams.get('next');
            
            if (token) newUrl += `&token=${token}`;
            if (next) newUrl += `&next=${next}`;
            
            window.history.replaceState({}, document.title, newUrl);
        }
    }
}

function initUserMenu() {
    const userMenu = document.querySelector('.user-menu');
    const userMenuTrigger = document.querySelector('.user-menu-trigger');
    
    if (userMenu && userMenuTrigger) {
        userMenuTrigger.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            userMenu.classList.toggle('active');
        });
        
        document.addEventListener('click', function(e) {
            if (userMenu.classList.contains('active') && !userMenu.contains(e.target)) {
                userMenu.classList.remove('active');
            }
        });
        
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && userMenu.classList.contains('active')) {
                userMenu.classList.remove('active');
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

    }
}

function initMediaMenu() {
    const mediaMenu = document.querySelector('.media-menu');
    const mediaMenuTrigger = document.querySelector('.media-menu-trigger');
    
    if (mediaMenu && mediaMenuTrigger) {
        mediaMenuTrigger.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            mediaMenu.classList.toggle('active');
        });
        
        document.addEventListener('click', function(e) {
            if (mediaMenu.classList.contains('active') && !mediaMenu.contains(e.target)) {
                mediaMenu.classList.remove('active');
            }
        });
        
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && mediaMenu.classList.contains('active')) {
                mediaMenu.classList.remove('active');
            }
        });
        
        const menuItems = mediaMenu.querySelectorAll('.dropdown-item');
        menuItems.forEach(item => {
            item.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    this.click(); 
                }
            });
        });
    }
}

function updateMediaMenuHeader() {
    const mediaMenuTrigger = document.querySelector('.media-menu-trigger');
    if (mediaMenuTrigger) {
        if (window.location.pathname === '/collections') {
            mediaMenuTrigger.textContent = 'Collections';
        } else {
            mediaMenuTrigger.textContent = 'Movies';
        }
    }
}

function checkAuthStatus() {
    fetch('/api/auth/check')
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            if (!data.authenticated) {
                localStorage.removeItem('is-plex-user');
            }
            requestAnimationFrame(() => {
                updateAuthUI(data);
            });
        })
        .catch(error => {
            localStorage.removeItem('is-plex-user');
            console.error('[Auth] checkAuthStatus: Error checking authentication status:', error);
            requestAnimationFrame(() => {
                updateAuthUI({ authenticated: false });
            });
        });
}

function attachLogoutHandler() {
    document.body.addEventListener('click', function(event) {
        if (event.target.matches('a[href="/logout"]')) {
             localStorage.removeItem('is-plex-user');
        }
    });
}

function updateAuthUI(authData) {
    const userMenu = document.querySelector('.user-menu');
    const userName = document.querySelector('.user-name');

    if (!userMenu || !userName) {
        return;
   }

    if (authData.authenticated) {
        userMenu.style.display = 'flex';
        userName.textContent = authData.username;

        const serviceType = authData.service_type;
        const dropdownContent = userMenu.querySelector('.user-dropdown');
        const logoutLink = dropdownContent ? dropdownContent.querySelector('a[href="/logout"]') : null;

        if (dropdownContent && logoutLink) {
            let localUserChangePasswordLink = dropdownContent.querySelector('#local-user-change-password-link');
            if (!localUserChangePasswordLink) {
                localUserChangePasswordLink = document.createElement('a');
                localUserChangePasswordLink.href = '#';
                localUserChangePasswordLink.id = 'local-user-change-password-link';
                localUserChangePasswordLink.className = 'dropdown-item';
                localUserChangePasswordLink.innerHTML = '<i class="fas fa-key"></i> Change Password';
                localUserChangePasswordLink.onclick = (e) => { e.preventDefault(); openChangePasswordModal(); };
                dropdownContent.insertBefore(localUserChangePasswordLink, logoutLink);
            }

            let managedUserChangePasswordLink = dropdownContent.querySelector('#managed-user-change-password-link');
            if (!managedUserChangePasswordLink) {
                managedUserChangePasswordLink = document.createElement('a');
                managedUserChangePasswordLink.href = '#';
                managedUserChangePasswordLink.id = 'managed-user-change-password-link';
                managedUserChangePasswordLink.className = 'dropdown-item';
                managedUserChangePasswordLink.innerHTML = '<i class="fas fa-key"></i> Change Password';
                managedUserChangePasswordLink.onclick = (e) => { e.preventDefault(); openManagedUserChangePasswordModal(); };
                dropdownContent.insertBefore(managedUserChangePasswordLink, logoutLink);
            }

            localUserChangePasswordLink.style.display = 'none';
            managedUserChangePasswordLink.style.display = 'none';

            if (serviceType === 'local') {
                localUserChangePasswordLink.style.display = '';
                localStorage.removeItem('is-plex-user');
            } else if (serviceType === 'plex_managed') {
                managedUserChangePasswordLink.style.display = '';
                localStorage.setItem('is-plex-user', 'true');
            } else { 
                if (serviceType === 'plex') localStorage.setItem('is-plex-user', 'true');
                else localStorage.removeItem('is-plex-user');
            }
        } else {
             console.warn("[Auth] updateAuthUI: Could not find user dropdown content (.user-dropdown) or logout link. Cannot manage Change Password links.");
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


function openChangePasswordModal() {
    fetch('/api/auth/check').then(r => r.json()).then(authData => {
        if (authData.authenticated && authData.service_type !== 'local') {
             showNotification('Password can only be changed for local accounts.', 'info');
             return;
        }
        const modal = document.getElementById('change-password-modal');
        if (modal) {
            modal.classList.remove('hidden');
            setTimeout(() => {
                document.getElementById('current-password').focus();
            }, 100);
        }
    }).catch(err => console.error("Error re-checking auth before opening password modal:", err));
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
     fetch('/api/auth/check').then(r => r.json()).then(authData => {
        if (!authData.authenticated || authData.service_type !== 'local') {
            showNotification('Password can only be changed for local accounts.', 'error');
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

    }).catch(err => {
         console.error("Error re-checking auth before submitting password change:", err);
         const errorElement = document.getElementById('password-error');
         if(errorElement) {
             errorElement.textContent = 'Could not verify user type. Please try again.';
             errorElement.style.display = 'block';
         }
    });
}

function openManagedUserChangePasswordModal() {
    let modal = document.getElementById('managed-user-change-password-modal-dynamic');
    if (modal) {
        modal.remove();
    }

    const modalHTML = `
        <div id="managed-user-change-password-modal-dynamic" class="hidden" style="display: flex;"> 
            <div class="change-password-content"> 
                <button id="managed-change-password-close" class="close-button" onclick="closeManagedUserChangePasswordModal()" aria-label="Close change password modal"> 
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
                        <path d="M24 20.188l-8.315-8.209 8.2-8.282-3.697-3.697-8.212 8.318-8.31-8.203-3.666 3.666 8.312 8.203-8.204 8.278 3.684 3.684 8.215-8.316 8.311 8.202z" />
                    </svg>
                </button>
                <div class="change-password-form"> 
                    <h3>Change Password</h3>
                    <div id="managed-password-error" class="error-message" style="display: none;"></div>
                    <form id="managed-change-password-form-inner"> 
                        <div class="form-group">
                            <label for="managed-current-password">Current Password</label>
                            <input type="password" id="managed-current-password" required>
                        </div>
                        <div class="form-group">
                            <label for="managed-new-password">New Password</label> 
                            <input type="password" id="managed-new-password" required minlength="6">
                        </div>
                        <div class="form-group">
                            <label for="managed-confirm-password">Confirm New Password</label>
                            <input type="password" id="managed-confirm-password" required minlength="6">
                        </div>
                        <div class="password-actions"> 
                            <button type="button" onclick="closeManagedUserChangePasswordModal()">Cancel</button> 
                            <button type="button" onclick="submitManagedUserChangePassword()">Update Password</button> 
                        </div>
                    </form>
                </div>
            </div>
        </div>
    `;
    document.body.insertAdjacentHTML('beforeend', modalHTML);
    
    const newModal = document.getElementById('managed-user-change-password-modal-dynamic');
    if (newModal) {
         newModal.classList.remove('hidden');
         setTimeout(() => {
             const firstInput = document.getElementById('managed-current-password');
             if (firstInput) firstInput.focus();
         }, 100); 
    } else {
        console.error("Failed to find newly created managed password modal with ID #managed-user-change-password-modal-dynamic");
    }
}

function closeManagedUserChangePasswordModal() {
    const modal = document.getElementById('managed-user-change-password-modal-dynamic'); 
    if (modal) {
        modal.remove();
    }
}

function submitManagedUserChangePassword() {
    const currentPassword = document.getElementById('managed-current-password').value;
    const newPassword = document.getElementById('managed-new-password').value;
    const confirmPassword = document.getElementById('managed-confirm-password').value;
    const errorElement = document.getElementById('managed-password-error');
    const modalNode = document.getElementById('managed-user-change-password-modal-dynamic');
    const submitButton = modalNode ? modalNode.querySelector('.password-actions button:last-child') : null; 

    if (!errorElement) { console.error("Managed password error element not found"); return; }
    
    errorElement.style.display = 'none';
    errorElement.textContent = '';
    if(submitButton) submitButton.disabled = true;

    if (!currentPassword || !newPassword || !confirmPassword) {
        errorElement.textContent = 'All fields are required.';
        errorElement.style.display = 'block';
        if(submitButton) submitButton.disabled = false;
        return;
    }
    if (newPassword.length < 6) {
        errorElement.textContent = 'New password must be at least 6 characters long.';
        errorElement.style.display = 'block';
        if(submitButton) submitButton.disabled = false;
        return;
    }
    if (newPassword !== confirmPassword) {
        errorElement.textContent = 'New passwords do not match.';
        errorElement.style.display = 'block';
        if(submitButton) submitButton.disabled = false;
        return;
    }

    fetch('/api/managed_user/change_password', {
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
    .then(response => response.json().then(data => ({ status: response.status, body: data })))
    .then(({ status, body }) => {
        if (status === 200 && body.message) {
            showNotification(body.message, 'success');
            closeManagedUserChangePasswordModal();
        } else {
            errorElement.textContent = body.error || 'Password change failed.';
            errorElement.style.display = 'block';
        }
    })
    .catch(error => {
        console.error('Error changing managed user password:', error);
        errorElement.textContent = 'An error occurred. Please try again.';
        errorElement.style.display = 'block';
    })
    .finally(() => {
         const stillExistsButton = document.querySelector('#managed-user-change-password-modal-dynamic .password-actions button:last-child');
         if (stillExistsButton) {
             stillExistsButton.disabled = false;
         }
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
    notification.className = `notification ${type} show`; 

    setTimeout(() => {
        if (notification) { 
             notification.classList.remove('show');
             notification.addEventListener('transitionend', () => {
                 if (notification.parentNode) { 
                     notification.remove();
                 }
             }, { once: true });
             setTimeout(() => {
                if (notification && notification.parentNode) notification.remove();
             }, 500); 
        }
    }, 3000);
}

function isWebAuthnSupported() {
    return window.PublicKeyCredential !== undefined &&
           typeof window.PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable === 'function';
}

async function initPasskeyLoginButton() {
    const passkeyLoginSection = document.getElementById('passkey-login-section');
    const passkeyLoginBtn = document.getElementById('passkey-login-btn');

    if (!passkeyLoginBtn || !passkeyLoginSection) {
        return;
    }

    if (!isWebAuthnSupported()) {
        console.log("WebAuthn not supported by this browser.");
        passkeyLoginSection.style.display = 'none';
        return;
    }

    try {
        const configResponse = await fetch('/api/auth/passkey/status');
        if (configResponse.ok) {
            const configData = await configResponse.json();
            if (configData.passkeys_enabled) {
                passkeyLoginSection.style.display = 'block';
                passkeyLoginBtn.addEventListener('click', handlePasskeyLogin);
            } else {
                console.log("Passkey login is disabled in server settings.");
                passkeyLoginSection.style.display = 'none';
            }
        } else {
             console.warn("Could not determine if passkeys are enabled; hiding passkey button.");
             passkeyLoginSection.style.display = 'none';
        }
    } catch (error) {
        console.error("Error checking passkey status:", error);
        passkeyLoginSection.style.display = 'none';
    }
}

async function handlePasskeyLogin() {
    const passkeyLoginBtn = document.getElementById('passkey-login-btn');
    const originalButtonText = passkeyLoginBtn.innerHTML;
    passkeyLoginBtn.disabled = true;
    passkeyLoginBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Signing In...';
    
    const errorContainer = document.getElementById('passkey-error-message'); 

    function displayLoginError(message) {
        if (errorContainer) {
            errorContainer.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${message}`;
            errorContainer.style.display = 'block';
        } else {
            const genericErrorContainer = document.querySelector('.login-form .error-message');
            if (genericErrorContainer) {
                genericErrorContainer.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${message}`;
                genericErrorContainer.style.display = 'block';
            } else {
                alert(message);
            }
        }
    }
    
    if (errorContainer) errorContainer.style.display = 'none';
    const genericErrorContainer = document.querySelector('.login-form .error-message');
    if (genericErrorContainer && genericErrorContainer.id !== 'passkey-error-message') {
    }


    try {
        const usernameInput = document.getElementById('username');
        const username = usernameInput ? usernameInput.value : null;

        const optionsResponse = await fetch('/api/auth/passkey/login-options', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify({ username: username })
        });

        const options = await optionsResponse.json();

        if (!optionsResponse.ok) {
            throw new Error(options.error || 'Failed to get passkey login options');
        }

        options.challenge = bufferDecode(options.challenge);
        if (options.allowCredentials) {
            for (let cred of options.allowCredentials) {
                cred.id = bufferDecode(cred.id);
            }
        }

        const assertion = await navigator.credentials.get({ publicKey: options });

        const assertionForServer = {
            id: assertion.id,
            rawId: bufferEncode(assertion.rawId),
            type: assertion.type,
            response: {
                authenticatorData: bufferEncode(assertion.response.authenticatorData),
                clientDataJSON: bufferEncode(assertion.response.clientDataJSON),
                signature: bufferEncode(assertion.response.signature),
                userHandle: assertion.response.userHandle ? bufferEncode(assertion.response.userHandle) : null,
            },
        };

        const verifyResponse = await fetch('/api/auth/passkey/login-verify', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify(assertionForServer)
        });

        const verifyResult = await verifyResponse.json();

        if (!verifyResponse.ok) {
            throw new Error(verifyResult.error || 'Passkey login failed');
        }

        const nextUrl = new URLSearchParams(window.location.search).get('next') || '/';
        window.location.href = nextUrl;

    } catch (err) {
        console.error('Passkey login error:', err);
        displayLoginError(err.message || 'Could not sign in with passkey.');
        passkeyLoginBtn.disabled = false;
        passkeyLoginBtn.innerHTML = originalButtonText;
    }
}
