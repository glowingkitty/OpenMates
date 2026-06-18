<!--
  frontend/packages/ui/src/components/embeds/diagrams/MermaidDiagramEmbedPreview.svelte

  Diagrams/Mermaid preview card. Mermaid source is rendered client-side with
  strict security settings, sanitized, and clipped at a readable scale instead
  of shrinking large diagrams into an unreadable thumbnail.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import {
    getPreviewTransform,
    normalizeMermaidContent,
    sanitizeMermaidSvg,
    type MermaidDiagramContent
  } from './mermaidDiagramContent';

  interface Props {
    id: string;
    title?: string;
    diagram_kind?: string;
    diagramKind?: string;
    diagram_code?: string;
    diagramCode?: string;
    status?: 'processing' | 'finished' | 'error' | 'cancelled';
    line_count?: number;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    title,
    diagram_kind,
    diagramKind,
    diagram_code,
    diagramCode,
    status: statusProp = 'processing',
    line_count,
    isMobile = false,
    onFullscreen
  }: Props = $props();

  let updatedContent = $state<Record<string, unknown> | null>(null);
  let renderedSvg = $state('');
  let renderError = $state<string | null>(null);
  let renderRequest = 0;

  let rawContent = $derived(updatedContent ?? {
    title,
    diagram_kind: diagram_kind ?? diagramKind,
    diagram_code: diagram_code ?? diagramCode,
    line_count,
    status: statusProp
  });
  let content = $derived<MermaidDiagramContent>(normalizeMermaidContent(rawContent));
  let skillName = $derived(content.title || 'Mermaid Diagram');
  let status = $derived(content.status);
  let sourcePreview = $derived(content.diagramCode.split('\n').slice(0, 5).join('\n'));
  let transform = $derived(getPreviewTransform(900, 600, isMobile ? 140 : 280, isMobile ? 180 : 135));

  $effect(() => {
    renderDiagram(content.diagramCode);
  });

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> }) {
    updatedContent = data.decodedContent;
  }

  async function renderDiagram(diagramCode: string) {
    const source = diagramCode.trim();
    if (!source || content.status !== 'finished') return;
    const request = ++renderRequest;
    try {
      const mermaid = await import('mermaid');
      mermaid.default.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        theme: document.documentElement.dataset.theme === 'dark' ? 'dark' : 'default'
      });
      const result = await mermaid.default.render(`mermaid-preview-${id}-${request}`, source);
      if (request !== renderRequest) return;
      renderedSvg = sanitizeMermaidSvg(result.svg);
      renderError = null;
    } catch (error) {
      if (request !== renderRequest) return;
      renderedSvg = '';
      renderError = error instanceof Error ? error.message : 'Mermaid render failed';
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="diagrams"
  skillId="mermaid"
  skillIconName="diagram"
  {status}
  {skillName}
  {isMobile}
  {onFullscreen}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileLayout })}
    <div class="mermaid-preview" class:mobile={isMobileLayout} data-testid="mermaid-diagram-preview">
      {#if status === 'processing'}
        <div class="diagram-placeholder" aria-label="Preparing Mermaid diagram">
          <div></div><div></div><div></div>
        </div>
      {:else if renderedSvg}
        <div
          class="diagram-crop"
          data-testid="mermaid-rendered-preview"
          style={`--diagram-scale: ${transform.scale}; --diagram-x: ${transform.offsetX}px; --diagram-y: ${transform.offsetY}px;`}
          aria-label={`${content.title} Mermaid diagram preview`}
        >
          <!-- eslint-disable-next-line svelte/no-at-html-tags -->
          <div class="diagram-svg">{@html renderedSvg}</div>
        </div>
      {:else}
        <div class="source-fallback" data-testid="mermaid-source-fallback">
          <strong>{content.diagramKind}</strong>
          <pre>{sourcePreview || renderError || 'No Mermaid source available.'}</pre>
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .mermaid-preview {
    width: 100%;
    height: 100%;
    min-height: 126px;
    overflow: hidden;
  }

  .diagram-crop {
    width: 100%;
    height: 100%;
    overflow: hidden;
    border-radius: var(--radius-3);
    background: var(--color-grey-5);
  }

  .diagram-svg {
    width: max-content;
    min-width: 100%;
    transform: translate(var(--diagram-x), var(--diagram-y)) scale(var(--diagram-scale));
    transform-origin: top left;
  }

  .diagram-svg :global(svg) {
    display: block;
    max-width: none;
    min-width: 420px;
  }

  .source-fallback {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
    height: 100%;
    padding: var(--spacing-3);
    border-radius: var(--radius-3);
    background: var(--color-grey-15);
    color: var(--color-font-primary);
    overflow: hidden;
  }

  .source-fallback strong {
    font-size: var(--font-size-small);
  }

  .source-fallback pre {
    margin: 0;
    font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
    font-size: var(--font-size-xs);
    line-height: 1.35;
    white-space: pre-wrap;
  }

  .diagram-placeholder {
    display: grid;
    place-items: center;
    grid-template-columns: repeat(3, 1fr);
    gap: var(--spacing-3);
    height: 100%;
    padding: var(--spacing-5);
    border-radius: var(--radius-3);
    background: var(--color-grey-15);
  }

  .diagram-placeholder div {
    width: 100%;
    height: 2px;
    background: var(--color-grey-40);
    box-shadow: 0 28px 0 var(--color-grey-30), 0 -28px 0 var(--color-grey-30);
  }
</style>
