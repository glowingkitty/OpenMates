<script lang="ts">
  /**
   * ConnectedAccountPermissionDialog.svelte
   *
   * Inline approval card for provider-backed connected-account actions. The UI
   * stays in chat history and approves one exact action by minting short-lived
   * token refs in the browser, never by sending provider tokens to chat.
   */
  import { fade } from 'svelte/transition';
  import { text } from '@repo/ui';
  import Icon from './Icon.svelte';
  import {
    connectedAccountPermissionLoading,
    connectedAccountPermissionStore,
    currentConnectedAccountPermissionRequest,
    selectedConnectedAccountPermissionAccountId
  } from '../stores/connectedAccountPermissionStore';
  import {
    approveConnectedAccountPermissionRequest,
    rejectConnectedAccountPermissionRequest
  } from '../services/chatSyncServiceHandlersConnectedAccounts';

  async function approve() {
    await approveConnectedAccountPermissionRequest();
  }

  async function reject() {
    await rejectConnectedAccountPermissionRequest();
  }
</script>

{#if $currentConnectedAccountPermissionRequest}
  <div
    class="connected-account-permission-card"
    data-testid="connected-account-permission-dialog"
    role="dialog"
    aria-labelledby="connected-account-permission-title"
    transition:fade={{ duration: 200 }}
  >
    <div class="connected-account-permission-header">
      <Icon name="calendar" type="app" size="38px" />
      <div>
        <span id="connected-account-permission-title" class="connected-account-permission-title">
          {$text('chat.connected_account_permissions.title')}
        </span>
        <p class="connected-account-permission-question">
          {$text('chat.connected_account_permissions.question', {
            values: { action: $currentConnectedAccountPermissionRequest.action }
          })}
        </p>
      </div>
    </div>

    <div class="connected-account-list">
      {#each $currentConnectedAccountPermissionRequest.accounts as account (account.connected_account_id)}
        <label class="connected-account-option" class:selected={$selectedConnectedAccountPermissionAccountId === account.connected_account_id}>
          <input
            type="radio"
            name="connected-account-permission-account"
            value={account.connected_account_id}
            checked={$selectedConnectedAccountPermissionAccountId === account.connected_account_id}
            onchange={() => connectedAccountPermissionStore.setSelectedAccount(account.connected_account_id)}
          />
          <span>{account.label}</span>
        </label>
      {/each}
    </div>

    <div class="connected-account-actions">
      <button
        type="button"
        class="btn-approve"
        data-testid="btn-approve-connected-account"
        onclick={approve}
        disabled={!$selectedConnectedAccountPermissionAccountId || $connectedAccountPermissionLoading}
      >
        {#if $connectedAccountPermissionLoading}
          {$text('chat.connected_account_permissions.loading')}
        {:else}
          {$text('chat.connected_account_permissions.approve')}
        {/if}
      </button>
      <button
        type="button"
        class="btn-reject"
        data-testid="btn-reject-connected-account"
        onclick={reject}
        disabled={$connectedAccountPermissionLoading}
      >
        {$text('chat.permissions.reject_all')}
      </button>
    </div>
  </div>
{/if}

<style>
  .connected-account-permission-card {
    position: relative;
    background: var(--color-grey-10, #fff);
    border-radius: var(--radius-7);
    padding: var(--spacing-8);
    width: 100%;
    max-width: 629px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
    margin-bottom: var(--spacing-6);
    border: 1px solid var(--color-grey-25, #e5e5e5);
  }

  .connected-account-permission-header {
    display: flex;
    align-items: flex-start;
    gap: var(--spacing-5);
    margin-bottom: var(--spacing-6);
  }

  .connected-account-permission-title {
    display: block;
    font-size: var(--font-size-p);
    font-weight: 700;
    color: var(--color-font-primary);
    margin-bottom: var(--spacing-2);
  }

  .connected-account-permission-question {
    margin: 0;
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
    line-height: 1.45;
  }

  .connected-account-list {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-3);
    margin-bottom: var(--spacing-6);
  }

  .connected-account-option {
    display: flex;
    align-items: center;
    gap: var(--spacing-3);
    padding: var(--spacing-4);
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-4);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    cursor: pointer;
  }

  .connected-account-option.selected {
    border-color: var(--color-button-primary);
    background: var(--color-grey-5);
  }

  .connected-account-actions {
    display: flex;
    gap: var(--spacing-4);
    justify-content: flex-end;
  }

  .btn-approve,
  .btn-reject {
    border: none;
    border-radius: var(--radius-5);
    padding: var(--spacing-4) var(--spacing-6);
    font-size: var(--font-size-small);
    font-weight: 600;
    cursor: pointer;
  }

  .btn-approve {
    background: var(--color-button-primary);
    color: var(--color-font-button);
  }

  .btn-reject {
    background: var(--color-grey-20);
    color: var(--color-font-primary);
  }

  .btn-approve:disabled,
  .btn-reject:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
</style>
