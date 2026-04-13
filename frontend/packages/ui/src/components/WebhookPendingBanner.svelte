<!--
  WebhookPendingBanner.svelte

  Renders a Process / Reject prompt above the chat history when the active
  chat is an incoming webhook that was created with `require_confirmation=true`.
  The backend held off dispatching the AI until the user confirms, so this
  component is the user-facing gate.

  Data source: activeChatPendingWebhook (pendingWebhookChatsStore), populated
  by chatSyncServiceHandlersWebhooks when a webhook_chat event arrives with
  status === "pending_confirmation".

  Architecture: docs/architecture/webhooks.md (§ "require_confirmation")
-->
<script lang="ts">
  import { activeChatPendingWebhook, pendingWebhookChatsStore } from '../stores/pendingWebhookChatsStore';
  import { getApiEndpoint } from '../config/api';

  let submitting = $state(false);
  let error = $state('');

  async function approve(chat_id: string): Promise<void> {
    try {
      submitting = true;
      error = '';
      const response = await fetch(
        getApiEndpoint(`/v1/webhooks/pending/${encodeURIComponent(chat_id)}/approve`),
        {
          method: 'POST',
          credentials: 'include',
          headers: { Accept: 'application/json' },
        }
      );
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || 'Failed to approve webhook chat');
      }
      // Optimistically clear locally — the backend will also broadcast
      // webhook_chat_approved to other devices.
      pendingWebhookChatsStore.remove(chat_id);
    } catch (err: unknown) {
      error = err instanceof Error ? err.message : 'Failed to approve webhook chat';
    } finally {
      submitting = false;
    }
  }

  async function reject(chat_id: string): Promise<void> {
    try {
      submitting = true;
      error = '';
      const response = await fetch(
        getApiEndpoint(`/v1/webhooks/pending/${encodeURIComponent(chat_id)}/reject`),
        {
          method: 'POST',
          credentials: 'include',
          headers: { Accept: 'application/json' },
        }
      );
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || 'Failed to reject webhook chat');
      }
      pendingWebhookChatsStore.remove(chat_id);
    } catch (err: unknown) {
      error = err instanceof Error ? err.message : 'Failed to reject webhook chat';
    } finally {
      submitting = false;
    }
  }
</script>

{#if $activeChatPendingWebhook}
  <div class="webhook-pending-banner" data-testid="webhook-pending-banner">
    <div class="banner-heading">
      <span class="badge">Webhook awaiting approval</span>
      <p class="banner-text">
        An external service triggered this chat. Review the message below, then
        choose whether to run the assistant on it or drop it.
      </p>
    </div>
    {#if error}
      <div class="banner-error">{error}</div>
    {/if}
    <div class="banner-actions">
      <button
        class="btn-reject"
        data-testid="webhook-reject-button"
        onclick={() => reject($activeChatPendingWebhook!.chat_id)}
        disabled={submitting}
      >
        Reject
      </button>
      <button
        class="btn-process"
        data-testid="webhook-process-button"
        onclick={() => approve($activeChatPendingWebhook!.chat_id)}
        disabled={submitting}
      >
        {submitting ? 'Processing…' : 'Process'}
      </button>
    </div>
  </div>
{/if}

<style>
  .webhook-pending-banner {
    display: flex;
    flex-direction: column;
    gap: 0.625rem;
    padding: 0.875rem 1rem;
    margin: 0.5rem 1rem 0.75rem;
    border: 1px solid color-mix(in srgb, var(--color-primary) 35%, transparent);
    background: color-mix(in srgb, var(--color-primary) 8%, var(--color-grey-10));
    border-radius: 0.625rem;
  }

  .banner-heading {
    display: flex;
    flex-direction: column;
    gap: 0.375rem;
  }

  .badge {
    align-self: flex-start;
    font-size: var(--processing-details-font-size);
    padding: 0.15rem 0.5rem;
    border-radius: 999px;
    color: var(--color-primary);
    background: color-mix(in srgb, var(--color-primary) 15%, transparent);
    font-weight: 600;
  }

  .banner-text {
    margin: 0;
    font-size: var(--font-size-p);
    color: var(--color-font-primary);
    line-height: 1.4;
  }

  .banner-error {
    font-size: var(--processing-details-font-size);
    color: var(--color-error);
  }

  .banner-actions {
    display: flex;
    gap: 0.5rem;
    justify-content: flex-end;
  }

  .btn-process,
  .btn-reject {
    padding: 0.4rem 0.9rem;
    border-radius: 0.4rem;
    font-size: var(--button-font-size);
    cursor: pointer;
    border: 1px solid transparent;
  }

  .btn-process {
    background: var(--color-primary);
    color: var(--color-grey-0);
  }

  .btn-process:disabled {
    background: var(--color-grey-30);
    cursor: not-allowed;
  }

  .btn-reject {
    background: transparent;
    color: var(--color-font-primary);
    border-color: var(--color-grey-30);
  }

  .btn-reject:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }
</style>
