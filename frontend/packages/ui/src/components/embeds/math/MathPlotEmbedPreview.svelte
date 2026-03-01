<!--
  frontend/packages/ui/src/components/embeds/math/MathPlotEmbedPreview.svelte

  Preview card for math-plot direct-type embeds.
  Renders a compact function graph using function-plot.

  These embeds are created automatically by stream_consumer.py when the LLM
  outputs a ```plot ... ``` fenced code block containing function definitions.

  States:
  - processing: Shows a loading indicator while the plot is being set up
  - finished:   Renders the interactive function graph
  - error:      Shows an error indicator
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';

  interface Props {
    /** Unique embed ID */
    id: string;
    /** Raw plot specification string (function definitions) */
    plotSpec?: string;
    /** Processing status */
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler that opens the fullscreen */
    onFullscreen?: () => void;
  }

  let {
    id,
    plotSpec: plotSpecProp,
    status: statusProp,
    isMobile = false,
    onFullscreen
  }: Props = $props();

  // ── Local state ─────────────────────────────────────────────────────────────
  let localPlotSpec = $state('');
  let localStatus   = $state<'processing' | 'finished' | 'error' | 'cancelled'>('processing');
  let plotContainer = $state<HTMLDivElement | null>(null);
  let renderError   = $state<string | null>(null);

  $effect(() => {
    localPlotSpec = plotSpecProp || '';
    localStatus   = statusProp || 'processing';
  });

  let plotSpec = $derived(localPlotSpec);
  let status   = $derived(localStatus);
  let skillName = $derived($text('embeds.math.plot'));

  // ── Embed data update callback ───────────────────────────────────────────────
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    const c = data.decodedContent;
    if (!c) return;
    if (typeof c.plot_spec === 'string') localPlotSpec = c.plot_spec;
  }

  // ── Plot rendering ───────────────────────────────────────────────────────────
  /**
   * Parse the plot spec string into function-plot data objects.
   * Format: one function per line, optionally "f(x) = expr" or just "expr".
   */
  function parsePlotSpec(spec: string): { fn: string }[] {
    if (!spec.trim()) return [];
    return spec
      .split('\n')
      .map(line => line.trim())
      .filter(line => line && !line.startsWith('#'))
      .map(line => {
        // Strip "f(x) = " or "y = " prefix if present
        const match = line.match(/^(?:[a-zA-Z_]\w*\s*\([^)]*\)\s*=|y\s*=)\s*(.+)$/);
        return { fn: match ? match[1].trim() : line };
      })
      .filter(d => d.fn.length > 0);
  }

  // Render graph when plotSpec or container changes
  $effect(() => {
    if (!plotContainer || status !== 'finished' || !plotSpec) return;

    renderError = null;

    // Dynamically import function-plot to avoid SSR issues
    import('function-plot').then(({ default: functionPlot }) => {
      if (!plotContainer) return;
      try {
        const data = parsePlotSpec(plotSpec);
        if (data.length === 0) return;

        // Clear previous render
        plotContainer.innerHTML = '';

        functionPlot({
          target: plotContainer,
          width: plotContainer.clientWidth || 260,
          height: plotContainer.clientHeight || 120,
          grid: true,
          data,
          // Disable interaction for the small preview card
          disableZoom: true,
        });
      } catch (err) {
        renderError = err instanceof Error ? err.message : 'Render failed';
        console.error('[MathPlotEmbedPreview] Plot render error:', err);
      }
    }).catch(err => {
      renderError = 'Failed to load plot library';
      console.error('[MathPlotEmbedPreview] Import error:', err);
    });
  });
</script>

<UnifiedEmbedPreview
  {id}
  appId="math"
  skillId="plot"
  skillIconName="math"
  {status}
  {skillName}
  {isMobile}
  {onFullscreen}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="math-plot-details" class:mobile={isMobileLayout}>
      {#if status === 'error' || renderError}
        <div class="error-indicator">{renderError || $text('chat.an_error_occured')}</div>
      {:else if status === 'finished' && plotSpec}
        <!-- Graph container — function-plot renders an SVG here -->
        <div class="plot-container" bind:this={plotContainer}></div>
      {:else if status === 'processing'}
        <div class="plot-placeholder">
          <div class="plot-axes">
            <div class="axis-x"></div>
            <div class="axis-y"></div>
          </div>
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  /* ── Details layout ─────────────────────────────────────────────────────── */

  .math-plot-details {
    display: flex;
    flex-direction: column;
    height: 100%;
    align-items: stretch;
    justify-content: center;
  }

  /* ── Plot container (function-plot renders SVG here) ────────────────────── */

  .plot-container {
    width: 100%;
    height: 120px;
    overflow: hidden;
    border-radius: 6px;
  }

  .math-plot-details.mobile .plot-container {
    height: 100px;
  }

  /* Make function-plot SVG fill the container */
  :global(.math-plot-details .function-plot) {
    width: 100% !important;
    overflow: visible;
  }

  /* ── Loading placeholder ─────────────────────────────────────────────────── */

  .plot-placeholder {
    width: 100%;
    height: 120px;
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    opacity: 0.3;
  }

  .axis-x {
    position: absolute;
    top: 50%;
    left: 0;
    right: 0;
    height: 1px;
    background: var(--color-grey-70);
  }

  .axis-y {
    position: absolute;
    left: 50%;
    top: 0;
    bottom: 0;
    width: 1px;
    background: var(--color-grey-70);
  }

  /* ── Error ───────────────────────────────────────────────────────────────── */

  .error-indicator {
    font-size: 13px;
    color: var(--color-error);
    margin-top: 4px;
  }

  /* ── Skill icon ──────────────────────────────────────────────────────────── */

  :global(.unified-embed-preview .skill-icon[data-skill-icon="math"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/math.svg');
    mask-image: url('@openmates/ui/static/icons/math.svg');
  }

  :global(.unified-embed-preview.mobile .skill-icon[data-skill-icon="math"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/math.svg');
    mask-image: url('@openmates/ui/static/icons/math.svg');
  }
</style>
