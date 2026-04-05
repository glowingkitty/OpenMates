<!--
  frontend/packages/ui/src/components/embeds/math/MathPlotEmbedPreview.svelte

  Preview card for math-plot direct-type embeds.
  Shows the function formulas rendered with KaTeX (LaTeX style) — the interactive
  graph renders in the fullscreen panel only (function-plot is too large for the
  300×200px card).

  These embeds are created automatically by stream_consumer.py when the LLM
  outputs a ```plot ... ``` fenced code block containing function definitions.

  States:
  - processing: Shows a loading placeholder (axis crosshairs) while the plot is being set up
  - finished:   Shows the function definitions rendered as LaTeX, tap to open fullscreen
  - error:      Shows an error indicator
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import katex from 'katex';

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
    onFullscreen: () => void;
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

  $effect(() => {
    localPlotSpec = plotSpecProp || '';
    localStatus   = statusProp || 'processing';
  });

  let plotSpec  = $derived(localPlotSpec);
  let status    = $derived(localStatus);
  let skillName = $derived($text('embeds.math.plot'));

  // ── Embed data update callback ───────────────────────────────────────────────
  /**
   * Called by UnifiedEmbedPreview when the server sends updated embed data.
   * Reads plot_spec (new field name) with a fallback to expression (old field name)
   * for backward compatibility with embeds stored before the rename.
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    const c = data.decodedContent;
    if (!c) return;
    // plot_spec is the canonical field name; expression is the legacy name (pre-rename)
    if (typeof c.plot_spec === 'string') localPlotSpec = c.plot_spec;
    else if (typeof c.expression === 'string') localPlotSpec = c.expression;
  }

  // ── Parse formula lines for display ──────────────────────────────────────────
  /**
   * Extract non-empty, non-comment lines from the plot spec for display.
   * Each line is shown as a formula in the preview card.
   */
  let formulaLines = $derived(
    plotSpec
      .split('\n')
      .map(l => l.trim())
      .filter(l => l && !l.startsWith('#'))
      .slice(0, 4) // Show at most 4 formulas in preview — rest visible in fullscreen
  );

  // ── Convert code-style math expression to LaTeX ───────────────────────────────
  /**
   * Converts a pseudo-code function definition (e.g. "f(x) = sin(x) + exp(-0.1 * x)")
   * into a LaTeX string suitable for KaTeX rendering.
   *
   * Handles:
   * - Named math functions: sin, cos, tan, exp, log, sqrt, abs, etc.
   * - Multiplication operator (*) replaced with \cdot (or removed between number/var)
   * - Powers: x^2, x^(n) → proper LaTeX superscripts
   * - Function definition LHS: f(x) = stays as f(x) =
   */
  function toLatex(line: string): string {
    let s = line;

    // Escape backslashes that might already be in the string
    // (plain text shouldn't have any, but be safe)
    s = s.replace(/\\/g, '');

    // Named math functions → LaTeX command (must come before general substitutions)
    const mathFns = [
      'sin', 'cos', 'tan', 'cot', 'sec', 'csc',
      'arcsin', 'arccos', 'arctan',
      'sinh', 'cosh', 'tanh',
      'exp', 'log', 'ln',
      'abs', 'sign',
      'floor', 'ceil',
    ];
    for (const fn of mathFns) {
      // Replace fn( with \fn( — only when preceded by non-alpha (avoid matching 'xsin')
      s = s.replace(new RegExp(`(?<![a-zA-Z])(${fn})\\(`, 'g'), `\\${fn}(`);
    }

    // sqrt(expr) → \sqrt{expr}  (single-argument, non-nested — handles simple cases)
    s = s.replace(/\\sqrt\(([^)]*)\)/g, '\\sqrt{$1}');

    // abs(expr) → |expr|
    s = s.replace(/\\abs\(([^)]*)\)/g, '|$1|');

    // Powers: x^(expr) → x^{expr}, x^n → x^{n} (already valid LaTeX for single char)
    s = s.replace(/\^(\([^)]+\))/g, (_, inner) => `^{${inner.slice(1, -1)}}`);

    // Explicit multiplication: number * symbol or symbol * number → use \cdot
    // e.g. "0.1 * x" → "0.1 \cdot x", "2 * pi" → "2 \cdot \pi"
    s = s.replace(/(\w)\s*\*\s*(\w)/g, '$1 \\cdot $2');

    // Remaining * (e.g. after the above) → \cdot
    s = s.replace(/\*/g, ' \\cdot ');

    // pi → \pi
    s = s.replace(/(?<![a-zA-Z])pi(?![a-zA-Z])/g, '\\pi');

    // e as standalone constant (e.g. "e^x" not "exp") → use \mathrm{e}
    // Only replace bare 'e' used as Euler's number (not inside words)
    s = s.replace(/(?<![a-zA-Z])e(?![a-zA-Z(])/g, '\\mathrm{e}');

    return s;
  }

  /**
   * Render a formula line as KaTeX HTML.
   * Falls back to the raw line text if KaTeX throws (e.g. invalid LaTeX).
   * Returns an object with the HTML string and a flag indicating if KaTeX succeeded.
   */
  function renderFormula(line: string): { html: string; isKatex: boolean } {
    try {
      const latex = toLatex(line);
      const html = katex.renderToString(latex, {
        throwOnError: true,
        displayMode: false,  // inline mode — fits in the card
        output: 'html',
      });
      return { html, isKatex: true };
    } catch {
      // KaTeX couldn't parse it — show the raw line in monospace as fallback
      return { html: line, isKatex: false };
    }
  }

  /** Pre-rendered formula HTML strings for each formula line. */
  let renderedFormulas = $derived(formulaLines.map(renderFormula));
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
      {#if status === 'error'}
        <div class="error-indicator">{$text('chat.an_error_occured')}</div>
      {:else if status === 'finished' && renderedFormulas.length > 0}
        <!-- Show function definitions rendered as LaTeX — graph is in fullscreen -->
        <div class="formula-list">
          {#each renderedFormulas as formula}
            <div class="formula-line" class:katex-rendered={formula.isKatex}>
              {#if formula.isKatex}
                <!-- KaTeX-rendered LaTeX formula -->
                <!-- eslint-disable-next-line svelte/no-at-html-tags -->
                {@html formula.html}
              {:else}
                <!-- Fallback: raw line in monospace when KaTeX can't parse -->
                <code>{formula.html}</code>
              {/if}
            </div>
          {/each}
        </div>
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
    justify-content: center;
  }

  /* ── Formula list ────────────────────────────────────────────────────────── */

  .formula-list {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-3);
    overflow: hidden;
  }

  .formula-line {
    overflow: hidden;
    /* Allow KaTeX to wrap naturally; clip overflow */
    white-space: nowrap;
    color: var(--color-grey-100);
    font-size: var(--font-size-small);
  }

  /* KaTeX-rendered lines: let KaTeX control sizing, just clip overflow */
  .formula-line.katex-rendered {
    overflow: hidden;
  }

  /* KaTeX global style overrides scoped to this component's formula lines */
  .formula-line :global(.katex) {
    font-size: var(--font-size-small);
    color: var(--color-grey-100);
  }

  .math-plot-details.mobile .formula-line :global(.katex) {
    font-size: var(--font-size-xxs);
  }

  /* Fallback monospace for non-KaTeX lines */
  .formula-line code {
    font-family: 'Courier New', Courier, monospace;
    font-size: var(--font-size-xs);
    font-weight: 500;
    color: var(--color-grey-100);
  }

  .math-plot-details.mobile .formula-line code {
    font-size: var(--font-size-tiny);
  }

  /* ── Loading placeholder (axis crosshairs) ───────────────────────────────── */

  .plot-placeholder {
    width: 100%;
    height: 80px;
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
    font-size: var(--font-size-xs);
    color: var(--color-error);
    margin-top: var(--spacing-2);
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
