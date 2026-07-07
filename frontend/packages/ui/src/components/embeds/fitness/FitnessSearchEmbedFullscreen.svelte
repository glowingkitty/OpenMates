<!--
  frontend/packages/ui/src/components/embeds/fitness/FitnessSearchEmbedFullscreen.svelte

  Fullscreen renderer for Fitness Urban Sports search embeds.
  Shows the grouped skill result list in an event-style card grid with stable
  data-testid attributes for future Playwright coverage.
-->

<script lang="ts">
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

  interface Props {
    data: EmbedFullscreenRawData;
    onClose: () => void;
  }

  let { data, onClose }: Props = $props();

  let content = $derived(data.decodedContent ?? data.embedData ?? {});
  let firstGroup = $derived(Array.isArray(content.results) ? content.results[0] as Record<string, unknown> | undefined : undefined);
  let results = $derived(Array.isArray(firstGroup?.results) ? firstGroup.results as Record<string, unknown>[] : []);
  let filters = $derived((firstGroup?.filters && typeof firstGroup.filters === 'object') ? firstGroup.filters as Record<string, unknown> : {});
  let skillId = $derived(String(content.skill_id || data.embedData?.skill_id || 'search_classes'));
  let title = $derived(skillId === 'search_locations' ? 'Fitness locations' : 'Fitness classes');
  let summary = $derived(String(firstGroup?.summary || 'Urban Sports Club results'));

  function asText(value: unknown): string {
    if (value === null || value === undefined) return '';
    if (Array.isArray(value)) return value.join(', ');
    return String(value);
  }
</script>

<div class="fitness-fullscreen" data-testid="fitness-search-fullscreen">
  <header class="fitness-fullscreen-header">
    <div>
      <p>Urban Sports Club</p>
      <h2>{title}</h2>
      <span>{summary}</span>
    </div>
    <button type="button" data-testid="fitness-search-close" onclick={onClose}>Close</button>
  </header>

  <div class="fitness-filter-row" data-testid="fitness-search-filters">
    {#each Object.entries(filters) as [key, value]}
      <span>{key}: {asText(value)}</span>
    {/each}
  </div>

  {#if results.length === 0}
    <div class="fitness-empty" data-testid="fitness-search-empty">No Urban Sports results found.</div>
  {:else}
    <div class="fitness-grid" data-testid="search-template-grid">
      {#each results as result}
        <article class="fitness-card" data-testid="embed-preview" data-fitness-card="true">
          <h3>{asText(result.name)}</h3>
          {#if result.venue_name}<p>{asText(result.venue_name)}</p>{/if}
          {#if result.address || result.venue_address}<p>{asText(result.address || result.venue_address)}</p>{/if}
          <div class="fitness-card-meta">
            {#if result.date || result.time_range}<span>{asText(result.date)} {asText(result.time_range)}</span>{/if}
            {#if result.distance_km !== undefined}<span>{asText(result.distance_km)} km</span>{/if}
            {#if result.spots_display || result.spots_left !== undefined}<span>{asText(result.spots_display || result.spots_left)} spots</span>{/if}
          </div>
          {#if result.plans_required}
            <div class="fitness-plan-row">{asText(result.plans_required)}</div>
          {/if}
          {#if result.url || result.detail_url}
            <a href={asText(result.url || result.detail_url)} target="_blank" rel="noopener noreferrer">Open Urban Sports</a>
          {/if}
        </article>
      {/each}
    </div>
  {/if}
</div>

<style>
  .fitness-fullscreen {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    min-height: 100%;
    padding: 1.25rem;
  }

  .fitness-fullscreen-header {
    align-items: flex-start;
    display: flex;
    justify-content: space-between;
    gap: 1rem;
  }

  .fitness-fullscreen-header p,
  .fitness-fullscreen-header span,
  .fitness-card p,
  .fitness-card-meta,
  .fitness-plan-row {
    color: var(--color-font-secondary, #666);
  }

  .fitness-fullscreen-header h2 {
    color: var(--color-font-primary, #111);
    font-size: 1.6rem;
    margin: 0.1rem 0;
  }

  .fitness-fullscreen-header button {
    border: 1px solid var(--color-grey-30, #d8d8d8);
    border-radius: 999px;
    padding: 0.4rem 0.75rem;
  }

  .fitness-filter-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
  }

  .fitness-filter-row span,
  .fitness-plan-row {
    background: var(--color-grey-10, #f5f5f5);
    border-radius: 999px;
    padding: 0.25rem 0.6rem;
  }

  .fitness-grid {
    display: grid;
    gap: 1rem;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  }

  .fitness-card {
    background: var(--color-grey-0, #fff);
    border: 1px solid var(--color-grey-20, #eee);
    border-radius: 1rem;
    box-shadow: 0 4px 16px rgb(0 0 0 / 8%);
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    padding: 1rem;
  }

  .fitness-card h3 {
    color: var(--color-font-primary, #111);
    font-size: 1rem;
    margin: 0;
  }

  .fitness-card p {
    margin: 0;
  }

  .fitness-card-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    font-size: 0.85rem;
  }

  .fitness-card a {
    color: var(--color-button-primary, #635bff);
    font-weight: 650;
    margin-top: auto;
  }
</style>
