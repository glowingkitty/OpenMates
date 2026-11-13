<!--
  Isolated evidence fixture for live progress on a running app skill embed.
  It replays the production path: a "processing" frame is stored in the embed
  store and announced with the `embedUpdated` event, exactly as
  handleSendEmbedDataImpl does for a re-sent processing embed. The buttons
  send later frames so the focused spec can prove the card updates in place.
  No account, API or backend is involved.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { encode } from '@toon-format/toon';
  import UnifiedEmbedPreview from './UnifiedEmbedPreview.svelte';
  import { embedStore } from '../../services/embedStore';
  import { chatSyncService } from '../../services/chatSyncService';
  import type { EmbedProgress } from './embedProgress';

  const embedId = 'preview-embed-progress';
  const frames: Record<string, EmbedProgress> = {
    first: { sources_total: 4, sources_done: 0, result_count: 0, seq: 1 },
    second: { sources_total: 4, sources_done: 2, result_count: 17, seq: 2 },
    stale: { sources_total: 4, sources_done: 1, result_count: 3, seq: 1 },
    single: { sources_total: 1, sources_done: 0, result_count: 17, seq: 3 },
  };

  let ready = $state(false);

  function sendFrame(name: keyof typeof frames) {
    const content = encode({ app_id: 'web', skill_id: 'search', status: 'processing', progress: frames[name] });
    embedStore.setInMemoryOnly(`embed:${embedId}`, {
      embed_id: embedId, type: 'app-skill-use', status: 'processing', content,
      app_id: 'web', skill_id: 'search', createdAt: Date.now(), updatedAt: Date.now(),
    });
    chatSyncService.dispatchEvent(new CustomEvent('embedUpdated', {
      detail: { embed_id: embedId, type: 'app-skill-use', status: 'processing', content, isProcessing: true },
    }));
  }

  // Seed the first frame before the card mounts, as a re-render during streaming would.
  onMount(() => {
    sendFrame('first');
    ready = true;
  });
</script>

<div class="embed-progress-fixture" data-testid="embed-progress-fixture">
  {#if ready}
    <UnifiedEmbedPreview
      id={embedId}
      localOnly
      appId="web"
      skillId="search"
      skillIconName="search"
      skillName="Search"
      status="processing"
      onFullscreen={() => {}}
    >
      {#snippet details()}<p>Searching the web</p>{/snippet}
    </UnifiedEmbedPreview>
  {/if}
  <div class="frame-buttons">
    {#each Object.keys(frames) as name (name)}
      <button type="button" data-testid={`send-frame-${name}`} onclick={() => sendFrame(name as keyof typeof frames)}>{name}</button>
    {/each}
  </div>
</div>

<style>
  .embed-progress-fixture { display: grid; gap: 12px; justify-items: start; }
  .frame-buttons { display: flex; gap: 8px; }
</style>
