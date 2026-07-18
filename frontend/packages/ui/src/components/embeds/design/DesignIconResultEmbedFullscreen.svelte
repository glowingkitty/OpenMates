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
  import { copyToClipboard } from '../../../utils/clipboardUtils';
  import { notificationStore } from '../../../stores/notificationStore';

  const ICONIFY_ICON_PAGE_PREFIX = 'https://icon-sets.iconify.design';
  const ICONIFY_PREFIX_PATTERN = /^[a-z0-9][a-z0-9-]{0,63}$/;
  const ICONIFY_NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,127}$/;

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

  function asNumber(value: unknown): number | undefined {
    return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : undefined;
  }

  function iconifyPageUrl(prefix: string, name: string): string {
    if (!ICONIFY_PREFIX_PATTERN.test(prefix) || !ICONIFY_NAME_PATTERN.test(name)) return '';
    return `${ICONIFY_ICON_PAGE_PREFIX}/${prefix}/${name}/`;
  }

  function applyIconColor(svg: string, color: string): string {
    const withCurrentColor = svg.replace(/\bcurrentColor\b/g, color);
    return withCurrentColor.replace(/<svg\b([^>]*)>/i, (match, attrs: string) => {
      if (/\scolor\s*=/.test(attrs)) {
        return match.replace(/\scolor\s*=\s*(['"])[^'"]*\1/i, ` color="${color}"`);
      }
      return `<svg${attrs} color="${color}">`;
    });
  }

  function filenameFor(extension: 'svg' | 'png'): string {
    const base = (asString(content.icon_id) || title || 'icon')
      .toLowerCase()
      .replace(/[^a-z0-9._-]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'icon';
    return `${base}.${extension}`;
  }

  async function fetchPreparedSvg(): Promise<string> {
    if (preparedSvg) return preparedSvg;
    if (!iconSrc) throw new Error('Icon SVG path is unavailable');
    const response = await fetch(iconSrc, { credentials: 'include' });
    if (!response.ok) {
      throw new Error(`Icon SVG request failed with status ${response.status}`);
    }
    const svg = await response.text();
    return canRecolor ? applyIconColor(svg, color) : svg;
  }

  async function handleCopySvg(): Promise<void> {
    try {
      const svg = await fetchPreparedSvg();
      const result = await copyToClipboard(svg);
      if (!result.success) throw new Error(result.error || 'Copy failed');
      notificationStore.success('SVG copied to clipboard');
    } catch (error) {
      console.error('[DesignIconResultEmbedFullscreen] Failed to copy SVG:', error);
      notificationStore.error('Failed to copy SVG');
    }
  }

  function renderPngDataUrl(svg: string, size: number): Promise<string> {
    return new Promise((resolve, reject) => {
      const svgUrl = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }));
      const image = new Image();
      image.onload = () => {
        try {
          const canvas = document.createElement('canvas');
          canvas.width = size;
          canvas.height = size;
          const context = canvas.getContext('2d');
          if (!context) throw new Error('Canvas rendering is unavailable');
          context.drawImage(image, 0, 0, size, size);
          const pngDataUrl = canvas.toDataURL('image/png');
          URL.revokeObjectURL(svgUrl);
          resolve(pngDataUrl);
        } catch (error) {
          URL.revokeObjectURL(svgUrl);
          reject(error);
        }
      };
      image.onerror = () => {
        URL.revokeObjectURL(svgUrl);
        reject(new Error('SVG image failed to load for PNG export'));
      };
      image.src = svgUrl;
    });
  }

  function handleDownloadLinkClick(event: MouseEvent): void {
    if (!(event.currentTarget instanceof HTMLAnchorElement) || !event.currentTarget.getAttribute('href')) {
      event.preventDefault();
      notificationStore.error('Icon export is still loading');
    }
  }

  function noopDownload(): void {
    // UnifiedEmbedFullscreen requires an onDownload prop to show the native anchor.
  }

  let content = $derived({
    ...(data?.embedData ?? {}),
    ...(data?.attrs ?? {}),
    ...(data?.decodedContent ?? {}),
  });
  let title = $derived(asString(content.display_name) || asString(content.name) || asString(content.icon_id) || 'Icon');
  let collection = $derived(asString(content.collection_name) || asString(content.prefix));
  let license = $derived(asString(content.license_title) || asString(content.license_spdx));
  let author = $derived(asString(content.author_name));
  let provider = $derived(asString(content.provider) || 'Iconify');
  let providerUrl = $derived(iconifyPageUrl(asString(content.prefix), asString(content.name)));
  let width = $derived(asNumber(content.width));
  let height = $derived(asNumber(content.height));
  let isPalette = $derived(content.palette === true);
  let svgPath = $derived(asString(content.svg_path));
  let iconSrc = $derived(svgPath ? getApiEndpoint(svgPath) : '');
  let color = $state('#111827');
  let pngSize = $state(256);
  let canRecolor = $derived(!isPalette);
  let rawSvg = $state('');
  let rawSvgIconSrc = $state('');
  let preparedSvg = $derived(rawSvg && rawSvgIconSrc === iconSrc ? (canRecolor ? applyIconColor(rawSvg, color) : rawSvg) : '');
  let svgDownloadHref = $derived(preparedSvg ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(preparedSvg)}` : '');
  let pngDownloadHref = $state('');
  let pngDownloadFilename = $derived(filenameFor('png'));

  $effect(() => {
    const currentIconSrc = iconSrc;
    rawSvg = '';
    rawSvgIconSrc = '';
    pngDownloadHref = '';
    if (!currentIconSrc) return;

    let isCancelled = false;
    fetch(currentIconSrc, { credentials: 'include' })
      .then((response) => {
        if (!response.ok) throw new Error(`Icon SVG request failed with status ${response.status}`);
        return response.text();
      })
      .then((svg) => {
        if (isCancelled) return;
        rawSvg = svg;
        rawSvgIconSrc = currentIconSrc;
      })
      .catch((error) => {
        if (isCancelled) return;
        console.error('[DesignIconResultEmbedFullscreen] Failed to prepare SVG export:', error);
      });

    return () => {
      isCancelled = true;
    };
  });

  $effect(() => {
    const currentSvg = preparedSvg;
    const currentPngSize = pngSize;
    pngDownloadHref = '';
    if (!currentSvg) return;

    let isCancelled = false;
    renderPngDataUrl(currentSvg, currentPngSize)
      .then((dataUrl) => {
        if (!isCancelled) pngDownloadHref = dataUrl;
      })
      .catch((error) => {
        if (isCancelled) return;
        console.error('[DesignIconResultEmbedFullscreen] Failed to prepare PNG export:', error);
      });

    return () => {
      isCancelled = true;
    };
  });
</script>

<UnifiedEmbedFullscreen
  appId="design"
  skillId="search_icons"
  skillIconName="design"
  embedHeaderTitle={title}
  embedHeaderSubtitle={collection}
  showSkillIcon={true}
  {onClose}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  onCopy={iconSrc ? handleCopySvg : undefined}
  onDownload={pngDownloadHref ? noopDownload : undefined}
  downloadHref={pngDownloadHref || null}
  downloadFilename={pngDownloadFilename}
>
  {#snippet embedHeaderCta()}
    {#if providerUrl}
      <EmbedHeaderCtaButton label={`Open on ${provider}`} href={providerUrl} testId="design-icon-provider-cta" />
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
        {#if width && height}<p>{width} x {height}</p>{/if}
        {#if isPalette}<p>Palette icon. Recoloring is disabled to preserve the original colors.</p>{/if}
        {#if svgPath}<code>{svgPath}</code>{/if}

        <div class="export-controls" aria-label="Icon export controls">
          <label>
            <span>Color</span>
            <input type="color" bind:value={color} disabled={!canRecolor} data-testid="design-icon-color-input" />
          </label>
          <label>
            <span>PNG size</span>
            <input type="number" min="16" max="4096" step="16" bind:value={pngSize} data-testid="design-icon-png-size-input" />
          </label>
        </div>

        <div class="export-actions">
          <button type="button" onclick={handleCopySvg} disabled={!iconSrc}>Copy SVG</button>
          <a
            role="button"
            href={svgDownloadHref || undefined}
            download={filenameFor('svg')}
            aria-disabled={!svgDownloadHref}
            class:disabled={!svgDownloadHref}
            onclick={handleDownloadLinkClick}
          >Download SVG</a>
          <a
            role="button"
            href={pngDownloadHref || undefined}
            download={filenameFor('png')}
            aria-disabled={!pngDownloadHref}
            class:disabled={!pngDownloadHref}
            onclick={handleDownloadLinkClick}
          >Download PNG</a>
        </div>
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

  .export-controls,
  .export-actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-4);
    margin-top: var(--spacing-4);
  }

  label {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
  }

  input[type='number'] {
    width: 110px;
    padding: var(--spacing-3);
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-4);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
  }

  input[type='color'] {
    width: 56px;
    height: 40px;
    padding: 0;
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-4);
    background: transparent;
  }

  button,
  .export-actions a {
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-4);
    padding: var(--spacing-3) var(--spacing-5);
    background: var(--color-grey-8);
    color: var(--color-font-primary);
    cursor: pointer;
    font: inherit;
    text-decoration: none;
  }

  button:hover:not(:disabled),
  .export-actions a:hover:not(.disabled) {
    background: var(--color-grey-15);
  }

  button:disabled,
  .export-actions a.disabled,
  input:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }

  @media (max-width: 760px) {
    .icon-result-fullscreen {
      grid-template-columns: 1fr;
      padding: var(--spacing-6);
    }
  }
</style>
