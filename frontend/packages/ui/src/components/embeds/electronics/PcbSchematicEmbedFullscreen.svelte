<!--
  frontend/packages/ui/src/components/embeds/electronics/PcbSchematicEmbedFullscreen.svelte

  Fullscreen view for Electronics PCB schematic embeds. Source rendering uses
  the same code highlighting utilities and line DOM shape as code-code, while
  the side panel is PCB-specific: prepare files, artifacts, and hidden logs.
-->

<script lang="ts">
  import 'highlight.js/styles/github-dark.css';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import { text } from '@repo/ui';
  import { notificationStore } from '../../../stores/notificationStore';
  import { downloadCodeFile } from '../../../services/zipExportService';
  import { copyToClipboard } from '../../../utils/clipboardUtils';
  import { countCodeLines, formatLanguageName, parseCodeEmbedContent } from '../code/codeEmbedContent';
  import { highlightToLines } from '../code/codeHighlighting';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import {
    getPcbSchematicArtifactDownloadUrl,
    preparePcbSchematicFiles,
    type PcbSchematicArtifactManifest,
  } from '../../../services/pcbSchematicCompileService';

  interface Props {
    data: EmbedFullscreenRawData;
    onClose: () => void;
    embedId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
    onShowChat?: () => void;
  }

  let {
    data,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    navigateDirection,
    showChatButton = false,
    onShowChat,
  }: Props = $props();

  let dc = $derived(data.decodedContent);
  let attrs = $derived(data.attrs);
  let codeContent = $derived(typeof dc.code === 'string' ? dc.code : typeof attrs?.code === 'string' ? attrs.code as string : '');
  let language = $derived(typeof dc.language === 'string' ? dc.language : typeof attrs?.language === 'string' ? attrs.language as string : 'atopile');
  let filename = $derived(typeof dc.filename === 'string' ? dc.filename : typeof attrs?.filename === 'string' ? attrs.filename as string : 'board.ato');
  let lineCount = $derived(typeof dc.line_count === 'number' ? dc.line_count : typeof dc.lineCount === 'number' ? dc.lineCount : 0);
  let moduleName = $derived(typeof dc.module_name === 'string' ? dc.module_name : undefined);

  let parsedContent = $derived.by(() => parseCodeEmbedContent(codeContent, { language, filename }));
  let renderCodeContent = $derived(parsedContent.code);
  let renderLanguage = $derived(parsedContent.language || 'atopile');
  let renderFilename = $derived(parsedContent.filename || filename || 'board.ato');
  let displayLanguage = $derived.by(() => formatLanguageName(renderLanguage) || 'Atopile');
  let actualLineCount = $derived.by(() => lineCount || countCodeLines(renderCodeContent));
  let highlightedLines = $derived(highlightToLines(renderCodeContent, renderLanguage));

  let initializedDataKey = $state<string | undefined>();
  let activeCompileId = $state<string | null>(null);
  let compileStatus = $state<string>('idle');
  let compileError = $state<string | null>(null);
  let compileLogs = $state<string>('');
  let showLogs = $state(false);
  let artifactManifest = $state<PcbSchematicArtifactManifest | null>(null);

  let skillName = $derived(renderFilename || moduleName || $text('embeds.electronics.pcb_schematic.title'));
  let statusText = $derived.by(() => {
    const lineText = actualLineCount === 1 ? $text('embeds.code_line_singular') : $text('embeds.code_line_plural');
    return actualLineCount > 0 ? `${actualLineCount} ${lineText}, ${displayLanguage}` : displayLanguage;
  });
  let preparing = $derived(compileStatus === 'running');
  let files = $derived(artifactManifest?.files ?? []);

  $effect(() => {
    const dataKey = embedId ?? String(data.embedData?.id ?? data.attrs?.id ?? 'pcb-schematic');
    if (initializedDataKey === dataKey) return;

    initializedDataKey = dataKey;
    activeCompileId = typeof dc.compile_id === 'string' ? dc.compile_id : null;
    compileStatus = typeof dc.compile_status === 'string' ? dc.compile_status : 'idle';
    compileError = null;
    compileLogs = typeof dc.compile_logs === 'string' ? dc.compile_logs : '';
    artifactManifest = typeof dc.artifact_manifest === 'object' && dc.artifact_manifest !== null
      ? dc.artifact_manifest as PcbSchematicArtifactManifest
      : null;
    showLogs = false;
  });

  async function handleCopy() {
    const result = await copyToClipboard(renderCodeContent);
    if (result.success) notificationStore.success($text('embeds.electronics.pcb_schematic.copied'));
    else notificationStore.error($text('embeds.electronics.pcb_schematic.copy_failed'));
  }

  async function handleDownload() {
    try {
      await downloadCodeFile(renderCodeContent, renderLanguage, renderFilename || 'board.ato');
    } catch (error) {
      console.error('[PcbSchematicEmbedFullscreen] Failed to download source:', error);
      notificationStore.error($text('embeds.electronics.pcb_schematic.download_failed'));
    }
  }

  async function handlePrepareFiles() {
    if (!embedId || preparing) return;
    compileStatus = 'running';
    compileError = null;
    showLogs = false;
    try {
      const result = await preparePcbSchematicFiles(embedId);
      activeCompileId = result.compile_id;
      compileStatus = result.status;
      artifactManifest = result.artifact_manifest ?? null;
      compileError = result.error ?? null;
      if (result.logs) compileLogs = result.logs;
      if (result.status === 'succeeded') notificationStore.success($text('embeds.electronics.pcb_schematic.prepared'));
      if (result.status === 'failed') notificationStore.error(result.error ?? $text('embeds.electronics.pcb_schematic.prepare_failed'));
    } catch (error) {
      compileStatus = 'failed';
      compileError = error instanceof Error ? error.message : String(error);
      compileLogs = compileError;
      notificationStore.error(compileError);
    }
  }
</script>

<UnifiedEmbedFullscreen
  appId="electronics"
  skillId="schematic"
  embedHeaderTitle={skillName}
  embedHeaderSubtitle={statusText || undefined}
  skillIconName="pcbdesign"
  {onClose}
  onCopy={handleCopy}
  onDownload={handleDownload}
  currentEmbedId={embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {navigateDirection}
  {showChatButton}
  {onShowChat}
>
  {#snippet embedHeaderCta()}
    <div class="embed-header-cta-group">
      <EmbedHeaderCtaButton
        label={preparing ? $text('embeds.electronics.pcb_schematic.preparing') : $text('embeds.electronics.pcb_schematic.prepare_files')}
        onclick={handlePrepareFiles}
        testId="pcb-schematic-prepare-files"
      />
      {#if compileLogs || compileError}
        <EmbedHeaderCtaButton
          label={showLogs ? $text('embeds.electronics.pcb_schematic.hide_logs') : $text('embeds.electronics.pcb_schematic.show_logs')}
          onclick={() => (showLogs = !showLogs)}
          testId="pcb-schematic-show-logs"
        />
      {/if}
    </div>
  {/snippet}

  {#snippet content()}
    <div class="pcb-fullscreen-container" class:split-active={showLogs || files.length > 0}>
      <section class="code-panel" data-testid="pcb-schematic-source-panel">
        <div class="code-lines-container" role="presentation">
          {#each highlightedLines as lineHtml, i}
            <div class="code-line" data-line={i + 1}>
              <span class="code-line-gutter" aria-hidden="true">{i + 1}</span>
              <!-- eslint-disable-next-line svelte/no-at-html-tags -->
              <code class="code-line-text">{@html lineHtml}</code>
            </div>
          {/each}
        </div>
      </section>

      <aside class="pcb-side-panel" data-testid="pcb-schematic-compile-panel">
        <div class="compile-card">
          <div class="compile-title">{$text('embeds.electronics.pcb_schematic.prepare_files')}</div>
          <div class="compile-status" data-status={compileStatus}>{compileStatus}</div>
          <p>{$text('embeds.electronics.pcb_schematic.safety_note')}</p>
          {#if compileError && !showLogs}
            <p class="compile-error">{compileError}</p>
          {/if}
        </div>

        {#if files.length > 0 && !showLogs}
          <div class="artifact-list" data-testid="pcb-schematic-artifacts">
            <div class="panel-heading">{$text('embeds.electronics.pcb_schematic.artifacts')}</div>
            {#each files as file}
              <div class="artifact-row">
                {#if activeCompileId}
                  <a href={getPcbSchematicArtifactDownloadUrl(activeCompileId, file.id)} download>{file.name}</a>
                {:else}
                  <span>{file.name}</span>
                {/if}
                <small>{file.type}</small>
              </div>
            {/each}
          </div>
        {/if}

        {#if showLogs}
          <div class="logs-panel" data-testid="pcb-schematic-logs">
            <div class="panel-heading">{$text('embeds.electronics.pcb_schematic.logs')}</div>
            <pre>{compileLogs || compileError || $text('embeds.electronics.pcb_schematic.no_logs')}</pre>
          </div>
        {/if}
      </aside>
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .embed-header-cta-group {
    display: flex;
    gap: var(--spacing-4);
    align-items: center;
  }

  .pcb-fullscreen-container {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(280px, 360px);
    gap: var(--spacing-6);
    width: calc(100% - 10px);
    min-height: calc(100vh - 360px);
    margin: 42px var(--spacing-5) var(--spacing-8);
  }

  .code-panel,
  .pcb-side-panel {
    min-height: 0;
    border-radius: var(--radius-4);
    background: var(--color-grey-15);
    overflow: auto;
  }

  .code-lines-container {
    min-width: max-content;
    padding: var(--spacing-6) 0 var(--spacing-8);
    font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Mono', 'Consolas', monospace;
    font-size: 0.875rem;
    line-height: 1.6;
  }

  .code-line {
    display: grid;
    grid-template-columns: 3.5rem minmax(0, 1fr);
    min-height: 1.6em;
  }

  .code-line-gutter {
    padding: 0 var(--spacing-4) 0 var(--spacing-5);
    color: var(--color-grey-50);
    text-align: right;
    user-select: none;
  }

  .code-line-text {
    padding-right: var(--spacing-8);
    color: var(--color-font-primary);
    white-space: pre;
    background: transparent !important;
  }

  .code-line-text:global(.hljs),
  .code-line-text :global(.hljs) {
    background: transparent !important;
  }

  .pcb-side-panel {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-6);
    padding: var(--spacing-6);
  }

  .compile-card,
  .artifact-list,
  .logs-panel {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-3);
  }

  .compile-title,
  .panel-heading {
    color: var(--color-font-primary);
    font-size: var(--font-size-small);
    font-weight: 700;
  }

  .compile-status {
    width: fit-content;
    padding: var(--spacing-2) var(--spacing-4);
    border-radius: var(--radius-full);
    background: var(--color-grey-25);
    color: var(--color-font-primary);
    font-size: var(--font-size-xs);
    font-weight: 700;
    text-transform: capitalize;
  }

  .compile-status[data-status="succeeded"] {
    background: var(--color-success-light, var(--color-grey-25));
  }

  .compile-status[data-status="failed"] {
    background: var(--color-error-light, var(--color-grey-25));
  }

  .compile-card p,
  .artifact-row small {
    margin: 0;
    color: var(--color-grey-70);
    font-size: var(--font-size-xs);
    line-height: 1.45;
  }

  .compile-error {
    color: var(--color-error, var(--color-font-primary)) !important;
  }

  .artifact-row {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: var(--spacing-3);
    border-radius: var(--radius-3);
    background: var(--color-grey-10);
  }

  .artifact-row span,
  .artifact-row a {
    color: var(--color-font-primary);
    font-size: var(--font-size-xs);
    font-weight: 600;
    overflow-wrap: anywhere;
  }

  .artifact-row a {
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .logs-panel pre {
    max-height: 55vh;
    margin: 0;
    padding: var(--spacing-4);
    overflow: auto;
    border-radius: var(--radius-3);
    background: var(--color-grey-100);
    color: var(--color-grey-0);
    font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Fira Mono', 'Consolas', monospace;
    font-size: var(--font-size-xs);
    line-height: 1.5;
    white-space: pre-wrap;
  }

  @container (max-width: 760px) {
    .pcb-fullscreen-container {
      grid-template-columns: minmax(0, 1fr);
      margin-top: var(--spacing-8);
    }
  }
</style>
