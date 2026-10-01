<!-- Isolated workflow template editor; no chat sync, uploads, or general mention search. -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { Editor, Extension } from '@tiptap/core';
  import { Plugin, PluginKey } from 'prosemirror-state';
  import { Decoration, DecorationSet } from 'prosemirror-view';
  import StarterKit from '@tiptap/starter-kit';
  import Placeholder from '@tiptap/extension-placeholder';
  import { GenericMentionNode } from '../enter_message/extensions/GenericMentionNode';
  import { resolveIconName } from '../../utils/iconNameResolver';
  import type { Output } from './workflowBuilder';
  import { documentToTemplate, templateToDocument, outputToken, WORKFLOW_OUTPUT_NODE } from './workflowMessageTokens';
  import { workflowMentionQuery } from './workflowMentionQuery';

  let { value = '', outputs = [], placeholder = '', id = undefined, ariaLabel = placeholder, dataTestid = 'workflow-message-template', compact = false, disabled = false, onChange, onMentionTrigger }: {
    value?: string; outputs?: Output[]; placeholder?: string; id?: string; ariaLabel?: string; dataTestid?: string; compact?: boolean; disabled?: boolean;
    onChange: (value: string) => void; onMentionTrigger: (visible: boolean, query: string) => void;
  } = $props();
  let element: HTMLDivElement | undefined = $state();
  let editor = $state.raw<Editor | null>(null);
  const WorkflowOutputNode = GenericMentionNode.extend({
    name: WORKFLOW_OUTPUT_NODE,
    addAttributes() {
      return { ...this.parent?.(), appId: { default: null }, sourceLabel: { default: '' } };
    },
    renderHTML(props) {
      const rendered = this.parent?.(props);
      if (!Array.isArray(rendered)) return ['span', {}, `@${props.HTMLAttributes.displayName}`];
      const appId = String(props.HTMLAttributes.appId ?? '');
      const attrs = { ...rendered[1], title: props.HTMLAttributes.sourceLabel };
      if (!/^[a-z0-9_-]+$/.test(appId)) return ['span', attrs, `@${props.HTMLAttributes.displayName}`];
      return ['span', attrs,
        ['span', { class: 'workflow-mention-icon', 'aria-hidden': 'true', style: `--workflow-mention-icon:var(--icon-url-${resolveIconName(appId)},var(--icon-url-app))` }],
        ['span', { class: 'generic-mention-label' }, `@${props.HTMLAttributes.displayName}`],
      ];
    },
    addKeyboardShortcuts() {
      return { Backspace: ({ editor: instance }) => {
        const { empty, $from: cursor } = instance.state.selection;
        const before = cursor.nodeBefore;
        if (!empty || before?.type.name !== WORKFLOW_OUTPUT_NODE) return false;
        return instance.commands.deleteRange({ from: cursor.pos - before.nodeSize, to: cursor.pos });
      } };
    },
  });

  function mentionAtCursor(instance: Editor) {
    const { $from: cursor, empty } = instance.state.selection;
    return empty ? workflowMentionQuery(cursor.parent.textBetween(0, cursor.parentOffset, '\n', '\ufffc')) : null;
  }

  function notifyMention(instance: Editor): void {
    const mention = mentionAtCursor(instance);
    onMentionTrigger(!!mention, mention?.query ?? '');
  }

  export function removeMentionTrigger(): void {
    if (!editor || disabled) return;
    const mention = mentionAtCursor(editor);
    if (!mention) return;
    const cursor = editor.state.selection.from;
    editor.chain().focus().deleteRange({ from: cursor - mention.length, to: cursor }).run();
  }

  export function insertReference(output: Output): void {
    if (!editor || disabled) return;
    const cursor = editor.state.selection.from;
    const mention = mentionAtCursor(editor);
    const chain = editor.chain().focus();
    if (mention) chain.deleteRange({ from: cursor - mention.length, to: cursor });
    chain.insertContent(outputToken(output)).run();
    onMentionTrigger(false, '');
  }

  onMount(() => {
    if (!element) return;
    const instance = new Editor({
      element,
      extensions: [StarterKit.configure({ bold: false, italic: false, strike: false, underline: false, link: false, code: false, codeBlock: false, blockquote: false, heading: false, bulletList: false, orderedList: false, horizontalRule: false }), WorkflowOutputNode, Placeholder.configure({ placeholder }), Extension.create({
        name: 'workflowMentionQueryHighlight',
        addProseMirrorPlugins() {
          return [new Plugin({
            key: new PluginKey('workflowMentionQueryHighlight'),
            props: { decorations(state) {
              const { $from: cursor, empty } = state.selection;
              const mention = empty ? workflowMentionQuery(cursor.parent.textBetween(0, cursor.parentOffset, '\n', '\ufffc')) : null;
              return mention ? DecorationSet.create(state.doc, [Decoration.inline(cursor.pos - mention.length, cursor.pos, { class: 'workflow-mention-query' })]) : DecorationSet.empty;
            } },
          })];
        },
      })],
      content: templateToDocument(value, outputs),
      editable: !disabled,
      onUpdate: ({ editor: updated }) => { onChange(documentToTemplate(updated.getJSON())); notifyMention(updated); },
      onSelectionUpdate: ({ editor: updated }) => notifyMention(updated),
      editorProps: {
        attributes: { ...(id ? { id } : {}), role: 'textbox', 'aria-multiline': compact ? 'false' : 'true', 'aria-label': ariaLabel, 'data-testid': dataTestid },
        handleKeyDown: (_view, event) => {
          if (event.key === 'Escape') onMentionTrigger(false, '');
          return compact && event.key === 'Enter';
        },
        handlePaste: (_view, event) => {
          const pasted = event.clipboardData?.getData('text/plain');
          if (!pasted || (!compact && !pasted.includes('{{'))) return false;
          const inserted = compact ? pasted.replace(/\s*\n+\s*/g, ' ') : pasted;
          instance.commands.insertContent(templateToDocument(inserted, outputs).content ?? []);
          return true;
        },
      },
    });
    editor = instance;
    return () => { instance.destroy(); editor = null; };
  });

  $effect(() => {
    // Schemas can arrive after the saved template is mounted. Reading outputs
    // outside the value comparison keeps the display metadata reactive.
    const declaredOutputs = new Map(outputs.map(output => [output.reference, output]));
    if (!editor) return;
    if (editor.isEditable === disabled) editor.setEditable(!disabled, false);
    if (documentToTemplate(editor.getJSON()) !== value) {
      editor.commands.setContent(templateToDocument(value, outputs), { emitUpdate: false });
    }
    const transaction = editor.state.tr;
    editor.state.doc.descendants((node, position) => {
      if (node.type.name !== WORKFLOW_OUTPUT_NODE) return;
      const output = declaredOutputs.get(node.attrs.mentionId);
      if (!output) return;
      const displayAttrs = outputToken(output).attrs ?? {};
      const attrs = { ...node.attrs, ...displayAttrs, mentionSyntax: node.attrs.mentionSyntax };
      if (Object.keys(displayAttrs).some(key => key !== 'mentionSyntax' && node.attrs[key] !== attrs[key])) {
        transaction.setNodeMarkup(position, undefined, attrs);
      }
    });
    if (transaction.docChanged) {
      // Labels/icons are presentation only: keep the draft, caret and undo stack.
      transaction.setMeta('preventUpdate', true).setMeta('addToHistory', false);
      editor.view.dispatch(transaction);
    }
  });
</script>

<div class="workflow-message-editor" class:compact class:disabled bind:this={element}></div>

<style>
  /* The chat composer hides the native ProseMirror caret globally when unfocused. */
  .workflow-message-editor :global(.tiptap){caret-color:var(--color-font-primary)}
  .workflow-message-editor :global(.workflow-mention-query){color:var(--color-primary-start);font-weight:500}
  .workflow-message-editor :global(.generic-mention){align-items:center;gap:.25rem;text-align:left}
  .workflow-message-editor :global(.generic-mention-label){min-width:0;overflow-wrap:anywhere;text-align:left}
  .workflow-message-editor :global(.workflow-mention-icon){display:inline-block;flex:0 0 auto;width:.875rem;height:.875rem;background:currentColor;-webkit-mask:var(--workflow-mention-icon) center/contain no-repeat;mask:var(--workflow-mention-icon) center/contain no-repeat}
  .workflow-message-editor{min-width:0;border:1px solid var(--color-grey-25);border-radius:.8rem;background:var(--workflow-input-surface,var(--color-grey-10));box-shadow:var(--shadow-sm);text-align:start;color:var(--color-font-primary);font-size:var(--font-size-p)}.workflow-message-editor:focus-within{outline:2px solid var(--color-button-primary);outline-offset:2px}.workflow-message-editor :global(.tiptap){padding:.65rem .8rem;min-height:8rem;outline:none;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.65;font-size:var(--font-size-p);user-select:text}.workflow-message-editor :global(p){margin:0;min-height:1.65em}.workflow-message-editor :global(.generic-mention){display:inline-flex;vertical-align:baseline;max-width:calc(100% - .2rem);box-sizing:border-box;border-radius:1rem;padding:0 .5rem;margin:0 .1rem;background:linear-gradient(135deg,var(--mention-color-start,var(--color-primary-start)),var(--mention-color-end,var(--color-primary-end)));color:var(--color-font-button)!important;-webkit-text-fill-color:var(--color-font-button)!important;opacity:1!important;font-size:var(--font-size-p);line-height:1.55;white-space:normal;cursor:default;user-select:all}.workflow-message-editor :global(.ProseMirror-selectednode){outline:2px solid var(--color-button-primary);outline-offset:2px}.workflow-message-editor :global(p.is-editor-empty:first-child::before){content:attr(data-placeholder);float:left;color:var(--color-font-secondary);height:0;pointer-events:none;text-align:start;position:static;width:100%}.disabled{opacity:.65}
  .workflow-message-editor.compact{box-sizing:border-box;width:100%;border:0;border-radius:1.5rem;background:var(--workflow-input-surface,var(--color-grey-10));box-shadow:0 .25rem .25rem rgba(0,0,0,.1);overflow-x:auto}
  .workflow-message-editor.compact:focus-within{outline:0;box-shadow:0 .25rem .5rem rgba(0,0,0,.15),0 0 0 .125rem var(--color-primary-start)}
  .workflow-message-editor.compact :global(.tiptap){box-sizing:border-box;width:max-content;min-width:100%;min-height:0;padding:1.0625rem 1.4375rem;white-space:nowrap;overflow-wrap:normal;line-height:1.25;font-weight:500}
  .workflow-message-editor.compact :global(p){display:inline;min-height:0}
  .workflow-message-editor.compact :global(p + p)::before{content:' '}
  .workflow-message-editor.compact :global(.generic-mention){line-height:1.25;white-space:nowrap}
</style>
