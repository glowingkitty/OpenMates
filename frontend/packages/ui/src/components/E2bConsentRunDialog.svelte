<!--
  frontend/packages/ui/src/components/E2bConsentRunDialog.svelte

  Modal asking for the account's E2B upload consent before a run the user
  started (assertion code-run.e2b.upload-consent). Presentation only: it wraps
  E2bUploadConsentRequest and reports the choice; the gate records the decision.
-->
<script lang="ts">
  import { text } from '../i18n/translations';
  import E2bUploadConsentRequest, { type E2bConsentChoice } from './E2bUploadConsentRequest.svelte';

  let { open, onAnswer, onDismiss }: {
    open: boolean;
    onAnswer: (choice: E2bConsentChoice) => void;
    onDismiss: () => void;
  } = $props();

  function onKeydown(event: KeyboardEvent) {
    if (open && event.key === 'Escape') onDismiss();
  }
</script>

<svelte:window onkeydown={onKeydown} />

{#if open}
  <div class="backdrop" data-testid="e2b-consent-dialog-backdrop" role="presentation"
    onclick={(event) => { if (event.target === event.currentTarget) onDismiss(); }}>
    <div class="dialog" data-testid="e2b-consent-dialog" role="dialog" aria-modal="true"
      aria-label={$text('e2b_consent.settings.title')}>
      <E2bUploadConsentRequest requestId="run-start" onAnswer={(choice) => onAnswer(choice)} />
    </div>
  </div>
{/if}

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    z-index: 10000;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: var(--spacing-8);
    background: rgba(0, 0, 0, 0.45);
  }
  .dialog {
    width: 100%;
    max-width: 560px;
    border-radius: var(--radius-7);
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
  }
</style>
