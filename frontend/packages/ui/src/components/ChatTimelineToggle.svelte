<script lang="ts">
  import { text } from '@repo/ui';
  import { tooltip } from '../actions/tooltip';
  let { open, controls, onToggle }: { open: boolean; controls: string; onToggle: () => void } = $props();
  const gradientId = $props.id();
</script>

<div class="button-wrapper timeline-toggle-shell">
  <button type="button" class="header-action timeline-toggle" class:open
    data-testid="chat-timeline-toggle" aria-label={$text('chat.timeline.navigation')}
    aria-expanded={open} aria-controls={controls} onclick={onToggle} use:tooltip>
    <svg class="clickable-icon top-button" viewBox="0 0 24 24" fill="none" stroke={`url(#${gradientId})`}
      stroke-width="2" stroke-linecap="round" aria-hidden="true">
      <!-- Match the shared toolbar gradient; CSS gradients cannot be used as a color. -->
      <defs>
        <linearGradient id={gradientId} gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="24" y2="24">
          <stop offset="9.04%" stop-color="var(--color-primary-start)" />
          <stop offset="90.06%" stop-color="var(--color-primary-end)" />
        </linearGradient>
      </defs>
      <path d="M6 6h12" /><path d="M3 12h18" /><path d="M6 18h12" />
    </svg>
  </button>
</div>

<style>
  .timeline-toggle-shell { display: flex; align-items: center; justify-content: center; box-sizing: border-box; min-width: 44px; min-height: 44px; padding: var(--spacing-4); background: var(--color-grey-10); border-radius: var(--radius-full); box-shadow: var(--shadow-md); pointer-events: auto; }
  .timeline-toggle.header-action { all: unset; display: flex; align-items: center; justify-content: center; cursor: pointer; pointer-events: auto; opacity: 1; transition: opacity var(--duration-fast, 160ms) var(--easing-in-out); }
  .timeline-toggle.header-action.open { opacity: 0.5; }
  .timeline-toggle:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 4px; border-radius: var(--radius-full); }
  .timeline-toggle svg { display: block; width: 25px; height: 25px; }
  @media (prefers-reduced-motion: reduce) { .timeline-toggle.header-action { transition: none; } }
</style>
