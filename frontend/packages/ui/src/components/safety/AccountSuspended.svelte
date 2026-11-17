<!--
  AccountSuspended: screen shown at login (or after an API 403) for a safety-suspended account.
  Shows the localized category-level reason and two actions: Appeal and Download my data.
  Preview: /dev/preview/safety/AccountSuspended
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import SafetyAppealForm from './SafetyAppealForm.svelte';

  interface Props {
    message: string;
    state?: 'temporary' | 'pending_review';
    until?: string | null;
    flaggedRequests?: string[];
    allowPhoto?: boolean;
    sent?: boolean;
    submitting?: boolean;
    errorMessage?: string | null;
    onappeal: (payload: { explanation: string; consent_share_requests: boolean; flagged_requests: string[]; attachment_data_url: string | null }) => void;
    ondownload?: () => void;
  }
  let { message, state: suspensionState = 'pending_review', until = null, flaggedRequests = [], allowPhoto = false, sent = false, submitting = false, errorMessage = null, onappeal, ondownload }: Props = $props();
  let showForm = $state(false);
  let untilDate = $derived(until ? new Date(until).toLocaleDateString() : '');
</script>

<div class="suspended" data-testid="account-suspended">
  <h1><mark>{$text('safety_appeal.title')}</mark></h1>
  <p class="reason" data-testid="account-suspended-reason">{message}</p>
  {#if suspensionState === 'temporary' && untilDate}
    <p class="until" data-testid="account-suspended-until">{$text('safety_appeal.until').replace('{date}', untilDate)}</p>
  {/if}
  {#if suspensionState === 'temporary'}
    <!-- A temporary suspension ends by itself; only a pending review can be appealed. -->
    {#if ondownload}
      <div class="actions">
        <button class="secondary" data-testid="account-suspended-download" onclick={ondownload}>{$text('safety_appeal.download_button')}</button>
      </div>
    {/if}
  {:else if sent}
    <p class="sent" data-testid="account-suspended-sent">{$text('safety_appeal.sent')}</p>
  {:else if showForm}
    <SafetyAppealForm {flaggedRequests} {allowPhoto} {submitting} {errorMessage} onsubmit={onappeal} />
  {:else}
    <div class="actions">
      <button class="primary" data-testid="account-suspended-appeal" onclick={() => (showForm = true)}>{$text('safety_appeal.appeal_button')}</button>
      {#if ondownload}
        <button class="secondary" data-testid="account-suspended-download" onclick={ondownload}>{$text('safety_appeal.download_button')}</button>
      {/if}
    </div>
  {/if}
</div>

<style>
  .suspended { display: flex; flex-direction: column; align-items: center; gap: var(--spacing-6, 16px); padding: 24px 16px; text-align: center; max-width: 420px; margin: 0 auto; }
  .reason { margin: 0; line-height: 1.4; }
  .actions { display: flex; flex-wrap: wrap; gap: 12px; justify-content: center; }
  .primary, .secondary { padding: 10px 18px; border-radius: 12px; cursor: pointer; font-weight: 600; border: 1px solid transparent; }
  .primary { background: var(--color-primary, #4867cd); color: #fff; }
  .secondary { background: transparent; border-color: var(--color-grey-40, #aaa); color: inherit; }
</style>
