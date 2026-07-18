<!--
  frontend/packages/ui/src/components/embeds/design/DesignIconResultEmbedFullscreen.svelte

  Fullscreen detail view for one SVG icon result from the Design app.
  Shows the icon, collection, license, and stable metadata from the saved embed.

  Architecture: docs/architecture/embeds.md
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import { getApiEndpoint } from '../../../config/api';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';

  interface Props {
    data?: EmbedFullscreenRawData;
    embedId?: string;
    onClose: () => void;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
  }

  let {
    data,
    embedId,
    onClose,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
  }: Props = $props();

  function asString(value: unknown): string {
    return typeof value === 'string' ? value : '';
  }

  let content = $derived({
    ...(data?.embedData ?? {}),
    ...(data?.attrs ?? {}),
    ...(data?.decodedContent ?? {}),
  });
  let title = $derived(asString(content.display_name) || asString(content.name) || asString(content.icon_id) || 'Icon');
  let collection = $derived(asString(content.collection_name) || asString(content.prefix));
  let license = $derived(asString(content.license_title) || asString(content.license_spdx));
  let licenseUrl = $derived(asString(content.license_url));
  let author = $derived(asString(content.author_name));
  let svgPath = $derived(asString(content.svg_path));
  let iconSrc = $derived(svgPath ? getApiEndpoint(svgPath) : '');
</script>

<UnifiedEmbedFullscreen
  appId="design"
  skillId="search_icons"
  skillIconName="search"
  embedHeaderTitle={title}
  embedHeaderSubtitle={collection}
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
>
  {#snippet embedHeaderCta()}
    {#if licenseUrl}
      <EmbedHeaderCtaButton label={license || 'View license'} href={licenseUrl} testId="design-icon-license-cta" />
    {/if}
  {/snippet}

  {#snippet content()}
    <div class="icon-result-fullscreen" data-testid="design-icon-result-fullscreen">
      <div class="icon-stage">
        {#if iconSrc}
          <img src={iconSrc} alt={title} />
        {:else}
          <span class="clickable-icon icon_design placeholder-icon"></span>
        {/if}
      </div>

      <section class="metadata">
        <h2>{title}</h2>
        {#if collection}<p>{collection}</p>{/if}
        {#if license}<p>{license}</p>{/if}
        {#if author}<p>{author}</p>{/if}
        {#if svgPath}<code>{svgPath}</code>{/if}
      </section>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .icon-result-fullscreen {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(260px, 360px);
    gap: var(--spacing-12);
    width: 100%;
    padding: var(--spacing-12);
  }

  .icon-stage {
    display: grid;
    place-items: center;
    min-height: 360px;
    border-radius: 24px;
    background: var(--color-grey-8);
    border: 1px solid var(--color-grey-20);
  }

  .icon-stage img {
    width: min(220px, 45vw);
    height: min(220px, 45vw);
    object-fit: contain;
  }

  .placeholder-icon {
    width: 56px;
    height: 56px;
    background: var(--color-grey-50) !important;
  }

  .metadata {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-4);
    color: var(--color-font-primary);
  }

  h2 {
    margin: 0;
    font-size: var(--font-size-lg);
  }

  p {
    margin: 0;
    color: var(--color-font-secondary);
  }

  code {
    padding: var(--spacing-3);
    border-radius: var(--radius-4);
    background: var(--color-grey-8);
    color: var(--color-font-secondary);
    word-break: break-all;
  }

  @media (max-width: 760px) {
    .icon-result-fullscreen {
      grid-template-columns: 1fr;
      padding: var(--spacing-6);
    }
  }
</style>
