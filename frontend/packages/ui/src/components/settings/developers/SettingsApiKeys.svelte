<script lang="ts">
    import { onMount, createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { authStore } from '../../../stores/authStore';
    import { getApiEndpoint } from '../../../config/api';
    import {
        encryptWithMasterKeyDirect,
        decryptWithMasterKey,
        deriveKeyFromApiKey,
        encryptKey,
        getKeyFromStorage,
        uint8ArrayToBase64,
        base64ToUint8Array
    } from '../../../services/cryptoService';

    const dispatch = createEventDispatcher();

    // State using Svelte 5 $state() runes
    let apiKeys = $state<any[]>([]);
    let loading = $state(true);
    let error = $state<string>('');
    let showCreateForm = $state(false);
    let newKeyName = $state('');
    let createdKey = $state('');
    let showCreatedKey = $state(false);
    let creatingKey = $state(false);

    // Load API keys on mount
    onMount(() => {
        loadApiKeys();
    });

    async function loadApiKeys() {
        try {
            loading = true;
            error = '';
            const response = await fetch(getApiEndpoint('/v1/settings/api-keys'), {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                credentials: 'include' // Include cookies for authentication
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Failed to load API keys');
            }

            const data = await response.json();
            const rawKeys = data.api_keys || [];
            
            // Decrypt encrypted_name and encrypted_key_prefix for each key
            const masterKey = await getKeyFromStorage();
            if (!masterKey) {
                throw new Error('Master key not found. Please log in again.');
            }

            apiKeys = await Promise.all(
                rawKeys.map(async (key: any) => {
                    let decryptedName = key.encrypted_name || '';
                    let decryptedPrefix = key.encrypted_key_prefix || '';
                    const lastUsed = key.last_used_at || null;
                    
                    try {
                        if (key.encrypted_name) {
                            const decrypted = await decryptWithMasterKey(key.encrypted_name);
                            if (decrypted) {
                                decryptedName = decrypted;
                            }
                        }
                        if (key.encrypted_key_prefix) {
                            const decrypted = await decryptWithMasterKey(key.encrypted_key_prefix);
                            if (decrypted) {
                                decryptedPrefix = decrypted;
                            }
                        }
                    } catch (err) {
                        console.error('Error decrypting API key fields:', err);
                        // Keep encrypted values if decryption fails
                    }

                    return {
                        ...key,
                        name: decryptedName,
                        key_prefix: decryptedPrefix,
                        last_used: lastUsed
                    };
                })
            );
        } catch (err: any) {
            console.error('Error loading API keys:', err);
            error = err.message || 'Failed to load API keys';
        } finally {
            loading = false;
        }
    }

    function generateApiKey(): string {
        // Generate a secure API key: sk-api-[32 random chars]
        const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
        let result = 'sk-api-';
        for (let i = 0; i < 32; i++) {
            result += chars.charAt(Math.floor(Math.random() * chars.length));
        }
        return result;
    }

    async function hashApiKey(key: string): Promise<string> {
        // Use Web Crypto API for proper SHA-256 hashing
        const encoder = new TextEncoder();
        const data = encoder.encode(key);
        const hashBuffer = await crypto.subtle.digest('SHA-256', data);
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
    }

    async function createApiKey() {
        if (!newKeyName.trim()) {
            error = 'API key name is required';
            return;
        }

        try {
            creatingKey = true;
            error = '';

            // Get master key for encryption
            const masterKey = await getKeyFromStorage();
            if (!masterKey) {
                throw new Error('Master key not found. Please log in again.');
            }

            // Generate API key client-side
            const apiKey = generateApiKey();
            const apiKeyHash = await hashApiKey(apiKey);
            const keyPrefix = apiKey.substring(0, 12) + '...';

            // Encrypt name and key_prefix with master key (client-side encryption)
            const encryptedName = await encryptWithMasterKeyDirect(newKeyName.trim(), masterKey);
            const encryptedKeyPrefix = await encryptWithMasterKeyDirect(keyPrefix, masterKey);

            if (!encryptedName || !encryptedKeyPrefix) {
                throw new Error('Failed to encrypt API key data');
            }

            // Derive key from API key and encrypt master key (for CLI/npm/pip access)
            // Generate random salt for this API key
            const salt = crypto.getRandomValues(new Uint8Array(16));
            const derivedKey = await deriveKeyFromApiKey(apiKey, salt);
            
            // Encrypt master key with derived key
            const { wrapped: encryptedMasterKey, iv: keyIv } = await encryptKey(masterKey, derivedKey);

            const response = await fetch(getApiEndpoint('/v1/settings/api-keys'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                credentials: 'include', // Include cookies for authentication
                body: JSON.stringify({
                    encrypted_name: encryptedName,
                    api_key_hash: apiKeyHash,
                    encrypted_key_prefix: encryptedKeyPrefix,
                    encrypted_master_key: encryptedMasterKey,
                    salt: uint8ArrayToBase64(salt),
                    key_iv: keyIv
                })
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Failed to create API key');
            }

            // Show the created key to user (only time they'll see it)
            createdKey = apiKey;
            showCreatedKey = true;

            // Refresh the list
            await loadApiKeys();

            // Reset form
            newKeyName = '';
            showCreateForm = false;
        } catch (err: any) {
            error = err.message || 'Failed to create API key';
        } finally {
            creatingKey = false;
        }
    }

    async function deleteApiKey(keyId: string, keyName: string) {
        if (!confirm(`Are you sure you want to delete the API key "${keyName}"? This action cannot be undone.`)) {
            return;
        }

        try {
            const response = await fetch(getApiEndpoint(`/v1/settings/api-keys/${keyId}`), {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                credentials: 'include' // Include cookies for authentication
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Failed to delete API key');
            }

            await loadApiKeys();
        } catch (err: any) {
            console.error('Error deleting API key:', err);
            error = err.message || 'Failed to delete API key';
        }
    }

    function copyToClipboard(text: string) {
        navigator.clipboard.writeText(text);
        // Could add a toast notification here
    }

    function formatDate(dateString: string) {
        return new Date(dateString).toLocaleDateString();
    }
</script>

<div class="api-keys-container">
    <div class="header">
        <h2 class="title">{$text('settings.developers_api_keys')}</h2>
        <p class="description">{$text('settings.developers_api_keys_description')}</p>

        <button
            class="btn-create"
            onclick={() => showCreateForm = true}
            disabled={apiKeys.length >= 5}
        >
            + Create New API Key
        </button>
    </div>

    {#if error}
        <div class="error-message">{error}</div>
    {/if}

    {#if loading}
        <div class="loading">Loading API keys...</div>
    {:else if apiKeys.length === 0}
        <div class="empty-state">
            <div class="empty-icon">🔑</div>
            <h3>No API Keys</h3>
            <p>Create your first API key to access OpenMates programmatically.</p>
        </div>
    {:else}
        <div class="api-keys-list">
            {#each apiKeys as key (key.id)}
                <div class="api-key-item">
                    <div class="key-info">
                        <h4 class="key-name">{key.name}</h4>
                        <p class="key-prefix">{key.key_prefix}</p>
                        <div class="key-meta">
                            <span>Created: {formatDate(key.created_at)}</span>
                            {#if key.last_used}
                                <span>Last used: {formatDate(key.last_used)}</span>
                            {:else}
                                <span>Never used</span>
                            {/if}
                        </div>
                    </div>
                    <div class="key-actions">
                        <button
                            class="btn-delete"
                            onclick={() => deleteApiKey(key.id, key.name)}
                        >
                            Delete
                        </button>
                    </div>
                </div>
            {/each}
        </div>
    {/if}

    {#if apiKeys.length >= 5}
        <div class="limit-warning">
            You've reached the maximum number of API keys (5). Delete an existing key to create a new one.
        </div>
    {/if}
</div>

<!-- Create API Key Modal -->
{#if showCreateForm}
    <div 
        class="modal-overlay" 
        role="button"
        tabindex="0"
        onclick={() => showCreateForm = false}
        onkeydown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                showCreateForm = false;
            }
        }}
    >
        <div 
            class="modal" 
            role="presentation"
            onclick={(e) => e.stopPropagation()}
            onkeydown={(e) => e.stopPropagation()}
        >
            <h3>Create New API Key</h3>
            <p>Choose a name for your API key to help you remember what it's for.</p>

            <input
                type="text"
                placeholder="e.g., My App Integration"
                bind:value={newKeyName}
                maxlength={100}
                class="name-input"
            />

            <div class="modal-actions">
                <button
                    class="btn-cancel"
                    onclick={() => showCreateForm = false}
                    disabled={creatingKey}
                >
                    Cancel
                </button>
                <button
                    class="btn-create-confirm"
                    onclick={createApiKey}
                    disabled={creatingKey || !newKeyName.trim()}
                >
                    {creatingKey ? 'Creating...' : 'Create API Key'}
                </button>
            </div>
        </div>
    </div>
{/if}

<!-- Show Created Key Modal -->
{#if showCreatedKey}
    <div 
        class="modal-overlay" 
        role="button"
        tabindex="0"
        onclick={() => showCreatedKey = false}
        onkeydown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                showCreatedKey = false;
            }
        }}
    >
        <div 
            class="modal" 
            role="presentation"
            onclick={(e) => e.stopPropagation()}
            onkeydown={(e) => e.stopPropagation()}
        >
            <h3>API Key Created</h3>
            <p><strong>Important:</strong> Copy this API key now. You won't be able to see it again!</p>

            <div class="created-key-container">
                <code class="created-key">{createdKey}</code>
                <button
                    class="btn-copy"
                    onclick={() => copyToClipboard(createdKey)}
                >
                    Copy
                </button>
            </div>

            <div class="modal-actions">
                <button
                    class="btn-done"
                    onclick={() => showCreatedKey = false}
                >
                    I've copied the key
                </button>
            </div>
        </div>
    </div>
{/if}

<style>
    .api-keys-container {
        padding: 20px;
    }

    .header {
        margin-bottom: 24px;
    }

    .title {
        font-size: 24px;
        font-weight: 600;
        margin-bottom: 8px;
        color: var(--text-primary);
    }

    .description {
        font-size: 14px;
        color: var(--text-secondary);
        margin-bottom: 16px;
        line-height: 1.5;
    }

    .btn-create {
        background: var(--accent-color);
        color: white;
        border: none;
        border-radius: 6px;
        padding: 8px 16px;
        font-size: 14px;
        cursor: pointer;
        transition: background-color 0.2s;
    }

    .btn-create:hover:not(:disabled) {
        background: var(--accent-color-hover);
    }

    .btn-create:disabled {
        background: var(--border-color);
        cursor: not-allowed;
    }

    .error-message {
        background: #fef2f2;
        border: 1px solid #fecaca;
        color: #dc2626;
        padding: 12px;
        border-radius: 6px;
        margin-bottom: 16px;
        font-size: 14px;
    }

    .loading {
        text-align: center;
        padding: 40px;
        color: var(--text-secondary);
    }

    .empty-state {
        text-align: center;
        padding: 40px;
        color: var(--text-secondary);
    }

    .empty-icon {
        font-size: 48px;
        margin-bottom: 16px;
    }

    .empty-state h3 {
        margin-bottom: 8px;
        color: var(--text-primary);
    }

    .api-keys-list {
        display: flex;
        flex-direction: column;
        gap: 12px;
    }

    .api-key-item {
        border: 1px solid var(--border-color);
        border-radius: 8px;
        padding: 16px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: var(--bg-secondary);
    }

    .key-info {
        flex: 1;
    }

    .key-name {
        font-size: 16px;
        font-weight: 500;
        margin-bottom: 4px;
        color: var(--text-primary);
    }

    .key-prefix {
        font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
        font-size: 13px;
        color: var(--text-secondary);
        margin-bottom: 8px;
    }

    .key-meta {
        display: flex;
        gap: 16px;
        font-size: 12px;
        color: var(--text-tertiary);
    }

    .btn-delete {
        background: #dc2626;
        color: white;
        border: none;
        border-radius: 4px;
        padding: 6px 12px;
        font-size: 12px;
        cursor: pointer;
        transition: background-color 0.2s;
    }

    .btn-delete:hover {
        background: #b91c1c;
    }

    .limit-warning {
        background: #fef3cd;
        border: 1px solid #f59e0b;
        color: #92400e;
        padding: 12px;
        border-radius: 6px;
        margin-top: 16px;
        font-size: 14px;
    }

    /* Modal Styles */
    .modal-overlay {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.5);
        display: flex;
        justify-content: center;
        align-items: center;
        z-index: 1000;
    }

    .modal {
        background: var(--bg-primary);
        border-radius: 8px;
        padding: 24px;
        max-width: 500px;
        width: 90%;
        box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1);
    }

    .modal h3 {
        margin-bottom: 8px;
        color: var(--text-primary);
    }

    .modal p {
        margin-bottom: 16px;
        color: var(--text-secondary);
        font-size: 14px;
        line-height: 1.5;
    }

    .name-input {
        width: 100%;
        padding: 12px;
        border: 1px solid var(--border-color);
        border-radius: 6px;
        font-size: 14px;
        margin-bottom: 20px;
        background: var(--bg-secondary);
        color: var(--text-primary);
    }

    .name-input:focus {
        outline: none;
        border-color: var(--accent-color);
    }

    .modal-actions {
        display: flex;
        gap: 12px;
        justify-content: flex-end;
    }

    .btn-cancel, .btn-create-confirm, .btn-done {
        padding: 8px 16px;
        border-radius: 6px;
        border: none;
        font-size: 14px;
        cursor: pointer;
        transition: background-color 0.2s;
    }

    .btn-cancel {
        background: var(--bg-secondary);
        color: var(--text-primary);
        border: 1px solid var(--border-color);
    }

    .btn-cancel:hover:not(:disabled) {
        background: var(--border-color);
    }

    .btn-create-confirm, .btn-done {
        background: var(--accent-color);
        color: white;
    }

    .btn-create-confirm:hover:not(:disabled), .btn-done:hover {
        background: var(--accent-color-hover);
    }

    .btn-create-confirm:disabled {
        background: var(--border-color);
        cursor: not-allowed;
    }

    .created-key-container {
        display: flex;
        gap: 8px;
        margin-bottom: 20px;
    }

    .created-key {
        flex: 1;
        padding: 12px;
        background: var(--bg-secondary);
        border: 1px solid var(--border-color);
        border-radius: 6px;
        font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
        font-size: 13px;
        word-break: break-all;
        line-height: 1.4;
    }

    .btn-copy {
        padding: 12px 16px;
        background: var(--accent-color);
        color: white;
        border: none;
        border-radius: 6px;
        cursor: pointer;
        font-size: 14px;
        transition: background-color 0.2s;
    }

    .btn-copy:hover {
        background: var(--accent-color-hover);
    }
</style>