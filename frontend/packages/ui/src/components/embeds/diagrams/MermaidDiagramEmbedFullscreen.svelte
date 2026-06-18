<!--
  frontend/packages/ui/src/components/embeds/diagrams/MermaidDiagramEmbedFullscreen.svelte

  Fullscreen Mermaid diagram renderer with safe SVG insertion, source fallback,
  and basic pan/zoom controls for large diagrams.
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import EmbedZoomControls from '../shared/EmbedZoomControls.svelte';
  import { notificationStore } from '../../../stores/notificationStore';
  import { copyToClipboard } from '../../../utils/clipboardUtils';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import {
    nextZoom,
    normalizeMermaidContent,
    sanitizeMermaidSvg,
    type MermaidDiagramContent
  } from './mermaidDiagramContent';

  interface Props {
    data?: EmbedFullscreenRawData;
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
    data = {},
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

  let updatedContent = $state<Record<string, unknown> | null>(null);
  let renderedSvg = $state('');
  let renderError = $state<string | null>(null);
  let showSource = $state(false);
  const DEFAULT_ZOOM = 1.2;
  const MIN_ZOOM = 0.25;
  const MAX_ZOOM = 4;

  let zoom = $state(DEFAULT_ZOOM);
  let offsetX = $state(0);
  let offsetY = $state(0);
  let dragging = $state(false);
  let dragStartX = 0;
  let dragStartY = 0;
  let dragOriginX = 0;
  let dragOriginY = 0;
  let pinchStartDistance = 0;
  let pinchStartZoom = DEFAULT_ZOOM;
  let pinchOriginContentX = 0;
  let pinchOriginContentY = 0;
  const activePointers = new Map<number, { x: number; y: number }>();
  let renderRequest = 0;

  let rawContent = $derived(updatedContent ?? data.decodedContent ?? data.attrs ?? {});
  let diagramContent = $derived<MermaidDiagramContent>(normalizeMermaidContent(rawContent));
  let subtitle = $derived(`${diagramContent.diagramKind}${diagramContent.versionNumber ? ` · v${diagramContent.versionNumber}` : ''}`);
  let zoomDisplayText = $derived(`${Math.round(zoom * 100)}%`);

  $effect(() => {
    renderDiagram(diagramContent.diagramCode);
  });

  function handleEmbedDataUpdated(update: { status: string; decodedContent: Record<string, unknown> }) {
    updatedContent = update.decodedContent;
  }

  async function renderDiagram(diagramCode: string) {
    const source = diagramCode.trim();
    if (!source) return;
    const request = ++renderRequest;
    try {
      const mermaid = await import('mermaid');
      mermaid.default.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        theme: document.documentElement.dataset.theme === 'dark' ? 'dark' : 'default'
      });
      const result = await mermaid.default.render(`mermaid-fullscreen-${embedId ?? 'embed'}-${request}`, source);
      if (request !== renderRequest) return;
      renderedSvg = sanitizeMermaidSvg(result.svg);
      renderError = null;
    } catch (error) {
      if (request !== renderRequest) return;
      renderedSvg = '';
      renderError = error instanceof Error ? error.message : 'Mermaid render failed';
      showSource = true;
    }
  }

  async function handleCopy() {
    const result = await copyToClipboard(diagramContent.diagramCode);
    if (result.success) notificationStore.success('Mermaid source copied');
    else notificationStore.error('Could not copy Mermaid source');
  }

  function handleDownload() {
    const blob = new Blob([diagramContent.diagramCode], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${diagramContent.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'diagram'}.mmd`;
    link.click();
    URL.revokeObjectURL(url);
  }

  function resetView() {
    zoom = DEFAULT_ZOOM;
    offsetX = 0;
    offsetY = 0;
  }

  function zoomIn() {
    zoom = nextZoom(zoom, 'in');
  }

  function zoomOut() {
    zoom = nextZoom(zoom, 'out');
  }

  function handlePointerDown(event: PointerEvent) {
    event.preventDefault();
    activePointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);

    if (activePointers.size >= 2) {
      startPinch(event.currentTarget as HTMLElement);
      return;
    }

    dragging = true;
    dragStartX = event.clientX;
    dragStartY = event.clientY;
    dragOriginX = offsetX;
    dragOriginY = offsetY;
  }

  function handlePointerMove(event: PointerEvent) {
    if (activePointers.has(event.pointerId)) {
      activePointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    }

    if (activePointers.size >= 2) {
      event.preventDefault();
      updatePinch(event.currentTarget as HTMLElement);
      return;
    }

    if (!dragging) return;
    event.preventDefault();
    offsetX = dragOriginX + event.clientX - dragStartX;
    offsetY = dragOriginY + event.clientY - dragStartY;
  }

  function handlePointerUp(event: PointerEvent) {
    activePointers.delete(event.pointerId);
    if (activePointers.size === 1) {
      const remaining = [...activePointers.values()][0];
      dragging = true;
      dragStartX = remaining.x;
      dragStartY = remaining.y;
      dragOriginX = offsetX;
      dragOriginY = offsetY;
    } else {
      dragging = false;
    }
    pinchStartDistance = 0;
    if ((event.currentTarget as HTMLElement).hasPointerCapture(event.pointerId)) {
      (event.currentTarget as HTMLElement).releasePointerCapture(event.pointerId);
    }
  }

  function startPinch(target: HTMLElement) {
    dragging = false;
    const points = [...activePointers.values()].slice(0, 2);
    const midpoint = getLocalMidpoint(target, points);
    pinchStartDistance = getPointerDistance(points);
    pinchStartZoom = zoom;
    pinchOriginContentX = (midpoint.x - offsetX) / zoom;
    pinchOriginContentY = (midpoint.y - offsetY) / zoom;
  }

  function updatePinch(target: HTMLElement) {
    const points = [...activePointers.values()].slice(0, 2);
    if (points.length < 2 || pinchStartDistance <= 0) return;
    const midpoint = getLocalMidpoint(target, points);
    const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, pinchStartZoom * (getPointerDistance(points) / pinchStartDistance)));
    zoom = Number(next.toFixed(3));
    offsetX = midpoint.x - pinchOriginContentX * zoom;
    offsetY = midpoint.y - pinchOriginContentY * zoom;
  }

  function getPointerDistance(points: { x: number; y: number }[]) {
    return Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
  }

  function getLocalMidpoint(target: HTMLElement, points: { x: number; y: number }[]) {
    const rect = target.getBoundingClientRect();
    return {
      x: ((points[0].x + points[1].x) / 2) - rect.left,
      y: ((points[0].y + points[1].y) / 2) - rect.top
    };
  }
</script>

<UnifiedEmbedFullscreen
  appId="diagrams"
  skillId="mermaid"
  embedHeaderTitle={diagramContent.title}
  embedHeaderSubtitle={subtitle}
  skillIconName="diagram"
  {onClose}
  onCopy={handleCopy}
  onDownload={handleDownload}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet content()}
    <div class="mermaid-fullscreen" data-testid="mermaid-diagram-fullscreen">
      {#if showSource || !renderedSvg}
        <section class="source-panel" data-testid="mermaid-source-panel">
          {#if renderError}
            <p class="render-error">{renderError}</p>
          {/if}
          <pre><code>{diagramContent.diagramCode || 'No Mermaid source available.'}</code></pre>
        </section>
      {:else}
        <section
          class="diagram-panel"
          class:dragging
          role="application"
          aria-label="Interactive Mermaid diagram"
          data-testid="mermaid-rendered-panel"
          style={`--zoom: ${zoom}; --offset-x: ${offsetX}px; --offset-y: ${offsetY}px;`}
          onpointerdown={handlePointerDown}
          onpointermove={handlePointerMove}
          onpointerup={handlePointerUp}
          onpointercancel={handlePointerUp}
        >
          <!-- eslint-disable-next-line svelte/no-at-html-tags -->
          <div class="diagram-svg">{@html renderedSvg}</div>
        </section>
      {/if}
    </div>
    <div class="mermaid-diagram-controls" data-testid="mermaid-diagram-controls">
      <EmbedZoomControls
        zoomOut={zoomOut}
        zoomIn={zoomIn}
        resetZoom={resetView}
        zoomLabel={zoomDisplayText}
        zoomOutDisabled={zoom <= MIN_ZOOM}
        zoomInDisabled={zoom >= MAX_ZOOM}
        zoomOutTestId="mermaid-zoom-out"
        zoomInTestId="mermaid-zoom-in"
        resetTestId="mermaid-fit"
      />
      <button
        class="mermaid-source-toggle"
        type="button"
        data-testid="mermaid-toggle-source"
        onclick={() => (showSource = !showSource)}
      >
        {showSource ? 'Show diagram' : 'Show source'}
      </button>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .mermaid-fullscreen {
    width: calc(100% - 10px);
    min-height: calc(100vh - 360px);
    margin: 42px var(--spacing-5) var(--spacing-8);
    border-radius: var(--radius-4);
    background: var(--color-grey-10);
    overflow: hidden;
  }

  .diagram-panel {
    width: 100%;
    height: min(72vh, 760px);
    overflow: hidden;
    cursor: grab;
    touch-action: none;
    background: var(--color-grey-0);
  }

  .diagram-panel.dragging {
    cursor: grabbing;
  }

  .diagram-svg {
    width: max-content;
    min-width: 100%;
    padding: var(--spacing-8);
    transform: translate(var(--offset-x), var(--offset-y)) scale(var(--zoom));
    transform-origin: top left;
  }

  .diagram-svg :global(svg) {
    display: block;
    max-width: none;
  }

  .source-panel {
    min-height: min(72vh, 760px);
    padding: var(--spacing-6);
    overflow: auto;
    background: var(--color-grey-15);
  }

  .source-panel pre {
    margin: 0;
    font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
    font-size: var(--font-size-small);
    line-height: 1.55;
    white-space: pre-wrap;
  }

  .render-error {
    margin: 0 0 var(--spacing-5);
    color: var(--color-error, var(--color-font-primary));
    font-weight: 700;
  }

  .mermaid-diagram-controls {
    position: sticky;
    bottom: var(--spacing-8);
    z-index: var(--z-index-modal);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--spacing-3);
    pointer-events: none;
    margin-top: -72px;
    padding-bottom: var(--spacing-6);
  }

  .mermaid-diagram-controls :global(.doc-zoom-bar) {
    position: static;
    margin-top: 0;
    padding-bottom: 0;
  }

  .mermaid-source-toggle {
    pointer-events: auto;
    border: 1px solid var(--color-grey-20, #e5e5e5);
    border-radius: var(--radius-7);
    background: var(--color-grey-0, #fff);
    color: var(--color-grey-80, #333);
    font: inherit;
    font-size: var(--font-size-xs);
    font-weight: 500;
    padding: var(--spacing-2) var(--spacing-5);
    cursor: pointer;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
  }

  .mermaid-source-toggle:hover {
    background: var(--color-grey-10, #f0f0f0);
    border-color: var(--color-grey-30, #ccc);
  }
</style>
