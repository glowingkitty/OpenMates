<!--
Passkey Management - View, rename, delete, and add passkeys
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { apiEndpoints, getApiEndpoint } from '../../config/api';
    import SettingsItem from '../SettingsItem.svelte';
    import { createEventDispatcher } from 'svelte';
    import { encryptWithMasterKey, decryptWithMasterKey, getEmailDecryptedWithMasterKey, hashEmail, getEmailSalt, deriveWrappingKeyFromPRF, encryptKey, hashKeyFromPRF, uint8ArrayToBase64, base64ToUint8Array } from '../../services/cryptoService';
    import { getMasterKeyFromIndexedDB, isDeviceTrusted } from '../../services/cryptoKeyStorage';
    import { userProfile } from '../../stores/userProfile';
    import { generateDeviceName } from '../../utils/deviceName';
    import * as cryptoService from '../../services/cryptoService';

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
    let isDeviceTrustedState = $state<boolean | null>(null);

    // Format date for display
    // Handles various date formats from Directus (ISO strings, Unix timestamps, etc.)
    function formatDate(dateString: string | null): string {
        if (!dateString) return 'Never';
        try {
            let date: Date;
            
            // Check if it's a Unix timestamp (number as string)
            if (/^\d+$/.test(dateString)) {
                // Unix timestamp in seconds - convert to milliseconds
                date = new Date(parseInt(dateString) * 1000);
            } else {
                // Try parsing as ISO string or other date format
                date = new Date(dateString);
            }
            
            // Check if date is valid
            if (isNaN(date.getTime())) {
                console.warn(`[SettingsPasskeys] Invalid date string: ${dateString}`);
                return 'Invalid date';
            }
            
            return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        } catch (error) {
            console.error(`[SettingsPasskeys] Error formatting date "${dateString}":`, error);
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
                    // Log raw passkey data for debugging
                    console.log(`[SettingsPasskeys] Raw passkey data:`, {
                        id: passkey.id,
                        registered_at: passkey.registered_at,
                        last_used_at: passkey.last_used_at,
                        sign_count: passkey.sign_count,
                        encrypted_device_name: passkey.encrypted_device_name ? 'present' : 'missing'
                    });
                    
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

    /**
     * Converts base64url to ArrayBuffer (WebAuthn format)
     */
    function base64UrlToArrayBuffer(base64url: string): ArrayBuffer {
        let base64 = base64url.replace(/-/g, '+').replace(/_/g, '/');
        while (base64.length % 4) {
            base64 += '=';
        }
        const binary = window.atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
        }
        return bytes.buffer;
    }

    /**
     * Converts ArrayBuffer to base64url (WebAuthn format)
     */
    function arrayBufferToBase64Url(buffer: ArrayBuffer): string {
        const bytes = new Uint8Array(buffer);
        let binary = '';
        for (let i = 0; i < bytes.byteLength; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        // Convert to base64url (replace + with -, / with _, remove padding)
        return window.btoa(binary)
            .replace(/\+/g, '-')
            .replace(/\//g, '_')
            .replace(/=/g, '');
    }

    /**
     * Add new passkey to existing account
     * Follows similar flow to signup but uses existing master key and email salt
     */
    async function addPasskey() {
        if (isLoading) return;

        isLoading = true;
        errorMessage = null;
        successMessage = null;

        try {
            // Step 1: Get current user's email and email salt
            const email = await getEmailDecryptedWithMasterKey();
            if (!email) {
                throw new Error('Unable to retrieve your email. Please log out and log back in.');
            }

            const emailSalt = getEmailSalt();
            if (!emailSalt) {
                throw new Error('Unable to retrieve your email salt. Please log out and log back in.');
            }

            // Step 2: Get existing master key from IndexedDB
            const masterKey = await getMasterKeyFromIndexedDB();
            if (!masterKey) {
                throw new Error('Unable to retrieve your master key. Please log out and log back in.');
            }

            // Step 3: Generate hashed email for lookup
            const hashedEmail = await hashEmail(email);

            // Step 4: Get username from userProfile
            const username = $userProfile.username;
            if (!username) {
                throw new Error('Unable to retrieve your username. Please refresh the page.');
            }

            // Step 5: Initiate passkey registration with backend
            // For existing users, we need to get user_id from the session
            // The backend will extract it from the auth cookie
            const initiateResponse = await fetch(getApiEndpoint(apiEndpoints.auth.passkey_registration_initiate), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                },
                body: JSON.stringify({
                    hashed_email: hashedEmail,
                    user_id: 'current', // Signal to backend to use current authenticated user
                    username: username
                }),
                credentials: 'include'
            });

            if (!initiateResponse.ok) {
                const errorData = await initiateResponse.json().catch(() => ({}));
                throw new Error(errorData.message || 'Failed to initiate passkey registration');
            }

            const initiateData = await initiateResponse.json();
            if (!initiateData.success) {
                throw new Error(initiateData.message || 'Failed to initiate passkey registration');
            }

            // Step 6: Prepare WebAuthn creation options
            const challenge = base64UrlToArrayBuffer(initiateData.challenge);
            const userId = base64UrlToArrayBuffer(initiateData.user.id);

            const publicKeyCredentialCreationOptions: PublicKeyCredentialCreationOptions = {
                challenge: challenge,
                rp: initiateData.rp,
                user: {
                    id: userId,
                    name: initiateData.user.name,
                    displayName: initiateData.user.displayName
                },
                pubKeyCredParams: initiateData.pubKeyCredParams,
                timeout: initiateData.timeout,
                attestation: initiateData.attestation as AttestationConveyancePreference,
                authenticatorSelection: initiateData.authenticatorSelection,
                extensions: {
                    prf: {
                        eval: {
                            first: base64UrlToArrayBuffer(initiateData.extensions?.prf?.eval?.first || initiateData.challenge)
                        }
                    }
                } as AuthenticationExtensionsClientInputs
            };

            // Step 7: Create passkey using WebAuthn API
            let credential: PublicKeyCredential;
            try {
                credential = await navigator.credentials.create({
                    publicKey: publicKeyCredentialCreationOptions
                }) as PublicKeyCredential;
            } catch (error: any) {
                console.error('[SettingsPasskeys] WebAuthn credential creation failed:', error);
                if (error.name === 'NotSupportedError' || 
                    error.message?.includes('PRF') || 
                    error.message?.includes('prf') ||
                    error.message?.toLowerCase().includes('extension')) {
                    throw new Error('Your device does not support PRF extension, which is required for passkey authentication. Please use a device that supports PRF (e.g., iOS 18+, recent Chrome, Android with Google Password Manager).');
                }
                if (error.name === 'NotAllowedError') {
                    throw new Error('Passkey registration was cancelled or not allowed.');
                }
                throw new Error(error.message || 'Failed to create passkey. Please try again.');
            }

            if (!credential || !(credential instanceof PublicKeyCredential)) {
                throw new Error('Invalid credential created');
            }

            const response = credential.response as AuthenticatorAttestationResponse;

            // Step 8: Check PRF extension support (CRITICAL for zero-knowledge encryption)
            const clientExtensionResults = credential.getClientExtensionResults();
            console.log('[SettingsPasskeys] Client extension results:', clientExtensionResults);
            const prfResults = clientExtensionResults?.prf as any;

            if (!prfResults || prfResults.enabled === false) {
                throw new Error('PRF extension is required for passkey authentication. Your device does not support PRF. Please use a device that supports PRF (e.g., iOS 18+, recent Chrome, Android with Google Password Manager).');
            }

            // Step 9: Extract PRF signature
            const prfSignatureBuffer = prfResults.results?.first;
            if (!prfSignatureBuffer) {
                throw new Error('PRF signature not found. Your device may not support PRF extension.');
            }

            // Convert PRF signature to Uint8Array
            let prfSignature: Uint8Array;
            if (typeof prfSignatureBuffer === 'string') {
                const hexString = prfSignatureBuffer;
                prfSignature = new Uint8Array(hexString.match(/.{1,2}/g)!.map(byte => parseInt(byte, 16)));
            } else if (prfSignatureBuffer instanceof ArrayBuffer) {
                prfSignature = new Uint8Array(prfSignatureBuffer);
            } else if (ArrayBuffer.isView(prfSignatureBuffer)) {
                prfSignature = new Uint8Array(prfSignatureBuffer.buffer, prfSignatureBuffer.byteOffset, prfSignatureBuffer.byteLength);
            } else {
                throw new Error('PRF signature is in unknown format');
            }

            // Validate PRF signature length
            if (prfSignature.length < 16 || prfSignature.length > 64) {
                throw new Error('PRF signature has invalid length');
            }

            console.log('[SettingsPasskeys] PRF signature validated successfully');

            // Step 10: Derive wrapping key from PRF signature using existing email salt
            const wrappingKey = await deriveWrappingKeyFromPRF(prfSignature, emailSalt);

            // Step 11: Wrap the existing master key with the new wrapping key
            const { wrapped: encryptedMasterKey, iv: keyIv } = await encryptKey(masterKey, wrappingKey);

            // Step 12: Generate lookup hash from PRF signature (for this passkey)
            const lookupHash = await hashKeyFromPRF(prfSignature, emailSalt);

            // Step 13: Re-encrypt email with master key for passkey login
            // This ensures encrypted_email_with_master_key matches the master key that will be unwrapped during passkey login
            // CRITICAL: The email must be encrypted with the same master key that's being wrapped for the passkey
            const { encryptWithMasterKeyDirect } = await import('../../services/cryptoService');
            const encryptedEmailWithMasterKey = await encryptWithMasterKeyDirect(email, masterKey);
            if (!encryptedEmailWithMasterKey) {
                throw new Error('Failed to encrypt email with master key. Please try again.');
            }
            console.log('[SettingsPasskeys] Email re-encrypted with master key for passkey login');

            // Step 14: Generate and encrypt device name for passkey
            const deviceName = generateDeviceName();
            const encryptedDeviceName = await encryptWithMasterKeyDirect(deviceName, masterKey);
            if (!encryptedDeviceName) {
                console.warn('[SettingsPasskeys] Failed to encrypt device name, continuing without it');
            }

            // Step 15: Extract credential data for backend
            const credentialId = arrayBufferToBase64Url(credential.rawId);
            const clientDataJSONB64 = uint8ArrayToBase64(new Uint8Array(response.clientDataJSON));
            const attestationObject = new Uint8Array(response.attestationObject);
            const attestationObjectB64 = uint8ArrayToBase64(attestationObject);
            const authenticatorData = attestationObject.slice(0, 37);
            const authenticatorDataB64 = uint8ArrayToBase64(authenticatorData);

            // Step 15: Complete passkey registration with backend
            // For existing users, we send user_id: 'current' to signal backend to use authenticated user
            const completeResponse = await fetch(getApiEndpoint(apiEndpoints.auth.passkey_registration_complete), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                },
                body: JSON.stringify({
                    credential_id: credentialId,
                    attestation_response: {
                        attestationObject: attestationObjectB64,
                        publicKey: {}
                    },
                    client_data_json: clientDataJSONB64,
                    authenticator_data: authenticatorDataB64,
                    hashed_email: hashedEmail,
                    username: username,
                    invite_code: "", // Not needed for existing users
                    encrypted_email: "", // Not needed for existing users (already stored)
                    encrypted_email_with_master_key: encryptedEmailWithMasterKey, // Re-encrypted with current master key for passkey login
                    encrypted_device_name: encryptedDeviceName || null,
                    user_email_salt: uint8ArrayToBase64(emailSalt),
                    encrypted_master_key: encryptedMasterKey,
                    key_iv: keyIv,
                    salt: uint8ArrayToBase64(emailSalt),
                    lookup_hash: lookupHash,
                    language: $userProfile.language || 'en',
                    darkmode: $userProfile.darkmode || false,
                    prf_enabled: true,
                    user_id: 'current' // Signal to backend to use current authenticated user
                }),
                credentials: 'include'
            });

            if (!completeResponse.ok) {
                const errorData = await completeResponse.json().catch(() => ({}));
                throw new Error(errorData.message || 'Failed to complete passkey registration');
            }

            const completeData = await completeResponse.json();
            if (!completeData.success) {
                throw new Error(completeData.message || 'Failed to register passkey');
            }

            // Step 16: Reload passkeys to show the new one
            successMessage = 'Passkey added successfully!';
            await loadPasskeys();

        } catch (error) {
            console.error('[SettingsPasskeys] Error adding passkey:', error);
            errorMessage = error instanceof Error ? error.message : 'Failed to add passkey. Please try again.';
        } finally {
            isLoading = false;
        }
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

    async function checkDeviceTrust() {
        try {
            isDeviceTrustedState = await isDeviceTrusted();
            console.log('[SettingsPasskeys] Device trust check:', isDeviceTrustedState);
        } catch (error) {
            console.error('[SettingsPasskeys] Error checking device trust:', error);
            isDeviceTrustedState = false;
        }
    }

    // Load passkeys on mount
    onMount(() => {
        checkDeviceTrust();
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

    <!-- Untrusted Device Message -->
    {#if isDeviceTrustedState === false}
        <div class="untrusted-device-message">
            <p class="title">Device Not Trusted</p>
            <p class="description">
                To manage passkeys on this device, you need to select "Stay logged in" during login. This ensures your device is trusted for managing your security credentials.
            </p>
            <p class="instruction">
                Please log out and log back in, then select "Stay logged in" to enable passkey management.
            </p>
        </div>
    {/if}

    <!-- Loading State -->
    {#if isLoading && passkeys.length === 0}
        <div class="loading">
            Loading passkeys...
        </div>
    {:else if isDeviceTrustedState === false}
        <!-- Passkey management is disabled for untrusted devices -->
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
            <button onclick={addPasskey} disabled={isLoading}>
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

    .untrusted-device-message {
        padding: 20px;
        margin-bottom: 20px;
        border-radius: 8px;
        background-color: rgba(255, 165, 0, 0.1);
        border: 2px solid #ffa500;
    }

    .untrusted-device-message .title {
        font-size: 16px;
        font-weight: 600;
        color: #ff8c00;
        margin: 0 0 12px 0;
    }

    .untrusted-device-message .description {
        font-size: 14px;
        color: var(--color-grey-100);
        margin: 0 0 12px 0;
        line-height: 1.5;
    }

    .untrusted-device-message .instruction {
        font-size: 14px;
        color: #ff8c00;
        font-weight: 500;
        margin: 0;
        line-height: 1.5;
    }

    .loading {
        padding: 20px;
        text-align: center;
        color: var(--color-grey-100);
    }

    .empty-state {
        padding: 40px 20px;
        text-align: center;
        color: var(--color-grey-100);
    }

    .empty-state .hint {
        font-size: 12px;
        margin-top: 10px;
        color: var(--color-grey-100);
    }

    .passkey-item {
        margin-bottom: 15px;
        padding: 15px;
        border: 1px solid var(--color-grey-30);
        border-radius: 8px;
        background-color: var(--color-grey-10);
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
        color: var(--color-grey-100);
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
        color: var(--color-grey-100);
    }

    .detail-item .value {
        color: var(--color-grey-100);
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

