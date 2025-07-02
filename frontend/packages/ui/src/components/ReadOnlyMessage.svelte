<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { Editor } from '@tiptap/core';
    import StarterKit from '@tiptap/starter-kit';
    import { text } from '@repo/ui';
    import * as EmbedNodes from '../components/enter_message/extensions/embeds';
    import { MateNode } from '../components/enter_message/extensions/MateNode';
    import { MarkdownExtensions } from '../components/enter_message/extensions/MarkdownExtensions';
    import { parseMarkdownToTiptap, isMarkdownContent } from '../components/enter_message/utils/markdownParser';
    import { createEventDispatcher } from 'svelte';
    import { preprocessTiptapJsonForEmbeds } from '../components/enter_message/utils/tiptapContentProcessor';

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
            console.debug('[ReadOnlyMessage] Embed container clicked');
            
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

    function processContent(inputContent: any) {
        if (!inputContent) return null;
        
        try {
            // Check if the content is a plain string (markdown text)
            if (typeof inputContent === 'string') {
                logger.debug('Processing markdown text content:', inputContent.substring(0, 100) + '...');
                
                // Handle special translation keys
                if (inputContent === 'chat.an_error_occured.text') {
                    const translatedText = $text('chat.an_error_occured.text');
                    return parseMarkdownToTiptap(translatedText);
                }
                
                // Parse markdown text to TipTap JSON
                return parseMarkdownToTiptap(inputContent);
            }
            
            // Check if it's already TipTap JSON but contains markdown-like text
            if (inputContent && typeof inputContent === 'object' && inputContent.type === 'doc') {
                // Deep copy to avoid modifying the original prop
                const newContent = JSON.parse(JSON.stringify(inputContent));
                
                // Check if the first paragraph contains markdown-like text
                const firstParagraph = newContent?.content?.[0];
                if (firstParagraph?.type === 'paragraph' && firstParagraph?.content?.[0]?.type === 'text') {
                    const textContent = firstParagraph.content[0].text;
                    
                    if (textContent === 'chat.an_error_occured.text') {
                        // Replace the key with the translated text
                        firstParagraph.content[0].text = $text('chat.an_error_occured.text');
                    } else if (isMarkdownContent(textContent)) {
                        // If the text content looks like markdown, parse it
                        logger.debug('Converting TipTap JSON with markdown text to proper markdown structure');
                        return parseMarkdownToTiptap(textContent);
                    }
                }
                
                return preprocessTiptapJsonForEmbeds(newContent);
            }
            
            // If it's some other format, try to convert it to string and parse as markdown
            const stringContent = String(inputContent);
            if (isMarkdownContent(stringContent)) {
                logger.debug('Converting unknown content type to markdown');
                return parseMarkdownToTiptap(stringContent);
            }
            
            // Fallback: try to process as TipTap JSON
            return preprocessTiptapJsonForEmbeds(inputContent);
            
        } catch (e) {
            logger.debug("Error processing content, attempting markdown fallback", e);
            
            // Final fallback: try to parse as markdown text
            try {
                const stringContent = typeof inputContent === 'string' ? inputContent : String(inputContent);
                return parseMarkdownToTiptap(stringContent);
            } catch (markdownError) {
                logger.debug("Markdown parsing also failed, returning simple paragraph", markdownError);
                
                // Ultimate fallback: return as simple text paragraph
                const fallbackText = typeof inputContent === 'string' ? inputContent : 'Error loading content';
                return {
                    type: 'doc',
                    content: [
                        {
                            type: 'paragraph',
                            content: [{ type: 'text', text: fallbackText }]
                        }
                    ]
                };
            }
        }
    }

    onMount(() => {
        if (!editorElement) return;

        const processedContent = processContent(content);
        logger.debug('Component mounted. Initializing Tiptap editor with content:', JSON.parse(JSON.stringify(processedContent)));
        
        editor = new Editor({
            element: editorElement,
            extensions: [
                StarterKit.configure({
                    hardBreak: {
                        keepMarks: true,
                        HTMLAttributes: {}
                    },
                    // Disable strike from StarterKit since we have our own
                    strike: false,
                }),
                ...Object.values(EmbedNodes),
                MateNode,
                ...MarkdownExtensions,
            ],
            content: processedContent,
            editable: false, // Make it read-only
            injectCSS: false, // Don't inject default styles
        });

        // Listen for clicks on the editor
        editor.view.dom.addEventListener('click', handleEmbedClick as EventListener);
    });

    // Reactive statement to update Tiptap editor when 'content' prop changes
    $: if (editor && content) {
        const newProcessedContent = processContent(content);
        
        if (JSON.stringify(editor.getJSON()) !== JSON.stringify(newProcessedContent)) {
            logger.debug('Content prop changed, updating Tiptap editor. New content:', JSON.parse(JSON.stringify(newProcessedContent)));
            editor.commands.setContent(newProcessedContent, false);
        } else {
            logger.debug('Content prop changed, but editor content is already up-to-date.');
        }
    } else if (editor && !content) {
        // Handle case where content becomes null/undefined after editor initialization
        logger.debug('Content prop became null/undefined, clearing Tiptap editor.');
        editor.commands.clearContent(false);
    }


    onDestroy(() => {
        if (editor) {
            logger.debug('Component destroying. Cleaning up Tiptap editor.');
            editor.view.dom.removeEventListener('click', handleEmbedClick as EventListener);
            editor.destroy();
        }
    });
</script>

<div class="read-only-message">
    <div bind:this={editorElement} class="editor-content"></div>
</div>

<style>
    @import '../styles/markdown.css';

    .read-only-message {
        width: 100%;
    }

    /* Style overrides for read-only mode */
    :global(.read-only-message .ProseMirror) {
        outline: none;
        cursor: default;
        padding: 0;
        user-select: text; /* Allow text selection */
    }

    :global(.read-only-message .ProseMirror p) {
        margin: 0;
        line-height: 1.5;
    }

    /* Hide trailing breaks that cause unwanted spacing in lists */
    :global(.read-only-message .markdown-list-item .markdown-paragraph .ProseMirror-trailingBreak) {
        display: none;
    }

    /* Hide trailing breaks in paragraphs that are followed by nested elements */
    :global(.read-only-message .markdown-paragraph:has(+ .markdown-bullet-list) .ProseMirror-trailingBreak),
    :global(.read-only-message .markdown-paragraph:has(+ .markdown-ordered-list) .ProseMirror-trailingBreak),
    :global(.read-only-message .markdown-paragraph:has(+ .markdown-blockquote) .ProseMirror-trailingBreak),
    :global(.read-only-message .markdown-paragraph:has(+ .markdown-code-block) .ProseMirror-trailingBreak),
    :global(.read-only-message .markdown-paragraph:has(+ .markdown-table) .ProseMirror-trailingBreak) {
        display: none;
    }

    /* Alternative approach for browsers that don't support :has() */
    :global(.read-only-message .markdown-list-item > .markdown-paragraph:not(:last-child) .ProseMirror-trailingBreak) {
        display: none;
    }

    /* Custom smaller heading styles for ReadOnlyMessage */
    :global(.read-only-message .markdown-h1) {
        font-size: 1.4em;
        font-weight: 600;
        margin: 1em 0 0.5em 0;
        border-bottom: 1px solid var(--color-border-secondary, #e1e5e9);
        padding-bottom: 0.2em;
    }

    :global(.read-only-message .markdown-h2) {
        font-size: 1.25em;
        font-weight: 600;
        margin: 0.8em 0 0.4em 0;
        border-bottom: 1px solid var(--color-border-secondary, #e1e5e9);
        padding-bottom: 0.15em;
    }

    :global(.read-only-message .markdown-h3) {
        font-size: 1.1em;
        font-weight: 600;
        margin: 0.7em 0 0.3em 0;
    }

    :global(.read-only-message .markdown-h4) {
        font-size: 1em;
        font-weight: 600;
        margin: 0.6em 0 0.3em 0;
    }

    :global(.read-only-message .markdown-h5) {
        font-size: 0.9em;
        font-weight: 600;
        margin: 0.5em 0 0.2em 0;
    }

    :global(.read-only-message .markdown-h6) {
        font-size: 0.85em;
        font-weight: 600;
        margin: 0.5em 0 0.2em 0;
        color: var(--color-font-secondary, #656d76);
    }

    /* First heading should have no top margin */
    :global(.read-only-message .markdown-heading:first-child) {
        margin-top: 0;
    }

    /* Preserve embed styles */
    :global(.read-only-message .preview-container) {
        pointer-events: all;
        cursor: pointer;
    }

    /* Ensure mate mentions are still clickable */
    :global(.read-only-message .mate-mention) {
        cursor: pointer;
    }

    /* Dark mode support for custom headings */
    @media (prefers-color-scheme: dark) {
        :global(.read-only-message .markdown-h1),
        :global(.read-only-message .markdown-h2) {
            border-bottom-color: var(--color-border-secondary-dark, #30363d);
        }
        
        :global(.read-only-message .markdown-h6) {
            color: var(--color-font-secondary-dark, #8b949e);
        }
    }

    /* Remove artificial margins - whitespace should be preserved naturally */
</style>
