<!--
  Header status of a live item: Saved / Saving… / Waiting for connection / View only /
  Access removed, plus avatars (initial on the person's colour) of the people present.
  Display only: status and peers come from the core's events.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import type { LivePeer, LiveStatus } from '../../../services/live/liveItemTypes';

  interface Props { status: LiveStatus; peers?: LivePeer[] }
  let { status, peers = [] }: Props = $props();

  const KEYS: Record<LiveStatus, string> = {
    saved: 'embed_user_edits.live_status_saved',
    saving: 'embed_user_edits.live_status_saving',
    offline: 'embed_user_edits.live_status_offline',
    read_only: 'embed_user_edits.live_status_read_only',
    access_revoked: 'embed_user_edits.live_status_access_revoked',
  };
  const initial = (peer: LivePeer) => (peer.mate_name ?? peer.display_name).trim().charAt(0).toUpperCase();
  const assistant = $derived(peers.find((peer) => peer.mate_name || peer.mate));
</script>

<div class="live-header-status" data-testid="live-header-status" data-status={status}>
  <span class="live-status" data-testid="live-status">{$text(KEYS[status])}</span>
  {#if assistant}
    <span data-testid="live-assistant-editing">{$text('embed_user_edits.live_editing_here', { values: { name: assistant.mate_name ?? assistant.mate ?? assistant.display_name } })}</span>
  {/if}
  {#if peers.length > 0}
    <ul class="live-peers" data-testid="live-peers" aria-label={$text('embed_user_edits.live_peers_label')}>
      {#each peers as peer (peer.user_id)}
        <li class="live-peer" data-testid="live-peer" style="background: {peer.color}" title={peer.mate_name ?? peer.display_name}>{initial(peer)}</li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .live-header-status { display: flex; align-items: center; gap: var(--spacing-4); font-size: var(--font-size-small); color: var(--color-font-secondary); }
  .live-header-status[data-status='offline'], .live-header-status[data-status='access_revoked'] { color: var(--color-error); }
  .live-peers { display: flex; margin: 0; padding: 0; list-style: none; }
  .live-peer { display: flex; align-items: center; justify-content: center; width: 24px; height: 24px; margin-inline-start: -6px; border: 2px solid var(--color-grey-0); border-radius: 50%; color: #fff; font-size: 12px; font-weight: 600; box-sizing: border-box; }
  .live-peer:first-child { margin-inline-start: 0; }
</style>
