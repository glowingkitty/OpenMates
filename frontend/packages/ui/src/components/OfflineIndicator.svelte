<!--
  frontend/packages/ui/src/components/OfflineIndicator.svelte

  Persistent offline indicator icon shown in the top-right corner (next to the
  user avatar) when the browser reports no network connectivity.
  Uses the existing offline.svg icon (cloud with strike-through).
  Subscribes to isOnline from networkStatusStore for instant reactivity.

  Architecture: simple presentational component, no server interaction.
-->
<script lang="ts">
  import { isOnline } from '../stores/networkStatusStore';
  import { text } from '@repo/ui';
  import { fade } from 'svelte/transition';
</script>

{#if !$isOnline}
  <div
    class="offline-indicator"
    title={$text('notifications.connection.offline_banner.title')}
    aria-label={$text('notifications.connection.offline_banner.title')}
    role="status"
    transition:fade={{ duration: 250 }}
  >
    <div class="offline-icon"></div>
  </div>
{/if}

<style>
  .offline-indicator {
    position: fixed;
    top: 18px;
    /* Positioned to the left of the avatar (avatar: inset-inline-end 10px, width 50px) */
    inset-inline-end: 68px;
    z-index: 1005;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    border-radius: 50%;
    background-color: var(--color-grey-10);
    cursor: default;
    pointer-events: auto;
  }

  .offline-icon {
    width: 18px;
    height: 18px;
    background-color: var(--color-grey-60);
    -webkit-mask-image: url('@openmates/ui/static/icons/offline.svg');
    mask-image: url('@openmates/ui/static/icons/offline.svg');
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-position: center;
    mask-position: center;
  }
</style>
