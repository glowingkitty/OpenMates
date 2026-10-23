<script lang="ts">
  import { text } from '@repo/ui';
  import { notificationStore } from '../stores/notificationStore';
  let { active, onToggle, disabled = false, question = false }: {
    active: boolean; onToggle: () => Promise<void>; disabled?: boolean; question?: boolean;
  } = $props();
  let busy = $state(false);
  let failed = $state(false);
  const label = $derived($text(failed ? 'chat.timeline.bookmark_failed'
    : active ? 'chat.timeline.remove_bookmark' : question ? 'chat.timeline.bookmark_question' : 'chat.timeline.bookmark'));
  async function toggle(event: MouseEvent): Promise<void> {
    event.stopPropagation();
    if (busy || disabled) return;
    busy = true; failed = false;
    try { await onToggle(); }
    catch { failed = true; notificationStore.error($text('chat.timeline.bookmark_failed')); }
    finally { busy = false; }
  }
</script>

<button type="button" class="bookmark-toggle" class:active class:failed disabled={busy || disabled}
  data-testid="message-bookmark-button" data-save-failed={failed ? 'true' : 'false'}
  aria-label={label} title={label} aria-pressed={active} aria-busy={busy} onclick={toggle}>
  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 3.5h10a2 2 0 0 1 2 2V21l-7-4-7 4V5.5a2 2 0 0 1 2-2Z" /></svg>
</button>

<style>
  .bookmark-toggle { display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto; width: 28px; min-width: 28px; height: 28px; margin: 0; padding: 4px; border: 0; border-radius: var(--radius-2); background: transparent; color: var(--color-grey-60); cursor: pointer; }
  .bookmark-toggle, .bookmark-toggle:is(:hover, :active, :focus) { scale: 1; transform: none; filter: none; box-shadow: none; transition: none; }
  .bookmark-toggle svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linejoin: round; }
  .bookmark-toggle.active { color: var(--color-highlight-yellow-solid); }
  .bookmark-toggle.active svg { fill: currentColor; stroke: var(--color-grey-80); filter: drop-shadow(0 0 4px var(--color-highlight-yellow)); }
  .bookmark-toggle:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }
  .bookmark-toggle.failed { outline: 1px solid var(--color-error); }
  .bookmark-toggle:disabled { cursor: wait; opacity: 0.6; }
  @media (pointer: coarse) { .bookmark-toggle { width: 44px; min-width: 44px; height: 44px; } }
</style>
