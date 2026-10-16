<script lang="ts">
  import { onMount } from 'svelte';
  import { text } from '@repo/ui';
  let { onContinue, onCancel }: { onContinue: () => Promise<void>; onCancel: () => void } = $props();
  let dialog: HTMLDialogElement;
  let cancelButton: HTMLButtonElement;
  let busy = $state(false);
  let failed = $state(false);
  function containTab(event: KeyboardEvent) {
    if (event.key !== 'Tab') return;
    const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(
      'a[href],button:not([disabled]),input:not([disabled]):not([type="hidden"]),textarea:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])',
    )).filter(element => !element.matches(':disabled') && element.getClientRects().length > 0);
    const first = focusable[0];
    const last = focusable.at(-1);
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first.focus();
    }
  }
  async function continueCall() {
    if (busy) return;
    busy = true; failed = false;
    try { await onContinue(); }
    catch { failed = true; }
    finally { busy = false; }
  }
  onMount(() => {
    dialog.showModal();
    cancelButton.focus();
    return () => dialog.close();
  });
</script>

<!-- Reuse the native top-layer confirmation layout from ChatProjectPicker. -->
<dialog bind:this={dialog} class="privacy-confirmation" data-testid="voice-call-privacy-dialog"
  aria-labelledby="voice-call-privacy-title" aria-describedby="voice-call-privacy-description"
  aria-busy={busy} onkeydown={containTab} oncancel={event => { event.preventDefault(); if (!busy) onCancel(); }}>
  <h2 id="voice-call-privacy-title">{$text('voicecall.privacy_title')}</h2>
  <p id="voice-call-privacy-description">{$text('voicecall.privacy_description')}</p>
  <a href="https://ai.google.dev/gemini-api/terms#paid-services" target="_blank" rel="noopener noreferrer">{$text('voicecall.privacy_terms')}</a>
  {#if failed}<p class="error" role="alert">{$text('voicecall.privacy_save_failed')}</p>{/if}
  <div class="actions">
    <button bind:this={cancelButton} class="action" data-testid="voice-call-privacy-cancel" disabled={busy} onclick={onCancel}>{$text('common.cancel')}</button>
    <button class="action primary" data-testid="voice-call-privacy-continue" disabled={busy} onclick={() => void continueCall()}>{$text(busy ? 'voicecall.privacy_saving' : 'voicecall.privacy_continue')}</button>
  </div>
</dialog>

<style>
  .privacy-confirmation { inline-size:min(28rem,calc(100vw - 2rem)); max-block-size:calc(100dvh - 2rem); box-sizing:border-box; overflow-y:auto; padding:var(--spacing-8); border:1px solid var(--color-grey-30); border-radius:var(--radius-5); background:var(--color-grey-0); color:var(--color-font-primary); box-shadow:var(--shadow-lg); }
  .privacy-confirmation::backdrop { background:rgb(0 0 0 / .35); }
  h2 { font-size:var(--font-size-h4); margin:0 0 var(--spacing-6); }
  p { font-size:var(--font-size-p); line-height:1.5; margin:0 0 var(--spacing-6); }
  a { color:var(--color-button-primary); font-size:var(--font-size-small); }
  .actions { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:var(--spacing-4); margin-block-start:var(--spacing-8); }
  .action { padding:var(--spacing-6); border:0; border-radius:var(--radius-8); background:var(--color-grey-20); color:var(--color-font-primary); font:inherit; cursor:pointer; min-inline-size:0; block-size:auto; margin:0; filter:none; scale:1; }
  .primary { background:var(--color-button-primary); color:var(--color-font-button); }
  .action:disabled { opacity:.5; cursor:default; }
  .error { margin-block-start:var(--spacing-6); color:var(--color-error); font-size:var(--font-size-small); }
  @media(pointer:coarse) { .action { min-block-size:44px; } }
</style>
