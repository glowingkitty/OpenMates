<!--
  frontend/packages/ui/src/components/embeds/math/MathPlotEmbedFullscreen.svelte

  Fullscreen view for math-plot direct-type embeds.
  Renders an interactive function graph using function-plot with zoom/pan enabled.

  Layout:
  - EmbedTopBar (share / copy / close) — handled by UnifiedEmbedFullscreen
  - EmbedHeader (gradient banner with title) — handled by UnifiedEmbedFullscreen
  - Full-width interactive plot area
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';

  interface Props {
    /** Raw plot specification string (function definitions) */
    plotSpec?: string;
    /** Plot title shown in the banner */
    title?: string;
    /** Close callback */
    onClose: () => void;
    /** Embed ID for the share button */
    embedId?: string;
    /** Navigation between sibling embeds in the same message */
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    /** Ultra-wide chat-button support */
    showChatButton?: boolean;
    onShowChat?: () => void;
  }

  let {
    plotSpec: plotSpecProp,
    title: titleProp,
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

  // ── Local state ─────────────────────────────────────────────────────────────
  let localPlotSpec = $state('');
  let localTitle    = $state('');
  let plotContainer = $state<HTMLDivElement | null>(null);
  let renderError   = $state<string | null>(null);

  $effect(() => {
    localPlotSpec = plotSpecProp || '';
    localTitle    = titleProp    || 'Function Plot';
  });

  let plotSpec = $derived(localPlotSpec);
  let title    = $derived(localTitle);

  // ── Embed data updates ───────────────────────────────────────────────────────
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (!data.decodedContent) return;
    const c = data.decodedContent;
    if (typeof c.plot_spec === 'string') localPlotSpec = c.plot_spec;
    if (typeof c.title === 'string') localTitle = c.title;
  }

  // ── Plot rendering ───────────────────────────────────────────────────────────
  function parsePlotSpec(spec: string): { fn: string }[] {
    if (!spec.trim()) return [];
    return spec
      .split('\n')
      .map(line => line.trim())
      .filter(line => line && !line.startsWith('#'))
      .map(line => {
        const match = line.match(/^(?:[a-zA-Z_]\w*\s*\([^)]*\)\s*=|y\s*=)\s*(.+)$/);
        return { fn: match ? match[1].trim() : line };
      })
      .filter(d => d.fn.length > 0);
  }

  $effect(() => {
    if (!plotContainer || !plotSpec) return;

    renderError = null;

    import('function-plot').then(({ default: functionPlot }) => {
      if (!plotContainer) return;
      try {
        const data = parsePlotSpec(plotSpec);
        if (data.length === 0) return;

        plotContainer.innerHTML = '';

        functionPlot({
          target: plotContainer,
          width: plotContainer.clientWidth || 600,
          height: plotContainer.clientHeight || 400,
          grid: true,
          data,
          // Zoom and pan enabled in fullscreen for interactivity
          disableZoom: false,
        });
      } catch (err) {
        renderError = err instanceof Error ? err.message : 'Render failed';
        console.error('[MathPlotEmbedFullscreen] Plot render error:', err);
      }
    }).catch(err => {
      renderError = 'Failed to load plot library';
      console.error('[MathPlotEmbedFullscreen] Import error:', err);
    });
  });

  // Re-render when container size changes (e.g. panel resize)
  let resizeObserver: ResizeObserver | null = null;

  $effect(() => {
    if (!plotContainer) return;

    resizeObserver = new ResizeObserver(() => {
      // Trigger re-render by re-running effect
      if (plotContainer && plotSpec) {
        import('function-plot').then(({ default: functionPlot }) => {
          if (!plotContainer) return;
          try {
            const data = parsePlotSpec(plotSpec);
            if (data.length === 0) return;
            plotContainer.innerHTML = '';
            functionPlot({
              target: plotContainer,
              width: plotContainer.clientWidth || 600,
              height: plotContainer.clientHeight || 400,
              grid: true,
              data,
              disableZoom: false,
            });
          } catch { /* ignore resize errors */ }
        }).catch(() => { /* ignore */ });
      }
    });

    resizeObserver.observe(plotContainer);

    return () => {
      resizeObserver?.disconnect();
      resizeObserver = null;
    };
  });
</script>

<UnifiedEmbedFullscreen
  appId="math"
  skillId="plot"
  embedHeaderTitle={title}
  onClose={onClose}
  skillIconName="math"
  showSkillIcon={true}
  currentEmbedId={embedId}
  onEmbedDataUpdated={handleEmbedDataUpdated}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    <div class="plot-fullscreen-content">
      {#if renderError}
        <div class="error-state">
          <p class="error-title">Plot render failed</p>
          <p class="error-message">{renderError}</p>
        </div>
      {:else if !plotSpec}
        <div class="loading-state"><p>Loading plot...</p></div>
      {:else}
        <!-- Interactive plot container - function-plot renders an SVG here -->
        <div class="plot-container" bind:this={plotContainer}></div>

        <!-- Function list below the graph -->
        <div class="functions-list">
          {#each plotSpec.split('\n').filter(l => l.trim() && !l.startsWith('#')) as fn}
            <div class="function-item">
              <code>{fn.trim()}</code>
            </div>
          {/each}
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ── Full-screen content wrapper ─────────────────────────────────────────── */

  .plot-fullscreen-content {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 24px 16px;
    padding-bottom: 120px;
    max-width: 1000px;
    margin: 0 auto;
    width: 100%;
  }

  /* ── Plot container ──────────────────────────────────────────────────────── */

  .plot-container {
    width: 100%;
    height: 400px;
    background: var(--color-grey-5, #fafafa);
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid var(--color-grey-20, #e5e5e5);
  }

  :global(.plot-fullscreen-content .function-plot) {
    width: 100% !important;
  }

  @container fullscreen (max-width: 500px) {
    .plot-container {
      height: 260px;
    }
  }

  /* ── Functions list ──────────────────────────────────────────────────────── */

  .functions-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .function-item {
    background: var(--color-grey-10, #f5f5f5);
    border-radius: 8px;
    padding: 10px 14px;
  }

  .function-item code {
    font-family: 'Courier New', Courier, monospace;
    font-size: 14px;
    color: var(--color-grey-100);
  }

  /* ── Loading / error ─────────────────────────────────────────────────────── */

  .loading-state {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--color-font-secondary);
    font-size: 16px;
  }

  .error-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 24px 16px;
  }

  .error-title {
    font-size: 18px;
    font-weight: 600;
    color: var(--color-error);
  }

  .error-message {
    font-size: 14px;
    color: var(--color-grey-70);
    line-height: 1.4;
  }

  /* ── Skill icon ──────────────────────────────────────────────────────────── */

  :global(.unified-embed-fullscreen-overlay .skill-icon[data-skill-icon="math"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/math.svg');
    mask-image: url('@openmates/ui/static/icons/math.svg');
  }
</style>
