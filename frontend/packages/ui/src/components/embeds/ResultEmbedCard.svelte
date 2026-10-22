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
    textFirst?: boolean;
    badge?: Snippet;
    facts?: Snippet;
    media?: Snippet;
    children?: Snippet;
  }
  let { title, titleTestId = 'result-card-title', description, sourceLabel, faviconUrl, imageUrl, imageAlt = '', imageTestId, mediaFit = 'cover', textFirst = false, badge, facts, media, children }: Props = $props();
  let failedImage = $state<string>();
  let failedFavicon = $state<string>();
  const hasImage = $derived(!!imageUrl && failedImage !== imageUrl);
</script>

<div class="result-card" class:has-media={hasImage || !!media} class:text-first={textFirst} class:contain-media={mediaFit === 'contain'} data-testid="result-card-content">
  {#if hasImage || media}
    <div class="card-media" data-testid="result-card-media">
      {#if media}{@render media()}{:else if imageUrl}
        <img src={imageUrl} data-testid={imageTestId} alt={imageAlt} loading="lazy" style:object-fit={mediaFit} onerror={(event) => { failedImage = imageUrl; handleImageError(event.currentTarget as HTMLImageElement); }} />
      {/if}
    </div>
  {/if}
  {#if badge}<div class="card-badge">{@render badge()}</div>{/if}
  <div class="card-copy">
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
</div>

<style>
  .result-card { position: relative; width: 100%; height: 100%; min-width: 0; overflow: hidden; background: var(--color-grey-0); color: var(--color-font-primary); }
  .card-media { position: absolute; inset: 0 0 30%; }
  .card-media > img { width: 100%; height: 100%; display: block; }
  .card-media::after { content: ''; position: absolute; inset: 35% 0 -1px; background: linear-gradient(transparent, var(--color-grey-0)); pointer-events: none; }
  .contain-media.has-media:not(.text-first) { display: grid; grid-template-rows: minmax(0, 1fr) auto; }
  .contain-media.has-media:not(.text-first) .card-media { position: relative; inset: auto; min-height: 0; overflow: hidden; }
  .contain-media.has-media:not(.text-first) .card-copy { position: relative; inset: auto; box-sizing: border-box; }
  .contain-media .card-media::after { display: none; }
  .card-copy { position: absolute; inset: auto 0 0; padding: var(--spacing-4); display: flex; flex-direction: column; gap: var(--spacing-2); min-width: 0; }
  .result-card:not(.has-media) .card-copy, .text-first .card-copy { inset: 0; justify-content: flex-start; padding-top: 3rem; box-sizing: border-box; }
  .result-card:not(.has-media) .card-source, .text-first .card-source,
  .result-card:not(.has-media) h3, .text-first h3,
  .result-card:not(.has-media) .card-facts, .text-first .card-facts { flex-shrink: 0; }
  .result-card:not(.has-media) p, .text-first p { -webkit-line-clamp: 5; min-height: 0; flex: 0 1 auto; }
  .text-first .card-media { display: none; }
  .card-source { display: flex; align-items: center; gap: var(--spacing-2); font-size: var(--font-size-xxs); color: var(--color-font-secondary); min-width: 0; }
  .card-source img { width: 20px; height: 20px; object-fit: contain; flex: 0 0 auto; }
  .card-source span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  h3 { margin: 0; font-size: var(--font-size-h4); line-height: 1.3; font-weight: 600; overflow-wrap: anywhere; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; }
  p { margin: 0; font-size: var(--font-size-xs); line-height: 1.45; color: var(--color-font-secondary); display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; }
  .has-media:not(.text-first) p { display: none; }
  .card-badge { position: absolute; top: 2.7rem; left: var(--spacing-3); z-index: 1; }
  .result-card:not(.has-media) .card-badge { top: var(--spacing-2); left: 3rem; }
  .card-facts { display: flex; flex-wrap: wrap; gap: var(--spacing-2); }
  @container result-card (min-width: 400px) {
    .card-copy, .result-card:not(.has-media) .card-copy, .text-first .card-copy { inset: 0; justify-content: center; padding: 3.5rem var(--spacing-6) var(--spacing-6); }
    .result-card:not(.has-media) .card-copy, .text-first .card-copy { justify-content: flex-start; }
    .has-media .card-copy { right: 46%; }
    .card-media, .text-first .card-media { display: block; inset: 0 0 0 54%; }
    .contain-media.has-media:not(.text-first) { display: block; }
    .contain-media.has-media:not(.text-first) .card-media { position: absolute; inset: 0 0 0 54%; }
    .contain-media.has-media:not(.text-first) .card-copy { position: absolute; inset: 0 46% 0 0; }
    .card-media::after { inset: 0; background: linear-gradient(90deg, var(--color-grey-0), transparent 35%); }
    .has-media:not(.text-first) p { display: -webkit-box; -webkit-line-clamp: 4; }
    h3 { font-size: var(--font-size-h3); -webkit-line-clamp: 3; }
    .card-badge { top: var(--spacing-3); left: 3rem; }
  }
</style>
