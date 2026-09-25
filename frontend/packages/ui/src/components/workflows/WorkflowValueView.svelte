<!-- Readable in-memory workflow values. Preview cards never create saved embeds. -->
<script lang="ts">
  import type { ComponentProps } from 'svelte';
  import { text } from '../../i18n/translations';
  import type { Schema } from './workflowBuilder';
  import { valueEntries, valueLabel, workflowValue, readableScalar } from './workflowValuePresentation';
  import EventEmbedPreview from '../embeds/events/EventEmbedPreview.svelte';
  import HomeListingEmbedPreview from '../embeds/home/HomeListingEmbedPreview.svelte';
  import NewsEmbedPreview from '../embeds/news/NewsEmbedPreview.svelte';

  let { value, schema, appId = '', path = 'value' }: { value: unknown; schema?: Schema; appId?: string; path?: string } = $props();
  let expandedResult = $state<string | null>(null);
  const rootValue = $derived(workflowValue(value));
  const tr = (key: string, values?: Record<string, unknown>) => $text(`workflows.builder.${key}`, values);
  const string = (value: unknown): string | undefined => typeof value === 'string' ? value : undefined;
  const number = (value: unknown): number | undefined => typeof value === 'number' ? value : undefined;
  function resultKind(item: Record<string, unknown>): string {
    if (!item.title) return '';
    if (item.date_start || item.type === 'event_result') return 'events';
    if (item.price_label || item.size_sqm || item.type === 'home_listing') return 'home';
    if (item.url && (appId === 'news' || item.type === 'news_result' || item.type === 'news_article')) return 'news';
    return '';
  }
  function eventData(item: Record<string, unknown>, id: string): ComponentProps<typeof EventEmbedPreview>['event'] { return { ...item, embed_id: id }; }
  function toggleResult(id: string): void { expandedResult = expandedResult === id ? null : id; }
</script>

{#snippet fields(data: unknown, spec: Schema | undefined, id: string)}
  <dl class="value-fields">{#each valueEntries(data) as [key, child]}<div><dt>{spec?.properties?.[key]?.title || valueLabel(key)}</dt><dd>{@render present(child, spec?.properties?.[key], `${id}.${key}`, key)}</dd></div>{/each}</dl>
{/snippet}

{#snippet present(raw: unknown, spec: Schema | undefined, id: string, key = '')}
  {@const data = workflowValue(raw)}
  {#if data === undefined || data === null || data === ''}<span class="muted">{tr('unavailable')}</span>
  {:else if typeof data === 'boolean'}<span>{tr(data ? 'true' : 'false')}</span>
  {:else if Array.isArray(data)}
    {#if !data.length}<span class="muted">{tr('output_empty_list')}</span>{:else}
      <details class="value-collection"><summary>{tr('output_item_count', { values: { count: data.length } })}</summary><div class="value-list">{#each data as item, index}<div class="value-item">{@render present(item, spec?.items, `${id}.${index}`, key)}</div>{/each}</div></details>
    {/if}
  {:else if typeof data === 'object'}
    {@const item = data as Record<string, unknown>}
    {@const kind = resultKind(item)}
    {#if kind}
      <div class="result-card">
        {#if kind === 'events'}<EventEmbedPreview id={`workflow-preview-${id}`} event={eventData(item, id)} onFullscreen={() => toggleResult(id)} />
        {:else if kind === 'home'}<HomeListingEmbedPreview embed_id={`workflow-preview-${id}`} title={string(item.title)} price_label={string(item.price_label)} size_sqm={number(item.size_sqm)} rooms={number(item.rooms)} address={string(item.address)} image_url={string(item.image_url)} url={string(item.url)} provider={string(item.provider)} available_from={string(item.available_from)} onSelect={() => toggleResult(id)} />
        {:else}<NewsEmbedPreview id={`workflow-preview-${id}`} url={string(item.url) ?? ''} title={string(item.title)} description={string(item.description) ?? string(item.summary)} image={string(item.image_url) ?? string(item.image)} status="finished" onFullscreen={() => toggleResult(id)} />{/if}
        {#if expandedResult === id}<div class="result-details">{@render fields(item, spec, id)}</div>{/if}
      </div>
    {:else if valueEntries(item).length}
      <details class="value-collection"><summary>{tr('details')}</summary>{@render fields(item, spec, id)}</details>
    {:else}<span class="muted">{tr('unavailable')}</span>{/if}
  {:else if typeof data === 'string' && /^https?:\/\/\S+$/.test(data)}<a href={data} target="_blank" rel="noopener noreferrer">{data}</a>
  {:else}<span class="scalar">{readableScalar(data, key || spec?.format || '')}</span>{/if}
{/snippet}

<div class="workflow-value" data-testid="workflow-readable-value">
  {#if rootValue && typeof rootValue === 'object' && !Array.isArray(rootValue) && !resultKind(rootValue as Record<string, unknown>)}{@render fields(rootValue, schema, path)}
  {:else}{@render present(rootValue, schema, path, path.split('.').at(-1) ?? '')}{/if}
</div>

<style>
  .workflow-value{min-width:0;text-align:start;font:inherit;font-size:16px;color:var(--color-font-primary);overflow-wrap:anywhere}.scalar{white-space:pre-wrap;line-height:1.5;user-select:text}.muted{color:var(--color-font-secondary)}.value-fields{margin:0;display:grid;gap:.6rem}.value-fields>div{display:grid;grid-template-columns:minmax(5rem,1fr) minmax(0,1.5fr);gap:.8rem;align-items:start}.value-fields dt{color:var(--color-font-secondary);font-weight:500}.value-fields dd{margin:0;min-width:0}.value-collection{min-width:0}.value-collection>summary{cursor:pointer;color:var(--color-primary);font-weight:600;padding:.2rem 0;user-select:none}.value-collection[open]>summary{margin-bottom:.5rem}.value-list{display:grid;gap:.75rem;max-height:28rem;overflow-y:auto;padding:.25rem}.value-item{min-width:0;padding:.55rem;background:var(--color-grey-0);border-radius:.65rem}.result-card{min-width:0;width:100%}.result-details{margin-top:.7rem;padding:.7rem;border:1px solid var(--color-grey-20);border-radius:.65rem}.result-card :global(.unified-embed-preview){max-width:100%}.workflow-value :global(*){font-size:max(14px,1em)}a{color:var(--color-primary);text-decoration:underline}summary:focus-visible,a:focus-visible{outline:2px solid var(--color-primary);outline-offset:3px}@media(max-width:550px){.value-fields>div{grid-template-columns:1fr;gap:.2rem}}
</style>
