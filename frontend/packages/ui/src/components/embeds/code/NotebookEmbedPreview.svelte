<!--
  frontend/packages/ui/src/components/embeds/code/NotebookEmbedPreview.svelte

  Preview component for Jupyter notebook embeds. It renders the first notebook
  cells as inert source previews and never exposes execution controls in the
  chat card.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import 'highlight.js/styles/github-dark.css';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  import { chatDB } from '../../../services/db';
  import { getNotebookRunOutputForEmbed } from '../../../services/db/notebookRunOutputs';
  import type { NotebookRunOutput } from '../../../types/chat';
  import { normalizeNotebookContent, notebookTitle, sourceToText, type NotebookCell } from './notebookContent';

  interface Props {
    id: string;
    notebook?: unknown;
    filename?: string;
    cellCount?: number;
    language?: string;
    sourceVersion?: string | null;
    status: 'processing' | 'finished' | 'error' | 'cancelled';
    taskId?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
    content?: Record<string, unknown> | null;
  }

  let {
    id,
    notebook,
    filename,
    cellCount = 0,
    language,
    sourceVersion = null,
    status,
    taskId,
    isMobile = false,
    onFullscreen,
    content = null,
  }: Props = $props();

  let localContent = $state<Record<string, unknown>>({});
  let savedRunOutput = $state<NotebookRunOutput | null>(null);
  let isLargePreview = $state(false);

  $effect(() => {
    localContent = {
      ...(content ?? {}),
      ...(notebook ? { notebook } : {}),
      ...(filename ? { filename } : {}),
      ...(cellCount ? { cell_count: cellCount } : {}),
      ...(language ? { language } : {}),
      ...(sourceVersion ? { source_version: sourceVersion } : {}),
    };
  });

  let normalized = $derived(normalizeNotebookContent(localContent));
  let title = $derived(normalized.filename || notebookTitle(normalized));
  let previewCellLimit = $derived(isLargePreview ? 5 : 3);
  let previewCells = $derived((normalized.notebook?.cells ?? []).slice(0, previewCellLimit));
  let statusText = $derived.by(() => {
    const count = normalized.cellCount || previewCells.length;
    const cellLabel = count === 1 ? $text('embeds.notebook_cell_singular') : $text('embeds.notebook_cell_plural');
    return `${count} ${cellLabel}, ${$text('embeds.notebook_type')}`;
  });
  let hasSavedOutput = $derived(Boolean(savedRunOutput?.cell_outputs?.length));

  function firstLine(cell: NotebookCell): string {
    return sourceToText(cell.source).trim().split('\n').find(Boolean) ?? '';
  }

  function codePreviewLines(cell: NotebookCell): string[] {
    return sourceToText(cell.source).split('\n').slice(0, isLargePreview ? 6 : 3);
  }

  async function loadSavedRunOutput() {
    if (!id) return;
    try {
      const output = await getNotebookRunOutputForEmbed(chatDB, id);
      if (output) savedRunOutput = output;
    } catch (error) {
      console.warn('[NotebookEmbedPreview] Failed to load saved notebook output:', error);
    }
  }

  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> | null }) {
    if (data.decodedContent) localContent = data.decodedContent;
  }

  onMount(() => {
    void loadSavedRunOutput();
    const handleSyncedOutput = (event: Event) => {
      const output = (event as CustomEvent<NotebookRunOutput>).detail;
      if (output.notebook_embed_id === id) savedRunOutput = output;
    };
    window.addEventListener('notebookRunOutputSynced', handleSyncedOutput);
    return () => window.removeEventListener('notebookRunOutputSynced', handleSyncedOutput);
  });
</script>

<UnifiedEmbedPreview
  {id}
  appId="code"
  skillId="notebook"
  skillIconName="coding"
  appIconName="code"
  {status}
  skillName={title}
  {taskId}
  {isMobile}
  {onFullscreen}
  customStatusText={statusText}
  showSkillIcon={false}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isLarge: isLargeLayout = false })}
    {(isLargePreview = isLargeLayout, undefined)}
    <div class="notebook-preview" data-testid="notebook-preview">
      {#if previewCells.length === 0}
        <div class="notebook-preview-empty">{$text('embeds.notebook_empty')}</div>
      {:else}
        {#each previewCells as cell, index}
          <div class="notebook-preview-cell" data-testid="notebook-preview-cell">
            <div class="notebook-cell-kind">{index + 1}. {cell.cell_type}</div>
            {#if cell.cell_type === 'code'}
              <pre class="notebook-code-preview" data-testid="notebook-preview-code-lines">{#each codePreviewLines(cell) as line}<code data-testid="notebook-preview-code-line">{line}</code>{/each}</pre>
            {:else}
              <div class="notebook-markdown-preview">{firstLine(cell)}</div>
            {/if}
          </div>
        {/each}
      {/if}
      {#if hasSavedOutput}
        <div class="notebook-output-pill" data-testid="notebook-output-pill">
          {$text('embeds.notebook_saved_outputs')}
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .notebook-preview {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-3);
    width: 100%;
    height: 100%;
    min-height: 0;
    overflow: hidden;
    color: var(--color-grey-100);
  }

  .notebook-preview-cell {
    min-width: 0;
    border-left: 0.2rem solid var(--color-grey-40);
    padding-left: var(--spacing-3);
  }

  .notebook-cell-kind {
    color: var(--color-grey-60);
    font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    font-size: 0.9rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .notebook-markdown-preview,
  .notebook-code-preview {
    margin: var(--spacing-1) 0 0;
    font-size: var(--font-size-small);
    line-height: 1.35;
  }

  .notebook-markdown-preview {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .notebook-code-preview {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
    overflow: hidden;
    color: var(--color-grey-90);
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    white-space: pre;
  }

  .notebook-code-preview code {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    margin: 0;
    padding: 0;
    border: 0;
    border-radius: 0;
    background: transparent !important;
    color: inherit;
    font: inherit;
  }

  .notebook-code-preview code:global(.hljs),
  .notebook-code-preview code :global(.hljs) {
    background: transparent !important;
    padding: 0 !important;
  }

  .notebook-code-preview code :global(span) {
    background: transparent !important;
  }

  .notebook-output-pill {
    align-self: flex-start;
    margin-top: auto;
    padding: 0.25rem 0.65rem;
    border-radius: 999px;
    background: var(--color-grey-20);
    color: var(--color-grey-80);
    font-size: 0.9rem;
    font-weight: 700;
  }

  .notebook-preview-empty {
    color: var(--color-grey-60);
    font-size: var(--font-size-small);
  }
</style>
