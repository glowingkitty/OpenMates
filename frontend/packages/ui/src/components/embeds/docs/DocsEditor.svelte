<!--
  Manual document editor (minimal slice): a contenteditable page over the
  sanitized document HTML with headings, bold, italic, underline and lists.
  Undo/redo are the browser's native ones (Ctrl/Cmd+Z); Ctrl/Cmd+S saves. Saving is started by
  the fullscreen's header check-mark button (one Edit/Save button for every
  editable embed) through the exported `save()`; onSave receives the cleaned,
  sanitized HTML and rejects with an Error (optionally with code
  `embed_version_conflict`) to keep the editor open.
  Architecture: docs/architecture (embeds) and specifications/features/doc-editor.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { text } from '@repo/ui';
  import { cleanEditedHtml } from './docsEditorHtml';
  import EmbedIconButton from '../shared/EmbedIconButton.svelte';

  interface Props {
    /** Current document HTML (sanitized again on load). */
    html: string;
    /** Persist the edited HTML; reject to keep the editor open and show the error. */
    onSave: (html: string) => Promise<void>;
    onCancel: () => void;
    /** True while a save runs; bound by the fullscreen to show its header button busy. */
    saving?: boolean;
  }

  let { html, onSave, onCancel, saving = $bindable(false) }: Props = $props();

  let contentEl: HTMLDivElement | undefined = $state(undefined);
  let error = $state('');
  let conflict = $state(false);
  /** The loaded HTML as the editor normalises it; saving it unchanged just leaves edit mode. */
  let initialHtml = '';

  onMount(() => {
    if (!contentEl) return;
    contentEl.innerHTML = cleanEditedHtml(html);
    initialHtml = cleanEditedHtml(contentEl.innerHTML);
    // New paragraphs are <p>, not <div>.
    document.execCommand('defaultParagraphSeparator', false, 'p');
    contentEl.focus();
  });

  /** execCommand keeps the user's selection and is undoable with the native undo stack. */
  function format(command: string, value?: string) {
    contentEl?.focus();
    document.execCommand(command, false, value);
  }

  /** Ctrl/Cmd+S saves, as in the code editor. */
  function onKeydown(event: KeyboardEvent) {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      void save();
    }
  }

  /** Keep the text selection when a toolbar button is pressed. */
  function keepSelection(event: MouseEvent) {
    event.preventDefault();
  }

  /** Save the edited HTML (called by the header check-mark button). */
  export async function save(): Promise<void> {
    if (!contentEl || saving) return;
    const edited = cleanEditedHtml(contentEl.innerHTML);
    if (edited === initialHtml) { onCancel(); return; }
    saving = true;
    error = '';
    conflict = false;
    try {
      await onSave(edited);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      conflict = (e as { code?: unknown } | null)?.code === 'embed_version_conflict';
    } finally {
      saving = false;
    }
  }

  const tools = [
    { id: 'bold', label: 'bold', glyph: 'B', run: () => format('bold') },
    { id: 'italic', label: 'italic', glyph: 'I', run: () => format('italic') },
    { id: 'underline', label: 'underline', glyph: 'U', run: () => format('underline') },
    { id: 'h1', label: 'h1', glyph: 'H1', run: () => format('formatBlock', 'h1') },
    { id: 'h2', label: 'h2', glyph: 'H2', run: () => format('formatBlock', 'h2') },
    { id: 'h3', label: 'h3', glyph: 'H3', run: () => format('formatBlock', 'h3') },
    { id: 'paragraph', label: 'paragraph', glyph: '¶', run: () => format('formatBlock', 'p') },
    { id: 'bullets', label: 'bullets', glyph: '•', run: () => format('insertUnorderedList') },
    { id: 'numbers', label: 'numbers', glyph: '1.', run: () => format('insertOrderedList') },
  ] as const;
</script>

<div class="docs-editor" data-testid="docs-editor">
  <div class="toolbar" role="toolbar" aria-label={$text('embed_user_edits.docs_editor_toolbar')}>
    <div class="tools">
      {#each tools as tool (tool.id)}
        {@const label = $text(`embed_user_edits.docs_editor_${tool.label}`)}
        <button
          type="button"
          class="tool tool-{tool.id}"
          data-testid="docs-editor-{tool.id}"
          title={label}
          aria-label={label}
          onmousedown={keepSelection}
          onclick={tool.run}
        >{tool.glyph}</button>
      {/each}
    </div>
    <div class="actions">
      <EmbedIconButton icon="close" label={$text('embed_user_edits.docs_editor_cancel')} testId="docs-editor-cancel" disabled={saving} onclick={onCancel} />
    </div>
  </div>

  {#if error}
    <div class="error" role="alert" data-testid="docs-editor-error">
      <span>{error}</span>
      {#if conflict}
        <button type="button" class="action" data-testid="docs-editor-reload" onclick={() => window.location.reload()}>
          {$text('embed_user_edits.docs_editor_reload')}
        </button>
      {/if}
    </div>
  {/if}

  <div class="paper">
    <div
      class="page"
      contenteditable="true"
      role="textbox"
      tabindex="0"
      aria-multiline="true"
      aria-label={$text('embed_user_edits.docs_editor_label')}
      data-testid="docs-editor-content"
      onkeydown={onKeydown}
      bind:this={contentEl}
    ></div>
  </div>
</div>

<style>
  .docs-editor {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-5);
    width: 100%;
    padding: var(--spacing-8) var(--spacing-5);
    box-sizing: border-box;
  }

  .toolbar {
    position: sticky;
    top: 0;
    z-index: var(--z-index-raised);
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--spacing-4);
    max-width: 794px;
    width: 100%;
    margin: 0 auto;
    padding: var(--spacing-3) var(--spacing-5);
    box-sizing: border-box;
    background: var(--color-grey-0);
    border-radius: var(--radius-5);
    box-shadow: 0 0 0 1px var(--color-grey-30);
  }

  .tools,
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-3);
  }

  .tool {
    min-width: 0;
    min-height: 0;
    width: 36px;
    height: 36px;
    margin: 0;
    padding: 0;
    border: 0;
    border-radius: 50%;
    background: var(--color-grey-10);
    color: var(--color-font-primary);
    font-size: var(--font-size-small);
    font-weight: 600;
    cursor: pointer;
  }

  .tool-italic { font-style: italic; }
  .tool-underline { text-decoration: underline; }
  .tool:hover { background: var(--color-grey-20); }
  .tool:focus-visible,
  .action:focus-visible { outline: 2px solid var(--color-primary-start); outline-offset: 2px; }

  .action {
    min-width: 0;
    min-height: 0;
    margin: 0;
    padding: var(--spacing-3) var(--spacing-8);
    border: 0;
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    box-shadow: 0 0 0 1px var(--color-grey-30);
    font-size: var(--font-size-small);
    cursor: pointer;
  }

  .action:disabled { opacity: 0.6; cursor: default; }

  .error {
    display: flex;
    align-items: center;
    gap: var(--spacing-5);
    max-width: 794px;
    width: 100%;
    margin: 0 auto;
    padding: var(--spacing-4) var(--spacing-5);
    box-sizing: border-box;
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
    box-shadow: 0 0 0 1px var(--color-error, #e74c3c);
    color: var(--color-font-primary);
    font-size: var(--font-size-small);
  }

  .paper {
    max-width: 794px;
    width: 100%;
    margin: 0 auto;
    background: #fff;
    border-radius: 2px;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.35), 0 8px 24px rgba(0, 0, 0, 0.25);
  }

  .page {
    min-height: 480px;
    padding: 96px 72px;
    box-sizing: border-box;
    outline: none;
    font-family: 'Calibri', 'Cambria', Georgia, 'Times New Roman', serif;
    font-size: var(--font-size-small);
    line-height: 1.65;
    color: #202020;
    word-break: break-word;
  }

  .page:focus-visible { box-shadow: inset 0 0 0 2px var(--color-primary-start); }
  .page :global(h1) { font-size: var(--font-size-h2-mobile); font-weight: 700; margin: 0 0 20px; padding-bottom: var(--spacing-5); border-bottom: 2px solid #e8e8e8; color: #1a1a1a; line-height: 1.25; }
  .page :global(h2) { font-size: var(--font-size-h3-mobile); font-weight: 600; margin: 32px 0 10px; color: #1a1a1a; line-height: 1.3; }
  .page :global(h3) { font-weight: 600; margin: 24px 0 8px; color: #2c2c2c; line-height: 1.35; }
  .page :global(p) { margin: 0 0 10px; }
  .page :global(ul),
  .page :global(ol) { margin: 0 0 12px; padding-left: 28px; }

  @media (max-width: 600px) {
    .page { padding: 40px 24px; }
  }
</style>
