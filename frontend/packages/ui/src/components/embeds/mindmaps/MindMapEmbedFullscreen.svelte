<!--
  frontend/packages/ui/src/components/embeds/mindmaps/MindMapEmbedFullscreen.svelte

  Fullscreen view for Mind Maps direct embeds. The canonical .ommindmap JSON can
  be downloaded from the top bar; the visible body shows the normalized outline
  and the exact source JSON for transparent debugging/import parity.

  Native Swift counterparts:
  - apple/OpenMates/Sources/Features/Embeds/Renderers/MindMapEmbedRenderer.swift
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import EmbedZoomControls from '../shared/EmbedZoomControls.svelte';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import {
    normalizeMindMapSource,
    serializeMindMapDocument,
    type MindMapDocument,
    type MindMapNode
  } from './mindMapContent';

  type ViewNode = MindMapNode & { x: number; y: number; depth: number; collapsed: boolean };

  const NODE_WIDTH = 180;
  const NODE_HEIGHT = 54;
  const COLUMN_GAP = 260;
  const ROW_GAP = 92;
  const MIN_ZOOM = 0.35;
  const MAX_ZOOM = 2.5;

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

  let graph = $derived(normalized.model ? buildLayout(normalized.model, collapsedNodeIds) : { nodes: [], edges: [], width: 0, height: 0 });
  let zoomLabel = $derived(`${Math.round(scale * 100)}%`);

  $effect(() => {
    const model = normalized.model;
    collapsedNodeIds = model?.view?.collapsedNodeIds ?? [];
  });

  $effect(() => {
    if (graph.nodes.length === 0 || viewportWidth === 0 || viewportHeight === 0) return;
    fitToView();
  });

  function downloadMindMap() {
    const filenameBase = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'mindmap';
    const blob = new Blob([sourceJson], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${filenameBase}.ommindmap`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
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

  function buildLayout(model: MindMapDocument, collapsedIds: string[]) {
    const nodesById = new Map(model.nodes.map((node) => [node.id, node]));
    const collapsed = new Set(collapsedIds);
    const visited = new Set<string>();
    const viewNodes: ViewNode[] = [];
    const edges: Array<{ source: ViewNode; target: ViewNode; label?: string }> = [];
    let nextRow = 0;

    function visit(nodeId: string, depth: number): ViewNode | null {
      const node = nodesById.get(nodeId);
      if (!node || visited.has(nodeId)) return null;
      visited.add(nodeId);

      const children = (node.children ?? []).filter((childId) => nodesById.has(childId));
      const childViews: ViewNode[] = [];
      if (!collapsed.has(nodeId)) {
        for (const childId of children) {
          const child = visit(childId, depth + 1);
          if (child) childViews.push(child);
        }
      }

      const row = childViews.length > 0
        ? childViews.reduce((sum, child) => sum + child.y, 0) / childViews.length / ROW_GAP
        : nextRow++;
      const viewNode: ViewNode = {
        ...node,
        x: depth * COLUMN_GAP,
        y: row * ROW_GAP,
        depth,
        collapsed: collapsed.has(nodeId),
      };
      viewNodes.push(viewNode);

      for (const child of childViews) edges.push({ source: viewNode, target: child });
      return viewNode;
    }

    visit(model.rootId, 0);
    for (const node of model.nodes) visit(node.id, 0);

    const visibleById = new Map(viewNodes.map((node) => [node.id, node]));
    for (const edge of model.edges ?? []) {
      const sourceNode = visibleById.get(edge.source);
      const targetNode = visibleById.get(edge.target);
      if (sourceNode && targetNode) edges.push({ source: sourceNode, target: targetNode, label: edge.label });
    }

    return {
      nodes: viewNodes,
      edges,
      width: Math.max(...viewNodes.map((node) => node.x + NODE_WIDTH), NODE_WIDTH),
      height: Math.max(...viewNodes.map((node) => node.y + NODE_HEIGHT), NODE_HEIGHT),
    };
  }
</script>

<UnifiedEmbedFullscreen
  appId="mindmaps"
  skillId="mindmap"
  {onClose}
  onDownload={downloadMindMap}
  embedHeaderTitle={title}
  embedHeaderSubtitle={`${normalized.nodeCount} nodes · ${normalized.edgeCount} edges`}
  skillIconName="workflow"
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
        <section
          class="mindmap-canvas"
          aria-label={title}
          bind:clientWidth={viewportWidth}
          bind:clientHeight={viewportHeight}
          onwheel={handleWheel}
          onpointerdown={handlePointerDown}
          onpointermove={handlePointerMove}
          onpointerup={handlePointerUp}
          onpointercancel={handlePointerUp}
          data-testid="mindmap-fullscreen-canvas"
        >
          <div
            class="mindmap-stage"
            style={`transform: translate(${panX}px, ${panY}px) scale(${scale}); width: ${graph.width}px; height: ${graph.height}px;`}
            data-testid="mindmap-fullscreen-stage"
          >
            <svg class="mindmap-edges" width={graph.width} height={graph.height} aria-hidden="true">
              {#each graph.edges as edge}
                <path
                  d={`M ${edge.source.x + NODE_WIDTH} ${edge.source.y + NODE_HEIGHT / 2} C ${edge.source.x + NODE_WIDTH + 60} ${edge.source.y + NODE_HEIGHT / 2}, ${edge.target.x - 60} ${edge.target.y + NODE_HEIGHT / 2}, ${edge.target.x} ${edge.target.y + NODE_HEIGHT / 2}`}
                />
              {/each}
            </svg>

            {#each graph.nodes as node}
              <article class="mindmap-node" style={`left: ${node.x}px; top: ${node.y}px;`} data-testid="mindmap-node">
                <div class="mindmap-node-label">{node.label}</div>
                {#if node.description}<div class="mindmap-node-description">{node.description}</div>{/if}
                {#if (node.children?.length ?? 0) > 0}
                  <button
                    type="button"
                    class="mindmap-collapse"
                    onclick={(event) => { event.stopPropagation(); toggleCollapsed(node.id); }}
                    aria-label={node.collapsed ? `Expand ${node.label}` : `Collapse ${node.label}`}
                    data-testid="mindmap-collapse-toggle"
                  >
                    {node.collapsed ? '+' : '−'}
                  </button>
                {/if}
              </article>
            {/each}
          </div>
        </section>
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

  .mindmap-canvas {
    position: relative;
    min-height: min(68vh, 720px);
    overflow: hidden;
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-8, 20px);
    background:
      radial-gradient(circle at 20px 20px, var(--color-grey-20) 1px, transparent 1px),
      var(--color-grey-5, #fafafa);
    background-size: 28px 28px;
    touch-action: none;
    cursor: grab;
  }

  .mindmap-canvas:active {
    cursor: grabbing;
  }

  .mindmap-stage {
    position: absolute;
    left: 0;
    top: 0;
    transform-origin: 0 0;
  }

  .mindmap-edges {
    position: absolute;
    inset: 0;
    overflow: visible;
  }

  .mindmap-edges path {
    fill: none;
    stroke: var(--color-grey-30, #d1d5db);
    stroke-width: 2;
  }

  .mindmap-node {
    position: absolute;
    width: 180px;
    min-height: 54px;
    box-sizing: border-box;
    padding: 10px 38px 10px 12px;
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-5, 12px);
    background: var(--color-grey-0, #fff);
    box-shadow: 0 8px 20px rgba(0, 0, 0, 0.08);
    color: var(--color-font-primary);
  }

  .mindmap-node-label {
    font-weight: 700;
    line-height: 1.2;
  }

  .mindmap-node-description {
    margin-top: 4px;
    color: var(--color-font-secondary, #667085);
    font-size: 0.78rem;
    line-height: 1.25;
  }

  .mindmap-collapse {
    position: absolute;
    right: 8px;
    top: 50%;
    width: 24px;
    height: 24px;
    transform: translateY(-50%);
    border: 1px solid var(--color-grey-20);
    border-radius: 50%;
    background: var(--color-grey-5, #fafafa);
    color: var(--color-font-primary);
    cursor: pointer;
    font: inherit;
    line-height: 1;
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

  @container fullscreen (max-width: 600px) {
    .mindmap-canvas {
      min-height: 58vh;
    }
  }
</style>
