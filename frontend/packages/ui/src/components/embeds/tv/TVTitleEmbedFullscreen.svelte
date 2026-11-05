<script lang="ts">
  import { getContext } from 'svelte';
  import ResultEmbedFullscreen from '../ResultEmbedFullscreen.svelte';
  import ResultEmbedInfo from '../ResultEmbedInfo.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import { text } from '../../../i18n/translations';
  import { proxyImage } from '../../../utils/imageProxy';
  import { AUTHORED_RESULT_PRESENTATION_CONTEXT, type AuthoredResultPresentationContext } from '../../../types/authoredResult';
  import type { EmbedFullscreenCommonProps, EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { readTVTitle, tvFollowupContext } from './tvTitleContent';

  const presentation = getContext<AuthoredResultPresentationContext | undefined>(AUTHORED_RESULT_PRESENTATION_CONTEXT);

  interface Props extends EmbedFullscreenCommonProps { data: EmbedFullscreenRawData; }
  let { data, embedId, onClose, hasPreviousEmbed, hasNextEmbed, onNavigatePrevious,
    onNavigateNext, navigateDirection, showChatButton, onShowChat }: Props = $props();
  const content = $derived(presentation?.presentationContent ?? presentation?.content ?? data.decodedContent);
  const model = $derived(readTVTitle(content, { allowDecryptedMedia: !!presentation }));
  const title = $derived(model.title ?? $text(`embeds.tv.${model.kind}`));
  const ready = $derived(!content.status || content.status === 'finished');
  const id = $derived(embedId ?? String(data.embedData?.embed_id ?? data.attrs?.id ?? ''));
  let failedPoster = $state<string>();
  let failedSeasonPosters = $state<Record<string, boolean>>({});
  const imageUrl = $derived(model.posterUrl ? proxyImage(model.posterUrl, 1200) : '');
  const scoreSource = $derived(model.score ? model.score.sourceLabel ?? new URL(model.score.sourceUrl).hostname : '');
  const details = $derived([
    { key: 'directors', value: model.directors.join(', ') },
    { key: 'creators', value: model.creators.join(', ') },
    { key: 'cast', value: model.cast.join(', ') },
    { key: 'genres', value: model.genres.join(' · ') },
    { key: 'language', value: model.language },
    { key: 'countries', value: model.countries.join(', ') },
    { key: 'content_rating', value: model.contentRating },
    { key: 'series_status', value: model.seriesStatus },
    { key: 'release_date', value: model.releaseDate },
    { key: 'first_air_date', value: model.firstAirDate },
    { key: 'last_air_date', value: model.lastAirDate },
  ].filter(fact => fact.value));
</script>

<ResultEmbedFullscreen result={tvFollowupContext(model)} appId="tv" skillId={model.kind}
  skillIconName={model.kind === 'movie' ? 'movies' : 'tv'} appIconName="tv" authoring={model.authoring}
  embedHeaderTitle={title} embedHeaderSubtitle={$text(`embeds.tv.${model.kind}`)}
  {onClose} {hasPreviousEmbed} {hasNextEmbed} {onNavigatePrevious} {onNavigateNext}
  {navigateDirection} {showChatButton} {onShowChat} currentEmbedId={id} mediaLayout="immersive">
  {#snippet embedHeaderCta()}
    {#if ready && model.sourceUrl}<EmbedHeaderCtaButton label={$text('embeds.authoring.open_source')} href={model.sourceUrl} testId="tv-open-source" />{/if}
  {/snippet}
  {#snippet summary()}
    {#if ready}
      {#if model.year !== undefined}<ResultEmbedInfo icon="Calendar" label={$text('embeds.tv.year')} value={`${model.year}${model.endYear === undefined ? '' : `–${model.endYear}`}`} testId="tv-year" />{/if}
      {#if model.runtimeMinutes !== undefined}<ResultEmbedInfo icon="Clock" label={$text('embeds.tv.runtime')} value={$text('embeds.search_domain.minutes', { values: { count: model.runtimeMinutes } })} testId="tv-runtime" />{/if}
      {#if model.seasonCount !== undefined}<ResultEmbedInfo icon="Layers" label={$text('embeds.tv.supplied_seasons')} value={$text('embeds.tv.season_count', { values: { count: model.seasonCount } })} testId="tv-season-total" />{/if}
      {#if model.episodeCount !== undefined}<ResultEmbedInfo icon="Tv" label={$text('embeds.tv.episodes')} value={$text('embeds.tv.episode_count', { values: { count: model.episodeCount } })} testId="tv-episode-total" />{/if}
      {#if model.score}<ResultEmbedInfo icon="Star" label={$text('embeds.tv.score')} value={`${model.score.value} / ${model.score.scale}`} caption={scoreSource} testId="tv-score" />{/if}
    {/if}
  {/snippet}
  {#snippet media()}
    {#if ready}
      {#if imageUrl && imageUrl !== failedPoster}<img class="result-primary-media" src={imageUrl} alt={title} data-testid="tv-fullscreen-poster" onerror={() => failedPoster = imageUrl} />
      {:else}<div class="tv-poster-fallback" data-testid="tv-poster-fallback"><span class="poster-symbol" aria-hidden="true"></span><span>{$text('embeds.tv.poster_unavailable')}</span></div>{/if}
    {/if}
  {/snippet}
  {#snippet detailContent()}
    <div class="tv-details" data-testid="tv-title-fullscreen" data-kind={model.kind}>
      {#if ready}
        {#if model.synopsis}<section aria-label={$text('embeds.tv.synopsis')}><h3>{$text('embeds.tv.synopsis')}</h3><p class="result-description synopsis" data-testid="tv-synopsis">{model.synopsis}</p></section>{/if}
        {#if details.length}<dl class="tv-metadata" data-testid="tv-metadata">{#each details as fact (fact.key)}<div><dt>{$text(`embeds.tv.${fact.key}`)}</dt><dd>{fact.value}</dd></div>{/each}</dl>{/if}
        {#if model.score}<section class="score-context" data-testid="tv-score-source"><h3>{$text('embeds.tv.score')}</h3>
          <a href={model.score.sourceUrl} target="_blank" rel="noopener noreferrer">{scoreSource}</a>
          {#if model.score.votes !== undefined}<span>{$text('embeds.tv.score_votes', { values: { count: model.score.votes } })}</span>{/if}
          {#if model.score.observedAt}<span>{$text('embeds.authoring.observed_at')}: <time>{model.score.observedAt}</time></span>{/if}
        </section>{/if}
        {#if model.seasons.length}<section class="tv-seasons" data-testid="tv-seasons"><h3>{$text('embeds.tv.supplied_seasons')}</h3>
          <p class="partial-guide" data-testid="tv-partial-guide">{$text('embeds.tv.partial_seasons')}</p>
          {#each model.seasons as season (season.number)}
            <article class="tv-season" data-testid="tv-season" data-season-number={season.number}>
              {#if season.posterUrl && !failedSeasonPosters[season.posterUrl]}<img src={proxyImage(season.posterUrl, 240)} alt={season.title ?? $text('embeds.tv.season', { values: { number: season.number } })} loading="lazy" onerror={() => { if (season.posterUrl) failedSeasonPosters[season.posterUrl] = true; }} />{/if}
              <div><h4>{season.number === 0 ? $text('embeds.tv.specials') : $text('embeds.tv.season', { values: { number: season.number } })}</h4>
                {#if season.title}<p class="season-title">{season.title}</p>{/if}
                {#if season.firstAirDate}<time>{season.firstAirDate}</time>{/if}
                {#if season.episodeCount !== undefined}<p>{$text('embeds.tv.episode_count', { values: { count: season.episodeCount } })}</p>{/if}
                {#if season.synopsis}<p class="result-description synopsis">{season.synopsis}</p>{/if}
              </div>
            </article>
          {/each}
        </section>{/if}
      {:else}<p role="status" data-testid="tv-fullscreen-state">{$text(content.status === 'processing' ? 'embeds.tv.preparing' : content.status === 'cancelled' ? 'embeds.tv.cancelled' : 'embeds.tv.unavailable')}</p>{/if}
    </div>
  {/snippet}
</ResultEmbedFullscreen>

<style>
  .tv-poster-fallback { display: grid; place-items: center; gap: var(--spacing-4); padding: var(--spacing-12); color: var(--color-font-secondary); text-align: center; }
  .poster-symbol { width: 3rem; height: 3rem; background: currentColor; mask: url('@openmates/ui/static/icons/tv.svg') center / contain no-repeat; }
  .tv-details { width: 100%; min-width: 0; }
  section { width: 100%; margin-bottom: var(--spacing-10); }
  h3, h4 { margin: 0 0 var(--spacing-4); font-size: var(--font-size-h4); font-weight: 600; }
  p { margin: 0 0 var(--spacing-4); font-size: var(--font-size-small); line-height: 1.55; }
  .synopsis { overflow-wrap: anywhere; }
  .tv-metadata { display: grid; gap: var(--spacing-6); margin: 0 0 var(--spacing-10); }
  .tv-metadata > div { display: grid; gap: var(--spacing-2); }
  dt, .partial-guide { color: var(--color-font-secondary); font-size: var(--font-size-small); }
  dd { margin: 0; font-size: var(--font-size-small); overflow-wrap: anywhere; }
  .score-context { display: flex; flex-wrap: wrap; align-items: center; gap: var(--spacing-4); font-size: var(--font-size-small); }
  .score-context h3 { width: 100%; margin: 0; }
  a { color: var(--color-primary); overflow-wrap: anywhere; }
  a:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 2px; }
  .tv-season { display: flex; align-items: flex-start; gap: var(--spacing-6); padding-block: var(--spacing-6); border-bottom: 1px solid var(--color-grey-25); }
  .tv-season img { width: 4.5rem; max-height: 7rem; object-fit: contain; }
  .tv-season > div { min-width: 0; }
  .tv-season time { display: block; color: var(--color-font-secondary); font-size: var(--font-size-small); }
  .season-title { font-weight: 500; }
  @container fullscreen (min-width: 600px) { .tv-metadata > div { grid-template-columns: minmax(8rem, 1fr) minmax(0, 2fr); gap: var(--spacing-6); } }
</style>
