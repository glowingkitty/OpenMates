<script lang="ts">
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import EmbedVersionTimeline from '../shared/EmbedVersionTimeline.svelte';
  import { text } from '../../../i18n/translations';
  import { activeChatStore } from '../../../stores/activeChatStore';
  import { notificationStore } from '../../../stores/notificationStore';
  import { fetchEmbedVersions } from '../../../services/embedDiffStore';
  import { requestEmbedFromServerOnce } from '../../../services/embedResolver';
  import { webSocketService } from '../../../services/websocketService';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import { buildDiagramFrame, normalizeDiagramHtmlContent, validateDiagramHtml } from './diagramHtmlContent';
  import { diagramEditorScript } from './diagramHtmlRuntime';
  import { saveDiagramHtmlRevision } from './diagramHtmlRevision';
  import { classifyDiagramRevisionBroadcast } from './diagramHtmlReceipt';
  import { resolveDiagramVersionView } from './diagramHtmlHistory';

  interface Props {
    data?: EmbedFullscreenRawData;
    onClose: () => void;
    embedId?: string;
    chatId?: string;
    hasPreviousEmbed?: boolean;
    hasNextEmbed?: boolean;
    onNavigatePrevious?: () => void;
    onNavigateNext?: () => void;
    navigateDirection?: 'previous' | 'next';
    showChatButton?: boolean;
    onShowChat?: () => void;
    /** Account-free component preview exercises editing without a stored embed. */
    fixtureEditable?: boolean;
  }
  let { data = { decodedContent: {} }, onClose, embedId, chatId, hasPreviousEmbed = false, hasNextEmbed = false,
    onNavigatePrevious, onNavigateNext, navigateDirection, showChatButton = false, onShowChat,
    fixtureEditable = false }: Props = $props();
  let updated = $state<Record<string, unknown> | null>(null);
  let editing = $state(false);
  let editorReady = $state(false);
  let editable = $state(false);
  let saving = $state(false);
  let draft = $state('');
  let frameSource = $state('');
  let token = $state('');
  let canUndo = $state(false);
  let viewport = $state<HTMLElement | null>(null);
  let frame = $state<HTMLIFrameElement | null>(null);
  let dimensions = $state({ width: 900, height: 620 });
  let zoom = $state(1);
  let panX = $state(0);
  let panY = $state(0);
  let panPointer: { id: number; x: number; y: number } | null = null;
  let error = $state('');
  let historicalSelection = $state<{ version: number; source: string | null; failed?: boolean } | null>(null);
  let sourceResponse: ((source: string) => void) | null = null;
  const raw = $derived(updated ?? data.decodedContent ?? data.attrs ?? {});
  const diagram = $derived(normalizeDiagramHtmlContent(raw));
  const versionView = $derived(resolveDiagramVersionView(diagram.versionNumber, diagram.htmlSource, historicalSelection));
  const effectiveChatId = $derived(chatId || get(activeChatStore) || '');
  const dirty = $derived(editing && draft !== diagram.htmlSource);
  const fittedScale = $derived(Math.min(dimensions.width / diagram.renderWidth, dimensions.height / diagram.renderHeight));
  const scale = $derived(Math.min(5, Math.max(0.05, fittedScale * zoom)));
  const left = $derived((dimensions.width - diagram.renderWidth * scale) / 2 + panX);
  const top = $derived((dimensions.height - diagram.renderHeight * scale) / 2 + panY);
  const render = $derived.by(() => {
    try {
      return { ...buildDiagramFrame(editing ? frameSource : versionView.source,
        editing ? diagramEditorScript(token) : undefined), error: '' };
    } catch (caught) {
      return { srcdoc: '', backgroundColor: '', error: caught instanceof Error ? caught.message : 'Unable to render diagram' };
    }
  });

  onMount(() => {
    if (fixtureEditable) editable = true;
    const observer = new ResizeObserver(() => {
      if (viewport) dimensions = { width: viewport.clientWidth, height: viewport.clientHeight };
    });
    if (viewport) observer.observe(viewport);
    window.addEventListener('message', onFrameMessage);
    webSocketService.on('embed_revision_committed', onRemoteRevision);
    if (!fixtureEditable && embedId && effectiveChatId && diagram.status === 'finished') {
      void fetchEmbedVersions(embedId, { chatId: effectiveChatId }).then((result) => {
        editable = !result.readonly;
      }).catch(() => { editable = false; });
    }
    return () => {
      observer.disconnect();
      window.removeEventListener('message', onFrameMessage);
      webSocketService.off('embed_revision_committed', onRemoteRevision);
    };
  });

  function onUpdate(event: { status: string; decodedContent: Record<string, unknown> }) {
    if (editing && draft !== diagram.htmlSource) {
      error = $text('diagrams.conflict');
      return;
    }
    if (Number(event.decodedContent.version_number) < diagram.versionNumber) return;
    if (Number(event.decodedContent.version_number) > diagram.versionNumber) historicalSelection = null;
    updated = event.decodedContent;
  }
  function onRemoteRevision(payload: unknown) {
    if (!embedId || !payload || typeof payload !== 'object' || (payload as { embed_id?: string }).embed_id !== embedId) return;
    const action = classifyDiagramRevisionBroadcast(saving, editing);
    if (action === 'defer') return;
    if (action === 'conflict') { error = $text('diagrams.conflict'); return; }
    void requestEmbedFromServerOnce(embedId, 'diagram revision committed');
  }
  function onFrameMessage(event: MessageEvent) {
    if (!editing || event.source !== frame?.contentWindow || event.origin !== 'null') return;
    const message = event.data;
    if (!message || message.channel !== 'openmates-diagram-editor-v1' || message.token !== token) return;
    if (message.kind === 'ready') { editorReady = true; return; }
    if (!editorReady) return;
    if (message.kind === 'changed' || message.kind === 'source') {
      if (typeof message.html_source !== 'string') return;
      try { validateDiagramHtml(message.html_source); }
      catch { error = $text('diagrams.invalid_source'); return; }
      draft = message.html_source;
      canUndo = message.can_undo === true;
      if (message.kind === 'source' && sourceResponse) {
        const resolve = sourceResponse;
        sourceResponse = null;
        resolve(draft);
      }
    }
  }
  function command(kind: 'undo' | 'source' | 'cancel') {
    frame?.contentWindow?.postMessage({ channel: 'openmates-diagram-editor-v1', token, kind }, '*');
  }
  function startEdit() {
    if (!editable || !versionView.canEdit || editing || render.error) return;
    token = crypto.randomUUID();
    frameSource = diagram.htmlSource;
    draft = diagram.htmlSource;
    canUndo = false;
    editorReady = false;
    error = '';
    editing = true;
  }
  function cancelEdit() {
    command('cancel');
    editing = false;
    editorReady = false;
    draft = '';
    canUndo = false;
    error = '';
  }
  function requestSource(): Promise<string> {
    if (!editorReady || !frame?.contentWindow) return Promise.reject(new Error('Diagram editor is unavailable'));
    return new Promise((resolve, reject) => {
      sourceResponse = resolve;
      command('source');
      setTimeout(() => {
        if (sourceResponse !== resolve) return;
        sourceResponse = null;
        reject(new Error('Diagram editor did not respond'));
      }, 5000);
    });
  }
  async function save() {
    if (!embedId || !effectiveChatId || saving || !editing || fixtureEditable) return;
    saving = true;
    error = '';
    try {
      const nextSource = await requestSource();
      if (nextSource === diagram.htmlSource) { cancelEdit(); return; }
      const result = await saveDiagramHtmlRevision({ embedId, chatId: effectiveChatId, current: raw,
        originalSource: diagram.htmlSource, editedSource: nextSource });
      updated = { ...raw, html_source: nextSource, version_number: result.version };
      historicalSelection = null;
      editing = false;
      editorReady = false;
      draft = '';
      error = '';
      if (result.cacheSynchronized) notificationStore.success($text('diagrams.saved'));
      else {
        editable = false;
        error = $text('diagrams.saved_refresh');
        void requestEmbedFromServerOnce(embedId, 'diagram local cache reconciliation');
      }
    } catch (caught) {
      error = caught instanceof Error ? caught.message : $text('diagrams.save_failed');
    } finally {
      saving = false;
    }
  }
  async function exportHtml() {
    try {
      const source = editing ? await requestSource() : versionView.source;
      validateDiagramHtml(source);
      const blob = new Blob([source], { type: 'text/html;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `${diagram.title.toLowerCase().replace(/[^a-z0-9]+/g, '-') || 'diagram'}.html`;
      document.body.append(anchor);
      anchor.click(); anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (caught) { error = caught instanceof Error ? caught.message : $text('diagrams.invalid_source'); }
  }
  function selectVersion(version: number, source: string | null) {
    historicalSelection = version >= diagram.versionNumber ? null : { version, source };
    error = '';
  }
  function versionLoadFailed(version: number) {
    if (historicalSelection?.version === version) historicalSelection = { version, source: null, failed: true };
  }
  async function restoreHistoricalVersion(source: string, selectedVersion: number): Promise<{ version: number; content: string }> {
    if (!embedId || !effectiveChatId || !editable || saving || editing || historicalSelection?.version !== selectedVersion) {
      throw new Error($text('diagrams.conflict'));
    }
    saving = true;
    error = '';
    try {
      validateDiagramHtml(source);
      const result = await saveDiagramHtmlRevision({ embedId, chatId: effectiveChatId, current: raw,
        originalSource: diagram.htmlSource, editedSource: source });
      updated = { ...raw, html_source: source, version_number: result.version };
      historicalSelection = null;
      if (result.cacheSynchronized) notificationStore.success($text('diagrams.saved'));
      else {
        editable = false;
        error = $text('diagrams.saved_refresh');
        void requestEmbedFromServerOnce(embedId, 'diagram restore local cache reconciliation');
      }
      return { version: result.version, content: source };
    } catch (caught) {
      error = caught instanceof Error ? caught.message : $text('diagrams.save_failed');
      throw caught;
    } finally {
      saving = false;
    }
  }
  function fit() { zoom = 1; panX = 0; panY = 0; }
  function zoomIn() { zoom = Math.min(5, Number((zoom * 1.25).toFixed(3))); }
  function zoomOut() { zoom = Math.max(0.25, Number((zoom / 1.25).toFixed(3))); }
  function panStart(event: PointerEvent) {
    if (editing || event.button !== 0) return;
    panPointer = { id: event.pointerId, x: event.clientX, y: event.clientY };
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
  }
  function panMove(event: PointerEvent) {
    if (!panPointer || panPointer.id !== event.pointerId) return;
    panX += event.clientX - panPointer.x;
    panY += event.clientY - panPointer.y;
    panPointer = { id: event.pointerId, x: event.clientX, y: event.clientY };
  }
  function panEnd(event: PointerEvent) {
    if (panPointer?.id !== event.pointerId) return;
    panPointer = null;
    (event.currentTarget as HTMLElement).releasePointerCapture(event.pointerId);
  }
</script>

<UnifiedEmbedFullscreen appId="diagrams" skillId="html" skillIconName="diagram" appIconName="diagram" onClose={onClose}
  contentBackgroundColor={render.backgroundColor || undefined}
  embedHeaderTitle={diagram.title} embedHeaderSubtitle={diagram.diagramKind}
  onEdit={editable && versionView.canEdit && diagram.status === 'finished' ? startEdit : undefined} editActive={editing}
  currentEmbedId={embedId} {hasPreviousEmbed} {hasNextEmbed} {onNavigatePrevious} {onNavigateNext}
  {navigateDirection} {showChatButton} {onShowChat} onEmbedDataUpdated={onUpdate}>
  {#snippet content()}
    <div class="diagram-fullscreen" data-testid="diagram-html-fullscreen" style:background-color={render.backgroundColor || undefined}>
      <div bind:this={viewport} class="canvas" role="group" aria-label={`${diagram.title} diagram`} data-testid="diagram-html-canvas" data-editing={editing} data-editor-ready={editorReady} data-historical={versionView.historical}
        style:--diagram-scale={scale} style:--diagram-pan-x={`${panX}px`} style:--diagram-pan-y={`${panY}px`} style:background-color={render.backgroundColor || undefined}
        onpointerdown={panStart} onpointermove={panMove} onpointerup={panEnd} onpointercancel={panEnd}>
        {#if diagram.status === 'processing'}
          <div class="state" data-testid="diagram-html-loading">{$text('diagrams.loading')}</div>
        {:else if render.error}
          <div class="state error" data-testid="diagram-html-error">{render.error}</div>
        {:else}
          <div class="artboard" style:width={`${diagram.renderWidth}px`} style:height={`${diagram.renderHeight}px`}
            style:transform={`translate(${left}px, ${top}px) scale(${scale})`}>
            {#key editing ? token : 'readonly'}
              <iframe bind:this={frame} data-testid="diagram-html-frame" title={`${diagram.title} diagram`}
                sandbox={editing ? 'allow-scripts' : ''} srcdoc={render.srcdoc}
                width={diagram.renderWidth} height={diagram.renderHeight}></iframe>
            {/key}
          </div>
        {/if}
      </div>
      {#if error}<p class="save-error" role="alert" data-testid="diagram-html-save-error">{error}</p>{/if}
      <div class="controls" data-testid="diagram-html-controls">
        <button type="button" data-testid="diagram-html-zoom-out" onclick={zoomOut} aria-label={$text('diagrams.zoom_out')}>−</button>
        <button type="button" data-testid="diagram-html-zoom-fit" onclick={fit} aria-label={$text('diagrams.fit')}>{Math.round(scale * 100)}%</button>
        <button type="button" data-testid="diagram-html-zoom-in" onclick={zoomIn} aria-label={$text('diagrams.zoom_in')}>+</button>
        <button type="button" data-testid="diagram-html-export" onclick={() => void exportHtml()}
          disabled={versionView.pending || versionView.unavailable || (editing && !editorReady)}>{$text('diagrams.export')}</button>
        {#if editing}
          <button type="button" data-testid="diagram-html-undo" onclick={() => command('undo')} disabled={!editorReady || !canUndo}>{$text('diagrams.undo')}</button>
          <button type="button" data-testid="diagram-html-cancel" onclick={cancelEdit}>{$text('diagrams.cancel')}</button>
          <button type="button" data-testid="diagram-html-save" onclick={() => void save()}
            disabled={!editorReady || !dirty || saving || fixtureEditable}>{saving ? $text('diagrams.saving') : $text('diagrams.save')}</button>
        {/if}
      </div>
      {#if versionView.historical}
        <p class="history-note" data-testid="diagram-html-history-indicator">{$text('diagrams.history_version')} {historicalSelection?.version}</p>
      {/if}
      {#if versionView.unavailable}
        <p class="save-error" role="alert" data-testid="diagram-html-history-error">{$text('diagrams.history_unavailable')}</p>
      {/if}
      {#if embedId && effectiveChatId && diagram.versionNumber > 1 && !editing}
        <EmbedVersionTimeline {embedId} chatId={effectiveChatId} currentVersion={diagram.versionNumber}
          currentContent={diagram.htmlSource} onVersionPending={(version) => selectVersion(version, null)}
          onVersionSelect={selectVersion} onVersionError={versionLoadFailed}
          onRestoreVersion={editable ? restoreHistoricalVersion : undefined} />
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .diagram-fullscreen { box-sizing: border-box; width: min(100%, 1440px); margin: var(--spacing-8) auto; padding: 0 var(--spacing-5) var(--spacing-6); }
  .canvas { box-sizing: border-box; position: relative; width: 100%; height: min(72vh, 820px); min-height: 320px; border: 1px solid var(--color-grey-20); border-radius: var(--radius-4); overflow: hidden; background: var(--color-grey-10); cursor: grab; touch-action: none; }
  .canvas[data-editing='true'] { cursor: default; touch-action: auto; }
  .artboard { position: absolute; top: 0; left: 0; transform-origin: top left; }
  iframe { display: block; border: 0; background: transparent; }
  .canvas[data-editing='false'] iframe { pointer-events: none; }
  .state { display: grid; place-items: center; height: 100%; color: var(--color-font-primary); }
  .error, .save-error { color: var(--color-error); }
  .save-error { margin: var(--spacing-3) 0; }
  .history-note { margin: var(--spacing-3) 0 0; text-align: center; color: var(--color-font-secondary); }
  .controls { display: flex; justify-content: center; align-items: center; flex-wrap: wrap; gap: var(--spacing-2); margin-top: var(--spacing-4); }
  .controls button { min-width: 38px; border: 1px solid var(--color-grey-30); border-radius: var(--radius-3); padding: var(--spacing-2) var(--spacing-4); color: var(--color-font-primary); background: var(--color-grey-0); font: inherit; cursor: pointer; }
  .controls button:hover:not(:disabled) { background: var(--color-grey-10); }
  .controls button:disabled { opacity: 0.45; cursor: default; }
</style>
