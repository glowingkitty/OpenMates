<!--
  frontend/packages/ui/src/components/embeds/mindmaps/MindMapCanvas.svelte

  Shared visual canvas for Mind Maps embed preview and fullscreen renderers.
  Keeps node layout, links, colors, Lucide icons, and collapse controls in one
  place so the compact card and fullscreen view render the same canonical JSON.
-->

<script lang="ts">
  import { getLucideIcon } from '../../../utils/categoryUtils';
  import {
    MIND_MAP_NODE_HEIGHT,
    MIND_MAP_NODE_WIDTH,
    type MindMapLayout,
    type MindMapViewNode
  } from './mindMapContent';

  interface Props {
    graph: MindMapLayout;
    title: string;
    scale: number;
    panX: number;
    panY: number;
    compact?: boolean;
    interactive?: boolean;
    onToggleCollapsed?: (nodeId: string) => void;
    onWheel?: (event: WheelEvent) => void;
    onPointerDown?: (event: PointerEvent) => void;
    onPointerMove?: (event: PointerEvent) => void;
    onPointerUp?: (event: PointerEvent) => void;
  }

  let {
    graph,
    title,
    scale,
    panX,
    panY,
    compact = false,
    interactive = false,
    onToggleCollapsed,
    onWheel,
    onPointerDown,
    onPointerMove,
    onPointerUp,
  }: Props = $props();

  function nodeStyle(node: MindMapViewNode): string {
    const color = node.color;
    const base = `left: ${node.x}px; top: ${node.y}px;`;
    if (!color) return base;
    return `${base} --mindmap-node-bg: ${color}; --mindmap-node-border: ${color}; --mindmap-node-fg: ${textColorFor(color)};`;
  }

  function textColorFor(hexColor: string): string {
    const hex = hexColor.slice(1);
    const expanded = hex.length === 3
      ? hex.split('').map((char) => char + char).join('')
      : hex;
    const alpha = expanded.length === 8 ? parseInt(expanded.slice(6, 8), 16) / 255 : 1;
    const r = compositeOnLightBackground(parseInt(expanded.slice(0, 2), 16), alpha);
    const g = compositeOnLightBackground(parseInt(expanded.slice(2, 4), 16), alpha);
    const b = compositeOnLightBackground(parseInt(expanded.slice(4, 6), 16), alpha);
    const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    return luminance > 0.58 ? 'var(--color-font-primary)' : 'var(--color-grey-0, #fff)';
  }

  function compositeOnLightBackground(channel: number, alpha: number): number {
    return Math.round(channel * alpha + 250 * (1 - alpha));
  }
</script>

<section
  class="mindmap-canvas"
  class:compact
  class:interactive
  aria-label={title}
  onwheel={onWheel}
  onpointerdown={onPointerDown}
  onpointermove={onPointerMove}
  onpointerup={onPointerUp}
  onpointercancel={onPointerUp}
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
          d={`M ${edge.source.x + MIND_MAP_NODE_WIDTH / 2} ${edge.source.y + MIND_MAP_NODE_HEIGHT} C ${edge.source.x + MIND_MAP_NODE_WIDTH / 2} ${edge.source.y + MIND_MAP_NODE_HEIGHT + 40}, ${edge.target.x + MIND_MAP_NODE_WIDTH / 2} ${edge.target.y - 40}, ${edge.target.x + MIND_MAP_NODE_WIDTH / 2} ${edge.target.y}`}
        />
      {/each}
    </svg>

    {#each graph.nodes as node}
      {@const NodeIcon = getLucideIcon(node.icon || 'workflow')}
      <article class="mindmap-node" class:has-color={!!node.color} style={nodeStyle(node)} data-testid="mindmap-node">
        <div class="mindmap-node-icon" aria-hidden="true">
          <NodeIcon size={compact ? 10 : 14} color="currentColor" strokeWidth={2.4} />
        </div>
        <div class="mindmap-node-text">
          <div class="mindmap-node-label">{node.label}</div>
          {#if node.description}<div class="mindmap-node-description">{node.description}</div>{/if}
        </div>
        {#if interactive && onToggleCollapsed && (node.children?.length ?? 0) > 0}
          <button
            type="button"
            class="mindmap-collapse"
            onpointerdown={(event) => event.stopPropagation()}
            onclick={(event) => { event.stopPropagation(); onToggleCollapsed?.(node.id); }}
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

<style>
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
  }

  .mindmap-canvas.compact {
    width: 100%;
    height: 100%;
    min-height: 126px;
    border: none;
    border-radius: var(--radius-3);
  }

  .mindmap-canvas.interactive {
    touch-action: none;
    cursor: grab;
  }

  .mindmap-canvas.interactive:active {
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
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    align-items: center;
    gap: 8px;
    width: 220px;
    min-height: 64px;
    box-sizing: border-box;
    padding: 10px 12px;
    border: 1px solid var(--mindmap-node-border, var(--color-grey-20));
    border-radius: var(--radius-5, 12px);
    background: var(--mindmap-node-bg, var(--color-grey-0, #fff));
    box-shadow: 0 8px 20px rgba(0, 0, 0, 0.08);
    color: var(--mindmap-node-fg, var(--color-font-primary));
  }

  .mindmap-canvas.compact .mindmap-node {
    gap: 6px;
    padding: 8px 10px;
  }

  .mindmap-node-icon {
    display: grid;
    place-items: center;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    background: color-mix(in srgb, currentColor 14%, transparent);
    flex-shrink: 0;
  }

  .mindmap-node-text {
    min-width: 0;
  }

  .mindmap-node-label {
    font-weight: 700;
    line-height: 1.2;
    overflow-wrap: anywhere;
  }

  .mindmap-node-description {
    margin-top: 4px;
    color: color-mix(in srgb, currentColor 72%, transparent);
    font-size: 0.78rem;
    line-height: 1.25;
    overflow-wrap: anywhere;
  }

  .mindmap-collapse {
    box-sizing: border-box;
    width: 24px !important;
    min-width: 24px !important;
    height: 24px !important;
    min-height: 24px !important;
    padding: 0 !important;
    border: 1px solid color-mix(in srgb, currentColor 24%, transparent) !important;
    border-radius: 999px !important;
    background: color-mix(in srgb, currentColor 8%, var(--color-grey-0, #fff)) !important;
    color: inherit !important;
    cursor: pointer;
    display: inline-grid !important;
    place-items: center;
    font: inherit;
    font-weight: 700;
    line-height: 1 !important;
    margin: 0 !important;
    aspect-ratio: 1 / 1;
    box-shadow: none !important;
  }

  @container fullscreen (max-width: 600px) {
    .mindmap-canvas:not(.compact) {
      min-height: 58vh;
    }
  }
</style>
