<!--
  Preview-only harness: two SlidesEditor instances joined by a fake core that applies deck ops
  to a tiny in-memory model (preview-only, see previewOpLink.ts). Prop `mate` makes the second
  person an assistant ("<mate> is editing here" badge on its slide).
-->
<script lang="ts">
  import { untrack } from 'svelte';
  import SlidesEditor from './SlidesEditor.svelte';
  import LiveHeaderStatus from '../shared/LiveHeaderStatus.svelte';
  import { createPreviewOpLink } from '../../../services/live/previewOpLink';
  import type { LivePeer, LiveStatus } from '../../../services/live/liveItemTypes';
  import { applyPreviewDeckOp, previewDeck } from './slidesLivePreviewModel';

  let { mate = '', assistantEdit = false }: { mate?: string; assistantEdit?: boolean } = $props();
  const mara: LivePeer = { user_id: 'mara', display_name: 'Mara', color: 'var(--color-app-sheets-start)' };
  const jon: LivePeer = untrack(() => ({
    user_id: 'jon', display_name: 'Jon', color: 'var(--color-primary-start)', ...(mate ? { mate_name: mate } : {})
  }));
  const initial = untrack(() => assistantEdit ? {
    ...applyPreviewDeckOp(previewDeck, {
      op: 'deck',
      operation: { op: 'set_text_content', slide_id: 's1', element_id: 'e1', markup: 'Updated quarterly review' }
    }),
    can_undo: true
  } : previewDeck);
  const undoPreview = Symbol();
  const [a, b] = createPreviewOpLink(mara, jon, initial, (deck, op) =>
    op === undoPreview ? previewDeck : applyPreviewDeckOp(deck, op)
  );
  a.client.liveUndoLatestAssistant = async (id) => {
    await a.client.liveApplyOp(id, undoPreview);
    return true;
  };
  let peersA = $state<LivePeer[]>([]);
  let peersB = $state<LivePeer[]>([]);
  let statusA = $state<LiveStatus>('saved');
  let statusB = $state<LiveStatus>('saved');
</script>

<div class="pair" data-testid="slides-live-pair">
  <section data-testid="slides-live-pane-a">
    <LiveHeaderStatus status={statusA} peers={peersA} />
    <SlidesEditor markup="" liveItemId="preview-deck" liveClient={a.client} bind:liveStatus={statusA} bind:livePeers={peersA} initialSlideId="s1" showDone={false} onSave={async () => {}} onExit={() => {}} />
  </section>
  <section data-testid="slides-live-pane-b">
    <LiveHeaderStatus status={statusB} peers={peersB} />
    <SlidesEditor markup="" liveItemId="preview-deck" liveClient={b.client} bind:liveStatus={statusB} bind:livePeers={peersB} initialSlideId="s1" showDone={false} onSave={async () => {}} onExit={() => {}} />
  </section>
</div>

<style>
  /* The preview frame shrink-wraps its content, and SlidesEditor/grids size by container, so the pair needs its own explicit width. */
  .pair { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--spacing-8); padding-top: var(--spacing-8); width: min(960px, 92vw); box-sizing: border-box; }
  section { min-width: 0; width: 100%; min-height: 320px; }
  section > :global(.live-header-status) { min-height: 32px; }
</style>
