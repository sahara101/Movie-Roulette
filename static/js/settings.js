document.addEventListener('DOMContentLoaded', function() {
    const settingsRoot = document.getElementById('settings-root');
    let currentSettings = null;
    let currentOverrides = null;
    let traktStatus = { enabled: false, connected: false, env_controlled: false }; 

    function getCsrfToken() {
        const token = document.querySelector('meta[name="csrf-token"]');
        return token ? token.getAttribute('content') : null;
    }

    function getNestedValue(obj, path) {
        return path.split('.').reduce((curr, key) => {
            if (curr === null || curr === undefined) return null;
            const value = curr[key];
            if (Array.isArray(value)) {
                return value.join(',');
            }
            return value;
        }, obj);
    }

    function setNestedValue(obj, path, value) {
        const keys = path.split('.');
        const lastKey = keys.pop();
        const target = keys.reduce((curr, key) => {
            if (!(key in curr)) {
                curr[key] = {};
            }
            return curr[key];
        }, obj);

        if (path.includes('poster_users') && typeof value === 'string') {
            target[lastKey] = value.split(',').map(item => item.trim()).filter(Boolean);
        } else {
            target[lastKey] = value;
        }

        return obj;
    }

    function showMessage(message) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'info-message';
        messageDiv.textContent = message;
        settingsRoot.insertBefore(messageDiv, settingsRoot.firstChild);
        setTimeout(() => messageDiv.remove(), 3000);
    }

    function showError(message) {
        const error = document.createElement('div');
        error.className = 'error-message';
        error.textContent = message;
        settingsRoot.insertBefore(error, settingsRoot.firstChild);
        setTimeout(() => error.remove(), 3000);
    }

    function showSuccess(message) {
        const success = document.createElement('div');
        success.className = 'success-message';
        success.textContent = message;
        settingsRoot.insertBefore(success, settingsRoot.firstChild);
        setTimeout(() => success.remove(), 3000);
    }

    function createInput(type, value, disabled, onChange, placeholder = '') {
        const input = document.createElement('input');
        input.type = type;
        input.value = value || '';
        input.disabled = disabled;
        input.placeholder = placeholder;
        input.className = 'setting-input';
        if (!disabled) {
            input.addEventListener('change', (e) => onChange(e.target.value));
        }
        return input;
    }

    function createToggle(checked, disabled, isEnvEnabled, onChange) {
        const toggle = document.createElement('div');
        toggle.className = `toggle ${(checked || isEnvEnabled) ? 'active' : ''} ${disabled ? 'disabled' : ''}`;

        if (!disabled) {
            toggle.addEventListener('click', () => {
                toggle.classList.toggle('active');
                onChange(toggle.classList.contains('active'));
            });
        } else {
            toggle.style.pointerEvents = 'none';
            toggle.title = 'This setting is controlled by environment variables';
        }

        return toggle;
    }

    async function handleSettingChange(key, value) {
    	try {
            if (currentOverrides && getNestedValue(currentOverrides, key)) {
            	showError('Cannot modify environment-controlled setting');
            	return;
            }

            if (key.includes('poster_users') && typeof value === 'string') {
            	value = value.split(',').map(item => item.trim()).filter(Boolean);
            }

            const category = key.split('.')[0];
            const updateData = {};
            const keyParts = key.split('.');
            let current = updateData;

            for (let i = 1; i < keyParts.length - 1; i++) {
            	current[keyParts[i]] = {};
            	current = current[keyParts[i]];
            }
            current[keyParts[keyParts.length - 1]] = value;

            console.log('Updating setting:', key, 'with value:', value);

            const csrfToken = getCsrfToken(); 

            if (!csrfToken) {
                console.error("[handleSettingChange] CSRF Token is missing!");
                showError("CSRF Token missing. Please refresh the page.");
                return; 
            }

            const response = await fetch(`/api/settings/${category}`, {
            	method: 'POST',
            	headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken 
                },
            	body: JSON.stringify(updateData)
            });

            if (!response.ok) {
            	const errorData = await response.json();
            	throw new Error(errorData.message || 'Failed to update setting');
            }

            const result = await response.json();
            
            if (result.status === 'redirect') {
                showMessage(result.message || 'Redirecting to setup page...');
                setTimeout(() => {
                    window.location.href = result.redirect;
                }, 1500);
                return;
            }
            
            showSuccess('Setting updated successfully');
            setNestedValue(currentSettings, key, value);

            if (key === 'features.poster_display.mode') {
            	const preferredUserContainer = document.querySelector('.preferred-user-wrapper')?.parentElement;
            	if (preferredUserContainer) {
                    preferredUserContainer.innerHTML = '';
                    renderPreferredUserSelector(preferredUserContainer);
            	}
            }

    	} catch (error) {
            console.error('Error updating setting:', error);
            showError(error.message || 'Failed to update setting');
    	}
    }

    function createTraktIntegration(container) {
        const wrapper = document.createElement('div');
        wrapper.className = 'trakt-integration-wrapper';

        const button = document.createElement('button');
        button.className = 'trakt-connect-button';

        function updateButtonState(loading = false) {
            const isConnected = traktStatus.connected;
            const isEnvControlled = traktStatus.env_controlled;

            button.className = `trakt-connect-button ${isConnected ? 'connected' : ''} ${loading ? 'loading' : ''}`;
            if (loading) {
                button.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Processing...`;
                button.disabled = true;
            } else {
                button.innerHTML = `
                    <i class="fa-solid fa-${isConnected ? 'plug-circle-xmark' : 'plug'}"></i>
                    ${isConnected ? 'Disconnect from Trakt' : 'Connect Trakt Account'}
                `;
                button.disabled = isEnvControlled; 

                const wrapper = button.closest('.trakt-integration-wrapper'); 
                if (wrapper) {
                    let overrideIndicator = wrapper.querySelector('.env-override');
                    if (isEnvControlled) {
                        if (!overrideIndicator) {
                            overrideIndicator = document.createElement('div');
                            overrideIndicator.className = 'env-override';
                            overrideIndicator.textContent = 'Set by environment variable';
                            wrapper.appendChild(overrideIndicator);
                        }
                        button.title = 'Trakt is configured via environment variables';
                    } else {
                        if (overrideIndicator) {
                            overrideIndicator.remove(); 
                        }
                        button.removeAttribute('title');
                    }
                }
            }
        }

        function checkConnectionStatus() {
             console.log('Updating Trakt button state based on:', traktStatus);
             updateButtonState(false); 
             return traktStatus;
        }

        async function handleOAuthFlow(authUrl) {
            const codeDialog = document.createElement('div');
            codeDialog.className = 'trakt-confirm-dialog';
            codeDialog.innerHTML = `
                <div class="dialog-content">
                    <h3>Connect to Trakt</h3>
                    <div class="dialog-steps">
                        <p class="step current">1. Authorize Movie Roulette in the Trakt window</p>
                        <p class="step">2. Copy the code shown by Trakt</p>
                        <p class="step">3. Paste the code here and click Connect</p>
                    </div>
                    <input type="text"
                           class="setting-input code-input"
                           placeholder="Paste your authorization code here"
                           autocomplete="off"
                           spellcheck="false">
                    <div class="dialog-note">
                        <i class="fa-solid fa-info-circle"></i>
                        Paste the code from Trakt and click Connect. You can close the Trakt window after.
                    </div>
                    <div class="dialog-buttons">
                        <button class="cancel-button">Cancel</button>
                        <button class="submit-button" disabled>Connect</button>
                    </div>
                </div>
            `;

            document.body.appendChild(codeDialog);

            const popup = window.open(
                authUrl,
                'TraktAuth',
                'width=600,height=800'
            );

            if (!popup) {
                showError('Popup was blocked. Please allow popups for this site.');
                codeDialog.remove();
                updateButtonState(false, false);
                return;
            }

            const input = codeDialog.querySelector('.code-input');
            const submitButton = codeDialog.querySelector('.submit-button');
            const steps = codeDialog.querySelectorAll('.step');

            input.focus();

            input.addEventListener('input', () => {
                const hasValue = input.value.trim();
                submitButton.disabled = !hasValue;
                if (hasValue) {
                    steps[1].classList.remove('current');
                    steps[2].classList.add('current');
                } else {
                    steps[1].classList.add('current');
                    steps[2].classList.remove('current');
                }
            });

            const checkPopup = setInterval(() => {
                if (popup.closed) {
                    clearInterval(checkPopup);
                    const note = codeDialog.querySelector('.dialog-note');
                    note.innerHTML = '<i class="fa-solid fa-check-circle"></i> Trakt window closed. Click Connect when ready.';
                }
            }, 1000);

            input.addEventListener('keypress', (e) => {
                if (e.key === 'Enter' && !submitButton.disabled) {
                    submitButton.click();
                }
            });

            function removeDialog() {
                if (!popup.closed) {
                    popup.close();
                }
                clearInterval(checkPopup);
                codeDialog.remove();
                updateButtonState(false, false);
            }

            codeDialog.addEventListener('click', (e) => {
                if (e.target === codeDialog) {
                    removeDialog();
                }
            });

            codeDialog.querySelector('.cancel-button').addEventListener('click', removeDialog);

            submitButton.addEventListener('click', async () => {
                const code = input.value.trim();
                if (!code) {
                    showError('Please enter the authorization code');
                    return;
                }

                updateButtonState(false, true);
                submitButton.disabled = true;
                submitButton.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Connecting...';

                try {
                    const response = await fetch('/trakt/token', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCsrfToken() 
                        },
                        body: JSON.stringify({ code })
                    });

                    const data = await response.json();
                    if (response.ok && data.status === 'success') {
                        showSuccess('Successfully connected to Trakt');
                        codeDialog.remove();
                        traktStatus.connected = true;
                        traktStatus.enabled = true; 
                        checkConnectionStatus(); 
                    } else {
                        throw new Error(data.error || 'Failed to connect to Trakt');
                    }
                } catch (error) {
                    showError(error.message);
                    submitButton.disabled = false;
                    submitButton.textContent = 'Connect';
                    updateButtonState(false, false);
                }
            });
        }

        async function handleDisconnect() {
            const confirmDialog = document.createElement('div');
            confirmDialog.className = 'trakt-confirm-dialog';
            confirmDialog.innerHTML = `
                <div class="dialog-content">
                    <h3>Disconnect from Trakt?</h3>
                    <p>This will remove the connection between Movie Roulette and your Trakt account.
                       Your Trakt history and ratings will remain unchanged.</p>
                    <div class="dialog-buttons">
                        <button class="cancel-button">Cancel</button>
                        <button class="disconnect-button">Disconnect</button>
                    </div>
                </div>
            `;

            document.body.appendChild(confirmDialog);

            function removeDialog() {
                confirmDialog.remove();
            }

            confirmDialog.addEventListener('click', (e) => {
                if (e.target === confirmDialog) {
                    removeDialog();
                }
            });

            confirmDialog.querySelector('.cancel-button').addEventListener('click', removeDialog);

            confirmDialog.querySelector('.disconnect-button').addEventListener('click', async () => {
                updateButtonState(false, true);
                removeDialog();

                try {
                    const response = await fetch('/trakt/disconnect');
                    const data = await response.json();

                    if (!response.ok) {
                        if (data.status === 'env_controlled') {
                            showError('Cannot disconnect: Trakt is configured via environment variables');
                            updateButtonState(true, false, true);
                        } else {
                            throw new Error(data.error || 'Failed to disconnect');
                        }
                    } else if (data.status === 'success') {
                        showSuccess('Successfully disconnected from Trakt');
                        traktStatus.connected = false;
                        checkConnectionStatus(); // Update button
                    }
                } catch (error) {
                    showError(error.message || 'Failed to disconnect from Trakt');
                    checkConnectionStatus();
                }
            });
        }

        button.addEventListener('click', async () => {
            const status = checkConnectionStatus();

            if (status.env_controlled) {
                return;
            }

            if (status.connected) {
                handleDisconnect();
            } else {
                updateButtonState(false, true);

                try {
                    const response = await fetch('/trakt/authorize');
                    if (!response.ok) {
                        throw new Error('Failed to initialize Trakt authorization');
                    }

                    const data = await response.json();
                    if (!data.auth_url) {
                        throw new Error('Invalid authorization URL');
                    }

                    await handleOAuthFlow(data.auth_url);
                } catch (error) {
                    console.error('Trakt authorization error:', error);
                    showError(error.message || 'Failed to start Trakt authorization');
                    updateButtonState(false, false);
                }
            }
        });

        wrapper.appendChild(button);
        container.appendChild(wrapper);
        checkConnectionStatus(); 
    }

    function renderSettingsSection(title, settings, envOverrides, fields) {
    	const section = document.createElement('div');
    	section.className = 'settings-section';

    	const titleElem = document.createElement('h2');
    	titleElem.textContent = title;
    	section.appendChild(titleElem);

    	fields.forEach(async field => { 
            const fieldContainer = document.createElement('div');
            fieldContainer.className = 'setting-field';

            const label = document.createElement('label');
            label.textContent = field.label;
            fieldContainer.appendChild(label);

            if (field.description) {
            	const description = document.createElement('div');
            	description.className = 'setting-description';
            	description.innerHTML = field.description;
            	fieldContainer.appendChild(description);
            }

            if (field.key === 'trakt.connect') {
                const defaultLabel = fieldContainer.querySelector('label');
                if (defaultLabel) defaultLabel.remove();
                const defaultDesc = fieldContainer.querySelector('.setting-description');
                 if (defaultDesc) defaultDesc.remove();

                const buttonLabel = document.createElement('label');
                buttonLabel.textContent = field.label || 'Trakt Account'; 
                fieldContainer.appendChild(buttonLabel);

            	createTraktIntegration(fieldContainer); 
            	section.appendChild(fieldContainer);
            	return; 
            }

            if (field.type === 'custom' && typeof field.render === 'function') {
            	field.render(fieldContainer);
            	section.appendChild(fieldContainer);
            	return;
            }

            if (field.key === 'tmdb.api_key') {
            	const isOverridden = Boolean(getNestedValue(envOverrides, 'tmdb.api_key'));
            	const tmdbEnabled = getNestedValue(settings, 'tmdb.enabled');

            	let input;
            	if (isOverridden) {
                    input = createInput(
                    	'password',
                    	getNestedValue(settings, 'tmdb.api_key'),
                    	true,
                    	() => {},
                    	''
                    );
                    input.setAttribute('data-field-key', 'tmdb.api_key');
                    const overrideIndicator = document.createElement('div');
                    overrideIndicator.className = 'env-override';
                    overrideIndicator.textContent = 'Set by environment variable';
                    fieldContainer.appendChild(input);
                    fieldContainer.appendChild(overrideIndicator);
            	} else if (tmdbEnabled) {
                    input = createInput(
                    	'password',
                    	getNestedValue(settings, 'tmdb.api_key'),
                    	false,
                    	(value) => handleSettingChange(field.key, value),
                    	'Enter your TMDB API key'
                    );
                    input.setAttribute('data-field-key', 'tmdb.api_key');
                    fieldContainer.appendChild(input);
            	} else {
                    input = createInput(
                    	'text',
                    	'Using built-in API key',
                    	true,
                    	() => {},
                    	''
                    );
                    input.setAttribute('data-field-key', 'tmdb.api_key');
                    fieldContainer.appendChild(input);
            	}
            	section.appendChild(fieldContainer);
            	return;
            }

            const value = getNestedValue(settings, field.key);
            let isOverridden = getNestedValue(envOverrides, field.key);

            const isIntegrationToggle = (
            	field.key === 'overseerr.enabled' ||
            	field.key === 'trakt.enabled' ||
            	field.key === 'jellyseerr.enabled' ||
            	field.key === 'ombi.enabled'
            );

            const isPlexEnv = Boolean(
            	getNestedValue(envOverrides, 'plex.url') &&
            	getNestedValue(envOverrides, 'plex.token') &&
            	getNestedValue(envOverrides, 'plex.movie_libraries')
            );
            const isJellyfinEnv = Boolean(
            	getNestedValue(envOverrides, 'jellyfin.url') &&
            	getNestedValue(envOverrides, 'jellyfin.api_key') &&
            	getNestedValue(envOverrides, 'jellyfin.user_id')
            );
            const isEmbyEnv = Boolean(
            	getNestedValue(envOverrides, 'emby.url') &&
            	getNestedValue(envOverrides, 'emby.api_key') &&
            	getNestedValue(envOverrides, 'emby.user_id')
            );
            const isAppleTVEnv = getNestedValue(envOverrides, 'clients.apple_tv.id');
            const isOverseerrEnv = Boolean(
            	getNestedValue(envOverrides, 'overseerr.url') &&
            	getNestedValue(envOverrides, 'overseerr.api_key')
            );
            const isJellyseerrEnv = Boolean(
            	getNestedValue(envOverrides, 'jellyseerr.url') &&
            	getNestedValue(envOverrides, 'jellyseerr.api_key')
            );
            const isOmbiEnv = Boolean(
            	getNestedValue(envOverrides, 'ombi.url') &&
            	getNestedValue(envOverrides, 'ombi.api_key')
            );
            const isTraktEnv = Boolean(
            	getNestedValue(envOverrides, 'trakt.client_id') &&
            	getNestedValue(envOverrides, 'trakt.client_secret') &&
            	getNestedValue(envOverrides, 'trakt.access_token') &&
            	getNestedValue(envOverrides, 'trakt.refresh_token')
            );

            let isEnvEnabled = false;
            const isServiceToggle = field.key === 'plex.enabled' || field.key === 'jellyfin.enabled' || field.key === 'emby.enabled';
            const isClientToggle = field.key === 'clients.apple_tv.enabled'

            if (isServiceToggle || isClientToggle || isIntegrationToggle) {
            	switch (field.key) {
                    case 'plex.enabled':
                    	isOverridden = isPlexEnv;
                    	isEnvEnabled = isPlexEnv;
                    	break;
                    case 'jellyfin.enabled':
                    	isOverridden = isJellyfinEnv;
                    	isEnvEnabled = isJellyfinEnv;
                    	break;
                    case 'emby.enabled':
                    	isOverridden = isEmbyEnv;
                    	isEnvEnabled = isEmbyEnv;
                    	break;
                    case 'clients.apple_tv.enabled':
                    	isOverridden = isAppleTVEnv;
                    	isEnvEnabled = isAppleTVEnv;
                    	break;
                    case 'overseerr.enabled':
                    	isOverridden = isOverseerrEnv;
                    	isEnvEnabled = isOverseerrEnv;
                    	break;
                    case 'jellyseerr.enabled':
                    	isOverridden = isJellyseerrEnv;
                    	isEnvEnabled = isJellyseerrEnv;
                    	break;
                    case 'ombi.enabled':
                    	isOverridden = isOmbiEnv;
                    	isEnvEnabled = isOmbiEnv;
                    	break;
                    case 'trakt.enabled':
                    	isOverridden = isTraktEnv;
                    	isEnvEnabled = isTraktEnv;
                    	break;
                }
            }

            if (field.type === 'select') {
            	const select = document.createElement('select');
            	select.className = 'setting-input';
            	select.disabled = isOverridden;

            	field.options.forEach(option => {
                    const optionElement = document.createElement('option');
                    optionElement.value = option.value;
                    optionElement.textContent = option.label;
                    if (option.value === value) {
                    	optionElement.selected = true;
                    }
                    select.appendChild(optionElement);
            	});

            	if (!isOverridden) {
                    select.addEventListener('change', (e) => handleSettingChange(field.key, e.target.value));
            	}
            	fieldContainer.appendChild(select);
            	if (isOverridden) {
            	       const overrideIndicator = document.createElement('div');
            	       overrideIndicator.className = 'env-override';
            	       overrideIndicator.textContent = 'Set by environment variable';
            	       fieldContainer.appendChild(overrideIndicator);
            	   }
            } else if (field.key === 'trakt.enabled') { 
                const currentValue = traktStatus.enabled;
                const toggle = createToggle(
                    currentValue,
                    isOverridden, 
                    isEnvEnabled, 
                    handleTraktToggleChange 
                );
                fieldContainer.appendChild(toggle);
                if (isOverridden) {
                    const overrideIndicator = document.createElement('div');
                    overrideIndicator.className = 'env-override';
                    overrideIndicator.textContent = 'Set by environment variable';
                    fieldContainer.appendChild(overrideIndicator);
                }
            } else if (field.type === 'switch') { 
            	const toggle = createToggle(
                    value, 
                    isOverridden, 
                    isEnvEnabled, 
                    (checked) => handleSettingChange(field.key, checked) 
            	);
            	fieldContainer.appendChild(toggle);
            	   if (isOverridden) { // Use the isOverridden determined earlier
            	       const overrideIndicator = document.createElement('div');
            	       overrideIndicator.className = 'env-override';
            	       overrideIndicator.textContent = 'Set by environment variable';
            	       fieldContainer.appendChild(overrideIndicator);
            	   }
            } else { 
                let inputType = (field.type === 'password') ? 'password' : 'text';
            	const input = createInput(
                    inputType, 
                    value,
                    isOverridden,
                    (value) => handleSettingChange(field.key, value),
                    field.placeholder
            	);
            	   input.setAttribute('data-field-key', field.key); 
            	   fieldContainer.appendChild(input);
            	      if (isOverridden) { // Use the isOverridden determined earlier
            	          const overrideIndicator = document.createElement('div');
            	          overrideIndicator.className = 'env-override';
            	          overrideIndicator.textContent = 'Set by environment variable';
            	          fieldContainer.appendChild(overrideIndicator);
            	      }
            }
 
            // Append the fully constructed field container to the section
            section.appendChild(fieldContainer);
    	});

    	return section;
    }

    const container = document.createElement('div');
    container.className = 'settings-container';

    const header = document.createElement('div');
    header.className = 'settings-header';
    header.innerHTML = `
    	<h1>Settings</h1>
    	<div class="header-controls">
            <div class="dropdown">
	        <a class="donate-button">Sponsor<i class="fa-solid fa-chevron-down"></i></a>
                <div class="dropdown-content">
                    <a href="https://github.com/sponsors/sahara101"
                       target="_blank"
                       rel="noopener noreferrer">
                        <i class="fa-brands fa-github"></i>
                        GitHub
                    </a>
                    <a href="https://ko-fi.com/sahara101/donate"
                       target="_blank"
                       rel="noopener noreferrer">
                        <i class="fa-solid fa-mug-hot"></i>
                        Ko-fi
                    </a>
                </div>
            </div>
             <a href="/" class="back-button">
                <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none"
                    stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <line x1="19" y1="12" x2="5" y2="12"></line>
                    <polyline points="12 19 5 12 12 5"></polyline>
                </svg>
                Back to Movies
            </a>
        </div>
    `;
    container.appendChild(header);

    const tabs = document.createElement('div');
    tabs.className = 'settings-tabs';
    tabs.innerHTML = `
        <button class="tab" data-tab="media">Media Servers</button>
        <button class="tab" data-tab="clients">Clients</button>
        <button class="tab" data-tab="features">Features</button>
        <button class="tab" data-tab="integrations">Integrations</button>
	<button class="tab" data-tab="auth">Authentication</button>
    `;
    container.appendChild(tabs);

    const contentContainer = document.createElement('div');
    contentContainer.className = 'settings-content';
    container.appendChild(contentContainer);

    settingsRoot.appendChild(container);

    async function checkVersion(manual = false) {
    	try {
            const response = await fetch('/api/check_version');
            const data = await response.json();

            if (data.update_available && (data.show_popup || manual)) {
            	showUpdateDialog(data);
            } else if (manual) {
            	showSuccess('You are running the latest version!');
            }
    	} catch (error) {
            console.error('Error checking version:', error);
            if (manual) {
            	showError('Failed to check for updates');
            }
    	}
    }

    function showUpdateDialog(updateInfo) {
    	const dialog = document.createElement('div');
    	dialog.className = 'trakt-confirm-dialog';
    	dialog.innerHTML = `
            <div class="dialog-content">
            	<h3>Update Available!</h3>
            	<p class="version-info">Version ${updateInfo.latest_version} is now available (you have ${updateInfo.current_version})</p>
            	<div class="changelog">
                    <h4>Changelog:</h4>
                    <div class="changelog-content">${updateInfo.changelog}</div>
            	</div>
            	<div class="dialog-buttons">
                    <button class="cancel-button">Dismiss</button>
                    <a href="${updateInfo.download_url}"
                   	class="submit-button"
                   	target="_blank"
                   	rel="noopener noreferrer">View Release</a>
                </div>
            </div>
    	`;

    	document.body.appendChild(dialog);

    	const closeDialog = () => {
            dialog.remove();
            fetch('/api/dismiss_update').catch(console.error);
    	};

    	dialog.querySelector('.cancel-button').addEventListener('click', closeDialog);
    	dialog.addEventListener('click', (e) => {
            if (e.target === dialog) closeDialog();
    	});
    }

    function renderVersionCheckButton(container) {
    	const wrapper = document.createElement('div');
    	wrapper.className = 'version-check-wrapper';

    	const button = document.createElement('button');
    	button.className = 'discover-button';
    	button.innerHTML = '<i class="fa-solid fa-rotate"></i> Check for Updates';

    	button.addEventListener('click', async () => {
            button.disabled = true;
            button.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Checking...';

            try {
            	await checkVersion(true);  
            } finally {
            	button.disabled = false;
            	button.innerHTML = '<i class="fa-solid fa-rotate"></i> Check for Updates';
            }
    	});

    	wrapper.appendChild(button);
    	container.appendChild(wrapper);
    }

    document.addEventListener('DOMContentLoaded', () => {
    	setTimeout(() => {
            checkVersion(false);  
    	}, 2000);  
    });

    const sections = {
        media: {
            title: 'Media Servers',
            sections: [
                {
                    title: 'Plex Configuration',
                    fields: [
                        { key: 'plex.enabled', label: 'Enable Plex', type: 'switch' },
                        { key: 'plex.url', label: 'Plex URL', type: 'text', placeholder: 'http://localhost:32400' },
			{
            		    key: 'plex.token_config',
            		    label: 'Plex Token',
            		    type: 'custom',
            		    render: renderPlexTokenConfig
        		},
			{
            		    key: 'plex.libraries_config',
            		    label: 'Movie Libraries',
            		    type: 'custom',
            		    render: renderPlexLibrariesConfig
        		}
                    ]
                },
                {
                    title: 'Jellyfin Configuration',
                    fields: [
                        { key: 'jellyfin.enabled', label: 'Enable Jellyfin', type: 'switch' },
                        { key: 'jellyfin.url', label: 'Jellyfin URL', type: 'text', placeholder: 'http://localhost:8096' },
			{
            		    key: 'jellyfin.auth_config',
            		    label: 'Authentication',
            		    type: 'custom',
            		    render: renderJellyfinAuthConfig
        		}
                    ]
                },
		{
                    title: 'Emby Configuration',
                    fields: [
                        { key: 'emby.enabled', label: 'Enable Emby', type: 'switch' },
                        { key: 'emby.url', label: 'Emby URL', type: 'text', placeholder: 'http://localhost:8096' },
                        {
                            key: 'emby.auth_config',
                            label: 'Authentication',
                            type: 'custom',
                            render: renderEmbyAuthConfig
                        }
                    ]
                }
           ]
        },
        clients: {
            title: 'Client Devices',
            fields: [
                { key: 'clients.apple_tv.enabled', label: 'Enable Apple TV', type: 'switch' },
                {
                    key: 'clients.apple_tv.configuration',
                    label: 'Apple TV Configuration',
                    type: 'custom',
                    render: renderAppleTVConfig
                },
		{
            	    key: 'clients.tvs.configuration',
            	    label: 'Smart TVs',
            	    type: 'custom',
            	    render: renderSmartTVSection
        	}
            ]
        },
        features: {
            title: 'Features',
            sections: [
                {
                    title: 'General Features',
                    fields: [
                        { key: 'features.use_links', label: 'Enable Links', type: 'switch' },
                        { key: 'features.use_filter', label: 'Enable Filters', type: 'switch' },
                        { key: 'features.use_watch_button', label: 'Enable Watch Button', type: 'switch' },
                        { key: 'features.use_next_button', label: 'Enable Next Button', type: 'switch' },
			{ key: 'features.mobile_truncation', label: 'Enable Mobile Description Truncation', type: 'switch' },
			{
            		    key: 'features.homepage_mode',
            		    label: 'Homepage Mode',
            		    type: 'switch',
            		    description: 'Provides a simplified, non-interactive display format ideal for <a href="https://gethomepage.dev" target="_blank" rel="noopener noreferrer">Homepage</a> iframe integration. Removes buttons, links, and keeps movie descriptions fully expanded.'
        		},
   { key: 'features.enable_movie_logos', label: 'Enable Movie Title Logos', type: 'switch' }, 
   { 
       key: 'features.load_movie_on_start',
       label: 'Load Movie on Page Start',
       type: 'switch', 
       description: 'If enabled, a random movie is loaded automatically when the page opens. If disabled, you need to click the "Get Random Movie" button first.'
   }
        		          ]
                },
                {
                    title: 'Poster Settings',
                    fields: [
			{
            		    key: 'features.poster_mode',
            		    label: 'Default Poster Mode',
            		    type: 'select',
            		    options: [
                		{ value: 'default', label: 'Static Default Poster' },
                		{ value: 'screensaver', label: 'Movie Poster Screensaver' }
            		    ],
            		    description: 'Choose between showing a static default poster or cycling through your movie posters'
        		},
        		{
            		    key: 'features.screensaver_interval',
            		    label: 'Screensaver Interval',
            		    type: 'select',
            		    options: [
                		{ value: '60', label: '1 minute' },
                		{ value: '300', label: '5 minutes' },
                		{ value: '600', label: '10 minutes' },
                		{ value: '900', label: '15 minutes' },
                		{ value: '1800', label: '30 minutes' },
                		{ value: '3600', label: '1 hour' }
            		    ],
            		    description: 'How often the screensaver should change posters'
        		},
			{
                    	    key: 'features.timezone',
                    	    label: 'Timezone',
                    	    type: 'custom',
                    	    render: renderTimezoneFieldWithButton
                	},
                        { key: 'features.default_poster_text', label: 'Default Poster Text', type: 'text' },
			{
            		    key: 'features.poster_users.plex',
            		    label: 'Plex Poster Users',
            		    type: 'custom',
            		    render: renderPlexUserSelector
        		},
        		{
            		    key: 'features.poster_users.jellyfin',
            		    label: 'Jellyfin Poster Users',
            		    type: 'custom',
            		    render: renderJellyfinUserSelector
        		},
			{
    			    key: 'features.poster_users.emby',
    			    label: 'Emby Poster Users',
    			    type: 'custom',
    			    render: renderEmbyUserSelector
			},
			{
            		    key: 'features.poster_display.mode',
            		    label: 'Movie Playback Poster Priority',
            		    type: 'select',
            		    options: [
                		{value: 'first_active', label: 'First Active User Takes Priority' },
                		{ value: 'preferred_user', label: 'Preferred User Takes Priority' }
            		    ],
            		    description: 'Choose how to handle multiple authorized users playing movies at the same time'
        		},
        		{
            		    key: 'features.poster_display.preferred_user',
            		    label: 'Preferred User',
            		    type: 'custom',
            		    render: renderPreferredUserSelector
        		}

                    ]
                }
            ]
        },
        integrations: {
            title: 'Integrations',
            sections: [
		{
                    title: 'System',
                    fields: [
                    	{
                            key: 'version_check',
                            label: 'Version Check',
                            type: 'custom',
                            render: renderVersionCheckButton
                    	}
		    ]
		},
		{
                    title: 'Request Services',
                    fields: [
                        {
                            key: 'request_services.default',
                            label: 'Global Default Service',
                            type: 'select',
                            options: [
                                { value: 'auto', label: 'Automatic' },
                                { value: 'overseerr', label: 'Overseerr' },
                                { value: 'jellyseerr', label: 'Jellyseerr' },
                                { value: 'ombi', label: 'Ombi' }
                            ],
                            description: 'The default request service to use when none is specified'
                        },
                        {
                            key: 'request_services.plex_override',
                            label: 'Plex Service Override',
                            type: 'select',
                            options: [
                                { value: 'auto', label: 'Use Default' },
                                { value: 'overseerr', label: 'Overseerr' },
                                { value: 'jellyseerr', label: 'Jellyseerr' },
                                { value: 'ombi', label: 'Ombi' }
                            ]
                        },
                        {
                            key: 'request_services.jellyfin_override',
                            label: 'Jellyfin Service Override',
                            type: 'select',
                            options: [
                                { value: 'auto', label: 'Use Default' },
                                { value: 'jellyseerr', label: 'Jellyseerr' },
                                { value: 'ombi', label: 'Ombi' }
                            ]
                        },
                        {
                            key: 'request_services.emby_override',
                            label: 'Emby Service Override',
                            type: 'select',
                            options: [
                                { value: 'auto', label: 'Use Default' },
                                { value: 'jellyseerr', label: 'Jellyseerr' },
                                { value: 'ombi', label: 'Ombi' }
                            ]
                        }
                    ]
                },
		{
            	    title: 'TMDB',
            	    fields: [
                	{
                    	    key: 'tmdb.enabled',
                    	    label: 'Use Custom TMDB API Key',
                    	    type: 'switch'
                	},
                	{
                    	    key: 'tmdb.api_key',
                    	    label: 'TMDB API Key (Optional)',
                    	    type: 'dynamic',
                    	    placeholder: 'Using built-in API key'
                	}
            	    ]
        	},
                {
                    title: 'Overseerr',
                    fields: [
                        { key: 'overseerr.enabled', label: 'Enable Overseerr', type: 'switch' },
                        { key: 'overseerr.url', label: 'Overseerr URL', type: 'text', placeholder: 'http://localhost:5055' },
                        { key: 'overseerr.api_key', label: 'API Key', type: 'password' },
                    ]
                },
		{
    		    title: 'Jellyseerr',
    		    fields: [
        		{
            		    key: 'jellyseerr.enabled',
            		    label: 'Enable Jellyseerr',
            		    type: 'switch'
        		},
        		{
            		    key: 'jellyseerr.url',
            		    label: 'Jellyseerr URL', placeholder: 'http://localhost:5055',
            		    type: 'text'
        		},
        		{
            		    key: 'jellyseerr.api_key',
            		    label: 'API Key',
            		    type: 'password'
        		}
    		    ]
		},
		{
                    title: 'Ombi',
                    fields: [
                        { key: 'ombi.enabled', label: 'Enable Ombi', type: 'switch' },
                        { key: 'ombi.url', label: 'Ombi URL', type: 'text', placeholder: 'http://localhost:5000' },
                        { key: 'ombi.api_key', label: 'API Key', type: 'password' }
                    ]
                },
                {
                    title: 'Trakt',
                    fields: [
			{ key: 'trakt.enabled', label: 'Enable Trakt', type: 'switch' },
                        { key: 'trakt.connect', label: 'Trakt Connection', type: 'custom' }
                    ]
                }
            ]
        },
	auth: {
            title: 'Authentication',
            sections: [
            	{
                    title: 'Authentication Settings',
                    fields: [
                    	{ key: 'auth.enabled', label: 'Enable Authentication', type: 'switch',
                          description: 'When enabled, users will be required to log in to access Movie Roulette' },
                        {
                            key: 'auth.session_lifetime',
                            label: 'Session Lifetime',
                            type: 'select',
                            options: [
                                { value: '86400', label: '1 Day' },    // 1 day
                                { value: '604800', label: '7 Days' },   // 7 days
                                { value: '2592000', label: '30 Days' },  // 30 days
                                { value: '7776000', label: '90 Days' },  // 90 days
                                { value: '31536000', label: '1 Year' } // 1 year (approx)
                            ],
                            description: 'Duration a standard username/password login session remains valid. Does not affect Plex/Jellyfin/Emby logins.'
                        },
                    	{
                    	       key: 'user_management',
                    	       label: 'User Management',
                    	       type: 'custom',
                    	       render: renderUserManagement
                    	},
                    	{ 
                    	    key: 'auth.user_cache_admin', 
                    	    label: 'User Cache Management',
                    	    type: 'custom',
                    	    render: function(container) {
                    	        const link = document.createElement('a');
                    	        link.href = '/user_cache_admin';
                    	        link.className = 'back-button admin-only'; 
                    	        link.innerHTML = `
                    	            <i class="fa-solid fa-database"></i>
                    	            <span>Open User Cache Admin</span>
                    	        `;
                    	        link.style.width = 'auto'; 
                    	        link.style.display = 'inline-flex'; 
                    	        container.appendChild(link);
                    	    }
                    	}
                    ]
            	}
            ]
    	}
    };

    function renderAppleTVConfig(container) {
        const wrapper = document.createElement('div');
        wrapper.className = 'appletv-setup-wrapper';

        const isEnvControlled = Boolean(
            getNestedValue(currentOverrides, 'clients.apple_tv.id')
        );

        if (isEnvControlled) {
            const overrideIndicator = document.createElement('div');
            overrideIndicator.className = 'env-override';
            overrideIndicator.textContent = 'Set by environment variable';
            wrapper.appendChild(overrideIndicator);
        } else {
            const scanButton = document.createElement('button');
            scanButton.className = 'discover-button';
            scanButton.innerHTML = '<i class="fa-solid fa-magnifying-glass"></i> Configure Apple TV';

            scanButton.addEventListener('click', async () => {
                try {
                    scanButton.disabled = true;
                    scanButton.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Scanning...';

                    const response = await fetch('/api/appletv/scan');
                    const data = await response.json();

                    showConfigDialog(data.devices || []);
                } catch (error) {
                    console.error('Scan error:', error);
                    showError(error.message || 'Failed to scan for Apple TVs');
                    showConfigDialog([]);
                } finally {
                    scanButton.disabled = false;
                    scanButton.innerHTML = '<i class="fa-solid fa-magnifying-glass"></i> Configure Apple TV';
                }
            });

            wrapper.appendChild(scanButton);
        }

        checkCurrentConfig().then(configDisplay => {
            if (configDisplay) {
                wrapper.appendChild(configDisplay);
            }
        });

        container.appendChild(wrapper);

        async function checkCurrentConfig() {
            const currentId = getNestedValue(currentSettings, 'clients.apple_tv.id');
            if (currentId) {
                try {
                    const response = await fetch('/api/appletv/check_credentials', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCsrfToken() 
                        },
                        body: JSON.stringify({ device_id: currentId })
                    });
                    const data = await response.json();

                    if (data.has_credentials) {
                        const configDisplay = document.createElement('div');
                        configDisplay.className = 'current-config';
                        configDisplay.innerHTML = `
                            <div class="config-item">Device ID: ${currentId}</div>
                        `;
                        return configDisplay; 
                    }
                } catch (error) {
                    console.error('Error checking device credentials:', error);
                }
            }
            return null;
        }

	function showConfigDialog(devices) {
   	    const dialog = document.createElement('div');
   	    dialog.className = 'trakt-confirm-dialog';

   	    let dialogContent = `
       	    	<div class="dialog-content">
           	    <h3><i class="fa-brands fa-apple"></i> Apple TV Configuration</h3>`;

   	    if (devices.length > 0) {
       	    	dialogContent += `
           	    <div class="dialog-section">
               	    	<h4>Found Devices</h4>
               	    	<div class="device-list">
                   	    ${devices.map((device, index) => `
                       	    	<button class="device-option" data-id="${device.identifier}">
                           	    <i class="fa-brands fa-apple"></i>
                           	    <div class="device-details">
                               	    	<div class="device-name">${device.name || `Apple TV ${index + 1}`}</div>
                               	    	<div class="device-info">ID: ${device.identifier}</div>
                               	    	${device.model ? `<div class="device-model">${device.model}</div>` : ''}
                           	    </div>
                       	    	</button>
                   	    `).join('')}
               	    	</div>
               	    	<div class="dialog-separator">
                   	    <span>or enter manually</span>
               	    	</div>
           	    </div>`;
   	    } else {
       	    	dialogContent += `
           	    <div class="scan-notice">
               	    	<i class="fa-solid fa-info-circle"></i>
               	    	<p>No Apple TVs found automatically. This could be because:</p>
               	    	<ul>
                   	    <li>The Apple TV is not powered on</li>
                   	    <li>The Apple TV is not connected to the network</li>
                   	    <li>The Apple TV is on a different subnet</li>
               	    	</ul>
               	    	<p>You can enter the Device ID manually below:</p>
           	    </div>`;
   	    }

   	    dialogContent += `
       	    	<div class="manual-input-group">
           	    <label>Device ID</label>
           	    <input type="text" class="setting-input" id="manual-id"
                      	   placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx">
       	    	</div>
       	    	<div class="dialog-buttons">
           	    <button class="cancel-button">Cancel</button>
           	    <button class="submit-button">Start Pairing</button>
       	    	</div>
   	    </div>`;

   	    dialog.innerHTML = dialogContent;
   	    document.body.appendChild(dialog);

   	    dialog.querySelectorAll('.device-option').forEach(button => {
       	    	button.addEventListener('click', () => {
           	    const id = button.dataset.id;
           	    dialog.querySelector('#manual-id').value = id;
       	        });
   	    });

   	    dialog.querySelector('.submit-button').addEventListener('click', async () => {
       	    	const id = dialog.querySelector('#manual-id').value.trim();
       	    	if (!id) {
           	    showError('Please enter a Device ID');
           	    return;
       	    	}

       	    	try {
           	    const submitButton = dialog.querySelector('.submit-button');
           	    submitButton.disabled = true;
           	    submitButton.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Starting pairing...';

           	    const pairResponse = await fetch(`/api/appletv/pair/${id}`);
           	    const pairData = await pairResponse.json();

           	    if (pairData.status === 'awaiting_pin') {
               	    	submitButton.disabled = false;
               	    	submitButton.innerHTML = 'Start Pairing';
               	    	dialog.remove();
               	    	setTimeout(() => showPinDialog(id), 100);
           	    } else {
               	    	throw new Error(pairData.message || 'Failed to start pairing');
           	    }
       	    	} catch (error) {
           	    const submitButton = dialog.querySelector('.submit-button');
           	    submitButton.disabled = false;
           	    submitButton.innerHTML = 'Start Pairing';
           	    showError(error.message);
       	    	}
   	    });

   	    dialog.querySelector('.cancel-button').addEventListener('click', () => {
       	    	dialog.remove();
   	    });
	}

        function showPinDialog(deviceId) {
            const dialog = document.createElement('div');
            dialog.className = 'trakt-confirm-dialog pin-input-dialog';
            dialog.innerHTML = `
                <div class="dialog-content">
                    <h3><i class="fa-brands fa-apple"></i> Enter PIN</h3>
                    <p>Enter the PIN shown on your Apple TV:</p>
                    <div class="pin-input">
                        <input type="text"
                           class="setting-input pin-code"
                           maxlength="4" placeholder="0000"
                           pattern="[0-9]*"
                           inputmode="numeric">
                    </div>
                    <div class="dialog-buttons">
                        <button class="cancel-button">Cancel</button>
                        <button class="submit-button" disabled>Submit PIN</button>
                    </div>
                </div>
            `;

            document.body.appendChild(dialog);

            const pinInput = dialog.querySelector('.pin-code');
            const submitButton = dialog.querySelector('.submit-button');

            setTimeout(() => pinInput.focus(), 100);

            pinInput.addEventListener('input', (e) => {
                e.target.value = e.target.value.replace(/[^0-9]/g, '');
                submitButton.disabled = e.target.value.length !== 4;
            });

            submitButton.addEventListener('click', async () => {
                const pin = pinInput.value;
                if (pin.length !== 4) {
                    showError('Please enter a 4-digit PIN');
                    return;
                }

                submitButton.disabled = true;
                submitButton.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Pairing...';

                try {
                    const response = await fetch(`/api/appletv/pin/${deviceId}`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCsrfToken() 
                        },
                        body: JSON.stringify({ pin })
                    });

                    const data = await response.json();
                    if (data.status === 'success') {
                        await handleSettingChange('clients.apple_tv.id', deviceId);
                        await handleSettingChange('clients.apple_tv.enabled', true);
                        showSuccess('Apple TV configured successfully');
                        dialog.remove();
                    } else if (data.status === 'awaiting_pin') {
                        pinInput.value = '';
                        pinInput.focus();
                        submitButton.disabled = true;
                        submitButton.innerHTML = 'Submit PIN';
                        showMessage('Please enter the new PIN shown on your Apple TV');
                    } else {
                        throw new Error(data.message || 'Pairing failed');
                    }
                } catch (error) {
                    showError(error.message);
                    submitButton.disabled = false;
                    submitButton.innerHTML = 'Submit PIN';
                    pinInput.value = '';
                    pinInput.focus();
                }
            });

            dialog.querySelector('.cancel-button').addEventListener('click', async () => {
                await fetch(`/api/appletv/cancel/${deviceId}`);
                dialog.remove();
            });

            pinInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter' && !submitButton.disabled) {
                    submitButton.click();
                }
            });

            pinInput.focus();
        }
    }

    function renderSmartTVSection(container) {
    	const wrapper = document.createElement('div');
    	wrapper.className = 'smart-tv-section';

    	const buttonContainer = document.createElement('div');
    	buttonContainer.className = 'tv-controls';

    	const addButton = document.createElement('button');
    	addButton.className = 'discover-button add-tv-button';
    	addButton.innerHTML = '<i class="fa-solid fa-plus"></i> Add TV';
    	addButton.addEventListener('click', () => showAddTVDialog());

    	const manageBlacklistButton = document.createElement('button');
    	manageBlacklistButton.className = 'discover-button manage-blacklist-button';
    	manageBlacklistButton.innerHTML = '<i class="fa-solid fa-ban"></i> Manage Blacklist';
    	manageBlacklistButton.addEventListener('click', showBlacklistDialog);

    	const tvs = getNestedValue(currentSettings, 'clients.tvs.instances') || {};
    	const envControlledTVs = Object.entries(tvs)
            .filter(([id, _]) => Boolean(getNestedValue(currentOverrides, `clients.tvs.instances.${id}`)));

    	if (envControlledTVs.length > 0) {
            const overrideIndicator = document.createElement('div');
            overrideIndicator.className = 'env-override';
            overrideIndicator.textContent = 'Some TVs are configured by environment variables';
            wrapper.appendChild(overrideIndicator);
    	}

    	buttonContainer.appendChild(addButton);
    	buttonContainer.appendChild(manageBlacklistButton);

    	const tvList = document.createElement('div');
    	tvList.className = 'tv-list';

    	refreshTVList(tvList);

    	wrapper.appendChild(buttonContainer);
    	wrapper.appendChild(tvList);
    	container.appendChild(wrapper);
    }

    function showBlacklistDialog() {
    	console.log("Opening blacklist dialog");
	console.log("Current settings:", currentSettings);
    	let blacklistedMacs = getNestedValue(currentSettings, 'clients.tvs.blacklist.mac_addresses');
    	console.log("Retrieved blacklisted MACs:", blacklistedMacs);

	if (typeof blacklistedMacs === 'string') {
            blacklistedMacs = [blacklistedMacs];
    	}

	blacklistedMacs = Array.isArray(blacklistedMacs) ? blacklistedMacs.filter(mac => mac) : [];
    	console.log("Filtered MACs:", blacklistedMacs);

    	const dialog = document.createElement('div');
    	dialog.className = 'trakt-confirm-dialog';

    	const envControlledMacs = Object.entries(currentSettings.clients.tvs.instances || {})
            .filter(([id, _]) => Boolean(getNestedValue(currentOverrides, `clients.tvs.instances.${id}`)))
            .map(([_, tv]) => tv.mac.toLowerCase());
    	console.log("ENV controlled MACs:", envControlledMacs);

    	const displayableMacs = blacklistedMacs.filter(mac =>
            !envControlledMacs.includes(mac.toLowerCase())
    	);
    	console.log("Displayable MACs:", displayableMacs);

    	dialog.innerHTML = `
            <div class="dialog-content">
            	<h3>Blacklisted Devices</h3>
            	<div class="blacklist-devices">
                    ${displayableMacs.length > 0
                    	? displayableMacs.map(mac => `
                            <div class="blacklist-item">
                            	<div class="blacklist-mac">${mac}</div>
                            	<button class="remove-blacklist" data-mac="${mac}">
                                    <i class="fas fa-trash"></i>
                            	</button>
                            </div>
                    	`).join('')
                    	: '<div class="no-blacklist">No devices blacklisted</div>'
                    }
            	</div>
            	<div class="dialog-buttons">
                    <button class="done-button">Done</button>
            	</div>
            </div>
    	`;

    	document.body.appendChild(dialog);

    	const dialogContent = dialog.querySelector('.dialog-content');
    	dialogContent.querySelectorAll('.remove-blacklist').forEach(button => {
            button.addEventListener('click', async () => {
            	const mac = button.dataset.mac;
            	console.log("Attempting to remove MAC:", mac);
            	try {
                    let currentBlacklist = getNestedValue(currentSettings, 'clients.tvs.blacklist.mac_addresses');
                    console.log("Current blacklist before removal:", currentBlacklist);
                    if (typeof currentBlacklist === 'string') {
                    	currentBlacklist = currentBlacklist.split(',').map(m => m.trim());
                    }
                    currentBlacklist = Array.isArray(currentBlacklist) ? currentBlacklist.filter(m => m) : [];

                    const updatedList = currentBlacklist.filter(m => m !== mac);
                    console.log("Updated blacklist after removal:", updatedList);
                    await handleSettingChange('clients.tvs.blacklist.mac_addresses', updatedList);

                    const blacklistDevices = dialogContent.querySelector('.blacklist-devices');
                    const itemToRemove = button.closest('.blacklist-item');

                    if (itemToRemove) {
                    	itemToRemove.remove();

                    	if (updatedList.length === 0) {
                            blacklistDevices.innerHTML = '<div class="no-blacklist">No devices blacklisted</div>';
                    	}
                    }

                    showSuccess('Device removed from blacklist');
            	} catch (error) {
                    console.error('Error removing from blacklist:', error);
                    showError('Failed to remove device from blacklist');
            	}
            });
    	});

    	const doneButton = dialog.querySelector('.done-button');
    	if (doneButton) {
            doneButton.addEventListener('click', () => {
            	dialog.remove();
            });
    	}

    	dialog.addEventListener('click', (e) => {
            if (e.target === dialog) {
            	dialog.remove();
            }
    	});
    }

    function showAddTVDialog() {
    	const dialog = document.createElement('div');
    	dialog.className = 'trakt-confirm-dialog';

    	dialog.innerHTML = `
            <div class="dialog-content">
            	<h3>Add Smart TV</h3>
            	<div class="tv-setup-form">
                    <div class="input-group">
                    	<label>TV Type</label>
                    	<select class="setting-input" id="tv-type">
                            <option value="webos">LG (WebOS)</option>
                            <option value="tizen">Samsung (Tizen)</option>
                            <option value="android">Sony (Android)</option>
                    	</select>
                    </div>

                    <div class="scan-section">
                    	<button class="discover-button scan-button">
                            <i class="fa-solid fa-magnifying-glass"></i> Scan Network
                    	</button>
                    	<div class="dialog-separator">
                            <span>or enter manually</span>
                    	</div>
                    </div>

                    <div class="manual-section">
                    	<div class="input-group">
                            <label>TV Name</label>
                            <input type="text" class="setting-input" id="tv-name"
                                   placeholder="e.g., Living Room TV">
                    	</div>
                    	<div class="input-group">
                            <label>IP Address</label>
                            <input type="text" class="setting-input" id="tv-ip"
                                   placeholder="192.168.1.100">
                    	</div>
                    	<div class="input-group">
                            <label>MAC Address</label>
                            <input type="text" class="setting-input" id="tv-mac"
                                   placeholder="00:00:00:00:00:00">
                    	</div>
                    </div>
            	</div>
            	<div class="dialog-buttons">
                    <button class="cancel-button">Cancel</button>
                    <button class="submit-button">Add TV</button>
            	</div>
            </div>
    	`;

    	document.body.appendChild(dialog);

    	const tvTypeSelect = dialog.querySelector('#tv-type');
    	const scanButton = dialog.querySelector('.scan-button');
    	const nameInput = dialog.querySelector('#tv-name');
    	const ipInput = dialog.querySelector('#tv-ip');
    	const macInput = dialog.querySelector('#tv-mac');

    	formatMacInput(macInput);

    	scanButton.addEventListener('click', async () => {
            try {
            	const tvType = tvTypeSelect.value;
            	scanButton.disabled = true;
            	scanButton.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Scanning...';

            	const response = await fetch(`/api/tv/scan/${tvType}`);
            	if (!response.ok) {
                    throw new Error('Scan failed');
            	}

            	const data = await response.json();
            	if (data.devices && data.devices.length > 0) {
                    dialog.remove();
                    showTVSelectionDialog(tvType, data.devices);
            	} else {
                    showMessage('No TVs found. You can enter details manually.');
            	}
            } catch (error) {
            	showError(error.message || 'Failed to scan for TVs');
            } finally {
            	scanButton.disabled = false;
            	scanButton.innerHTML = '<i class="fa-solid fa-magnifying-glass"></i> Scan Network';
            }
    	});

    	dialog.querySelector('.submit-button').addEventListener('click', async () => {
            const mac = macInput.value.trim().toLowerCase();
            const name = nameInput.value.trim();
            const ip = ipInput.value.trim();
            const type = tvTypeSelect.value;

            if (!name || !ip || !mac) {
            	showError('All fields are required');
            	return;
            }

            const envControlledMacs = Object.entries(currentSettings.clients.tvs.instances || {})
            	.filter(([id, _]) => Boolean(getNestedValue(currentOverrides, `clients.tvs.instances.${id}`)))
            	.map(([_, tv]) => tv.mac.toLowerCase());

            if (envControlledMacs.includes(mac)) {
            	showError('This TV is already configured via environment variables');
            	return;
            }

            await submitTVConfig({
            	name,
            	type,
            	ip,
            	mac
            }, dialog);
    	});

    	dialog.querySelector('.cancel-button').addEventListener('click', () => {
            dialog.remove();
    	});
    }

    function showTVSelectionDialog(tvType, devices) {
    	const dialog = document.createElement('div');
    	dialog.className = 'trakt-confirm-dialog';

    	const envControlledMacs = Object.entries(currentSettings.clients.tvs.instances || {})
            .filter(([id, _]) => Boolean(getNestedValue(currentOverrides, `clients.tvs.instances.${id}`)))
            .map(([_, tv]) => tv.mac.toLowerCase());

    	const availableDevices = devices.filter(device =>
            !envControlledMacs.includes(device.mac.toLowerCase())
    	);

    	const typeDisplay = {
            'webos': 'LG',
            'tizen': 'Samsung',
            'android': 'Sony'
    	}[tvType];

    	const implName = {
            'webos': 'WebOS',
            'tizen': 'Tizen',
            'android': 'Android'
    	}[tvType];

    	dialog.innerHTML = `
            <div class="dialog-content">
            	<h3>Select ${typeDisplay} TV</h3>
            	${availableDevices.length === 0 ? `
                    <div class="no-devices">
                    	<p>No configurable TVs found. This could be because:</p>
                    	<ul>
                            <li>No TVs were detected on the network</li>
                            <li>All detected TVs are already configured via environment variables</li>
                            <li>TVs are not powered on or not connected to the network</li>
                    	</ul>
                    </div>
            	` : `
                    <div class="found-devices">
                    	${availableDevices.map((device, index) => `
                            <div class="device-info-block">
                            	<div class="device-info-header">
                                    <div class="device-info">
                                    	<div class="device-name">${typeDisplay} TV ${index + 1}</div>
                                    	<div class="device-meta">IP: ${device.ip || ''}</div>
                                    	<div class="device-meta">MAC: ${device.mac || ''}</div>
                                    </div>
                                    <div class="device-actions">
                                    	<button class="select-button"
                                                data-ip="${device.ip || ''}"
                                            	data-mac="${device.mac || ''}"
                                            	data-type="${tvType}">
                                            Select
                                    	</button>
                                    	<button class="blacklist-button"
                                            	data-mac="${device.mac || ''}"
                                            	title="Blacklist this device">
                                            <i class="fa-solid fa-ban"></i> Not a TV
                                    	</button>
                                    </div>
                            	</div>
                            	${device.warning ? `
                                    <div class="device-warning">
                                    	<i class="fa-solid fa-triangle-exclamation"></i>
					${device.warning}
                                    </div>
                            	` : ''}
                            </div>
                    	`).join('')}
                    </div>
            	`}
            	<div class="dialog-footer">
                    <button class="cancel-button">Cancel</button>
                    <button class="manual-button">Enter Manually</button>
            	</div>
            </div>
    	`;

    	dialog.querySelectorAll('.select-button').forEach(button => {
            button.addEventListener('click', () => {
            	const deviceData = {
                    ip: button.dataset.ip,
                    mac: button.dataset.mac,
                    type: button.dataset.type
            	};
            	dialog.remove();
            	showNameInputDialog(tvType, deviceData);
            });
    	});

    	dialog.querySelectorAll('.blacklist-button').forEach(button => {
            button.addEventListener('click', async () => {
            	try {
                    let currentBlacklist = getNestedValue(currentSettings, 'clients.tvs.blacklist.mac_addresses') || [];
                    if (!Array.isArray(currentBlacklist)) {
                    	currentBlacklist = [];
                    }

                    const macToAdd = button.dataset.mac;
                    if (!currentBlacklist.includes(macToAdd)) {
                    	currentBlacklist.push(macToAdd);
                    	await handleSettingChange('clients.tvs.blacklist.mac_addresses', currentBlacklist);
                    }

                    button.closest('.device-info-block').remove();
                    showSuccess('Device added to blacklist');

                    if (dialog.querySelectorAll('.device-info-block').length === 0) {
                    	dialog.querySelector('.found-devices').innerHTML =
                            '<div class="no-devices">No TV devices found</div>';
                    }
            	} catch (error) {
                    console.error('Blacklist error:', error);
                    showError('Failed to blacklist device');
            	}
            });
    	});

    	dialog.querySelector('.cancel-button').addEventListener('click', () => {
            dialog.remove();
    	});

    	dialog.querySelector('.manual-button').addEventListener('click', () => {
            dialog.remove();
            showAddTVDialog();
    	});

    	dialog.addEventListener('click', (e) => {
            if (e.target === dialog) {
            	dialog.remove();
            }
    	});

    	document.body.appendChild(dialog);
    }

    function showNameInputDialog(tvType, deviceData) {
    	const dialog = document.createElement('div');
    	dialog.className = 'trakt-confirm-dialog';

    	dialog.innerHTML = `
            <div class="dialog-content">
            	<h3>Name Your TV</h3>
            	<div class="input-group">
                    <label>TV Name</label>
                    <input type="text" class="setting-input" id="tv-name"
                           placeholder="e.g., Living Room TV">
            	</div>
            	<div class="dialog-buttons">
                    <button class="cancel-button">Cancel</button>
                    <button class="submit-button">Add TV</button>
            	</div>
            </div>
        `;

        document.body.appendChild(dialog);

        dialog.querySelector('.submit-button').addEventListener('click', () => {
            const name = dialog.querySelector('#tv-name').value.trim();
            if (!name) {
            	showError('Please enter a name for the TV');
            	return;
            }

            submitTVConfig({
            	name: name,
            	type: tvType,
            	ip: deviceData.ip,
            	mac: deviceData.mac
            }, dialog);
    	});

    	dialog.querySelector('.cancel-button').addEventListener('click', () => {
            dialog.remove();
    	});
    }

    async function submitTVConfig(config, dialog) {
    	if (!config.name || !config.ip || !config.mac) {
            showError('All fields are required');
            return;
    	}

    	const tvs = getNestedValue(currentSettings, 'clients.tvs.instances') || {};
    	const isDuplicateMAC = Object.values(tvs).some(tv =>
            tv && tv.mac && tv.mac.toLowerCase() === config.mac.toLowerCase()
    	);

    	if (isDuplicateMAC) {
            showError('A TV with this MAC address is already configured');
            return;
    	}

    	try {
            const tvConfig = {
            	enabled: true,
            	type: config.type,
            	name: config.name,
            	ip: config.ip,
            	mac: config.mac
            };

            const key = config.name.toLowerCase().replace(/[^a-z0-9]/g, '_');
            await handleSettingChange(`clients.tvs.instances.${key}`, tvConfig);
            dialog.remove();
            showSuccess('TV added successfully');

            refreshTVList(document.querySelector('.tv-list'));
    	} catch (error) {
            showError(error.message);
    	}
    }

    function getDisplayType(type) {
    	const types = {
            'webos': 'LG (WebOS)',
            'tizen': 'Samsung (Tizen)',
            'android': 'Sony (Android)'
    	};
    	return types[type] || `Unknown (${type.toUpperCase()})`;
    }

    function refreshTVList(container) {
	console.log("Current overrides:", currentOverrides);
    	console.log("Current settings:", currentSettings);
    	const tvs = getNestedValue(currentSettings, 'clients.tvs.instances') || {};

    	if (Object.keys(tvs).length === 0) {
            container.innerHTML = '<div class="no-tvs">No Smart TVs configured</div>';
            return;
    	}

    	container.innerHTML = Object.entries(tvs)
            .filter(([_, tv]) => tv !== undefined && tv !== null && typeof tv === 'object')
            .map(([id, tv]) => {
		const name = tv.name || id.split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
            	const type = tv.type || 'unknown';
            	const ip = tv.ip || 'Not set';
            	const isEnabled = tv.enabled !== false; 

            	const isEnvControlled = Boolean(
                    getNestedValue(currentOverrides, `clients.tvs.instances.${id}`)
            	);

		return `
    		    <div class="tv-entry" data-id="${id}">
        		<div class="tv-header">
            		    <div class="tv-title-section">
                		<div class="tv-name">${name}</div>
                		${isEnvControlled ? `<div class="env-override">Set by environment variable</div>` : ''}
            		    </div>
            		    <div class="tv-type small">${getDisplayType(type)}</div>
        		</div>
        		<div class="tv-details">
            		    IP: ${ip}
        		</div>
        		<div class="tv-toggle-section">
            		    <label>Enabled</label>
            		    <div class="toggle ${isEnabled ? 'active' : ''} ${isEnvControlled ? 'disabled' : ''}"
                 		data-tv-id="${id}"
                 		role="switch"
                 		aria-checked="${isEnabled}">
            		    </div>
        		</div>
        		<div class="tv-actions">
            		    <button class="tv-action test" data-tv-id="${id}">
                		<i class="fa-solid fa-plug"></i> Test
            		    </button>
            		    ${!isEnvControlled ? `
                		<button class="tv-action edit" data-tv-id="${id}">
                    		    <i class="fa-solid fa-edit"></i> Edit
                		</button>
                		<button class="tv-action delete" data-tv-id="${id}">
                    		    <i class="fa-solid fa-trash"></i> Delete
                		</button>
            		    ` : ''}
        		</div>
    		    </div>
		`;
        }).join('');

    	container.querySelectorAll('.tv-toggle-section .toggle:not(.disabled)').forEach(toggle => {
            toggle.addEventListener('click', async () => {
            	const tvId = toggle.getAttribute('data-tv-id');
            	const tv = getNestedValue(currentSettings, `clients.tvs.instances.${tvId}`);
            	if (!tv) return;

            	const newEnabled = !tv.enabled;
            	const updatedTV = { ...tv, enabled: newEnabled };

            	try {
                    await handleSettingChange(`clients.tvs.instances.${tvId}`, updatedTV);
                    toggle.classList.toggle('active');
                    toggle.setAttribute('aria-checked', newEnabled);
            	} catch (error) {
                    showError('Failed to update TV status');
            	}
            });
    	});

    	container.querySelectorAll('.tv-action.test').forEach(button => {
            button.addEventListener('click', () => {
            	const tvId = button.getAttribute('data-tv-id');
            	testTVConnection(tvId);
            });
    	});

    	container.querySelectorAll('.tv-action.edit').forEach(button => {
            button.addEventListener('click', () => {
            	const tvId = button.getAttribute('data-tv-id');
            	editTV(tvId);
            });
    	});

    	container.querySelectorAll('.tv-action.delete').forEach(button => {
            button.addEventListener('click', () => {
            	const tvId = button.getAttribute('data-tv-id');
            	deleteTV(tvId);
            });
    	});
    }

    function getDisplayType(type, model) {
    	const types = {
            'webos': 'LG (WebOS)',
            'tizen': 'Samsung (Tizen)',
            'android': 'Sony (Android)'
    	};
        return types[type] || `${model.toUpperCase()} (${type.toUpperCase()})`;
    }

    async function testTVConnection(id) {
    	const button = document.querySelector(`[data-id="${id}"] .tv-action.test`);
    	const originalHtml = button.innerHTML;

    	try {
            button.disabled = true;
            button.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Testing...';

            const response = await fetch(`/api/tv/test/${id}`);
            const data = await response.json();

            if (response.ok && data.success) {
            	showSuccess('TV connection successful');
            } else {
            	throw new Error(data.error || 'Connection failed');
            }
    	} catch (error) {
            showError(error.message);
    	} finally {
            button.disabled = false;
            button.innerHTML = originalHtml;
    	}
    }

    function editTV(id) {
    	const tv = getNestedValue(currentSettings, `clients.tvs.instances.${id}`);
    	if (!tv) return;

    	const dialog = document.createElement('div');
    	dialog.className = 'trakt-confirm-dialog';

    	dialog.innerHTML = `
            <div class="dialog-content">
            	<h3>Edit ${tv.name}</h3>
                <div class="tv-setup-form">
                    <div class="input-group">
                    	<label>IP Address</label>
                    	<input type="text" class="setting-input" id="tv-ip" value="${tv.ip}">
                    </div>
                    <div class="input-group">
                    	<label>MAC Address</label>
                    	<input type="text" class="setting-input" id="tv-mac" value="${tv.mac}">
                    </div>
                </div>
                <div class="dialog-buttons">
                    <button class="cancel-button">Cancel</button>
                    <button class="submit-button">Save Changes</button>
            	</div>
            </div>
    	`;

    	document.body.appendChild(dialog);

    	formatMacInput(dialog.querySelector('#tv-mac'));

    	dialog.querySelector('.submit-button').addEventListener('click', async () => {
            const ip = dialog.querySelector('#tv-ip').value.trim();
            const mac = dialog.querySelector('#tv-mac').value.trim();

            if (!ip || !mac) {
            	showError('All fields are required');
            	return;
            }

            if (mac.toLowerCase() !== tv.mac.toLowerCase()) {
            	const tvs = getNestedValue(currentSettings, 'clients.tvs.instances') || {};
            	const isDuplicateMAC = Object.values(tvs).some(existingTv =>
                    existingTv &&
                    existingTv.mac &&
                    existingTv.mac.toLowerCase() === mac.toLowerCase()
            	);

            	if (isDuplicateMAC) {
                    showError('A TV with this MAC address is already configured');
                    return;
            	}
            }

            try {
            	const updatedTV = { ...tv, ip, mac };
            	await handleSettingChange(`clients.tvs.instances.${id}`, updatedTV);
            	dialog.remove();
            	showSuccess('TV updated successfully');
            	refreshTVList(document.querySelector('.tv-list'));
            } catch (error) {
            	showError(error.message);
            }
    	});

    	dialog.querySelector('.cancel-button').addEventListener('click', () => {
            dialog.remove();
    	});
    }

    function deleteTV(id) {
    	const tv = getNestedValue(currentSettings, `clients.tvs.instances.${id}`);
    	if (!tv) return;

    	const dialog = document.createElement('div');
    	dialog.className = 'trakt-confirm-dialog';

    	const name = tv.name || id;

    	dialog.innerHTML = `
            <div class="dialog-content">
            	<h3>Delete TV</h3>
            	<p>Are you sure you want to remove ${name}?</p>
            	<div class="dialog-buttons">
                    <button class="cancel-button">Cancel</button>
                    <button class="delete-button">Delete</button>
            	</div>
            </div>
    	`;

    	document.body.appendChild(dialog);

    	dialog.querySelector('.delete-button').addEventListener('click', async () => {
            try {
            	await handleSettingChange(`clients.tvs.instances.${id}`, null); 
            	dialog.remove();
            	showSuccess('TV removed successfully');
            	refreshTVList(document.querySelector('.tv-list'));
            } catch (error) {
            	showError(error.message);
            }
    	});

    	dialog.querySelector('.cancel-button').addEventListener('click', () => {
            dialog.remove();
    	});
    }

    function formatMacInput(input) {
    	input.addEventListener('input', (e) => {
            let value = e.target.value.replace(/[^0-9a-fA-F]/g, '');
            if (value.length > 12) value = value.slice(0, 12);
            const formatted = value.match(/.{1,2}/g)?.join(':') || value;
            input.value = formatted.toUpperCase();
    	});
    }

    tabs.addEventListener('click', (e) => {
        if (e.target.classList.contains('tab')) {
            document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
            e.target.classList.add('active');
            loadTabContent(e.target.dataset.tab);
        }
    });

    async function handleTraktToggleChange(newState) {
        console.log('Handling Trakt toggle change:', newState);

        if (traktStatus.env_controlled) {
            showError('Trakt setting is controlled by environment variables and cannot be changed here.');
            return;
        }

        try {
            const csrfToken = getCsrfToken();
            if (!csrfToken) {
                showError("CSRF Token missing. Please refresh the page.");
                return;
            }

            const response = await fetch('/trakt/settings', { 
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({ enabled: newState })
            });

            if (!response.ok) {
                let errorMessage = 'Failed to update Trakt setting';
                try {
                    const contentType = response.headers.get('content-type');
                    if (contentType && contentType.includes('application/json')) {
                        const errorData = await response.json();
                        errorMessage = errorData.message || errorData.error || JSON.stringify(errorData);
                    } else {
                        errorMessage = await response.text();
                    }
                } catch (parseError) {
                    console.error('Error parsing error response:', parseError);
                    errorMessage = `Server returned status ${response.status}, but failed to parse error response.`;
                }
                throw new Error(errorMessage);
            }

            const result = await response.json();
            if (result.status === 'success') {
                showSuccess(`Trakt integration ${newState ? 'enabled' : 'disabled'}`);
                traktStatus.enabled = newState;
            } else {
                 throw new Error(result.message || 'Failed to update Trakt setting');
            }

        } catch (error) {
            console.error('Error updating Trakt setting:', error);
            showError(error.message || 'Failed to update Trakt setting');
        }
    }

    async function initialize() {
    	try {
            const authResponse = await fetch('/api/auth/check');
            const authData = await authResponse.json();
            const isAuthenticated = authData.authenticated;
            const isAdmin = isAuthenticated && authData.is_admin;
            const serviceType = isAuthenticated ? authData.service_type : null; 
            const isServiceUser = serviceType && ['plex', 'jellyfin', 'emby'].includes(serviceType);

            window.isAuthenticated = isAuthenticated;
            window.isAdminUser = isAdmin;
            window.serviceType = serviceType;
            window.isServiceUser = isServiceUser;
        
            const response = await fetch('/api/settings');
            if (!response.ok) throw new Error('Failed to load settings');
            const data = await response.json();

            currentSettings = data.settings;
            currentOverrides = data.env_overrides;

            if (currentSettings && currentSettings.trakt) {
                traktStatus.enabled = currentSettings.trakt.enabled || false;
            }

            try {
                const traktStatusResponse = await fetch('/trakt/status');
                if (traktStatusResponse.ok) {
                    const statusData = await traktStatusResponse.json();
                    traktStatus.connected = statusData.connected;
                    traktStatus.env_controlled = statusData.env_controlled;
                    console.log('Fetched Trakt Status:', traktStatus);
                } else {
                    console.error('Failed to fetch Trakt status:', traktStatusResponse.statusText);
                }
            } catch (statusError) {
                console.error('Error fetching Trakt status:', statusError);
            }

            const tabsContainer = document.querySelector('.settings-tabs');
            if (!isAdmin && isServiceUser) {
                tabsContainer.querySelectorAll('.tab').forEach(tab => {
                    if (tab.dataset.tab !== 'integrations') {
                        tab.style.display = 'none';
                    }
                });
                const integrationsTab = tabsContainer.querySelector('[data-tab="integrations"]');
                if (integrationsTab) integrationsTab.click();
                else console.error("Integrations tab not found"); 
            } else if (!isAdmin) {
                tabsContainer.querySelectorAll('.tab').forEach(tab => {
                    if (!['features', 'clients', 'integrations'].includes(tab.dataset.tab)) {
                        tab.style.display = 'none';
                    }
                });
                const featuresTab = tabsContainer.querySelector('[data-tab="features"]');
                 if (featuresTab) featuresTab.click();
                 else console.error("Features tab not found"); 
            } else {
                const mediaTab = tabsContainer.querySelector('[data-tab="media"]');
                if (mediaTab) mediaTab.click();
                else { 
                    const firstTab = tabsContainer.querySelector('.tab');
                    if (firstTab) firstTab.click();
                }
            }

            if (isAdmin) {
            	const plexEnabled = currentSettings.plex?.enabled;
            	const jellyfinEnabled = currentSettings.jellyfin?.enabled;
            	const embyEnabled = currentSettings.emby?.enabled;

            	if (!plexEnabled && !jellyfinEnabled && !embyEnabled) {
                    const contentContainer = document.querySelector('.settings-content');
                    if (contentContainer) {
                    	const message = document.createElement('div');
                    	message.className = 'setup-message';
                    	message.innerHTML = `
                            <div class="setup-welcome">
                            	<h2>Welcome to Movie Roulette!</h2>
                            	<p>To get started, you'll need to configure at least one media server.</p>
                            	<p>Configure Plex, Jellyfin, Emby or any combination to start using Movie Roulette.</p>
                            </div>
                    	`;
                    	contentContainer.insertBefore(message, contentContainer.firstChild);

                        document.querySelector('[data-tab="media"]').click();
                    }
            	} else {
                    const enabledButUnconfigured = [];

                    if (currentSettings.plex?.enabled &&
                    	(!currentSettings.plex?.url || !currentSettings.plex?.token || !currentSettings.plex?.movie_libraries)) {
                    	enabledButUnconfigured.push('Plex');
                    }

                    if (currentSettings.jellyfin?.enabled &&
                    	(!currentSettings.jellyfin?.url || !currentSettings.jellyfin?.api_key || !currentSettings.jellyfin?.user_id)) {
                    	enabledButUnconfigured.push('Jellyfin');
                    }

                    if (currentSettings.emby?.enabled &&
                    	(!currentSettings.emby?.url || !currentSettings.emby?.api_key || !currentSettings.emby?.user_id)) {
                    	enabledButUnconfigured.push('Emby');
                    }

                    if (enabledButUnconfigured.length > 0) {
                    	const contentContainer = document.querySelector('.settings-content');
                    	if (contentContainer) {
                            const message = document.createElement('div');
                            message.className = 'setup-message warning';
                            message.innerHTML = `
                            	<div class="setup-welcome">
                                    <h2>Configuration Required</h2>
                                    <p>The following services are enabled but not fully configured:</p>
                                    <ul>
                                    	${enabledButUnconfigured.map(service => `<li>${service}</li>`).join('')}
                                    </ul>
                                    <p>Please complete the configuration to use Movie Roulette.</p>
                            	</div>
                            `;
                            contentContainer.insertBefore(message, contentContainer.firstChild);

                            document.querySelector('[data-tab="media"]').click();
                    	}
                    }
            	}
            }

            const backButton = document.querySelector('.back-button');
            if (backButton) {
            	backButton.addEventListener('click', async (e) => {
                    e.preventDefault(); 

                    try {
                    	const response = await fetch('/debug_service');
                    	const data = await response.json();

                    	if (data.service === 'plex' && !data.cache_file_exists) {
                            const loadingOverlay = document.createElement('div');
                            loadingOverlay.id = 'loading-overlay';
                            loadingOverlay.className = 'cache-building';
                            loadingOverlay.innerHTML = `
                            	<div id="loading-content" class="custom-loading">
                                    <h3>Building Movie Library</h3>
                                    <div class="loading-text">Loading movies: <span class="loading-count">0/0</span></div>
                                    <div id="loading-bar-container">
                                    	<div id="loading-progress"></div>
                                    </div>
                            	</div>
                            `;
                            document.body.appendChild(loadingOverlay);

                            const socket = io();

                            socket.on('loading_progress', (data) => {
                            	const progressBar = document.getElementById('loading-progress');
                            	const loadingCount = document.querySelector('.loading-count');

                            	if (progressBar && loadingCount) {
                                    progressBar.style.width = `${data.progress * 100}%`;
                                    loadingCount.textContent = `${data.current}/${data.total}`;
                            	}
                            });

                            socket.on('loading_complete', () => {
                            	window.location.href = '/';
                            });

                            await fetch('/start_loading');
                    	} else {
                            window.location.href = '/';
                    	}
                    } catch (error) {
                    	console.error('Error checking cache status:', error);
                    	window.location.href = '/';
                    }
            	});
            }

            if (window.innerWidth <= 640) {
            	const dropdown = document.querySelector('.dropdown');

            	if (dropdown) {
                    dropdown.addEventListener('click', function(e) {
                    	if (e.target.matches('.donate-button, .donate-button *')) {
                            e.preventDefault();
                            e.stopPropagation();
                            this.classList.toggle('active');
                    	}
                    });

                    document.addEventListener('click', function(e) {
                    	if (!dropdown.contains(e.target)) {
                            dropdown.classList.remove('active');
                    	}
                    });
            	}
            }
        
            const settingsContent = document.querySelector('.settings-content');
            if (settingsContent) {
                const observer = new MutationObserver(() => {
                    handleSectionVisibility(); 
                });

                observer.observe(settingsContent, {
                    childList: true, 
                    subtree: true    
                });

                setTimeout(handleSectionVisibility, 100); 
            } else {
                console.error("Settings content container not found for observer.");
            }

    	} catch (error) {
            console.error('Error loading settings:', error);
            showError('Failed to load settings');
    	}
    }

    function handleSectionVisibility() {
        const allSections = document.querySelectorAll('.settings-content .settings-section');
        const currentTab = document.querySelector('.tab.active')?.dataset.tab;

        if (window.isAdminUser) {
            allSections.forEach(section => {
                section.style.display = ''; 
            });
        } else if (window.isServiceUser) {
            if (currentTab === 'integrations') {
                allSections.forEach(section => {
                    const title = section.querySelector('h2')?.textContent.trim();
                    section.style.display = (title === 'Trakt') ? '' : 'none';
                });
            } else {
                 allSections.forEach(section => {
                    section.style.display = 'none';
                });
            }
        } else {
            if (currentTab === 'features') {
                allSections.forEach(section => {
                    const title = section.querySelector('h2')?.textContent.trim();
                    section.style.display = (title === 'General Features') ? '' : 'none';
                });
            } else if (currentTab === 'integrations') {
                 allSections.forEach(section => {
                    const title = section.querySelector('h2')?.textContent.trim();
                    section.style.display = (title === 'Trakt') ? '' : 'none';
                });
            } else if (currentTab === 'clients') {
                 allSections.forEach(section => {
                    section.style.display = '';
                });
            } else {
                 allSections.forEach(section => {
                    section.style.display = 'none';
                });
            }
        }
    }

    function loadTabContent(tabName) {
    	const section = sections[tabName];
        if (!section) return;

        contentContainer.innerHTML = '';

    	if (window.isAdminUser === false && ['media', 'auth'].includes(tabName)) {
            contentContainer.innerHTML = `
            	<div class="admin-required">
                    <i class="fa-solid fa-lock"></i>
                    <h3>Admin Access Required</h3>
                    <p>You need administrator privileges to view this section.</p>
            	</div>
            `;
            return;
    	}

    	if (section.sections) {
            section.sections.forEach(subSection => {
            	contentContainer.appendChild(renderSettingsSection(
                    subSection.title,
                    currentSettings,
                    currentOverrides,
                    subSection.fields
            	));
            });
    	} else {
            contentContainer.appendChild(renderSettingsSection(
            	section.title,
            	currentSettings,
            	currentOverrides,
            	section.fields
            ));
    	}
    
    	if (window.isAdminUser === false) {
            handleSectionVisibility();
    	}
    }

    function showPinDialog(pin) {
        const dialog = document.createElement('div');
        dialog.className = 'trakt-confirm-dialog';
        dialog.innerHTML = `
            <div class="dialog-content">
                <h3><i class="fa-brands fa-plex"></i> Enter PIN on Plex.tv</h3>
                <p>Enter this PIN on the Plex website:</p>
                <div class="pin-display">
                    <span class="pin-code">${pin}</span>
                </div>
                <p class="pin-instructions">A Plex.tv tab has been opened. Enter this PIN there to link Movie Roulette.</p>
                <div class="dialog-buttons">
                    <button class="cancel-button">Cancel</button>
                </div>
            </div>
        `;

        document.body.appendChild(dialog);

        dialog.querySelector('.cancel-button').addEventListener('click', () => {
            dialog.remove();
        });

        return dialog;
    }

    function renderPlexTokenConfig(container) {
        const wrapper = document.createElement('div');
        wrapper.className = 'plex-token-wrapper';

        const isEnvControlled = Boolean(
            getNestedValue(currentOverrides, 'plex.token')
        );

        if (isEnvControlled) {
            const overrideIndicator = document.createElement('div');
            overrideIndicator.className = 'env-override';
            overrideIndicator.textContent = 'Set by environment variable';
            wrapper.appendChild(overrideIndicator);
        } else {
            const inputGroup = document.createElement('div');
            inputGroup.className = 'input-group';

            const tokenInput = createInput(
                'password',
                getNestedValue(currentSettings, 'plex.token'),
                false,
                (value) => handleSettingChange('plex.token', value),
                'Enter your Plex token'
            );

            const getTokenButton = document.createElement('button');
            getTokenButton.className = 'discover-button';
            getTokenButton.innerHTML = '<i class="fa-solid fa-key"></i> Get Token';

            getTokenButton.addEventListener('click', async () => {
                try {
                    const plexUrl = getNestedValue(currentSettings, 'plex.url');
                    if (!plexUrl) {
                        showError('Please enter Plex URL first');
                        return;
                    }

                    getTokenButton.disabled = true;
                    getTokenButton.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Getting token...';

                    const response = await fetch('/api/plex/get_token', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCsrfToken() 
                        }
                    });

                    if (!response.ok) {
                        throw new Error('Failed to initiate Plex authentication');
                    }

                    const data = await response.json();

                    const authWindow = window.open(
                        data.auth_url,
                        'PlexAuth',
			'width=800,height=600,location=yes,status=yes,scrollbars=yes'
                    );

                    if (!authWindow) {
                        throw new Error('Popup was blocked. Please allow popups for this site.');
                    }

        	    const pinDialog = showPinDialog(data.pin);

		    let attempts = 0;
        	    const maxAttempts = 60;

                    const checkAuth = setInterval(async () => {
                        try {
			    if (attempts >= maxAttempts) {
				clearInterval(checkAuth);
                    		authWindow.close();
                    		throw new Error('Authentication timed out');
			    }

			    attempts++;

			    const statusResponse = await fetch(`/api/plex/check_auth/${data.client_id}`);
                            const statusData = await statusResponse.json();

			    console.log("Auth status check completed");

                            if (statusData.token) {
                                clearInterval(checkAuth);
                                authWindow.close();
                                await handleSettingChange('plex.token', statusData.token);
                                tokenInput.value = statusData.token;
                                showSuccess('Successfully got Plex token');
                            }
                        } catch (error) {
                            console.error('Auth check error:', error);
			    if (error.message !== 'Authentication timed out') {
                    		clearInterval(checkAuth);
                    		showError(error.message);
			    }
                        }
                    }, 2000);

                    const windowCheck = setInterval(() => {
                        if (authWindow.closed) {
                            clearInterval(checkAuth);
                            clearInterval(windowCheck);
			    pinDialog.remove();
                            getTokenButton.disabled = false;
                            getTokenButton.innerHTML = '<i class="fa-solid fa-key"></i> Get Token';
                        }
                    }, 1000);

                } catch (error) {
                    showError(error.message);
                } finally {
                    getTokenButton.disabled = false;
                    getTokenButton.innerHTML = '<i class="fa-solid fa-key"></i> Get Token';
                }
            });

            inputGroup.appendChild(tokenInput);
            wrapper.appendChild(inputGroup);
            wrapper.appendChild(getTokenButton);
        }

        container.appendChild(wrapper);
    }

    function renderPlexLibrariesConfig(container) {
        const wrapper = document.createElement('div');
        wrapper.className = 'plex-libraries-wrapper';

        const isEnvControlled = Boolean(
            getNestedValue(currentOverrides, 'plex.movie_libraries')
        );

        if (isEnvControlled) {
            const overrideIndicator = document.createElement('div');
            overrideIndicator.className = 'env-override';
            overrideIndicator.textContent = 'Set by environment variable';
            wrapper.appendChild(overrideIndicator);
        } else {
            const inputGroup = document.createElement('div');
            inputGroup.className = 'input-group';

            const librariesInput = createInput(
                'text',
                getNestedValue(currentSettings, 'plex.movie_libraries'),
                false,
                (value) => handleSettingChange('plex.movie_libraries', value),
                'Comma-separated library names'
            );

            const fetchButton = document.createElement('button');
            fetchButton.className = 'discover-button';
            fetchButton.innerHTML = '<i class="fa-solid fa-sync"></i> Fetch Libraries';

            fetchButton.addEventListener('click', async () => {
                try {
                    const plexUrl = getNestedValue(currentSettings, 'plex.url');
                    const plexToken = getNestedValue(currentSettings, 'plex.token');

                    if (!plexUrl || !plexToken) {
                        showError('Please configure Plex URL and token first');
                        return;
                    }

                    fetchButton.disabled = true;
                    fetchButton.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Fetching...';

                    const response = await fetch('/api/plex/libraries', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCsrfToken() 
                        },
                        body: JSON.stringify({
                            plex_url: plexUrl,
                            plex_token: plexToken
                        })
                    });

                    if (!response.ok) {
                        throw new Error('Failed to fetch libraries');
                    }

                    const data = await response.json();

                    showLibraryDialog(data.libraries, librariesInput);

                } catch (error) {
                    showError(error.message);
                } finally {
                    fetchButton.disabled = false;
                    fetchButton.innerHTML = '<i class="fa-solid fa-sync"></i> Fetch Libraries';
                }
            });

            inputGroup.appendChild(librariesInput);
            wrapper.appendChild(inputGroup);
            wrapper.appendChild(fetchButton);
        }

        container.appendChild(wrapper);
    }

    function showLibraryDialog(libraries, inputElement) {
        const dialog = document.createElement('div');
        dialog.className = 'trakt-confirm-dialog';

        const currentLibraries = inputElement.value.split(',').map(lib => lib.trim());

        dialog.innerHTML = `
            <div class="dialog-content">
                <h3>Select Movie Libraries</h3>
                <div class="library-select">
                    ${libraries.map(library => `
                        <label class="library-option">
                            <input type="checkbox" value="${library}"
                                ${currentLibraries.includes(library) ? 'checked' : ''}>
                            <span>${library}</span>
                        </label>
                    `).join('')}
                </div>
                <div class="dialog-buttons">
                    <button class="cancel-button">Cancel</button>
                    <button class="submit-button">Save Selection</button>
                </div>
            </div>
        `;

        document.body.appendChild(dialog);

        dialog.querySelector('.submit-button').addEventListener('click', async () => {
            const selectedLibraries = Array.from(dialog.querySelectorAll('input[type="checkbox"]:checked'))
                .map(cb => cb.value);

            await handleSettingChange('plex.movie_libraries', selectedLibraries.join(','));
            inputElement.value = selectedLibraries.join(',');
            dialog.remove();
        });

        dialog.querySelector('.cancel-button').addEventListener('click', () => {
            dialog.remove();
        });
    }

    function renderJellyfinAuthConfig(container) {
        const wrapper = document.createElement('div');
        wrapper.className = 'jellyfin-auth-wrapper';

        const isEnvControlled = Boolean(
            getNestedValue(currentOverrides, 'jellyfin.api_key') ||
            getNestedValue(currentOverrides, 'jellyfin.user_id')
        );

        if (isEnvControlled) {
            const overrideIndicator = document.createElement('div');
            overrideIndicator.className = 'env-override';
            overrideIndicator.textContent = 'Set by environment variable';
            wrapper.appendChild(overrideIndicator);
        } else {
            const manualGroup = document.createElement('div');
            manualGroup.className = 'input-group';

            const apiKeyInput = createInput(
                'password',
                getNestedValue(currentSettings, 'jellyfin.api_key'),
                false,
                (value) => handleSettingChange('jellyfin.api_key', value),
                'API Key'
            );

            const userIdInput = createInput(
                'text',
                getNestedValue(currentSettings, 'jellyfin.user_id'),
                false,
                (value) => handleSettingChange('jellyfin.user_id', value),
                'User ID'
            );

            manualGroup.appendChild(createLabel('API Key (manual entry)'));
            manualGroup.appendChild(apiKeyInput);
            manualGroup.appendChild(createLabel('User ID (manual entry)'));
            manualGroup.appendChild(userIdInput);

            const separator = document.createElement('div');
            separator.className = 'dialog-separator';
            separator.innerHTML = '<span>or get automatically</span>';

            const autoGroup = document.createElement('div');
            autoGroup.className = 'input-group';

            const usernameInput = createInput(
                'text',
                '',
                false,
                null,
                'Jellyfin username'
            );
            const passwordInput = createInput(
                'password',
                '',
                false,
                null,
                'Jellyfin password'
            );

            const loginButton = document.createElement('button');
            loginButton.className = 'discover-button';
            loginButton.innerHTML = '<i class="fa-solid fa-key"></i> Get API Key & User ID';

            loginButton.addEventListener('click', async () => {
                try {
                    const jellyfinUrl = getNestedValue(currentSettings, 'jellyfin.url');
                    if (!jellyfinUrl) {
                        showError('Please enter Jellyfin URL first');
                        return;
                    }

                    const username = usernameInput.value;
                    const password = passwordInput.value;

                    if (!username || !password) {
                        showError('Please enter both username and password');
                        return;
                    }

                    loginButton.disabled = true;
                    loginButton.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Authenticating...';

                    const response = await fetch('/api/jellyfin/auth', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCsrfToken() 
                        },
                        body: JSON.stringify({
                            server_url: jellyfinUrl,
                            username: username,
                            password: password
                        })
                    });

                    const data = await response.json();

                    if (!response.ok) {
                        throw new Error(data.error || 'Failed to authenticate');
                    }

                    apiKeyInput.value = data.api_key;
                    userIdInput.value = data.user_id;
                    await handleSettingChange('jellyfin.api_key', data.api_key);
                    await handleSettingChange('jellyfin.user_id', data.user_id);

                    usernameInput.value = '';
                    passwordInput.value = '';

                    showSuccess('Successfully retrieved Jellyfin credentials');

                } catch (error) {
                    showError(error.message);
                } finally {
                    loginButton.disabled = false;
                    loginButton.innerHTML = '<i class="fa-solid fa-key"></i> Get API Key & User ID';
                }
            });

            autoGroup.appendChild(createLabel('Username (for automatic setup)'));
            autoGroup.appendChild(usernameInput);
            autoGroup.appendChild(createLabel('Password (for automatic setup)'));
            autoGroup.appendChild(passwordInput);
            autoGroup.appendChild(loginButton);

            wrapper.appendChild(manualGroup);
            wrapper.appendChild(separator);
            wrapper.appendChild(autoGroup);
        }

        container.appendChild(wrapper);
    }

    function renderEmbyAuthConfig(container) {
    	const wrapper = document.createElement('div');
    	wrapper.className = 'emby-auth-wrapper';

    	const isEnvControlled = Boolean(
            getNestedValue(currentOverrides, 'emby.api_key') ||
            getNestedValue(currentOverrides, 'emby.user_id')
    	);

    	if (isEnvControlled) {
            const overrideIndicator = document.createElement('div');
            overrideIndicator.className = 'env-override';
            overrideIndicator.textContent = 'Set by environment variable';
            wrapper.appendChild(overrideIndicator);
    	} else {
            const manualGroup = document.createElement('div');
            manualGroup.className = 'input-group';

            const apiKeyInput = createInput(
            	'password',
            	getNestedValue(currentSettings, 'emby.api_key'),
            	false,
            	(value) => handleSettingChange('emby.api_key', value),
            	'API Key'
            );

            const userIdInput = createInput(
            	'text',
            	getNestedValue(currentSettings, 'emby.user_id'),
            	false,
            	(value) => handleSettingChange('emby.user_id', value),
            	'User ID'
            );

            manualGroup.appendChild(createLabel('API Key (manual entry)'));
            manualGroup.appendChild(apiKeyInput);
            manualGroup.appendChild(createLabel('User ID (manual entry)'));
            manualGroup.appendChild(userIdInput);

            const separator = document.createElement('div');
            separator.className = 'dialog-separator';
            separator.innerHTML = '<span>or login with</span>';

            const authGroup = document.createElement('div');
            authGroup.className = 'auth-buttons-group';

            const connectButton = document.createElement('button');
            connectButton.className = 'discover-button';
            connectButton.innerHTML = '<i class="fa-solid fa-link"></i> Emby Connect';
            connectButton.addEventListener('click', () => showEmbyConnectDialog()); 

            const localButton = document.createElement('button');
            localButton.className = 'discover-button';
            localButton.innerHTML = '<i class="fa-solid fa-user"></i> Local Login'; 
            localButton.addEventListener('click', () => showEmbyLocalLoginDialog()); 

            authGroup.appendChild(connectButton); 
            authGroup.appendChild(localButton);

            wrapper.appendChild(manualGroup);
            wrapper.appendChild(separator);
            wrapper.appendChild(authGroup);
   	}

    	container.appendChild(wrapper);
    }

    function showEmbyServerSelectionDialog(servers, connectUserId) {
    	const dialog = document.createElement('div');
    	dialog.className = 'trakt-confirm-dialog';

    	dialog.innerHTML = `
            <div class="dialog-content">
            	<h3><i class="fa-solid fa-server"></i> Select Connection Type</h3>
            	<div class="server-list">
                    ${servers.map(server => `
                    	<div class="server-group">
                            <div class="server-name">${server.name}</div>
                            <div class="connection-options">
                            	<button class="server-option" data-server='${JSON.stringify({
                                    ...server,
                                    url: server.local_url,
                                    access_key: server.access_key,
                                    name: server.name,
                                    id: server.id
                            	})}'>
                                     <i class="fa-solid fa-network-wired"></i>
                                    <div class="server-details">
                                    	<div class="connection-type">Local Network</div>
                                    	<div class="server-url">${server.local_url}</div>
                                    </div>
                            	</button>
                            	<button class="server-option" data-server='${JSON.stringify({
                               	    ...server,
                                    url: server.remote_url, // Use remote_url here
                                    access_key: server.access_key,
                                    name: server.name,
                                    id: server.id
                            	})}'>
                               	    <i class="fa-solid fa-globe"></i>
                                    <div class="server-details">
                                        <div class="connection-type">Remote Access (HTTPS)</div>
                                        <div class="server-url">${server.remote_url || 'N/A'}</div>
                                    </div>
                                </button>
                            </div>
                        </div>
                    `).join('')}
                </div>
                <div class="dialog-buttons">
                    <button class="cancel-button">Cancel</button>
                </div>
            </div>
        `;

        document.body.appendChild(dialog);

        dialog.querySelectorAll('.server-option').forEach(button => {
            button.addEventListener('click', async () => {
                const server = JSON.parse(button.dataset.server);
                const originalHtml = button.innerHTML; 
                try {
                    button.disabled = true;
                    button.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Connecting...';

                    const response = await fetch('/api/emby/connect/select_server', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCsrfToken() 
                        },
                        body: JSON.stringify({
                            server: server, 
                            connect_user_id: connectUserId 
                        })
                    });

                    const data = await response.json();
                    if (!response.ok || data.status !== 'success') { 
                        throw new Error(data.message || 'Failed to connect to server');
                    }

                    updateEmbyFields(data.server_url, data.api_key, data.user_id);
                    showSuccess('Successfully connected to Emby server');
                    dialog.remove();

                } catch (error) {
                    showError(error.message);
                    button.disabled = false;
                    button.innerHTML = originalHtml;
                }
            });
        });

        dialog.querySelector('.cancel-button').addEventListener('click', () => {
            dialog.remove();
        });
    }

    function showEmbyConnectDialog() {
    	const dialog = document.createElement('div');
    	dialog.className = 'trakt-confirm-dialog';

    	dialog.innerHTML = `
            <div class="dialog-content">
            	<h3><i class="fa-solid fa-link"></i> Connect with Emby Connect</h3>
            	<form id="emby-connect-form">
                    <div class="input-group">
                    	<label>Emby Connect Email</label>
                    	<input type="email" class="setting-input" id="emby-username" required>
                    </div>
                    <div class="input-group">
                    	<label>Password</label>
                    	<input type="password" class="setting-input" id="emby-password" required>
                    </div>
                    <div class="dialog-buttons">
                    	<button type="button" class="cancel-button">Cancel</button>
                    	<button type="submit" class="submit-button">Connect</button>
                    </div>
            	</form>
            </div>
    	`;

    	document.body.appendChild(dialog);

    	const form = dialog.querySelector('#emby-connect-form');
    	const submitButton = form.querySelector('.submit-button');

    	form.addEventListener('submit', async (e) => {
            e.preventDefault();
            submitButton.disabled = true;
            submitButton.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Connecting...';

            try {
            	const response = await fetch('/api/emby/connect/auth', {
                    method: 'POST',
                    headers: {
                    	'Content-Type': 'application/json',
                        'X-CSRFToken': getCsrfToken() 
                    },
                    body: JSON.stringify({
                    	username: form.querySelector('#emby-username').value,
                    	password: form.querySelector('#emby-password').value
                    })
            	});

            	const data = await response.json();
            	if (!response.ok) {
                    throw new Error(data.error || 'Failed to authenticate with Emby Connect');
            	}

            	if (data.status === 'servers_available') {
                    dialog.remove();
                    showEmbyServerSelectionDialog(data.servers, data.connect_user_id);
            	} else {
                    throw new Error('Unexpected response from server');
            	}
            } catch (error) {
            	showError(error.message);
            	submitButton.disabled = false;
            	submitButton.innerHTML = 'Connect';
            }
    	});

    	dialog.querySelector('.cancel-button').addEventListener('click', () => {
            dialog.remove();
    	});
    }

    function showEmbyLocalLoginDialog() {
    	const dialog = document.createElement('div');
    	dialog.className = 'trakt-confirm-dialog';

    	dialog.innerHTML = `
            <div class="dialog-content">
            	<h3><i class="fa-solid fa-user"></i> Local Login</h3>
            	<form id="emby-local-form">
                    <div class="input-group">
                    	<label>Server URL</label>
                    	<input type="text" class="setting-input" id="emby-server-url"
                               value="${getNestedValue(currentSettings, 'emby.url') || ''}"
                               placeholder="http://your-server:8096" required>
                    </div>
                    <div class="input-group">
                    	<label>Username</label>
                    	<input type="text" class="setting-input" id="emby-local-username" required>
                    </div>
                    <div class="input-group">
                    	<label>Password</label>
                    	<input type="password" class="setting-input" id="emby-local-password" required>
                    </div>
                    <div class="dialog-buttons">
                    	<button type="button" class="cancel-button">Cancel</button>
                    	<button type="submit" class="submit-button">Login</button>
                    </div>
            	</form>
            </div>
    	`;

    	document.body.appendChild(dialog);

    	const form = dialog.querySelector('#emby-local-form');
    	const submitButton = form.querySelector('.submit-button');

    	form.addEventListener('submit', async (e) => {
    	       e.preventDefault();
    	       submitButton.disabled = true;
    	       submitButton.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Logging in...';

    	       const serverUrl = form.querySelector('#emby-server-url').value;
    	       const username = form.querySelector('#emby-local-username').value; 
    	       const password = form.querySelector('#emby-local-password').value; 

    	       try {
    	           console.log(">>> DEBUG: Attempting fetch to /api/settings/emby/authenticate"); 
    	       	const response = await fetch('/api/settings/emby/authenticate', { 
            	       method: 'POST',
            	       headers: {
            	       	'Content-Type': 'application/json',
            	           'X-CSRFToken': getCsrfToken() 
            	       },
            	       body: JSON.stringify({
            	       	url: serverUrl, 
            	       	username: form.querySelector('#emby-local-username').value,
            	       	password: form.querySelector('#emby-local-password').value
            	       })
            	});

            	const data = await response.json();
            	if (!response.ok || !data.success) { 
            	       throw new Error(data.message || 'Failed to authenticate');
            	}

            	updateEmbyFields(serverUrl, data.api_key, data.user_id);
            	showSuccess('Successfully logged in to Emby');
            	dialog.remove();

            } catch (error) {
            	showError(error.message);
            	submitButton.disabled = false;
            	submitButton.innerHTML = 'Login';
            }
    	});

    	dialog.querySelector('.cancel-button').addEventListener('click', () => {
            dialog.remove();
    	});
    }

    function getConnectionOptions(server) {
    	const options = [];

    	if (server.LocalAddress) {
            options.push({
            	type: 'local',
            	name: 'Local Network',
            	url: server.LocalAddress,
            	description: 'Best performance on your home network'
            });
    	}

    	if (server.ConnectAddress) {
            options.push({
            	type: 'connect',
            	name: 'Emby Connect',
            	url: server.ConnectAddress,
            	description: 'Recommended for most users'
            });
    	}

    	const remoteUrl = server.ExternalDomain || server.RemoteAddress;
    	if (remoteUrl) {
            const isDomain = /^[a-zA-Z0-9][a-zA-Z0-9-]{1,61}[a-zA-Z0-9]\.[a-zA-Z]{2,}/.test(remoteUrl);
            options.push({
            	type: 'remote',
            	name: 'Remote Access',
            	url: remoteUrl,
            	description: isDomain ?
                    'Custom domain access' :
                    'Direct IP access (requires static IP)',
            	warning: !isDomain ?
                    'Warning: IP-based access may be unreliable with dynamic IPs' :
                    null
            });
    	}

    	return options;
    }

    function updateEmbyFields(url, apiKey, userId) {
    	Promise.all([
            handleSettingChange('emby.url', url),
            handleSettingChange('emby.api_key', apiKey),
            handleSettingChange('emby.user_id', userId)
    	]).then(() => {
            setNestedValue(currentSettings, 'emby.url', url);
            setNestedValue(currentSettings, 'emby.api_key', apiKey);
            setNestedValue(currentSettings, 'emby.user_id', userId);

            const currentTab = document.querySelector('.tab.active');
            if (currentTab) {
            	loadTabContent(currentTab.dataset.tab);
            }
    	});
    }

    function createLabel(text) {
        const label = document.createElement('label');
        label.textContent = text;
        return label;
    }

    function renderPlexUserSelector(container) {
        const wrapper = document.createElement('div');
        wrapper.className = 'user-selector-wrapper';

        const isEnvControlled = Boolean(
            getNestedValue(currentOverrides, 'features.poster_users.plex')
        );

        if (isEnvControlled) {
            const overrideIndicator = document.createElement('div');
            overrideIndicator.className = 'env-override';
            overrideIndicator.textContent = 'Set by environment variable';
            wrapper.appendChild(overrideIndicator);
        } else {
            const inputGroup = document.createElement('div');
            inputGroup.className = 'input-group';

            const manualInput = createInput(
                'text',
                getNestedValue(currentSettings, 'features.poster_users.plex'),
                false,
                (value) => handleSettingChange('features.poster_users.plex', value),
                'Comma-separated usernames'
            );
            inputGroup.appendChild(manualInput);

            const fetchButton = document.createElement('button');
            fetchButton.className = 'discover-button';
            fetchButton.innerHTML = '<i class="fa-solid fa-users"></i> Fetch Users';

            fetchButton.addEventListener('click', async () => {
                const csrfToken = getCsrfToken(); 
                if (!csrfToken) {
                    showError("CSRF Token missing. Please refresh the page.");
                    return; 
                }
                try {
                    const plexUrl = getNestedValue(currentSettings, 'plex.url');
                    const plexToken = getNestedValue(currentSettings, 'plex.token');

                    if (!plexUrl || !plexToken) {
                        showError('Please configure Plex URL and token first');
                        return;
                    }

                    fetchButton.disabled = true;
                    fetchButton.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Fetching...';

                    const response = await fetch('/api/plex/users', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': csrfToken 
                        },
                        body: JSON.stringify({
                            plex_url: plexUrl,
                            plex_token: plexToken,
                            csrf_token: csrfToken 
                        })
                    });

                    if (!response.ok) {
                        throw new Error('Failed to fetch users');
                    }

                    const data = await response.json();
                    showUserSelectionDialog(data.users, 'plex', manualInput);

                } catch (error) {
                    showError(error.message);
                } finally {
                    fetchButton.disabled = false;
                    fetchButton.innerHTML = '<i class="fa-solid fa-users"></i> Fetch Users';
                }
            });

            wrapper.appendChild(inputGroup);
            wrapper.appendChild(fetchButton);
        }

        container.appendChild(wrapper);
    }

    function renderJellyfinUserSelector(container) {
        const wrapper = document.createElement('div');
        wrapper.className = 'user-selector-wrapper';

        const isEnvControlled = Boolean(
            getNestedValue(currentOverrides, 'features.poster_users.jellyfin')
        );

        if (isEnvControlled) {
            const overrideIndicator = document.createElement('div');
            overrideIndicator.className = 'env-override';
            overrideIndicator.textContent = 'Set by environment variable';
            wrapper.appendChild(overrideIndicator);
        } else {
            const inputGroup = document.createElement('div');
            inputGroup.className = 'input-group';

            const manualInput = createInput(
                'text',
                getNestedValue(currentSettings, 'features.poster_users.jellyfin'),
                false,
                (value) => handleSettingChange('features.poster_users.jellyfin', value),
                'Comma-separated usernames'
            );
            inputGroup.appendChild(manualInput);

            const fetchButton = document.createElement('button');
            fetchButton.className = 'discover-button';
            fetchButton.innerHTML = '<i class="fa-solid fa-users"></i> Fetch Users';

            fetchButton.addEventListener('click', async () => {
                try {
                    const jellyfinUrl = getNestedValue(currentSettings, 'jellyfin.url');
                    const jellyfinApiKey = getNestedValue(currentSettings, 'jellyfin.api_key');

                    if (!jellyfinUrl || !jellyfinApiKey) {
                        showError('Please configure Jellyfin URL and API key first');
                        return;
                    }

                    fetchButton.disabled = true;
                    fetchButton.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Fetching...';

                    const response = await fetch('/api/jellyfin/users', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCsrfToken() 
                        },
                        body: JSON.stringify({
                            jellyfin_url: jellyfinUrl,
                            api_key: jellyfinApiKey
                        })
                    });

                    if (!response.ok) {
                        throw new Error('Failed to fetch users');
                    }

                    const data = await response.json();
                    showUserSelectionDialog(data.users, 'jellyfin', manualInput);

                } catch (error) {
                    showError(error.message);
                } finally {
                    fetchButton.disabled = false;
                    fetchButton.innerHTML = '<i class="fa-solid fa-users"></i> Fetch Users';
                }
            });

            wrapper.appendChild(inputGroup);
            wrapper.appendChild(fetchButton);
        }

        container.appendChild(wrapper);
    }

    function renderEmbyUserSelector(container) {
    	const wrapper = document.createElement('div');
    	wrapper.className = 'user-selector-wrapper';

    	const isEnvControlled = Boolean(
            getNestedValue(currentOverrides, 'features.poster_users.emby')
    	);

    	if (isEnvControlled) {
            const overrideIndicator = document.createElement('div');
            overrideIndicator.className = 'env-override';
            overrideIndicator.textContent = 'Set by environment variable';
            wrapper.appendChild(overrideIndicator);
    	} else {
            const inputGroup = document.createElement('div');
            inputGroup.className = 'input-group';

            const manualInput = createInput(
            	'text',
            	getNestedValue(currentSettings, 'features.poster_users.emby'),
            	false,
            	(value) => handleSettingChange('features.poster_users.emby', value),
            	'Comma-separated usernames'
            );
            inputGroup.appendChild(manualInput);

            const fetchButton = document.createElement('button');
            fetchButton.className = 'discover-button';
            fetchButton.innerHTML = '<i class="fa-solid fa-users"></i> Fetch Users';

            fetchButton.addEventListener('click', async () => {
            	try {
                    const embyUrl = getNestedValue(currentSettings, 'emby.url');
                    const embyApiKey = getNestedValue(currentSettings, 'emby.api_key');

                    if (!embyUrl || !embyApiKey) {
                    	showError('Please configure Emby URL and API key first');
                    	return;
                    }

                    fetchButton.disabled = true;
                    fetchButton.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Fetching...';

                    const response = await fetch('/api/emby/users', {
                    	method: 'POST',
                    	headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': getCsrfToken() 
                    	},
                        body: JSON.stringify({
                       	    emby_url: embyUrl,
                            api_key: embyApiKey
                    	})
                    });

                    if (!response.ok) {
                    	throw new Error('Failed to fetch users');
                    }

                    const data = await response.json();
                    showUserSelectionDialog(data.users, 'emby', manualInput);

            	} catch (error) {
                    showError(error.message);
            	} finally {
                    fetchButton.disabled = false;
                    fetchButton.innerHTML = '<i class="fa-solid fa-users"></i> Fetch Users';
            	}
            });

            wrapper.appendChild(inputGroup);
            wrapper.appendChild(fetchButton);
    	}

        container.appendChild(wrapper);
    }

    async function showUserSelectionDialog(users, service, inputElement) {
        if (!Array.isArray(users)) {
             console.error("showUserSelectionDialog called with invalid users data:", users);
             showError("Failed to display user selection dialog: Invalid user data.");
             return;
        }

    	const dialog = document.createElement('div');
    	dialog.className = 'trakt-confirm-dialog';

    	const currentUsers = inputElement.value.split(',').map(u => u.trim());

    	dialog.innerHTML = `
            <div class="dialog-content">
            	<h3><i class="fa-solid fa-users"></i> Select ${service.charAt(0).toUpperCase() + service.slice(1)} Users</h3>
            	<div class="user-select">
                    ${users.map(user => {
                        const username = user && user.username ? user.username : 'Invalid User';
                        const isChecked = currentUsers.includes(username);
                        return `
                            <label class="user-option">
                                <input type="checkbox" value="${username}" ${isChecked ? 'checked' : ''}>
                                <span>${username}</span>
                            </label>
                        `;
                    }).join('')}
            	</div>
            	<div class="dialog-buttons">
                    <button class="cancel-button">Cancel</button>
                    <button class="submit-button">Save Selection</button>
            	</div>
            </div>
    	`;

    	document.body.appendChild(dialog);

    	dialog.querySelector('.submit-button').addEventListener('click', async () => {
            const selectedUsers = Array.from(dialog.querySelectorAll('input[type="checkbox"]:checked'))
            	.map(cb => cb.value);

            await handleSettingChange(`features.poster_users.${service}`, selectedUsers.join(','));
            inputElement.value = selectedUsers.join(',');
            dialog.remove();
    	});

    	dialog.querySelector('.cancel-button').addEventListener('click', () => {
            dialog.remove();
    	});
    }

    function renderTimezoneFieldWithButton(container) {
    	const wrapper = document.createElement('div');
    	wrapper.className = 'timezone-field-wrapper';

    	const isEnvControlled = Boolean(
            getNestedValue(currentOverrides, 'features.timezone')
    	);

    	if (isEnvControlled) {
            const overrideIndicator = document.createElement('div');
            overrideIndicator.className = 'env-override';
            overrideIndicator.textContent = 'Set by environment variable';
            wrapper.appendChild(overrideIndicator);
    	} else {
            const inputGroup = document.createElement('div');
            inputGroup.className = 'input-group';

            const timezoneInput = createInput(
                'text',
                getNestedValue(currentSettings, 'features.timezone'),
                false,
                (value) => handleSettingChange('features.timezone', value),
                'Enter timezone (e.g., Europe/Berlin)'
            );

            inputGroup.appendChild(timezoneInput);

            const searchButton = document.createElement('button');
            searchButton.className = 'discover-button';
            searchButton.innerHTML = '<i class="fa-solid fa-search"></i> Search Timezone';

            searchButton.addEventListener('click', () => {
            	showTimezoneSelectionDialog(timezoneInput);
            });

            wrapper.appendChild(inputGroup);
            wrapper.appendChild(searchButton);
        }

        container.appendChild(wrapper);
    }

    function showTimezoneSelectionDialog(inputElement) {
    	const dialog = document.createElement('div');
    	dialog.className = 'trakt-confirm-dialog'; 

    	const timezones = Intl.supportedValuesOf('timeZone');

    	dialog.innerHTML = `
            <div class="dialog-content">
                <h3><i class="fa-solid fa-globe"></i> Select Timezone</h3>
                <div class="timezone-dialog">
                    <input type="text" class="setting-input timezone-search" placeholder="Search timezones...">
                    <div class="timezone-list">
                        <!-- Timezone options will be inserted here -->
                    </div>
                </div>
                <div class="dialog-buttons">
                    <button class="cancel-button">Cancel</button>
                </div>
            </div>
        `;

    	document.body.appendChild(dialog);

    	const searchInput = dialog.querySelector('.timezone-search');
    	const timezoneList = dialog.querySelector('.timezone-list');

    	function renderTimezones(filter = '') {
            timezoneList.innerHTML = ''; 
            const filteredTimezones = timezones.filter(tz =>
            	tz.toLowerCase().includes(filter.toLowerCase())
            );

            const currentValue = inputElement.value;

            filteredTimezones.forEach(tz => {
            	const option = document.createElement('div');
            	option.className = 'timezone-option';
            	if (tz === currentValue) {
                    option.classList.add('selected');
            	}
            	option.textContent = tz;
            	option.addEventListener('click', () => {
                    inputElement.value = tz;
                    inputElement.dispatchEvent(new Event('input'));
                    handleSettingChange('features.timezone', tz);
                    dialog.remove();
            	});
                timezoneList.appendChild(option);
            });
        }

        renderTimezones();

        searchInput.addEventListener('input', (e) => {
            renderTimezones(e.target.value);
    	});

    	dialog.querySelector('.cancel-button').addEventListener('click', () => {
            dialog.remove();
        });
    }

    function renderPreferredUserSelector(container) {
    	const wrapper = document.createElement('div');
    	wrapper.className = 'preferred-user-wrapper';

    	const isPreferredMode = getNestedValue(currentSettings, 'features.poster_display.mode') === 'preferred_user';

    	if (!isPreferredMode) {
            const notice = document.createElement('div');
            notice.className = 'setting-description';
            notice.textContent = 'Enable "Preferred User" mode to select a preferred user.';
            wrapper.appendChild(notice);
            container.appendChild(wrapper);
            return;
    	}

    	const isEnvControlled = Boolean(
      	getNestedValue(currentOverrides, 'features.poster_display.preferred_user')
    	);

    	if (isEnvControlled) {
            const overrideIndicator = document.createElement('div');
            overrideIndicator.className = 'env-override';
            overrideIndicator.textContent = 'Set by environment variable';
            wrapper.appendChild(overrideIndicator);
    	}

    	const allUsers = [];
    	['plex', 'jellyfin', 'emby'].forEach(service => {
            let serviceUsers = getNestedValue(currentSettings, `features.poster_users.${service}`);
            if (typeof serviceUsers === 'string') {
            	serviceUsers = serviceUsers
                    .split(',')
                    .map(u => u.trim())
                    .filter(Boolean);
            }
            if (Array.isArray(serviceUsers)) {
            	serviceUsers.forEach(user => {
                    allUsers.push({ username: user, service });
            	});
            }
    	});

    	const serviceGroup = document.createElement('div');
    	serviceGroup.className = 'input-group';

    	const select = document.createElement('select');
    	select.className = 'setting-input';
    	select.disabled = isEnvControlled;

    	const emptyOption = document.createElement('option');
    	emptyOption.value = '';
    	emptyOption.textContent = '-- Select Preferred User --';
    	select.appendChild(emptyOption);

    	const currentPreferred = getNestedValue(currentSettings, 'features.poster_display.preferred_user');

    	allUsers.forEach(user => {
            const option = document.createElement('option');
            const serviceName = user.service.charAt(0).toUpperCase() + user.service.slice(1);

            option.value = JSON.stringify({ username: user.username, service: user.service });
            option.textContent = `${user.username} (${serviceName})`;

            if (
            	currentPreferred &&
            	user.username === currentPreferred.username &&
            	user.service === currentPreferred.service
            ) {
            	option.selected = true;
            }

            select.appendChild(option);
    	});

    	if (!isEnvControlled) {
            select.addEventListener('change', (e) => {
            	const value = e.target.value ? JSON.parse(e.target.value) : null;
            	handleSettingChange('features.poster_display.preferred_user', value);
            });
    	}

    	serviceGroup.appendChild(select);
    	wrapper.appendChild(serviceGroup);
    	container.appendChild(wrapper);
    }

    function renderUserManagement(container) {
    	const wrapper = document.createElement('div');
    	wrapper.className = 'user-management-wrapper';
    
    	const usersUI = document.createElement('div');
    	usersUI.className = 'users-container';
    
    	const userList = document.createElement('div');
    	userList.className = 'user-list';
    	userList.innerHTML = '<div class="loading-users">Loading users...</div>';
    
    	fetchUsers(userList);
    
    	usersUI.appendChild(userList);
    	wrapper.appendChild(usersUI);
    	container.appendChild(wrapper);
    }

    function fetchUsers(container) {
    	fetch('/api/auth/users')
            .then(response => {
            	if (!response.ok) {
                    throw new Error('Failed to fetch users');
            	}
            	return response.json();
            })
            .then(users => {
            	renderUserList(container, users);
            })
            .catch(error => {
            	console.error('Error fetching users:', error);
            	container.innerHTML = `
                    <div class="error-message">
                    	<i class="fa-solid fa-exclamation-circle"></i>
                    	Failed to load users
                    </div>
            	`;
            });
    }

    function renderUserList(container, userList) { 
    	if (userList.length === 0) { 
            container.innerHTML = '<div class="no-users">No users found</div>';
            return;
    	}
    
    	const usersList = document.createElement('div');
    	usersList.className = 'users-list';
    
    	userList.forEach(user => { 
    	       const internalUsername = user.internal_username; 
    	       const displayUsername = user.display_username; 
    	       const userData = user; 
    	       const username = displayUsername; 
            const userItem = document.createElement('div');
            userItem.className = 'user-item';
        
            const userInfo = document.createElement('div');
            userInfo.className = 'user-info';
        
            const userName = document.createElement('div');
            userName.className = 'user-name';
            
            const serviceType = userData.service_type || 'local'; 
            const serviceTypeDisplay = serviceType.charAt(0).toUpperCase() + serviceType.slice(1); 
            const displayRole = userData.display_role || 'User'; 
            const isAdminFlag = userData.is_admin || false; 

            let roleClass = displayRole.toLowerCase(); 

            userName.innerHTML = `
            	<span>${username}</span>
            	<span class="role-badge ${roleClass}">${displayRole}</span> <!-- Use display_role -->
            	<span class="service-type-badge ${serviceType}">${serviceTypeDisplay}</span>
            `;
        
            const userMeta = document.createElement('div');
            userMeta.className = 'user-meta';
            userMeta.innerHTML = `
            	<span>Created: ${formatDate(userData.created_at)}</span>
            	${userData.last_login ? `<span>Last login: ${formatDate(userData.last_login)}</span>` : ''}
            `;
        
            userInfo.appendChild(userName);
            userInfo.appendChild(userMeta);
        
            const userActions = document.createElement('div');
            userActions.className = 'user-actions';
        
            if (userData.service_type === 'local') {
                const resetPasswordButton = document.createElement('button');
                resetPasswordButton.className = 'user-action';
                resetPasswordButton.innerHTML = '<i class="fa-solid fa-key"></i>';
                resetPasswordButton.title = 'Reset Password';
                resetPasswordButton.addEventListener('click', () => showResetPasswordModal(internalUsername)); 
                userActions.appendChild(resetPasswordButton);
            }
        
            if (!(userData.service_type === 'local' && isAdminFlag)) {
                const deleteButton = document.createElement('button');
                deleteButton.className = 'user-action delete';
                deleteButton.innerHTML = '<i class="fa-solid fa-trash"></i>';
                deleteButton.title = 'Delete User';
                deleteButton.addEventListener('click', () => showDeleteUserModal(internalUsername, isAdminFlag)); 
                userActions.appendChild(deleteButton);
            }
        
            userItem.appendChild(userInfo);
            userItem.appendChild(userActions);
        
            usersList.appendChild(userItem);
    	});
    
    	container.innerHTML = '';
    	container.appendChild(usersList);
    }

    function formatDate(dateString) {
    	try {
            const date = new Date(dateString);
            return date.toLocaleString();
    	} catch (e) {
            return dateString;
    	}
    }

    function showAddUserModal() {
        showMessage('Adding new local users is disabled. Only the admin account is allowed.');
    }

    function showResetPasswordModal(internalUsername) { 
    	const modal = document.createElement('div');
    	modal.className = 'settings-modal'; 
    
    	modal.innerHTML = `
            <div class="dialog-content">
                <h3><i class="fa-solid fa-key"></i> Reset Password</h3>
                <p>Set a new password for user: <strong>${internalUsername}</strong></p> <!-- Display internal name here, as it's the one being acted upon -->
            
            	<form id="reset-password-form">
                    <div class="error-message" id="reset-password-error" style="display: none;"></div>
                
                    <div class="input-group">
                    	<label for="reset-password">New Password</label>
                    	<input type="password" id="reset-password" class="setting-input" required> <!-- Add setting-input class -->
                    </div>
                
                    <div class="input-group">
                    	<label for="confirm-reset-password">Confirm New Password</label>
                    	<input type="password" id="confirm-reset-password" class="setting-input" required> <!-- Add setting-input class -->
                    </div>
                
                    <div class="dialog-buttons">
                    	<button type="button" class="cancel-button">Cancel</button>
                    	<button type="submit" class="submit-button">Reset Password</button>
                    </div>
            	</form>
            </div>
    	`;
    
   	document.body.appendChild(modal);
    
    	modal.querySelector('#reset-password-form').addEventListener('submit', (e) => {
            e.preventDefault();
        
            const password = document.getElementById('reset-password').value;
            const confirmPassword = document.getElementById('confirm-reset-password').value;
        
            if (password !== confirmPassword) {
            	const errorElement = document.getElementById('reset-password-error');
            	errorElement.textContent = 'Passwords do not match';
            	errorElement.style.display = 'block';
            	return;
            }
        
            fetch(`/api/auth/admin/change-password/${internalUsername}`, { 
            	method: 'POST',
            	headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken() 
            	},
            	body: JSON.stringify({
                    password
            	})
            })
            .then(response => response.json())
            .then(data => {
            	if (data.success) {
                    modal.remove();
                
                    showMessage('Password reset successfully');
            	} else {
                    const errorElement = document.getElementById('reset-password-error');
                    errorElement.textContent = data.message;
                    errorElement.style.display = 'block';
            	}
            })
            .catch(error => {
            	console.error('Error resetting password:', error);
            	const errorElement = document.getElementById('reset-password-error');
            	errorElement.textContent = 'An error occurred. Please try again.';
            	errorElement.style.display = 'block';
            });
        });
    
        modal.querySelector('.cancel-button').addEventListener('click', () => {
            modal.remove();
    	});
    
    	modal.addEventListener('click', (e) => {
            if (e.target === modal) {
            	modal.remove();
            }
    	});
    }

    function showDeleteUserModal(internalUsername, isAdminFlag) { 
    	const modal = document.createElement('div');
    	modal.className = 'trakt-confirm-dialog';
    
    	modal.innerHTML = `
            <div class="dialog-content">
            	<h3><i class="fa-solid fa-trash"></i> Delete User</h3>
            	<p>Are you sure you want to delete the user: <strong>${internalUsername}</strong>?</p> <!-- Display internal name here, as it's the one being acted upon -->
            	${isAdminFlag ? '<p class="warning"><i class="fa-solid fa-exclamation-triangle"></i> Warning: This user has admin privileges.</p>' : ''} <!-- Use actual admin flag for warning -->
            	<div class="dialog-buttons">
                    <button type="button" class="cancel-button">Cancel</button>
                    <button type="button" class="delete-button">Delete User</button>
            	</div>
            </div>
    	`;
    
    	document.body.appendChild(modal);
    
    	modal.querySelector('.delete-button').addEventListener('click', () => {
            fetch(`/api/auth/users/${internalUsername}`, { 
            	method: 'DELETE',
                headers: {
                    'X-CSRFToken': getCsrfToken() 
                }
            })
            .then(response => response.json())
            .then(data => {
            	if (data.success) {
                    modal.remove();
                
                    showMessage(`User ${internalUsername} deleted successfully`); 
                
                    const userList = document.querySelector('.user-list');
                    if (userList) {
                    	fetchUsers(userList);
                    }
            	} else {
                    modal.innerHTML = `
                    	<div class="dialog-content">
                            <h3><i class="fa-solid fa-exclamation-circle"></i> Error</h3>
                            <p>${data.message}</p>
                            <div class="dialog-buttons">
                            	<button type="button" class="ok-button">OK</button>
                            </div>
                    	</div>
                    `;
                
                    modal.querySelector('.ok-button').addEventListener('click', () => {
                    	modal.remove();
                    });
            	}
            })
            .catch(error => {
            	console.error('Error deleting user:', error);
            	modal.innerHTML = `
                    <div class="dialog-content">
                    	<h3><i class="fa-solid fa-exclamation-circle"></i> Error</h3>
                    	<p>An error occurred. Please try again.</p>
                    	<div class="dialog-buttons">
                            <button type="button" class="ok-button">OK</button>
                    	</div>
                    </div>
            	`;
            
            	modal.querySelector('.ok-button').addEventListener('click', () => {
                    modal.remove();
            	})
            	.catch(error => {
            	    console.error('Error fetching user list for delete confirmation:', error);
            	    showError('Could not fetch user details to confirm deletion.');
            	});
            });
    	});
    
    	modal.querySelector('.cancel-button').addEventListener('click', () => {
            modal.remove();
        });
    
    	modal.addEventListener('click', (e) => {
            if (e.target === modal) {
            	modal.remove();
            }
    	});
    }

    initialize();
});
