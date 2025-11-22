<!--
Passkey Management - View, rename, delete, and add passkeys
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { apiEndpoints, getApiEndpoint } from '../../config/api';
    import SettingsItem from '../SettingsItem.svelte';
    import { createEventDispatcher } from 'svelte';
    import { encryptWithMasterKey, decryptWithMasterKey } from '../../services/cryptoService';
    import { userProfile } from '../../stores/userProfile';

    const dispatch = createEventDispatcher();

    // State
    // Only store essential passkey data needed for the settings UI
    let passkeys = $state<Array<{
        id: string;  // Required for rename/delete operations
        device_name: string | null;  // Decrypted device name for display
        registered_at: string | null;  // Registration timestamp
        last_used_at: string | null;  // Last usage timestamp
        sign_count: number;  // Usage counter
    }>>([]);
    let isLoading = $state(false);
    let errorMessage = $state<string | null>(null);
    let successMessage = $state<string | null>(null);
    let editingPasskeyId = $state<string | null>(null);
    let editingDeviceName = $state('');
    let deletingPasskeyId = $state<string | null>(null);

    // Format date for display
    function formatDate(dateString: string | null): string {
        if (!dateString) return 'Never';
        try {
            const date = new Date(dateString);
            return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        } catch {
            return 'Invalid date';
        }
    }

    // Load passkeys from backend
    async function loadPasskeys() {
        isLoading = true;
        errorMessage = null;
        successMessage = null;

        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.passkey_list), {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                },
                credentials: 'include'
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.message || 'Failed to load passkeys');
            }

            const data = await response.json();
            if (data.success) {
                // Decrypt device names client-side using master key
                const decryptedPasskeys = [];
                for (const passkey of data.passkeys || []) {
                    let deviceName = null;
                    if (passkey.encrypted_device_name) {
                        // Decrypt device name using master key (client-side only)
                        deviceName = await decryptWithMasterKey(passkey.encrypted_device_name);
                        if (!deviceName) {
                            console.warn(`[SettingsPasskeys] Failed to decrypt device name for passkey ${passkey.id}`);
                            deviceName = 'Unknown Device';
                        }
                    }
                    decryptedPasskeys.push({
                        ...passkey,
                        device_name: deviceName
                    });
                }
                passkeys = decryptedPasskeys;
                console.log(`[SettingsPasskeys] Loaded ${passkeys.length} passkey(s)`);
            } else {
                throw new Error(data.message || 'Failed to load passkeys');
            }
        } catch (error) {
            console.error('[SettingsPasskeys] Error loading passkeys:', error);
            errorMessage = error instanceof Error ? error.message : 'Failed to load passkeys. Please try again.';
        } finally {
            isLoading = false;
        }
    }

    // Start editing a passkey name
    function startEdit(passkey: any) {
        editingPasskeyId = passkey.id;
        editingDeviceName = passkey.device_name || 'Unknown Device';
    }

    // Cancel editing
    function cancelEdit() {
        editingPasskeyId = null;
        editingDeviceName = '';
    }

    // Save renamed passkey
    async function saveRename(passkeyId: string) {
        if (!editingDeviceName.trim()) {
            errorMessage = 'Device name cannot be empty';
            return;
        }

        isLoading = true;
        errorMessage = null;
        successMessage = null;

        try {
            // Encrypt device name client-side using master key before sending to server
            const encryptedDeviceName = await encryptWithMasterKey(editingDeviceName.trim());
            if (!encryptedDeviceName) {
                throw new Error('Failed to encrypt device name');
            }

            const response = await fetch(getApiEndpoint(apiEndpoints.auth.passkey_rename), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                },
                credentials: 'include',
                body: JSON.stringify({
                    passkey_id: passkeyId,
                    encrypted_device_name: encryptedDeviceName
                })
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.message || 'Failed to rename passkey');
            }

            const data = await response.json();
            if (data.success) {
                successMessage = 'Passkey renamed successfully';
                editingPasskeyId = null;
                editingDeviceName = '';
                // Reload passkeys to get updated names
                await loadPasskeys();
            } else {
                throw new Error(data.message || 'Failed to rename passkey');
            }
        } catch (error) {
            console.error('[SettingsPasskeys] Error renaming passkey:', error);
            errorMessage = error instanceof Error ? error.message : 'Failed to rename passkey. Please try again.';
        } finally {
            isLoading = false;
        }
    }

    // Confirm delete
    function confirmDelete(passkeyId: string) {
        deletingPasskeyId = passkeyId;
    }

    // Cancel delete
    function cancelDelete() {
        deletingPasskeyId = null;
    }

    // Delete passkey
    async function deletePasskey(passkeyId: string) {
        isLoading = true;
        errorMessage = null;
        successMessage = null;

        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.passkey_delete), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                },
                credentials: 'include',
                body: JSON.stringify({
                    passkey_id: passkeyId
                })
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.message || 'Failed to delete passkey');
            }

            const data = await response.json();
            if (data.success) {
                successMessage = 'Passkey deleted successfully';
                deletingPasskeyId = null;
                // Reload passkeys
                await loadPasskeys();
            } else {
                throw new Error(data.message || 'Failed to delete passkey');
            }
        } catch (error) {
            console.error('[SettingsPasskeys] Error deleting passkey:', error);
            errorMessage = error instanceof Error ? error.message : 'Failed to delete passkey. Please try again.';
        } finally {
            isLoading = false;
        }
    }

    // Add new passkey (navigate to signup flow or trigger registration)
    function addPasskey() {
        // TODO: Implement passkey registration flow for existing users
        // For now, show a message
        errorMessage = 'Adding new passkeys from settings is not yet implemented. Please use the signup flow or contact support.';
    }

    /**
     * Check if delete button should be shown for a passkey.
     * Hide delete button if:
     * - It's the last remaining passkey AND
     * - User doesn't have 2FA enabled (which means no password+2FA login method)
     * 
     * This prevents users from deleting their only secure login method.
     * The backend will also prevent deletion, but we hide the button for better UX.
     * 
     * Uses Svelte 5 runes: $userProfile auto-subscribes to the store
     */
    function canDeletePasskey(): boolean {
        // If there's more than one passkey, deletion is always allowed
        if (passkeys.length > 1) {
            return true;
        }
        
        // If it's the last passkey, check if user has password+2FA as backup
        // If 2FA is enabled, user likely has password+2FA (backend will verify)
        // If 2FA is not enabled, user cannot use password login (password requires 2FA)
        // Use $userProfile to auto-subscribe to the store (Svelte 5 syntax)
        return $userProfile.tfa_enabled;
    }

    // Load passkeys on mount
    onMount(() => {
        loadPasskeys();
    });
</script>

<div class="passkeys-container">
    <!-- Error/Success Messages -->
    {#if errorMessage}
        <div class="message error">
            {errorMessage}
        </div>
    {/if}
    {#if successMessage}
        <div class="message success">
            {successMessage}
        </div>
    {/if}

    <!-- Loading State -->
    {#if isLoading && passkeys.length === 0}
        <div class="loading">
            Loading passkeys...
        </div>
    {:else}
        <!-- Passkey List -->
        {#if passkeys.length === 0}
            <div class="empty-state">
                <p>No passkeys registered yet.</p>
                <p class="hint">Passkeys allow you to sign in without a password using biometric authentication.</p>
            </div>
        {:else}
            {#each passkeys as passkey}
                <div class="passkey-item">
                    {#if editingPasskeyId === passkey.id}
                        <!-- Edit Mode -->
                        <div class="edit-form">
                            <input
                                type="text"
                                bind:value={editingDeviceName}
                                placeholder="Device name"
                                class="device-name-input"
                                onkeydown={(e) => {
                                    if (e.key === 'Enter') {
                                        saveRename(passkey.id);
                                    } else if (e.key === 'Escape') {
                                        cancelEdit();
                                    }
                                }}
                            />
                            <div class="edit-actions">
                                <button class="btn-save" onclick={() => saveRename(passkey.id)} disabled={isLoading}>
                                    Save
                                </button>
                                <button class="btn-cancel" onclick={cancelEdit} disabled={isLoading}>
                                    Cancel
                                </button>
                            </div>
                        </div>
                    {:else if deletingPasskeyId === passkey.id}
                        <!-- Delete Confirmation -->
                        <div class="delete-confirmation">
                            <p>Are you sure you want to delete this passkey?</p>
                            <p class="warning">You must have at least one passkey or password with 2FA enabled.</p>
                            <div class="delete-actions">
                                <button class="btn-delete" onclick={() => deletePasskey(passkey.id)} disabled={isLoading}>
                                    Delete
                                </button>
                                <button class="btn-cancel" onclick={cancelDelete} disabled={isLoading}>
                                    Cancel
                                </button>
                            </div>
                        </div>
                    {:else}
                        <!-- Display Mode -->
                        <div class="passkey-info">
                            <div class="passkey-header">
                                <span class="device-name">{passkey.device_name || 'Unknown Device'}</span>
                                <span class="sign-count">Used {passkey.sign_count} time(s)</span>
                            </div>
                            <div class="passkey-details">
                                <div class="detail-item">
                                    <span class="label">Registered:</span>
                                    <span class="value">{formatDate(passkey.registered_at)}</span>
                                </div>
                                <div class="detail-item">
                                    <span class="label">Last used:</span>
                                    <span class="value">{formatDate(passkey.last_used_at)}</span>
                                </div>
                            </div>
                            <div class="passkey-actions">
                                <button class="btn-rename" onclick={() => startEdit(passkey)} disabled={isLoading}>
                                    Rename
                                </button>
                                {#if canDeletePasskey()}
                                    <button class="btn-delete" onclick={() => confirmDelete(passkey.id)} disabled={isLoading}>
                                        Delete
                                    </button>
                                {/if}
                            </div>
                        </div>
                    {/if}
                </div>
            {/each}
        {/if}

        <!-- Add Passkey Button -->
        <div class="add-passkey-section">
            <button class="btn-add" onclick={addPasskey} disabled={isLoading}>
                Add Passkey
            </button>
        </div>
    {/if}
</div>

<style>
    .passkeys-container {
        padding: 10px;
    }

    .message {
        padding: 10px;
        margin-bottom: 15px;
        border-radius: 4px;
        font-size: 14px;
    }

    .message.error {
        background-color: rgba(255, 0, 0, 0.1);
        color: #ff0000;
        border: 1px solid #ff0000;
    }

    .message.success {
        background-color: rgba(0, 255, 0, 0.1);
        color: #00aa00;
        border: 1px solid #00aa00;
    }

    .loading {
        padding: 20px;
        text-align: center;
        color: #666;
    }

    .empty-state {
        padding: 40px 20px;
        text-align: center;
        color: #666;
    }

    .empty-state .hint {
        font-size: 12px;
        margin-top: 10px;
        color: #999;
    }

    .passkey-item {
        margin-bottom: 15px;
        padding: 15px;
        border: 1px solid #ddd;
        border-radius: 8px;
        background-color: #f9f9f9;
    }

    .passkey-info {
        display: flex;
        flex-direction: column;
        gap: 10px;
    }

    .passkey-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    .device-name {
        font-weight: bold;
        font-size: 16px;
    }

    .sign-count {
        font-size: 12px;
        color: #666;
    }

    .passkey-details {
        display: flex;
        flex-direction: column;
        gap: 5px;
        font-size: 14px;
    }

    .detail-item {
        display: flex;
        gap: 10px;
    }

    .detail-item .label {
        font-weight: 500;
        color: #666;
    }

    .detail-item .value {
        color: #333;
    }

    .passkey-actions {
        display: flex;
        gap: 10px;
        margin-top: 10px;
    }

    .edit-form {
        display: flex;
        flex-direction: column;
        gap: 10px;
    }

    .device-name-input {
        padding: 8px;
        border: 1px solid #ddd;
        border-radius: 4px;
        font-size: 14px;
    }

    .edit-actions,
    .delete-actions {
        display: flex;
        gap: 10px;
    }

    .delete-confirmation {
        display: flex;
        flex-direction: column;
        gap: 10px;
    }

    .delete-confirmation .warning {
        font-size: 12px;
        color: #ff6600;
        font-weight: 500;
    }

    button {
        padding: 8px 16px;
        border: none;
        border-radius: 4px;
        cursor: pointer;
        font-size: 14px;
        transition: background-color 0.2s;
    }

    button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .btn-rename {
        background-color: #4CAF50;
        color: white;
    }

    .btn-rename:hover:not(:disabled) {
        background-color: #45a049;
    }

    .btn-delete {
        background-color: #f44336;
        color: white;
    }

    .btn-delete:hover:not(:disabled) {
        background-color: #da190b;
    }

    .btn-save {
        background-color: #2196F3;
        color: white;
    }

    .btn-save:hover:not(:disabled) {
        background-color: #0b7dda;
    }

    .btn-cancel {
        background-color: #666;
        color: white;
    }

    .btn-cancel:hover:not(:disabled) {
        background-color: #555;
    }

    .btn-add {
        background-color: #2196F3;
        color: white;
        padding: 12px 24px;
        width: 100%;
        font-size: 16px;
        font-weight: 500;
    }

    .btn-add:hover:not(:disabled) {
        background-color: #0b7dda;
    }

    .add-passkey-section {
        margin-top: 20px;
        padding-top: 20px;
        border-top: 1px solid #ddd;
    }

    /* Responsive Styles */
    @media (max-width: 480px) {
        .passkeys-container {
            padding: 5px;
        }

        .passkey-item {
            padding: 10px;
        }

        .passkey-header {
            flex-direction: column;
            align-items: flex-start;
            gap: 5px;
        }
    }
</style>

