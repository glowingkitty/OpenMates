<!--
  SettingsWebhooks — Webhook key management for incoming webhooks.

  Allows users to create/delete webhook keys that let external services
  (e.g., GitHub Actions CI) trigger new chats via POST /v1/webhooks/incoming.

  Architecture: docs/architecture/webhooks.md
  Pattern mirrors: SettingsApiKeys.svelte (same zero-knowledge encryption flow)

  Key differences from API keys:
  - Simpler payload (no device approval, no master key wrapping)
  - Additional `require_confirmation` toggle
  - Key prefix starts with "wh-" not "sk-api-"
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { text } from '@repo/ui';
  import { getApiEndpoint, getApiUrl } from '../../../config/api';
  import SettingsInput from '../elements/SettingsInput.svelte';
  import SettingsItem from '../../SettingsItem.svelte';
  import {
    encryptWithMasterKeyDirect,
    decryptWithMasterKey,
    getKeyFromStorage,
  } from '../../../services/cryptoService';
  import { copyToClipboard as clipboardCopy } from '../../../utils/clipboardUtils';

  interface WebhookKey {
    id: string;
    name: string;
    key_prefix: string;
    direction: string;
    permissions: string[];
    require_confirmation: boolean;
    is_active: boolean;
    created_at: string | null;
    last_used_at: string | null;
  }

  const MAX_WEBHOOKS = 10;
  const WEBHOOK_KEY_PREFIX = 'wh-';

  // State
  let webhooks = $state<WebhookKey[]>([]);
  let loading = $state(true);
  let error = $state('');
  let showCreateForm = $state(false);
  let newKeyName = $state('');
  let requireConfirmation = $state(false);
  let createdKey = $state('');
  let showCreatedKey = $state(false);
  let creating = $state(false);

  onMount(() => { loadWebhooks(); });

  async function loadWebhooks() {
    try {
      loading = true;
      error = '';
      const response = await fetch(getApiEndpoint('/v1/webhooks'), {
        method: 'GET',
        credentials: 'include',
        headers: { Accept: 'application/json' },
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to load webhooks');
      }

      const data = await response.json();
      const raw = data.webhooks || [];

      const masterKey = await getKeyFromStorage();
      if (!masterKey) throw new Error('Master key not found. Please log in again.');

      webhooks = await Promise.all(
        raw.map(async (wh: Record<string, unknown>) => {
          let name = (wh.encrypted_name as string) || '';
          let prefix = (wh.encrypted_key_prefix as string) || '';
          try {
            if (wh.encrypted_name) name = (await decryptWithMasterKey(wh.encrypted_name as string)) || name;
            if (wh.encrypted_key_prefix) prefix = (await decryptWithMasterKey(wh.encrypted_key_prefix as string)) || prefix;
          } catch { /* keep encrypted value if decryption fails */ }
          return {
            id: wh.id as string,
            name,
            key_prefix: prefix,
            direction: (wh.direction as string) || 'incoming',
            permissions: (wh.permissions as string[]) || [],
            require_confirmation: !!(wh.require_confirmation),
            is_active: wh.is_active !== false,
            created_at: (wh.created_at as string) || null,
            last_used_at: (wh.last_used_at as string) || null,
          } satisfies WebhookKey;
        })
      );
    } catch (err: unknown) {
      error = (err instanceof Error ? err.message : null) || 'Failed to load webhooks';
    } finally {
      loading = false;
    }
  }

  function generateWebhookKey(): string {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    let result = WEBHOOK_KEY_PREFIX;
    for (let i = 0; i < 64; i++) result += chars[Math.floor(Math.random() * chars.length)];
    return result;
  }

  async function hashKey(key: string): Promise<string> {
    const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(key));
    return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
  }

  async function createWebhook() {
    if (!newKeyName.trim()) { error = 'Webhook name is required'; return; }

    try {
      creating = true;
      error = '';

      const masterKey = await getKeyFromStorage();
      if (!masterKey) throw new Error('Master key not found. Please log in again.');

      const rawKey = generateWebhookKey();
      const keyHash = await hashKey(rawKey);
      const keyPrefix = rawKey.substring(0, 12) + '...';

      const encryptedName = await encryptWithMasterKeyDirect(newKeyName.trim(), masterKey);
      const encryptedKeyPrefix = await encryptWithMasterKeyDirect(keyPrefix, masterKey);

      if (!encryptedName || !encryptedKeyPrefix) throw new Error('Failed to encrypt webhook data');

      const response = await fetch(getApiEndpoint('/v1/webhooks'), {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          encrypted_name: encryptedName,
          webhook_key_hash: keyHash,
          encrypted_key_prefix: encryptedKeyPrefix,
          direction: 'incoming',
          permissions: ['trigger_chat'],
          require_confirmation: requireConfirmation,
        }),
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to create webhook');
      }

      createdKey = rawKey;
      showCreatedKey = true;
      await loadWebhooks();
      newKeyName = '';
      requireConfirmation = false;
      showCreateForm = false;
    } catch (err: unknown) {
      error = (err instanceof Error ? err.message : null) || 'Failed to create webhook';
    } finally {
      creating = false;
    }
  }

  async function deleteWebhook(id: string, name: string) {
    if (!confirm($text('settings.developers_webhooks_delete_confirm'))) return;
    try {
      const response = await fetch(getApiEndpoint(`/v1/webhooks/${id}`), {
        method: 'DELETE',
        credentials: 'include',
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to delete webhook');
      }
      await loadWebhooks();
    } catch (err: unknown) {
      error = (err instanceof Error ? err.message : null) || 'Failed to delete webhook';
    }
  }

  async function copyToClipboard(value: string) {
    const result = await clipboardCopy(value);
    if (!result.success) console.error('[SettingsWebhooks] clipboard copy failed:', result.error);
  }

  function formatDate(ds: string | null | undefined) {
    if (!ds) return '—';
    return new Date(ds).toLocaleDateString();
  }

  // Derive the public endpoint URL from the API base
  let endpointUrl = $derived(`${getApiUrl()}/v1/webhooks/incoming`);
</script>

<div class="webhooks-container" data-testid="webhooks-container">
  <div class="header">
    <h2 class="title">{$text('settings.developers_webhooks')}</h2>
    <p class="description">{$text('settings.developers_webhooks_description')}</p>

    <button
      class="btn-create"
      data-testid="webhook-create-button"
      onclick={() => { showCreateForm = true; error = ''; }}
      disabled={webhooks.length >= MAX_WEBHOOKS}
    >
      + {$text('settings.developers_webhooks_create')}
    </button>
  </div>

  <!-- Endpoint reference -->
  <div class="endpoint-box">
    <span class="endpoint-label">{$text('settings.developers_webhooks_endpoint')}</span>
    <code class="endpoint-url">{endpointUrl}</code>
    <button class="btn-copy-small" onclick={() => copyToClipboard(endpointUrl)}>
      Copy
    </button>
  </div>

  {#if error}
    <div class="error-message">{error}</div>
  {/if}

  {#if loading}
    <div class="loading">Loading webhooks...</div>
  {:else if webhooks.length === 0}
    <div class="empty-state" data-testid="webhooks-empty-state">
      <div class="empty-icon">🔗</div>
      <p>{$text('settings.developers_webhooks_empty')}</p>
    </div>
  {:else}
    <div class="webhook-list">
      {#each webhooks as wh (wh.id)}
        <div class="webhook-item" data-testid="webhook-item">
          <div class="wh-info">
            <div class="wh-name-row">
              <h4 class="wh-name" data-testid="webhook-name">{wh.name}</h4>
              {#if !wh.is_active}
                <span class="badge inactive">{$text('settings.developers_webhooks_inactive_badge')}</span>
              {/if}
              {#if wh.require_confirmation}
                <span class="badge confirmation">Approval required</span>
              {/if}
            </div>
            <p class="wh-prefix">{wh.key_prefix}</p>
            <div class="wh-meta">
              <span>Created: {formatDate(wh.created_at)}</span>
              {#if wh.last_used_at}
                <span>Last used: {formatDate(wh.last_used_at)}</span>
              {:else}
                <span>Never used</span>
              {/if}
            </div>
          </div>
          <div class="wh-actions">
            <button
              class="btn-delete"
              data-testid="webhook-delete-button"
              onclick={() => deleteWebhook(wh.id, wh.name)}
            >
              Delete
            </button>
          </div>
        </div>
      {/each}
    </div>
  {/if}

  {#if webhooks.length >= MAX_WEBHOOKS}
    <div class="limit-warning">{$text('settings.developers_webhooks_limit')}</div>
  {/if}
</div>

<!-- Create Webhook Modal -->
{#if showCreateForm}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div
    class="modal-overlay"
    role="button"
    tabindex="0"
    onclick={() => showCreateForm = false}
    onkeydown={(e) => { if (e.key === 'Escape') showCreateForm = false; }}
  >
    <div
      class="modal"
      role="presentation"
      onclick={(e) => e.stopPropagation()}
      onkeydown={(e) => e.stopPropagation()}
    >
      <h3>{$text('settings.developers_webhooks_create')}</h3>
      <p style="color: var(--color-font-secondary); font-size: var(--font-size-p); margin-bottom: 1rem;">
        {$text('settings.developers_webhooks_description')}
      </p>

      <SettingsInput
        type="text"
        placeholder={$text('settings.developers_webhooks_name_placeholder')}
        bind:value={newKeyName}
        maxlength={100}
        dataTestid="webhook-name-input"
      />

      <!-- Require confirmation toggle -->
      <div class="confirmation-toggle">
        <SettingsItem
          icon="subsetting_icon shield"
          type="submenu"
          title={$text('settings.developers_webhooks_require_confirmation')}
          subtitleTop={$text('settings.developers_webhooks_require_confirmation_desc')}
          hasToggle={true}
          checked={requireConfirmation}
          onClick={() => { requireConfirmation = !requireConfirmation; }}
        />
      </div>

      <div class="modal-actions">
        <button class="btn-cancel" onclick={() => showCreateForm = false} disabled={creating}>
          Cancel
        </button>
        <button
          class="btn-confirm"
          data-testid="webhook-create-confirm-button"
          onclick={createWebhook}
          disabled={creating || !newKeyName.trim()}
        >
          {creating ? 'Creating...' : $text('settings.developers_webhooks_create')}
        </button>
      </div>
    </div>
  </div>
{/if}

<!-- Show Created Key Modal -->
{#if showCreatedKey}
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div
    class="modal-overlay"
    role="button"
    tabindex="0"
    onclick={() => showCreatedKey = false}
    onkeydown={(e) => { if (e.key === 'Escape') showCreatedKey = false; }}
  >
    <div
      class="modal"
      role="presentation"
      onclick={(e) => e.stopPropagation()}
      onkeydown={(e) => e.stopPropagation()}
    >
      <h3>{$text('settings.developers_webhooks_created_title')}</h3>
      <p class="warning-text">{$text('settings.developers_webhooks_created_warning')}</p>

      <div class="created-key-container">
        <code class="created-key" data-testid="webhook-created-value">{createdKey}</code>
        <button class="btn-copy" onclick={() => copyToClipboard(createdKey)}>Copy</button>
      </div>

      <div class="how-to-use">
        <h4>{$text('settings.developers_webhooks_how_to_use')}</h4>
        <pre class="code-example">curl -X POST {endpointUrl} \
  -H "Authorization: Bearer {createdKey.substring(0, 18)}..." \
  -H "Content-Type: application/json" \
  -d '{`{"message": "Your message here"}`}'</pre>
      </div>

      <div class="modal-actions">
        <button class="btn-done" onclick={() => showCreatedKey = false}>
          I've copied the key
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  .webhooks-container { padding: 1.25rem; }

  .header { margin-bottom: 1.5rem; }

  .title {
    font-size: var(--font-size-h3);
    font-weight: 600;
    margin-bottom: 0.5rem;
    color: var(--color-font-primary);
  }

  .description {
    font-size: var(--font-size-p);
    color: var(--color-font-secondary);
    margin-bottom: 1rem;
    line-height: 1.5;
  }

  .endpoint-box {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    background: var(--color-grey-10);
    border: 1px solid var(--color-grey-25);
    border-radius: 0.5rem;
    padding: 0.625rem 0.875rem;
    margin-bottom: 1.25rem;
    flex-wrap: wrap;
  }

  .endpoint-label {
    font-size: var(--processing-details-font-size);
    color: var(--color-font-secondary);
    flex-shrink: 0;
  }

  .endpoint-url {
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    font-size: var(--processing-details-font-size);
    color: var(--color-font-primary);
    flex: 1;
    word-break: break-all;
  }

  .btn-copy-small {
    padding: 0.25rem 0.625rem;
    border: 1px solid var(--color-grey-30);
    border-radius: 0.3rem;
    background: var(--color-grey-0);
    color: var(--color-font-secondary);
    font-size: var(--processing-details-font-size);
    cursor: pointer;
    flex-shrink: 0;
  }

  .btn-create {
    background: var(--color-primary);
    color: var(--color-grey-0);
    border: none;
    border-radius: 0.4rem;
    padding: 0.5rem 1rem;
    font-size: var(--button-font-size);
    cursor: pointer;
  }

  .btn-create:disabled { background: var(--color-grey-30); cursor: not-allowed; }

  .error-message {
    background: color-mix(in srgb, var(--color-error) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--color-error) 40%, transparent);
    color: var(--color-error);
    padding: 0.75rem;
    border-radius: 0.4rem;
    margin-bottom: 1rem;
    font-size: var(--font-size-p);
  }

  .loading, .empty-state {
    text-align: center;
    padding: 2.5rem;
    color: var(--color-font-secondary);
  }

  .empty-icon { font-size: 3rem; margin-bottom: 1rem; }

  .webhook-list { display: flex; flex-direction: column; gap: 0.75rem; }

  .webhook-item {
    border: 1px solid var(--color-grey-25);
    border-radius: 0.5rem;
    padding: 1rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    background: var(--color-grey-10);
  }

  .wh-info { flex: 1; min-width: 0; }

  .wh-name-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
    margin-bottom: 0.25rem;
  }

  .wh-name {
    font-size: var(--font-size-p);
    font-weight: 500;
    color: var(--color-font-primary);
    margin: 0;
  }

  .badge {
    font-size: var(--processing-details-font-size);
    padding: 0.125rem 0.5rem;
    border-radius: 999px;
  }

  .badge.inactive {
    background: color-mix(in srgb, var(--color-error) 15%, transparent);
    color: var(--color-error);
  }

  .badge.confirmation {
    background: color-mix(in srgb, var(--color-primary) 15%, transparent);
    color: var(--color-primary);
  }

  .wh-prefix {
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    font-size: var(--processing-details-font-size);
    color: var(--color-font-secondary);
    margin: 0 0 0.5rem;
  }

  .wh-meta {
    display: flex;
    gap: 1rem;
    font-size: var(--processing-details-font-size);
    color: var(--color-font-secondary);
  }

  .btn-delete {
    background: color-mix(in srgb, var(--color-error) 15%, transparent);
    color: var(--color-error);
    border: 1px solid color-mix(in srgb, var(--color-error) 30%, transparent);
    border-radius: 0.3rem;
    padding: 0.375rem 0.75rem;
    font-size: var(--processing-details-font-size);
    cursor: pointer;
    flex-shrink: 0;
  }

  .limit-warning {
    background: color-mix(in srgb, var(--color-warning, #f59e0b) 15%, transparent);
    border: 1px solid color-mix(in srgb, var(--color-warning, #f59e0b) 40%, transparent);
    padding: 0.75rem;
    border-radius: 0.4rem;
    margin-top: 1rem;
    font-size: var(--font-size-p);
    color: var(--color-font-primary);
  }

  /* Modal */
  .modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    justify-content: center;
    align-items: center;
    z-index: 1000;
  }

  .modal {
    background: var(--color-grey-0);
    border-radius: 0.75rem;
    padding: 1.5rem;
    max-width: 520px;
    width: 92%;
    box-shadow: 0 20px 40px rgba(0, 0, 0, 0.2);
    max-height: 90vh;
    overflow-y: auto;
  }

  .modal h3 {
    margin: 0 0 0.5rem;
    font-size: var(--font-size-h4);
    color: var(--color-font-primary);
  }

  .confirmation-toggle {
    margin: 0.75rem 0;
  }

  .modal-actions {
    display: flex;
    gap: 0.75rem;
    justify-content: flex-end;
    margin-top: 1rem;
  }

  .btn-cancel, .btn-confirm, .btn-done {
    padding: 0.5rem 1rem;
    border-radius: 0.4rem;
    border: none;
    font-size: var(--button-font-size);
    cursor: pointer;
  }

  .btn-cancel {
    background: var(--color-grey-20);
    color: var(--color-font-primary);
    border: 1px solid var(--color-grey-30);
  }

  .btn-confirm, .btn-done {
    background: var(--color-primary);
    color: var(--color-grey-0);
  }

  .btn-confirm:disabled { background: var(--color-grey-30); cursor: not-allowed; }

  .warning-text {
    color: var(--color-error);
    font-size: var(--font-size-p);
    font-weight: 500;
    margin-bottom: 1rem;
  }

  .created-key-container {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1.25rem;
  }

  .created-key {
    flex: 1;
    padding: 0.75rem;
    background: var(--color-grey-10);
    border: 1px solid var(--color-grey-25);
    border-radius: 0.4rem;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    font-size: var(--processing-details-font-size);
    word-break: break-all;
  }

  .btn-copy {
    padding: 0.75rem 1rem;
    background: var(--color-primary);
    color: var(--color-grey-0);
    border: none;
    border-radius: 0.4rem;
    cursor: pointer;
    font-size: var(--button-font-size);
    flex-shrink: 0;
  }

  .how-to-use { margin-top: 1rem; }

  .how-to-use h4 {
    font-size: var(--font-size-p);
    font-weight: 600;
    color: var(--color-font-primary);
    margin-bottom: 0.5rem;
  }

  .code-example {
    background: var(--color-grey-10);
    border: 1px solid var(--color-grey-25);
    border-radius: 0.4rem;
    padding: 0.75rem;
    font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
    font-size: var(--processing-details-font-size);
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-all;
    color: var(--color-font-secondary);
  }
</style>
