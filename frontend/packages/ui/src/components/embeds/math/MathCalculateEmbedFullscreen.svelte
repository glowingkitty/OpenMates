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
  interface CalculateResult {
    expression?: string;
    result?: string;
    result_type?: string;
    mode?: string;
    steps?: string[];
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
  let queryProp = $derived(typeof dc.query === 'string' ? dc.query : undefined);
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

  // ── Embed data updates ───────────────────────────────────────────────────────
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    if (!data.decodedContent) return;
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error' || data.status === 'cancelled') {
      localStatus = data.status;
    }
    const c = data.decodedContent;
    if (typeof c.query === 'string') localQuery = c.query;
    if (Array.isArray(c.results)) localResults = c.results as CalculateResult[];
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
  embedHeaderTitle={query || 'Calculation'}
  embedHeaderSubtitle={subtitle}
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
        <p class="error-title">{$text('embeds.search_failed')}</p>
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
            {#if result.expression}
              <div class="result-expression">{result.expression}</div>
            {/if}

            <!-- Result value -->
            {#if result.error}
              <div class="result-error">{result.error}</div>
            {:else if result.result}
              <div class="result-value">{result.result}</div>
              {#if result.result_type}
                <div class="result-meta">Type: {result.result_type}</div>
              {/if}
              {#if result.mode}
                <div class="result-meta">Mode: {modeLabel(result.mode)}</div>
              {/if}
            {/if}

            <!-- Steps (if provided) -->
            {#if result.steps && result.steps.length > 0}
              <details class="result-steps">
                <summary>Steps</summary>
                <ol>
                  {#each result.steps as step}
                    <li>{step}</li>
                  {/each}
                </ol>
              </details>
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

  /* ── Results list ────────────────────────────────────────────────────────── */

  .results-list {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 24px 16px;
    padding-bottom: 120px;
    max-width: 800px;
    margin: 0 auto;
  }

  /* ── Result card ─────────────────────────────────────────────────────────── */

  .result-card {
    background: var(--color-grey-10, #f5f5f5);
    border-radius: 12px;
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .result-expression {
    font-size: 14px;
    font-weight: 400;
    color: var(--color-grey-70);
    font-family: 'Courier New', Courier, monospace;
    word-break: break-all;
  }

  .result-value {
    font-size: 28px;
    font-weight: 700;
    color: var(--color-grey-100);
    font-family: 'Courier New', Courier, monospace;
    word-break: break-all;
    line-height: 1.2;
  }

  .result-meta {
    font-size: 13px;
    color: var(--color-grey-70);
    font-weight: 400;
  }

  .result-error {
    font-size: 14px;
    color: var(--color-error);
    font-weight: 500;
  }

  /* ── Steps ───────────────────────────────────────────────────────────────── */

  .result-steps {
    margin-top: 8px;
    font-size: 14px;
    color: var(--color-grey-70);
  }

  .result-steps summary {
    cursor: pointer;
    font-weight: 500;
    color: var(--color-grey-100);
    margin-bottom: 6px;
  }

  .result-steps ol {
    padding-left: 20px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-family: 'Courier New', Courier, monospace;
    font-size: 13px;
  }

  /* ── Skill icon ──────────────────────────────────────────────────────────── */

  :global(.unified-embed-fullscreen-overlay .skill-icon[data-skill-icon="math"]) {
    -webkit-mask-image: url('@openmates/ui/static/icons/math.svg');
    mask-image: url('@openmates/ui/static/icons/math.svg');
  }
</style>
