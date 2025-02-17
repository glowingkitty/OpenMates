<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { Editor } from '@tiptap/core';
    import StarterKit from '@tiptap/starter-kit';
    import * as EmbedNodes from '../components/enter_message/extensions/embeds';
    import { WebPreview } from '../components/enter_message/extensions/WebPreview';
    import { MateNode } from '../components/enter_message/extensions/MateNode';
    import { createEventDispatcher } from 'svelte';

    // Props
    export let content: any; // The message content from Tiptap JSON

    let editorElement: HTMLElement;
    let editor: Editor;
    const dispatch = createEventDispatcher();

    // Logger for debugging
    const logger = {
        debug: (...args: any[]) => console.debug('[ReadOnlyMessage]', ...args),
        info: (...args: any[]) => console.info('[ReadOnlyMessage]', ...args)
    };

    // Handle embed interactions directly from the editor element
    function handleEmbedClick(event: CustomEvent) {
        event.stopPropagation();
        const target = event.target as HTMLElement;
        // Look for any embed container with either data attribute
        const embedContainer = target.closest('[data-embed-id], [data-code-embed], .preview-container');
        if (embedContainer) {
            console.log('[ReadOnlyMessage] Embed container clicked');
            
            // Get the node from the editor
            const pos = editor?.view.posAtDOM(embedContainer, 0);
            const node = pos !== undefined ? editor?.state.doc.nodeAt(pos) : null;
            
            if (node) {
                const elementId = embedContainer.getAttribute('data-embed-id') || 
                                embedContainer.getAttribute('data-code-embed') || 
                                embedContainer.id;
                
                // Get container rect for menu positioning
                const rect = embedContainer.getBoundingClientRect();
                
                dispatch('message-embed-click', {
                    view: editor?.view,
                    node,
                    dom: embedContainer,
                    elementId,
                    rect // Pass the rect for proper menu positioning
                });
            }
        }
    }

    // Handle mate mentions
    function handleMateClick(event: CustomEvent) {
        event.stopPropagation();
        dispatch('message-mate-click', event.detail);
    }

    onMount(() => {
        if (!editorElement) return;

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

        // Listen for clicks on the editor
        editor.view.dom.addEventListener('click', handleEmbedClick as EventListener);
    });

    onDestroy(() => {
        if (editor) {
            editor.view.dom.removeEventListener('click', handleEmbedClick as EventListener);
            editor.destroy();
        }
    });
</script>

<div class="read-only-message">
    <div bind:this={editorElement} class="editor-content"></div>
</div>

<style>
    .read-only-message {
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