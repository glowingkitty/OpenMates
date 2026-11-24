<!--
  Live document editor (flag live_collaboration): TipTap bound to a local Y.Doc mirror
  (field "default"). The mirror only exchanges opaque update bytes with the Rust core
  through the live item client; merging, sealing, saving and access are the core's.
  Remote cursors render from the core's presence (CollaborationCaret). There is no Save
  button: edits are saved by the core; the header Edit button enters and leaves editing.
  Keeps the toolbar and data-testid selectors of DocsEditor.
  Architecture: docs/plans/live-collaboration-crdt/build-contract.md section 5.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { Editor } from '@tiptap/core';
  import StarterKit from '@tiptap/starter-kit';
  import Collaboration from '@tiptap/extension-collaboration';
  import CollaborationCaret from '@tiptap/extension-collaboration-caret';
  import { text } from '@repo/ui';
  import { RawBlock } from './rawBlockNode';
  import EmbedIconButton from '../shared/EmbedIconButton.svelte';
  import { liveItemClient } from '../../../services/live/liveItemClient';
  import { bindLiveMirror, type LiveMirror } from '../../../services/live/liveMirror';
  import type { LiveItemClient, LivePeer, LiveStatus } from '../../../services/live/liveItemTypes';

  interface Props {
    itemId: string;
    projectId?: string;
    teamId?: string;
    /** The signed-in person as shown to others (name and colour come from the core's profile). */
    self: Pick<LivePeer, 'display_name' | 'color'>;
    /** Leaves edit mode (the header Edit button does the same). */
    onCancel: () => void;
    client?: LiveItemClient;
    status?: LiveStatus;
    peers?: LivePeer[];
  }

  let { itemId, projectId, teamId, self, onCancel, client = liveItemClient(), status = $bindable('saving'), peers = $bindable([]) }: Props = $props();

  let contentEl: HTMLDivElement | undefined = $state(undefined);
  let editor: Editor | null = null;
  let mirror: LiveMirror | null = null;
  let readOnly = $derived(status === 'read_only' || status === 'access_revoked');

  onMount(() => {
    if (!contentEl) return;
    mirror = bindLiveMirror(client, itemId, 'doc', self, (s) => { status = s; }, (p) => { peers = p; }, projectId, teamId);
    editor = new Editor({
      element: contentEl,
      extensions: [
        StarterKit.configure({ undoRedo: false }),
        RawBlock,
        Collaboration.configure({ document: mirror.doc, field: 'default' }),
        CollaborationCaret.configure({
          provider: { awareness: mirror.awareness },
          user: { name: self.display_name, color: self.color },
          render: (user: { name?: string; color?: string; mate?: string | null }) => {
            const caret = document.createElement('span');
            caret.classList.add('collaboration-carets__caret');
            caret.style.borderColor = user.color ?? '#999';
            const label = document.createElement('div');
            label.classList.add('collaboration-carets__label');
            label.style.backgroundColor = user.color ?? '#999';
            // An assistant's caret says it is editing here; a person's shows the name.
            label.textContent = user.mate
              ? $text('embed_user_edits.live_editing_here', { values: { name: user.mate } })
              : (user.name ?? '');
            if (user.mate) caret.dataset.mate = 'true';
            caret.appendChild(label);
            return caret;
          },
        }),
      ],
      editorProps: {
        handleKeyDown: (_view, event) => {
          if (!client.liveUndoLatestAssistant || !(event.metaKey || event.ctrlKey) ||
              event.shiftKey || event.altKey || event.key.toLowerCase() !== 'z') return false;
          void client.liveUndoLatestAssistant(itemId).then(
            (undone) => { if (!undone) editor?.commands.undo(); },
            () => { editor?.commands.undo(); },
          );
          return true;
        },
        attributes: {
          role: 'textbox',
          'aria-multiline': 'true',
          'aria-label': $text('embed_user_edits.docs_editor_label'),
          'data-testid': 'docs-editor-content',
        },
      },
      autofocus: 'end',
    });
    return () => {
      editor?.destroy();
      mirror?.destroy();
      editor = null;
      mirror = null;
    };
  });

  $effect(() => { editor?.setEditable(!readOnly); });

  /** Leaves edit mode; the core has already saved every change. */
  export async function save(): Promise<void> { onCancel(); }

  const tools = [
    { id: 'bold', label: 'bold', glyph: 'B', run: (e: Editor) => e.chain().focus().toggleBold().run() },
    { id: 'italic', label: 'italic', glyph: 'I', run: (e: Editor) => e.chain().focus().toggleItalic().run() },
    { id: 'underline', label: 'underline', glyph: 'U', run: (e: Editor) => e.chain().focus().toggleUnderline().run() },
    { id: 'h1', label: 'h1', glyph: 'H1', run: (e: Editor) => e.chain().focus().toggleHeading({ level: 1 }).run() },
    { id: 'h2', label: 'h2', glyph: 'H2', run: (e: Editor) => e.chain().focus().toggleHeading({ level: 2 }).run() },
    { id: 'h3', label: 'h3', glyph: 'H3', run: (e: Editor) => e.chain().focus().toggleHeading({ level: 3 }).run() },
    { id: 'paragraph', label: 'paragraph', glyph: '¶', run: (e: Editor) => e.chain().focus().setParagraph().run() },
    { id: 'bullets', label: 'bullets', glyph: '•', run: (e: Editor) => e.chain().focus().toggleBulletList().run() },
    { id: 'numbers', label: 'numbers', glyph: '1.', run: (e: Editor) => e.chain().focus().toggleOrderedList().run() },
  ] as const;

  /** Keep the text selection when a toolbar button is pressed. */
  function keepSelection(event: MouseEvent) { event.preventDefault(); }
</script>

<div class="docs-editor" data-testid="docs-editor" data-live="true" data-status={status}>
  <div class="toolbar" role="toolbar" aria-label={$text('embed_user_edits.docs_editor_toolbar')}>
    <div class="tools">
      {#each tools as tool (tool.id)}
        {@const label = $text(`embed_user_edits.docs_editor_${tool.label}`)}
        <button
          type="button"
          class="tool tool-{tool.id}"
          title={label}
          aria-label={label}
          disabled={readOnly}
          onmousedown={keepSelection}
          data-testid="docs-editor-{tool.id}" onclick={() => editor && tool.run(editor)}
        >{tool.glyph}</button>
      {/each}
    </div>
    <div class="actions">
      <EmbedIconButton icon="close" label={$text('embed_user_edits.docs_editor_cancel')} testId="docs-editor-cancel" onclick={onCancel} />
      <!-- ui-control-visibility: allow — EmbedIconButton forwards testId to its button. -->
    </div>
  </div>

  <div class="paper">
    <div class="page" bind:this={contentEl}></div>
  </div>
</div>

<style>
  .docs-editor { display: flex; flex-direction: column; gap: var(--spacing-5); width: 100%; padding: var(--spacing-8) var(--spacing-5); box-sizing: border-box; }
  .toolbar { position: sticky; top: 0; z-index: var(--z-index-raised); display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--spacing-4); max-width: 794px; width: 100%; margin: 0 auto; padding: var(--spacing-3) var(--spacing-5); box-sizing: border-box; background: var(--color-grey-0); border-radius: var(--radius-5); box-shadow: 0 0 0 1px var(--color-grey-30); }
  .tools, .actions { display: flex; flex-wrap: wrap; gap: var(--spacing-3); }
  .tool { min-width: 0; min-height: 0; width: 36px; height: 36px; margin: 0; padding: 0; border: 0; border-radius: 50%; background: var(--color-grey-10); color: var(--color-font-primary); font-size: var(--font-size-small); font-weight: 600; cursor: pointer; }
  .tool-italic { font-style: italic; }
  .tool-underline { text-decoration: underline; }
  .tool:hover { background: var(--color-grey-20); }
  .tool:disabled { opacity: 0.5; cursor: default; }
  .tool:focus-visible { outline: 2px solid var(--color-primary-start); outline-offset: 2px; }
  .paper { max-width: 794px; width: 100%; margin: 0 auto; background: #fff; border-radius: 2px; box-shadow: 0 2px 6px rgba(0, 0, 0, 0.35), 0 8px 24px rgba(0, 0, 0, 0.25); }
  .page { min-height: 480px; padding: 96px 72px; box-sizing: border-box; font-family: 'Calibri', 'Cambria', Georgia, 'Times New Roman', serif; font-size: var(--font-size-small); line-height: 1.65; color: #202020; word-break: break-word; }
  .page :global(.ProseMirror) { outline: none; min-height: 288px; }
  .paper:focus-within { box-shadow: 0 0 0 2px var(--color-primary-start), 0 8px 24px rgba(0, 0, 0, 0.25); }
  .page :global(.ProseMirror:focus-visible) { outline: none; }
  .page :global(h1) { font-size: var(--font-size-h2-mobile); font-weight: 700; margin: 0 0 20px; padding-bottom: var(--spacing-5); border-bottom: 2px solid #e8e8e8; color: #1a1a1a; line-height: 1.25; }
  .page :global(h2) { font-size: var(--font-size-h3-mobile); font-weight: 600; margin: 32px 0 10px; color: #1a1a1a; line-height: 1.3; }
  .page :global(h3) { font-weight: 600; margin: 24px 0 8px; color: #2c2c2c; line-height: 1.35; }
  .page :global(p) { margin: 0 0 10px; }
  .page :global(ul), .page :global(ol) { margin: 0 0 12px; padding-left: 28px; }
  .page :global(.collaboration-carets__caret) { position: relative; margin-left: -1px; margin-right: -1px; border-left: 1px solid #0d0d0d; border-right: 1px solid #0d0d0d; word-break: normal; pointer-events: none; }
  .page :global(.collaboration-carets__label) { position: absolute; top: -1.4em; left: -1px; padding: 0.1rem 0.3rem; border-radius: 3px 3px 3px 0; color: var(--color-font-button); font-size: var(--font-size-xxs); font-weight: 600; line-height: normal; white-space: nowrap; user-select: none; }
  @media (max-width: 600px) { .page { padding: 40px 24px; } }
</style>
