<script lang="ts">
  import { text } from '../../i18n/translations';
  import type { AuthoredResultMetadata } from '../../types/authoredResult';
  import { authoredSourceUrl } from '../../utils/authoredResultPresentation';

  let { authoring, compact = false }: { authoring?: AuthoredResultMetadata; compact?: boolean } = $props();
  const sources = $derived((authoring?.sources ?? []).filter(source => source && typeof source === 'object'));
  const domain = $derived.by(() => {
    const url = sources.map(source => authoredSourceUrl(source.url)).find(Boolean);
    return url ? new URL(url).hostname.replace(/^www\./, '') : '';
  });
  const originLabel = $derived(authoring?.origin === 'draft' ? $text('embeds.authoring.draft')
    : authoring?.origin === 'user_provided' ? $text('embeds.authoring.user_provided') : domain);
  const observed = $derived.by(() => {
    if (!authoring?.observed_at) return '';
    const value = new Date(authoring.observed_at);
    return Number.isNaN(value.getTime()) ? '' : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(value);
  });
  const credits = $derived((authoring?.images ?? []).filter(image => image && typeof image === 'object' && image.attribution));
</script>

{#if authoring}
  <aside class="authored-context" class:compact data-testid="authored-result-context" data-origin={authoring.origin} aria-label={originLabel || $text('embeds.authoring.sources')}>
    {#if originLabel}<span class="origin" data-testid="authored-result-origin">{originLabel}</span>{/if}
    {#if !compact}
      {#if sources.length}
        <div class="sources"><span>{$text('embeds.authoring.sources')}</span>
          {#each sources as source}
            {@const url = authoredSourceUrl(source.url)}
            {#if url}<a href={url} target="_blank" rel="noopener noreferrer">{source.label || new URL(url).hostname}</a>
            {:else}<span>{source.label || $text('embeds.authoring.uploaded_source')}</span>{/if}
          {/each}
        </div>
      {/if}
      {#if observed}<span>{$text('embeds.authoring.observed_at')}: {observed}</span>{/if}
      {#each credits as image}
        {#if typeof image === 'object'}<span>{$text('embeds.authoring.image_credit')}: {image.attribution}</span>{/if}
      {/each}
    {/if}
  </aside>
{/if}

<style>
  .authored-context { display: flex; flex-wrap: wrap; justify-content: center; gap: var(--spacing-2); max-width: 100%; font-size: 0.75rem; color: var(--color-font-secondary); line-height: 1.5; }
  .origin { font-weight: 600; }
  .sources { display: flex; flex-wrap: wrap; justify-content: center; gap: var(--spacing-2); }
  a { color: var(--color-primary); overflow-wrap: anywhere; }
  .compact { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding: 0.125rem var(--spacing-2); border-radius: var(--radius-8); background: var(--color-grey-0); }
</style>
