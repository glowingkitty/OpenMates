<script lang="ts">
  import { onMount } from 'svelte';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { buildDiagramFrame, normalizeDiagramHtmlContent } from './diagramHtmlContent';
  import { text } from '../../../i18n/translations';

  interface Props {
    id: string;
    title?: string;
    diagram_kind?: string;
    html_source?: string;
    render_width?: number;
    render_height?: number;
    schema_version?: number;
    version_number?: number;
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    isMobile?: boolean;
    onFullscreen: () => void;
  }
  let { id, title, diagram_kind, html_source, render_width, render_height, schema_version, version_number,
    status: statusProp = 'processing', isMobile = false, onFullscreen }: Props = $props();
  let updatedContent = $state<Record<string, unknown> | null>(null);
  let viewport = $state<HTMLElement | null>(null);
  let size = $state({ width: 280, height: 135 });
  const raw = $derived(updatedContent ?? { title, diagram_kind, html_source, render_width, render_height, schema_version, version_number, status: statusProp });
  const content = $derived(normalizeDiagramHtmlContent(raw));
  const rendered = $derived.by(() => {
    try { return { ...buildDiagramFrame(content.htmlSource), error: '' }; }
    catch (error) { return { srcdoc: '', backgroundColor: '', error: error instanceof Error ? error.message : 'Unable to render diagram' }; }
  });
  const scale = $derived(Math.min(size.width / content.renderWidth, size.height / content.renderHeight));
  const left = $derived((size.width - content.renderWidth * scale) / 2);
  const top = $derived((size.height - content.renderHeight * scale) / 2);

  onMount(() => {
    const observer = new ResizeObserver(() => {
      if (viewport) size = { width: viewport.clientWidth, height: viewport.clientHeight };
    });
    if (viewport) observer.observe(viewport);
    return () => observer.disconnect();
  });
  function onUpdate(data: { status: string; decodedContent: Record<string, unknown> }) { updatedContent = data.decodedContent; }
</script>

<UnifiedEmbedPreview {id} appId="diagrams" skillId="html" skillIconName="diagram" appIconName="diagram" showSkillIcon={false} status={content.status}
  skillName={content.title} {isMobile} {onFullscreen} hasFullWidthImage={true} onEmbedDataUpdated={onUpdate}>
  {#snippet details()}
    <div bind:this={viewport} class="diagram-preview" data-testid="diagram-html-preview" style:background-color={rendered.backgroundColor || undefined}>
      {#if content.status === 'processing'}
        <div class="placeholder" data-testid="diagram-html-loading">{$text('diagrams.loading')}</div>
      {:else if rendered.error}
        <div class="error" data-testid="diagram-html-error">{rendered.error}</div>
      {:else}
        <div class="artboard" style:width={`${content.renderWidth}px`} style:height={`${content.renderHeight}px`}
          style:transform={`translate(${left}px, ${top}px) scale(${scale})`}>
          <iframe data-testid="diagram-html-frame" title={`${content.title} diagram preview`} srcdoc={rendered.srcdoc}
            sandbox="" width={content.renderWidth} height={content.renderHeight} tabindex="-1"></iframe>
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .diagram-preview { position: relative; width: 100%; height: 100%; min-height: 126px; overflow: hidden; border-radius: var(--radius-3); background: var(--color-grey-10); }
  .artboard { position: absolute; top: 0; left: 0; transform-origin: top left; overflow: hidden; pointer-events: none; }
  iframe { display: block; border: 0; background: transparent; pointer-events: none; }
  .placeholder, .error { display: grid; place-items: center; height: 100%; padding: var(--spacing-3); color: var(--color-font-primary); text-align: center; font-size: var(--font-size-small); }
  .error { color: var(--color-error); }
</style>
