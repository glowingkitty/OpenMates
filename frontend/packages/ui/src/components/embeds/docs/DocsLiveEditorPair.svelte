<!--
  Preview-only harness: two DocsLiveEditor mirrors joined by a fake link (no core, no
  server), so a component spec can show two editors converging and each other's carets.
-->
<script lang="ts">
  import DocsLiveEditor from './DocsLiveEditor.svelte';
  import LiveHeaderStatus from '../shared/LiveHeaderStatus.svelte';
  import { createFakeLiveLink } from '../../../services/live/fakeLiveLink';
  import type { LivePeer } from '../../../services/live/liveItemTypes';

  const mara: LivePeer = { user_id: 'mara', display_name: 'Mara', color: '#e8590c' };
  const jon: LivePeer = { user_id: 'jon', display_name: 'Jon', color: '#1c7ed6' };
  const [a, b] = createFakeLiveLink(mara, jon);
  let peersA = $state<LivePeer[]>([]);
  let peersB = $state<LivePeer[]>([]);
</script>

<div class="pair" data-testid="docs-live-pair">
  <section data-testid="docs-live-pane-a">
    <LiveHeaderStatus status="saved" peers={peersA} />
    <DocsLiveEditor itemId="preview-doc" client={a.client} self={mara} bind:peers={peersA} status="saved" onCancel={() => {}} />
  </section>
  <section data-testid="docs-live-pane-b">
    <LiveHeaderStatus status="saved" peers={peersB} />
    <DocsLiveEditor itemId="preview-doc" client={b.client} self={jon} bind:peers={peersB} status="saved" onCancel={() => {}} />
  </section>
</div>

<style>
  .pair { display: grid; grid-template-columns: 1fr 1fr; gap: var(--spacing-8); }
  section { min-width: 0; }
</style>
