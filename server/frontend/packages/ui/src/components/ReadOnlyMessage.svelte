<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { Editor } from '@tiptap/core';
    import StarterKit from '@tiptap/starter-kit';
    import * as EmbedNodes from '../components/enter_message/extensions/embeds';
    import { WebPreview } from '../components/enter_message/extensions/WebPreview';
    import { MateNode } from '../components/enter_message/extensions/MateNode';

    // Props
    export let content: any; // The message content from Tiptap JSON

    let editorElement: HTMLElement;
    let editor: Editor;

    // Logger for debugging
    const logger = {
        debug: (...args: any[]) => console.debug('[ReadOnlyMessage]', ...args),
        info: (...args: any[]) => console.info('[ReadOnlyMessage]', ...args)
    };

    onMount(() => {
        if (!editorElement) return;

        logger.debug('Initializing read-only editor with content:', content);

        editor = new Editor({
            element: editorElement,
            extensions: [
                StarterKit.configure({
                    hardBreak: {
                        keepMarks: true,
                        HTMLAttributes: {}
                    },
                }),
                ...Object.values(EmbedNodes),
                WebPreview,
                MateNode,
            ],
            content: content,
            editable: false, // Make it read-only
            injectCSS: false, // Don't inject default styles
        });

        // Add event listener for embed clicks
        document.addEventListener('embedclick', handleEmbedClick as EventListener);
        document.addEventListener('mateclick', handleMateClick as EventListener);
    });

    onDestroy(() => {
        if (editor) {
            editor.destroy();
        }
        document.removeEventListener('embedclick', handleEmbedClick as EventListener);
        document.removeEventListener('mateclick', handleMateClick as EventListener);
    });

    // Handle embed interactions
    function handleEmbedClick(event: CustomEvent) {
        const { id } = event.detail;
        logger.debug('Embed clicked:', id);
        // Dispatch event up to parent components
        editorElement.dispatchEvent(new CustomEvent('embedclick', {
            detail: event.detail,
            bubbles: true
        }));
    }

    // Handle mate mentions
    function handleMateClick(event: CustomEvent) {
        const { id } = event.detail;
        logger.debug('Mate clicked:', id);
        // Dispatch event up to parent components
        editorElement.dispatchEvent(new CustomEvent('mateclick', {
            detail: event.detail,
            bubbles: true
        }));
    }
</script>

<div class="read-only-message">
    <div bind:this={editorElement} class="editor-content"></div>
</div>

<style>
    .read-only-message {
        width: 100%;
    }

    .editor-content {
        width: 100%;
    }

    /* Style overrides for read-only mode */
    :global(.read-only-message .ProseMirror) {
        outline: none;
        cursor: default;
        padding: 0;
    }

    :global(.read-only-message .ProseMirror p) {
        margin: 0;
        line-height: 1.5;
    }

    /* Preserve embed styles */
    :global(.read-only-message .preview-container) {
        pointer-events: all;
        cursor: pointer;
    }

    /* Ensure mate mentions are still clickable */
    :global(.read-only-message .mate-mention) {
        cursor: pointer;
        user-select: none;
    }
</style> 