document.addEventListener('DOMContentLoaded', () => {
    const embyLoginBtn = document.getElementById('emby-login-btn'); 
    const embyAuthModal = document.getElementById('emby-auth-modal');
    const embyAuthForm = document.getElementById('emby-auth-form'); 
    const cancelEmbyAuthBtn = document.getElementById('cancel-emby-auth'); 
    const embyUsernameInput = document.getElementById('emby-username'); 
    const embyPasswordInput = document.getElementById('emby-password'); 

    const getCsrfToken = () => {
        const tokenMeta = document.querySelector('meta[name="csrf-token"]');
        return tokenMeta ? tokenMeta.getAttribute('content') : null;
    };

    const showElementFlex = (el) => { if (el) el.style.display = 'flex'; };
    const hideElement = (el) => { if (el) el.style.display = 'none'; };

    const resetModalState = () => {
        if (embyUsernameInput) embyUsernameInput.value = '';
        if (embyPasswordInput) embyPasswordInput.value = '';
        clearError(embyAuthForm);
    };

    const showModal = () => {
        if (embyAuthModal) {
            resetModalState(); 
            showElementFlex(embyAuthModal); 
            if (embyUsernameInput) embyUsernameInput.focus();
        }
    };

    const hideModal = () => {
        if (embyAuthModal) {
            hideElement(embyAuthModal);
        }
    };

    const showError = (message, targetElement = embyAuthForm) => {
        if (targetElement) {
            clearError(targetElement); 
            const errorDiv = document.createElement('div');
            errorDiv.className = 'error-message';
            errorDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> ${message}`;
            targetElement.insertBefore(errorDiv, targetElement.firstChild);
        }
    };

    const clearError = (targetElement = embyAuthForm) => {
         if (targetElement) {
            const existingError = targetElement.querySelector('.error-message');
            if (existingError) {
                existingError.remove();
            }
         }
    };

    const setLoadingState = (isLoading) => {
         const submitButton = embyAuthForm?.querySelector('button[type="submit"]');
         const inputs = embyAuthForm?.querySelectorAll('input');
         const buttons = embyAuthForm?.querySelectorAll('button');

         if (submitButton) {
             submitButton.disabled = isLoading;
             submitButton.innerHTML = isLoading
                ? '<i class="fas fa-spinner fa-spin"></i> Signing In...'
                : 'Sign In';
         }
         inputs?.forEach(input => input.disabled = isLoading);
         buttons?.forEach(button => {
             if (!button.classList.contains('cancel-button')) {
                 button.disabled = isLoading;
             }
         });
    };

    if (embyLoginBtn) {
        embyLoginBtn.addEventListener('click', showModal);
    }

    if (cancelEmbyAuthBtn) {
        cancelEmbyAuthBtn.addEventListener('click', hideModal);
    }

    if (embyAuthForm) {
        embyAuthForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            const username = embyUsernameInput ? embyUsernameInput.value.trim() : null;
            const password = embyPasswordInput ? embyPasswordInput.value : null;
            const csrfToken = getCsrfToken();

            if (!username || !password) {
                showError('Username and password are required.');
                return;
            }
             if (!csrfToken) {
                 showError('Security token missing. Please refresh the page.');
                 return;
             }

            setLoadingState(true);

            try {
                const response = await fetch('/api/auth/emby/login', { 
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken
                    },
                    body: JSON.stringify({ username, password }),
                });

                if (response.ok) {
                    const result = await response.json();
                    if (result.success) {
                        const nextUrlInput = document.querySelector('input[name="next"]');
                        window.location.href = nextUrlInput ? nextUrlInput.value : '/';
                    } else {
                         showError(result.message || 'Authentication failed.');
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
                            try { const textError = await response.text(); if (textError && !textError.trim().startsWith('<')) { errorMessage = textError.trim(); } } catch (e2) {}
                            console.warn("Could not parse error response as JSON. Status:", response.status);
                        }
                     }
                    showError(errorMessage);
                }
            } catch (error) {
                console.error('Error during Emby login fetch:', error);
                showError('A network error occurred.');
            } finally {
                 setLoadingState(false);
            }
        });
    }

    if (embyAuthModal) {
        embyAuthModal.addEventListener('click', (event) => {
            if (event.target === embyAuthModal) {
                hideModal();
            }
        });
    }

}); 
