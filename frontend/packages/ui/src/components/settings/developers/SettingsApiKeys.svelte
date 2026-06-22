<script lang="ts">
    import { onMount, createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { getApiEndpoint } from '../../../config/api';
    import SettingsInput from '../elements/SettingsInput.svelte';
    import {
        encryptWithMasterKeyDirect,
        decryptWithMasterKey,
        deriveKeyFromApiKey,
        encryptKey,
        getKeyFromStorage,
        uint8ArrayToBase64,
    } from '../../../services/cryptoService';
    import { copyToClipboard as clipboardCopy } from '../../../utils/clipboardUtils';
    import { focusTrap } from '../../../actions/focusTrap';

    const _dispatch = createEventDispatcher();

    interface ApiKey {
        id: string;
        name: string;
        key_prefix: string;
        created_at: string | null;
        last_used: string | null;
        encrypted_name?: string;
        encrypted_key_prefix?: string;
        full_access?: boolean;
        scopes?: Record<string, unknown>;
        credit_limit?: { period: string; credits: number } | null;
    }

    type CreateStep = 'scope' | 'credit' | 'expiration';

    // State using Svelte 5 $state() runes
    let apiKeys = $state<ApiKey[]>([]);
    let loading = $state(true);
    let error = $state<string>('');
    let showCreateForm = $state(false);
    let newKeyName = $state('');
    let createdKey = $state('');
    let showCreatedKey = $state(false);
    let creatingKey = $state(false);
    let createStep = $state<CreateStep>('scope');
    let fullAccess = $state(true);
    let chatCreateIncognito = $state(true);
    let chatCreateSaved = $state(true);
    let chatReadExisting = $state(true);
    let chatAppendExisting = $state(true);
    let chatDelete = $state(true);
    let chatShare = $state(true);
    let memoryRead = $state(true);
    let appsMode = $state<'all' | 'selected'>('all');
    let allowedSkillText = $state('web:search');
    let creditPeriod = $state<'unlimited' | 'daily' | 'weekly' | 'monthly' | 'lifetime'>('unlimited');
    let creditAmount = $state('1000');
    let expirationPreset = $state<'7d' | '30d' | '90d' | '1y' | 'never'>('never');

    // Load API keys on mount
    onMount(() => {
        loadApiKeys();
    });

    async function loadApiKeys() {
        try {
            loading = true;
            error = '';
            // Keep this endpoint aligned with CLI safety gates:
            // frontend/packages/openmates-cli/src/client.ts (BLOCKED_SETTINGS_POST_PATHS)
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
                rawKeys.map(async (key: Record<string, unknown>) => {
                    let decryptedName = (key.encrypted_name as string) || '';
                    let decryptedPrefix = (key.encrypted_key_prefix as string) || '';
                    const lastUsed = (key.last_used_at as string) || null;
                    
                    try {
                        if (key.encrypted_name) {
                            const decrypted = await decryptWithMasterKey(key.encrypted_name as string);
                            if (decrypted) {
                                decryptedName = decrypted;
                            }
                        }
                        if (key.encrypted_key_prefix) {
                            const decrypted = await decryptWithMasterKey(key.encrypted_key_prefix as string);
                            if (decrypted) {
                                decryptedPrefix = decrypted;
                            }
                        }
                    } catch (err) {
                        console.error('Error decrypting API key fields:', err);
                        // Keep encrypted values if decryption fails
                    }

                    return {
                        id: key.id as string,
                        created_at: (key.created_at as string) || null,
                        name: decryptedName,
                        key_prefix: decryptedPrefix,
                        last_used: lastUsed,
                        full_access: (key.full_access as boolean | undefined) ?? true,
                        scopes: (key.scopes as Record<string, unknown>) || {},
                        credit_limit: (key.credit_limit as ApiKey['credit_limit']) || null,
                    } satisfies ApiKey;
                })
            );
        } catch (err: unknown) {
            console.error('Error loading API keys:', err);
            error = (err instanceof Error ? err.message : null) || 'Failed to load API keys';
        } finally {
            loading = false;
        }
    }

    function generateApiKey(): string {
        // Generate a secure API key: sk-api-[32 random chars]
        const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
        let result = 'sk-api-';
        const maxUnbiasedValue = Math.floor(256 / chars.length) * chars.length;
        while (result.length < 'sk-api-'.length + 32) {
            const randomValues = crypto.getRandomValues(new Uint8Array(32));
            for (const value of randomValues) {
                if (value >= maxUnbiasedValue) continue;
                result += chars.charAt(value % chars.length);
                if (result.length >= 'sk-api-'.length + 32) break;
            }
        }
        return result;
    }

    function buildScopes() {
        return {
            chat: [
                chatCreateIncognito ? 'chat:create_incognito' : null,
                chatCreateSaved ? 'chat:create_saved' : null,
                chatReadExisting ? 'chat:read_existing' : null,
                chatAppendExisting ? 'chat:append_existing' : null,
                chatDelete ? 'chat:delete' : null,
                chatShare ? 'chat:share' : null,
            ].filter(Boolean),
            memories: memoryRead ? ['memory:read'] : [],
            apps: {
                mode: appsMode,
                allowed_skills: appsMode === 'selected'
                    ? allowedSkillText.split(',').map((item) => item.trim()).filter(Boolean)
                    : [],
                allowed_apps: [],
            },
        };
    }

    function buildCreditLimit() {
        if (creditPeriod === 'unlimited') return null;
        return { period: creditPeriod, credits: Math.max(1, Math.floor(Number(creditAmount) || 1)) };
    }

    function buildExpiresAt() {
        if (expirationPreset === 'never') return null;
        const daysByPreset = { '7d': 7, '30d': 30, '90d': 90, '1y': 365 } as const;
        const expires = new Date();
        expires.setDate(expires.getDate() + daysByPreset[expirationPreset]);
        return expires.toISOString();
    }

    function closeCreateForm() {
        showCreateForm = false;
        createStep = 'scope';
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
                    key_iv: keyIv,
                    full_access: fullAccess,
                    scopes: buildScopes(),
                    credit_limit: buildCreditLimit(),
                    expires_at: buildExpiresAt(),
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
            closeCreateForm();
        } catch (err: unknown) {
            error = (err instanceof Error ? err.message : null) || 'Failed to create API key';
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
        } catch (err: unknown) {
            console.error('Error deleting API key:', err);
            error = (err instanceof Error ? err.message : null) || 'Failed to delete API key';
        }
    }

    async function copyToClipboard(text: string) {
        const result = await clipboardCopy(text);
        if (!result.success) {
            console.error('[SettingsApiKeys] Failed to copy to clipboard:', result.error);
        }
    }

    function formatDate(dateString: string | null | undefined) {
        if (!dateString) return 'Unknown';
        return new Date(dateString).toLocaleDateString();
    }

    function describeCreditLimit(key: ApiKey) {
        if (!key.credit_limit) return 'Unlimited credits';
        return `${key.credit_limit.credits} credits / ${key.credit_limit.period}`;
    }
</script>

<div class="api-keys-container" data-testid="api-keys-container">
    <div class="header">
        <h2 class="title">{$text('settings.developers_api_keys')}</h2>
        <p class="description">{$text('settings.developers_api_keys_description')}</p>

        <button
            class="btn-create"
            data-testid="api-key-create-button"
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
                <div class="api-key-item" data-testid="api-key-item">
                    <div class="key-info">
                        <h4 class="key-name" data-testid="api-key-name">{key.name}</h4>
                        <p class="key-prefix">{key.key_prefix}</p>
                        <div class="key-meta">
                            <span>Created: {formatDate(key.created_at)}</span>
                            <span>{key.full_access ? 'Full access' : 'Restricted'}</span>
                            <span>{describeCreditLimit(key)}</span>
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
                            data-testid="api-key-delete-button"
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
        <div class="limit-warning" data-testid="api-key-limit-warning">
            You've reached the maximum number of API keys (5). Delete an existing key to create a new one.
        </div>
    {/if}
</div>

<!-- Create API Key Modal -->
{#if showCreateForm}
    <div
        class="modal-overlay"
        role="presentation"
        onmousedown={(e) => { if (e.target === e.currentTarget) showCreateForm = false; }}
    >
        <div
            class="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="apikey-create-title"
            tabindex="-1"
            use:focusTrap={{ onEscape: closeCreateForm }}
            onmousedown={(e) => e.stopPropagation()}
        >
            <h3 id="apikey-create-title">Create New API Key</h3>

            {#if createStep === 'scope'}
                <p>Scope controls what this key can do. Full access is convenient but can read and create account data.</p>
                <SettingsInput
                    type="text"
                    placeholder="e.g., My App Integration"
                    bind:value={newKeyName}
                    maxlength={100}
                    dataTestid="api-key-name-input"
                />

                <label class="scope-toggle">
                    <input type="checkbox" bind:checked={fullAccess} data-testid="api-key-full-access-toggle" />
                    <span>Full access to supported API-key actions</span>
                </label>
                {#if fullAccess}
                    <div class="warning-box" data-testid="api-key-full-access-warning">
                        Full access can read encrypted account metadata, create chats, run app skills, and spend account credits.
                    </div>
                {:else}
                    <div class="scope-grid" data-testid="api-key-scope-options">
                        <label><input type="checkbox" bind:checked={chatCreateIncognito} /> Create non-persistent chats</label>
                        <label><input type="checkbox" bind:checked={chatCreateSaved} /> Create saved chats</label>
                        <label><input type="checkbox" bind:checked={chatReadExisting} /> Read existing chats</label>
                        <label><input type="checkbox" bind:checked={chatAppendExisting} /> Append existing chats</label>
                        <label><input type="checkbox" bind:checked={chatDelete} /> Delete chats</label>
                        <label><input type="checkbox" bind:checked={chatShare} /> Share chats</label>
                        <label><input type="checkbox" bind:checked={memoryRead} /> Read selected memories</label>
                    </div>
                    <details class="scope-details" open>
                        <summary>App skill access</summary>
                        <label class="scope-toggle">
                            <input type="radio" bind:group={appsMode} value="all" />
                            <span>All app skills</span>
                        </label>
                        <label class="scope-toggle">
                            <input type="radio" bind:group={appsMode} value="selected" />
                            <span>Selected app skills</span>
                        </label>
                        {#if appsMode === 'selected'}
                            <SettingsInput
                                type="text"
                                placeholder="web:search, images:generate"
                                bind:value={allowedSkillText}
                                dataTestid="api-key-allowed-skills-input"
                            />
                        {/if}
                    </details>
                {/if}
            {:else if createStep === 'credit'}
                <p>Set one optional credit cap for this key. Unlimited is the default.</p>
                <div class="radio-list" data-testid="api-key-credit-step">
                    <label><input type="radio" bind:group={creditPeriod} value="unlimited" /> Unlimited</label>
                    <label><input type="radio" bind:group={creditPeriod} value="daily" /> Daily</label>
                    <label><input type="radio" bind:group={creditPeriod} value="weekly" /> Weekly</label>
                    <label><input type="radio" bind:group={creditPeriod} value="monthly" /> Monthly</label>
                    <label><input type="radio" bind:group={creditPeriod} value="lifetime" /> Lifetime</label>
                </div>
                {#if creditPeriod === 'unlimited'}
                    <div class="warning-box" data-testid="api-key-credit-warning">
                        This key can spend account credits without a per-key cap.
                    </div>
                {:else}
                    <SettingsInput
                        type="number"
                        placeholder="Credit cap"
                        bind:value={creditAmount}
                        min="1"
                        dataTestid="api-key-credit-amount-input"
                    />
                {/if}
            {:else}
                <p>Choose when this key expires. Never is the default, but rotating keys is safer.</p>
                <div class="radio-list" data-testid="api-key-expiration-step">
                    <label><input type="radio" bind:group={expirationPreset} value="7d" /> 7 days</label>
                    <label><input type="radio" bind:group={expirationPreset} value="30d" /> 30 days</label>
                    <label><input type="radio" bind:group={expirationPreset} value="90d" /> 90 days</label>
                    <label><input type="radio" bind:group={expirationPreset} value="1y" /> 1 year</label>
                    <label><input type="radio" bind:group={expirationPreset} value="never" /> Never</label>
                </div>
                {#if expirationPreset === 'never'}
                    <div class="warning-box" data-testid="api-key-expiration-warning">
                        This key never expires. Delete it immediately if it is leaked.
                    </div>
                {/if}
            {/if}

            <div class="modal-actions">
                <button
                    class="btn-cancel"
                    data-testid="api-key-cancel-button"
                    onclick={closeCreateForm}
                    disabled={creatingKey}
                >
                    Cancel
                </button>
                {#if createStep !== 'scope'}
                    <button
                        class="btn-cancel"
                        data-testid="api-key-back-button"
                        onclick={() => createStep = createStep === 'expiration' ? 'credit' : 'scope'}
                        disabled={creatingKey}
                    >
                        Back
                    </button>
                {/if}
                <button
                    class="btn-create-confirm"
                    data-testid="api-key-create-confirm"
                    onclick={() => {
                        if (createStep === 'scope') createStep = 'credit';
                        else if (createStep === 'credit') createStep = 'expiration';
                        else createApiKey();
                    }}
                    disabled={creatingKey || !newKeyName.trim()}
                >
                    {creatingKey ? 'Creating...' : createStep === 'expiration' ? 'Create API Key' : 'Continue'}
                </button>
            </div>
        </div>
    </div>
{/if}

<!-- Show Created Key Modal -->
{#if showCreatedKey}
    <div
        class="modal-overlay"
        role="presentation"
        onmousedown={(e) => { if (e.target === e.currentTarget) showCreatedKey = false; }}
    >
        <div
            class="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="apikey-created-title"
            tabindex="-1"
            use:focusTrap={{ onEscape: () => showCreatedKey = false }}
            onmousedown={(e) => e.stopPropagation()}
        >
            <h3 id="apikey-created-title">API Key Created</h3>
            <p><strong>Important:</strong> Copy this API key now. You won't be able to see it again!</p>

            <div class="created-key-container">
                <code class="created-key" data-testid="api-key-created-value">{createdKey}</code>
                <button
                    class="btn-copy"
                    data-testid="api-key-copy-button"
                    onclick={() => copyToClipboard(createdKey)}
                >
                    Copy
                </button>
            </div>

            <div class="modal-actions">
                <button
                    class="btn-done"
                    data-testid="api-key-done-button"
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
        padding: var(--spacing-10);
    }

    .header {
        margin-bottom: var(--spacing-12);
    }

    .title {
        font-size: var(--font-size-h2-mobile);
        font-weight: 600;
        margin-bottom: var(--spacing-4);
        color: var(--text-primary);
    }

    .description {
        font-size: var(--font-size-small);
        color: var(--text-secondary);
        margin-bottom: var(--spacing-8);
        line-height: 1.5;
    }

    .btn-create {
        background: var(--accent-color);
        color: white;
        border: none;
        border-radius: var(--radius-2);
        padding: var(--spacing-4) var(--spacing-8);
        font-size: var(--font-size-small);
        cursor: pointer;
        transition: background-color var(--duration-normal);
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
        padding: var(--spacing-6);
        border-radius: var(--radius-2);
        margin-bottom: var(--spacing-8);
        font-size: var(--font-size-small);
    }

    .loading {
        text-align: center;
        padding: var(--spacing-20);
        color: var(--text-secondary);
    }

    .empty-state {
        text-align: center;
        padding: var(--spacing-20);
        color: var(--text-secondary);
    }

    .empty-icon {
        font-size: var(--font-size-hero);
        margin-bottom: var(--spacing-8);
    }

    .empty-state h3 {
        margin-bottom: var(--spacing-4);
        color: var(--text-primary);
    }

    .api-keys-list {
        display: flex;
        flex-direction: column;
        gap: var(--spacing-6);
    }

    .api-key-item {
        border: 1px solid var(--border-color);
        border-radius: var(--radius-3);
        padding: var(--spacing-8);
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: var(--bg-secondary);
    }

    .key-info {
        flex: 1;
    }

    .key-name {
        font-size: var(--font-size-p);
        font-weight: 500;
        margin-bottom: var(--spacing-2);
        color: var(--text-primary);
    }

    .key-prefix {
        font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
        font-size: var(--font-size-xs);
        color: var(--text-secondary);
        margin-bottom: var(--spacing-4);
    }

    .key-meta {
        display: flex;
        gap: var(--spacing-8);
        font-size: var(--font-size-xxs);
        color: var(--text-tertiary);
    }

    .btn-delete {
        background: #dc2626;
        color: white;
        border: none;
        border-radius: var(--radius-1);
        padding: var(--spacing-3) var(--spacing-6);
        font-size: var(--font-size-xxs);
        cursor: pointer;
        transition: background-color var(--duration-normal);
    }

    .btn-delete:hover {
        background: #b91c1c;
    }

    .limit-warning {
        background: #fef3cd;
        border: 1px solid #f59e0b;
        color: #92400e;
        padding: var(--spacing-6);
        border-radius: var(--radius-2);
        margin-top: var(--spacing-8);
        font-size: var(--font-size-small);
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
        z-index: var(--z-index-modal);
    }

    .modal {
        background: var(--bg-primary);
        border-radius: var(--radius-3);
        padding: var(--spacing-12);
        max-width: 620px;
        width: 90%;
        max-height: 90vh;
        overflow: auto;
        box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1);
    }

    .modal h3 {
        margin-bottom: var(--spacing-4);
        color: var(--text-primary);
    }

    .modal p {
        margin-bottom: var(--spacing-8);
        color: var(--text-secondary);
        font-size: var(--font-size-small);
        line-height: 1.5;
    }

    .modal-actions {
        display: flex;
        gap: var(--spacing-6);
        justify-content: flex-end;
        margin-top: var(--spacing-8);
    }

    .scope-toggle,
    .scope-grid label,
    .radio-list label {
        display: flex;
        align-items: center;
        gap: var(--spacing-4);
        color: var(--text-primary);
        font-size: var(--font-size-small);
    }

    .scope-toggle {
        margin: var(--spacing-6) 0;
    }

    .scope-grid,
    .radio-list {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: var(--spacing-4);
        margin: var(--spacing-6) 0;
    }

    .scope-details {
        border: 1px solid var(--border-color);
        border-radius: var(--radius-2);
        padding: var(--spacing-6);
        margin-top: var(--spacing-6);
    }

    .scope-details summary {
        cursor: pointer;
        color: var(--text-primary);
        font-weight: 600;
    }

    .warning-box {
        background: #fef3cd;
        border: 1px solid #f59e0b;
        color: #92400e;
        padding: var(--spacing-6);
        border-radius: var(--radius-2);
        margin: var(--spacing-6) 0;
        font-size: var(--font-size-small);
        line-height: 1.4;
    }

    .btn-cancel, .btn-create-confirm, .btn-done {
        padding: var(--spacing-4) var(--spacing-8);
        border-radius: var(--radius-2);
        border: none;
        font-size: var(--font-size-small);
        cursor: pointer;
        transition: background-color var(--duration-normal);
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
        gap: var(--spacing-4);
        margin-bottom: var(--spacing-10);
    }

    .created-key {
        flex: 1;
        padding: var(--spacing-6);
        background: var(--bg-secondary);
        border: 1px solid var(--border-color);
        border-radius: var(--radius-2);
        font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
        font-size: var(--font-size-xs);
        word-break: break-all;
        line-height: 1.4;
    }

    .btn-copy {
        padding: var(--spacing-6) var(--spacing-8);
        background: var(--accent-color);
        color: white;
        border: none;
        border-radius: var(--radius-2);
        cursor: pointer;
        font-size: var(--font-size-small);
        transition: background-color var(--duration-normal);
    }

    .btn-copy:hover {
        background: var(--accent-color-hover);
    }
</style>
