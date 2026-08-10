<!--
  frontend/packages/ui/src/components/embeds/mindmaps/MindMapEmbedFullscreen.svelte

  Fullscreen view for Mind Maps direct embeds. The canonical .ommindmap JSON can
  be downloaded from the top bar; the visible body shows the normalized outline
  and the exact source JSON for transparent debugging/import parity.

  Native Swift counterparts:
  - apple/OpenMates/Sources/Features/Embeds/Renderers/MindMapEmbedRenderer.swift
-->

<script lang="ts">
  import { onDestroy, untrack } from 'svelte';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import EmbedZoomControls from '../shared/EmbedZoomControls.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import MindMapCanvas from './MindMapCanvas.svelte';
  import {
    buildMindMapLayout,
    normalizeMindMapSource,
    serializeMindMapDocument,
    type MindMapDocument
  } from './mindMapContent';

  const MIN_ZOOM = 0.35;
  const MAX_ZOOM = 2.5;
  const DOWNLOAD_URL_REVOKE_DELAY_MS = 60_000;

  interface Props {
    data: EmbedFullscreenRawData;
    onClose: () => void;
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
    onShowChat?: () => void;
  }

  let {
    data,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat
  }: Props = $props();

  let decoded = $derived(data.decodedContent ?? {});
  let attrs = $derived(data.attrs ?? {});
  let source = $derived(
    typeof decoded.source_json === 'string'
      ? decoded.source_json
      : decoded.model && typeof decoded.model === 'object'
        ? decoded.model as MindMapDocument
        : typeof attrs.source_json === 'string'
          ? attrs.source_json as string
          : undefined
  );
  let normalized = $derived(normalizeMindMapSource(source));
  let title = $derived(
    typeof decoded.title === 'string'
      ? decoded.title
      : typeof attrs.title === 'string'
        ? attrs.title as string
        : normalized.title
  );
  let sourceJson = $derived(normalized.model ? serializeMindMapDocument(normalized.model) : normalized.sourceJson);

  let viewportWidth = $state(0);
  let viewportHeight = $state(0);
  let scale = $state(1);
  let panX = $state(0);
  let panY = $state(0);
  let collapsedNodeIds = $state<string[]>([]);
  let draggingPointerId = $state<number | null>(null);
  let lastPointerX = $state(0);
  let lastPointerY = $state(0);
  const activePointers = new Map<number, { x: number; y: number }>();
  let lastPinchDistance = 0;

  let graph = $derived(normalized.model ? buildMindMapLayout(normalized.model, collapsedNodeIds) : { nodes: [], edges: [], width: 0, height: 0 });
  let zoomLabel = $derived(`${Math.round(scale * 100)}%`);
  let filenameBase = $derived(title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'mindmap');
  let downloadFilename = $derived(`${filenameBase}.ommindmap`);
  let preparedDownloadUrl = $state<string | null>(null);
  let preparedDownloadKey = $state<string | null>(null);

  $effect(() => {
    const model = normalized.model;
    collapsedNodeIds = model?.view?.collapsedNodeIds ?? [];
  });

  $effect(() => {
    if (graph.nodes.length === 0 || viewportWidth === 0 || viewportHeight === 0) return;
    fitToView();
  });

  $effect(() => {
    if (sourceJson === untrack(() => preparedDownloadKey)) return;

    const previousUrl = untrack(() => preparedDownloadUrl);
    if (previousUrl) URL.revokeObjectURL(previousUrl);
    preparedDownloadUrl = URL.createObjectURL(createMindMapBlob());
    preparedDownloadKey = sourceJson;
  });

  onDestroy(() => {
    if (preparedDownloadUrl) URL.revokeObjectURL(preparedDownloadUrl);
  });

  function createMindMapBlob() {
    return new Blob([sourceJson], { type: 'application/json' });
  }

  function downloadMindMap() {
    const url = preparedDownloadUrl ?? URL.createObjectURL(createMindMapBlob());
    const link = document.createElement('a');
    link.href = url;
    link.download = downloadFilename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    if (!preparedDownloadUrl) {
      window.setTimeout(() => URL.revokeObjectURL(url), DOWNLOAD_URL_REVOKE_DELAY_MS);
    }
  }

  function fitToView() {
    if (graph.width === 0 || graph.height === 0) return;
    const nextScale = clamp(Math.min((viewportWidth - 80) / graph.width, (viewportHeight - 120) / graph.height, 1.2), MIN_ZOOM, MAX_ZOOM);
    scale = nextScale;
    panX = Math.round((viewportWidth - graph.width * nextScale) / 2);
    panY = Math.round((viewportHeight - graph.height * nextScale) / 2);
  }

  function zoomBy(delta: number, originX = viewportWidth / 2, originY = viewportHeight / 2) {
    const nextScale = clamp(scale * delta, MIN_ZOOM, MAX_ZOOM);
    if (nextScale === scale) return;
    const worldX = (originX - panX) / scale;
    const worldY = (originY - panY) / scale;
    scale = nextScale;
    panX = originX - worldX * nextScale;
    panY = originY - worldY * nextScale;
  }

  function toggleCollapsed(nodeId: string) {
    collapsedNodeIds = collapsedNodeIds.includes(nodeId)
      ? collapsedNodeIds.filter((id) => id !== nodeId)
      : [...collapsedNodeIds, nodeId];
  }

  function handleWheel(event: WheelEvent) {
    event.preventDefault();
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    zoomBy(event.deltaY > 0 ? 0.9 : 1.1, event.clientX - rect.left, event.clientY - rect.top);
  }

  function handlePointerDown(event: PointerEvent) {
    const target = event.currentTarget as HTMLElement;
    target.setPointerCapture(event.pointerId);
    activePointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    draggingPointerId = event.pointerId;
    lastPointerX = event.clientX;
    lastPointerY = event.clientY;
    lastPinchDistance = getPointerDistance();
  }

  function handlePointerMove(event: PointerEvent) {
    if (!activePointers.has(event.pointerId)) return;
    activePointers.set(event.pointerId, { x: event.clientX, y: event.clientY });

    if (activePointers.size >= 2) {
      const distance = getPointerDistance();
      if (distance > 0 && lastPinchDistance > 0) {
        const center = getPointerCenter();
        const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
        zoomBy(distance / lastPinchDistance, center.x - rect.left, center.y - rect.top);
      }
      lastPinchDistance = distance;
      return;
    }

    if (draggingPointerId !== event.pointerId) return;
    panX += event.clientX - lastPointerX;
    panY += event.clientY - lastPointerY;
    lastPointerX = event.clientX;
    lastPointerY = event.clientY;
  }

  function handlePointerUp(event: PointerEvent) {
    activePointers.delete(event.pointerId);
    if (draggingPointerId === event.pointerId) draggingPointerId = null;
    lastPinchDistance = getPointerDistance();
  }

  function getPointerDistance() {
    const points = [...activePointers.values()];
    if (points.length < 2) return 0;
    return Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
  }

  function getPointerCenter() {
    const points = [...activePointers.values()];
    return {
      x: points.reduce((sum, point) => sum + point.x, 0) / points.length,
      y: points.reduce((sum, point) => sum + point.y, 0) / points.length,
    };
  }

  function clamp(value: number, min: number, max: number) {
    return Math.max(min, Math.min(max, value));
  }

</script>

<UnifiedEmbedFullscreen
  appId="mindmaps"
  skillId="mindmap"
  {onClose}
  onDownload={downloadMindMap}
  downloadHref={preparedDownloadUrl}
  {downloadFilename}
  embedHeaderTitle={title}
  embedHeaderSubtitle={`${normalized.nodeCount} nodes · ${normalized.edgeCount} edges`}
  skillIconName=""
  appIconName="workflow"
  showSkillIcon={false}
  {embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    <div class="mindmap-fullscreen">
      {#if normalized.status === 'invalid_source'}
        <section class="mindmap-error">
          <h3>Invalid mind map JSON</h3>
          {#if normalized.parseError}<p>{normalized.parseError}</p>{/if}
        </section>
      {:else}
        <div
          class="mindmap-canvas-frame"
          bind:clientWidth={viewportWidth}
          bind:clientHeight={viewportHeight}
        >
          <MindMapCanvas
            {graph}
            {title}
            {scale}
            {panX}
            {panY}
            interactive={true}
            onToggleCollapsed={toggleCollapsed}
            onWheel={handleWheel}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
          />
        </div>
        <EmbedZoomControls
          zoomOut={() => zoomBy(0.85)}
          zoomIn={() => zoomBy(1.15)}
          resetZoom={fitToView}
          {zoomLabel}
          zoomOutDisabled={scale <= MIN_ZOOM}
          zoomInDisabled={scale >= MAX_ZOOM}
          zoomOutTestId="mindmap-zoom-out"
          zoomInTestId="mindmap-zoom-in"
          resetTestId="mindmap-zoom-reset"
        />
        {#if normalized.warnings.length > 0}
          <section class="mindmap-warnings">
            <h3>Validation warnings</h3>
            <ul>
              {#each normalized.warnings as warning}
                <li>{warning.code}: {warning.path}</li>
              {/each}
            </ul>
          </section>
        {/if}
      {/if}
      <section class="mindmap-source">
        <h3>Source</h3>
        <pre>{sourceJson}</pre>
      </section>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .mindmap-fullscreen {
    display: grid;
    gap: var(--spacing-8, 16px);
    padding: var(--spacing-8, 16px);
    min-height: 100%;
  }

  .mindmap-source,
  .mindmap-warnings,
  .mindmap-error {
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-8, 20px);
    background: var(--color-grey-0);
    padding: var(--spacing-8, 16px);
  }

  .mindmap-canvas-frame {
    width: 100%;
  }

  h3 {
    margin: 0 0 var(--spacing-4, 8px);
  }

  pre {
    margin: 0;
    overflow: auto;
    white-space: pre-wrap;
    font: inherit;
    line-height: 1.45;
  }

  .mindmap-source pre {
    font-family: var(--font-family-mono, monospace);
    font-size: 0.85rem;
  }

</style>
