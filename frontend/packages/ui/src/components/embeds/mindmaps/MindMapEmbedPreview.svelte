<!--
  frontend/packages/ui/src/components/embeds/mindmaps/MindMapEmbedPreview.svelte

  Preview card for Mind Maps direct embeds. Rendering is source-first: the
  canonical OpenMates JSON model is normalized by mindMapContent.ts and shown as
  a compact outline in the card.

  Native Swift counterparts:
  - apple/OpenMates/Sources/Features/Embeds/Renderers/MindMapEmbedRenderer.swift
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { normalizeMindMapSource, toMindMapOutline, type MindMapDocument } from './mindMapContent';

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
  let outline = $derived(normalized.model ? toMindMapOutline(normalized.model, 12) : 'Invalid mind map JSON');

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
  status={localStatus}
  skillName="Mind Map"
  {isMobile}
  {onFullscreen}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details()}
    <div class="mindmap-preview" aria-label={displayTitle}>
      <div class="mindmap-title">{displayTitle}</div>
      <pre>{outline}</pre>
      {#if normalized.status === 'partial'}
        <div class="mindmap-warning">{normalized.warnings.length} validation warning{normalized.warnings.length === 1 ? '' : 's'}</div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .mindmap-preview {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-4, 8px);
    height: 100%;
    overflow: hidden;
    padding: var(--spacing-6, 12px);
    color: var(--color-font-primary);
  }

  .mindmap-title {
    font-weight: 700;
    font-size: 0.95rem;
  }

  pre {
    flex: 1;
    margin: 0;
    overflow: hidden;
    white-space: pre-wrap;
    font: inherit;
    font-size: 0.75rem;
    line-height: 1.35;
  }

  .mindmap-warning {
    font-size: 0.7rem;
    color: var(--color-warning, #a86b00);
  }
</style>
