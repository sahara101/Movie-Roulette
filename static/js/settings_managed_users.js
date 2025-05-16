window.openAddManagedUserModal = async function() {
    const existingModal = document.getElementById('addManagedUserModal');
    if (existingModal) {
        existingModal.remove();
    }

    let availableUsers = [];
    try {
        const response = await fetch('/api/settings/managed_users/available');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        availableUsers = await response.json();
    } catch (error) {
        console.error('Error fetching available managed users:', error);
        const errorMessage = `Error fetching available users: ${error.message || 'Please check server logs.'}`;
        if (typeof showError === 'function') {
            showError(errorMessage);
        } else {
            console.warn('showError function not found, using alert fallback.');
            alert(errorMessage);
        }
        return;
    }

    if (availableUsers.length === 0) {
        const noUsersMessage = 'No available Plex managed users found to add.';
        if (typeof showMessage === 'function') {
            showMessage(noUsersMessage);
        } else {
            console.warn('showMessage function not found, using alert fallback.');
            alert(noUsersMessage);
        }
        return;
    }

    const modalHTML = `
        <div class="trakt-confirm-dialog" id="addManagedUserModal"> 
            <div class="dialog-content"> 
                <h3><i class="fa-solid fa-user-plus"></i> Add Managed User</h3> 
                <div id="addManagedUserError" class="error-message" style="display: none;"></div> 
                <form id="addManagedUserForm">
                    <div class="input-group">
                        <label for="managedUserSelect">Select Plex User</label>
                        <select class="setting-input" id="managedUserSelect" required> 
                            <option value="" selected disabled>-- Select a User --</option>
                            ${availableUsers.map(user => `<option value="${user.id}" data-username="${user.name}">${user.name}</option>`).join('')}
                        </select>
                    </div>
                    <div class="input-group">
                        <label for="managedUsernameInput">Username (for login)</label>
                        <input type="text" class="setting-input" id="managedUsernameInput" required readonly> 
                        <small class="setting-description">Username is based on the selected Plex user.</small> 
                    </div>
                    <div class="input-group">
                        <label for="managedUserPassword">Set Password</label>
                        <input type="password" class="setting-input" id="managedUserPassword" required minlength="6"> 
                        <small class="setting-description">Minimum 6 characters.</small> 
                    </div>
                </form>
                <div class="dialog-buttons"> 
                    <button type="button" class="cancel-button" id="cancelAddManagedUserBtn">Cancel</button> 
                    <button type="button" class="submit-button" id="confirmAddManagedUserBtn">Add User</button> 
                    </div>
                </div>
            </div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHTML);

    const modalElement = document.getElementById('addManagedUserModal');
    if (!modalElement) {
        console.error("Failed to find modal element (#addManagedUserModal) after insertion!");
        return;
    }

    function closeModal() {
        const modalToClose = document.getElementById('addManagedUserModal');
        if (modalToClose) {
            modalToClose.remove();
        }
    }

    modalElement.addEventListener('click', (e) => {
        if (e.target === modalElement) {
            closeModal();
        }
    });

    if (modalElement) {
        const userSelect = modalElement.querySelector('#managedUserSelect');
        const usernameInput = modalElement.querySelector('#managedUsernameInput');
        const cancelBtn = modalElement.querySelector('#cancelAddManagedUserBtn');
        const confirmBtn = modalElement.querySelector('#confirmAddManagedUserBtn');
        const passwordInput = modalElement.querySelector('#managedUserPassword');

        if (userSelect && usernameInput) {
            userSelect.addEventListener('change', (event) => {
                const selectedOption = event.target.selectedOptions[0];
                if (selectedOption) {
                    const username = selectedOption.getAttribute('data-username');
                    usernameInput.value = username || '';
                } else {
                    usernameInput.value = '';
                }
            });
        } else {
            console.error("Could not find user select or username input elements in modal.");
        }

        if (cancelBtn) {
            cancelBtn.addEventListener('click', () => {
                closeModal();
            });
        } else {
            console.error("Could not find cancel button in modal.");
        }

        if (confirmBtn) {
            confirmBtn.addEventListener('click', async () => {
                const form = modalElement.querySelector('#addManagedUserForm');
                const errorDiv = modalElement.querySelector('#addManagedUserError');
                const currentSelectedOption = modalElement.querySelector('#managedUserSelect').selectedOptions[0];
                const currentUsername = modalElement.querySelector('#managedUsernameInput').value;
                const currentPassword = modalElement.querySelector('#managedUserPassword').value;
                
                errorDiv.style.display = 'none';

                if (!form.checkValidity()) {
                    form.reportValidity();
                    return;
                }

                const selectedOption = userSelect.selectedOptions[0];
                const plexUserId = selectedOption ? selectedOption.value : null;
                const username = usernameInput.value;
                const password = passwordInput.value;

                if (!plexUserId) {
                    errorDiv.textContent = 'Please select a Plex user.';
                    errorDiv.style.display = 'block';
                    return;
                }

                if (!password || password.length < 6) {
                     errorDiv.textContent = 'Password must be at least 6 characters long.';
                     errorDiv.style.display = 'block';
                     passwordInput.focus();
                     return;
                }

                confirmBtn.disabled = true;
                confirmBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Adding...';

                try {
                    const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
                    const response = await fetch('/api/settings/managed_users', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': csrfToken
                        },
                        body: JSON.stringify({
                            plex_user_id: plexUserId,
                            username: username,
                            password: password
                        })
                    });

                    if (!response.ok) {
                        const errorData = await response.json();
                        throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
                    }

                    const newUser = await response.json();
                    closeModal(); 

                    document.dispatchEvent(new CustomEvent('managedUserAdded'));

                } catch (error) {
                    console.error('Error adding managed user:', error);
                    errorDiv.textContent = error.message || 'An unexpected error occurred.';
                    errorDiv.style.display = 'block';
                } finally {
                    confirmBtn.disabled = false;
                    confirmBtn.innerHTML = 'Add User';
                }
            }); 
        } else {
            console.error("Could not find confirm button in modal.");
        }
    }

    modalElement.style.display = 'flex'; 

}