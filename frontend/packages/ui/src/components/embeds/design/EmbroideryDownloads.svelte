<!--
  frontend/packages/ui/src/components/embeds/design/EmbroideryDownloads.svelte

  One download per machine format. Each button asks the generated-assets route
  for an owner-scoped download URL (the server names the file with the matching
  extension), keeping its own loading and error state.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import { getApiEndpoint } from '../../../config/api';
  import { EMBROIDERY_FORMATS, type EmbroideryFormat } from './embroideryDesign';

  interface Props {
    embedId: string;
    /** File name without extension, used as the browser's suggested name. */
    baseName: string;
  }
  let { embedId, baseName }: Props = $props();

  let loading = $state<Partial<Record<EmbroideryFormat, boolean>>>({});
  let failed = $state<Partial<Record<EmbroideryFormat, boolean>>>({});

  async function download(format: EmbroideryFormat) {
    if (!embedId || loading[format]) return;
    loading = { ...loading, [format]: true };
    failed = { ...failed, [format]: false };
    try {
      const response = await fetch(
        getApiEndpoint(`/v1/generated-assets/${encodeURIComponent(embedId)}/files/${format}/download-url`),
        { credentials: 'include' },
      );
      if (!response.ok) throw new Error(`Embroidery download unavailable (${response.status})`);
      const result = await response.json() as { download_url?: string };
      if (!result.download_url) throw new Error('Embroidery download URL missing');
      const link = document.createElement('a');
      link.href = result.download_url;
      link.rel = 'noopener noreferrer';
      link.download = `${baseName || 'embroidery'}.${format}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (caught) {
      console.warn('[EmbroideryDownloads] download failed:', format, caught);
      failed = { ...failed, [format]: true };
    } finally {
      loading = { ...loading, [format]: false };
    }
  }
</script>

<section class="downloads" data-testid="design-embroidery-downloads">
  <h4>{$text('embeds.design.embroidery.download')}</h4>
  <div class="buttons">
    {#each EMBROIDERY_FORMATS as format (format)}
      <div class="item">
        <button
          type="button"
          class="download"
          class:failed={failed[format]}
          data-testid={`design-embroidery-download-${format}`}
          data-state={loading[format] ? 'loading' : failed[format] ? 'error' : 'idle'}
          disabled={loading[format]}
          aria-busy={loading[format] ? 'true' : undefined}
          onclick={() => download(format)}
        >
          {format.toUpperCase()}
        </button>
        {#if failed[format]}
          <span class="error" role="alert" data-testid={`design-embroidery-download-${format}-error`}>
            {$text('embeds.action_failed')}
          </span>
        {/if}
      </div>
    {/each}
  </div>
</section>

<style>
  .downloads { width: 100%; }
  h4 { margin: 0 0 var(--spacing-4); font-size: var(--font-size-small); color: var(--color-font-secondary); }
  .buttons { display: grid; grid-template-columns: repeat(auto-fit, minmax(5rem, 1fr)); gap: var(--spacing-4); }
  .item { display: flex; flex-direction: column; gap: var(--spacing-2); min-width: 0; }
  .download {
    min-height: 44px;
    border: 0;
    border-radius: var(--radius-4);
    background: var(--color-button-primary);
    color: var(--color-font-button);
    font: inherit;
    font-weight: 650;
    cursor: pointer;
    transition: opacity var(--duration-fast) var(--easing-default);
  }
  .download:hover:not(:disabled) { opacity: 0.9; }
  .download:disabled { opacity: 0.6; cursor: progress; }
  .download:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 3px; }
  .download.failed { background: var(--color-error); }
  .error { font-size: var(--font-size-xxs); color: var(--color-error); text-align: center; }
</style>
