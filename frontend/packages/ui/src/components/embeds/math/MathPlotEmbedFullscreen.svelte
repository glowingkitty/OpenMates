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
  import katex from 'katex';
  import functionPlot from 'function-plot';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

  interface Props {
    /** Standardized raw embed data (decodedContent, attrs, embedData) */
    data: EmbedFullscreenRawData;
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

  // ── Extract fields from data ────────────────────────────────────────────────

  let dc = $derived(data.decodedContent);
  let attrs = $derived(data.attrs);
  let plotSpecProp = $derived(
      typeof dc.plot_spec === 'string' ? dc.plot_spec
      : typeof dc.expression === 'string' ? dc.expression
      : typeof attrs?.code === 'string' ? attrs.code as string
      : undefined
    );
  let titleProp = $derived(
      typeof dc.title === 'string' ? dc.title
      : typeof attrs?.title === 'string' ? attrs.title as string
      : 'Function Plot'
    );

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
    // plot_spec is the canonical field name; expression is the legacy name (pre-rename).
    // The fallback ensures embeds stored before the field rename still render correctly.
    if (typeof c.plot_spec === 'string') localPlotSpec = c.plot_spec;
    else if (typeof c.expression === 'string') localPlotSpec = c.expression;
    if (typeof c.title === 'string') localTitle = c.title;
  }

  // ── LaTeX rendering (mirrors MathPlotEmbedPreview) ──────────────────────────

  /**
   * Extract non-empty, non-comment lines from the plot spec for LaTeX display.
   * Shown above the interactive plot, just like the preview card shows formulas.
   */
  let formulaLines = $derived(
    plotSpec
      .split('\n')
      .map((l: string) => l.trim())
      .filter((l: string) => l && !l.startsWith('#'))
  );

  /**
   * Converts a pseudo-code function definition to a LaTeX string for KaTeX.
   * Mirrors the same logic in MathPlotEmbedPreview.svelte.
   */
  function toLatex(line: string): string {
    let s = line;
    s = s.replace(/\\/g, '');
    const mathFns = [
      'sin', 'cos', 'tan', 'cot', 'sec', 'csc',
      'arcsin', 'arccos', 'arctan',
      'sinh', 'cosh', 'tanh',
      'exp', 'log', 'ln',
      'abs', 'sign',
      'floor', 'ceil',
    ];
    for (const fn of mathFns) {
      s = s.replace(new RegExp(`(?<![a-zA-Z])(${fn})\\(`, 'g'), `\\${fn}(`);
    }
    s = s.replace(/\\sqrt\(([^)]*)\)/g, '\\sqrt{$1}');
    s = s.replace(/\\abs\(([^)]*)\)/g, '|$1|');
    s = s.replace(/\^(\([^)]+\))/g, (_, inner) => `^{${inner.slice(1, -1)}}`);
    s = s.replace(/(\w)\s*\*\s*(\w)/g, '$1 \\cdot $2');
    s = s.replace(/\*/g, ' \\cdot ');
    s = s.replace(/(?<![a-zA-Z])pi(?![a-zA-Z])/g, '\\pi');
    s = s.replace(/(?<![a-zA-Z])e(?![a-zA-Z(])/g, '\\mathrm{e}');
    return s;
  }

  /**
   * Render a formula line as KaTeX HTML.
   * Falls back to the raw line text if KaTeX throws (e.g. invalid LaTeX).
   */
  function renderFormula(line: string): { html: string; isKatex: boolean } {
    try {
      const latex = toLatex(line);
      const html = katex.renderToString(latex, {
        throwOnError: true,
        displayMode: true,   // display mode for fullscreen — centered, larger
        output: 'html',
      });
      return { html, isKatex: true };
    } catch {
      return { html: line, isKatex: false };
    }
  }

  /** Pre-rendered formula HTML strings for each formula line. */
  let renderedFormulas = $derived(formulaLines.map(renderFormula));

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

  function renderPlot(): void {
    if (!plotContainer || !plotSpec) return;

    renderError = null;

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
  }

  $effect(() => {
    if (!plotContainer || !plotSpec) return;
    renderPlot();
  });

  // Re-render when container size changes (e.g. panel resize)
  let resizeObserver: ResizeObserver | null = null;

  $effect(() => {
    if (!plotContainer) return;

    resizeObserver = new ResizeObserver(() => {
      // Trigger re-render by re-running effect
      if (plotContainer && plotSpec) {
        try {
          renderPlot();
        } catch {
          /* ignore resize errors */
        }
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
          <p class="ds-error-title">Plot render failed</p>
          <p class="error-message">{renderError}</p>
        </div>
      {:else if !plotSpec}
        <div class="loading-state"><p>Loading plot...</p></div>
      {:else}
        <!-- Function formulas rendered as LaTeX — shown above the interactive plot -->
        {#if renderedFormulas.length > 0}
          <div class="functions-header">
            <div class="formula-list">
              {#each renderedFormulas as formula}
                <div class="formula-line" class:katex-rendered={formula.isKatex}>
                  {#if formula.isKatex}
                    <!-- KaTeX-rendered LaTeX formula (displayMode = centered) -->
                    <!-- eslint-disable-next-line svelte/no-at-html-tags -->
                    {@html formula.html}
                  {:else}
                    <!-- Fallback: raw line in monospace when KaTeX can't parse -->
                    <code>{formula.html}</code>
                  {/if}
                </div>
              {/each}
            </div>
          </div>
        {/if}

        <!-- Interactive plot container - function-plot renders an SVG here -->
        <div class="plot-container" bind:this={plotContainer}></div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ── Full-screen content wrapper ─────────────────────────────────────────── */

  .plot-fullscreen-content {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-8);
    padding: var(--spacing-12) var(--spacing-8);
    width: 100%;
    box-sizing: border-box;
    /*
     * The parent .content-area is a flex scroll container (overflow-y: auto).
     * We can't use height: 100% here (it resolves to the scrolled content size,
     * not the viewport).  Instead, size the content wrapper to fill the
     * visible embed area by subtracting the EmbedHeader banner (~196px) and our
     * own vertical padding (48px) from the full container height.
     * This keeps the formula bar + plot neatly within one screen-full, with the
     * plot expanding to fill all remaining space via flex: 1 on .plot-container.
     */
    min-height: calc(100vh - 196px - 48px);
  }

  /* ── Plot container ──────────────────────────────────────────────────────── */

  .plot-container {
    width: 100%;
    /* Grow to fill whatever vertical space remains after the formula header */
    flex: 1 1 0;
    min-height: 200px;
    background: var(--color-grey-0);
    border-radius: var(--radius-5);
    overflow: hidden;
    border: 1px solid var(--color-grey-20);
  }

  :global(.plot-fullscreen-content .function-plot) {
    width: 100% !important;
    height: 100% !important;
  }

  /* ── Axis / tick label visibility ────────────────────────────────────────────
     function-plot renders an SVG; its tick text and axis lines must be explicitly
     coloured since they don't inherit CSS custom properties.
     Light mode: dark labels/lines on light background.
     Dark mode: light labels/lines on dark background. */
  :global(.plot-fullscreen-content .function-plot text) {
    fill: #333333 !important;
    font-size: var(--font-size-tiny);
  }

  /* Axis lines and grid (light mode) */
  :global(.plot-fullscreen-content .function-plot .x.axis path),
  :global(.plot-fullscreen-content .function-plot .x.axis line),
  :global(.plot-fullscreen-content .function-plot .y.axis path),
  :global(.plot-fullscreen-content .function-plot .y.axis line) {
    stroke: #555555 !important;
  }

  /* Dark mode: light labels and lines */
  :global([data-theme="dark"] .plot-fullscreen-content .function-plot text) {
    fill: #cccccc !important;
  }

  :global([data-theme="dark"] .plot-fullscreen-content .function-plot .x.axis path),
  :global([data-theme="dark"] .plot-fullscreen-content .function-plot .x.axis line),
  :global([data-theme="dark"] .plot-fullscreen-content .function-plot .y.axis path),
  :global([data-theme="dark"] .plot-fullscreen-content .function-plot .y.axis line) {
    stroke: var(--color-grey-60) !important;
  }

  /* ── Function formulas header (above the plot) ───────────────────────────── */

  .functions-header {
    background: var(--color-grey-10);
    border-radius: var(--radius-5);
    padding: var(--spacing-8) var(--spacing-10);
    border: 1px solid var(--color-grey-20);
  }

  .formula-list {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-4);
    align-items: center;
  }

  .formula-line {
    width: 100%;
    color: var(--color-grey-100);
    font-size: var(--font-size-p);
    text-align: center;
    overflow-x: auto;
  }

  /* KaTeX display-mode formulas: let KaTeX control sizing */
  .formula-line.katex-rendered :global(.katex-display) {
    margin: 0;
  }

  .formula-line :global(.katex) {
    font-size: var(--font-size-h3-mobile);
    color: var(--color-grey-100);
  }

  /* Fallback monospace for non-KaTeX lines */
  .formula-line code {
    font-family: 'Courier New', Courier, monospace;
    font-size: null;
    color: var(--color-grey-100);
  }

  /* ── Loading / error ─────────────────────────────────────────────────────── */

  .loading-state {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 200px;
    color: var(--color-font-secondary);
    font-size: var(--font-size-p);
  }

  .error-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-3);
    padding: var(--spacing-12) var(--spacing-8);
  }

  /* .ds-error-title base styles are generated from
     frontend/packages/ui/src/tokens/sources/components/status-feedback.yml */

  .error-message {
    font-size: var(--font-size-small);
    color: var(--color-grey-70);
    line-height: 1.4;
  }

  /* ── Skill icon ─────────────────────────────────────────────────────────────
     The math skill icon mask-image is defined globally in EmbedHeader.svelte
     via the [data-skill-icon="math"] rule — no local override needed here.
     ──────────────────────────────────────────────────────────────────────── */
</style>
