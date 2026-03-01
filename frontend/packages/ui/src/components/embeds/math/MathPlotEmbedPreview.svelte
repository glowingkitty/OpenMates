<!--
  frontend/packages/ui/src/components/embeds/math/MathPlotEmbedPreview.svelte

  Preview card for math-plot direct-type embeds.
  Shows the function formulas as monospace text — the interactive graph renders
  in the fullscreen panel only (function-plot is too large for the 300×200px card).

  These embeds are created automatically by stream_consumer.py when the LLM
  outputs a ```plot ... ``` fenced code block containing function definitions.

  States:
  - processing: Shows a loading placeholder (axis crosshairs) while the plot is being set up
  - finished:   Shows the function definitions as monospace text, tap to open fullscreen
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
      {:else if status === 'finished' && formulaLines.length > 0}
        <!-- Show function definitions as monospace text — graph is in fullscreen -->
        <div class="formula-list">
          {#each formulaLines as line}
            <div class="formula-line"><code>{line}</code></div>
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
    gap: 5px;
    overflow: hidden;
  }

  .formula-line {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .formula-line code {
    font-family: 'Courier New', Courier, monospace;
    font-size: 13px;
    font-weight: 500;
    color: var(--color-grey-100);
  }

  .math-plot-details.mobile .formula-line code {
    font-size: 11px;
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
