<!--
  Preview-only harness: two SheetLiveGrid editors joined by a fake core that applies ops to a
  tiny in-memory model (preview-only, see previewOpLink.ts). Prop `mate` makes the second
  person an assistant, so the "<mate> is editing here" label can be shown.
-->
<script lang="ts">
  import { untrack } from 'svelte';
  import SheetLiveGrid from './SheetLiveGrid.svelte';
  import LiveHeaderStatus from '../shared/LiveHeaderStatus.svelte';
  import { createPreviewOpLink } from '../../../services/live/previewOpLink';
  import type { LivePeer } from '../../../services/live/liveItemTypes';
  import { applyPreviewSheetOp, previewSheet } from './sheetLivePreviewModel';

  let { mate = '' }: { mate?: string } = $props();
  const mara: LivePeer = { user_id: 'mara', display_name: 'Mara', color: 'var(--color-app-sheets-start)' };
  const jon: LivePeer = untrack(() => ({
    user_id: 'jon', display_name: 'Jon', color: 'var(--color-primary-start)', ...(mate ? { mate_name: mate } : {})
  }));
  const [a, b] = createPreviewOpLink(mara, jon, previewSheet, applyPreviewSheetOp);
  let peersA = $state<LivePeer[]>([]);
  let peersB = $state<LivePeer[]>([]);
</script>

<div class="pair" data-testid="sheet-live-pair">
  <section data-testid="sheet-live-pane-a">
    <LiveHeaderStatus status="saved" peers={peersA} />
    <SheetLiveGrid itemId="preview-sheet" client={a.client} bind:peers={peersA} status="saved" />
  </section>
  <section data-testid="sheet-live-pane-b">
    <LiveHeaderStatus status="saved" peers={peersB} />
    <SheetLiveGrid itemId="preview-sheet" client={b.client} bind:peers={peersB} status="saved" />
  </section>
</div>

<style>
  /* The preview frame shrink-wraps its content, and SlidesEditor/grids size by container, so the pair needs its own explicit width. */
  .pair { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--spacing-8); padding-top: var(--spacing-8); width: min(960px, 92vw); box-sizing: border-box; }
  section { min-width: 0; width: 100%; min-height: 320px; }
  section > :global(.live-header-status) { min-height: 32px; }
</style>
