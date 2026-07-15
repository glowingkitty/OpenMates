<!--
  frontend/packages/ui/src/components/embeds/models3d/Model3DResultEmbedPreview.svelte

  Preview-only child card for a 3D model catalog result. Source-provider CTAs
  are intentionally reserved for fullscreen so preview cards stay navigational.
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
  function handleStop() {
    // Result cards are not cancellable.
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
      <div class="card-body" data-testid="models3d-result-card-body">
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
      </div>
      <div class="image-shell" data-testid="models3d-result-card-image">
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
    </article>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .model-card {
    display: flex;
    align-items: stretch;
    gap: var(--spacing-4);
    width: 100%;
    height: 100%;
    padding: var(--spacing-6);
  }

  .image-shell {
    flex: 0 0 40%;
    display: grid;
    place-items: center;
    aspect-ratio: 4 / 3;
    width: 40%;
    min-width: 96px;
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
    justify-content: center;
    flex: 1 1 0;
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

  :global(.unified-embed-preview.mobile) .model-card {
    flex-direction: column-reverse;
  }

  :global(.unified-embed-preview.mobile) .image-shell {
    flex: 0 0 auto;
    width: 100%;
    min-width: 0;
  }
</style>
