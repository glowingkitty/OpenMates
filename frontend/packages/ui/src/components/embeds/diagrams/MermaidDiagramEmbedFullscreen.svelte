<!--
  frontend/packages/ui/src/components/embeds/diagrams/MermaidDiagramEmbedFullscreen.svelte

  Fullscreen Mermaid diagram renderer with safe SVG insertion, source fallback,
  and basic pan/zoom controls for large diagrams.
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
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
  let zoom = $state(1);
  let offsetX = $state(0);
  let offsetY = $state(0);
  let dragging = $state(false);
  let dragStartX = 0;
  let dragStartY = 0;
  let dragOriginX = 0;
  let dragOriginY = 0;
  let renderRequest = 0;

  let rawContent = $derived(updatedContent ?? data.decodedContent ?? data.attrs ?? {});
  let diagramContent = $derived<MermaidDiagramContent>(normalizeMermaidContent(rawContent));
  let subtitle = $derived(`${diagramContent.diagramKind}${diagramContent.versionNumber ? ` · v${diagramContent.versionNumber}` : ''}`);

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
    zoom = 1;
    offsetX = 0;
    offsetY = 0;
  }

  function handlePointerDown(event: PointerEvent) {
    dragging = true;
    dragStartX = event.clientX;
    dragStartY = event.clientY;
    dragOriginX = offsetX;
    dragOriginY = offsetY;
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event: PointerEvent) {
    if (!dragging) return;
    offsetX = dragOriginX + event.clientX - dragStartX;
    offsetY = dragOriginY + event.clientY - dragStartY;
  }

  function handlePointerUp(event: PointerEvent) {
    dragging = false;
    (event.currentTarget as HTMLElement).releasePointerCapture(event.pointerId);
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
  {#snippet embedHeaderCta()}
    <div class="mermaid-controls" data-testid="mermaid-diagram-controls">
      <EmbedHeaderCtaButton label="Zoom in" onclick={() => (zoom = nextZoom(zoom, 'in'))} testId="mermaid-zoom-in" />
      <EmbedHeaderCtaButton label="Zoom out" onclick={() => (zoom = nextZoom(zoom, 'out'))} testId="mermaid-zoom-out" />
      <EmbedHeaderCtaButton label="Fit" onclick={resetView} testId="mermaid-fit" />
      <EmbedHeaderCtaButton label={showSource ? 'Show diagram' : 'Show source'} onclick={() => (showSource = !showSource)} testId="mermaid-toggle-source" />
    </div>
  {/snippet}

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
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .mermaid-controls {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-4);
    justify-content: center;
  }

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
</style>
