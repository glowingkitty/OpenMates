<!-- frontend/packages/ui/src/components/settings/MemoryBodyEditor.svelte
     Memory body editor. Spec: app-memories.references.embeds.
     The chat composer's editor model: plain text plus inline embed previews.
     Paste an embed copied from a chat to reference it; the body stays Markdown
     (embeds as the same fenced blocks messages use). Nothing here leaves the device. -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { Editor } from '@tiptap/core';
  import StarterKit from '@tiptap/starter-kit';
  import Placeholder from '@tiptap/extension-placeholder';
  import { Embed } from '../enter_message/extensions/Embed';
  import { parseEmbedClipboardData } from '../../message_parsing/serializers';
  import { MAX_MEMORY_REFERENCES } from '../../utils/ruleDocuments';
  import { bodyToDocument, documentToBody, embedIdsInBody, type BodyDocument } from '../../utils/memoryBodyDocument';

  interface Props {
    value: string;
    ariaLabel: string;
    placeholder?: string;
    disabled?: boolean;
    dataTestid?: string;
    onChange: (value: string) => void;
    /** Called when a paste would exceed the reference limit. */
    onLimit: () => void;
  }
  let { value, ariaLabel, placeholder = '', disabled = false, dataTestid = 'rule-body', onChange, onLimit }: Props = $props();

  let element: HTMLDivElement | undefined = $state();
  let editor = $state.raw<Editor | null>(null);

  function clipboardEmbeds(event: ClipboardEvent): unknown[] {
    let json = event.clipboardData?.getData('application/x-openmates-embed') || '';
    if (!json) {
      const html = event.clipboardData?.getData('text/html') || '';
      const meta = html.match(/<meta\s[^>]*name="x-openmates-embed"[^>]*content="([^"]*)"[^>]*>/i)
        ?? html.match(/<meta\s[^>]*content="([^"]*)"[^>]*name="x-openmates-embed"[^>]*>/i);
      if (meta) {
        try { json = decodeURIComponent(escape(atob(meta[1]))); } catch { json = ''; }
      }
    }
    if (!json) return [];
    try {
      const parsed: unknown = JSON.parse(json);
      return Array.isArray(parsed) ? parsed : [parsed];
    } catch { return []; }
  }

  onMount(() => {
    if (!element) return;
    const instance = new Editor({
      element,
      extensions: [
        StarterKit.configure({
          bold: false, italic: false, strike: false, code: false, codeBlock: false, blockquote: false, heading: false,
          bulletList: false, orderedList: false, listItem: false, horizontalRule: false, link: false,
        }),
        Embed,
        Placeholder.configure({ placeholder }),
      ],
      content: bodyToDocument(value),
      editable: !disabled,
      onUpdate: ({ editor: updated }) => onChange(documentToBody(updated.getJSON() as BodyDocument)),
      editorProps: {
        attributes: { role: 'textbox', 'aria-multiline': 'true', 'aria-label': ariaLabel, 'data-testid': dataTestid },
        handlePaste: (_view, event) => {
          const embeds = clipboardEmbeds(event);
          if (!embeds.length) return false;
          event.preventDefault();
          const present = new Set(embedIdsInBody(documentToBody(instance.getJSON() as BodyDocument)));
          for (const data of embeds) {
            // Reference-only: removing the block from a Memory must never delete the embed itself.
            const attrs = { ...parseEmbedClipboardData(data as Parameters<typeof parseEmbedClipboardData>[0]), referenceOnly: true };
            if (present.has(attrs.id)) continue;
            if (present.size >= MAX_MEMORY_REFERENCES) { onLimit(); break; }
            present.add(attrs.id);
            instance.commands.insertContent({ type: 'embed', attrs });
          }
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
    if (documentToBody(editor.getJSON() as BodyDocument) !== value) {
      editor.commands.setContent(bodyToDocument(value), { emitUpdate: false });
    }
  });
</script>

<div class="memory-body-editor" class:disabled bind:this={element}></div>

<style>
  .memory-body-editor { min-width: 0; border: 1px solid var(--color-grey-25); border-radius: 0.8rem; background: var(--color-grey-10); text-align: start; }
  .memory-body-editor :global(.tiptap) { min-height: 9rem; padding: var(--spacing-5) var(--spacing-6); outline: 0; caret-color: var(--color-font-primary); overflow-wrap: anywhere; }
  .memory-body-editor :global(.tiptap p) { margin: 0; min-height: 1.4em; }
  .memory-body-editor :global(.tiptap p.is-editor-empty:first-child::before) { content: attr(data-placeholder); float: inline-start; height: 0; color: var(--color-font-tertiary); pointer-events: none; }
  .memory-body-editor:focus-within { box-shadow: 0 0 0 0.125rem var(--color-primary-start); }
  .memory-body-editor.disabled { opacity: 0.6; }
</style>
