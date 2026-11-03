<script lang="ts">
  import { getContext } from 'svelte';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import ResultEmbedCard from '../ResultEmbedCard.svelte';
  import { text } from '../../../i18n/translations';
  import { proxyImage } from '../../../utils/imageProxy';
  import { AUTHORED_RESULT_PRESENTATION_CONTEXT, type AuthoredResultPresentationContext } from '../../../types/authoredResult';
  import { readTVTitle } from './tvTitleContent';

  type Status = 'processing' | 'finished' | 'error' | 'cancelled';
  const presentation = getContext<AuthoredResultPresentationContext | undefined>(AUTHORED_RESULT_PRESENTATION_CONTEXT);

  interface Props {
    id: string;
    content: Record<string, unknown>;
    status?: Status;
    isMobile?: boolean;
    resultContext?: 'auto' | 'chat' | 'results';
    onFullscreen: () => void;
  }
  let { id, content, status: statusProp = 'finished', isMobile = false,
    resultContext = 'auto', onFullscreen }: Props = $props();
  let currentContent = $state<Record<string, unknown>>({});
  let status = $state<Status>('processing');
  $effect(() => { currentContent = content; status = statusProp; });
  const model = $derived(readTVTitle(presentation?.presentationContent ?? presentation?.content ?? currentContent, { allowDecryptedMedia: !!presentation }));
  const title = $derived(model.title ?? $text(`embeds.tv.${model.kind}`));
  const kindLabel = $derived($text(`embeds.tv.${model.kind}`));
  const yearLabel = $derived(model.year === undefined ? '' : `${model.year}${model.endYear === undefined ? '' : `–${model.endYear}`}`);
  const previewFacts = $derived([
    yearLabel,
    model.runtimeMinutes === undefined ? '' : $text('embeds.search_domain.minutes', { values: { count: model.runtimeMinutes } }),
    model.seasonCount === undefined ? '' : $text('embeds.tv.season_count', { values: { count: model.seasonCount } }),
  ].filter(Boolean).join(' · '));
  const imageUrl = $derived(model.posterUrl ? proxyImage(model.posterUrl, 960) : '');
  const scoreSource = $derived(model.score ? model.score.sourceLabel ?? new URL(model.score.sourceUrl).hostname : '');
  function updated(update: { status: string; decodedContent: Record<string, unknown> }) {
    currentContent = update.decodedContent;
    if (['processing', 'finished', 'error', 'cancelled'].includes(update.status)) status = update.status as Status;
  }
</script>

<UnifiedEmbedPreview {id} {status} {isMobile} {resultContext} {onFullscreen}
  appId="tv" appIconName="tv" skillId={model.kind} skillIconName={model.kind === 'movie' ? 'movies' : 'tv'}
  skillName={title} resultPreview showStatus={false} showSkillIcon={false}
  authoring={model.authoring} onEmbedDataUpdated={updated}>
  {#snippet details()}
    <div class="tv-preview" data-testid="tv-title-preview" data-kind={model.kind} data-status={status}>
      {#if status === 'finished'}
        <ResultEmbedCard {title} titleTestId="tv-title" {imageUrl} imageAlt={title}
          imageTestId="tv-poster" mediaFit="contain" sourceLabel={kindLabel}
          description={[model.genres.join(' · '), model.synopsis].filter(Boolean).join(' — ')}>
          {#snippet facts()}
            {#if previewFacts}<span class="tv-facts" data-testid="tv-preview-facts">{previewFacts}</span>{/if}
            {#if model.score}<span class="tv-score" data-testid="tv-preview-score">{model.score.value} / {model.score.scale} · {scoreSource}</span>{/if}
          {/snippet}
        </ResultEmbedCard>
      {:else}
        <p class="tv-state" role="status" data-testid="tv-title-state">{$text(status === 'processing' ? 'embeds.tv.preparing' : status === 'cancelled' ? 'embeds.tv.cancelled' : 'embeds.tv.unavailable')}</p>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .tv-preview { height: 100%; min-width: 0; width: 100%; }
  .tv-facts, .tv-score { font-size: var(--font-size-xs); line-height: 1.35; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; }
  .tv-state { display: grid; place-items: center; height: 100%; margin: 0; padding: var(--spacing-12) var(--spacing-24); box-sizing: border-box; color: var(--color-font-secondary); font-size: var(--font-size-small); text-align: center; }
</style>
