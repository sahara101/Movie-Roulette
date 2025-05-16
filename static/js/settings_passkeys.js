function bufferDecode(value) {
    return Uint8Array.from(atob(value.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0));
}
function bufferEncode(value) {
    return btoa(String.fromCharCode.apply(null, new Uint8Array(value)))
        .replace(/\+/g, "-")
        .replace(/\//g, "_")
        .replace(/=/g, "");
}

function formatDateSimple(dateString) {
    if (!dateString) return 'Unknown date';
    try {
        const date = new Date(dateString);
        return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
    } catch (e) {
        return dateString;
    }
}

async function handleAddPasskey() {
    const addButton = document.querySelector('.add-passkey-button');
    if(addButton) addButton.disabled = true;
    if (typeof window.showSuccess !== 'function' || typeof window.showError !== 'function' || typeof window.getCsrfToken !== 'function') {
        console.error('showSuccess, showError, or getCsrfToken not available globally.');
        if(addButton) addButton.disabled = false;
        alert('A UI error occurred. Please refresh.');
        return;
    }

    let passkeyName;
    try {
        passkeyName = await showPasskeyNameModal();
    } catch (error) {
        window.showError('Passkey registration cancelled.');
        if(addButton) addButton.disabled = false;
        return;
    }

    if (!passkeyName) {
        window.showError('Passkey name cannot be empty. Registration cancelled.');
        if(addButton) addButton.disabled = false;
        return;
    }

    window.showSuccess('Requesting passkey registration options...');

    try {
        const response = await fetch('/api/auth/passkey/register-options', {
            method: 'POST',
            headers: { 'X-CSRFToken': window.getCsrfToken() }
        });
        const options = await response.json();

        if (!response.ok) {
            throw new Error(options.error || 'Failed to get registration options');
        }

        options.challenge = bufferDecode(options.challenge);
        options.user.id = bufferDecode(options.user.id);
        if (options.excludeCredentials) {
            for (let cred of options.excludeCredentials) {
                cred.id = bufferDecode(cred.id);
            }
        }
        
        console.log("Passkey Registration Options from server:", options);

        const credential = await navigator.credentials.create({ publicKey: options });
        console.log("Credential created by browser:", credential);

        const credentialForServer = {
            id: credential.id, 
            rawId: bufferEncode(credential.rawId),
            type: credential.type,
            response: {
                attestationObject: bufferEncode(credential.response.attestationObject),
                clientDataJSON: bufferEncode(credential.response.clientDataJSON),
            },
            name: passkeyName
        };
        if (typeof credential.response.getTransports === 'function') {
            credentialForServer.response.transports = credential.response.getTransports();
        }


        const verifyResponse = await fetch('/api/auth/passkey/register-verify', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': window.getCsrfToken()
            },
            body: JSON.stringify(credentialForServer)
        });

        const verifyResult = await verifyResponse.json();
        if (!verifyResponse.ok) {
            throw new Error(verifyResult.error || 'Passkey registration failed');
        }

        window.showSuccess('Passkey registered successfully!');
        const listContainer = document.querySelector('.passkey-list-container');
        if (listContainer) {
            loadAndRenderUserPasskeys(listContainer);
        }

    } catch (err) {
        console.error('Passkey registration error:', err);
        window.showError(`Error: ${err.message || 'Could not register passkey.'}`);
    } finally {
        if(addButton) addButton.disabled = false;
    }
}

async function loadAndRenderUserPasskeys(listContainer) {
    if (!listContainer) {
        console.error("Passkey list container not found for rendering.");
        return;
    }
    listContainer.innerHTML = '<p>Loading your registered passkeys...</p>';
    if (typeof window.showError !== 'function' || typeof window.getCsrfToken !== 'function') {
        console.error('showError or getCsrfToken not available globally.');
        listContainer.innerHTML = '<p class="error-message">UI error: Core functions missing.</p>';
        return;
    }

    try {
        const response = await fetch('/api/auth/passkey/list', { headers: { 'X-CSRFToken': window.getCsrfToken() } });
        const passkeys = await response.json();

        if (!response.ok) {
            throw new Error(passkeys.error || 'Failed to load passkeys');
        }
        
        listContainer.innerHTML = ''; 

        if (passkeys.length === 0) {
            listContainer.innerHTML = '<p>No passkeys registered for this account.</p>';
            return;
        }

        const ul = document.createElement('ul');
        ul.className = 'passkey-list user-list';
        passkeys.forEach(key => {
            const li = document.createElement('li');
            li.className = 'passkey-item user-item';
            
            let displayName = key.name || `Passkey (ID: ...${key.id.slice(-12)})`;
            if (key.name) {
                displayName = `${key.name} (${key.device_type === 'single_device' ? 'Device-bound' : 'Synced'}, added ${formatDateSimple(key.created_at)})`;
            } else if (key.device_type) {
                displayName = `${key.device_type === 'single_device' ? 'Device-bound Key' : 'Synced Passkey'} (added ${formatDateSimple(key.created_at)})`;
            } else {
                 displayName = `Passkey (added ${formatDateSimple(key.created_at)})`;
            }

            li.innerHTML = `
                <div class="user-info">
                    <span class="passkey-name user-name">${displayName}</span>
                </div>
                <div class="user-actions">
                    <button class="remove-passkey-button user-action delete" data-id="${key.id}" title="Remove this passkey">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            `;
            li.querySelector('.remove-passkey-button').addEventListener('click', () => handleRemovePasskey(key.id));
            ul.appendChild(li);
        });
        listContainer.appendChild(ul);

    } catch (err) {
        console.error('Error loading passkeys:', err);
        listContainer.innerHTML = `<p class="error-message">Error loading passkeys: ${err.message}</p>`;
    }
}

async function handleRemovePasskey(credentialId) {
    let confirmed = false;
    try {
        confirmed = await showRemovePasskeyConfirmModal();
    } catch (error) {
        return;
    }

    if (!confirmed) {
        return;
    }

    if (typeof window.showSuccess !== 'function' || typeof window.showError !== 'function' || typeof window.getCsrfToken !== 'function') {
        console.error('showSuccess, showError, or getCsrfToken not available globally.');
        alert('A UI error occurred. Please refresh.');
        return;
    }
    window.showSuccess('Removing passkey...');
    try {
        const response = await fetch('/api/auth/passkey/remove', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': window.getCsrfToken()
            },
            body: JSON.stringify({ credential_id: credentialId })
        });
        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.error || 'Failed to remove passkey');
        }
        window.showSuccess('Passkey removed successfully!');
        const listContainer = document.querySelector('.passkey-list-container');
        if (listContainer) {
            loadAndRenderUserPasskeys(listContainer);
        }
    } catch (err) {
        console.error('Error removing passkey:', err);
        window.showError(`Error: ${err.message || 'Could not remove passkey.'}`);
    }
}

window.renderPasskeyManagementSection = function(container, currentSettingsFromMain, getNestedValueFunc) {
    const wrapper = document.createElement('div');
    wrapper.className = 'passkey-management-wrapper';
    container.appendChild(wrapper);

    const passkeysGloballyEnabled = getNestedValueFunc(currentSettingsFromMain, 'auth.passkey_enabled');
    const isLocalUser = window.serviceType === 'local';

    if (!passkeysGloballyEnabled) {
        wrapper.innerHTML = '<p class="setting-description">Passkey authentication is currently disabled in global settings.</p>';
        return;
    }
    if (!isLocalUser) {
        wrapper.innerHTML = '<p class="setting-description">Passkeys can only be managed for local accounts.</p>';
        return;
    }
    
    const addButton = document.createElement('button');
    addButton.className = 'discover-button add-passkey-button';
    addButton.innerHTML = '<i class="fas fa-plus-circle"></i> Add a Passkey';
    addButton.addEventListener('click', handleAddPasskey);
    wrapper.appendChild(addButton);
    
    const passkeySectionTitle = document.createElement('h2');
    passkeySectionTitle.textContent = 'Your Registered Passkeys:';
    wrapper.appendChild(passkeySectionTitle);

    const listContainer = document.createElement('div');
    listContainer.className = 'passkey-list-container'; 
    wrapper.appendChild(listContainer);

    loadAndRenderUserPasskeys(listContainer);
};

function showPasskeyNameModal() {
    return new Promise((resolve, reject) => {
        const modalOverlay = document.createElement('div');
        modalOverlay.className = 'custom-modal-overlay';
        modalOverlay.innerHTML = `
            <div class="custom-modal-content">
                <h3>Name Your Passkey</h3>
                <p>Please enter a descriptive name for this passkey (e.g., 'My Work Laptop', 'Personal Phone').</p>
                <div class="custom-modal-input-group">
                    <label for="passkey-name-input">Passkey Name</label>
                    <input type="text" id="passkey-name-input" class="custom-modal-input" placeholder="e.g., My Work Laptop">
                </div>
                <div class="custom-modal-buttons">
                    <button type="button" class="custom-modal-button secondary" id="cancel-name-btn">Cancel</button>
                    <button type="button" class="custom-modal-button primary" id="save-name-btn">Save</button>
                </div>
            </div>
        `;
        document.body.appendChild(modalOverlay);
        const input = modalOverlay.querySelector('#passkey-name-input');
        input.focus();

        const closeModal = (value) => {
            document.body.removeChild(modalOverlay);
            if (value) {
                resolve(value);
            } else {
                reject();
            }
        };

        modalOverlay.querySelector('#save-name-btn').addEventListener('click', () => {
            const name = input.value.trim();
            if (name) {
                closeModal(name);
            } else {
                if (typeof window.showError === 'function') {
                    window.showError('Passkey name cannot be empty.');
                } else {
                    alert('Passkey name cannot be empty.');
                }
                input.focus();
            }
        });

        modalOverlay.querySelector('#cancel-name-btn').addEventListener('click', () => closeModal(null));
        modalOverlay.addEventListener('click', (e) => {
            if (e.target === modalOverlay) {
                closeModal(null);
            }
        });
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                modalOverlay.querySelector('#save-name-btn').click();
            }
        });
    });
}

function showRemovePasskeyConfirmModal() {
    return new Promise((resolve, reject) => {
        const modalOverlay = document.createElement('div');
        modalOverlay.className = 'custom-modal-overlay';
        modalOverlay.innerHTML = `
            <div class="custom-modal-content">
                <h3>Remove Passkey</h3>
                <p>Are you sure you want to remove this passkey? This action cannot be undone.</p>
                <div class="custom-modal-buttons">
                    <button type="button" class="custom-modal-button secondary" id="cancel-remove-btn">Cancel</button>
                    <button type="button" class="custom-modal-button danger" id="confirm-remove-btn">Remove</button>
                </div>
            </div>
        `;
        document.body.appendChild(modalOverlay);

        const confirmButton = modalOverlay.querySelector('#confirm-remove-btn');
        confirmButton.focus();

        const closeModal = (confirmed) => {
            document.body.removeChild(modalOverlay);
            if (confirmed) {
                resolve(true);
            } else {
                reject();
            }
        };

        confirmButton.addEventListener('click', () => closeModal(true));
        modalOverlay.querySelector('#cancel-remove-btn').addEventListener('click', () => closeModal(false));
        modalOverlay.addEventListener('click', (e) => {
            if (e.target === modalOverlay) {
                closeModal(false);
            }
        });
    });
}
