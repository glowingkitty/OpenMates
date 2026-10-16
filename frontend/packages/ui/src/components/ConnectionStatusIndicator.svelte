<!-- Compact transient status. The reconnect control preserves manual retry. -->
<script lang="ts">
  import { Wifi, RefreshCw, Plane } from '@lucide/svelte';
  import type { ConnectionFeedbackState } from '../stores/connectionFeedbackStore';

  interface Props {
    state: ConnectionFeedbackState;
    label: string;
    retryLabel: string;
    onReconnect?: () => void;
  }

  let { state, label, retryLabel, onReconnect }: Props = $props();
</script>

{#if state !== 'idle'}
  <div
    class="connection-status"
    class:reconnecting={state === 'reconnecting'}
    class:syncing={state === 'syncing'}
    data-testid="connection-status-indicator"
    data-state={state}
    role="status"
    aria-label={label}
    title={label}
  >
    {#if state === 'offline'}
      <Plane size={18} strokeWidth={1.75} aria-hidden="true" />
    {:else if state === 'reconnecting' && onReconnect}
      <button type="button" class="retry" onclick={onReconnect} aria-label={retryLabel} title={retryLabel}>
        <Wifi size={20} strokeWidth={1.75} aria-hidden="true" />
      </button>
    {:else if state === 'reconnecting'}
      <Wifi size={20} strokeWidth={1.75} aria-hidden="true" />
    {:else}
      <RefreshCw size={18} strokeWidth={1.75} aria-hidden="true" />
    {/if}
  </div>
{/if}

<style>
  .connection-status {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    color: var(--color-grey-60);
    cursor: default;
  }

  .retry {
    all: unset;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    border-radius: var(--radius-full);
    cursor: pointer;
  }
  .retry:focus-visible {
    outline: 2px solid var(--color-warning);
    outline-offset: -2px;
  }

  /* Lucide supplies the icon paths; ripple outward through its three Wi-Fi arcs. */
  .reconnecting :global(svg path:not(:first-of-type)) {
    animation: wifi-ripple 1.8s ease-in-out infinite;
  }

  .reconnecting :global(svg path:nth-of-type(2)) {
    animation-delay: 0.36s;
  }

  .reconnecting :global(svg path:nth-of-type(3)) {
    animation-delay: 0.18s;
  }

  .syncing :global(svg) {
    animation: sync-turn 2.4s linear infinite;
  }

  @keyframes wifi-ripple {
    0%, 100% { opacity: 0.3; }
    45% { opacity: 1; }
  }

  @keyframes sync-turn {
    to { transform: rotate(360deg); }
  }

  @media (prefers-reduced-motion: reduce) {
    .reconnecting :global(svg path:not(:first-of-type)),
    .syncing :global(svg) {
      animation: none;
    }
  }
</style>
