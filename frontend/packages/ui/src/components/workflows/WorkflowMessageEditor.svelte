<!-- Isolated workflow template editor; no chat sync, uploads, or general mention search. -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { Editor } from '@tiptap/core';
  import StarterKit from '@tiptap/starter-kit';
  import Placeholder from '@tiptap/extension-placeholder';
  import { GenericMentionNode } from '../enter_message/extensions/GenericMentionNode';
  import type { Output } from './workflowBuilder';
  import { documentToTemplate, templateToDocument, outputToken, WORKFLOW_OUTPUT_NODE } from './workflowMessageTokens';

  let { value = '', outputs = [], placeholder = '', disabled = false, onChange, onMentionTrigger }: {
    value?: string; outputs?: Output[]; placeholder?: string; disabled?: boolean;
    onChange: (value: string) => void; onMentionTrigger: (visible: boolean) => void;
  } = $props();
  let element: HTMLDivElement | undefined = $state();
  let editor = $state.raw<Editor | null>(null);
  const WorkflowOutputNode = GenericMentionNode.extend({
    name: WORKFLOW_OUTPUT_NODE,
    addKeyboardShortcuts() {
      return { Backspace: ({ editor: instance }) => {
        const { empty, $from: cursor } = instance.state.selection;
        const before = cursor.nodeBefore;
        if (!empty || before?.type.name !== WORKFLOW_OUTPUT_NODE) return false;
        return instance.commands.deleteRange({ from: cursor.pos - before.nodeSize, to: cursor.pos });
      } };
    },
  });

  function mentionAtCursor(instance: Editor): boolean {
    const { $from: cursor, empty } = instance.state.selection;
    return empty && cursor.parent.textBetween(0, cursor.parentOffset, '\n', '\ufffc').endsWith('@');
  }

  export function removeMentionTrigger(): void {
    if (!editor || disabled || !mentionAtCursor(editor)) return;
    const cursor = editor.state.selection.from;
    editor.chain().focus().deleteRange({ from: cursor - 1, to: cursor }).run();
  }

  export function insertReference(output: Output): void {
    if (!editor || disabled) return;
    const cursor = editor.state.selection.from;
    const chain = editor.chain().focus();
    if (mentionAtCursor(editor)) chain.deleteRange({ from: cursor - 1, to: cursor });
    chain.insertContent(outputToken(output)).run();
    onMentionTrigger?.(false);
  }

  onMount(() => {
    if (!element) return;
    const instance = new Editor({
      element,
      extensions: [StarterKit.configure({ bold: false, italic: false, strike: false, underline: false, link: false, code: false, codeBlock: false, blockquote: false, heading: false, bulletList: false, orderedList: false, horizontalRule: false }), WorkflowOutputNode, Placeholder.configure({ placeholder })],
      content: templateToDocument(value, outputs),
      editable: !disabled,
      onUpdate: ({ editor: updated }) => { onChange(documentToTemplate(updated.getJSON())); onMentionTrigger?.(mentionAtCursor(updated)); },
      onSelectionUpdate: ({ editor: updated }) => onMentionTrigger?.(mentionAtCursor(updated)),
      editorProps: {
        attributes: { role: 'textbox', 'aria-multiline': 'true', 'aria-label': placeholder, 'data-testid': 'workflow-message-template' },
        handleKeyDown: (_view, event) => { if (event.key === 'Escape') onMentionTrigger?.(false); return false; },
        handlePaste: (_view, event) => {
          const pasted = event.clipboardData?.getData('text/plain');
          if (!pasted?.includes('{{')) return false;
          instance.commands.insertContent(templateToDocument(pasted, outputs).content ?? []);
          return true;
        },
      },
    });
    editor = instance;
    return () => { instance.destroy(); editor = null; };
  });

  $effect(() => {
    if (!editor) return;
    if (editor.isEditable === disabled) editor.setEditable(!disabled, false);
    if (documentToTemplate(editor.getJSON()) !== value) editor.commands.setContent(templateToDocument(value, outputs), { emitUpdate: false });
  });
</script>

<div class="workflow-message-editor" class:disabled bind:this={element}></div>

<style>
  .workflow-message-editor{min-width:0;border:1px solid var(--color-grey-25);border-radius:.8rem;background:var(--color-grey-0);box-shadow:var(--shadow-sm);text-align:start;color:var(--color-font-primary);font-size:var(--font-size-p)}.workflow-message-editor:focus-within{outline:2px solid var(--color-button-primary);outline-offset:2px}.workflow-message-editor :global(.tiptap){padding:.65rem .8rem;min-height:8rem;outline:none;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.65;font-size:var(--font-size-p);user-select:text}.workflow-message-editor :global(p){margin:0;min-height:1.65em}.workflow-message-editor :global(.generic-mention){display:inline-block;vertical-align:baseline;border-radius:1rem;padding:0 .5rem;margin:0 .1rem;background:var(--color-primary);color:var(--color-font-button);font-size:var(--font-size-p);line-height:1.55;white-space:normal;cursor:default;user-select:all}.workflow-message-editor :global(.ProseMirror-selectednode){outline:2px solid var(--color-button-primary);outline-offset:2px}.workflow-message-editor :global(p.is-editor-empty:first-child::before){content:attr(data-placeholder);float:left;color:var(--color-font-secondary);height:0;pointer-events:none}.disabled{opacity:.65}
</style>
