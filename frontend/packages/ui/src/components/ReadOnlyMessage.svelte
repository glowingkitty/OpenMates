<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { Editor } from '@tiptap/core';
    import StarterKit from '@tiptap/starter-kit';
    import { text } from '@repo/ui';
    import { Embed } from '../components/enter_message/extensions/Embed';
    import { MateNode } from '../components/enter_message/extensions/MateNode';
    import { MarkdownExtensions } from '../components/enter_message/extensions/MarkdownExtensions';
    import { parseMarkdownToTiptap, isMarkdownContent } from '../components/enter_message/utils/markdownParser';
    import { parse_message } from '../message_parsing/parse_message';
    import { createEventDispatcher } from 'svelte';
    import { contentCache } from '../utils/contentCache';
    import { locale } from 'svelte-i18n';

    // Props using Svelte 5 runes mode
    let { content, isStreaming = false }: { content: any; isStreaming?: boolean } = $props(); // The message content from Tiptap JSON

    let editorElement: HTMLElement;
    let editor: Editor | null = null;
    const dispatch = createEventDispatcher();
    

    // Performance optimization: Lazy initialization with Intersection Observer
    // Only create the TipTap editor when the message becomes visible in the viewport
    let isVisible = $state(false);
    let editorCreated = $state(false);

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

    /**
     * Handle right-click (context menu) on embeds
     * Dispatches the same event as handleEmbedClick to show the context menu
     */
    function handleEmbedContextMenu(event: MouseEvent) {
        const target = event.target as HTMLElement;
        // Look for any embed container with either data attribute
        const embedContainer = target.closest('[data-embed-id], [data-code-embed], .preview-container');
        if (embedContainer) {
            // Prevent default browser context menu
            event.preventDefault();
            event.stopPropagation();
            
            logger.debug('[ReadOnlyMessage] Embed container right-clicked');
            
            // Get the node from the editor
            const pos = editor?.view.posAtDOM(embedContainer, 0);
            const node = pos !== undefined ? editor?.state.doc.nodeAt(pos) : null;
            
            if (node) {
                const elementId = embedContainer.getAttribute('data-embed-id') || 
                                embedContainer.getAttribute('data-code-embed') || 
                                embedContainer.id;
                
                // Get container rect for menu positioning
                const rect = embedContainer.getBoundingClientRect();
                
                // Dispatch the same event as left-click to show the context menu
                // Pass the actual click coordinates for proper menu positioning
                dispatch('message-embed-click', {
                    view: editor?.view,
                    node,
                    dom: embedContainer,
                    elementId,
                    rect, // Pass the rect for embed info
                    x: event.clientX, // Actual click X coordinate
                    y: event.clientY // Actual click Y coordinate
                });
            }
        }
    }

    // Touch event handlers for long-press detection on embeds (mobile support)
    // Constants for touch handling
    const LONG_PRESS_DURATION = 500; // milliseconds
    const TOUCH_MOVE_THRESHOLD = 10; // pixels
    
    let touchTimer: ReturnType<typeof setTimeout> | null = null;
    let touchStartX = 0;
    let touchStartY = 0;
    let touchTarget: HTMLElement | null = null;

    /**
     * Handle touch start for long-press detection on embeds
     * Starts a timer that will show the context menu if the touch is held long enough
     */
    function handleTouchStart(event: TouchEvent) {
        // Only handle single touch
        if (event.touches.length !== 1) {
            clearTouchTimer();
            return;
        }

        const target = event.target as HTMLElement;
        // Check if touch is on an embed container
        const embedContainer = target.closest('[data-embed-id], [data-code-embed], .preview-container');
        if (!embedContainer) {
            return; // Not touching an embed, ignore
        }

        const touch = event.touches[0];
        touchStartX = touch.clientX;
        touchStartY = touch.clientY;
        touchTarget = embedContainer as HTMLElement;

        // Start long-press timer
        touchTimer = setTimeout(() => {
            if (touchTarget && editor) {
                logger.debug('[ReadOnlyMessage] Embed container long-pressed');
                
                // Get the node from the editor
                const pos = editor.view.posAtDOM(touchTarget, 0);
                const node = pos !== undefined ? editor.state.doc.nodeAt(pos) : null;
                
                if (node) {
                    const elementId = touchTarget.getAttribute('data-embed-id') || 
                                    touchTarget.getAttribute('data-code-embed') || 
                                    touchTarget.id;
                    
                    // Get container rect for menu positioning
                    const rect = touchTarget.getBoundingClientRect();
                    
                    // Dispatch the same event as click to show the context menu
                    // Pass the actual touch coordinates for proper menu positioning
                    dispatch('message-embed-click', {
                        view: editor.view,
                        node,
                        dom: touchTarget,
                        elementId,
                        rect, // Pass the rect for embed info
                        x: touchStartX, // Actual touch X coordinate
                        y: touchStartY // Actual touch Y coordinate
                    });
                    
                    // Vibrate to provide haptic feedback (if supported)
                    if (navigator.vibrate) {
                        navigator.vibrate(50);
                    }
                }
            }
        }, LONG_PRESS_DURATION);
    }

    /**
     * Handle touch move - cancel long-press if finger moves too much
     */
    function handleTouchMove(event: TouchEvent) {
        if (!touchTimer || event.touches.length !== 1) {
            return;
        }

        const touch = event.touches[0];
        const deltaX = Math.abs(touch.clientX - touchStartX);
        const deltaY = Math.abs(touch.clientY - touchStartY);

        // If finger moved too much, cancel the long-press
        if (deltaX > TOUCH_MOVE_THRESHOLD || deltaY > TOUCH_MOVE_THRESHOLD) {
            clearTouchTimer();
        }
    }

    /**
     * Handle touch end - cancel long-press timer
     */
    function handleTouchEnd(event: TouchEvent) {
        clearTouchTimer();
    }

    /**
     * Clear the touch timer
     */
    function clearTouchTimer() {
        if (touchTimer) {
            clearTimeout(touchTimer);
            touchTimer = null;
        }
        touchTarget = null;
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
                    return parse_message(translatedText, 'read', { unifiedParsingEnabled: true });
                }

                // Performance optimization: Check cache before parsing
                // Include locale in cache key to invalidate cache on language change
                const currentLocale = $locale || 'en';
                const cacheKey = `${currentLocale}:${inputContent}`;
                const cached = contentCache.get(cacheKey);
                if (cached) {
                    logger.debug('Using cached content for markdown parsing');
                    return cached;
                }

                // Parse markdown text to TipTap JSON with unified parsing (includes embed parsing)
                const parsed = parse_message(inputContent, 'read', { unifiedParsingEnabled: true });
                contentCache.set(cacheKey, parsed);
                return parsed;
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
                        // If the text content looks like markdown, parse it with unified parsing
                        logger.debug('Converting TipTap JSON with markdown text to proper markdown structure');
                        return parse_message(textContent, 'read', { unifiedParsingEnabled: true });
                    }
                }
                
                // CRITICAL: When locale changes, TipTap JSON content might have old translations embedded
                // We can't re-translate it here because we don't have the original translation keys
                // Instead, we rely on ChatHistory to re-process messages from original_message when locale changes
                // Content is already processed by ChatHistory, don't double-process
                // NOTE: For locale changes, ChatHistory should provide new content with updated translations
                return newContent;
            }
            
            // If it's some other format, try to convert it to string and parse as markdown
            const stringContent = String(inputContent);
            if (isMarkdownContent(stringContent)) {
                logger.debug('Converting unknown content type to markdown');
                return parse_message(stringContent, 'read', { unifiedParsingEnabled: true });
            }
            
            // Fallback: return content as-is (should already be processed)
            return inputContent;
            
        } catch (e) {
            logger.debug("Error processing content, attempting markdown fallback", e);
            
            // Final fallback: try to parse as markdown text
            try {
                const stringContent = typeof inputContent === 'string' ? inputContent : String(inputContent);
                return parse_message(stringContent, 'read', { unifiedParsingEnabled: true });
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

    /**
     * Create the TipTap editor instance
     * Performance optimization: This is called lazily when the message becomes visible
     */
    function createEditor() {
        if (editorCreated || !editorElement) return;

        const processedContent = processContent(content);
        logger.debug('Creating Tiptap editor for visible message');
        
        // Check for duplicates in MarkdownExtensions
        const markdownExtNames = MarkdownExtensions.map(e => e.name);
        const duplicatesInMarkdown = markdownExtNames.filter((name, index) => markdownExtNames.indexOf(name) !== index);
        if (duplicatesInMarkdown.length > 0) {
            logger.debug('⚠️  DUPLICATES FOUND IN MarkdownExtensions:', duplicatesInMarkdown);
        }
        
        // Create extensions array
        // Important: StarterKit is a composite extension that includes many sub-extensions
        // We must disable any StarterKit extensions that we're providing custom versions of
        // NOTE: StarterKit does NOT include link, underline, highlight, or table by default
        // Those are provided through MarkdownExtensions
        const extensionsBeforeDedup = [
            StarterKit.configure({
                hardBreak: {
                    keepMarks: true,
                    HTMLAttributes: {}
                },
                // Disable extensions we provide through MarkdownExtensions to avoid duplicates
                strike: false, // Using MarkdownStrike instead
            }),
            Embed,
            MateNode,
            ...MarkdownExtensions, // Spread the array of markdown extensions
        ];
        
        // Comprehensive deduplication: Remove any extension with a duplicate name
        // Keep only the FIRST occurrence of each extension name
        const seenNames = new Set<string>();
        const extensions = extensionsBeforeDedup.filter((ext, index) => {
            const name = ext.name;
            if (seenNames.has(name)) {
                logger.debug(`⚠️  Removing duplicate extension at index ${index}: "${name}"`);
                return false; // Filter out duplicate
            }
            seenNames.add(name);
            return true; // Keep first occurrence
        });
    
        editor = new Editor({
            element: editorElement,
            extensions: extensions,
            content: processedContent,
            editable: false, // Make it read-only
            injectCSS: false, // Don't inject default styles
        });
        
        // Listen for right-clicks on the editor (for embed context menu)
        // Left clicks are handled by UnifiedEmbedPreview components directly
        editor.view.dom.addEventListener('contextmenu', handleEmbedContextMenu as EventListener);
        editor.view.dom.addEventListener('touchstart', handleTouchStart as EventListener);
        editor.view.dom.addEventListener('touchmove', handleTouchMove as EventListener);
        editor.view.dom.addEventListener('touchend', handleTouchEnd as EventListener);
        editor.view.dom.addEventListener('touchcancel', handleTouchEnd as EventListener);
        editorCreated = true;
    }

    onMount(() => {
        if (!editorElement) return;

        // CRITICAL: Streaming messages must render immediately, not lazily
        // Otherwise content updates won't be visible until the message scrolls into view
        if (isStreaming) {
            isVisible = true;
            createEditor();
            return; // Skip Intersection Observer for streaming messages
        }

        // Performance optimization: Use Intersection Observer for lazy initialization
        // Only create the TipTap editor when the message becomes visible
        const observer = new IntersectionObserver(
            (entries) => {
                const entry = entries[0];
                if (entry.isIntersecting && !isVisible) {
                    isVisible = true;
                    // Create editor when message enters viewport
                    createEditor();
                }
            },
            {
                // Start loading slightly before message becomes visible (100px buffer)
                rootMargin: '100px',
                threshold: 0.01
            }
        );

        observer.observe(editorElement);

        // Cleanup observer on component destroy
        return () => {
            observer.disconnect();
        };
    });

    // Track previous locale to detect changes
    let previousLocale = $state($locale || 'en');
    
    // Reactive statement to update Tiptap editor when 'content' prop OR locale changes using $effect (Svelte 5 runes mode)
    $effect(() => {
        // Include $locale in the effect to trigger re-processing on language change
        const currentLocale = $locale || 'en';
        const localeChanged = currentLocale !== previousLocale;
        
        if (localeChanged) {
            previousLocale = currentLocale;
            // Clear cache for this component's content
            // The cache is already cleared globally, but ensure we don't use stale cache
        }
        
        if (editor && content) {
            // Always re-process content when locale changes to ensure translations are updated
            // The processContent function uses $text() which depends on the current locale
            const newProcessedContent = processContent(content);
            
            // Compare processed content to detect changes (including translation updates)
            const currentEditorContent = editor.getJSON();
            const contentChanged = JSON.stringify(currentEditorContent) !== JSON.stringify(newProcessedContent);
            
            // Force update if locale changed, even if content appears identical
            // This ensures translations are refreshed
            if (contentChanged || localeChanged) {
                editor.commands.setContent(newProcessedContent, { emitUpdate: false });
            }
        } else if (editor && !content) {
            // Handle case where content becomes null/undefined after editor initialization
            editor.commands.clearContent(false);
        }
    });


    onDestroy(() => {
        if (editor) {
            logger.debug('Component destroying. Cleaning up Tiptap editor.');
            // Remove all event listeners
            editor.view.dom.removeEventListener('contextmenu', handleEmbedContextMenu as EventListener);
            editor.view.dom.removeEventListener('touchstart', handleTouchStart as EventListener);
            editor.view.dom.removeEventListener('touchmove', handleTouchMove as EventListener);
            editor.view.dom.removeEventListener('touchend', handleTouchEnd as EventListener);
            editor.view.dom.removeEventListener('touchcancel', handleTouchEnd as EventListener);
            // Clear any pending touch timers
            clearTouchTimer();
            editor.destroy();
            editor = null;
        }
    });
</script>

<div class="read-only-message">
    <div bind:this={editorElement} class="editor-content"></div>
</div>

<style>
    .read-only-message {
        width: 100%;
        /* Enable text selection on touch devices - override parent user-select: none */
        user-select: text !important;
        -webkit-user-select: text !important; /* Required for iOS Safari */
        -moz-user-select: text !important;
        -ms-user-select: text !important;
    }

    /* Style overrides for read-only mode */
    :global(.read-only-message .ProseMirror) {
        outline: none;
        cursor: default;
        padding: 0;
        /* Enable text selection on touch devices - override parent user-select: none */
        user-select: text !important;
        -webkit-user-select: text !important; /* Required for iOS Safari */
        -moz-user-select: text !important;
        -ms-user-select: text !important;
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

    /* Hide ProseMirror separator and trailingBreak after embed previews to reduce spacing */
    /* These are ProseMirror's internal elements used for cursor positioning in the editor,
       but they create unwanted gaps in read-only view. The separator is an <img> element
       that marks the end of a node view, and trailingBreak is a <br> for cursor positioning. */
    :global(.read-only-message .markdown-paragraph .embed-full-width-wrapper ~ .ProseMirror-separator),
    :global(.read-only-message .markdown-paragraph .embed-full-width-wrapper ~ .ProseMirror-trailingBreak),
    :global(.read-only-message .markdown-paragraph:has(.embed-full-width-wrapper) .ProseMirror-separator),
    :global(.read-only-message .markdown-paragraph:has(.embed-full-width-wrapper) .ProseMirror-trailingBreak) {
        display: none;
    }

    :global(code) {
        background-color: black;
        padding: 5px;
        border-radius: 7px; 
    }

    /* Link styling - target actual anchor tags with high specificity */
    :global(.read-only-message .ProseMirror .markdown-link),
    :global(.read-only-message .ProseMirror .markdown-paragraph a),
    :global(.read-only-message .ProseMirror a),
    :global(.read-only-message .markdown-link),
    :global(.read-only-message .markdown-paragraph a),
    :global(.read-only-message a) {
        background: var(--color-primary) !important;
        background-clip: text !important;
        -webkit-background-clip: text !important;
        -webkit-text-fill-color: transparent !important;
        text-decoration: none !important;
        color: transparent !important; /* Fallback for browsers that don't support background-clip */
        transition: none !important; /* Remove transition that might interfere */
    }

    /* Hover states with high specificity */
    :global(.read-only-message .ProseMirror .markdown-link:hover),
    :global(.read-only-message .ProseMirror .markdown-paragraph a:hover),
    :global(.read-only-message .ProseMirror a:hover),
    :global(.read-only-message .markdown-link:hover),
    :global(.read-only-message .markdown-paragraph a:hover),
    :global(.read-only-message a:hover) {
        background: var(--color-primary) !important;
        background-clip: text !important;
        -webkit-background-clip: text !important;
        -webkit-text-fill-color: transparent !important;
        text-decoration: underline !important;
        color: transparent !important;
    }

    /* Focus states */
    :global(.read-only-message .ProseMirror .markdown-link:focus),
    :global(.read-only-message .ProseMirror .markdown-paragraph a:focus),
    :global(.read-only-message .ProseMirror a:focus),
    :global(.read-only-message .markdown-link:focus),
    :global(.read-only-message .markdown-paragraph a:focus),
    :global(.read-only-message a:focus) {
        background: var(--color-primary) !important;
        background-clip: text !important;
        -webkit-background-clip: text !important;
        -webkit-text-fill-color: transparent !important;
        outline: 2px solid var(--color-primary) !important;
        outline-offset: 2px !important;
        color: transparent !important;
    }

    /* Alternative approach for browsers that don't support :has() */
    :global(.read-only-message .markdown-list-item > .markdown-paragraph:not(:last-child) .ProseMirror-trailingBreak) {
        display: none;
    }

    /* List indentation - target the actual ul/ol elements with markdown classes */
    :global(.read-only-message ul.markdown-bullet-list),
    :global(.read-only-message ol.markdown-ordered-list) {
        padding-inline-start: 20px !important;
        margin: 0 !important;
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

    /* Empty paragraph styling for proper spacing */
    :global(.read-only-message .ProseMirror p) {
        min-height: 0.3em;
    }

    /* Remove artificial margins - whitespace should be preserved naturally */
</style>
