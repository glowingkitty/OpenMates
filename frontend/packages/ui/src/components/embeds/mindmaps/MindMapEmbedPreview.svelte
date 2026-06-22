<!--
  frontend/packages/ui/src/components/embeds/mindmaps/MindMapEmbedPreview.svelte

  Preview card for Mind Maps direct embeds. Rendering is source-first: the
  canonical OpenMates JSON model is normalized by mindMapContent.ts and shown as
  a compact rendered map in the card.

  Native Swift counterparts:
  - apple/OpenMates/Sources/Features/Embeds/Renderers/MindMapEmbedRenderer.swift
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import MindMapCanvas from './MindMapCanvas.svelte';
  import { buildMindMapLayout, normalizeMindMapSource, type MindMapDocument } from './mindMapContent';

  interface Props {
    id: string;
    sourceJson?: string;
    model?: MindMapDocument | Record<string, unknown> | null;
    title?: string;
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    sourceJson = '',
    model = null,
    title = 'Mind Map',
    status: statusProp = 'processing',
    isMobile = false,
    onFullscreen
  }: Props = $props();

  let localSourceJson = $state('');
  let localModel = $state<MindMapDocument | Record<string, unknown> | null>(null);
  let localTitle = $state('Mind Map');
  let localStatus = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');

  $effect(() => {
    localSourceJson = sourceJson;
    localModel = model;
    localTitle = title;
    localStatus = statusProp;
  });

  let normalized = $derived(normalizeMindMapSource(localSourceJson || localModel));
  let displayTitle = $derived(localTitle || normalized.title || 'Mind Map');
  let graph = $derived(normalized.model ? buildMindMapLayout(normalized.model, normalized.model.view?.collapsedNodeIds ?? []) : { nodes: [], edges: [], width: 0, height: 0 });
  let viewportWidth = $state(0);
  let viewportHeight = $state(0);
  let previewScale = $derived.by(() => {
    if (graph.width === 0 || graph.height === 0 || viewportWidth === 0 || viewportHeight === 0) return 1;
    return Math.min(viewportWidth / graph.width, viewportHeight / graph.height, 1.1);
  });
  let previewPanX = $derived(Math.round((viewportWidth - graph.width * previewScale) / 2));
  let previewPanY = $derived(Math.round((viewportHeight - graph.height * previewScale) / 2));

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    const c = data.decodedContent;
    if (typeof c.source_json === 'string') localSourceJson = c.source_json;
    if (typeof c.title === 'string') localTitle = c.title;
    if (c.model && typeof c.model === 'object') localModel = c.model as Record<string, unknown>;
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="mindmaps"
  skillId="mindmap"
  skillIconName="workflow"
  appIconName="workflow"
  showSkillIcon={false}
  status={localStatus}
  skillName="Mind Map"
  {isMobile}
  {onFullscreen}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details()}
    <div class="mindmap-preview" aria-label={displayTitle} bind:clientWidth={viewportWidth} bind:clientHeight={viewportHeight} data-testid="mindmap-rendered-preview">
      {#if normalized.status === 'invalid_source'}
        <div class="mindmap-invalid">Invalid mind map JSON</div>
      {:else}
        <MindMapCanvas
          {graph}
          title={displayTitle}
          scale={previewScale}
          panX={previewPanX}
          panY={previewPanY}
          compact={true}
        />
      {/if}
      {#if normalized.status === 'partial'}
        <div class="mindmap-warning">{normalized.warnings.length} validation warning{normalized.warnings.length === 1 ? '' : 's'}</div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .mindmap-preview {
    position: relative;
    height: 100%;
    overflow: hidden;
    color: var(--color-font-primary);
  }

  .mindmap-invalid {
    display: grid;
    place-items: center;
    height: 100%;
    padding: var(--spacing-6, 12px);
    color: var(--color-font-secondary);
  }

  .mindmap-warning {
    position: absolute;
    right: var(--spacing-3, 6px);
    bottom: var(--spacing-3, 6px);
    padding: 2px 6px;
    border-radius: var(--radius-2, 6px);
    background: var(--color-grey-0, #fff);
    font-size: 0.7rem;
    color: var(--color-warning, #a86b00);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
  }
</style>
