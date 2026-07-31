<!--
  frontend/packages/ui/src/components/embeds/code/NotebookEmbedFullscreen.svelte

  Fullscreen notebook workspace. Source cells render read-only; Python execution
  is explicit user action through the first-party notebook run API and persisted
  as encrypted sidecar outputs.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import DOMPurify from 'dompurify';
  import 'highlight.js/styles/github-dark.css';
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import MarkdownContent from '../MarkdownContent.svelte';
  import EmbedHeaderCtaButton from '../EmbedHeaderCtaButton.svelte';
  import { text } from '@repo/ui';
  import { authStore } from '../../../stores/authStore';
  import { loginInterfaceOpen } from '../../../stores/uiStateStore';
  import { notificationStore } from '../../../stores/notificationStore';
  import { chatDB } from '../../../services/db';
  import { getNotebookRunOutputForEmbed } from '../../../services/db/notebookRunOutputs';
  import { sendRequestNotebookRunOutputImpl, sendUpsertNotebookRunOutputImpl } from '../../../services/sendersNotebookRunOutputs';
  import { copyToClipboard } from '../../../utils/clipboardUtils';
  import { cancelCodeRun, type CodeRunEvent, type CodeRunStatus } from '../../../services/codeRunService';
  import {
    extractNotebookRunOutput,
    getNotebookRunStatus,
    getNotebookRunStreamUrl,
    startNotebookRun,
    type NotebookRunStreamMessage,
  } from '../../../services/notebookRunService';
  import type { EmbedFullscreenRawData } from '../../../types/embedFullscreen';
  import type { NotebookCellRunOutput, NotebookRunOutput } from '../../../types/chat';
  import { highlightToLines } from './codeHighlighting';
  import { normalizeNotebookContent, notebookTitle, sourceToText, type NotebookCell } from './notebookContent';

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
    chatId?: string;
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
    chatId,
  }: Props = $props();

  let dc = $derived(data.decodedContent ?? {});
  let attrs = $derived(data.attrs ?? {});
  let mergedContent = $derived({ ...attrs, ...dc });
  let normalized = $derived(normalizeNotebookContent(mergedContent));
  let cells = $derived(normalized.notebook?.cells ?? []);
  let skillName = $derived(notebookTitle(normalized));
  let cellCountText = $derived.by(() => {
    const cellLabel = normalized.cellCount === 1 ? $text('embeds.notebook_cell_singular') : $text('embeds.notebook_cell_plural');
    return `${normalized.cellCount} ${cellLabel}, ${$text('embeds.notebook_type')}`;
  });
  let sourceVersion = $derived(normalized.sourceVersion ?? (data.embedData?.version_number ? `v${data.embedData.version_number}` : null));

  const TERMINAL_RUN_STATUSES = new Set(['finished', 'failed', 'timeout', 'cancelled']);
  const OUTPUT_HTML_SANITIZE_OPTIONS: DOMPurify.Config = {
    ALLOWED_TAGS: ['p', 'br', 'strong', 'b', 'em', 'i', 'u', 's', 'del', 'code', 'pre', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'ul', 'ol', 'li', 'span', 'div'],
    ALLOWED_ATTR: ['class', 'title'],
  };

  let savedRunOutput = $state<NotebookRunOutput | null>(null);
  let requestedOutputKey = $state<string | null>(null);
  let runPanelOpen = $state(false);
  let runStatus = $state<CodeRunStatus['status'] | 'idle'>('idle');
  let runExecutionId = $state<string | null>(null);
  let runEvents = $state<CodeRunEvent[]>([]);
  let runError = $state<string | null>(null);
  let runCancelRequested = $state(false);
  let runPollTimer: ReturnType<typeof setTimeout> | null = null;
  let runSocket: WebSocket | null = null;
  let persistedRunExecutionId = $state<string | null>(null);

  let runActive = $derived(runStatus !== 'idle' && !TERMINAL_RUN_STATUSES.has(runStatus));
  let canRunNotebook = $derived(normalized.isPython && !!embedId && !!normalized.notebook);
  let outputByCell = $derived.by(() => {
    const map = new Map<number, NotebookCellRunOutput>();
    for (const output of savedRunOutput?.cell_outputs ?? []) map.set(output.cell_index, output);
    return map;
  });
  let hasStaleOutput = $derived(Boolean(savedRunOutput?.source_version && sourceVersion && savedRunOutput.source_version !== sourceVersion));
  let visibleRunEvents = $derived(runEvents.map((event) => ({ ...event, text: stripNotebookOutputEnvelope(event.text) })).filter((event) => event.text));

  function codeCellIndices(): number[] {
    return cells
      .map((cell, index) => cell.cell_type === 'code' && sourceToText(cell.source).trim() ? index : -1)
      .filter((index) => index >= 0);
  }

  function highlightedCodeLines(cell: NotebookCell): string[] {
    return highlightToLines(sourceToText(cell.source), normalized.language === 'python' ? 'python' : normalized.language);
  }

  function stripNotebookOutputEnvelope(text: string): string {
    return text
      .replace(/OPENMATES_NOTEBOOK_OUTPUT_JSON_START[\s\S]*?OPENMATES_NOTEBOOK_OUTPUT_JSON_END/g, '')
      .trimEnd();
  }

  function outputText(value: unknown): string {
    if (typeof value === 'string') return value;
    if (Array.isArray(value) && value.every((part) => typeof part === 'string')) return value.join('');
    if (value === null || value === undefined) return '';
    return String(value);
  }

  function outputData(output: unknown, key: string): unknown {
    if (!output || typeof output !== 'object') return null;
    const data = (output as Record<string, unknown>).data;
    if (!data || typeof data !== 'object') return null;
    return (data as Record<string, unknown>)[key];
  }

  function outputType(output: unknown): string {
    return output && typeof output === 'object' && typeof (output as Record<string, unknown>).output_type === 'string'
      ? String((output as Record<string, unknown>).output_type)
      : '';
  }

  function streamText(output: unknown): string {
    if (!output || typeof output !== 'object') return '';
    return outputText((output as Record<string, unknown>).text);
  }

  function errorText(output: unknown): string {
    if (!output || typeof output !== 'object') return '';
    const record = output as Record<string, unknown>;
    if (Array.isArray(record.traceback)) return record.traceback.map(outputText).join('\n');
    return [record.ename, record.evalue].map(outputText).filter(Boolean).join(': ');
  }

  function plainDataText(output: unknown): string {
    return outputText(outputData(output, 'text/plain'));
  }

  function htmlData(output: unknown): string {
    const html = outputText(outputData(output, 'text/html'));
    return html ? DOMPurify.sanitize(html, OUTPUT_HTML_SANITIZE_OPTIONS) : '';
  }

  function imageDataUrl(output: unknown): string {
    const png = outputText(outputData(output, 'image/png')).replace(/\s/g, '');
    if (png) return `data:image/png;base64,${png}`;
    const svg = outputText(outputData(output, 'image/svg+xml'));
    if (svg) return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
    return '';
  }

  function runOutputText(): string {
    return visibleRunEvents.map((event) => event.text).join('').trimEnd();
  }

  function translate(key: string, vars: Record<string, unknown> = {}): string {
    return get(text)(key, vars);
  }

  async function copyRunLog() {
    const text = runOutputText();
    if (!text) return;
    const result = await copyToClipboard(text);
    if (result.success) notificationStore.success(translate('app_skills.code.run.output_copied'));
    else notificationStore.error(translate('app_skills.code.run.output_copy_failed'));
  }

  async function loadSavedRunOutput() {
    if (!embedId) return;
    try {
      const output = await getNotebookRunOutputForEmbed(chatDB, embedId);
      if (output) savedRunOutput = output;
    } catch (error) {
      console.warn('[NotebookEmbedFullscreen] Failed to load saved notebook output:', error);
    }
  }

  $effect(() => {
    void loadSavedRunOutput();
    const requestKey = chatId && embedId ? `${chatId}:${embedId}` : null;
    if (chatId && embedId && requestedOutputKey !== requestKey) {
      requestedOutputKey = requestKey;
      void sendRequestNotebookRunOutputImpl(chatId, embedId);
    }
  });

  onMount(() => {
    const handleSyncedOutput = (event: Event) => {
      const output = (event as CustomEvent<NotebookRunOutput>).detail;
      if (!embedId || output.notebook_embed_id !== embedId) return;
      savedRunOutput = output;
    };
    window.addEventListener('notebookRunOutputSynced', handleSyncedOutput);
    return () => window.removeEventListener('notebookRunOutputSynced', handleSyncedOutput);
  });

  function clearRunPollTimer() {
    if (runPollTimer) {
      clearTimeout(runPollTimer);
      runPollTimer = null;
    }
  }

  function closeRunSocket() {
    if (runSocket) {
      runSocket.onclose = null;
      runSocket.onerror = null;
      runSocket.onmessage = null;
      runSocket.close();
      runSocket = null;
    }
  }

  function syncRunStatus(status: CodeRunStatus) {
    runStatus = status.status;
    runCancelRequested = status.status === 'cancelling';
    runEvents = status.events || [];
    runError = status.error || null;
  }

  function applyRunUpdate(update: Partial<CodeRunStatus>) {
    if (update.status) runStatus = update.status;
    if (update.status === 'cancelling') runCancelRequested = true;
    if (update.status && TERMINAL_RUN_STATUSES.has(update.status)) runCancelRequested = false;
    if (update.error !== undefined) runError = update.error || null;
  }

  function appendRunEvent(event: CodeRunEvent) {
    runEvents = [...runEvents, event];
  }

  function openRunStream(executionId: string) {
    closeRunSocket();
    const socket = new WebSocket(getNotebookRunStreamUrl(executionId));
    runSocket = socket;
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data) as NotebookRunStreamMessage;
      if (message.type === 'code_run_snapshot') {
        syncRunStatus(message.payload);
        return;
      }
      if (message.type === 'code_run_update') {
        applyRunUpdate(message.payload);
        return;
      }
      if (message.type === 'code_run_event') appendRunEvent(message.payload);
    };
    socket.onerror = () => socket.close();
    socket.onclose = () => {
      if (runSocket === socket) runSocket = null;
      if (runExecutionId === executionId && !TERMINAL_RUN_STATUSES.has(runStatus)) pollRunStatus(executionId);
    };
  }

  async function pollRunStatus(executionId: string) {
    try {
      const status = await getNotebookRunStatus(executionId);
      syncRunStatus(status);
      if (!TERMINAL_RUN_STATUSES.has(status.status)) runPollTimer = setTimeout(() => pollRunStatus(executionId), 1000);
    } catch (error) {
      runStatus = 'failed';
      runError = error instanceof Error ? error.message : 'Notebook run status unavailable';
      runEvents = [...runEvents, { kind: 'stderr', text: `${runError}\n`, timestamp: Date.now() / 1000 }];
    }
  }

  async function handleRun(cellIndex?: number) {
    if (!$authStore.isAuthenticated) {
      loginInterfaceOpen.set(true);
      return;
    }
    if (!chatId || !embedId || !normalized.notebook || runActive) return;
    const selected = cellIndex === undefined ? codeCellIndices() : [cellIndex];
    if (selected.length === 0) return;
    clearRunPollTimer();
    closeRunSocket();
    runPanelOpen = true;
    runStatus = 'queued';
    runError = null;
    runCancelRequested = false;
    runEvents = [{ kind: 'status', text: `${translate('embeds.notebook_running')}\n`, timestamp: Date.now() / 1000 }];
    try {
      const started = await startNotebookRun(chatId, embedId, normalized.notebook as unknown as Record<string, unknown>, {
        runScope: cellIndex === undefined ? 'all' : 'cells',
        cellIndices: cellIndex === undefined ? undefined : selected,
        sourceVersion,
      });
      runExecutionId = started.execution_id;
      persistedRunExecutionId = null;
      runStatus = started.status as CodeRunStatus['status'];
      runEvents = [
        { kind: 'status', text: `Queued notebook run. Pricing: ${started.credits_per_minute} credits per started minute.\n`, timestamp: Date.now() / 1000 },
      ];
      openRunStream(started.execution_id);
    } catch (error) {
      runStatus = 'failed';
      runError = error instanceof Error ? error.message : 'Notebook run failed to start';
      runEvents = [{ kind: 'stderr', text: `${runError}\n`, timestamp: Date.now() / 1000 }];
    }
  }

  async function handleCancelRun() {
    if (!runExecutionId || !runActive || runCancelRequested) return;
    runCancelRequested = true;
    try {
      const result = await cancelCodeRun(runExecutionId);
      runStatus = result.status;
      runEvents = [...runEvents, { kind: 'status', text: `${translate('app_skills.code.run.cancelling')}\n`, timestamp: Date.now() / 1000 }];
    } catch (error) {
      runCancelRequested = false;
      runError = error instanceof Error ? error.message : 'Notebook run cancellation failed';
      runEvents = [...runEvents, { kind: 'stderr', text: `${runError}\n`, timestamp: Date.now() / 1000 }];
    }
  }

  async function persistRunOutput() {
    if (!chatId || !embedId || !runExecutionId || persistedRunExecutionId === runExecutionId) return;
    const extracted = extractNotebookRunOutput(runEvents);
    if (!extracted || extracted.cell_outputs.length === 0) return;

    persistedRunExecutionId = runExecutionId;
    const savedAt = Date.now();
    const now = Math.floor(savedAt / 1000);
    const outputId = savedRunOutput?.id ?? crypto.randomUUID();
    try {
      await sendUpsertNotebookRunOutputImpl({
        id: outputId,
        chat_id: chatId,
        notebook_embed_id: embedId,
        source_version: sourceVersion,
        status: extracted.status ?? runStatus,
        selected_cell_indices: extracted.selected_cell_indices,
        cell_outputs: extracted.cell_outputs,
        error: extracted.error,
        saved_at: savedAt,
        created_at: now,
        updated_at: now,
      });
      savedRunOutput = {
        id: outputId,
        chat_id: chatId,
        notebook_embed_id: embedId,
        source_version: sourceVersion,
        status: extracted.status ?? runStatus,
        selected_cell_indices: extracted.selected_cell_indices,
        cell_outputs: extracted.cell_outputs,
        error: extracted.error,
        saved_at: savedAt,
        created_at: now,
        updated_at: now,
      };
    } catch (error) {
      console.warn('[NotebookEmbedFullscreen] Failed to persist notebook output:', error);
      persistedRunExecutionId = null;
    }
  }

  $effect(() => {
    if (runExecutionId && TERMINAL_RUN_STATUSES.has(runStatus)) void persistRunOutput();
  });

  $effect(() => {
    return () => {
      clearRunPollTimer();
      closeRunSocket();
    };
  });
</script>

<UnifiedEmbedFullscreen
  appId="code"
  skillId="notebook"
  embedHeaderTitle={skillName}
  embedHeaderSubtitle={cellCountText}
  skillIconName="coding"
  {onClose}
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
    {#if canRunNotebook}
      <EmbedHeaderCtaButton label={$text('embeds.notebook_run_all')} onclick={() => handleRun()} testId="notebook-run-all-button" />
    {:else if normalized.notebook && !normalized.isPython}
      <div class="notebook-run-disabled" data-testid="notebook-python-only">{$text('embeds.notebook_python_only')}</div>
    {/if}
  {/snippet}

  {#snippet content()}
    <div class="notebook-fullscreen" data-testid="notebook-fullscreen">
      {#if hasStaleOutput}
        <div class="notebook-stale-output" data-testid="notebook-stale-output">{$text('embeds.notebook_stale_outputs')}</div>
      {/if}

      {#if runPanelOpen}
        <section class="notebook-run-panel" data-testid="notebook-run-panel" aria-live="polite">
          <div class="notebook-run-panel-header">
            <div class="notebook-run-panel-title">{$text('embeds.notebook_run')}</div>
            <div class="notebook-run-panel-status">{runStatus}</div>
          </div>
          <pre class="notebook-run-log">{#each visibleRunEvents as event}<span class={`notebook-run-line notebook-run-${event.kind}`}>{event.text}</span>{/each}</pre>
          <div class="notebook-run-actions">
            {#if runActive}
              <button type="button" data-testid="notebook-cancel-run" onclick={handleCancelRun} disabled={runCancelRequested}>
                {$text('embeds.notebook_cancel')}
              </button>
            {/if}
            <button type="button" data-testid="notebook-copy-run-log" onclick={copyRunLog} disabled={!runOutputText()}>
              {$text('app_skills.code.run.copy_output')}
            </button>
          </div>
        </section>
      {/if}

      {#if cells.length === 0}
        <div class="notebook-empty">{$text('embeds.notebook_no_content')}</div>
      {:else}
        <div class="notebook-cells">
          {#each cells as cell, index}
            {@const cellOutput = outputByCell.get(index)}
            <section class="notebook-cell" data-testid="notebook-cell" data-cell-index={index}>
              <div class="notebook-cell-header">
                <span class="notebook-cell-index">[{index + 1}]</span>
                <span class="notebook-cell-type">{cell.cell_type}</span>
                {#if canRunNotebook && cell.cell_type === 'code' && sourceToText(cell.source).trim()}
                  <button type="button" class="notebook-run-cell" data-testid="notebook-run-cell-button" onclick={() => handleRun(index)} disabled={runActive}>
                    {$text('embeds.notebook_run_cell')}
                  </button>
                {/if}
              </div>

              {#if cell.cell_type === 'markdown'}
                <div class="notebook-markdown-cell">
                  <MarkdownContent content={sourceToText(cell.source)} />
                </div>
              {:else if cell.cell_type === 'code'}
                <div class="notebook-code-cell">
                  <div class="notebook-code-lines" data-testid="notebook-code-lines">
                    {#each highlightedCodeLines(cell) as lineHtml, lineIndex}
                      <div class="notebook-code-line">
                        <span class="notebook-code-gutter" aria-hidden="true">{lineIndex + 1}</span>
                        <!-- eslint-disable-next-line svelte/no-at-html-tags -->
                        <code>{@html lineHtml}</code>
                      </div>
                    {/each}
                  </div>
                </div>
              {:else}
                <pre class="notebook-raw-cell">{sourceToText(cell.source)}</pre>
              {/if}

              {#if cellOutput}
                <div class="notebook-cell-output" data-testid="notebook-cell-output">
                  <div class="notebook-output-heading">{$text('embeds.notebook_output')}</div>
                  {#each cellOutput.outputs as output}
                    {@const imageSrc = imageDataUrl(output)}
                    {@const html = htmlData(output)}
                    {@const plainText = streamText(output) || errorText(output) || plainDataText(output)}
                    <div class="notebook-output-block" data-output-type={outputType(output)}>
                      {#if imageSrc}
                        <img src={imageSrc} alt={$text('embeds.notebook_output')} />
                      {:else if html}
                        <!-- eslint-disable-next-line svelte/no-at-html-tags -- sanitized via DOMPurify above -->
                        <div class="notebook-output-html">{@html html}</div>
                      {:else if plainText}
                        <pre class="notebook-output-text">{plainText}</pre>
                      {/if}
                    </div>
                  {/each}
                </div>
              {/if}
            </section>
          {/each}
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .notebook-fullscreen {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-6);
    width: calc(100% - 10px);
    min-height: 0;
    margin: 42px var(--spacing-5) var(--spacing-8);
    color: var(--color-grey-100);
  }

  .notebook-run-disabled,
  .notebook-stale-output {
    color: var(--color-grey-70);
    font-size: var(--font-size-small);
    font-weight: 700;
  }

  .notebook-stale-output {
    padding: var(--spacing-3) var(--spacing-4);
    border-radius: var(--radius-3);
    background: var(--color-grey-20);
  }

  .notebook-run-panel {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-4);
    padding: var(--spacing-5);
    border-radius: var(--radius-4);
    background: var(--color-grey-0);
    box-shadow: var(--shadow-md);
  }

  .notebook-run-panel-header,
  .notebook-run-actions,
  .notebook-cell-header {
    display: flex;
    align-items: center;
    gap: var(--spacing-3);
  }

  .notebook-run-panel-title {
    font-size: var(--font-size-p);
    font-weight: 800;
  }

  .notebook-run-panel-status,
  .notebook-cell-type {
    color: var(--color-grey-60);
    font-size: var(--font-size-small);
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .notebook-run-log {
    min-height: 5rem;
    max-height: 18rem;
    overflow: auto;
    margin: 0;
    padding: var(--spacing-4);
    border-radius: var(--radius-3);
    background: var(--color-grey-10);
    color: var(--color-grey-90);
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: var(--font-size-small);
    white-space: pre-wrap;
  }

  .notebook-run-actions button,
  .notebook-run-cell {
    height: auto;
    min-height: 2.4rem;
    margin: 0;
    padding: 0 var(--spacing-4);
    border-radius: 999px;
    font-size: var(--font-size-small);
    font-weight: 800;
  }

  .notebook-cells {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-6);
  }

  .notebook-cell {
    overflow: hidden;
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-4);
    background: var(--color-grey-10);
  }

  .notebook-cell-header {
    min-height: 3.5rem;
    padding: 0 var(--spacing-5);
    border-bottom: 1px solid var(--color-grey-20);
    background: var(--color-grey-20);
  }

  .notebook-cell-index {
    color: var(--color-grey-80);
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: var(--font-size-small);
    font-weight: 800;
  }

  .notebook-run-cell {
    margin-left: auto;
  }

  .notebook-markdown-cell {
    padding: var(--spacing-5);
    background: var(--color-grey-0);
  }

  .notebook-code-cell,
  .notebook-raw-cell {
    margin: 0;
    background: var(--color-grey-20);
  }

  .notebook-code-lines {
    overflow: auto;
    padding: var(--spacing-4) 0;
  }

  .notebook-code-line {
    display: flex;
    min-width: max-content;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: var(--font-size-small);
    line-height: 1.55;
  }

  .notebook-code-gutter {
    flex: 0 0 4rem;
    padding-right: var(--spacing-4);
    color: var(--color-grey-50);
    text-align: right;
    user-select: none;
  }

  .notebook-code-line code {
    padding-right: var(--spacing-5);
    white-space: pre;
  }

  .notebook-raw-cell {
    padding: var(--spacing-5);
    color: var(--color-grey-80);
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    white-space: pre-wrap;
  }

  .notebook-cell-output {
    padding: var(--spacing-4) var(--spacing-5) var(--spacing-5);
    border-top: 1px solid var(--color-grey-20);
    background: var(--color-grey-0);
  }

  .notebook-output-heading {
    margin-bottom: var(--spacing-3);
    color: var(--color-grey-60);
    font-size: var(--font-size-small);
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .notebook-output-block + .notebook-output-block {
    margin-top: var(--spacing-3);
  }

  .notebook-output-text {
    overflow: auto;
    margin: 0;
    padding: var(--spacing-4);
    border-radius: var(--radius-3);
    background: var(--color-grey-10);
    color: var(--color-grey-90);
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: var(--font-size-small);
    white-space: pre-wrap;
  }

  .notebook-output-html {
    overflow: auto;
    padding: var(--spacing-4);
    border-radius: var(--radius-3);
    background: var(--color-grey-10);
  }

  .notebook-output-block img {
    max-width: 100%;
    border-radius: var(--radius-3);
    background: var(--color-grey-10);
  }

  .notebook-empty {
    padding: var(--spacing-8);
    border-radius: var(--radius-4);
    background: var(--color-grey-20);
    color: var(--color-grey-70);
    text-align: center;
  }

  @media (max-width: 768px) {
    .notebook-fullscreen {
      margin: var(--spacing-6) var(--spacing-3) var(--spacing-8);
      width: calc(100% - var(--spacing-6));
    }

    .notebook-cell-header {
      flex-wrap: wrap;
      padding: var(--spacing-3) var(--spacing-4);
    }

    .notebook-run-cell {
      margin-left: 0;
      width: 100%;
    }
  }
</style>
