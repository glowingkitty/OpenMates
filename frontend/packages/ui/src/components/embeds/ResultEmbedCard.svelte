<!-- Shared visual content for result previews. Callers own data, proxying and actions. -->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import { handleImageError } from '../../utils/offlineImageHandler';
  interface Props {
    title: string;
    titleTestId?: string;
    description?: string;
    sourceLabel?: string;
    faviconUrl?: string;
    imageUrl?: string;
    imageAlt?: string;
    imageTestId?: string;
    mediaFit?: 'cover' | 'contain';
    /** Image previews use the entire card, without title/source copy or a fade. */
    mediaOnly?: boolean;
    textFirst?: boolean;
    badge?: Snippet;
    facts?: Snippet;
    media?: Snippet;
    children?: Snippet;
  }
  let { title, titleTestId = 'result-card-title', description, sourceLabel, faviconUrl, imageUrl, imageAlt = '', imageTestId, mediaFit = 'contain', mediaOnly = false, textFirst = false, badge, facts, media, children }: Props = $props();
  let failedImage = $state<string>();
  let failedFavicon = $state<string>();
  const hasImage = $derived(!!imageUrl && failedImage !== imageUrl);
</script>

<div class="result-card" class:has-media={hasImage || !!media} class:media-only={mediaOnly} class:text-first={textFirst} class:contain-media={mediaFit === 'contain'} data-testid="result-card-content">
  {#if hasImage || media}
    <div class="card-media" data-testid="result-card-media">
      {#if media}{@render media()}{:else if imageUrl}
        <img src={imageUrl} data-testid={imageTestId} alt={imageAlt} loading="lazy" style:object-fit={mediaFit} onerror={(event) => { failedImage = imageUrl; handleImageError(event.currentTarget as HTMLImageElement); }} />
      {/if}
    </div>
  {/if}
  {#if !mediaOnly}
  <div class="card-copy">
    {#if badge}<div class="card-badge">{@render badge()}</div>{/if}
    {#if sourceLabel || (faviconUrl && failedFavicon !== faviconUrl)}
      <div class="card-source">
        {#if faviconUrl && failedFavicon !== faviconUrl}<img src={faviconUrl} alt="" loading="lazy" onerror={(event) => { failedFavicon = faviconUrl; handleImageError(event.currentTarget as HTMLImageElement); }} />{/if}
        {#if sourceLabel}<span>{sourceLabel}</span>{/if}
      </div>
    {/if}
    <h3 data-testid={titleTestId}>{title}</h3>
    {#if description}<p>{description}</p>{/if}
    {#if facts}<div class="card-facts">{@render facts()}</div>{/if}
    {#if children}{@render children()}{/if}
  </div>
  {/if}
</div>

<style>
  .result-card { position: relative; width: 100%; height: 100%; min-width: 0; overflow: hidden; background: var(--color-grey-0); color: var(--color-font-primary); }
  .result-card.has-media:not(.text-first) { display: grid; grid-template-rows: minmax(0, 1fr) auto; }
  .card-media { position: relative; min-height: 0; z-index: 0; isolation: isolate; overflow: hidden; background: var(--color-grey-90); }
  :global([data-theme="dark"]) .card-media { background: var(--color-grey-30); }
  .card-media > img { width: 100%; height: 100%; display: block; }
  .card-media::after { content: ''; position: absolute; inset: auto 0 -1px; height: 20px; background: linear-gradient(transparent, var(--color-grey-0)); pointer-events: none; }
  /* The same safety gap is present with and without carousel arrows. */
  .card-copy { position: static; z-index: 1; box-sizing: border-box; padding: 0 48px 10px; display: flex; flex-direction: column; justify-content: flex-end; gap: var(--spacing-2); min-width: 0; }
  .result-card:not(.has-media) .card-copy, .text-first .card-copy { position: absolute; inset: 0; justify-content: flex-start; padding-top: 52px; }
  .text-first .card-media { display: none; }
  .card-source { display: flex; align-items: center; gap: var(--spacing-2); font-size: var(--font-size-xxs); color: var(--color-font-secondary); min-width: 0; flex-shrink: 0; }
  .card-source img { width: 18px; height: 18px; object-fit: contain; flex: 0 0 auto; }
  .card-source span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  h3 { flex-shrink: 0; margin: 0; color: var(--color-font-primary); font-size: var(--font-size-h4); line-height: 1.25; font-weight: 700; overflow-wrap: anywhere; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; line-clamp: 2; overflow: hidden; text-overflow: ellipsis; }
  p { margin: 0; min-height: 0; font-size: var(--font-size-xs); line-height: 1.4; color: var(--color-font-secondary); display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 3; overflow: hidden; }
  .has-media:not(.text-first) p { display: none; }
  .card-badge { position: absolute; top: 6px; left: 54px; z-index: 1; }
  .card-facts { display: flex; flex-wrap: wrap; gap: var(--spacing-1); min-width: 0; max-height: 3rem; overflow: hidden; color: var(--color-font-secondary); }
  @container result-card (min-width: 401px) {
    .result-card.has-media:not(.text-first) { display: block; }
    .card-copy, .result-card:not(.has-media) .card-copy, .text-first .card-copy { position: absolute; inset: 0; justify-content: center; padding: 54px 48px 48px; }
    .has-media .card-copy { right: 66.6667%; }
    .card-media, .text-first .card-media { position: absolute; display: block; inset: 0 0 0 33.3333%; }
    .card-media::after { display: none; }
    .has-media:not(.text-first) p { display: -webkit-box; -webkit-line-clamp: 4; }
    h3 { font-size: var(--font-size-h3); -webkit-line-clamp: 2; line-clamp: 2; }
    .card-badge { position: static; align-self: flex-start; margin-bottom: var(--spacing-4); }
    .card-facts { max-height: none; }
  }
  .media-only .card-media { position: absolute; display: block; inset: 0; }
  .media-only .card-media::after { display: none; }
</style>
