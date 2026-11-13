<!--
  frontend/packages/ui/src/components/embeds/code/CodeEditor.svelte

  Plain-text editor of a code file embed fullscreen: monospace textarea with a
  line-number gutter, Tab inserts two spaces (Shift+Tab outdents), Ctrl/Cmd+S
  saves, Escape cancels (asks first when there are unsaved changes). The parent
  owns persistence: `onSave` receives the edited code and may reject; the
  message is shown in `code-editor-error`.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import EmbedIconButton from '../shared/EmbedIconButton.svelte';

  interface Props {
    /** The code to edit (the saved head). */
    code: string;
    /** Saves the edited code; reject to keep the editor open and show the error. */
    onSave: (code: string) => Promise<void>;
    onCancel: () => void;
    /** Error from the parent's save (shown in the editor). */
    error?: string;
    /** Offered next to the error, e.g. to reload after a version conflict. */
    onReload?: () => void;
  }

  let { code, onSave, onCancel, error = '', onReload }: Props = $props();

  // The editor works on its own copy; `code` is only the starting point.
  // svelte-ignore state_referenced_locally
  let draft = $state(code);
  let saving = $state(false);
  let saveError = $state('');
  let textarea: HTMLTextAreaElement | null = $state(null);
  let gutter: HTMLElement | null = $state(null);

  let dirty = $derived(draft !== code);
  let lineCount = $derived(draft.split('\n').length);
  let shownError = $derived(saveError || error);

  $effect(() => { textarea?.focus(); });

  async function save() {
    if (saving || !dirty) return;
    saving = true;
    saveError = '';
    try {
      await onSave(draft);
    } catch (err) {
      saveError = err instanceof Error ? err.message : String(err);
    } finally {
      saving = false;
    }
  }

  function cancel() {
    if (dirty && !window.confirm($text('app_skills.code.editor.discard_confirm'))) return;
    onCancel();
  }

  /** Replaces a range and places the caret synchronously, so keys typed right after Tab land at the caret. */
  function replaceRange(start: number, end: number, value: string, caretStart: number, caretEnd = caretStart) {
    if (!textarea) return;
    textarea.setRangeText(value, start, end);
    textarea.setSelectionRange(caretStart, caretEnd);
    draft = textarea.value;
  }

  /** Tab indents (two spaces; every selected line for a multi-line selection), Shift+Tab outdents. */
  function indent(outdent: boolean) {
    if (!textarea) return;
    const { selectionStart: start, selectionEnd: end } = textarea;
    const multiLine = draft.slice(start, end).includes('\n');
    if (!outdent && !multiLine) {
      replaceRange(start, end, '  ', start + 2);
      return;
    }
    const lineStart = draft.lastIndexOf('\n', start - 1) + 1;
    const block = draft.slice(lineStart, end);
    const lines = block.split('\n');
    const changed = lines.map((line) => outdent ? line.replace(/^ {1,2}/, '') : '  ' + line);
    const delta = changed.join('\n').length - block.length;
    const firstDelta = changed[0].length - lines[0].length;
    replaceRange(lineStart, end, changed.join('\n'), Math.max(lineStart, start + firstDelta), end + delta);
  }

  function onKeydown(event: KeyboardEvent) {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
      event.preventDefault();
      void save();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      cancel();
    } else if (event.key === 'Tab') {
      event.preventDefault();
      indent(event.shiftKey);
    }
  }

  function syncScroll() {
    if (gutter && textarea) gutter.scrollTop = textarea.scrollTop;
  }
</script>

<div class="code-editor" data-testid="code-editor" data-dirty={dirty ? 'true' : 'false'}>
  <div class="code-editor-bar">
    {#if dirty}
      <span class="code-editor-dirty" data-testid="code-editor-dirty">{$text('app_skills.code.editor.unsaved')}</span>
    {/if}
    <EmbedIconButton icon="close" label={$text('common.cancel')} testId="code-editor-cancel" onclick={cancel} />
    <EmbedIconButton icon="check" primary label={$text('common.save')} testId="code-editor-save" disabled={saving || !dirty} onclick={save} />
  </div>
  {#if shownError}
    <div class="code-editor-error" data-testid="code-editor-error" role="alert">
      <span>{shownError}</span>
      {#if onReload}
        <button type="button" class="code-editor-reload" data-testid="code-editor-reload" onclick={onReload}>{$text('app_skills.code.editor.reload')}</button>
      {/if}
    </div>
  {/if}
  <div class="code-editor-body">
    <div class="code-editor-gutter" bind:this={gutter} aria-hidden="true">
      {#each Array.from({ length: lineCount }, (_, i) => i + 1) as n (n)}<div>{n}</div>{/each}
    </div>
    <textarea
      class="code-editor-textarea"
      data-testid="code-editor-textarea"
      aria-label={$text('app_skills.code.editor.label')}
      bind:this={textarea}
      bind:value={draft}
      onkeydown={onKeydown}
      onscroll={syncScroll}
      spellcheck="false"
      autocapitalize="off"
      autocomplete="off"
      wrap="off"
    ></textarea>
  </div>
</div>

<style>
  .code-editor {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-4);
    min-height: 320px;
    height: 100%;
  }

  .code-editor-bar {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: var(--spacing-4);
  }

  .code-editor-dirty {
    margin-inline-end: auto;
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
  }

  .code-editor-error {
    display: flex;
    align-items: center;
    gap: var(--spacing-4);
    padding: var(--spacing-4) var(--spacing-6);
    border-radius: var(--radius-3);
    background: var(--color-grey-10);
    color: var(--color-error);
    font-size: var(--font-size-small);
  }

  .code-editor-reload {
    all: unset;
    cursor: pointer;
    font-weight: 600;
    text-decoration: underline;
  }

  .code-editor-body {
    display: flex;
    flex: 1;
    min-height: 0;
    border-radius: var(--radius-3);
    background: var(--color-grey-10);
    overflow: hidden;
  }

  .code-editor-gutter,
  .code-editor-textarea {
    margin: 0;
    padding: var(--spacing-6) 0;
    font-family: var(--font-family-mono, ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace);
    font-size: var(--font-size-small);
    line-height: 1.5;
    tab-size: 2;
  }

  .code-editor-gutter {
    flex: 0 0 auto;
    min-width: 3ch;
    padding-inline: var(--spacing-5);
    box-sizing: content-box;
    overflow: hidden;
    text-align: end;
    color: var(--color-font-tertiary);
    user-select: none;
  }

  .code-editor-textarea {
    all: unset;
    box-sizing: border-box;
    flex: 1;
    min-width: 0;
    padding: var(--spacing-6) var(--spacing-6) var(--spacing-6) 0;
    font-family: var(--font-family-mono, ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace);
    font-size: var(--font-size-small);
    line-height: 1.5;
    tab-size: 2;
    white-space: pre;
    overflow: auto;
    color: var(--color-font-primary);
  }

  .code-editor-textarea:focus-visible {
    outline: 2px solid var(--color-primary-start);
    outline-offset: -2px;
  }
</style>
