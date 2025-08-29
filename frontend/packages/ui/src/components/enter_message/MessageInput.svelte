<!-- frontend/packages/ui/src/components/enter_message/MessageInput.svelte -->
<script lang="ts">
    import { onMount, onDestroy, tick } from 'svelte';
    import { Editor } from '@tiptap/core';
    import { createEventDispatcher } from 'svelte';
    import { tooltip } from '../../actions/tooltip';
    import { text } from '@repo/ui'; // Use text store
    import { chatSyncService } from '../../services/chatSyncService'; // Import chatSyncService

    // Services & Stores
    import {
        initializeDraftService,
        cleanupDraftService,
        setCurrentChatContext,
        clearEditorAndResetDraftState,
        triggerSaveDraft,
        flushSaveDraft
    } from '../../services/draftService';
    import { recordingState, updateRecordingState } from './recordingStore';
    import { aiTypingStore, type AITypingStatus } from '../../stores/aiTypingStore';

    // Config & Extensions
    import { getEditorExtensions } from './editorConfig';

    // Components
    import CameraView from './CameraView.svelte';
    import RecordAudio from './RecordAudio.svelte'; // Import type for ref
    import MapsView from './MapsView.svelte';
    import PressAndHoldMenu from './in_message_previews/PressAndHoldMenu.svelte';
    import ActionButtons from './ActionButtons.svelte';
    import KeyboardShortcuts from '../KeyboardShortcuts.svelte';
    import { Decoration, DecorationSet } from 'prosemirror-view';

    // Utils
    import {
        formatDuration,
        isContentEmptyExceptMention,
        getInitialContent,
        detectAndReplaceMates,
        detectAndReplaceUrls,
    } from './utils';
    
    // Unified parser imports
    import { parse_message } from '../../message_parsing/parse_message';
    import { tipTapToCanonicalMarkdown } from '../../message_parsing/serializers';
    import { generateUUID } from '../../message_parsing/utils';
    import { isDesktop } from '../../utils/platform';
    
    // URL metadata service
    import { fetchUrlMetadata, createJsonCodeBlock, extractUrlFromJsonBlock } from './services/urlMetadataService';

    // Handlers
    import { handleSend } from './handlers/sendHandlers';
    import {
        processFiles,
        handleDrop as handleFileDrop,
        handleDragOver as handleFileDragOver,
        handleDragLeave as handleFileDragLeave,
        handlePaste as handleFilePaste,
        onFileSelected as handleFileSelectedEvent
    } from './fileHandlers';
    import {
        insertVideo,
        insertImage,
        insertRecording,
        insertMap
    } from './embedHandlers';
    import {
        handleEmbedInteraction as handleMenuEmbedInteraction,
        handleMenuAction as handleMenuActionTrigger
    } from './menuHandlers';
    import {
        // Import the handlers that expect DOM events
        handleRecordMouseDown as handleRecordMouseDownLogic,
        handleRecordMouseUp as handleRecordMouseUpLogic,
        handleRecordMouseLeave as handleRecordMouseLeaveLogic,
        handleRecordTouchStart as handleRecordTouchStartLogic,
        handleRecordTouchEnd as handleRecordTouchEndLogic,
        handleStopRecordingCleanup
    } from './handlers/recordingHandlers';
    import { handleKeyboardShortcut } from './handlers/keyboardShortcutHandler';

    const dispatch = createEventDispatcher();

    // --- Props ---
    export let defaultMention: string = 'sophia';
    export let currentChatId: string | undefined = undefined;
    export let isFullscreen = false;
    export let hasContent = false; // Expose hasContent to parent component

    // --- Refs ---
    let fileInput: HTMLInputElement;
    let cameraInput: HTMLInputElement;
    let videoElement: HTMLVideoElement;
    let editor: Editor;
    let editorElement: HTMLElement | undefined = undefined;
    let scrollableContent: HTMLElement;
    let messageInputWrapper: HTMLElement;
    // Type the ref using the component's type
    let recordAudioComponent: RecordAudio;

    // --- Local UI State ---
    let showCamera = false;
    let showMaps = false;
    let isMessageFieldFocused = false;
    let isScrollable = false;
    let showMenu = false;
    let menuX = 0;
    let menuY = 0;
    let selectedEmbedId: string | null = null;
    let menuType: 'default' | 'pdf' | 'web' = 'default';
    let selectedNode: { node: any; pos: number } | null = null;
    let isMenuInteraction = false;
    let previousHeight = 0;

    // --- Original Markdown Tracking ---
    let originalMarkdown = '';
    let isUpdatingFromMarkdown = false;
    let isConvertingEmbeds = false;

    // --- AI Task State ---
    let activeAITaskId: string | null = null;
    let currentTypingStatus: AITypingStatus = { isTyping: false, category: null, chatId: null, userMessageId: null, aiMessageId: null };
 
    // --- Unified Parsing Handler ---
    function handleUnifiedParsing(editor: Editor) {
        try {
            // Get raw text content from the editor to preserve newlines
            const markdown = editor.getText();
            
            console.debug('[MessageInput] Using unified parser for write mode:', { 
                markdown: markdown.substring(0, 100),
                length: markdown.length,
                hasNewlines: markdown.includes('\n')
            });
            
            // Parse with unified parser in write mode
            const parsedDoc = parse_message(markdown, 'write', { 
                unifiedParsingEnabled: true 
            });
            
            // Check for closed URLs that should be processed for metadata
            const closedUrls = detectClosedUrls(editor);
            if (closedUrls.length > 0) {
                console.info('[MessageInput] Found closed URLs to process:', closedUrls);
                processClosedUrls(editor, closedUrls);
                return; // Exit early as editor content will change and trigger another update
            }
            
            // Check if there are streaming data for highlighting
            if (parsedDoc._streamingData && parsedDoc._streamingData.unclosedBlocks.length > 0) {
                console.info('[MessageInput] Found unclosed blocks for highlighting:',
                    parsedDoc._streamingData.unclosedBlocks);
                
                // Apply highlighting colors for unclosed blocks
                applyHighlightingColors(editor, parsedDoc._streamingData.unclosedBlocks);
            } else {
                console.debug('[MessageInput] No unclosed blocks found, current markdown:', editor.getText());
                // Clear decorations when no unclosed blocks
                currentDecorationSet = DecorationSet.empty;
                if (decorationPropsSet && editor?.view) {
                    editor.view.dispatch(editor.state.tr);
                }
            }
            
        } catch (error) {
            console.error('[MessageInput] Error in unified parsing:', error);
            // Log the error but don't fall back to legacy - we need to fix the unified parser
        }
    }
    
    /**
     * Detect URLs that have become "closed" and should be processed for metadata
     * A URL is considered closed when it has whitespace (space or newline) after it
     */
    function detectClosedUrls(editor: Editor): Array<{url: string, startPos: number, endPos: number}> {
        const closedUrls: Array<{url: string, startPos: number, endPos: number}> = [];
        
        // Only check for closed URLs if the user just typed a space or newline
        const lastChar = originalMarkdown.slice(-1);
        if (lastChar !== ' ' && lastChar !== '\n') {
            return closedUrls;
        }
        
        // Find URLs in the original markdown that end just before the space/newline
        const urlRegex = /https?:\/\/[^\s]+/g;
        let match;
        
        // Reset regex lastIndex to ensure we get all matches
        urlRegex.lastIndex = 0;
        
        while ((match = urlRegex.exec(originalMarkdown)) !== null) {
            const url = match[0];
            const urlStart = match.index!;
            const urlEnd = urlStart + url.length;
            
            // Check if this URL ends just before where we typed the space/newline
            if (urlEnd === originalMarkdown.length - 1 && (lastChar === ' ' || lastChar === '\n')) {
                console.debug('[MessageInput] Found newly closed URL:', url, 'at position', urlStart, '-', urlEnd);
                
                // Check if this URL is already processed (not in a JSON code block)
                if (!originalMarkdown.includes('```json')) {
                    closedUrls.push({
                        url,
                        startPos: urlStart,
                        endPos: urlEnd
                    });
                }
            }
        }
        
        return closedUrls;
    }
    
    /**
     * Process closed URLs by fetching metadata and replacing them with JSON code blocks
     */
    async function processClosedUrls(editor: Editor, closedUrls: Array<{url: string, startPos: number, endPos: number}>) {
        console.debug('[MessageInput] Processing closed URLs:', closedUrls);
        
        if (closedUrls.length === 0) return;
        
        // Set flag to prevent originalMarkdown updates during processing
        isConvertingEmbeds = true;
        
        try {
            // Process URLs one by one (could be parallelized later if needed)
            for (const urlInfo of closedUrls) {
                try {
                    console.info('[MessageInput] Fetching metadata for URL:', urlInfo.url);
                    
                    // Fetch metadata from preview.openmates.org
                    const metadata = await fetchUrlMetadata(urlInfo.url);
                    
                    if (metadata) {
                        // Replace URL with JSON block in markdown storage for successful metadata fetch
                        const jsonBlock = createJsonCodeBlock(metadata);
                        
                        // Replace URL in original markdown
                        const beforeUrl = originalMarkdown.substring(0, urlInfo.startPos);
                        const afterUrl = originalMarkdown.substring(urlInfo.endPos);
                        originalMarkdown = beforeUrl + jsonBlock + afterUrl;
                        
                        console.info('[MessageInput] Successfully replaced URL with JSON block:', {
                            url: urlInfo.url,
                            title: metadata.title.substring(0, 50) + '...'
                        });
                        
                        // Update the editor to reflect the new content
                        updateEditorFromMarkdown(editor, originalMarkdown);
                        
                    } else {
                        console.info('[MessageInput] Metadata fetch failed, creating webEmbed node without metadata:', urlInfo.url);
                        
                        // For UI: Convert URL to webEmbed node even without metadata
                        // For storage: Keep original markdown with plain URL (no JSON block)
                        
                        // Find the URL position in the current editor
                        const transaction = editor.state.tr;
                        const doc = editor.state.doc;
                        let urlPos = -1;
                        
                        // Find the URL text in the document
                        doc.descendants((node, pos) => {
                            if (node.isText && node.text?.includes(urlInfo.url)) {
                                const textContent = node.text;
                                const urlIndex = textContent.indexOf(urlInfo.url);
                                if (urlIndex !== -1) {
                                    urlPos = pos + urlIndex;
                                    return false; // stop iteration
                                }
                            }
                        });
                        
                        if (urlPos !== -1) {
                            // Use the unified embed extension to create a web embed node
                            const embedNode = editor.schema.nodes.embed;
                            if (!embedNode) {
                                console.error('[MessageInput] embed node type not found in schema. Available nodes:', Object.keys(editor.schema.nodes));
                                return;
                            }
                            
                            // Replace the URL text with a unified embed node of type 'web'
                            const from = urlPos;
                            const to = urlPos + urlInfo.url.length;
                            
                            const embedAttributes = {
                                id: crypto.randomUUID(),
                                type: 'web',
                                status: 'finished', // Since we're not fetching metadata, it's "finished"
                                contentRef: null, // No content ref since no metadata
                                url: urlInfo.url
                            };
                            
                            transaction.replaceWith(from, to, embedNode.create(embedAttributes));
                            
                            editor.view.dispatch(transaction);
                            
                            console.info('[MessageInput] Created unified embed node (web) for URL without metadata:', urlInfo.url);
                        }
                    }
                    
                } catch (error) {
                    console.error('[MessageInput] Error processing URL:', urlInfo.url, error);
                }
            }
        } finally {
            // Always reset the flag
            isConvertingEmbeds = false;
        }
    }
    
    /**
     * Update the editor content from markdown
     * Used when we modify the markdown (e.g., URL replacements) and need to sync the editor
     */
    function updateEditorFromMarkdown(editor: Editor, markdown: string) {
        isUpdatingFromMarkdown = true;
        
        try {
            // Parse the markdown and update the editor
            // For now, we'll use a simple approach - in future iterations we can enhance this
            const parsedDoc = parse_message(markdown, 'write', { unifiedParsingEnabled: true });
            
            if (parsedDoc && parsedDoc.content) {
                editor.commands.setContent(parsedDoc);
            }
            
            console.debug('[MessageInput] Updated editor from markdown:', {
                length: markdown.length,
                preview: markdown.substring(0, 100)
            });
            
        } catch (error) {
            console.error('[MessageInput] Error updating editor from markdown:', error);
        } finally {
            isUpdatingFromMarkdown = false;
        }
    }
    
    /**
     * Update the original markdown based on editor changes
     * This preserves the user's original intent while allowing rich editing
     */
    function updateOriginalMarkdown(editor: Editor) {
        if (isUpdatingFromMarkdown || isConvertingEmbeds) {
            return; // Prevent infinite loops and preserve markdown during embed conversions
        }
        
        // Get the raw text content from the editor (this preserves user's actual typing)
        const editorText = editor.getText();
        
        // If the editor content is just the default mention, treat as empty
        if (isContentEmptyExceptMention(editor)) {
            originalMarkdown = '';
        } else {
            originalMarkdown = editorText;
        }
        
        console.debug('[MessageInput] Updated original markdown:', { 
            length: originalMarkdown.length,
            preview: originalMarkdown.substring(0, 100)
        });
    }
    
    /**
     * Get the original markdown for sending to server
     * This returns the user's actual typed content without TipTap conversion artifacts
     */
    function getOriginalMarkdownForSending(): string {
        console.debug('[MessageInput] Getting original markdown for sending:', {
            length: originalMarkdown.length,
            preview: originalMarkdown.substring(0, 100)
        });
        return originalMarkdown;
    }

    /**
     * Apply TipTap decorations to highlight unclosed blocks in write mode
     * Uses TipTap's native decoration system to avoid DOM conflicts
     */
    function applyHighlightingColors(editor: Editor, unclosedBlocks: any[]) {
        console.debug('[MessageInput] Applying TipTap decorations for unclosed blocks:', 
            unclosedBlocks.map(block => ({ type: block.type, startLine: block.startLine })));

        const { state, view } = editor;
        const { doc } = state;
        const text = editor.getText();
        console.debug('[MessageInput] applyHighlightingColors called with unclosedBlocks:', unclosedBlocks, 'editor text:', text);

        console.debug('[MessageInput] Editor state:', {
            docSize: doc.content.size,
            textLength: text.length,
            text: text.substring(0, 100) + (text.length > 100 ? '...' : '')
        });

        try {
            // Map each line to its start offset for precise range mapping
            const lines = text.split('\n');
            const lineStartOffsets: number[] = [];
            let acc = 0;
            for (let i = 0; i < lines.length; i++) {
                lineStartOffsets.push(acc);
                acc += lines[i].length + 1; // +1 for the newline
            }

            // Build decorations for all unclosed blocks (support multiple ranges)
            const decorations: Array<{ from: number; to: number; className: string; type: string; }> = [];
            // Track last table decoration end to avoid creating multiple overlapping table decorations
            let lastTableDecorationTo = -1;

            const clampToDoc = (pos: number) => Math.max(1, Math.min(pos, doc.content.size));

            for (const block of unclosedBlocks) {
                let className = 'unclosed-block-default';
                switch (block.type) {
                    case 'code': className = 'unclosed-block-code'; break;
                    case 'table': className = 'unclosed-block-table'; break;
                    case 'document_html': className = 'unclosed-block-html'; break;
                    case 'url':
                        // Check if this is a YouTube URL from the block content
                        if (block.content && /(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/watch\?v=|youtu\.be\/)/.test(block.content)) {
                            className = 'unclosed-block-video';
                        } else {
                            className = 'unclosed-block-url';
                        }
                        break;
                    case 'video':
                        className = 'unclosed-block-video';
                        break;
                    case 'markdown':
                        className = 'unclosed-block-markdown';
                        break;
                    default:
                        className = 'unclosed-block-default';
                        break;
                }

                const startLine: number = typeof block.startLine === 'number' ? block.startLine : 0;
                const startLineOffset = lineStartOffsets[Math.max(0, Math.min(startLine, lineStartOffsets.length - 1))] ?? 0;

                if (block.type === 'code') {
                    // Find the opening fence on or after startLine
                    let openIndex = -1;
                    for (let ln = startLine; ln < lines.length && openIndex === -1; ln++) {
                        const lineText = lines[ln];
                        const idx = lineText.indexOf('```');
                        if (idx !== -1) openIndex = lineStartOffsets[ln] + idx;
                    }
                    if (openIndex === -1) openIndex = startLineOffset; // fallback

                    // Find the closing fence after opening; if absent, highlight to end
                    const closeIndex = text.indexOf('```', openIndex + 3);
                    
                    // Highlight from opening fence to end of text if no closing fence
                    const from = clampToDoc(openIndex + 1);
                    const to = clampToDoc((closeIndex !== -1 ? closeIndex + 3 : text.length) + 1);
                    if (from < to) decorations.push({ from, to, className, type: 'code' });
                    continue;
                }

                if (block.type === 'url' || block.type === 'video') {
                    // Highlight the specific URL from the block content
                    const url = block.content;
                    const startIndex = text.indexOf(url, startLineOffset);
                    if (startIndex !== -1) {
                        const endIndex = startIndex + url.length;
                        const from = clampToDoc(startIndex + 1);
                        const to = clampToDoc(endIndex + 1);
                        if (from < to) decorations.push({ from, to, className, type: block.type });
                    }
                    continue;
                }

                if (block.type === 'table') {
                    // Highlight contiguous table lines until an empty line appears
                    let firstLine = startLine;
                    // If startLine doesn't include a pipe, search downwards for the next pipe row
                    while (firstLine < lines.length && !lines[firstLine].includes('|')) firstLine++;
                    if (firstLine >= lines.length) continue;

                    let lastLine = firstLine;
                    for (let ln = firstLine; ln < lines.length; ln++) {
                        const lt = lines[ln];
                        const trimmedLt = lt.trim();
                        if (trimmedLt === '') {
                            // Allow blank lines within a table if the following non-blank line is still a table row
                            let k = ln + 1;
                            while (k < lines.length && lines[k].trim() === '') k++;
                            if (k < lines.length && lines[k].includes('|')) {
                                // skip over blanks and continue
                                ln = k - 1; // loop will ++ to k
                                continue;
                            }
                            break; // end of table block
                        }
                        if (!trimmedLt.includes('|')) break; // no longer a table row
                        lastLine = ln;
                    }
                    const from = clampToDoc(lineStartOffsets[firstLine] + 1);
                    // end at end of lastLine text
                    const endOffset = lineStartOffsets[lastLine] + lines[lastLine].length;
                    const to = clampToDoc(endOffset + 1);
                    // Avoid pushing multiple overlapping/adjacent table decorations for the same block
                    if (from < to && from > lastTableDecorationTo) {
                        decorations.push({ from, to, className, type: 'table' });
                        lastTableDecorationTo = to;
                    }
                    continue;
                }

                // Markdown token highlighting: use tokenStartCol/tokenEndCol when present
                if (block.type === 'markdown' && typeof (block as any).tokenStartCol === 'number' && typeof (block as any).tokenEndCol === 'number') {
                    const tokenStartCol = (block as any).tokenStartCol as number;
                    const tokenEndCol = (block as any).tokenEndCol as number;
                    const from = clampToDoc(startLineOffset + tokenStartCol + 1);
                    const to = clampToDoc(startLineOffset + tokenEndCol + 1);
                    if (from < to) decorations.push({ from, to, className, type: block.type });
                    continue;
                }

                // Default: highlight current line
                const lineEnd = text.indexOf('\n', startLineOffset);
                const from = clampToDoc(startLineOffset + 1);
                const to = clampToDoc((lineEnd === -1 ? text.length : lineEnd) + 1);
                if (from < to) decorations.push({ from, to, className, type: block.type });
            }

            console.debug('[MessageInput] Created decorations:', decorations, 'from unclosedBlocks:', unclosedBlocks);

            const tipTapDecorations = decorations.map(dec =>
                Decoration.inline(dec.from, dec.to, {
                    class: dec.className,
                    'data-block-type': dec.type
                }, {
                    inclusiveStart: false,
                    inclusiveEnd: true
                })
            );

            currentDecorationSet = DecorationSet.create(doc, tipTapDecorations);
            if (!decorationPropsSet) {
                view.setProps({
                    decorations: () => currentDecorationSet ?? DecorationSet.empty,
                });
                decorationPropsSet = true;
            }
            // Always dispatch to refresh (also clears when empty)
            console.debug('[MessageInput] Dispatching transaction with decorations:', tipTapDecorations.length > 0 ? tipTapDecorations : 'empty');
            view.dispatch(state.tr);

        } catch (error) {
            console.error('[MessageInput] Error in TipTap decoration highlighting:', error);
        }
    }
 
    // --- Lifecycle ---
    let languageChangeHandler: () => void;
    let resizeObserver: ResizeObserver;
    // ProseMirror decorations plumbing
    let decorationPropsSet = false;
    let currentDecorationSet: DecorationSet | null = null;

    // onMount, onDestroy, editor handlers, setupEventListeners, cleanup remain the same

    onMount(() => {
        if (!editorElement) {
            console.error("Editor element not found on mount.");
            return;
        }

        editor = new Editor({
            element: editorElement,
            extensions: getEditorExtensions(),
            content: getInitialContent(),
            onFocus: handleEditorFocus,
            onBlur: handleEditorBlur,
            onUpdate: handleEditorUpdate,
        });

        initializeDraftService(editor);
        hasContent = !isContentEmptyExceptMention(editor);

        setupEventListeners();

        resizeObserver = new ResizeObserver(handleResize);
        if (scrollableContent) resizeObserver.observe(scrollableContent);

        tick().then(updateHeight);

        // AI Task related updates
        updateActiveAITaskStatus(); // Initial check
        chatSyncService.addEventListener('aiTaskInitiated', handleAiTaskOrChatChange);
        chatSyncService.addEventListener('aiTaskEnded', handleAiTaskOrChatChange);
        // Consider 'aiTaskCancellationAcknowledged' for more granular UI if needed

        const unsubscribeAiTyping = aiTypingStore.subscribe(value => {
            currentTypingStatus = value;
        });
 
        return () => {
            cleanup();
            unsubscribeAiTyping();
        };
    });
 
    onDestroy(() => {
        // cleanup() is now called from the onMount return function.
        // Ensure event listeners specific to this component that were added outside onMount's return
        // (if any) are cleaned up here or in the onMount return.
        // For chatSyncService listeners, they are added in onMount and should be cleaned up in its return.
        // The unsubscribeAiTyping is also handled there.
    });

    // --- Editor Lifecycle Handlers ---
    function handleEditorFocus({ editor }: { editor: Editor }) {
        isMessageFieldFocused = true;
        if (editor.isEmpty) {
            editor.commands.setContent(getInitialContent(), false);
            editor.commands.focus('end');
        }
    }

    function handleEditorBlur({ editor }: { editor: Editor }) {
        isMessageFieldFocused = false;
        setTimeout(() => {
            if (isMenuInteraction) return;
            flushSaveDraft();
            if (isContentEmptyExceptMention(editor)) {
                editor.commands.setContent(getInitialContent());
                hasContent = false;
            }
        }, 100);
    }

    function handleEditorUpdate({ editor }: { editor: Editor }) {
        const newHasContent = !isContentEmptyExceptMention(editor);
        if (hasContent !== newHasContent) {
            hasContent = newHasContent;
            if (!newHasContent) {
                console.debug("[MessageInput] Content cleared, triggering draft deletion.");
            }
        }
        
        // Update original markdown tracking
        updateOriginalMarkdown(editor);
        
        // Always trigger save/delete operation - the draft service handles both scenarios
        triggerSaveDraft(currentChatId);

        // Use unified parser for write mode
        handleUnifiedParsing(editor);

        tick().then(() => {
            checkScrollable();
            updateHeight();
        });
    }

    // --- Event Listener Setup & Cleanup ---
    function setupEventListeners() {
        document.addEventListener('embedclick', handleEmbedClick as EventListener);
        document.addEventListener('mateclick', handleMateClick as EventListener);
        editorElement?.addEventListener('paste', handlePaste);
        editorElement?.addEventListener('custom-send-message', handleSendMessage as EventListener);
        editorElement?.addEventListener('keydown', handleKeyDown);
        editorElement?.addEventListener('codefullscreen', handleCodeFullscreen as EventListener);
        window.addEventListener('saveDraftBeforeSwitch', flushSaveDraft);
        window.addEventListener('beforeunload', handleBeforeUnload);
        document.addEventListener('visibilitychange', handleVisibilityChange);
        languageChangeHandler = () => {
            if (editor && !editor.isDestroyed) editor.view.dispatch(editor.view.state.tr);
        };
        window.addEventListener('language-changed', languageChangeHandler);
    }

    function cleanup() {
        resizeObserver?.disconnect();
        document.removeEventListener('embedclick', handleEmbedClick as EventListener);
        document.removeEventListener('mateclick', handleMateClick as EventListener);
        editorElement?.removeEventListener('paste', handlePaste);
        editorElement?.removeEventListener('custom-send-message', handleSendMessage as EventListener);
        editorElement?.removeEventListener('keydown', handleKeyDown);
        editorElement?.removeEventListener('codefullscreen', handleCodeFullscreen as EventListener);
        window.removeEventListener('saveDraftBeforeSwitch', flushSaveDraft);
        window.removeEventListener('beforeunload', handleBeforeUnload);
        document.removeEventListener('visibilitychange', handleVisibilityChange);
        window.removeEventListener('language-changed', languageChangeHandler);
        cleanupDraftService();
        if (editor && !editor.isDestroyed) editor.destroy();
        handleStopRecordingCleanup();
    }

    // --- AI Task Status Update ---
    function updateActiveAITaskStatus() {
        if (currentChatId && chatSyncService) {
            activeAITaskId = chatSyncService.getActiveAITaskIdForChat(currentChatId);
        } else {
            activeAITaskId = null;
        }
    }

    function handleAiTaskOrChatChange() {
        updateActiveAITaskStatus();
    }

    async function handleCancelAITask() {
        if (activeAITaskId) {
            console.info(`[MessageInput] Requesting cancellation for AI task: ${activeAITaskId}`);
            await chatSyncService.sendCancelAiTask(activeAITaskId);
            // Optionally, set a "cancelling..." UI state here
            // The button will disappear once the 'aiTaskEnded' event is received and processed.
        }
    }
 
    // --- Specific Event Handlers ---
    function handleEmbedClick(event: CustomEvent) { // Use built-in CustomEvent
        const result = handleMenuEmbedInteraction(event, editor, event.detail.id);
        if (result) {
            isMenuInteraction = true;
            menuX = result.menuX; menuY = result.menuY;
            selectedEmbedId = result.selectedEmbedId; menuType = result.menuType;
            selectedNode = result.selectedNode; showMenu = true;
        } else {
            isMenuInteraction = false; showMenu = false; selectedNode = null; selectedEmbedId = null;
        }
    }
    function handleMateClick(event: CustomEvent) { dispatch('mateclick', { id: event.detail.id }); }
    async function handlePaste(event: ClipboardEvent) {
        await handleFilePaste(event, editor, defaultMention);
        tick().then(() => hasContent = !isContentEmptyExceptMention(editor));
    }
    function handleKeyDown(event: KeyboardEvent) {
        // The 'Enter' key logic is now handled by the custom Tiptap extension
        // in createKeyboardHandlingExtension() in sendHandlers.ts.

        if (event.key === 'Backspace') {
            // Check if we're trying to delete a JSON code block (website preview)
            handleJsonCodeBlockBackspace(event);
        } else if (event.key === 'Escape') {
            if (showCamera) { event.preventDefault(); showCamera = false; }
            else if (showMaps) { event.preventDefault(); showMaps = false; }
            else if (showMenu) { event.preventDefault(); showMenu = false; isMenuInteraction = false; selectedNode = null; }
            else if (isMessageFieldFocused) { event.preventDefault(); editor?.commands.blur(); }
        }
    }
    
    /**
     * Handle backspace when trying to delete JSON code blocks (website previews)
     * Should revert the JSON code block back to the original URL
     */
    function handleJsonCodeBlockBackspace(event: KeyboardEvent) {
        if (!editor) return;
        
        const { from, to } = editor.state.selection;
        
        // Only handle if cursor is at the end of a JSON code block or if a JSON code block is selected
        const textBeforeCursor = editor.state.doc.textBetween(Math.max(0, from - 200), from);
        const jsonBlockMatch = textBeforeCursor.match(/```json\n([\s\S]*?)\n```$/);
        
        if (jsonBlockMatch) {
            try {
                const jsonContent = jsonBlockMatch[1];
                const parsed = JSON.parse(jsonContent);
                
                if (parsed.type === 'website' && parsed.url) {
                    event.preventDefault();
                    
                    // Find the position of the JSON code block in the original markdown
                    const fullJsonBlock = jsonBlockMatch[0];
                    const jsonStart = originalMarkdown.indexOf(fullJsonBlock);
                    
                    if (jsonStart !== -1) {
                        // Replace JSON code block with original URL in markdown
                        const beforeJson = originalMarkdown.substring(0, jsonStart);
                        const afterJson = originalMarkdown.substring(jsonStart + fullJsonBlock.length);
                        originalMarkdown = beforeJson + parsed.url + afterJson;
                        
                        // Update editor to reflect the change
                        updateEditorFromMarkdown(editor, originalMarkdown);
                        
                        console.info('[MessageInput] Reverted JSON code block to URL:', parsed.url);
                    }
                }
            } catch (error) {
                // Not a valid JSON, let default backspace behavior handle it
                console.debug('[MessageInput] Not a valid website JSON block, using default backspace');
            }
        }
    }
    function handleCodeFullscreen(event: CustomEvent) { dispatch('codefullscreen', event.detail); }
    function handleBeforeUnload() { if (hasContent) flushSaveDraft(); }
    function handleVisibilityChange() { if (document.visibilityState === 'hidden' && hasContent) flushSaveDraft(); }
    function handleResize() { checkScrollable(); updateHeight(); }

    // --- UI Update Functions ---
    function updateHeight() {
        if (!messageInputWrapper) return;
        const currentHeight = messageInputWrapper.offsetHeight;
        if (currentHeight !== previousHeight) {
            previousHeight = currentHeight;
            dispatch('heightchange', { height: currentHeight });
        }
    }
    function checkScrollable() { if (scrollableContent) isScrollable = scrollableContent.scrollHeight > scrollableContent.clientHeight; }
    function toggleFullscreen() {
        isFullscreen = !isFullscreen;
        dispatch('fullscreenToggle', isFullscreen);
        tick().then(checkScrollable);
    }

    // --- Action Handlers (delegating to imported handlers) ---
    // File/Camera/Location handlers remain the same as previous step

    async function handleDrop(event: DragEvent) {
        await handleFileDrop(event, editorElement, editor, defaultMention);
        tick().then(() => hasContent = !isContentEmptyExceptMention(editor));
    }
    function handleDragOver(event: DragEvent) { handleFileDragOver(event, editorElement); }
    function handleDragLeave(event: DragEvent) { handleFileDragLeave(event, editorElement); }
    async function onFileSelected(event: Event) {
        await handleFileSelectedEvent(event, editor, defaultMention);
        tick().then(() => hasContent = !isContentEmptyExceptMention(editor));
    }
    function handleCameraClick() {
        const isMobile = window.matchMedia('(max-width: 768px), (pointer: coarse)').matches && ('ontouchstart' in window || navigator.maxTouchPoints > 0);
        if (isMobile) cameraInput?.click(); else showCamera = true;
    }
    async function handlePhotoCaptured(event: CustomEvent<{ blob: Blob, previewUrl: string }>) {
        const { blob, previewUrl } = event.detail;
        const file = new File([blob], `camera_${Date.now()}.jpg`, { type: 'image/jpeg' });
        showCamera = false; await tick();
        await insertImage(editor, file, true, previewUrl);
        hasContent = true;
    }
    async function handleVideoRecorded(event: CustomEvent<{ blob: Blob, duration: string }>) {
        const { blob, duration } = event.detail;
        const file = new File([blob], `video_${Date.now()}.webm`, { type: 'video/webm' });
        showCamera = false; await tick();
        await insertVideo(editor, file, duration, true);
        hasContent = true;
    }
    async function handleAudioRecorded(event: CustomEvent<{ blob: Blob, duration: number }>) {
        const { blob, duration } = event.detail;
        const url = URL.createObjectURL(blob);
        const filename = `audio_${Date.now()}.webm`;
        const formattedDuration = formatDuration(duration);
        if (editor.isEmpty) { editor.commands.setContent(getInitialContent()); await tick(); }
        insertRecording(editor, url, filename, formattedDuration);
        hasContent = true;
        handleStopRecordingCleanup(); // Called here after recording is inserted
    }
    function handleLocationClick() { showMaps = true; }
    async function handleLocationSelected(event: CustomEvent<{ type: string; attrs: any }>) {
        showMaps = false; await tick();
        if (editor.isEmpty) { editor.commands.setContent(getInitialContent()); await tick(); }
        insertMap(editor, event.detail);
        hasContent = true;
    }
    async function handleMenuAction(action: string) {
        await handleMenuActionTrigger(action, selectedNode, editor, dispatch, selectedEmbedId);
        showMenu = false; isMenuInteraction = false; selectedNode = null; selectedEmbedId = null;
        if (action === 'delete') {
            await tick(); hasContent = !isContentEmptyExceptMention(editor);
        }
    }
    function handleFileSelect() { fileInput.multiple = true; fileInput.click(); }
    function handleSendMessage() {
        handleSend(
            editor,
            defaultMention,
            dispatch,
            (value) => (hasContent = value),
            currentChatId
        );
    }

    function handleInsertSpace() {
        if (editor && !editor.isDestroyed) {
            editor.commands.insertContent(' ');
        }
    }
    function handleRecordingLayoutChange(event: CustomEvent<{ active: boolean }>) {
        updateRecordingState({ isRecordingActive: event.detail.active });
        tick().then(updateHeight);
    }

    // --- Handlers to bridge ActionButtons events to recordingHandlers ---
    // These now extract the original event from the detail payload
    function onRecordMouseDown(event: CustomEvent<{ originalEvent: MouseEvent }>) {
        handleRecordMouseDownLogic(event.detail.originalEvent);
    }
    function onRecordMouseUp(event: CustomEvent<{ originalEvent: MouseEvent }>) {
        // Pass the component ref to the logic handler
        handleRecordMouseUpLogic(recordAudioComponent);
    }
    function onRecordMouseLeave(event: CustomEvent<{ originalEvent: MouseEvent }>) {
        // Pass the component ref to the logic handler
        handleRecordMouseLeaveLogic(recordAudioComponent);
    }
    function onRecordTouchStart(event: CustomEvent<{ originalEvent: TouchEvent }>) {
        handleRecordTouchStartLogic(event.detail.originalEvent);
    }
    function onRecordTouchEnd(event: CustomEvent<{ originalEvent: TouchEvent }>) {
        // Pass the component ref to the logic handler
        handleRecordTouchEndLogic(recordAudioComponent);
    }


    // --- Public API ---
    export function focus() { if (editor && !editor.isDestroyed) editor.commands.focus('end'); }
    export function setDraftContent(chatId: string | null, draftContent: any | null, version: number, shouldFocus: boolean = true) {
        setCurrentChatContext(chatId, draftContent, version);
        
        // If draftContent is null, it means the draft was deleted on another device
        // We need to clear the editor content
        if (draftContent === null && editor) {
            console.debug("[MessageInput] Received null draft from sync, clearing editor content");
            editor.commands.setContent(getInitialContent());
            hasContent = false;
            originalMarkdown = ''; // Clear markdown tracking
        } else if (shouldFocus && editor) {
            editor.commands.focus('end');
            hasContent = !isContentEmptyExceptMention(editor);
            updateOriginalMarkdown(editor); // Update markdown tracking
        }
    }
    export function clearMessageField(shouldFocus: boolean = true) {
        clearEditorAndResetDraftState(shouldFocus);
        hasContent = false;
        originalMarkdown = ''; // Clear markdown tracking
    }
    export function getOriginalMarkdown(): string {
        return getOriginalMarkdownForSending();
    }

    // --- Reactive Calculations ---
    $: containerStyle = isFullscreen ? `height: calc(100vh - 100px); max-height: calc(100vh - 120px); height: calc(100dvh - 100px); max-height: calc(100dvh - 120px);` : 'height: auto; max-height: 350px;';
    $: scrollableStyle = isFullscreen ? `max-height: calc(100vh - 190px); max-height: calc(100dvh - 190px);` : 'max-height: 250px;';
    $: if (isFullscreen !== undefined && messageInputWrapper) tick().then(updateHeight);
    
    // Track previous chat ID to detect changes
    let previousChatId: string | undefined = undefined;
    
    // React to chat ID changes to save drafts when switching chats
    $: {
        if (currentChatId !== previousChatId && previousChatId !== undefined && hasContent) {
            console.debug(`[MessageInput] Chat ID changed from ${previousChatId} to ${currentChatId}, flushing draft for previous chat`);
            flushSaveDraft(); // Save draft for the previous chat before switching
        }
        previousChatId = currentChatId;
    }
    
    $: if (currentChatId !== undefined && chatSyncService) updateActiveAITaskStatus(); // Update when currentChatId changes
 
</script>
 
<!-- Template -->
<div bind:this={messageInputWrapper} class="message-input-wrapper">
    <div
        class="message-field {isMessageFieldFocused ? 'focused' : ''} {$recordingState.isRecordingActive ? 'recording-active' : ''}"
        class:drag-over={editorElement?.classList.contains('drag-over')}
        style={containerStyle}
        on:dragover|preventDefault={handleDragOver}
        on:dragleave|preventDefault={handleDragLeave}
        on:drop|preventDefault={handleDrop}
        role="textbox"
        aria-multiline="true"
        tabindex="0"
    >
        {#if isScrollable || isFullscreen}
            <button
                class="clickable-icon icon_fullscreen fullscreen-button"
                on:click={toggleFullscreen}
                aria-label={isFullscreen ? $text('enter_message.fullscreen.exit_fullscreen.text') : $text('enter_message.fullscreen.enter_fullscreen.text')}
                use:tooltip
            ></button>
        {/if}

        <input bind:this={fileInput} type="file" on:change={onFileSelected} style="display: none" multiple accept="*/*" />
        <input bind:this={cameraInput} type="file" accept="image/*,video/*" capture="environment" on:change={onFileSelected} style="display: none" />

        <div class="scrollable-content" bind:this={scrollableContent} style={scrollableStyle}>
            <div class="content-wrapper">
                <div bind:this={editorElement} class="editor-content prose"></div>
            </div>
        </div>

        {#if showCamera}
            <CameraView bind:videoElement on:close={() => showCamera = false} on:focusEditor={focus} on:photocaptured={handlePhotoCaptured} on:videorecorded={handleVideoRecorded} />
        {/if}

        <!-- Action Buttons Component or Cancel Button -->
        {#if activeAITaskId}
            <div class="action-buttons-container cancel-mode-active">
                <button
                    class="button primary cancel-ai-button"
                    on:click={handleCancelAITask}
                    use:tooltip
                    title={$text('enter_message.stop.text')}
                    aria-label={$text('enter_message.stop.text')}
                >
                    <span class="icon icon_stop"></span>
                    <span>{$text('enter_message.stop.text')}</span>
                </button>
            </div>
        {:else}
            <ActionButtons
                showSendButton={hasContent}
                isRecordButtonPressed={$recordingState.isRecordButtonPressed}
                showRecordHint={$recordingState.showRecordHint}
                micPermissionGranted={$recordingState.micPermissionGranted}
                on:fileSelect={handleFileSelect}
                on:locationClick={handleLocationClick}
                on:cameraClick={handleCameraClick}
                on:sendMessage={handleSendMessage}
                on:recordMouseDown={onRecordMouseDown}
                on:recordMouseUp={onRecordMouseUp}
                on:recordMouseLeave={onRecordMouseLeave}
                on:recordTouchStart={onRecordTouchStart}
                on:recordTouchEnd={onRecordTouchEnd}
            />
        {/if}
 
        {#if showMenu}
            <PressAndHoldMenu x={menuX} y={menuY} show={showMenu} type={menuType} isYouTube={selectedNode?.node?.attrs?.isYouTube || false} on:close={() => { showMenu = false; isMenuInteraction = false; selectedNode = null; selectedEmbedId = null; }} on:delete={() => handleMenuAction('delete')} on:download={() => handleMenuAction('download')} on:view={() => handleMenuAction('view')} on:copy={() => handleMenuAction('copy')} />
        {/if}

        {#if $recordingState.showRecordAudioUI}
            <!-- Pass the required initialPosition from the store -->
            <RecordAudio
                bind:this={recordAudioComponent}
                initialPosition={$recordingState.recordStartPosition}
                on:audiorecorded={handleAudioRecorded}
                on:close={handleStopRecordingCleanup}
                on:cancel={handleStopRecordingCleanup}
                on:recordingStateChange={handleRecordingLayoutChange}
            />
        {/if}

        {#if showMaps}
            <MapsView on:close={() => showMaps = false} on:locationselected={handleLocationSelected} />
        {/if}
    </div>
</div>

<!-- Keyboard Shortcuts Listener -->
<!-- Pass the component instance directly -->
<KeyboardShortcuts
    on:startRecording={() => handleKeyboardShortcut('startRecording', editor, isMessageFieldFocused, recordAudioComponent)}
    on:stopRecording={() => handleKeyboardShortcut('stopRecording', editor, isMessageFieldFocused, recordAudioComponent)}
    on:cancelRecording={() => handleKeyboardShortcut('cancelRecording', editor, isMessageFieldFocused, recordAudioComponent)}
    on:insertSpace={handleInsertSpace}
/>

<style>
    @import './MessageInput.styles.css';
</style>