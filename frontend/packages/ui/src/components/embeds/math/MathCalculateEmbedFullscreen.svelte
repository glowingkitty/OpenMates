<!--
  frontend/packages/ui/src/components/embeds/math/MathCalculateEmbedFullscreen.svelte

  Fullscreen view for Math / Calculate skill embeds.
  Uses UnifiedEmbedFullscreen as base.

  Layout:
  - EmbedTopBar (share / copy / close) — handled by UnifiedEmbedFullscreen
  - EmbedHeader (gradient banner with expression + subtitle) — handled by UnifiedEmbedFullscreen
  - Scrollable content area — shows all calculation results
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

  /**
   * Individual calculation result from the backend TOON content.
   */
  type CalculateStep = string | {
    description?: string;
    expression?: string;
    result?: string;
    latex?: string;
  };

  interface CalculateResult {
    expression?: string;
    expression_latex?: string;
    result?: string;
    result_latex?: string;
    result_type?: string;
    mode?: string;
    steps?: CalculateStep[];
    error?: string;
  }

  /**
   * Normalize an unknown status value to a valid embed status string.
   */
  function normalizeStatus(value: unknown): 'processing' | 'finished' | 'error' | 'cancelled' {
    if (value === 'processing' || value === 'finished' || value === 'error' || value === 'cancelled') return value;
    return 'finished';
  }

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
  let queryProp = $derived(
    typeof dc.query === 'string'
      ? dc.query
      : typeof dc.expression === 'string'
        ? dc.expression
        : undefined
  );
  let subtitleProp = $derived(typeof dc.subtitle === 'string' ? dc.subtitle : undefined);
  let statusProp = $derived(normalizeStatus(dc.status));
  let resultsProp = $derived(Array.isArray(dc.results) ? dc.results as CalculateResult[] : undefined);

  // ── Local state ─────────────────────────────────────────────────────────────
  let localQuery    = $state('');
  let localSubtitle = $state('');
  let localStatus   = $state<'processing' | 'finished' | 'error' | 'cancelled'>('finished');
  let localResults  = $state<CalculateResult[]>([]);

  $effect(() => {
    localQuery    = queryProp    || '';
    localSubtitle = subtitleProp || '';
    localStatus   = statusProp   || 'finished';
    localResults  = resultsProp  || [];
  });

  let query    = $derived(localQuery);
  let subtitle = $derived(localSubtitle);
  let status   = $derived(localStatus);
  let results  = $derived(localResults);
  let primaryExpression = $derived(query || results[0]?.expression || '');

  // ── Embed data updates ───────────────────────────────────────────────────────
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (!data.decodedContent) return;
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    const c = data.decodedContent;
    if (typeof c.query === 'string') localQuery = c.query;
    else if (typeof c.expression === 'string') localQuery = c.expression;
    if (Array.isArray(c.results)) localResults = c.results as CalculateResult[];
  }

  function calculationExpression(result: CalculateResult): string {
    return query || result.expression || '';
  }

  function stepText(step: CalculateStep): string {
    if (typeof step === 'string') return step;
    if (step.expression && step.result) return `${step.expression} = ${step.result}`;
    if (step.description && step.latex) return `${step.description}: ${step.latex}`;
    return step.latex || step.description || '';
  }

  function fallbackStep(result: CalculateResult): string {
    const expression = calculationExpression(result);
    if (!expression || !result.result) return '';
    return `${expression} = ${result.result}`;
  }

  /**
   * Map mode identifier to a human-readable label.
   */
  function modeLabel(mode?: string): string {
    const modes: Record<string, string> = {
      numeric: 'Numeric',
      symbolic: 'Symbolic',
      solve: 'Solve',
      simplify: 'Simplify',
      diff: 'Differentiate',
      integrate: 'Integrate',
      convert: 'Convert',
    };
    return mode ? (modes[mode] || mode) : '';
  }
</script>

<UnifiedEmbedFullscreen
  appId="math"
  skillId="calculate"
  embedHeaderTitle="Calculation"
  embedHeaderSubtitle={subtitle || primaryExpression}
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
    {#if status === 'error'}
      <div class="error-state">
        <p class="ds-error-title">{$text('embeds.search_failed')}</p>
      </div>
    {:else if results.length === 0}
      {#if status === 'processing'}
        <div class="loading-state"><p>{$text('common.loading')}</p></div>
      {:else}
        <div class="loading-state"><p>No results.</p></div>
      {/if}
    {:else}
      <div class="results-list">
        {#each results as result}
          <div class="result-card">
            <!-- Expression -->
            {#if calculationExpression(result)}
              <section class="calculation-section">
                <h3>Expression</h3>
                <div class="result-expression">{calculationExpression(result)}</div>
              </section>
            {/if}

            <!-- Result value -->
            {#if result.error}
              <div class="result-error">{result.error}</div>
            {:else if result.result}
              <section class="calculation-section">
                <h3>Result</h3>
                <div class="result-value">{result.result}</div>
              </section>
              {#if result.result_type}
                <div class="result-meta">Type: {result.result_type}</div>
              {/if}
              {#if result.mode}
                <div class="result-meta">Mode: {modeLabel(result.mode)}</div>
              {/if}
            {/if}

            <!-- Steps (or a compact fallback calculation trace) -->
            {#if result.steps && result.steps.length > 0}
              <section class="calculation-section result-steps">
                <h3>Calculation</h3>
                <ol>
                  {#each result.steps as step}
                    <li>{stepText(step)}</li>
                  {/each}
                </ol>
              </section>
            {:else if fallbackStep(result)}
              <section class="calculation-section result-steps">
                <h3>Calculation</h3>
                <div class="calculation-line">{fallbackStep(result)}</div>
              </section>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  /* ── Loading / empty states ─────────────────────────────────────────────── */

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

  /* ── Results list ────────────────────────────────────────────────────────── */

  .results-list {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-8);
    padding: var(--spacing-12) var(--spacing-8);
    padding-bottom: 120px;
    max-width: 800px;
    margin: 0 auto;
  }

  /* ── Result card ─────────────────────────────────────────────────────────── */

  .result-card {
    background: var(--color-grey-10, #f5f5f5);
    border-radius: var(--radius-5);
    padding: var(--spacing-10);
    display: flex;
    flex-direction: column;
    gap: var(--spacing-6);
  }

  .calculation-section {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
  }

  .calculation-section h3 {
    margin: 0;
    font-size: var(--font-size-xs);
    font-weight: 700;
    color: var(--color-grey-70);
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .result-expression {
    font-size: var(--font-size-small);
    font-weight: 400;
    color: var(--color-grey-70);
    font-family: 'Courier New', Courier, monospace;
    word-break: break-all;
  }

  .result-value {
    font-size: var(--font-size-xxl);
    font-weight: 700;
    color: var(--color-grey-100);
    font-family: 'Courier New', Courier, monospace;
    word-break: break-all;
    line-height: 1.2;
  }

  .result-meta {
    font-size: var(--font-size-xs);
    color: var(--color-grey-70);
    font-weight: 400;
  }

  .result-error {
    font-size: var(--font-size-small);
    color: var(--color-error);
    font-weight: 500;
  }

  /* ── Steps ───────────────────────────────────────────────────────────────── */

  .result-steps {
    margin-top: var(--spacing-4);
    font-size: var(--font-size-small);
    color: var(--color-grey-70);
  }

  .result-steps ol {
    padding-left: var(--spacing-10);
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
    font-family: 'Courier New', Courier, monospace;
    font-size: var(--font-size-xs);
  }

  .calculation-line {
    font-family: 'Courier New', Courier, monospace;
    font-size: var(--font-size-small);
    color: var(--color-grey-100);
    word-break: break-all;
  }

  /* ── Skill icon ──────────────────────────────────────────────────────────── */

  :global(.unified-embed-fullscreen-overlay .skill-icon[data-skill-icon="math"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/math.svg');
    mask-image: url('@openmates/ui/static/icons/math.svg');
  }
</style>
