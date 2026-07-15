<!--
  frontend/packages/ui/src/components/embeds/models3d/Model3DResultEmbedPreview.svelte

  Preview-only child card for a 3D model catalog result. The CTA links to the
  provider source page; no model file is downloaded or rendered in V1.
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { proxyImage, MAX_WIDTH_PREVIEW_THUMBNAIL } from '../../../utils/imageProxy';

  interface Props {
    id: string;
    title?: string;
    provider?: string;
    creatorName?: string;
    sourcePageUrl?: string;
    previewImageUrl?: string;
    thumbnailUrl?: string;
    license?: string;
    filesCount?: number | null;
    isFree?: boolean | null;
    status?: 'processing' | 'finished' | 'error';
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    title = '',
    provider = '',
    creatorName = '',
    sourcePageUrl = '',
    previewImageUrl = '',
    thumbnailUrl = '',
    license = '',
    filesCount = null,
    isFree = null,
    status = 'finished',
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  let imageLoaded = $state(false);
  let imageFailed = $state(false);
  let displayImage = $derived(proxyImage(previewImageUrl || thumbnailUrl, MAX_WIDTH_PREVIEW_THUMBNAIL));
  let cardTitle = $derived(title || $text('embeds.models3d.search.result_title'));
  let ctaLabel = $derived(provider ? $text('embeds.models3d.search.open_on_provider', { values: { provider } }) : $text('embeds.models3d.search.open_result'));

  function handleStop() {
    // Result cards are not cancellable.
  }

  function stopLinkClick(event: MouseEvent) {
    event.stopPropagation();
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="models3d"
  skillId="model_result"
  skillIconName="3dmodels"
  {status}
  skillName={provider || $text('apps.models3d')}
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  showStatus={false}
  showSkillIcon={false}
>
  {#snippet details()}
    <article class="model-card" data-testid="models3d-result-card">
      <div class="image-shell">
        {#if displayImage && !imageFailed}
          <img
            src={displayImage}
            alt={cardTitle}
            class:visible={imageLoaded}
            loading="lazy"
            onload={() => imageLoaded = true}
            onerror={() => imageFailed = true}
          />
        {:else}
          <span class="clickable-icon icon_3dmodels placeholder-icon"></span>
        {/if}
      </div>
      <div class="card-body">
        <h3>{cardTitle}</h3>
        <div class="meta-line">
          {#if creatorName}<span>{creatorName}</span>{/if}
          {#if provider}<span>{provider}</span>{/if}
        </div>
        <div class="pills">
          {#if isFree === true}<span>{$text('embeds.models3d.search.free')}</span>{/if}
          {#if filesCount != null}<span>{$text('embeds.models3d.search.files_count', { values: { count: filesCount } })}</span>{/if}
          {#if license}<span>{license}</span>{/if}
        </div>
        {#if sourcePageUrl}
          <a
            class="provider-cta"
            data-testid="models3d-open-provider-cta"
            href={sourcePageUrl}
            target="_blank"
            rel="noopener noreferrer"
            onclick={stopLinkClick}
          >
            {ctaLabel}
          </a>
        {/if}
      </div>
    </article>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .model-card {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-6);
    width: 100%;
    height: 100%;
    padding: var(--spacing-6);
  }

  .image-shell {
    display: grid;
    place-items: center;
    aspect-ratio: 4 / 3;
    width: 100%;
    overflow: hidden;
    border-radius: 18px;
    background: var(--color-grey-10);
  }

  img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    opacity: 0;
    transition: opacity var(--duration-normal) var(--easing-default);
  }

  img.visible { opacity: 1; }

  .placeholder-icon {
    width: 32px;
    height: 32px;
    background: var(--color-grey-40) !important;
  }

  .card-body {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-3);
    min-width: 0;
  }

  h3 {
    margin: 0;
    color: var(--color-font-primary);
    font-size: var(--font-size-sm);
    font-weight: 650;
    line-height: 1.25;
  }

  .meta-line,
  .pills {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
  }

  .pills span {
    padding: 2px 7px;
    border-radius: var(--radius-full);
    background: var(--color-grey-10);
  }

  .provider-cta {
    align-self: flex-start;
    margin-top: var(--spacing-3);
    padding: 7px 11px;
    border-radius: var(--radius-8);
    background: var(--color-button-primary);
    color: var(--color-font-button);
    font-size: var(--font-size-xs);
    font-weight: 650;
    text-decoration: none;
  }
</style>
