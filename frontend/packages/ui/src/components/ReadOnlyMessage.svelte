<script lang="ts">
    import { onMount, onDestroy, tick } from 'svelte';
    import { Editor } from '@tiptap/core';
    import StarterKit from '@tiptap/starter-kit';
    import { text } from '@repo/ui';
    import { Embed } from '../components/enter_message/extensions/Embed';
    import { MateNode } from '../components/enter_message/extensions/MateNode';
    import { AIModelMentionNode } from '../components/enter_message/extensions/AIModelMentionNode';
    import { GenericMentionNode } from '../components/enter_message/extensions/GenericMentionNode';
    import { MarkdownExtensions } from '../components/enter_message/extensions/MarkdownExtensions';
    import { parseMarkdownToTiptap, isMarkdownContent } from '../components/enter_message/utils/markdownParser';
    import { parse_message } from '../message_parsing/parse_message';
    import { createEventDispatcher } from 'svelte';
    import { contentCache } from '../utils/contentCache';
    import { locale } from 'svelte-i18n';
    import { Decoration, DecorationSet } from 'prosemirror-view';
    import { getPIILabel } from '../components/enter_message/services/piiDetectionService';
    import type { PIIMapping } from '../types/chat';

    // Props using Svelte 5 runes mode
    // _embedUpdateTimestamp is used to force re-render when embed data becomes available
    // (bypasses content cache since markdown string is unchanged but embed data is now decryptable)
    let { 
        content, 
        isStreaming = false, 
        _embedUpdateTimestamp = 0,
        selectable = false,
        piiMappings = undefined,
        piiRevealed = false
    }: { 
        content: any; 
        isStreaming?: boolean; 
        _embedUpdateTimestamp?: number;
        selectable?: boolean;
        piiMappings?: PIIMapping[];
        piiRevealed?: boolean; // Whether PII original values are visible (false = placeholders shown, true = originals shown)
    } = $props(); // The message content from Tiptap JSON

    let editorElement: HTMLElement;
    let editor: Editor | null = null;
    const dispatch = createEventDispatcher();
    
    /**
     * Auto-selects all text content within the message.
     * Useful when 'Select' is chosen from the context menu.
     */
    export function selectAll() {
        if (!editorElement) return;
        
        // Wait for next tick to ensure any state changes are reflected in DOM
        tick().then(() => {
            const range = document.createRange();
            range.selectNodeContents(editorElement);
            const selection = window.getSelection();
            if (selection) {
                selection.removeAllRanges();
                selection.addRange(range);
                logger.debug('Text auto-selected');
            }
        });
    }

    /**
     * Selects the word at the specified coordinates, or the whole message as fallback.
     */
    export function selectAt(x: number, y: number) {
        if (!editor || !editor.view) return;

        tick().then(() => {
            const selection = window.getSelection();
            if (!selection) return;

            // Use TipTap's posAtCoords for better accuracy with its internal DOM structure
            const pos = editor.view.posAtCoords({ left: x, top: y });
            
            if (pos && pos.pos !== undefined) {
                try {
                    // Focus editor first
                    editor.commands.focus();
                    
                    // Get document and resolve position
                    const { doc } = editor.state;
                    const resolvedPos = doc.resolve(pos.pos);
                    
                    // Find word boundaries around the position
                    // We look for the start and end of the word containing the position
                    let start = pos.pos;
                    let end = pos.pos;
                    
                    const textContent = resolvedPos.parent.textContent;
                    
                    // Find start of word
                    while (start > resolvedPos.start() && /\w/.test(textContent[start - resolvedPos.start() - 1])) {
                        start--;
                    }
                    
                    // Find end of word
                    while (end < resolvedPos.end() && /\w/.test(textContent[end - resolvedPos.start()])) {
                        end++;
                    }
                    
                    if (start < end) {
                        // Select the word
                        editor.commands.setTextSelection({ from: start, to: end });
                        logger.debug(`Word selected at point: "${doc.textBetween(start, end)}"`);
                    } else {
                        // Fallback to select all if no word found
                        selectAll();
                    }
                } catch (e) {
                    logger.debug('Failed to expand selection via TipTap, falling back to select all', e);
                    selectAll();
                }
            } else {
                // Coordinate lookup failed, select all
                selectAll();
            }
        });
    }
    
    // Performance optimization: Lazy initialization with Intersection Observer
    // Only create the TipTap editor when the message becomes visible in the viewport
    let isVisible = $state(false);
    let editorCreated = $state(false);
    
    // STREAMING FIX: Track minimum height to prevent container collapse during chunk updates
    // When TipTap's setContent() replaces the document, it momentarily clears the DOM,
    // causing the container height to collapse to 0px before re-expanding.
    // We preserve the previous height as min-height to prevent this visual glitch.
    let preservedMinHeight = $state<number | null>(null);

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
    
    /**
     * Handle custom embed context menu events emitted by UnifiedEmbedPreview.
     * This is the canonical way for embed previews to request the EmbedContextMenu
     * (works for right-click and long-press, and avoids native browser menus).
     */
    function handleEmbedContextMenuEvent(event: CustomEvent) {
        const target = event.target as HTMLElement;
        const embedContainer = target.closest('[data-embed-id], [data-code-embed], .preview-container');
        if (!embedContainer) return;
        
        event.preventDefault?.();
        event.stopPropagation?.();
        
        logger.debug('[ReadOnlyMessage] Received embed-context-menu event');
        
        const pos = editor?.view.posAtDOM(embedContainer, 0);
        const node = pos !== undefined ? editor?.state.doc.nodeAt(pos) : null;
        if (!node) return;
        
        const elementId =
            embedContainer.getAttribute('data-embed-id') ||
            embedContainer.getAttribute('data-code-embed') ||
            embedContainer.id;
        
        const rect = embedContainer.getBoundingClientRect();
        const x = event.detail?.x;
        const y = event.detail?.y;
        
        dispatch('message-embed-click', {
            view: editor?.view,
            node,
            dom: embedContainer,
            elementId,
            rect,
            x,
            y
        });
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
                if (inputContent === 'chat.an_error_occured') {
                    const translatedText = $text('chat.an_error_occured');
                    return parse_message(translatedText, 'read', { unifiedParsingEnabled: true });
                }

                // Performance optimization: Check cache before parsing
                // Include locale in cache key to invalidate cache on language change
                // CRITICAL: When _embedUpdateTimestamp is set, bypass cache to force re-render
                // This handles the case where embed data becomes available after initial render
                // (the markdown is unchanged but embeds can now be decrypted and rendered)
                const currentLocale = $locale || 'en';
                const cacheKey = `${currentLocale}:${inputContent}`;
                
                // Bypass cache if embed update is pending - forces fresh parsing and re-rendering
                // This is necessary because embed NodeViews need to call resolveEmbed() again
                // to get the newly available embed data
                const bypassCache = _embedUpdateTimestamp && _embedUpdateTimestamp > 0;
                
                if (!bypassCache) {
                    const cached = contentCache.get(cacheKey);
                    if (cached) {
                        logger.debug('Using cached content for markdown parsing');
                        return cached;
                    }
                } else {
                    logger.debug('Bypassing cache due to embed update timestamp:', _embedUpdateTimestamp);
                }

                // Parse markdown text to TipTap JSON with unified parsing (includes embed parsing)
                const parsed = parse_message(inputContent, 'read', { unifiedParsingEnabled: true });
                
                // Only cache if not bypassing (avoid polluting cache with stale embed state)
                if (!bypassCache) {
                    contentCache.set(cacheKey, parsed);
                }
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
                    
                    if (textContent === 'chat.an_error_occured') {
                        // Replace the key with the translated text
                        firstParagraph.content[0].text = $text('chat.an_error_occured');
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
                // NOTE: StarterKit v3.4+ now includes link and underline by default
                strike: false, // Using MarkdownStrike instead
                link: false,   // Using MarkdownLink instead (with custom renderHTML for internal links)
                underline: false, // Using MarkdownUnderline instead
            }),
            Embed,
            MateNode,
            AIModelMentionNode, // For @ai-model:id mentions (displays as @Claude-4.5-Opus)
            GenericMentionNode, // For @skill:, @focus:, @memory: mentions
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
        editor.view.dom.addEventListener('embed-context-menu', handleEmbedContextMenuEvent as EventListener);
        editor.view.dom.addEventListener('touchstart', handleTouchStart as EventListener);
        editor.view.dom.addEventListener('touchmove', handleTouchMove as EventListener);
        editor.view.dom.addEventListener('touchend', handleTouchEnd as EventListener);
        editor.view.dom.addEventListener('touchcancel', handleTouchEnd as EventListener);
        editorCreated = true;
        
        // Apply PII highlighting decorations after editor is created
        applyPIIDecorations(editor);
    }
    
    /**
     * Find PII original values directly in the ProseMirror document and return
     * their correct document positions. This avoids the position mismatch that
     * occurs when using flat-text indices (from editor.getText()) because
     * ProseMirror positions include structural offsets for block boundaries
     * (each paragraph open/close adds to the position count).
     *
     * Walks every text node in the document and searches for each PII original
     * value within that node's text content, yielding exact ProseMirror positions.
     */
    function findPIIPositionsInDoc(doc: import('prosemirror-model').Node, mappings: PIIMapping[]): Array<{
        from: number;
        to: number;
        type: string;
        label: string;
    }> {
        const results: Array<{ from: number; to: number; type: string; label: string }> = [];
        // Build lookup entries that search for BOTH originals and placeholders.
        // The text might contain either depending on the current visibility state.
        const piiLookup: Array<{ searchText: string; type: string; label: string }> = [];
        for (const m of mappings) {
            const type = m.type || 'UNKNOWN';
            const label = getPIILabel(type);
            if (m.original) {
                piiLookup.push({ searchText: m.original, type, label });
            }
            if (m.placeholder) {
                piiLookup.push({ searchText: m.placeholder, type, label });
            }
        }
        
        doc.descendants((node, pos) => {
            if (!node.isText || !node.text) return;
            const nodeText = node.text;
            // For each PII mapping, search for all occurrences within this text node
            for (const pii of piiLookup) {
                let searchFrom = 0;
                while (searchFrom < nodeText.length) {
                    const idx = nodeText.indexOf(pii.searchText, searchFrom);
                    if (idx === -1) break;
                    // ProseMirror position: pos is the absolute position of the text node start
                    const from = pos + idx;
                    const to = from + pii.searchText.length;
                    results.push({ from, to, type: pii.type, label: pii.label });
                    searchFrom = idx + pii.searchText.length;
                }
            }
        });
        
        // Sort by position and deduplicate overlapping ranges
        results.sort((a, b) => a.from - b.from);
        // Remove overlapping results (keep the first one found)
        const deduped: typeof results = [];
        let lastEnd = -1;
        for (const r of results) {
            if (r.from >= lastEnd) {
                deduped.push(r);
                lastEnd = r.to;
            }
        }
        return deduped;
    }

    /**
     * Apply ProseMirror decorations to highlight restored PII values in read-only messages.
     * 
     * Searches the ProseMirror document directly (not flat text) to find correct
     * positions for PII values. Also strips link marks from PII ranges so that
     * emails don't render as clickable <a> tags.
     *
     * Two modes:
     * - piiRevealed=true: Shows original values with orange bold text
     * - piiRevealed=false (default): Replaces originals with placeholders, shown in green bold text
     */
    function applyPIIDecorations(editorInstance: Editor) {
        if (!piiMappings || piiMappings.length === 0 || !editorInstance || editorInstance.isDestroyed) return;
        
        try {
            const { state, view } = editorInstance;
            const { doc } = state;
            
            // Find PII positions by walking the ProseMirror document directly.
            // This gives correct positions that account for block-level structural offsets.
            const piiPositions = findPIIPositionsInDoc(doc, piiMappings);
            
            if (piiPositions.length === 0) return;
            
            // Step 1: Remove link marks from PII ranges so emails/URLs don't
            // render as clickable <a> tags. PII values should be plain highlighted text.
            const linkMarkType = state.schema.marks.link;
            if (linkMarkType) {
                let tr = state.tr;
                let hasLinkRemovals = false;
                for (const pos of piiPositions) {
                    let hasLink = false;
                    doc.nodesBetween(pos.from, pos.to, (node) => {
                        if (node.isText && linkMarkType.isInSet(node.marks)) {
                            hasLink = true;
                        }
                    });
                    if (hasLink) {
                        tr = tr.removeMark(pos.from, pos.to, linkMarkType);
                        hasLinkRemovals = true;
                    }
                }
                if (hasLinkRemovals) {
                    view.dispatch(tr);
                }
            }
            
            // Step 2: In HIDDEN mode, replace the actual text with placeholders.
            // In REVEALED mode, restore originals (in case we previously replaced them).
            // This is done via ProseMirror transactions so the DOM updates naturally.
            const afterLinkState = editorInstance.state;
            const afterLinkDoc = afterLinkState.doc;
            const afterLinkPositions = findPIIPositionsInDoc(afterLinkDoc, piiMappings);
            
            // Build lookup maps for both directions
            const originalToPlaceholder = new Map<string, string>();
            const placeholderToOriginal = new Map<string, string>();
            for (const m of piiMappings) {
                originalToPlaceholder.set(m.original, m.placeholder);
                placeholderToOriginal.set(m.placeholder, m.original);
            }
            
            // Replace text content: swap originals↔placeholders depending on mode
            let replaceTr = afterLinkState.tr;
            let hasReplacements = false;
            // Process positions in reverse order to avoid offset shifts
            for (let i = afterLinkPositions.length - 1; i >= 0; i--) {
                const pos = afterLinkPositions[i];
                // Extract the current text in this range
                let currentText = '';
                afterLinkDoc.nodesBetween(pos.from, pos.to, (node, nodePos) => {
                    if (node.isText && node.text) {
                        const start = Math.max(0, pos.from - nodePos);
                        const end = Math.min(node.text.length, pos.to - nodePos);
                        currentText += node.text.slice(start, end);
                    }
                });
                
                let targetText: string | null = null;
                if (!piiRevealed && originalToPlaceholder.has(currentText)) {
                    // Hidden mode: replace original with placeholder
                    targetText = originalToPlaceholder.get(currentText)!;
                } else if (piiRevealed && placeholderToOriginal.has(currentText)) {
                    // Revealed mode: replace placeholder with original
                    targetText = placeholderToOriginal.get(currentText)!;
                }
                
                if (targetText && targetText !== currentText) {
                    const textNode = afterLinkState.schema.text(targetText);
                    replaceTr = replaceTr.replaceWith(pos.from, pos.to, textNode);
                    hasReplacements = true;
                }
            }
            if (hasReplacements) {
                view.dispatch(replaceTr);
            }
            
            // Step 3: Apply PII highlight decorations on the (potentially updated) doc.
            const updatedState = editorInstance.state;
            const updatedDoc = updatedState.doc;
            
            // Re-find positions in updated doc after text replacements
            const updatedPositions = findPIIPositionsInDoc(updatedDoc, piiMappings);
            
            const cssClass = piiRevealed ? 'pii-restored pii-revealed' : 'pii-restored pii-hidden';
            const titleSuffix = piiRevealed ? '(sensitive data)' : '(hidden for privacy)';
            
            const decorations = updatedPositions.map(pos => {
                return Decoration.inline(pos.from, pos.to, {
                    class: cssClass,
                    'data-pii-type': pos.type,
                    title: `${pos.label} ${titleSuffix}`
                });
            });
            
            const decorationSet = DecorationSet.create(updatedDoc, decorations);
            view.setProps({
                decorations: () => decorationSet,
            });
            // Dispatch a no-op transaction to force ProseMirror to apply the decorations
            view.dispatch(updatedState.tr);
            
            logger.debug(`Applied ${decorations.length} PII decorations (revealed: ${piiRevealed}) to read-only message`);
        } catch (error) {
            console.error('[ReadOnlyMessage] Error applying PII decorations:', error);
        }
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
                // Start loading well before message becomes visible to prevent
                // content cutoff during fast scrolling. 500px buffer ensures editors
                // are initialized roughly half a mobile screen before entering viewport,
                // eliminating visual glitches while keeping memory usage reasonable
                // (only ~2-3 extra editors pre-initialized at any time).
                rootMargin: '500px',
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
    
    // STREAMING FIX: Clear preserved min-height when streaming ends
    // This allows the container to properly resize for subsequent renders
    $effect(() => {
        if (!isStreaming && preservedMinHeight !== null) {
            // Use a small delay to allow the final content to render before releasing min-height
            // This prevents any final frame flicker when the streaming completes
            const cleanup = setTimeout(() => {
                // Clear both the reactive state AND the inline DOM style
                preservedMinHeight = null;
                if (editorElement) {
                    editorElement.style.minHeight = '';
                }
            }, 100);
            
            return () => clearTimeout(cleanup);
        }
    });
    
    // Reactive statement to update Tiptap editor when 'content' prop OR locale changes using $effect (Svelte 5 runes mode)
    $effect(() => {
        // Include $locale in the effect to trigger re-processing on language change
        const currentLocale = $locale || 'en';
        const localeChanged = currentLocale !== previousLocale;
        
        // CRITICAL: Track embed update timestamp to force re-render when embed data arrives
        // This handles the race condition where embeds are initially unreadable (keys not cached)
        // but become decryptable after send_embed_data finishes processing
        const hasEmbedUpdate = _embedUpdateTimestamp && _embedUpdateTimestamp > 0;
        
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
            
            // Force update if locale changed, embed update occurred, or content actually changed
            // Embed updates require re-render even if parsed content is identical, because:
            // - The embed NodeViews need to call resolveEmbed() again
            // - Embed keys may now be available in cache for decryption
            if (contentChanged || localeChanged || hasEmbedUpdate) {
                if (hasEmbedUpdate) {
                    logger.debug('Forcing re-render due to embed update at:', _embedUpdateTimestamp);
                }
                // STREAMING FIX: Preserve current height SYNCHRONOUSLY before content replacement
                // CRITICAL: We must set min-height directly on the DOM element BEFORE calling setContent()
                // because Svelte's reactive updates are batched and happen asynchronously.
                // If we used reactive state, setContent() would execute before the style is applied,
                // causing the visual collapse we're trying to prevent.
                if (isStreaming && editorElement) {
                    const currentHeight = editorElement.offsetHeight;
                    if (currentHeight > 0) {
                        // Apply min-height SYNCHRONOUSLY via direct DOM manipulation
                        // This ensures the height constraint is in place before TipTap clears the content
                        editorElement.style.minHeight = `${currentHeight}px`;
                        // Also update the reactive state for consistency (used when streaming ends)
                        preservedMinHeight = currentHeight;
                    }
                }
                
                // Now safely replace content - the min-height prevents visual collapse
                editor.commands.setContent(newProcessedContent, { emitUpdate: false });
                
                // Re-apply PII decorations after content update
                applyPIIDecorations(editor);
                
                // STREAMING FIX: After content renders, update min-height to match actual content.
                // Always track the real height to prevent both collapse AND stale over-sizing.
                // The pre-setContent min-height above prevents the brief visual collapse during
                // the TipTap DOM rebuild; here we reconcile to the actual rendered height.
                if (isStreaming && editorElement) {
                    requestAnimationFrame(() => {
                        if (!editorElement) return;
                        const newHeight = editorElement.scrollHeight;
                        // Always update min-height to match the actual content.
                        // This prevents stale min-height from keeping the container stretched
                        // when embed groups are rebuilt at a different height.
                        editorElement.style.minHeight = `${newHeight}px`;
                        preservedMinHeight = newHeight;
                    });
                }
            }
        } else if (editor && !content) {
            // Handle case where content becomes null/undefined after editor initialization
            editor.commands.clearContent(false);
        }
    });


    // Re-apply PII decorations when piiRevealed changes (user toggled visibility)
    // This allows instant switching between showing placeholders and original values
    // without re-processing the entire message content.
    let previousPiiRevealed = $state(piiRevealed);
    $effect(() => {
        if (piiRevealed !== previousPiiRevealed) {
            previousPiiRevealed = piiRevealed;
            if (editor && !editor.isDestroyed) {
                applyPIIDecorations(editor);
            }
        }
    });

    onDestroy(() => {
        if (editor) {
            logger.debug('Component destroying. Cleaning up Tiptap editor.');
            // Remove all event listeners
            editor.view.dom.removeEventListener('contextmenu', handleEmbedContextMenu as EventListener);
            editor.view.dom.removeEventListener('embed-context-menu', handleEmbedContextMenuEvent as EventListener);
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

<div class="read-only-message" class:is-streaming={isStreaming} class:is-selectable={selectable}>
    <!-- STREAMING FIX: min-height is applied directly to the DOM via JavaScript (synchronously)
         before TipTap's setContent() clears the content. This prevents the visual collapse/stutter.
         Direct DOM manipulation is necessary because Svelte's reactive style updates are async. -->
    <div bind:this={editorElement} class="editor-content"></div>
</div>

<style>
    .read-only-message {
        width: 100%;
        /* Enable text selection by default */
        user-select: text !important;
        -webkit-user-select: text !important; /* Required for iOS Safari */
        -moz-user-select: text !important;
        -ms-user-select: text !important;
    }

    /* Keep is-selectable class for potentially future explicit overrides */
    .read-only-message.is-selectable {
        user-select: text !important;
        -webkit-user-select: text !important;
        -moz-user-select: text !important;
        -ms-user-select: text !important;
    }
    
    /* STREAMING FIX: Use CSS containment during streaming to prevent layout thrashing.
       contain: style prevents style recalculations from propagating to ancestors,
       while still allowing height changes to flow normally to the parent container.
       
       IMPORTANT: We previously used `contain: layout` which prevented the container from
       reporting its actual size to parent elements. This caused the "text stretching" glitch
       where content grew but the bubble/scroll container didn't resize properly.
       `contain: style` is sufficient to prevent style recalculation cascading without
       blocking height propagation. */
    .read-only-message.is-streaming {
        contain: style;
    }
    
    /* STREAMING FIX: Ensure editor-content transitions smoothly during streaming.
       overflow-anchor: none prevents the browser's automatic scroll anchoring from
       fighting with our manual scroll position management during streaming. */
    .editor-content {
        /* Prevent sudden height collapse by ensuring content always takes space */
        min-height: 1em;
    }
    
    .read-only-message.is-streaming .editor-content {
        /* Disable browser's automatic scroll anchoring during streaming.
           Without this, the browser tries to "helpfully" adjust scroll position when
           content above the anchor changes height, causing visual jumps. */
        overflow-anchor: none;
    }

    /* Style overrides for read-only mode */
    :global(.read-only-message .ProseMirror) {
        outline: none;
        cursor: default;
        padding: 0;
        /* Enable text selection by default */
        user-select: text !important;
        -webkit-user-select: text !important; /* Required for iOS Safari */
        -moz-user-select: text !important;
        -ms-user-select: text !important;
    }

    :global(.read-only-message.is-selectable .ProseMirror) {
        /* Keep for consistency */
        user-select: text !important;
        -webkit-user-select: text !important;
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

    /* AI Model mention styling - uses AI app gradient for consistent look */
    :global(.read-only-message .ai-model-mention) {
        display: inline;
        background: linear-gradient(
            135deg,
            var(--color-app-ai-start) 0%,
            var(--color-app-ai-end) 100%
        );
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        font-weight: 500;
        cursor: default;
        white-space: nowrap;
    }

    /* Mate mention styling - uses mate's custom gradient color via CSS custom properties */
    :global(.read-only-message .mate-mention) {
        display: inline;
        background: linear-gradient(
            135deg,
            var(--mate-color-start, var(--color-app-ai-start)) 0%,
            var(--mate-color-end, var(--color-app-ai-end)) 100%
        );
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        font-weight: 500;
        cursor: pointer;
        white-space: nowrap;
    }

    :global(.read-only-message .mate-mention:hover) {
        opacity: 0.8;
    }

    /* Generic mention styling (skills, focus modes, settings/memories) */
    :global(.read-only-message .generic-mention) {
        display: inline;
        background: linear-gradient(
            135deg,
            var(--mention-color-start, var(--color-primary-start)) 0%,
            var(--mention-color-end, var(--color-primary-end)) 100%
        );
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        font-weight: 500;
        cursor: default;
        white-space: nowrap;
    }

    /* Skill mentions */
    :global(.read-only-message .generic-mention.mention-skill) {
        /* Uses gradient from inline custom properties */
    }

    /* Focus mode mentions */
    :global(.read-only-message .generic-mention.mention-focus-mode) {
        /* Uses gradient from inline custom properties */
    }

    /* Settings/memory mentions */
    :global(.read-only-message .generic-mention.mention-settings-memory) {
        /* Uses gradient from inline custom properties */
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

    /* ==========================================================================
       PII RESTORED HIGHLIGHTING
       Bold colored text for ALL PII types in read-only messages.
       Same orange/amber color as the message input editor (MessageInput.styles.css).
       No links, no underlines — just bold colored text.
       
        Two modes controlled by CSS classes:
        - .pii-revealed: Original values shown in orange bold (warns sensitive data is exposed)
        - .pii-hidden: Placeholders shown in green bold (indicates data is safely anonymized)
       ========================================================================== */

    /* Base style for all restored PII — shared by both revealed and hidden modes.
       Uses bold colored text instead of background highlights for clean appearance. */
    :global(.read-only-message .pii-restored) {
        border-bottom: none;
        text-decoration: none !important;
        cursor: default;
        font-family: inherit;
        font-size: inherit;
        letter-spacing: inherit;
        font-weight: 600;
    }

    /* REVEALED MODE: Orange/amber bold text — warns that sensitive data is exposed */
    :global(.read-only-message .pii-restored.pii-revealed) {
        color: #f59e0b;
    }

    /* HIDDEN MODE: Green-toned bold text — indicates data is safely anonymized.
       The original text is replaced by the placeholder in the DOM via ProseMirror,
       so no CSS overlay trick is needed. */
    :global(.read-only-message .pii-restored.pii-hidden) {
        color: #4ade80;
    }

    /* Override link styling when PII is inside an anchor tag (e.g. email auto-linked).
       PII values must NOT appear as clickable links — strip all link appearance. */
    :global(.read-only-message a .pii-restored),
    :global(.read-only-message .pii-restored a),
    :global(.read-only-message a.pii-restored),
    :global(.read-only-message .ProseMirror a .pii-restored),
    :global(.read-only-message .ProseMirror .pii-restored a),
    :global(.read-only-message .ProseMirror a.pii-restored) {
        -webkit-text-fill-color: inherit !important;
        color: inherit !important;
        text-decoration: none !important;
        pointer-events: none;
        cursor: default;
    }
</style>
