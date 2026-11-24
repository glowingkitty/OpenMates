<!--
  Preview-only harness: two CodeLiveEditor mirrors joined by a fake link (no core, no
  server), seeded with one file, so a component spec can show two editors converging.
-->
<script lang="ts">
  import * as Y from 'yjs';
  import CodeLiveEditor from './CodeLiveEditor.svelte';
  import LiveHeaderStatus from '../shared/LiveHeaderStatus.svelte';
  import { createFakeLiveLink } from '../../../services/live/fakeLiveLink';
  import type { LivePeer } from '../../../services/live/liveItemTypes';

  const mara: LivePeer = { user_id: 'mara', display_name: 'Mara', color: '#e8590c' };
  const jon: LivePeer = { user_id: 'jon', display_name: 'Jon', color: '#1c7ed6' };
  const seedDoc = new Y.Doc();
  seedDoc.getText('content').insert(0, 'export function add(a: number, b: number): number {\n  return a + b;\n}\n');
  const [a, b] = createFakeLiveLink(mara, jon, Y.encodeStateAsUpdate(seedDoc));
  let peersA = $state<LivePeer[]>([]);
  let peersB = $state<LivePeer[]>([]);
</script>

<div class="pair" data-testid="code-live-pair">
  <section data-testid="code-live-pane-a">
    <LiveHeaderStatus status="saved" peers={peersA} />
    <CodeLiveEditor itemId="preview-code" filename="add.ts" client={a.client} self={mara} bind:peers={peersA} status="saved" onCancel={() => {}} />
  </section>
  <section data-testid="code-live-pane-b">
    <LiveHeaderStatus status="saved" peers={peersB} />
    <CodeLiveEditor itemId="preview-code" filename="add.ts" client={b.client} self={jon} bind:peers={peersB} status="saved" onCancel={() => {}} />
  </section>
</div>

<style>
  .pair { display: grid; grid-template-columns: 1fr 1fr; gap: var(--spacing-8); }
  section { min-width: 0; }
</style>
