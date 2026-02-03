<!-- frontend/packages/ui/src/components/enter_message/MessageInput.svelte -->
<script lang="ts">
    import { onMount, onDestroy, tick } from 'svelte';
    import { Editor } from '@tiptap/core';
    import { createEventDispatcher } from 'svelte';
    import { tooltip } from '../../actions/tooltip';
    import { fade } from 'svelte/transition';
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
    import { authStore } from '../../stores/authStore'; // Import auth store to check authentication status

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
        getInitialContent
    } from './utils';
    
    // Unified parser imports
    import { parse_message } from '../../message_parsing/parse_message';
    import { tipTapToCanonicalMarkdown } from '../../message_parsing/serializers';
    import { generateUUID } from '../../message_parsing/utils';
    import { isDesktop } from '../../utils/platform';
    
    // URL metadata service - creates proper embeds with embed_id for LLM context
    import { createEmbedFromUrl } from './services/urlMetadataService';

    // Handlers
    import { handleSend } from './handlers/sendHandlers';
    import MentionDropdown from './MentionDropdown.svelte';
    import {
        extractMentionQuery,
        type AnyMentionResult,
        type MateMentionResult
    } from './services/mentionSearchService';
    import {
        processFiles,
        handleDrop as handleFileDrop,
        handleDragOver as handleFileDragOver,
        handleDragLeave as handleFileDragLeave,
        handlePaste as handleFilePaste,
        onFileSelected as handleFileSelectedEvent,
        extractChatLinkFromYAML
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

    // --- Props using Svelte 5 $props() ---
    interface Props {
        currentChatId?: string | undefined;
        isFullscreen?: boolean;
        hasContent?: boolean;
        showActionButtons?: boolean;
        isFocused?: boolean;
    }
    let { 
        currentChatId = undefined,
        isFullscreen = $bindable(false),
        hasContent = $bindable(false),
        showActionButtons = true,
        isFocused = $bindable(false)
    }: Props = $props();

    // --- Refs ---
    let fileInput: HTMLInputElement;
    let cameraInput: HTMLInputElement;
    let videoElement = $state<HTMLVideoElement>();
    let editor: Editor;
    let editorElement = $state<HTMLElement | undefined>(undefined);
    let scrollableContent: HTMLElement;
    let messageInputWrapper: HTMLElement;
    // Type the ref using the component's type
    let recordAudioComponent = $state<RecordAudio>();

    // --- Local UI State ---
    let showCamera = $state(false);
    let showMaps = $state(false);
    let isMessageFieldFocused = $state(false);
    
    // --- Mention Dropdown State ---
    let showMentionDropdown = $state(false);
    let mentionQuery = $state('');

    let mentionDropdownY = $state(0);
    let isScrollable = $state(false);
    let showMenu = $state(false);
    let menuX = $state(0);
    let menuY = $state(0);
    let selectedEmbedId: string | null = null;
    let menuType = $state<'default' | 'pdf' | 'web'>('default');
    let selectedNode = $state<{ node: any; pos: number } | null>(null);
    let isMenuInteraction = false;
    let previousHeight = 0;
    
    // Computed state for showing action buttons
    // Shows when prop is true OR when field is focused
    let shouldShowActionButtons = $derived(showActionButtons || isMessageFieldFocused);

    // --- Original Markdown Tracking ---
    let originalMarkdown = '';
    let isUpdatingFromMarkdown = false;
    let isConvertingEmbeds = false;

    // --- AI Task State ---
    let activeAITaskId = $state<string | null>(null);
    // CRITICAL: Must use $state() for Svelte 5 reactivity - otherwise store subscription updates
    // won't trigger re-evaluation of reactive statements that depend on this variable
    let currentTypingStatus = $state<AITypingStatus>({ isTyping: false, category: null, chatId: null, userMessageId: null, aiMessageId: null });
    let queuedMessageText = $state<string | null>(null); // Message text when a message is queued
    let awaitingAITaskStart = $state(false); // Optimistic stop button immediately after send
    let cancelRequestedWhileAwaiting = $state(false); // If user clicks stop before task_id exists
    let awaitingAITaskTimeoutId: NodeJS.Timeout | null = null;
    
    // --- Backspace State ---
    let isBackspaceOperation = false; // Flag to prevent immediate re-grouping after backspace
    
    // --- Blur timeout tracking ---
    let blurTimeoutId: NodeJS.Timeout | null = null; // Track blur timeout to cancel it if focus is regained
    
    // --- Initial mount tracking ---
    let isInitialMount = $state(true); // Flag to prevent auto-focus during initial mount
    let mountCompleteTimeout: NodeJS.Timeout | null = null; // Track when mount is complete
 
    // --- Unified Parsing Handler ---
    function handleUnifiedParsing(editor: Editor) {
        try {
            // Skip unified parsing if we just performed a backspace operation to prevent immediate re-grouping
            if (isBackspaceOperation) {
                console.debug('[MessageInput] Skipping unified parsing due to recent backspace operation');
                isBackspaceOperation = false; // Reset the flag
                return;
            }
            
            // Use the serialized markdown that preserves json_embed blocks, not plain text
            // This ensures previously converted embeds are maintained when parsing new content
            const markdown = originalMarkdown || editor.getText();
            
            // console.debug('[MessageInput] Using unified parser for write mode:', { 
            //     markdown: markdown.substring(0, 100),
            //     length: markdown.length,
            //     hasNewlines: markdown.includes('\n'),
            //     usingOriginalMarkdown: !!originalMarkdown
            // });
            
            // Check for closed URLs that should be processed for metadata first
            // This should be done before parsing to avoid losing existing embeds
            const closedUrls = detectClosedUrls(editor);
            if (closedUrls.length > 0) {
                console.info('[MessageInput] Found closed URLs to process:', closedUrls);
                processClosedUrls(editor, closedUrls);
                return; // Exit early as editor content will change and trigger another update
            }
            
            // Parse with unified parser in write mode using the preserved markdown
            const parsedDoc = parse_message(markdown, 'write', { 
                unifiedParsingEnabled: true 
            });
            
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
                
                // Check if the parsed document contains preview embeds (closed code blocks)
                // If so, update the editor content to show the rendered embed preview
                if (parsedDoc && parsedDoc.content && hasPreviewEmbeds(parsedDoc)) {
                    console.debug('[MessageInput] Found preview embeds, updating editor with parsed document');
                    // Set flag to prevent originalMarkdown update during this content change
                    isConvertingEmbeds = true;
                    try {
                        editor.chain().setContent(parsedDoc, { emitUpdate: false }).run();
                        console.debug('[MessageInput] Updated editor with preview embeds');
                    } finally {
                        isConvertingEmbeds = false;
                    }
                }
            }
            
        } catch (error) {
            console.error('[MessageInput] Error in unified parsing:', error);
            // Log the error but don't fall back to legacy - we need to fix the unified parser
        }
    }
    
    /**
     * Check if a parsed document contains preview embeds (closed code blocks, tables, etc.)
     * Preview embeds have contentRef starting with 'preview:'
     */
    function hasPreviewEmbeds(doc: any): boolean {
        if (!doc || !doc.content) return false;
        
        for (const node of doc.content) {
            // Check if this node is a paragraph containing an embed
            if (node.type === 'paragraph' && node.content) {
                for (const child of node.content) {
                    if (child.type === 'embed' && child.attrs?.contentRef?.startsWith('preview:')) {
                        return true;
                    }
                }
            }
            // Check for direct embed nodes (shouldn't happen but be safe)
            if (node.type === 'embed' && node.attrs?.contentRef?.startsWith('preview:')) {
                return true;
            }
        }
        return false;
    }
    
    /**
     * Detect URLs that have become "closed" and should be processed for metadata
     * A URL is considered closed when it has whitespace (space or newline) after it
     * This function properly handles multiple URLs pasted together by detecting all URLs
     * that are followed by whitespace in the recent content
     */
    function detectClosedUrls(editor: Editor): Array<{url: string, startPos: number, endPos: number}> {
        const closedUrls: Array<{url: string, startPos: number, endPos: number}> = [];
        
        // Use originalMarkdown to preserve existing json_embed blocks when detecting new URLs
        // Fall back to editor text if originalMarkdown is not available yet
        const sourceText = originalMarkdown || editor.getText();
        const lastChar = sourceText.slice(-1);
        
        console.debug('[MessageInput] detectClosedUrls using source:', {
            usingOriginalMarkdown: !!originalMarkdown,
            sourceLength: sourceText.length,
            lastChar: lastChar,
            preview: sourceText.substring(0, 100) + (sourceText.length > 100 ? '...' : '')
        });
        
        // Only check for closed URLs if the user just typed a space or newline
        // This ensures we only process URLs when they're actually "closed" (followed by whitespace)
        if (lastChar !== ' ' && lastChar !== '\n') {
            return closedUrls;
        }
        
        // Find all code block ranges to exclude URLs within them in source text
        const codeBlockRanges: Array<{start: number, end: number}> = [];
        
        // Find all types of code blocks: regular code, json_embed, and document_html
        const codeBlockPatterns = [
            /```json_embed\n[\s\S]*?\n```/g,           // json_embed blocks
            /```document_html\n[\s\S]*?\n```/g,        // document_html blocks
            /```[\w]*[:\w\/\.]*\n[\s\S]*?\n```/g       // regular code blocks (with optional language and path)
        ];
        
        for (const pattern of codeBlockPatterns) {
            pattern.lastIndex = 0; // Reset regex
            let blockMatch;
            while ((blockMatch = pattern.exec(sourceText)) !== null) {
                codeBlockRanges.push({
                    start: blockMatch.index,
                    end: blockMatch.index + blockMatch[0].length
                });
                console.debug('[MessageInput] Found code block to exclude:', {
                    start: blockMatch.index,
                    end: blockMatch.index + blockMatch[0].length,
                    content: blockMatch[0].substring(0, 50) + '...'
                });
            }
        }
        
        console.debug('[MessageInput] Total code block ranges to exclude:', codeBlockRanges.length);
        
        // Find all URLs in the source text
        // We'll check each one to see if it's closed (followed by whitespace) and recently added
        const urlRegex = /https?:\/\/[^\s]+/g;
        let match;
        
        // Reset regex lastIndex to ensure we get all matches
        urlRegex.lastIndex = 0;
        
        // Track all URLs and their positions
        const allUrls: Array<{url: string, startPos: number, endPos: number}> = [];
        
        while ((match = urlRegex.exec(sourceText)) !== null) {
            const url = match[0];
            const urlStart = match.index!;
            const urlEnd = urlStart + url.length;
            
            // Check if this URL is inside any code block - skip if it is
            const isInsideCodeBlock = codeBlockRanges.some(range => 
                urlStart >= range.start && urlEnd <= range.end
            );
            
            if (!isInsideCodeBlock) {
                allUrls.push({
                    url,
                    startPos: urlStart,
                    endPos: urlEnd
                });
            } else {
                console.debug('[MessageInput] URL is inside a code block, skipping:', url);
            }
        }
        
        // Now check which URLs are "closed" (followed by whitespace)
        // For multiple URLs pasted together, we need to detect all that are followed by space/newline
        // and are in the recent content (within a reasonable distance from the end)
        // Use a more generous threshold to handle multiple long URLs pasted together
        const recentContentThreshold = Math.max(500, sourceText.length * 0.3); // At least 500 chars or 30% of content
        
        for (const urlInfo of allUrls) {
            const { url, startPos, endPos } = urlInfo;
            
            // Check if URL is followed by whitespace (space or newline)
            // This indicates the URL is "closed" and ready for processing
            const charAfterUrl = sourceText[endPos];
            const isFollowedByWhitespace = charAfterUrl === ' ' || charAfterUrl === '\n';
            
            // Check if this URL is in the recent content area
            // This helps us focus on URLs that were just pasted/typed, not old ones
            const distanceFromEnd = sourceText.length - endPos;
            const isInRecentContent = distanceFromEnd <= recentContentThreshold;
            
            // Check if URL is part of a sentence (has non-whitespace text before it)
            // URLs that are part of sentences like "summarize {url}" should NOT be converted to embeds
            // Only standalone URLs (at start of text, after newline, after only whitespace, or after another URL) should be converted
            const textBeforeUrl = sourceText.substring(0, startPos);
            const trimmedBeforeUrl = textBeforeUrl.trim();
            
            // Check if the text before the URL is just another URL (for handling multiple URLs pasted together)
            // This allows "url1 url2 " to convert both URLs
            const urlRegexBefore = /https?:\/\/[^\s]+$/;
            const textBeforeTrimmed = textBeforeUrl.trimEnd();
            const isAfterAnotherUrl = urlRegexBefore.test(textBeforeTrimmed);
            
            // A URL is standalone if:
            // 1. There's no non-whitespace content before it (at start or after only whitespace)
            // 2. It's after a newline
            // 3. It's after another URL (for multiple URLs pasted together)
            const isStandaloneUrl = trimmedBeforeUrl.length === 0 || textBeforeUrl.endsWith('\n') || isAfterAnotherUrl;
            
            // A URL is considered "recently closed" and ready for conversion if:
            // 1. It's followed by whitespace (closed)
            // 2. It's in the recent content area (likely just pasted/typed)
            // 3. The last character of the text is whitespace (user just closed something)
            // 4. It's a standalone URL (not part of a sentence)
            const isRecentlyClosed = isFollowedByWhitespace && isInRecentContent && (lastChar === ' ' || lastChar === '\n') && isStandaloneUrl;
            
            if (isRecentlyClosed) {
                console.debug('[MessageInput] Found newly closed standalone URL:', {
                    url,
                    startPos,
                    endPos,
                    charAfterUrl,
                    distanceFromEnd,
                    threshold: recentContentThreshold,
                    isStandaloneUrl,
                    textBeforeUrl: textBeforeUrl.substring(Math.max(0, textBeforeUrl.length - 20)) // Last 20 chars for debugging
                });
                
                closedUrls.push({
                    url,
                    startPos,
                    endPos
                });
            } else if (isFollowedByWhitespace && isInRecentContent && (lastChar === ' ' || lastChar === '\n') && !isStandaloneUrl) {
                // Log when we skip a URL because it's part of a sentence
                console.debug('[MessageInput] Skipping URL conversion - URL is part of a sentence:', {
                    url,
                    textBeforeUrl: textBeforeUrl.substring(Math.max(0, textBeforeUrl.length - 30)) // Last 30 chars for debugging
                });
            }
        }
        
        console.debug('[MessageInput] Total closed URLs detected:', closedUrls.length);
        
        return closedUrls;
    }
    
    // NOTE: Code block detection and embed creation is handled SERVER-SIDE
    // When user sends a message with code blocks:
    // 1. Client sends raw markdown (with code blocks as-is)
    // 2. Server extracts code blocks and creates embeds
    // 3. Server sends embed data back to client for encrypted storage
    // 4. Server replaces code blocks with embed references in stored message
    // This avoids client-side complexity and draft serialization issues
    
    /**
     * Process closed URLs by creating proper embeds with embed_id.
     * 
     * This function:
     * 1. Fetches metadata from preview server (website or YouTube)
     * 2. Creates proper embeds with embed_id stored in EmbedStore
     * 3. Replaces URLs with embed references: {"type": "...", "embed_id": "..."}
     * 
     * The embeds will be:
     * - Extracted by extractEmbedReferences() when message is sent
     * - Loaded from EmbedStore and sent to server
     * - Cached server-side for LLM inference
     * - Resolved for AI context building
     */
    async function processClosedUrls(editor: Editor, closedUrls: Array<{url: string, startPos: number, endPos: number}>) {
        console.debug('[MessageInput] Processing closed URLs:', closedUrls);
        
        if (closedUrls.length === 0) return;
        
        // Set flag to prevent originalMarkdown updates during processing
        isConvertingEmbeds = true;
        
        try {
            // Create embeds for all URLs in parallel to improve performance
            // This fetches metadata and stores embeds in EmbedStore
            const embedPromises = closedUrls.map(async (urlInfo) => {
                try {
                    console.info('[MessageInput] Creating embed for URL:', urlInfo.url);
                    const embedResult = await createEmbedFromUrl(urlInfo.url);
                    return { urlInfo, embedResult };
                } catch (error) {
                    console.error('[MessageInput] Error creating embed for URL:', urlInfo.url, error);
                    return { urlInfo, embedResult: null };
                }
            });
            
            const embedResults = await Promise.all(embedPromises);
            
            // Replace URLs with embed reference blocks in the preserved markdown content
            // Process URLs from end to beginning to maintain position integrity when replacing
            const sortedResults = [...embedResults].sort((a, b) => b.urlInfo.startPos - a.urlInfo.startPos);
            let currentText = originalMarkdown || editor.getText();
            
            for (const { urlInfo, embedResult } of sortedResults) {
                if (!embedResult) {
                    console.warn('[MessageInput] Skipping URL - embed creation failed:', urlInfo.url);
                    continue;
                }
                
                try {
                    console.info('[MessageInput] Successfully created embed for URL:', {
                        url: urlInfo.url,
                        embed_id: embedResult.embed_id,
                        type: embedResult.type
                    });
                    
                    // Replace URL with embed reference block in text content
                    const beforeUrl = currentText.substring(0, urlInfo.startPos);
                    const afterUrl = currentText.substring(urlInfo.endPos);
                    
                    // Ensure proper newline spacing around the embed reference block
                    let processedBeforeUrl = beforeUrl;
                    let processedAfterUrl = afterUrl;
                    
                    // Ensure single newline before the block (if there's content before and it doesn't end with newline)
                    if (processedBeforeUrl.length > 0 && !processedBeforeUrl.endsWith('\n')) {
                        processedBeforeUrl += '\n';
                    }
                    
                    // ALWAYS ensure single newline after the block if there's content after
                    // This prevents the text from being on the same line as the closing fence
                    if (processedAfterUrl.length > 0) {
                        // Only trim if there's actual content (not just whitespace)
                        // Don't remove the space the user just typed!
                        const hasNonWhitespaceContent = processedAfterUrl.trim().length > 0;
                        if (hasNonWhitespaceContent) {
                            // Remove leading whitespace and ensure proper newline separation
                            processedAfterUrl = processedAfterUrl.trimStart();
                            processedAfterUrl = '\n' + processedAfterUrl;
                        }
                        // If it's just whitespace (like a single space), keep it as-is
                    }
                    
                    currentText = processedBeforeUrl + embedResult.embedReference + processedAfterUrl;
                    
                    console.debug('[MessageInput] Replaced URL with embed reference:', {
                        url: urlInfo.url,
                        embed_id: embedResult.embed_id,
                        type: embedResult.type
                    });
                    
                } catch (error) {
                    console.error('[MessageInput] Error processing URL:', urlInfo.url, error);
                }
            }
            
            // Update the original markdown and then re-parse with unified parser
            console.debug('[MessageInput] Updated originalMarkdown with embed references:', {
                previousLength: originalMarkdown?.length || 0,
                newLength: currentText.length,
                hasEmbedRef: currentText.includes('"embed_id"'),
                preview: currentText.substring(0, 100) + (currentText.length > 100 ? '...' : '')
            });
            originalMarkdown = currentText;
            
            // Re-parse the updated markdown with unified parser to create embed nodes
            const parsedDoc = parse_message(originalMarkdown, 'write', { unifiedParsingEnabled: true });
            
            if (parsedDoc && parsedDoc.content) {
                // Update editor with the parsed content that includes embed nodes
                // Use chain().setContent(content, { emitUpdate: false }).run() to match the working draft loading pattern
                editor.chain().setContent(parsedDoc, { emitUpdate: false }).run();
                console.debug('[MessageInput] Updated editor with unified parser result');
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
                editor.chain().setContent(parsedDoc, { emitUpdate: false }).run();
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
     * IMPORTANT: This function should preserve existing json_embed blocks by using TipTap serialization
     */
    function updateOriginalMarkdown(editor: Editor) {
        if (isUpdatingFromMarkdown || isConvertingEmbeds) {
            return; // Prevent infinite loops and preserve markdown during embed conversions
        }
        
        // If the editor content is just the default mention, treat as empty
        if (isContentEmptyExceptMention(editor)) {
            originalMarkdown = '';
        } else {
            try {
                // Use TipTap's built-in serialization to convert the editor content back to markdown
                // This should preserve embed nodes as json_embed blocks
                const serializedMarkdown = tipTapToCanonicalMarkdown(editor.getJSON());
                originalMarkdown = serializedMarkdown;
                
                console.debug('[MessageInput] Updated original markdown via TipTap serialization:', { 
                    length: originalMarkdown.length,
                    preview: originalMarkdown.substring(0, 100),
                    hasJsonEmbed: originalMarkdown.includes('```json_embed')
                });
            } catch (error) {
                console.warn('[MessageInput] Error serializing TipTap content, falling back to plain text:', error);
                // Fallback to plain text if serialization fails
                originalMarkdown = editor.getText();
                
                console.debug('[MessageInput] Updated original markdown (fallback):', { 
                    length: originalMarkdown.length,
                    preview: originalMarkdown.substring(0, 100)
                });
            }
        }
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
        // console.debug('[MessageInput] applyHighlightingColors called with unclosedBlocks:', unclosedBlocks, 'editor text:', text);

        // console.debug('[MessageInput] Editor state:', {
        //     docSize: doc.content.size,
        //     textLength: text.length,
        //     text: text.substring(0, 100) + (text.length > 100 ? '...' : '')
        // });

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
                        // Use the same pattern as EMBED_PATTERNS.YOUTUBE_URL for consistency
                        // Note: This is a fallback - YouTube URLs should be detected as 'video' type in streamingSemantics
                        // Matches: youtube.com, www.youtube.com, m.youtube.com (mobile), youtu.be
                        // Supports: /watch?v=, /embed/, /shorts/, /v/ (legacy) formats
                        const youtubePattern = /(?:https?:\/\/)?(?:www\.|m\.)?(?:youtube\.com\/(?:watch\?v=|embed\/|shorts\/|v\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})/;
                        if (block.content && youtubePattern.test(block.content)) {
                            className = 'unclosed-block-video';
                            console.debug('[MessageInput] Detected YouTube URL in url block, using video highlight color (red):', block.content.substring(0, 50));
                        } else {
                            className = 'unclosed-block-url';
                        }
                        break;
                    case 'video':
                        // YouTube videos should always use red color (#A70B09)
                        className = 'unclosed-block-video';
                        console.debug('[MessageInput] Video block detected, using video highlight color (red):', block.content?.substring(0, 50));
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
                    // Check if URL is part of a sentence - if so, skip highlighting
                    // URLs that are part of sentences like "summarize {url}" should NOT be highlighted
                    // Only standalone URLs should be highlighted
                    const url = block.content;
                    let urlStartPos: number;
                    
                    if (typeof (block as any).tokenStartCol === 'number') {
                        urlStartPos = startLineOffset + (block as any).tokenStartCol;
                    } else {
                        const startIndex = text.indexOf(url, startLineOffset);
                        if (startIndex === -1) continue; // URL not found, skip
                        urlStartPos = startIndex;
                    }
                    
                    // Check if URL is standalone (not part of a sentence)
                    const textBeforeUrl = text.substring(0, urlStartPos);
                    const trimmedBeforeUrl = textBeforeUrl.trim();
                    
                    // Check if the text before the URL is just another URL (for handling multiple URLs pasted together)
                    const urlRegexBefore = /https?:\/\/[^\s]+$/;
                    const textBeforeTrimmed = textBeforeUrl.trimEnd();
                    const isAfterAnotherUrl = urlRegexBefore.test(textBeforeTrimmed);
                    
                    // A URL is standalone if:
                    // 1. There's no non-whitespace content before it (at start or after only whitespace)
                    // 2. It's after a newline
                    // 3. It's after another URL (for multiple URLs pasted together)
                    const isStandaloneUrl = trimmedBeforeUrl.length === 0 || textBeforeUrl.endsWith('\n') || isAfterAnotherUrl;
                    
                    // Only highlight standalone URLs - skip URLs that are part of sentences
                    if (!isStandaloneUrl) {
                        console.debug('[MessageInput] Skipping URL highlight - URL is part of a sentence:', {
                            url: url.substring(0, 50),
                            textBeforeUrl: textBeforeUrl.substring(Math.max(0, textBeforeUrl.length - 30))
                        });
                        continue;
                    }
                    
                    // Use precise character positions when available (preferred)
                    if (typeof (block as any).tokenStartCol === 'number' && typeof (block as any).tokenEndCol === 'number') {
                        const tokenStartCol = (block as any).tokenStartCol as number;
                        const tokenEndCol = (block as any).tokenEndCol as number;
                        const from = clampToDoc(startLineOffset + tokenStartCol + 1);
                        const to = clampToDoc(startLineOffset + tokenEndCol + 1);
                        if (from < to) {
                            decorations.push({ from, to, className, type: block.type });
                        }
                    } else {
                        // Fallback to indexOf method for backwards compatibility
                        const startIndex = text.indexOf(url, startLineOffset);
                        if (startIndex !== -1) {
                            const endIndex = startIndex + url.length;
                            const from = clampToDoc(startIndex + 1);
                            const to = clampToDoc(endIndex + 1);
                            if (from < to) {
                                decorations.push({ from, to, className, type: block.type });
                            }
                        }
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

            const tipTapDecorations = decorations.map(dec => {
                // For URLs/videos, use inclusiveEnd: false to prevent highlighting beyond the URL
                // For other block types, use inclusiveEnd: true to include the end position
                const isUrlOrVideo = dec.type === 'url' || dec.type === 'video';
                return Decoration.inline(dec.from, dec.to, {
                    class: dec.className,
                    'data-block-type': dec.type
                }, {
                    inclusiveStart: false,
                    inclusiveEnd: !isUrlOrVideo // URLs/videos: false, others: true
                });
            });

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

    /**
     * Update embed group layouts based on container width
     * Applies container-mobile class to web-website-preview-group elements when narrow
     * (< 450px = mobile override, >= 450px = default desktop layout)
     */
    function updateEmbedGroupLayouts() {
        if (!editorElement) return;
        
        try {
            const websiteGroups = editorElement.querySelectorAll('.web-website-preview-group');
            
            websiteGroups.forEach((group: Element) => {
                const scrollContainer = group.querySelector('.group-scroll-container') as HTMLElement;
                if (!scrollContainer) return;
                
                const containerWidth = scrollContainer.offsetWidth;
                const isMobile = containerWidth < 450;
                
                console.debug('[MessageInput] Updating embed group layout:', {
                    containerWidth,
                    isMobile,
                    threshold: 450
                });
                
                // Apply mobile class only when container is narrow
                // Desktop is the default layout (no class needed)
                if (isMobile) {
                    group.classList.add('container-mobile');
                } else {
                    group.classList.remove('container-mobile');
                }
            });
        } catch (error) {
            console.error('[MessageInput] Error updating embed group layouts:', error);
        }
    }

    /**
     * Setup ResizeObserver for embed groups to handle dynamic width changes
     */
    function setupEmbedGroupResizeObserver() {
        if (embedGroupResizeObserver) {
            embedGroupResizeObserver.disconnect();
        }
        
        embedGroupResizeObserver = new ResizeObserver((entries) => {
            // Debounce the layout updates to avoid excessive recalculations
            clearTimeout(layoutUpdateTimeout);
            layoutUpdateTimeout = setTimeout(() => {
                updateEmbedGroupLayouts();
            }, 50);
        });
        
        // Observe all existing group scroll containers
        observeEmbedGroupContainers();
    }
    
    /**
     * Observe embed group containers for resize changes
     */
    function observeEmbedGroupContainers() {
        if (!editorElement || !embedGroupResizeObserver) return;
        
        try {
            const scrollContainers = editorElement.querySelectorAll('.web-website-preview-group .group-scroll-container');
            
            scrollContainers.forEach((container) => {
                embedGroupResizeObserver.observe(container as HTMLElement);
            });
            
            console.debug('[MessageInput] Observing', scrollContainers.length, 'embed group containers for resize');
        } catch (error) {
            console.error('[MessageInput] Error setting up embed group observers:', error);
        }
    }
    
    // Debounce timeout for layout updates
    let layoutUpdateTimeout: NodeJS.Timeout;
 
    // --- Lifecycle ---
    let languageChangeHandler: () => void;
    let resizeObserver: ResizeObserver;
    let embedGroupResizeObserver: ResizeObserver;
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
            editorProps: {
                // Handle paste events at the ProseMirror level to intercept before default handling
                handlePaste: (view, event, slice) => {
                    const text = event.clipboardData?.getData('text/plain');
                    
                    if (text) {
                        // Check for chat YAML with embedded link (highest priority)
                        const chatLink = extractChatLinkFromYAML(text);
                        if (chatLink) {
                            // We found a chat link in YAML format
                            // Insert just the link and return true to prevent default handling
                            event.preventDefault();
                            event.stopPropagation();
                            editor.commands.insertContent(chatLink + ' ');
                            console.debug('[MessageInput] Pasted chat link from YAML (via editorProps):', chatLink);
                            return true; // Prevent default paste handling
                        }
                        
                        // Check for multi-line text - convert to markdown code embed for readability
                        // This ensures pasted logs, errors, code snippets, etc. are formatted as code blocks
                        const isMultiLine = text.includes('\n');
                        const isAlreadyCodeBlock = text.trim().startsWith('```');
                        
                        if (isMultiLine && !isAlreadyCodeBlock) {
                            event.preventDefault();
                            event.stopPropagation();
                            
                            // Wrap in markdown code block for preview rendering
                            const markdownBlock = `\`\`\`markdown\n${text}\n\`\`\``;
                            
                            // CRITICAL: Update originalMarkdown directly with the code block
                            // This ensures the unified parser sees the proper markdown syntax
                            // TipTap's insertContent doesn't preserve code fence structure
                            const currentMarkdown = originalMarkdown || '';
                            originalMarkdown = currentMarkdown + (currentMarkdown ? '\n' : '') + markdownBlock;
                            
                            // Parse and render the updated markdown with embeds
                            const parsedDoc = parse_message(originalMarkdown, 'write', { 
                                unifiedParsingEnabled: true 
                            });
                            
                            if (parsedDoc && parsedDoc.content) {
                                isConvertingEmbeds = true;
                                try {
                                    editor.chain().setContent(parsedDoc, { emitUpdate: false }).run();
                                    // Move cursor to end after inserting
                                    editor.commands.focus('end');
                                } finally {
                                    isConvertingEmbeds = false;
                                }
                            }
                            
                            console.debug('[MessageInput] Converted multi-line paste to markdown code embed:', {
                                lineCount: text.split('\n').length,
                                charCount: text.length,
                                originalMarkdownLength: originalMarkdown.length
                            });
                            return true; // Prevent default paste handling
                        }
                    }
                    
                    // Check for files (images, etc.) - let the DOM event listener handle it
                    const items = event.clipboardData?.items;
                    if (items) {
                        for (let i = 0; i < items.length; i++) {
                            const item = items[i];
                            if (item.type.startsWith('image/') || item.kind === 'file') {
                                // Files present - let the DOM event listener handle it
                                return false;
                            }
                        }
                    }
                    
                    // No special handling needed - allow default paste
                    return false;
                }
            }
        });

        // Explicitly blur the editor on mount to prevent auto-focus on page load
        // This ensures the editor doesn't automatically get focus when the page loads
        editor.commands.blur();
        console.debug('[MessageInput] Blurred editor on mount to prevent auto-focus');

        initializeDraftService(editor);
        hasContent = !isContentEmptyExceptMention(editor);

        setupEventListeners();

        resizeObserver = new ResizeObserver(handleResize);
        if (scrollableContent) resizeObserver.observe(scrollableContent);

        // Setup embed group layout observers
        setupEmbedGroupResizeObserver();

        // Initial height calculation (immediate)
        updateHeight();
        
        // Aggressively prevent auto-focus during initial mount phase
        // TipTap or the browser might try to focus the editor multiple times
        const preventAutoFocus = () => {
            if (editor && !editor.isDestroyed && editor.isFocused && isInitialMount) {
                editor.commands.blur();
                console.debug('[MessageInput] Prevented auto-focus during initial mount');
            }
        };
        
        // Try to blur immediately
        preventAutoFocus();
        
        tick().then(() => {
            updateHeight(); // Update again after tick
            updateEmbedGroupLayouts(); // Initial layout check
            preventAutoFocus(); // Blur again after tick
        });
        
        // Force height update after a short delay to ensure proper rendering
        setTimeout(() => {
            updateHeight();
            preventAutoFocus(); // Blur again after short delay
        }, 100);
        
        // Mark mount as complete after a longer delay to allow all async operations to finish
        // This ensures we don't prevent legitimate user-initiated focus after page load
        mountCompleteTimeout = setTimeout(() => {
            isInitialMount = false;
            console.debug('[MessageInput] Initial mount phase complete - focus prevention disabled');
        }, 500);

        // AI Task related updates
        updateActiveAITaskStatus(); // Initial check
        chatSyncService.addEventListener('aiTaskInitiated', handleAiTaskOrChatChange);
        chatSyncService.addEventListener('aiTaskEnded', handleAiTaskEnded as EventListener);
        chatSyncService.addEventListener('messageQueued', handleMessageQueued as EventListener);
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
        // Prevent auto-focus during initial mount phase
        // Only allow focus if it's user-initiated (not during initial mount)
        if (isInitialMount) {
            console.debug('[MessageInput] Blocking auto-focus during initial mount phase');
            editor.commands.blur();
            return; // Exit early to prevent focus during mount
        }
        
        // Cancel any pending blur timeout - focus was regained
        if (blurTimeoutId) {
            clearTimeout(blurTimeoutId);
            blurTimeoutId = null;
            console.debug('[MessageInput] Cancelled pending blur timeout - focus regained');
        }
        
        isMessageFieldFocused = true;
        isFocused = true; // Update bindable prop for parent components
        if (editor.isEmpty) {
            editor.commands.setContent(getInitialContent(), { emitUpdate: false });
            editor.commands.focus('end');
        }
        
        // Re-check mention trigger when focus is regained
        // This ensures the dropdown reappears if cursor is right after '@'
        checkMentionTrigger(editor);
    }

    function handleEditorBlur({ editor }: { editor: Editor }) {
        // Cancel any existing blur timeout before creating a new one
        if (blurTimeoutId) {
            clearTimeout(blurTimeoutId);
            blurTimeoutId = null;
        }
        
        // Use a small delay before updating focus state to avoid false blurs
        // This prevents suggestions from disappearing when clicking on the editor
        // or when clicking on UI elements that should maintain focus
        blurTimeoutId = setTimeout(() => {
            blurTimeoutId = null; // Clear the timeout ID
            // Check if editor is still actually blurred (not refocused)
            // This prevents race conditions where focus is regained quickly
            if (editor && !editor.isDestroyed && !editor.isFocused && !isMenuInteraction) {
                isMessageFieldFocused = false;
                isFocused = false; // Update bindable prop for parent components
                
                // Close the mention dropdown when editor loses focus
                // It will reopen when focus is regained if cursor is after '@'
                showMentionDropdown = false;
                mentionQuery = '';
                
                flushSaveDraft();
                // Only reset to initial content if the editor is TRULY empty (no content at all)
                // Do NOT reset if it contains mentions - those are valid draft content
                // that should be preserved even though they can't be sent alone
                if (editor.isEmpty) {
                    editor.commands.setContent(getInitialContent());
                    hasContent = false;
                }
            } else if (isMenuInteraction) {
                // If it's a menu interaction, don't update focus state
                return;
            }
        }, 150); // Slightly longer delay to allow for quick focus regains
    }

    /**
     * Check for @ mention trigger and update the dropdown state.
     * Shows the mention dropdown when user types @ at start of word.
     */
    function checkMentionTrigger(editor: Editor) {
        const { from } = editor.state.selection;

        // Get text from document start to cursor position using ProseMirror's textBetween
        // This properly handles the document structure and gives us the actual character position
        const textBeforeCursor = editor.state.doc.textBetween(0, from, '\n');

        // Extract the query after @ if we're in mention mode
        // Pass full length as cursor position since we only have text up to cursor
        const query = extractMentionQuery(textBeforeCursor, textBeforeCursor.length);

        if (query !== null) {
            // We're in mention mode - show dropdown
            mentionQuery = query;

            // Calculate dropdown position based on cursor/caret
            // The dropdown is OUTSIDE .message-field but INSIDE .message-input-wrapper
            // Position it at the top of the wrapper (above the entire message field)
            // The dropdown is horizontally centered via CSS transform
            if (messageInputWrapper) {
                const wrapperRect = messageInputWrapper.getBoundingClientRect();
                // Position dropdown at the top of the wrapper + small gap
                // Since we use bottom positioning and the dropdown is in the wrapper,
                // bottom: wrapperHeight + gap positions it above the wrapper
                mentionDropdownY = wrapperRect.height + 8;
            }

            showMentionDropdown = true;
        } else {
            // Not in mention mode - hide dropdown
            showMentionDropdown = false;
            mentionQuery = '';
        }
    }

    /**
     * Handle selection of a mention result from the dropdown.
     * Replaces the @query with a styled mention node (for models) or mention syntax (for others).
     */
    function handleMentionSelectCallback(result: AnyMentionResult) {
        if (!editor) return;

        const { from } = editor.state.selection;

        // Calculate the range to replace (from @ to cursor)
        // IMPORTANT: textBetween gives us a string, but deleteRange expects document positions.
        // We need to get text ONLY up to cursor position, then find @ in that substring.
        // The string length will match the character offset from start of content.
        const textBeforeCursor = editor.state.doc.textBetween(0, from, '\n');
        const atIndexInText = textBeforeCursor.lastIndexOf('@');

        console.info('[MentionSelect] DEBUG: Starting mention selection', {
            resultType: result.type,
            resultId: result.id,
            from,
            textBeforeCursor,
            atIndexInText
        });

        if (atIndexInText === -1) {
            console.warn('[MentionSelect] DEBUG: @ not found in text before cursor!');
            return;
        }

        // Calculate the actual document position of the @ character
        // The cursor is at 'from', and we typed (textBeforeCursor.length - atIndexInText) chars including @
        // So @ is at: from - (textBeforeCursor.length - atIndexInText)
        const charsAfterAt = textBeforeCursor.length - atIndexInText;
        const atDocPosition = from - charsAfterAt;

        console.info('[MentionSelect] DEBUG: Calculated positions', {
            charsAfterAt,
            atDocPosition,
            deleteRange: { from: atDocPosition, to: from }
        });

        // Insert the appropriate content based on result type
        // CRITICAL: Combine deleteRange and insert into a SINGLE chain to preserve cursor position
        if (result.type === 'model') {
            // Use the custom AI model mention node for visual display
            // Shows hyphenated name (e.g., "Claude-4.5-Opus") but serializes to @ai-model:id
            editor
                .chain()
                .focus()
                .deleteRange({ from: atDocPosition, to: from })
                .setAIModelMention({
                    modelId: result.id,
                    displayName: result.mentionDisplayName
                })
                .insertContent(' ')
                .run();
            
            // Debug: Log the editor state after insertion
            console.info('[MentionSelect] DEBUG: After model insertion, editor JSON:', 
                JSON.stringify(editor.getJSON(), null, 2)
            );
        } else if (result.type === 'mate') {
            // Use the mate node which shows @Name with gradient color
            // Shows @Sophia but serializes to @mate:id
            const mateResult = result as MateMentionResult;
            editor
                .chain()
                .focus()
                .deleteRange({ from: atDocPosition, to: from })
                .setMate({
                    name: mateResult.id, // mate id like "software_development"
                    displayName: mateResult.mentionDisplayName, // e.g., "Sophia"
                    id: crypto.randomUUID(),
                    colorStart: mateResult.colorStart,
                    colorEnd: mateResult.colorEnd
                })
                .insertContent(' ')
                .run();
        } else {
            // Use generic mention node for skills, focus modes, and settings/memories
            // Shows @Code-Get-Docs, @Web-Research, @Code-Projects but serializes to backend syntax
            // Extract color gradient for the app-specific styling
            const genericResult = result as import('./services/mentionSearchService').SkillMentionResult | import('./services/mentionSearchService').FocusModeMentionResult | import('./services/mentionSearchService').SettingsMemoryMentionResult;
            editor
                .chain()
                .focus()
                .deleteRange({ from: atDocPosition, to: from })
                .setGenericMention({
                    mentionType: result.type as 'skill' | 'focus_mode' | 'settings_memory',
                    displayName: result.mentionDisplayName,
                    mentionSyntax: result.mentionSyntax,
                    colorStart: genericResult.colorStart,
                    colorEnd: genericResult.colorEnd
                })
                .insertContent(' ')
                .run();
        }

        // Close dropdown
        showMentionDropdown = false;
        mentionQuery = '';
    }

    /**
     * Handle closing the mention dropdown.
     */
    function handleMentionClose() {
        showMentionDropdown = false;
        mentionQuery = '';
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
        
        // NOTE: Code block detection is handled SERVER-SIDE when message is sent
        // Client keeps raw markdown with code blocks - no client-side embed creation
        
        // Always trigger save/delete operation - the draft service handles both scenarios
        triggerSaveDraft(currentChatId);

        // Use unified parser for write mode
        handleUnifiedParsing(editor);

        // Dispatch live text change event so parent components can react on each keystroke
        // This enables precise, character-by-character search in new chat suggestions
        try {
            const liveText = editor.getText();
            console.debug('[MessageInput] Dispatching textchange event:', { text: liveText, length: liveText.length });
            dispatch('textchange', { text: liveText });
        } catch (err) {
            console.error('[MessageInput] Failed to dispatch textchange event:', err);
        }

        // Check for @ mention trigger and update dropdown state
        checkMentionTrigger(editor);

        tick().then(() => {
            checkScrollable();
            updateHeight();
            updateEmbedGroupLayouts(); // Update embed group layouts when content changes
            observeEmbedGroupContainers(); // Re-observe any new embed groups
        });
    }

    // --- Event Listener Setup & Cleanup ---
    function setupEventListeners() {
        document.addEventListener('embedclick', handleEmbedClick as EventListener);
        document.addEventListener('mateclick', handleMateClick as EventListener);
        editorElement?.addEventListener('paste', handlePaste);
        editorElement?.addEventListener('custom-send-message', handleSendMessage as EventListener);
        editorElement?.addEventListener('custom-sign-up-click', handleSignUpClick as EventListener); // Handle Enter key for unauthenticated users
        editorElement?.addEventListener('keydown', handleKeyDown);
        editorElement?.addEventListener('codefullscreen', handleCodeFullscreen as EventListener);
        window.addEventListener('saveDraftBeforeSwitch', flushSaveDraft);
        window.addEventListener('beforeunload', handleBeforeUnload);
        window.addEventListener('focusInput', handleFocusInput as EventListener);
        document.addEventListener('visibilitychange', handleVisibilityChange);
        document.addEventListener('embed-group-backspace', handleEmbedGroupBackspace as EventListener);
        messageInputWrapper?.addEventListener('mousedown', handleMessageWrapperMouseDown);
        // Handler for language change - updates placeholder text when language switches
        languageChangeHandler = () => {
            if (editor && !editor.isDestroyed) {
                // Use a small delay to ensure translations are fully loaded
                // The language-changed event is dispatched after waitLocale() completes,
                // but we add a small delay to ensure the text store has the new translations
                setTimeout(() => {
                    if (editor && !editor.isDestroyed) {
                        // Force the placeholder to update by triggering a view update
                        // The placeholder extension uses the reactive text store which will have the new language
                        const { state, view } = editor;
                        
                        // Create a transaction that doesn't change content but forces a view update
                        // This will cause the placeholder extension to re-evaluate its placeholder function
                        const tr = state.tr;
                        view.dispatch(tr);
                        
                        // Also update the placeholder attribute directly if the editor is empty
                        // This ensures the placeholder text is immediately visible in the new language
                        if (isContentEmptyExceptMention(editor)) {
                            // Get the current placeholder text using the text store
                            const key = (typeof window !== 'undefined' && 
                                        (('ontouchstart' in window) || navigator.maxTouchPoints > 0)) ?
                                'enter_message.placeholder.touch.text' :
                                'enter_message.placeholder.desktop.text';
                            const newPlaceholderText = $text(key);
                            
                            // Update the placeholder data attribute on the editor element
                            // TipTap's placeholder extension uses this attribute for display
                            const editorDom = editor.view.dom;
                            if (editorDom) {
                                const placeholderElement = editorDom.querySelector('p.is-editor-empty');
                                if (placeholderElement) {
                                    placeholderElement.setAttribute('data-placeholder', newPlaceholderText);
                                }
                            }
                            
                            console.debug('[MessageInput] Updated placeholder text after language change:', newPlaceholderText);
                        }
                    }
                }, 50); // Small delay to ensure translations are loaded
            }
        };
        
        // Listen to both language-changed and language-changed-complete events
        // language-changed-complete is dispatched after a short delay to ensure all components have updated
        window.addEventListener('language-changed', languageChangeHandler);
        window.addEventListener('language-changed-complete', languageChangeHandler);
    }

    function cleanup() {
        resizeObserver?.disconnect();
        embedGroupResizeObserver?.disconnect();
        clearTimeout(layoutUpdateTimeout);
        // Clear any pending blur timeout
        if (blurTimeoutId) {
            clearTimeout(blurTimeoutId);
            blurTimeoutId = null;
        }
        // Clear mount complete timeout
        if (mountCompleteTimeout) {
            clearTimeout(mountCompleteTimeout);
            mountCompleteTimeout = null;
        }
        document.removeEventListener('embedclick', handleEmbedClick as EventListener);
        document.removeEventListener('mateclick', handleMateClick as EventListener);
        editorElement?.removeEventListener('paste', handlePaste);
        editorElement?.removeEventListener('custom-send-message', handleSendMessage as EventListener);
        editorElement?.removeEventListener('custom-sign-up-click', handleSignUpClick as EventListener);
        editorElement?.removeEventListener('keydown', handleKeyDown);
        editorElement?.removeEventListener('codefullscreen', handleCodeFullscreen as EventListener);
        window.removeEventListener('saveDraftBeforeSwitch', flushSaveDraft);
        window.removeEventListener('beforeunload', handleBeforeUnload);
        window.removeEventListener('focusInput', handleFocusInput as EventListener);
        document.removeEventListener('visibilitychange', handleVisibilityChange);
        document.removeEventListener('embed-group-backspace', handleEmbedGroupBackspace as EventListener);
        messageInputWrapper?.removeEventListener('mousedown', handleMessageWrapperMouseDown);
        window.removeEventListener('language-changed', languageChangeHandler);
        window.removeEventListener('language-changed-complete', languageChangeHandler);
        chatSyncService.removeEventListener('aiTaskInitiated', handleAiTaskOrChatChange);
        chatSyncService.removeEventListener('aiTaskEnded', handleAiTaskEnded as EventListener);
        chatSyncService.removeEventListener('messageQueued', handleMessageQueued as EventListener);
        cleanupDraftService();
        if (editor && !editor.isDestroyed) editor.destroy();
        handleStopRecordingCleanup();
    }

    // --- AI Task Status Update ---
    function updateActiveAITaskStatus() {
        if (currentChatId && chatSyncService) {
            const taskId = chatSyncService.getActiveAITaskIdForChat(currentChatId);
            console.debug('[MessageInput] updateActiveAITaskStatus:', {
                currentChatId,
                taskId,
                previousTaskId: activeAITaskId,
                allActiveTasks: Array.from(chatSyncService.activeAITasks.entries())
            });
            activeAITaskId = taskId;

            // If we now have a task id, clear optimistic pending state
            if (taskId) {
                awaitingAITaskStart = false;
                cancelRequestedWhileAwaiting = false;
                if (awaitingAITaskTimeoutId) {
                    clearTimeout(awaitingAITaskTimeoutId);
                    awaitingAITaskTimeoutId = null;
                }
            }
        } else {
            console.debug('[MessageInput] updateActiveAITaskStatus: No chatId or chatSyncService', {
                currentChatId,
                hasChatSyncService: !!chatSyncService
            });
            activeAITaskId = null;
            awaitingAITaskStart = false;
            cancelRequestedWhileAwaiting = false;
            if (awaitingAITaskTimeoutId) {
                clearTimeout(awaitingAITaskTimeoutId);
                awaitingAITaskTimeoutId = null;
            }
        }
    }

    function handleAiTaskOrChatChange() {
        console.debug('[MessageInput] handleAiTaskOrChatChange called');
        updateActiveAITaskStatus();

        // If the user clicked stop before we had a task id, cancel as soon as it's known
        if (cancelRequestedWhileAwaiting && activeAITaskId) {
            const taskId = activeAITaskId;
            console.info('[MessageInput] Cancelling AI task that started after user requested stop:', taskId);
            // Clear UI immediately
            cancelRequestedWhileAwaiting = false;
            awaitingAITaskStart = false;
            activeAITaskId = null;
            void chatSyncService.sendCancelAiTask(taskId);
        }
    }

    /**
     * Handle AI task ended event - fade out stop button when task completes
     */
    function handleAiTaskEnded(event: CustomEvent) {
        const { chatId, taskId } = event.detail;
        console.debug('[MessageInput] handleAiTaskEnded received:', {
            chatId,
            taskId,
            currentChatId,
            matches: chatId === currentChatId
        });
        // Only update if this is for the current chat
        if (chatId === currentChatId) {
            console.debug('[MessageInput] AI task ended for current chat, updating UI');
            updateActiveAITaskStatus();
            // Clear queued message text when task ends
            queuedMessageText = null;
        }
    }

    /**
     * Handle AI task cancellation with optimistic UI updates.
     * Immediately hides the stop button and clears typing indicator for instant feedback,
     * then sends the cancellation request to the backend.
     */
    async function handleCancelAITask() {
        // If the task isn't known yet, still allow immediate UX: hide button and cancel as soon as task starts
        if (!activeAITaskId && awaitingAITaskStart) {
            console.info('[MessageInput] Stop clicked before task id is known; will cancel as soon as task starts');
            cancelRequestedWhileAwaiting = true;
            awaitingAITaskStart = false; // Hide button immediately
            if (awaitingAITaskTimeoutId) {
                clearTimeout(awaitingAITaskTimeoutId);
                awaitingAITaskTimeoutId = null;
            }
            return;
        }

        if (activeAITaskId && currentChatId) {
            const taskId = activeAITaskId;
            console.info(`[MessageInput] Requesting cancellation for AI task: ${taskId}`);
            
            // Optimistic UI update: immediately hide the stop button
            // This provides instant feedback before backend confirmation
            activeAITaskId = null;
            
            // Optimistic state update: clear activeAITasks Map to prevent new messages from being queued
            // This ensures the frontend state matches what we're trying to do (cancel the task)
            if (chatSyncService && currentChatId) {
                const taskInfo = (chatSyncService as any).activeAITasks.get(currentChatId);
                if (taskInfo && taskInfo.taskId === taskId) {
                    (chatSyncService as any).activeAITasks.delete(currentChatId);
                    console.debug('[MessageInput] Optimistically cleared activeAITasks entry on cancel');
                }
            }
            
            // Optimistic UI update: immediately clear typing indicator
            // Use clearTypingForChat since we only have taskId, not message_id
            // (aiMessageId in the store is set to message_id, not task_id)
            if (currentTypingStatus?.isTyping && 
                currentTypingStatus.chatId === currentChatId) {
                console.debug('[MessageInput] Optimistically clearing typing indicator on cancel for chat', currentChatId);
                aiTypingStore.clearTypingForChat(currentChatId);
            }
            
            // Clear any queued message text
            queuedMessageText = null;
            
            // Send cancellation request to backend
            // The backend will confirm via 'aiTaskEnded' event, which will trigger final cleanup
            await chatSyncService.sendCancelAiTask(taskId);
        }
    }
    
    /**
     * Handle message queued event - shows message in MessageInput instead of notification
     */
    function handleMessageQueued(event: CustomEvent) {
        const { chat_id, message, active_task_id } = event.detail;
        
        // Only show if this is for the current chat
        if (chat_id === currentChatId) {
            console.debug('[MessageInput] Message queued for current chat:', {
                chatId: chat_id,
                activeTaskId: active_task_id,
                message
            });
            
            // Show the queued message text in the UI
            queuedMessageText = message || $text('enter_message.message_queued.text') || 'Press enter again to stop previous response';
            
            // Auto-hide after 7 seconds
            setTimeout(() => {
                queuedMessageText = null;
            }, 7000);
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
        await handleFilePaste(event, editor);
        tick().then(() => {
            hasContent = !isContentEmptyExceptMention(editor);
            updateEmbedGroupLayouts();
            observeEmbedGroupContainers();
        });
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
     * Handle backspace when trying to delete json_embed code blocks (website previews)
     * Should revert the json_embed code block back to the original URL
     */
    function handleJsonCodeBlockBackspace(event: KeyboardEvent) {
        if (!editor) return;
        
        const { from, to } = editor.state.selection;
        
        // Check for json_embed blocks first (new format)
        const textBeforeCursor = editor.state.doc.textBetween(Math.max(0, from - 300), from);
        let jsonEmbedBlockMatch = textBeforeCursor.match(/```json_embed\n([\s\S]*?)\n```$/);
        
        if (jsonEmbedBlockMatch) {
            try {
                const jsonContent = jsonEmbedBlockMatch[1];
                const parsed = JSON.parse(jsonContent);
                
                if (parsed.type === 'website' && parsed.url) {
                    event.preventDefault();
                    
                    // Find the position of the json_embed code block in the original markdown
                    // Use a more robust approach that handles multiple occurrences
                    const fullJsonEmbedBlock = jsonEmbedBlockMatch[0];
                    
                    // Find all occurrences of this json_embed block
                    const allMatches = [];
                    const regex = new RegExp(fullJsonEmbedBlock.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g');
                    let match;
                    while ((match = regex.exec(originalMarkdown)) !== null) {
                        allMatches.push({
                            index: match.index,
                            length: match[0].length
                        });
                    }
                    
                    // For multiple matches, we need to identify which one we're editing
                    // Use the cursor position to find the closest match
                    const editorText = editor.getText();
                    const cursorTextPos = editorText.substring(0, from).length;
                    
                    let closestMatch = null;
                    let closestDistance = Infinity;
                    
                    for (const match of allMatches) {
                        const distance = Math.abs(match.index - cursorTextPos);
                        if (distance < closestDistance) {
                            closestDistance = distance;
                            closestMatch = match;
                        }
                    }
                    
                    if (closestMatch) {
                        // Replace the closest json_embed code block with original URL in markdown
                        const beforeJson = originalMarkdown.substring(0, closestMatch.index);
                        const afterJson = originalMarkdown.substring(closestMatch.index + closestMatch.length);
                        originalMarkdown = beforeJson + parsed.url + afterJson;
                        
                        // Update editor to reflect the change
                        updateEditorFromMarkdown(editor, originalMarkdown);
                        
                        console.info('[MessageInput] Reverted json_embed code block to URL:', parsed.url);
                    }
                    return;
                }
            } catch (error) {
                console.debug('[MessageInput] Not a valid json_embed block, using default backspace');
            }
        }
    }
    function handleCodeFullscreen(event: CustomEvent) { dispatch('codefullscreen', event.detail); }
    function handleBeforeUnload() { if (hasContent) flushSaveDraft(); }
    function handleVisibilityChange() { if (document.visibilityState === 'hidden' && hasContent) flushSaveDraft(); }
    function handleResize() { checkScrollable(); updateHeight(); }
    
    /**
     * Handle embed group backspace events to prevent immediate re-grouping
     */
    function handleEmbedGroupBackspace(event: CustomEvent) {
        console.debug('[MessageInput] Embed group backspace event received:', event.detail);
        isBackspaceOperation = true;
    }

    /**
     * Prevent blur when clicking on UI elements within the message input wrapper
     * This allows users to click on action buttons and other controls without losing focus
     * Also ensures clicks on the editor itself maintain focus properly
     */
    function handleMessageWrapperMouseDown(event: MouseEvent) {
        const target = event.target as HTMLElement;
        
        // Allow blur for interactive elements like buttons (outside suggestions)
        // But check if it's a suggestion button - those should maintain editor focus
        const isSuggestionButton = target.closest('.suggestion-item');
        if ((target.closest('button') || target.closest('[role="button"]')) && !isSuggestionButton) {
            console.debug('[MessageInput] Click on button detected, allowing default behavior');
            return;
        }
        
        // If clicking on the editor itself, ensure it gets focus
        if (editor?.view.dom.contains(target)) {
            // Click is on the editor - ensure it's focused
            // Use a small delay to ensure the focus event fires after any potential blur
            setTimeout(() => {
                if (editor && !editor.isDestroyed && !editor.isFocused) {
                    editor.commands.focus('end');
                    console.debug('[MessageInput] Ensuring editor focus after click on editor');
                }
            }, 10);
            return;
        }
        
        // Check if click is within the message-input-wrapper but outside editor
        if (messageInputWrapper?.contains(target) && !editor?.view.dom.contains(target)) {
            // This is a click on the wrapper UI (action buttons area, etc.)
            // Keep the editor focused by preventing default blur
            event.preventDefault();
            console.debug('[MessageInput] Click on wrapper UI detected, keeping editor focused');
            
            // Re-focus the editor
            if (editor && !editor.isDestroyed) {
                editor.commands.focus('end');
            }
        }
    }

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
        await handleFileDrop(event, editorElement, editor);
        tick().then(() => {
            hasContent = !isContentEmptyExceptMention(editor);
            updateEmbedGroupLayouts();
            observeEmbedGroupContainers();
        });
    }
    function handleDragOver(event: DragEvent) { handleFileDragOver(event, editorElement); }
    function handleDragLeave(event: DragEvent) { handleFileDragLeave(event, editorElement); }
    async function onFileSelected(event: Event) {
        await handleFileSelectedEvent(event, editor);
        tick().then(() => {
            hasContent = !isContentEmptyExceptMention(editor);
            updateEmbedGroupLayouts();
            observeEmbedGroupContainers();
        });
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
        // Optimistically show stop button immediately after sending
        awaitingAITaskStart = true;
        cancelRequestedWhileAwaiting = false;
        if (awaitingAITaskTimeoutId) {
            clearTimeout(awaitingAITaskTimeoutId);
        }
        // If the backend never starts a task (e.g., network issues), don't leave stop button stuck
        awaitingAITaskTimeoutId = setTimeout(() => {
            if (awaitingAITaskStart && !activeAITaskId) {
                console.warn('[MessageInput] Timed out waiting for AI task to start; hiding stop button');
                awaitingAITaskStart = false;
                cancelRequestedWhileAwaiting = false;
            }
            awaitingAITaskTimeoutId = null;
        }, 15000);

        void handleSend(
            editor,
            dispatch,
            (value) => (hasContent = value),
            currentChatId
        );
    }

    /**
     * Handle "Sign up" button click for non-authenticated users
     * Saves the current draft message to sessionStorage so it can be restored after signup
     * Clears the editor content after saving to prevent search in new chat suggestions
     */
    async function handleSignUpClick() {
        if (!editor || editor.isDestroyed) {
            console.warn('[MessageInput] Cannot save draft for sign-up - editor not available');
            // Still open signup interface even if draft can't be saved
            window.dispatchEvent(new CustomEvent('openSignupInterface'));
            return;
        }

        // Get the current markdown content from the editor
        const editorContent = editor.getJSON();
        const markdown = tipTapToCanonicalMarkdown(editorContent);
        
        // Only save if there's actual content (not just empty or mention)
        if (markdown && markdown.trim().length > 0 && !isContentEmptyExceptMention(editor)) {
            // Save draft to sessionStorage with chat ID and markdown content
            const draftData = {
                chatId: currentChatId || 'new-chat', // Use 'new-chat' if no chat ID
                markdown: markdown,
                timestamp: Date.now()
            };
            
            try {
                sessionStorage.setItem('pendingDraftAfterSignup', JSON.stringify(draftData));
                console.debug('[MessageInput] Saved draft to sessionStorage for restoration after signup:', {
                    chatId: draftData.chatId,
                    markdownLength: markdown.length,
                    preview: markdown.substring(0, 50) + '...'
                });
            } catch (error) {
                console.error('[MessageInput] Failed to save draft to sessionStorage:', error);
            }
        }

        // Clear the editor content after saving to prevent search in new chat suggestions
        // This ensures that if the user interrupts the signup process, the field is empty
        await clearMessageField(false); // Don't focus after clearing
        originalMarkdown = ''; // Clear markdown tracking
        hasContent = false; // Update content state
        
        // Manually dispatch textchange event with empty text to clear liveInputText in ActiveChat
        // This ensures follow-up suggestions show properly when user returns from signup flow
        // The clearMessageField function uses clearContent(false) which doesn't trigger update events
        try {
            dispatch('textchange', { text: '' });
            console.debug('[MessageInput] Dispatched textchange event with empty text to clear liveInputText');
        } catch (err) {
            console.error('[MessageInput] Failed to dispatch textchange event after clearing:', err);
        }
        
        console.debug('[MessageInput] Cleared editor content after saving draft for sign-up');

        // Open the signup interface directly with alpha disclaimer
        window.dispatchEvent(new CustomEvent('openSignupInterface'));
    }

    function handleInsertSpace() {
        if (editor && !editor.isDestroyed) {
            editor.commands.insertContent(' ');
        }
    }

    /**
     * Handle Shift+Enter keyboard shortcut to focus the message input field
     * This is called from the KeyboardShortcuts component when Shift+Enter is pressed
     */
    function handleFocusInput() {
        console.debug('[MessageInput] handleFocusInput called from KeyboardShortcuts');
        
        if (!editor || editor.isDestroyed) {
            console.warn('[MessageInput] handleFocusInput: editor is not available or destroyed');
            return;
        }
        
        try {
            console.info('[MessageInput] Focusing editor due to Shift+Enter shortcut');
            editor.commands.focus('end');
            isMessageFieldFocused = true; // Update UI state
            console.debug('[MessageInput] Editor focused successfully');
        } catch (error) {
            console.error('[MessageInput] Error focusing editor:', error);
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
    export function setSuggestionText(text: string) {
        console.debug('[MessageInput] setSuggestionText called with:', text);
        console.debug('[MessageInput] editor available:', !!editor);
        console.debug('[MessageInput] editor destroyed:', editor?.isDestroyed);
        
        if (editor && !editor.isDestroyed) {
            console.debug('[MessageInput] Setting suggestion text in editor');
            editor.commands.setContent(`<p>${text}</p>`);
            hasContent = true;
            updateOriginalMarkdown(editor);
            editor.commands.focus('end');
            console.debug('[MessageInput] Suggestion text set and focused successfully');
        } else {
            console.warn('[MessageInput] setSuggestionText: editor not available or destroyed');
        }
    }
    export function getTextContent(): string {
        if (editor && !editor.isDestroyed) {
            return editor.getText();
        }
        return '';
    }
    export function setDraftContent(chatId: string | null, draftContent: any | null, version: number, shouldFocus: boolean = false) {
        // CRITICAL: setCurrentChatContext already sets the editor content (to draftContent or initial content)
        // So we don't need to clear it again if draftContent is null - that would trigger unnecessary update events
        // The setCurrentChatContext function handles setting the editor content with emitUpdate: false to prevent triggering saves
        setCurrentChatContext(chatId, draftContent, version);
        
        // Update local state based on the editor content after setCurrentChatContext
        if (editor) {
            // Always update hasContent state based on current editor content
            hasContent = !isContentEmptyExceptMention(editor);
            
            // Only update originalMarkdown if there's actual content
            // For demo chats with no draft, we don't want to set originalMarkdown
            if (draftContent !== null) {
                updateOriginalMarkdown(editor); // Update markdown tracking
            } else {
                originalMarkdown = ''; // Clear markdown tracking for chats with no draft
            }
            
            // Only focus if explicitly requested - default is false to prevent unwanted auto-focus
            // Users should manually click on the input field when they want to type
            if (shouldFocus) {
                editor.commands.focus('end');
                console.debug('[MessageInput] Focused editor after setDraftContent (explicitly requested)');
            } else {
                console.debug('[MessageInput] Skipped focus after setDraftContent (user must click to focus)');
            }
        }
    }
    /**
     * Clears the message input field.
     * @param shouldFocus - Whether to focus the editor after clearing
     * @param preserveContext - If true, preserves the current chat context (doesn't delete drafts)
     *                          Used when switching to a chat that has no draft - we just clear the editor
     *                          without deleting the previous chat's draft.
     */
    export async function clearMessageField(shouldFocus: boolean = true, preserveContext: boolean = false) {
        await clearEditorAndResetDraftState(shouldFocus, preserveContext);
        hasContent = false;
        originalMarkdown = ''; // Clear markdown tracking
    }
    export function getOriginalMarkdown(): string {
        return getOriginalMarkdownForSending();
    }
    export function setOriginalMarkdown(markdown: string) {
        originalMarkdown = markdown;
        console.debug('[MessageInput] Set original markdown from draft:', {
            length: markdown.length,
            preview: markdown.substring(0, 100)
        });
    }

    // --- Reactive Calculations using Svelte 5 runes ---
    let containerStyle = $derived(isFullscreen ? `height: calc(100vh - 100px); max-height: calc(100vh - 120px); height: calc(100dvh - 100px); max-height: calc(100dvh - 120px);` : 'height: auto; max-height: 350px;');
    let scrollableStyle = $derived(isFullscreen ? `max-height: calc(100vh - 190px); max-height: calc(100dvh - 190px);` : 'max-height: 250px;');
    
    // Convert reactive statement with side effects to $effect
    $effect(() => {
        if (isFullscreen !== undefined && messageInputWrapper) {
            tick().then(updateHeight);
        }
    });
    
    // Track when action buttons visibility changes to update height
    $effect(() => {
        if (shouldShowActionButtons !== undefined && messageInputWrapper) {
            // Wait for CSS transition to complete (300ms) then update height
            setTimeout(() => {
                tick().then(updateHeight);
            }, 350); // Slightly longer than CSS transition
        }
    });
    
    // Track previous chat ID to detect changes
    let previousChatId: string | undefined = undefined;
    
    // React to chat ID changes to save drafts when switching chats using $effect
    // CRITICAL: Save the previous chat's draft BEFORE the context switches
    // This prevents draft loss when quickly switching between chats
    $effect(() => {
        if (currentChatId !== previousChatId && previousChatId !== undefined) {
            console.debug(`[MessageInput] Chat ID changed from ${previousChatId} to ${currentChatId}, flushing draft for previous chat`);
            // CRITICAL: Flush draft for the PREVIOUS chat before switching
            // Use the previous chat ID explicitly to ensure we save the right draft
            // The draft service will use the current state's chatId, so we need to ensure it's still set
            flushSaveDraft(); // Save draft for the previous chat before switching
            // Small delay to ensure the save completes before context switch
            setTimeout(() => {
                console.debug(`[MessageInput] Draft flush completed for previous chat ${previousChatId}`);
            }, 100);
        }
        previousChatId = currentChatId;
    });
    
    // Update active AI task status when currentChatId changes using $effect
    $effect(() => {
        if (currentChatId !== undefined && chatSyncService) {
            updateActiveAITaskStatus();
        }
    });
 
</script>
 
<!-- Template -->
<div bind:this={messageInputWrapper} class="message-input-wrapper" role="none" onmousedown={handleMessageWrapperMouseDown}>
    <div
        class="message-field {isMessageFieldFocused ? 'focused' : ''} {$recordingState.isRecordingActive ? 'recording-active' : ''} {!shouldShowActionButtons ? 'compact' : ''}"
        class:drag-over={editorElement?.classList.contains('drag-over')}
        style={containerStyle}
        ondragover={handleDragOver}
        ondragleave={handleDragLeave}
        ondrop={handleDrop}
        role="textbox"
        aria-multiline="true"
        tabindex="0"
    >
        {#if isScrollable || isFullscreen}
            <button
                class="clickable-icon icon_fullscreen fullscreen-button"
                onclick={toggleFullscreen}
                aria-label={isFullscreen ? $text('enter_message.fullscreen.exit_fullscreen.text') : $text('enter_message.fullscreen.enter_fullscreen.text')}
                use:tooltip
            ></button>
        {/if}

        <input bind:this={fileInput} type="file" onchange={onFileSelected} style="display: none" multiple accept="*/*" />
        <input bind:this={cameraInput} type="file" accept="image/*,video/*" capture="environment" onchange={onFileSelected} style="display: none" />

        <div class="scrollable-content" bind:this={scrollableContent} style={scrollableStyle}>
            <div class="content-wrapper">
                <div bind:this={editorElement} class="editor-content prose"></div>
            </div>
        </div>

        {#if showCamera}
            <CameraView bind:videoElement on:close={() => showCamera = false} on:focusEditor={focus} on:photocaptured={handlePhotoCaptured} on:videorecorded={handleVideoRecorded} />
        {/if}

        <!-- Action Buttons Component -->
        {#if shouldShowActionButtons}
            <ActionButtons
                showSendButton={hasContent}
                isRecordButtonPressed={$recordingState.isRecordButtonPressed}
                showRecordHint={$recordingState.showRecordHint}
                micPermissionGranted={$recordingState.micPermissionGranted}
                isAuthenticated={$authStore.isAuthenticated}
                on:fileSelect={handleFileSelect}
                on:locationClick={handleLocationClick}
                on:cameraClick={handleCameraClick}
                on:sendMessage={handleSendMessage}
                on:signUpClick={handleSignUpClick}
                on:recordMouseDown={onRecordMouseDown}
                on:recordMouseUp={onRecordMouseUp}
                on:recordMouseLeave={onRecordMouseLeave}
                on:recordTouchStart={onRecordTouchStart}
                on:recordTouchEnd={onRecordTouchEnd}
            />
        {/if}

        <!-- Queued Message Indicator - shown when a message is queued due to active AI task -->
        {#if queuedMessageText}
            <div class="queued-message-indicator" transition:fade={{ duration: 200 }}>
                {queuedMessageText}
            </div>
        {/if}

        <!-- Stop Processing Icon - shown when AI task is active -->
        <!-- Debug: activeAITaskId = {activeAITaskId}, currentChatId = {currentChatId} -->
        {#if activeAITaskId || awaitingAITaskStart}
            <button
                class="stop-processing-button {hasContent ? 'shifted-left' : ''}"
                onclick={handleCancelAITask}
                use:tooltip
                title={$text('enter_message.stop.text')}
                aria-label={$text('enter_message.stop.text')}
                transition:fade={{ duration: 300 }}
            >
                <span class="clickable-icon icon_stop_processing"></span>
            </button>
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

    <!-- @ Mention Dropdown for AI model, mate, skill, focus mode, and settings/memories selection -->
    <!-- IMPORTANT: This must be OUTSIDE .message-field but INSIDE .message-input-wrapper -->
    <!-- .message-field has overflow:hidden which would clip the dropdown if placed inside -->
    <MentionDropdown
        bind:show={showMentionDropdown}
        query={mentionQuery}
        positionY={mentionDropdownY}
        onselect={handleMentionSelectCallback}
        onclose={handleMentionClose}
    />
</div>

<!-- Keyboard Shortcuts Listener -->
<!-- Audio recording shortcuts removed - feature not yet implemented:
     - on:startRecording
     - on:stopRecording
     - on:cancelRecording
     - on:insertSpace
-->
<KeyboardShortcuts on:focusInput={handleFocusInput} />

<style>
    @import './MessageInput.styles.css';
    @import './EmbeddPreview.styles.css';
</style>
