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
    selectedConnectedAccountPermissionAccountId,
    selectedConnectedAccountPermissionAccountIdsByActionId,
    selectedConnectedAccountPermissionActionIds
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

  function summaryValue(value: unknown): string {
    if (value === null || value === undefined || value === '') return '';
    return String(value);
  }

  function hasSummaryValue(summary: Record<string, unknown> | undefined, key: string): boolean {
    return Boolean(summaryValue(summary?.[key]));
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

    {#if $currentConnectedAccountPermissionRequest.requests?.length}
      <div class="connected-account-request-list" data-testid="connected-account-permission-requests">
        {#each $currentConnectedAccountPermissionRequest.requests as request (request.action_id)}
          <div class="connected-account-request" data-testid="connected-account-permission-request">
            <div class="connected-account-request-title">
              <label class="connected-account-request-toggle">
                <input
                  type="checkbox"
                  data-testid="connected-account-permission-request-toggle"
                  checked={$selectedConnectedAccountPermissionActionIds.includes(request.action_id)}
                  onchange={(event) =>
                    connectedAccountPermissionStore.toggleAction(
                      request.action_id,
                      event.currentTarget.checked
                    )}
                />
                <span>
                  {$text('chat.connected_account_permissions.request_title', {
                    values: { action: request.action }
                  })}
                </span>
              </label>
            </div>
            {#if $currentConnectedAccountPermissionRequest.accounts.length > 1}
              <label class="connected-account-request-account">
                <span>{$text('chat.connected_account_permissions.account')}</span>
                <select
                  data-testid="connected-account-permission-request-account"
                  value={$selectedConnectedAccountPermissionAccountIdsByActionId[request.action_id] ?? $selectedConnectedAccountPermissionAccountId ?? ''}
                  onchange={(event) =>
                    connectedAccountPermissionStore.setSelectedAccountForAction(
                      request.action_id,
                      event.currentTarget.value
                    )}
                  disabled={!$selectedConnectedAccountPermissionActionIds.includes(request.action_id)}
                >
                  {#each $currentConnectedAccountPermissionRequest.accounts as account (account.connected_account_id)}
                    <option value={account.connected_account_id}>{account.label}</option>
                  {/each}
                </select>
              </label>
            {/if}
            {#if request.summary}
              <dl class="connected-account-request-summary">
                {#if hasSummaryValue(request.summary, 'calendar_id')}
                  <div>
                    <dt>{$text('chat.connected_account_permissions.calendar')}</dt>
                    <dd>{summaryValue(request.summary.calendar_id)}</dd>
                  </div>
                {/if}
                {#if hasSummaryValue(request.summary, 'event_title')}
                  <div>
                    <dt>{$text('chat.connected_account_permissions.event_title')}</dt>
                    <dd>{summaryValue(request.summary.event_title)}</dd>
                  </div>
                {/if}
                {#if hasSummaryValue(request.summary, 'event_id')}
                  <div>
                    <dt>{$text('chat.connected_account_permissions.event_id')}</dt>
                    <dd>{summaryValue(request.summary.event_id)}</dd>
                  </div>
                {/if}
                {#if hasSummaryValue(request.summary, 'start')}
                  <div>
                    <dt>{$text('chat.connected_account_permissions.start')}</dt>
                    <dd>{summaryValue(request.summary.start)}</dd>
                  </div>
                {/if}
                {#if hasSummaryValue(request.summary, 'end')}
                  <div>
                    <dt>{$text('chat.connected_account_permissions.end')}</dt>
                    <dd>{summaryValue(request.summary.end)}</dd>
                  </div>
                {/if}
                {#if hasSummaryValue(request.summary, 'time_min')}
                  <div>
                    <dt>{$text('chat.connected_account_permissions.from')}</dt>
                    <dd>{summaryValue(request.summary.time_min)}</dd>
                  </div>
                {/if}
                {#if hasSummaryValue(request.summary, 'time_max')}
                  <div>
                    <dt>{$text('chat.connected_account_permissions.to')}</dt>
                    <dd>{summaryValue(request.summary.time_max)}</dd>
                  </div>
                {/if}
              </dl>
            {/if}
          </div>
        {/each}
      </div>
    {/if}

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
        disabled={!$selectedConnectedAccountPermissionAccountId || $connectedAccountPermissionLoading || Boolean($currentConnectedAccountPermissionRequest.requests?.length && $selectedConnectedAccountPermissionActionIds.length === 0)}
      >
        {#if $connectedAccountPermissionLoading}
          {$text('chat.connected_account_permissions.loading')}
        {:else}
          {$text('chat.connected_account_permissions.approve_selected')}
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

  .connected-account-request-list {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-3);
    margin-bottom: var(--spacing-6);
  }

  .connected-account-request {
    background: var(--color-grey-0);
    border: 1px solid var(--color-grey-25);
    border-radius: var(--radius-4);
    padding: var(--spacing-4);
  }

  .connected-account-request-title {
    color: var(--color-font-primary);
    font-size: var(--font-size-small);
    font-weight: 700;
    margin-bottom: var(--spacing-3);
  }

  .connected-account-request-toggle,
  .connected-account-request-account {
    display: flex;
    align-items: center;
    gap: var(--spacing-3);
  }

  .connected-account-request-toggle input {
    accent-color: var(--color-button-primary);
  }

  .connected-account-request-account {
    justify-content: space-between;
    margin-bottom: var(--spacing-3);
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
    font-weight: 600;
  }

  .connected-account-request-account select {
    max-width: 60%;
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-3);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    padding: var(--spacing-2) var(--spacing-3);
    font: inherit;
  }

  .connected-account-request-summary {
    display: grid;
    gap: var(--spacing-2);
    margin: 0;
  }

  .connected-account-request-summary div {
    display: grid;
    grid-template-columns: minmax(5.5rem, max-content) 1fr;
    gap: var(--spacing-3);
  }

  .connected-account-request-summary dt {
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
    font-weight: 600;
  }

  .connected-account-request-summary dd {
    color: var(--color-font-primary);
    font-size: var(--font-size-xs);
    margin: 0;
    overflow-wrap: anywhere;
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
