<script lang="ts">
  import { onMount } from 'svelte';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { buildDiagramFrame, normalizeDiagramHtmlContent } from './diagramHtmlContent';
  import { diagramMeasureScript, nextDiagramPresentationHeight, readDiagramMeasurement } from './diagramHtmlMeasure';
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
  let measureFrame = $state<HTMLIFrameElement | null>(null);
  let measureToken = $state(crypto.randomUUID());
  let measuredHeight = $state<number | null>(null);
  let measureSteps = $state(0);
  let layoutReady = $state(false);
  let measureError = $state(false);
  let size = $state({ width: 280, height: 135 });
  const raw = $derived(updatedContent ?? { title, diagram_kind, html_source, render_width, render_height, schema_version, version_number, status: statusProp });
  const content = $derived(normalizeDiagramHtmlContent(raw));
  const rendered = $derived.by(() => {
    try { return { ...buildDiagramFrame(content.htmlSource), error: '' }; }
    catch (error) { return { srcdoc: '', backgroundColor: '', error: error instanceof Error ? error.message : 'Unable to render diagram' }; }
  });
  const measured = $derived.by(() => {
    try { return buildDiagramFrame(content.htmlSource, diagramMeasureScript(measureToken)); }
    catch { return null; }
  });
  const presentationHeight = $derived(Math.max(content.renderHeight, measuredHeight ?? 0));
  const scale = $derived(Math.min(size.width / content.renderWidth, size.height / presentationHeight));
  const left = $derived((size.width - content.renderWidth * scale) / 2);
  const top = $derived((size.height - presentationHeight * scale) / 2);

  $effect(() => {
    void content.htmlSource;
    void content.renderWidth;
    void content.renderHeight;
    measureToken = crypto.randomUUID();
    measuredHeight = null;
    measureSteps = 0;
    layoutReady = false;
    measureError = false;
  });

  $effect(() => {
    const currentToken = measureToken;
    if (content.status !== 'finished' || rendered.error) return;
    const timeout = setTimeout(() => {
      if (measureToken === currentToken && !layoutReady) measureError = true;
    }, 10_000);
    return () => clearTimeout(timeout);
  });

  onMount(() => {
    const observer = new ResizeObserver(() => {
      if (viewport) size = { width: viewport.clientWidth, height: viewport.clientHeight };
    });
    if (viewport) observer.observe(viewport);
    window.addEventListener('message', onMeasureMessage);
    return () => {
      observer.disconnect();
      window.removeEventListener('message', onMeasureMessage);
    };
  });
  function onMeasureMessage(event: MessageEvent) {
    if (event.source !== measureFrame?.contentWindow || event.origin !== 'null') return;
    const height = readDiagramMeasurement(event.data, measureToken, content.renderWidth, presentationHeight);
    if (height === null) return;
    const next = nextDiagramPresentationHeight(content.renderHeight, presentationHeight, height, measureSteps);
    if (next.error) { measureError = true; return; }
    if (next.height > presentationHeight) { measuredHeight = next.height; measureSteps += 1; return; }
    layoutReady = next.ready;
  }
  function onUpdate(data: { status: string; decodedContent: Record<string, unknown> }) { updatedContent = data.decodedContent; }
</script>

<UnifiedEmbedPreview {id} appId="diagrams" skillId="html" skillIconName="diagram" appIconName="diagram" showSkillIcon={false} status={content.status}
  skillName={content.title} {isMobile} {onFullscreen} hasFullWidthImage={true} onEmbedDataUpdated={onUpdate}>
  {#snippet details()}
    <div bind:this={viewport} class="diagram-preview" data-testid="diagram-html-preview" data-layout-ready={layoutReady} style:background-color={rendered.backgroundColor || undefined}>
      {#if content.status === 'processing'}
        <div class="placeholder" data-testid="diagram-html-loading">{$text('diagrams.loading')}</div>
      {:else if rendered.error}
        <div class="error" data-testid="diagram-html-error">{rendered.error}</div>
      {:else if measureError}
        <div class="error" data-testid="diagram-html-error">{$text('diagrams.invalid_source')}</div>
      {:else}
        {#if measured}
          <div class="measure-shell" aria-hidden="true">
            <iframe bind:this={measureFrame} class="measure-frame" data-testid="diagram-html-measure-frame" tabindex="-1" title="Diagram layout measurement"
              sandbox="allow-scripts" srcdoc={measured.srcdoc} width={content.renderWidth} height={presentationHeight}></iframe>
          </div>
        {/if}
        <div class="artboard" style:width={`${content.renderWidth}px`} style:height={`${presentationHeight}px`}
          style:transform={`translate(${left}px, ${top}px) scale(${scale})`}>
          <iframe data-testid="diagram-html-frame" title={`${content.title} diagram preview`} srcdoc={rendered.srcdoc}
            sandbox="" width={content.renderWidth} height={presentationHeight} tabindex="-1"></iframe>
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .diagram-preview { position: relative; width: 100%; height: 100%; min-height: 126px; overflow: hidden; border-radius: var(--radius-3); background: var(--color-grey-10); }
  .artboard { position: absolute; top: 0; left: 0; transform-origin: top left; overflow: hidden; pointer-events: none; }
  iframe { display: block; border: 0; background: transparent; pointer-events: none; }
  .measure-shell { position: absolute; top: 0; left: 0; width: 0; height: 0; overflow: hidden; opacity: 0; pointer-events: none; }
  .placeholder, .error { display: grid; place-items: center; height: 100%; padding: var(--spacing-3); color: var(--color-font-primary); text-align: center; font-size: var(--font-size-small); }
  .error { color: var(--color-error); }
</style>
