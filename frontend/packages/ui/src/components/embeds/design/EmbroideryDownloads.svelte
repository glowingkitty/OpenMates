<!--
  frontend/packages/ui/src/components/embeds/design/EmbroideryDownloads.svelte

  One download per machine format. Each file is fetched encrypted from storage
  and decrypted in the browser with the embed's own key material (like the
  stitch preview), then saved from a same-origin object URL so the browser
  honours the suggested "<name>.<format>". The first button saves all formats in
  one ZIP; the opened view's top-bar download button triggers the same action.
  Component previews carry inline text (`previewDownloadText`) and need no
  network. Each button keeps its own loading and error state.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import { EMBROIDERY_FORMATS, type EmbroideryFormat } from './embroideryDesign';
  import {
    downloadAllEmbroideryFiles, downloadEmbroideryFile, type EmbroideryDownloadSource,
  } from './embroideryDownload';

  interface Props {
    /** Per-format file descriptors and key material of the result. */
    design: EmbroideryDownloadSource;
    /** File name without extension, used as the browser's suggested name. */
    baseName: string;
  }
  let { design, baseName }: Props = $props();

  type Target = EmbroideryFormat | 'all';
  let loading = $state<Partial<Record<Target, boolean>>>({});
  let failed = $state<Partial<Record<Target, boolean>>>({});

  /** Also called by the opened view's top-bar download button. */
  export async function download(target: Target) {
    if (loading[target]) return;
    loading = { ...loading, [target]: true };
    failed = { ...failed, [target]: false };
    try {
      if (target === 'all') await downloadAllEmbroideryFiles(design, baseName);
      else await downloadEmbroideryFile(design, target, baseName);
    } catch (caught) {
      console.warn('[EmbroideryDownloads] download failed:', target, caught);
      failed = { ...failed, [target]: true };
    } finally {
      loading = { ...loading, [target]: false };
    }
  }
</script>

<section class="downloads" data-testid="design-embroidery-downloads">
  <h4>{$text('embeds.design.embroidery.download')}</h4>
  <div class="item all">
    <button
      type="button"
      class="download primary"
      class:failed={failed.all}
      data-testid="design-embroidery-download-all"
      data-state={loading.all ? 'loading' : failed.all ? 'error' : 'idle'}
      disabled={loading.all}
      aria-busy={loading.all ? 'true' : undefined}
      onclick={() => download('all')}
    >
      <span class="clickable-icon icon_download" aria-hidden="true"></span>
      {$text('embeds.design.embroidery.download_all')}
    </button>
    {#if failed.all}
      <span class="error" role="alert" data-testid="design-embroidery-download-all-error">
        {$text('embeds.action_failed')}
      </span>
    {/if}
  </div>
  <p class="or">{$text('embeds.design.embroidery.download_single')}</p>
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
  .item.all { margin-bottom: var(--spacing-6); }
  .download.primary { display: inline-flex; align-items: center; justify-content: center; gap: var(--spacing-4); min-height: 52px; width: 100%; font-size: var(--font-size-p); }
  .download.primary .clickable-icon { width: 20px; height: 20px; background: var(--color-font-button); }
  .or { margin: 0 0 var(--spacing-4); font-size: var(--font-size-small); color: var(--color-font-secondary); }
  .buttons .download { background: var(--color-grey-20); color: var(--color-font-primary); }
  .buttons .download.failed { background: var(--color-error); color: var(--color-font-button); }
  .download:hover:not(:disabled) { opacity: 0.9; }
  .download:disabled { opacity: 0.6; cursor: progress; }
  .download:focus-visible { outline: 2px solid var(--color-button-primary); outline-offset: 3px; }
  .download.failed { background: var(--color-error); }
  .error { font-size: var(--font-size-xxs); color: var(--color-error); text-align: center; }
</style>
