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
    import { pendingNotificationReplyStore } from '../../stores/pendingNotificationReplyStore';
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
    import { isDesktop } from '../../utils/platform';
    
    // URL metadata service - creates proper embeds with embed_id for LLM context
    import { createEmbedFromUrl } from './services/urlMetadataService';
    // Code embed service - creates proper embeds for pasted code/text
    import { createCodeEmbedFromPastedText, detectLanguageFromVSCode, detectLanguageFromContent } from './services/codeEmbedService';
    import { generateUUID } from '../../message_parsing/utils';

    // Handlers
    import { handleSend } from './handlers/sendHandlers';
    import MentionDropdown from './MentionDropdown.svelte';
    import {
        extractMentionQuery,
        type AnyMentionResult,
        type MateMentionResult
    } from './services/mentionSearchService';
    import {
        handleDrop as handleFileDrop,
        handleDragOver as handleFileDragOver,
        handleDragLeave as handleFileDragLeave,
        handlePaste as handleFilePaste,
        onFileSelected as handleFileSelectedEvent,
        extractChatLinkFromYAML
    } from './fileHandlers';
    import {
        // insertVideo, // Disabled: video upload not yet supported — re-enable with handleVideoRecorded
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
    
    // PII Detection
    import { detectPII, type PIIMatch, type PIIDetectionOptions, type PersonalDataForDetection } from './services/piiDetectionService';
    import PIIWarningBanner from './PIIWarningBanner.svelte';
    // Privacy settings store — controls master toggle, per-category toggles, and personal data entries
    import { personalDataStore, type PersonalDataEntry, type PIIDetectionSettings } from '../../stores/personalDataStore';
    import { get } from 'svelte/store';

    const dispatch = createEventDispatcher();

    // --- Props using Svelte 5 $props() ---
    interface Props {
        currentChatId?: string | undefined;
        isFullscreen?: boolean;
        hasContent?: boolean;
        showActionButtons?: boolean;
        isFocused?: boolean;
        /** Whether the map location selector is currently open.
         *  Bindable so the parent (ActiveChat) can hide NewChatSuggestions
         *  while the map overlay is active. */
        isMapsOpen?: boolean;
    }
    let { 
        currentChatId = undefined,
        isFullscreen = $bindable(false),
        hasContent = $bindable(false),
        showActionButtons = true,
        isFocused = $bindable(false),
        isMapsOpen = $bindable(false)
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
    // Keep the bindable isMapsOpen prop in sync with the local showMaps state so
    // the parent (ActiveChat) can react to the map overlay opening/closing.
    $effect(() => { isMapsOpen = showMaps; });
    // Tracks whether files are being dragged over the message field.
    // When true, the drop overlay ("Drop files to upload") is shown.
    let isDragging = $state(false);

    // Location precision setting — read from personalDataStore (persisted, encrypted).
    // When impreciseByDefault=true, MapsView opens in area mode (privacy-first default).
    let locationSettingsState = $state({ impreciseByDefault: true });
    personalDataStore.locationSettings.subscribe((s) => { locationSettingsState = s; });
    let defaultImprecise = $derived(locationSettingsState.impreciseByDefault);
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
    // Shows when prop is true OR when field is focused OR when recording is in progress.
    // CRITICAL: Keep action buttons visible while record button is pressed or recording
    // is active — otherwise the onmouseup/touchend handlers on the record button are
    // removed from the DOM before they can fire (because the editor blur clears
    // isMessageFieldFocused after 150ms, hiding ActionButtons mid-interaction).
    let shouldShowActionButtons = $derived(
        showActionButtons ||
        isMessageFieldFocused ||
        $recordingState.isRecordButtonPressed ||
        $recordingState.showRecordAudioUI
    );

    // Single-tap feedback: briefly highlight the inline "Press & hold to record" label
    // in ActionButtons (and force it visible even when there's text in the editor).
    // Set to true when showRecordHint fires AND mic is granted; auto-resets after 1.5s.
    let highlightPressHold = $state(false);
    let highlightTimeout: ReturnType<typeof setTimeout> | null = null;
    $effect(() => {
        // React to showRecordHint changing to true while mic is already granted
        if ($recordingState.showRecordHint && $recordingState.micPermissionState === 'granted') {
            highlightPressHold = true;
            clearTimeout(highlightTimeout ?? undefined);
            highlightTimeout = setTimeout(() => { highlightPressHold = false; }, 1500);
        }
    });

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
    
    // --- Text-change guard for handleEditorUpdate ---
    // Tracks the last text content processed by handleEditorUpdate.
    // On iOS Firefox, double-tap to select text fires spurious `input` events that
    // ProseMirror interprets as content changes, triggering TipTap's onUpdate even
    // though only the selection changed. Without this guard, each false onUpdate runs
    // heavy operations (markdown serialization, unified parsing, PII detection) and
    // dispatches empty transactions (editor.view.dispatch(state.tr)) which cause
    // further DOM mutations → more input events → an infinite feedback loop that
    // crashes performance.
    let lastEditorUpdateText = '';
    
    // --- Blur timeout tracking ---
    let blurTimeoutId: NodeJS.Timeout | null = null; // Track blur timeout to cancel it if focus is regained
    
    // --- Mobile keyboard viewport scroll fix ---
    // On iOS Safari the virtual keyboard resizes window.visualViewport but does NOT
    // reliably scroll the focused element into view, causing the message input to be
    // hidden behind the keyboard until the user taps multiple times. Android Chrome
    // handles this better natively, but edge cases exist there too (e.g. complex
    // flex layouts, PWA mode). Applying the fix universally on touch devices is safe
    // because scrollIntoView({ block: 'nearest' }) is a no-op when already visible.
    // We track the listener reference so we can clean it up on blur and on destroy.
    let viewportResizeListener: (() => void) | null = null;
    // Scroll timeout used to debounce the viewport-resize scroll callback
    let scrollIntoViewTimeout: ReturnType<typeof setTimeout> | null = null;

    /** Returns true when running on a touch-capable device (mobile / tablet). */
    function isTouchDevice(): boolean {
        if (typeof window === 'undefined' || typeof navigator === 'undefined') return false;
        return 'ontouchstart' in window || navigator.maxTouchPoints > 0;
    }

    /**
     * Scroll the message input wrapper into the visible area after the mobile
     * keyboard has animated in and resized window.visualViewport.
     * Called both from the visualViewport resize handler and as a plain timeout
     * fallback for browsers without visualViewport support.
     */
    function scrollInputIntoView() {
        if (!messageInputWrapper) return;
        try {
            messageInputWrapper.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
            console.debug('[MessageInput] Scrolled input into view after keyboard open');
        } catch {
            // Fallback for browsers that don't support options on scrollIntoView
            try { messageInputWrapper.scrollIntoView(false); } catch { /* ignore */ }
        }
    }

    /**
     * Attach the viewport-resize listener that fires once the mobile keyboard has
     * finished appearing and scrolls the input into view.
     * Only runs on touch devices; safe no-op on desktop.
     */
    function attachViewportListener() {
        if (!isTouchDevice()) return;
        detachViewportListener(); // Ensure no duplicate listeners

        if (window.visualViewport) {
            // visualViewport fires 'resize' when the keyboard appears/disappears.
            // Debounce because the event can fire multiple times during keyboard animation.
            viewportResizeListener = () => {
                if (scrollIntoViewTimeout) clearTimeout(scrollIntoViewTimeout);
                scrollIntoViewTimeout = setTimeout(scrollInputIntoView, 80);
            };
            window.visualViewport.addEventListener('resize', viewportResizeListener);
            console.debug('[MessageInput] Attached visualViewport resize listener for mobile keyboard');
        }

        // Unconditional fallback timeout — fires ~300 ms after focus (keyboard animation
        // typically completes within 250–300 ms on both iOS and Android). Covers devices
        // where visualViewport is unavailable or the resize event misfires.
        if (scrollIntoViewTimeout) clearTimeout(scrollIntoViewTimeout);
        scrollIntoViewTimeout = setTimeout(scrollInputIntoView, 320);
    }

    /**
     * Remove the viewport-resize listener and cancel any pending scroll timeout.
     */
    function detachViewportListener() {
        if (viewportResizeListener && window.visualViewport) {
            window.visualViewport.removeEventListener('resize', viewportResizeListener);
            viewportResizeListener = null;
            console.debug('[MessageInput] Detached visualViewport resize listener');
        }
        if (scrollIntoViewTimeout) {
            clearTimeout(scrollIntoViewTimeout);
            scrollIntoViewTimeout = null;
        }
    }

    // --- Initial mount tracking ---
    let isInitialMount = $state(true); // Flag to prevent auto-focus during initial mount
    let mountCompleteTimeout: NodeJS.Timeout | null = null; // Track when mount is complete
    
    // --- PII Detection State ---
    // Tracks detected PII matches for highlighting and the warning banner
    let detectedPII = $state<PIIMatch[]>([]);
    // Set of PII match IDs that user has clicked to exclude from replacement
    // These won't be replaced when sending and won't be highlighted
    let piiExclusions = $state<Set<string>>(new Set());
    // Cache of current PII Decoration objects to merge with unclosed-block decorations.
    // Stored separately so they survive when applyHighlightingColors rebuilds the decoration set.
    let currentPIIDecorations: any[] = [];
    // Cache the last text we ran PII detection on to skip redundant work
    let lastPIIText = '';
    // Debounce timer for PII detection - safety net fallback for edge cases
    let piiDebounceTimer: ReturnType<typeof setTimeout> | null = null;
    // Fallback debounce: if no delimiter is typed for this long, run detection anyway.
    // This catches edge cases like slow typing followed by an immediate send.
    const PII_DEBOUNCE_MS = 800;
    // Characters that trigger immediate PII detection (natural word/token boundaries).
    // PII patterns like emails, phone numbers, and API keys are only fully formed
    // after the user types a delimiter, so we detect at these boundaries instead of
    // running 16+ regex patterns on every single keystroke.
    const PII_TRIGGER_CHARS = new Set([' ', ',', '.', '\n', '/', ')', ']', '}', ';', ':', '\t']);
    // Flag set by paste handlers to force immediate PII detection on next editor update.
    // Paste events inject complete content (possibly containing PII) so detection should
    // not wait for a delimiter character.
    let piiPasteDetectionPending = false;
    
    // --- Heavy Parsing Debounce ---
    // handleUnifiedParsing and updateOriginalMarkdown are expensive:
    //   - updateOriginalMarkdown serializes the full TipTap document tree to markdown
    //   - handleUnifiedParsing runs the full message parser + regex URL detection + decorations
    // Running these on every keystroke is wasteful — most characters don't change
    // the parsing result. Instead, we use the same boundary-trigger pattern as PII
    // detection: run immediately on delimiter chars and paste, debounce fallback otherwise.
    let heavyParsingDebounceTimer: ReturnType<typeof setTimeout> | null = null;
    const HEAVY_PARSING_DEBOUNCE_MS = 400; // Safety-net fallback (shorter than PII since it affects UX)
    // Re-use PII_TRIGGER_CHARS for consistency — these mark natural word/token boundaries
    // where parsing results are most likely to change (e.g. URL closed by space, code fence closed)
    
    /**
     * Schedule or immediately run the heavy parsing operations.
     * Immediate on delimiter characters and paste events (content is "complete");
     * debounced fallback for regular typing.
     */
    function scheduleHeavyParsing(editor: Editor, text: string, forcedByPaste: boolean) {
        const lastChar = text.length > 0 ? text[text.length - 1] : '';
        const isDelimiter = PII_TRIGGER_CHARS.has(lastChar);
        
        if (forcedByPaste || isDelimiter) {
            // Delimiter typed or paste — content is at a natural boundary, parse now
            if (heavyParsingDebounceTimer) { clearTimeout(heavyParsingDebounceTimer); heavyParsingDebounceTimer = null; }
            runHeavyParsing(editor);
        } else {
            // Regular character — debounce to avoid parsing on every keystroke
            if (heavyParsingDebounceTimer) { clearTimeout(heavyParsingDebounceTimer); }
            heavyParsingDebounceTimer = setTimeout(() => {
                heavyParsingDebounceTimer = null;
                if (editor && !editor.isDestroyed) {
                    runHeavyParsing(editor);
                }
            }, HEAVY_PARSING_DEBOUNCE_MS);
        }
    }
    
    /**
     * Run the heavy parsing operations immediately.
     * Called at word boundaries and when the debounce timer fires.
     */
    function runHeavyParsing(editor: Editor) {
        // Update original markdown tracking (serializes editor → markdown)
        updateOriginalMarkdown(editor);
        // Run unified parser for write mode (handles unclosed-block decorations)
        handleUnifiedParsing(editor);
    }
    
    /**
     * Flush any pending heavy parsing immediately.
     * Called before sending a message to ensure decorations and markdown are up-to-date.
     */
    function flushHeavyParsing(editor: Editor) {
        if (heavyParsingDebounceTimer) {
            clearTimeout(heavyParsingDebounceTimer);
            heavyParsingDebounceTimer = null;
        }
        if (editor && !editor.isDestroyed) {
            runHeavyParsing(editor);
        }
    }

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
                // No unclosed blocks — update decoration set only if it actually changed.
                // Avoid dispatching empty transactions when nothing changed, as these cause
                // DOM mutations that can trigger cascading input events on iOS Firefox.
                const prevDecorationSet = currentDecorationSet;
                if (currentPIIDecorations.length > 0) {
                    const { state: st } = editor;
                    currentDecorationSet = DecorationSet.create(st.doc, currentPIIDecorations);
                } else {
                    currentDecorationSet = DecorationSet.empty;
                }
                // Only dispatch a transaction to refresh decorations if the set actually changed
                const decorationsChanged = prevDecorationSet !== currentDecorationSet;
                if (decorationsChanged && decorationPropsSet && editor?.view) {
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
            }
        }
        
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
            } catch (error) {
                console.warn('[MessageInput] Error serializing TipTap content, falling back to plain text:', error);
                // Fallback to plain text if serialization fails
                originalMarkdown = editor.getText();
            }
        }
    }
    
    /**
     * Get the original markdown for sending to server
     * This returns the user's actual typed content without TipTap conversion artifacts
     */
    function getOriginalMarkdownForSending(): string {
        return originalMarkdown;
    }

    /**
     * Apply TipTap decorations to highlight unclosed blocks in write mode
     * Uses TipTap's native decoration system to avoid DOM conflicts
     */
    function applyHighlightingColors(editor: Editor, unclosedBlocks: any[]) {
        // Debug: unclosed blocks for decoration (logged only at info level to reduce keystroke overhead)

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

            // Decorations created from unclosed blocks (omit per-keystroke logging for performance)

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

            // Merge unclosed-block decorations with PII decorations so both are visible
            const allDecorations = [...tipTapDecorations, ...currentPIIDecorations];
            currentDecorationSet = DecorationSet.create(doc, allDecorations);
            if (!decorationPropsSet) {
                view.setProps({
                    decorations: () => currentDecorationSet ?? DecorationSet.empty,
                });
                decorationPropsSet = true;
            }
            // Always dispatch to refresh (also clears when empty)
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
                        
                        // Check for multi-line text - create a proper code embed for readability
                        // This ensures pasted logs, errors, code snippets, etc. are formatted as code blocks
                        // and stored in EmbedStore (encrypted, synced to server)
                        const isMultiLine = text.includes('\n');
                        const isAlreadyCodeBlock = text.trim().startsWith('```');
                        
                        if (isMultiLine && !isAlreadyCodeBlock) {
                            event.preventDefault();
                            event.stopPropagation();
                            
                            // Check for VS Code editor data to detect the programming language
                            // VS Code includes a 'vscode-editor-data' MIME type with JSON containing the 'mode' (language)
                            const vsCodeEditorData = event.clipboardData?.getData('vscode-editor-data') || null;
                            
                            if (!$authStore.isAuthenticated) {
                                // Unauthenticated / demo mode: EmbedStore is unavailable (no encryption keys).
                                // Insert a preview embed node with the code stored inline in the node `code`
                                // attribute — GroupRenderer reads this directly without EmbedStore.
                                const vsCodeLang = detectLanguageFromVSCode(vsCodeEditorData);
                                const language = vsCodeLang || detectLanguageFromContent(text) || 'text';
                                const embedId = generateUUID();
                                const lineCount = text.split('\n').length;
                                
                                console.debug('[MessageInput] Demo mode — inserting inline code embed:', {
                                    language, lineCount, embedId
                                });
                                
                                editor.commands.insertContent({
                                    type: 'embed',
                                    attrs: {
                                        id: embedId,
                                        type: 'code-code',
                                        status: 'finished',
                                        // "preview:code:" prefix tells GroupRenderer to read code from item.code attr
                                        contentRef: `preview:code:${embedId}`,
                                        code: text,
                                        language,
                                        lineCount,
                                    }
                                });
                                editor.commands.insertContent(' ');
                                editor.commands.focus('end');
                                hasContent = !isContentEmptyExceptMention(editor);
                                return true;
                            }
                            
                            // Authenticated path: create a proper embed in EmbedStore (async).
                            // This follows the same pattern as URL embeds.
                            // Pass VS Code editor data for automatic language detection.
                            createCodeEmbedFromPastedText({ text, vsCodeEditorData }).then(async (embedResult) => {
                                console.info('[MessageInput] Created code embed for pasted text:', {
                                    embed_id: embedResult.embed_id,
                                    lineCount: text.split('\n').length,
                                    charCount: text.length
                                });
                                
                                // Update originalMarkdown with the embed reference
                                const currentMarkdown = originalMarkdown || '';
                                originalMarkdown = currentMarkdown + (currentMarkdown ? '\n' : '') + embedResult.embedReference;
                                
                                // Parse and render the updated markdown with the embed reference
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
                                
                                // Update hasContent state
                                hasContent = !isContentEmptyExceptMention(editor);
                                
                                console.debug('[MessageInput] Inserted code embed reference:', {
                                    embed_id: embedResult.embed_id,
                                    originalMarkdownLength: originalMarkdown.length
                                });
                            }).catch((error) => {
                                console.error('[MessageInput] Failed to create code embed:', error);
                                // Fallback: insert as plain text if embed creation fails
                                editor.commands.insertContent(text);
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
                    
                    // No special handling needed - allow default paste.
                    // Flag for immediate PII detection on the next editor update,
                    // since pasted text may contain complete PII patterns.
                    piiPasteDetectionPending = true;
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
        
        // Clean up PII detection state
        if (piiDebounceTimer) { clearTimeout(piiDebounceTimer); piiDebounceTimer = null; }
        currentPIIDecorations = [];
        lastPIIText = '';
        
        // Clean up heavy parsing debounce timer
        if (heavyParsingDebounceTimer) { clearTimeout(heavyParsingDebounceTimer); heavyParsingDebounceTimer = null; }
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
        
        // Mobile keyboards (iOS Safari, Android Chrome, etc.): attach a viewport-
        // resize listener so the input scrolls into view after the virtual keyboard
        // finishes animating in. Fixes the common issue where the message field is
        // hidden behind the keyboard and only becomes visible after multiple taps.
        attachViewportListener();
        
        // Re-check mention trigger when focus is regained
        // This ensures the dropdown reappears if cursor is right after '@'
        checkMentionTrigger(editor);
    }

    function handleEditorBlur({ editor }: { editor: Editor }) {
        // Mobile: remove viewport-resize listener as soon as the editor loses focus
        // (keyboard is about to hide — no need to scroll anymore).
        detachViewportListener();

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
            const genericResult = result as import('./services/mentionSearchService').SkillMentionResult | import('./services/mentionSearchService').FocusModeMentionResult | import('./services/mentionSearchService').SettingsMemoryMentionResult | import('./services/mentionSearchService').SettingsMemoryEntryMentionResult;
            editor
                .chain()
                .focus()
                .deleteRange({ from: atDocPosition, to: from })
                .setGenericMention({
                    mentionType: result.type as 'skill' | 'focus_mode' | 'settings_memory' | 'settings_memory_entry',
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
    
    // =============================================================================
    // PII Detection and Highlighting
    // =============================================================================
    
    /**
     * Hybrid PII detection trigger: runs detection at natural word/token boundaries
     * (delimiter characters) instead of on every keystroke. This avoids running 16+
     * regex patterns per character while still catching PII at the exact moment it
     * becomes complete (e.g. after the space following an email address).
     *
     * Three trigger modes:
     * 1. **Delimiter**: Immediate detection when user types a delimiter char (space,
     *    comma, dot, newline, slash, etc.) — these mark the end of a token/word.
     * 2. **Paste**: Immediate detection after paste events (content arrives complete).
     * 3. **Debounce fallback**: If no delimiter is typed for PII_DEBOUNCE_MS, run
     *    detection anyway as a safety net (e.g. slow typing then clicking Send).
     *
     * For immediate needs (e.g. exclusion changes), use runPIIDetectionImmediate().
     */
    function runPIIDetection(editor: Editor, forcedByPaste = false) {
        if (!editor || editor.isDestroyed) return;
        
        const text = editor.getText();
        
        // Skip if text hasn't changed (e.g. cursor movement, selection change)
        if (text === lastPIIText) return;
        
        // If text was cleared, update immediately (no need to debounce cleanup)
        if (!text || text.trim().length === 0) {
            if (piiDebounceTimer) { clearTimeout(piiDebounceTimer); piiDebounceTimer = null; }
            lastPIIText = text;
            detectedPII = [];
            currentPIIDecorations = [];
            return;
        }
        
        // Determine if the latest character typed is a delimiter (word boundary).
        // Compare current text to last detected text to find what was just typed.
        const lastChar = text.length > 0 ? text[text.length - 1] : '';
        const isDelimiter = PII_TRIGGER_CHARS.has(lastChar);
        
        if (forcedByPaste || isDelimiter) {
            // Trigger 1 & 2: Delimiter typed or paste event — run immediately
            if (piiDebounceTimer) { clearTimeout(piiDebounceTimer); piiDebounceTimer = null; }
            runPIIDetectionImmediate(editor);
        } else {
            // Trigger 3: No delimiter — schedule fallback debounce.
            // This catches cases where the user finishes typing PII but doesn't type
            // a trailing delimiter before sending.
            if (piiDebounceTimer) { clearTimeout(piiDebounceTimer); }
            piiDebounceTimer = setTimeout(() => {
                piiDebounceTimer = null;
                runPIIDetectionImmediate(editor);
            }, PII_DEBOUNCE_MS);
        }
    }
    
    /**
     * Run PII detection immediately (no debounce).
     * Used when the debounce timer fires and when the user interacts with PII
     * UI (exclusions, undo-all).
     * 
     * After building PII decorations, calls rebuildDecorationSet() to merge
     * them into the visible decoration set alongside any unclosed-block
     * decorations that applyHighlightingColors previously created.
     * 
     * Optimization: skips re-detection if text hasn't changed since last run.
     */
    function runPIIDetectionImmediate(editor: Editor) {
        if (!editor || editor.isDestroyed) return;
        
        const text = editor.getText();
        
        // Skip if text hasn't changed (e.g. cursor movement, selection change)
        if (text === lastPIIText) return;
        lastPIIText = text;
        
        if (!text || text.trim().length === 0) {
            detectedPII = [];
            currentPIIDecorations = [];
            return;
        }
        
        // Read current privacy settings from the personalDataStore
        const piiSettings: PIIDetectionSettings = get(personalDataStore.settings);
        
        // If master toggle is off, skip all PII detection
        if (!piiSettings.masterEnabled) {
            detectedPII = [];
            currentPIIDecorations = [];
            return;
        }
        
        // Build the set of disabled categories (categories where the toggle is OFF)
        const disabledCategories = new Set<string>();
        for (const [category, enabled] of Object.entries(piiSettings.categories)) {
            if (!enabled) disabledCategories.add(category);
        }
        
        // Get user-defined personal data entries that are enabled
        const enabledEntries: PersonalDataEntry[] = get(personalDataStore.enabledEntries);
        const personalDataForDetection: PersonalDataForDetection[] = enabledEntries.map(
            (entry) => {
                const result: PersonalDataForDetection = {
                    id: entry.id,
                    textToHide: entry.textToHide,
                    replaceWith: entry.replaceWith,
                };
                // For address entries, include individual address lines as additional search texts
                if (entry.type === 'address' && entry.addressLines) {
                    const additionalTexts: string[] = [];
                    if (entry.addressLines.street) additionalTexts.push(entry.addressLines.street);
                    if (entry.addressLines.city) additionalTexts.push(entry.addressLines.city);
                    result.additionalTexts = additionalTexts;
                }
                return result;
            },
        );
        
        // Build detection options with category filtering and personal data entries
        const detectionOptions: PIIDetectionOptions = {
            excludedIds: piiExclusions,
            disabledCategories,
            personalDataEntries: personalDataForDetection,
        };
        
        // Detect PII with full store-aware options
        const matches = detectPII(text, detectionOptions);
        detectedPII = matches;
        
        if (matches.length > 0) {
            console.debug('[MessageInput] PII detected:', matches.length, 'matches');
            buildPIIDecorations(editor, matches);
        } else {
            currentPIIDecorations = [];
        }
        
        // Rebuild the full decoration set so PII highlights become visible.
        // rebuildDecorationSet merges currentPIIDecorations into the view and
        // dispatches a transaction to refresh the display.
        rebuildDecorationSet(editor);
    }
    
    /**
     * Build PII Decoration objects and store them in currentPIIDecorations.
     * These are merged into the main decoration set by applyHighlightingColors
     * or directly when no unclosed blocks exist.
     */
    function buildPIIDecorations(editor: Editor, matches: PIIMatch[]) {
        const { doc } = editor.state;
        
        try {
            currentPIIDecorations = matches.map(match => {
                // TipTap positions are 1-indexed, text positions are 0-indexed
                const from = Math.max(1, Math.min(match.startIndex + 1, doc.content.size));
                const to = Math.max(1, Math.min(match.endIndex + 1, doc.content.size));
                
                // All PII types use the same orange/amber bold text style (matches ReadOnlyMessage .pii-revealed).
                // The data-pii-type attribute is kept for tooltip display and click handling.
                return Decoration.inline(from, to, {
                    class: 'pii-highlight',
                    'data-pii-id': match.id,
                    'data-pii-type': match.type,
                    title: `Click to keep original (${match.type.toLowerCase().replace(/_/g, ' ')})`
                });
            });
        } catch (error) {
            console.error('[MessageInput] Error building PII decorations:', error);
            currentPIIDecorations = [];
        }
    }
    
    /**
     * Handle click on a PII decoration to exclude it from replacement.
     * Called when user clicks on highlighted sensitive data.
     */
    function handlePIIClick(matchId: string) {
        // Add to exclusions set
        piiExclusions = new Set([...piiExclusions, matchId]);
        // Invalidate last text cache so detection re-runs immediately
        lastPIIText = '';
        
        // Re-run detection immediately (no debounce) and rebuild decorations
        if (editor && !editor.isDestroyed) {
            runPIIDetectionImmediate(editor);
            // Rebuild the full decoration set with updated PII decorations
            rebuildDecorationSet(editor);
        }
        
        console.debug('[MessageInput] PII exclusion added:', matchId);
    }
    
    /**
     * Handle "Undo All" from the PII warning banner.
     * Excludes all detected PII so nothing gets replaced on send.
     */
    function handlePIIUndoAll() {
        // Mark all current detections as excluded
        const newExclusions = new Set(piiExclusions);
        for (const match of detectedPII) {
            newExclusions.add(match.id);
        }
        piiExclusions = newExclusions;
        
        // Clear detected PII and decorations
        detectedPII = [];
        currentPIIDecorations = [];
        lastPIIText = '';
        
        // Rebuild decoration set without PII decorations
        if (editor && !editor.isDestroyed) {
            rebuildDecorationSet(editor);
        }
        
        console.debug('[MessageInput] All PII exclusions applied, user chose to keep original text');
    }
    
    /**
     * Rebuild the currentDecorationSet from scratch using the current PII decorations.
     * Called after PII exclusions change to immediately update the view.
     */
    function rebuildDecorationSet(editor: Editor) {
        const { state, view } = editor;
        if (currentPIIDecorations.length > 0) {
            // Re-run the unified parser to get unclosed-block decorations, then merge
            // For simplicity, just rebuild with PII only - the next editor update
            // will call handleUnifiedParsing which merges both
            currentDecorationSet = DecorationSet.create(state.doc, currentPIIDecorations);
        } else {
            currentDecorationSet = DecorationSet.empty;
        }
        if (!decorationPropsSet) {
            view.setProps({
                decorations: () => currentDecorationSet ?? DecorationSet.empty,
            });
            decorationPropsSet = true;
        }
        view.dispatch(state.tr);
    }

    function handleEditorUpdate({ editor }: { editor: Editor }) {
        // --- Text-change guard ---
        // On iOS Firefox, double-tap to select text fires spurious `input` events
        // that ProseMirror treats as content changes, triggering onUpdate even though
        // only the selection changed. The heavy operations below (markdown serialization,
        // unified parsing, PII detection) plus the empty transaction dispatches they
        // perform would create an infinite feedback loop crashing performance.
        // Guard: compare current plain text to last processed text and bail early
        // for selection-only changes. checkMentionTrigger still runs because it
        // depends on cursor position, not content.
        const currentText = editor.getText();
        const textActuallyChanged = currentText !== lastEditorUpdateText;
        
        if (textActuallyChanged) {
            lastEditorUpdateText = currentText;
        }
        
        const newHasContent = !isContentEmptyExceptMention(editor);
        if (hasContent !== newHasContent) {
            hasContent = newHasContent;
            if (!newHasContent) {
                console.debug("[MessageInput] Content cleared, triggering draft deletion.");
                // Clear PII detections and exclusions when content is cleared
                detectedPII = [];
                piiExclusions = new Set();
                currentPIIDecorations = [];
                lastPIIText = '';
            }
        }
        
        // Skip all heavy processing if only the selection changed (no content change).
        // This prevents the infinite loop on iOS Firefox where empty transaction
        // dispatches cause further spurious input events.
        if (!textActuallyChanged) {
            // Still check mention trigger (depends on cursor position, not content)
            checkMentionTrigger(editor);
            return;
        }
        
        // Always trigger save/delete operation - the draft service handles both scenarios
        triggerSaveDraft(currentChatId);

        // PII Detection: hybrid trigger — immediate on delimiter chars and paste events,
        // debounce fallback for regular typing. See runPIIDetection() for details.
        const wasPaste = piiPasteDetectionPending;
        piiPasteDetectionPending = false;
        runPIIDetection(editor, wasPaste);

        // Heavy parsing (markdown serialization + unified parser + decorations):
        // Debounced to delimiter boundaries to avoid running the full parser on every
        // keystroke. Runs immediately on space/newline/punctuation and paste, with a
        // 400ms fallback timer for regular characters.
        scheduleHeavyParsing(editor, currentText, wasPaste);

        // Dispatch live text change event so parent components can react on each keystroke
        // This enables precise, character-by-character search in new chat suggestions
        try {
            dispatch('textchange', { text: currentText });
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
        editorElement?.addEventListener('imagefullscreen', handleImageFullscreen as EventListener);
        editorElement?.addEventListener('pdffullscreen', handlePdfFullscreen as EventListener);
        editorElement?.addEventListener('recordingfullscreen', handleRecordingFullscreen as EventListener);
        editorElement?.addEventListener('click', handleEditorClick); // For PII click handling
        // Listen for stop-button upload cancellations from image embeds.
        // This event is dispatched by Embed.ts after the embed node is deleted so
        // we can update the draft and originalMarkdown even when getText() is
        // unchanged (e.g. the editor contained only the uploading image with no text).
        editorElement?.addEventListener('embed-upload-cancelled', handleEmbedUploadCancelled as EventListener);
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
                                'enter_message.placeholder.touch' :
                                'enter_message.placeholder.desktop';
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
        // Always clean up the viewport listener on destroy
        detachViewportListener();
        document.removeEventListener('embedclick', handleEmbedClick as EventListener);
        document.removeEventListener('mateclick', handleMateClick as EventListener);
        editorElement?.removeEventListener('paste', handlePaste);
        editorElement?.removeEventListener('custom-send-message', handleSendMessage as EventListener);
        editorElement?.removeEventListener('custom-sign-up-click', handleSignUpClick as EventListener);
        editorElement?.removeEventListener('keydown', handleKeyDown);
        editorElement?.removeEventListener('codefullscreen', handleCodeFullscreen as EventListener);
        editorElement?.removeEventListener('imagefullscreen', handleImageFullscreen as EventListener);
        editorElement?.removeEventListener('pdffullscreen', handlePdfFullscreen as EventListener);
        editorElement?.removeEventListener('recordingfullscreen', handleRecordingFullscreen as EventListener);
        editorElement?.removeEventListener('click', handleEditorClick);
        editorElement?.removeEventListener('embed-upload-cancelled', handleEmbedUploadCancelled as EventListener);
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
            void chatSyncService.sendCancelAiTask(taskId, currentChatId ?? undefined);
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
            // Pass currentChatId so server can clear active task marker immediately
            await chatSyncService.sendCancelAiTask(taskId, currentChatId);
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
            queuedMessageText = message || $text('enter_message.message_queued');
            
            // Auto-hide after 7 seconds
            setTimeout(() => {
                queuedMessageText = null;
            }, 7000);
        }
    }
 
    // --- Specific Event Handlers ---
    
    /**
     * Handle clicks in the editor to detect clicks on PII highlights.
     * When a user clicks on a highlighted PII item, we exclude it from replacement.
     */
    function handleEditorClick(event: MouseEvent) {
        const target = event.target as HTMLElement;
        
        // Check if the clicked element is a PII highlight
        if (target.classList.contains('pii-highlight') || target.closest('.pii-highlight')) {
            const piiElement = target.classList.contains('pii-highlight') ? target : target.closest('.pii-highlight') as HTMLElement;
            const piiId = piiElement?.getAttribute('data-pii-id');
            
            if (piiId) {
                event.preventDefault();
                event.stopPropagation();
                handlePIIClick(piiId);
            }
        }
    }
    
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
        await handleFilePaste(event, editor, $authStore.isAuthenticated);
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
    function handleImageFullscreen(event: CustomEvent) { dispatch('imagefullscreen', event.detail); }
    function handlePdfFullscreen(event: CustomEvent) { dispatch('pdffullscreen', event.detail); }
    function handleRecordingFullscreen(event: CustomEvent) { dispatch('recordingfullscreen', event.detail); }
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
     * Handle the embed-upload-cancelled event dispatched by Embed.ts when the user
     * presses Stop on an uploading image.
     *
     * WHY THIS IS NEEDED:
     * The normal draft-save path (handleEditorUpdate → triggerSaveDraft) is guarded
     * by a text-change check:
     *   if (!textActuallyChanged) return; // skip heavy work
     * When the editor contains only an uploading image (no text), removing the embed
     * node does NOT change editor.getText() — it was empty before and stays empty
     * after. The guard therefore skips triggerSaveDraft, leaving the draft preview
     * in Chat.svelte stale (it still shows "[Image]" after the stop button was pressed).
     *
     * This handler is called AFTER deleteRange has already run (the embed is gone),
     * so we:
     *  1. Rebuild originalMarkdown from the current (updated) editor state.
     *  2. Force-save the draft (or delete it if the editor is now empty), bypassing
     *     the text-change guard.
     *  3. Update hasContent so the UI (send button, fullscreen button) reflects the
     *     new empty state.
     */
    function handleEmbedUploadCancelled(event: CustomEvent) {
        const { embedId } = event.detail ?? {};
        console.debug('[MessageInput] Embed upload cancelled, forcing draft update:', embedId);

        if (!editor || editor.isDestroyed) return;

        // Rebuild originalMarkdown from the now-updated editor state.
        // isConvertingEmbeds is deliberately NOT set — we are reading the document
        // after deletion, not mid-conversion, so the guard must NOT block the update.
        updateOriginalMarkdown(editor);

        // Update content tracking so the send button and fullscreen button hide/show correctly.
        hasContent = !isContentEmptyExceptMention(editor);
        // Keep the text-change guard in sync so the next legitimate editor update
        // doesn't incorrectly think text hasn't changed.
        lastEditorUpdateText = editor.getText();

        // Force a draft save (or deletion) even though getText() may not have changed.
        // triggerSaveDraft is debounced — it will read the editor state at fire time.
        triggerSaveDraft(currentChatId);
    }

    /**
     * Prevent blur when clicking on UI elements within the message input wrapper
     * This allows users to click on action buttons and other controls without losing focus
     * Also ensures clicks on the editor itself maintain focus properly
     */
    function handleMessageWrapperMouseDown(event: MouseEvent) {
        const target = event.target as HTMLElement;
        
        // When MapsView is open, its overlay sits inside .message-field and contains
        // its own interactive elements (search input, buttons, map).
        // Do NOT steal focus from them — let clicks inside the maps overlay pass through
        // naturally so the search input and other controls are reachable.
        if (showMaps && target.closest('.maps-overlay')) {
            console.debug('[MessageInput] Click inside MapsView overlay, skipping editor focus logic');
            return;
        }
        
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
        isDragging = false; // Hide drop overlay when files are dropped
        await handleFileDrop(event, editorElement, editor, $authStore.isAuthenticated);
        tick().then(() => {
            hasContent = !isContentEmptyExceptMention(editor);
            updateEmbedGroupLayouts();
            observeEmbedGroupContainers();
        });
    }
    function handleDragOver(event: DragEvent) {
        isDragging = true; // Show drop overlay when files are dragged over
        handleFileDragOver(event, editorElement);
    }
    function handleDragLeave(event: DragEvent) {
        isDragging = false; // Hide drop overlay when drag leaves
        handleFileDragLeave(event, editorElement);
    }
    async function onFileSelected(event: Event) {
        await handleFileSelectedEvent(event, editor, $authStore.isAuthenticated);
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
    /**
     * Handle a photo captured from the CameraView (desktop webcam overlay).
     * Routes through insertImage — same embed pipeline as file picker uploads.
     * The previewUrl is an object URL for the resized preview blob; insertImage
     * will call resizeImage internally when only previewUrl (no originalUrl) is given,
     * so we skip the redundant blob URL and let it generate fresh URLs from the file.
     */
    async function handlePhotoCaptured(event: CustomEvent<{ blob: Blob, previewUrl?: string }>) {
        const { blob } = event.detail;
        // Use the blob's MIME type to preserve PNG/JPEG/HEIC from native camera
        const mimeType = blob.type || 'image/jpeg';
        const ext = mimeType.includes('png') ? 'png' : mimeType.includes('webp') ? 'webp' : 'jpg';
        const file = new File([blob], `camera_${Date.now()}.${ext}`, { type: mimeType });
        showCamera = false;
        await tick();
        // isRecording=false: camera photos are not recordings; isAuthenticated controls upload path
        await insertImage(editor, file, false, undefined, undefined, $authStore.isAuthenticated);
        hasContent = true;
        tick().then(() => {
            updateEmbedGroupLayouts();
            observeEmbedGroupContainers();
        });
    }
    /* VIDEO RECORDING DISABLED — re-enable when video upload support is added.
     * To re-enable:
     *   1. Uncomment this function.
     *   2. Re-add `on:videorecorded={handleVideoRecorded}` to <CameraView> in the template.
     *   3. Restore `video/*` in the cameraInput accept attribute.
     *
     * async function handleVideoRecorded(event: CustomEvent<{ blob: Blob, duration: string }>) {
     *     const { blob, duration } = event.detail;
     *     const mimeType = blob.type || 'video/webm';
     *     const ext = mimeType.includes('mp4') ? 'mp4' : 'webm';
     *     const file = new File([blob], `camera_${Date.now()}.${ext}`, { type: mimeType });
     *     showCamera = false;
     *     await tick();
     *     await insertVideo(editor, file, duration, false);
     *     hasContent = true;
     *     tick().then(() => {
     *         updateEmbedGroupLayouts();
     *         observeEmbedGroupContainers();
     *     });
     * }
     */
    async function handleAudioRecorded(event: CustomEvent<{ blob: Blob, duration: number, mimeType: string }>) {
        const { blob, duration, mimeType } = event.detail;
        const formattedDuration = formatDuration(duration);
        if (editor.isEmpty) { editor.commands.setContent(getInitialContent()); await tick(); }
        // insertRecording() uploads to server + triggers Mistral Voxtral transcription in parallel.
        // It does NOT need a pre-created blob URL — it creates its own internally.
        await insertRecording(editor, blob, mimeType, formattedDuration, $authStore.isAuthenticated);
        hasContent = true;
        handleStopRecordingCleanup(); // Called here after recording is inserted
    }
    function handleLocationClick() { showMaps = true; }
    async function handleLocationSelected(event: CustomEvent<{ type: string; attrs: Record<string, unknown> }>) {
        showMaps = false;
        await tick();
        if (editor.isEmpty) { editor.commands.setContent(getInitialContent()); await tick(); }

        const previewData = event.detail;
        if (!previewData?.attrs) return;

        // insertMap() stores the location data in EmbedStore and inserts the embed node.
        // The embed node is serialized on send as {"type":"location","embed_id":"..."}
        // which the backend uses to inject location context into the LLM prompt.
        await insertMap(editor, previewData);
        hasContent = true;
    }
    async function handleMenuAction(action: string) {
        await handleMenuActionTrigger(action, selectedNode, editor, dispatch, selectedEmbedId);
        showMenu = false; isMenuInteraction = false; selectedNode = null; selectedEmbedId = null;
        if (action === 'delete') {
            await tick(); hasContent = !isContentEmptyExceptMention(editor);
        }
    }
    function handleFileSelect() {
        // Cancel any pending blur timeout so the action buttons stay visible after the
        // OS file picker opens. Without this, the editor blur fires before the file picker
        // opens and collapses the action buttons bar.
        if (blurTimeoutId) {
            clearTimeout(blurTimeoutId);
            blurTimeoutId = null;
        }
        isMessageFieldFocused = true;
        fileInput.multiple = true;
        fileInput.click();
    }
    function handleSendMessage() {
        // Flush any debounced heavy parsing so originalMarkdown is fully up-to-date
        if (editor && !editor.isDestroyed) {
            flushHeavyParsing(editor);
        }
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
            currentChatId,
            piiExclusions // Pass PII exclusions so excluded matches are not replaced
        );
        
        // Clear PII state after sending
        detectedPII = [];
        piiExclusions = new Set();
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
        lastEditorUpdateText = ''; // Reset text-change guard
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
    async function onRecordMouseUp(event: CustomEvent<{ originalEvent: MouseEvent }>) {
        // Wait for Svelte to render RecordAudio (bind:this is set after the #if block mounts).
        // If the user releases exactly when the 200ms hold timer fires, showRecordAudioUI
        // becomes true but the DOM update hasn't committed yet, so recordAudioComponent is
        // still undefined. tick() ensures the component ref is available before we call stop().
        await tick();
        handleRecordMouseUpLogic(recordAudioComponent);
    }
    async function onRecordMouseLeave(event: CustomEvent<{ originalEvent: MouseEvent }>) {
        // When the recording overlay is active, the overlay covers the mic button and
        // the browser fires a synthetic mouseleave. Ignore it — RecordAudio's own
        // document-level listeners handle all stop/cancel logic from this point.
        if ($recordingState.showRecordAudioUI) return;

        // Same tick() reasoning as onRecordMouseUp — component ref may not be set yet.
        await tick();
        handleRecordMouseLeaveLogic(recordAudioComponent);
    }
    function onRecordTouchStart(event: CustomEvent<{ originalEvent: TouchEvent }>) {
        handleRecordTouchStartLogic(event.detail.originalEvent);
    }
    async function onRecordTouchEnd(event: CustomEvent<{ originalEvent: TouchEvent }>) {
        // Same tick() reasoning as onRecordMouseUp.
        await tick();
        handleRecordTouchEndLogic(recordAudioComponent);
    }


    // --- Public API ---
    export function focus() { if (editor && !editor.isDestroyed) editor.commands.focus('end'); }
    export function setSuggestionText(text: string) {
        console.debug('[MessageInput] setSuggestionText called with:', text);
        console.debug('[MessageInput] editor available:', !!editor);
        console.debug('[MessageInput] editor destroyed:', editor?.isDestroyed);
        
        if (editor && !editor.isDestroyed) {
            console.debug('[MessageInput] Inserting suggestion text at cursor position');
            // Insert at cursor position rather than replacing the entire content.
            // This preserves embeds and other content already in the editor.
            // If the editor is empty, focus to the end first so the text lands in
            // the right paragraph; if there's existing content the cursor is already
            // where the user last clicked.
            if (editor.isEmpty) {
                editor.commands.focus('end');
            }
            editor.commands.insertContent(text);
            hasContent = true;
            lastEditorUpdateText = editor.getText(); // Sync text-change guard after external content set
            updateOriginalMarkdown(editor);
            editor.commands.focus('end');
            console.debug('[MessageInput] Suggestion text inserted at cursor successfully');
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
        
        // Reset text-change guard so next editor update processes fully after content swap
        lastEditorUpdateText = editor ? editor.getText() : '';
        
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
        lastEditorUpdateText = ''; // Reset text-change guard so next update processes fully
    }
    export function getOriginalMarkdown(): string {
        // Flush any pending heavy parsing to ensure originalMarkdown is up-to-date
        // before the caller reads it (e.g. before sending a message)
        if (editor && !editor.isDestroyed) {
            flushHeavyParsing(editor);
        }
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
    // When the map overlay is open the field must be tall enough to show the map.
    // We use a fixed height so the editor sits below the map controls and the
    // message-field container grows, making the map fill edge-to-edge.
    // When the map overlay or camera overlay is open, grow the container to a fixed height
    // so the overlay fills edge-to-edge (same as maps). Without this the desktop camera
    // view renders at a tiny default height.
    let containerStyle = $derived(
        (showMaps || showCamera)
            ? 'height: 400px; max-height: 400px;'
            : isFullscreen
                ? `height: calc(100vh - 100px); max-height: calc(100vh - 120px); height: calc(100dvh - 100px); max-height: calc(100dvh - 120px);`
                : 'height: auto; max-height: 350px;'
    );
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
    
    // Update active AI task status when currentChatId changes using $effect.
    // IMPORTANT: Must call updateActiveAITaskStatus() even when currentChatId is undefined
    // (e.g. when navigating to a new chat) so that stale stop-button state is cleared.
    $effect(() => {
        // Access currentChatId so Svelte tracks it as a dependency
        const _chatId = currentChatId;
        if (chatSyncService) {
            updateActiveAITaskStatus();
        }
    });

    // Check for pending notification reply when chat ID changes.
    // If the user typed a reply in a notification and hit send, the text
    // was stored in pendingNotificationReplyStore. We pick it up here,
    // populate the editor, and focus it so the user can review and send.
    $effect(() => {
        if (currentChatId && editor && !editor.isDestroyed) {
            const pendingReply = pendingNotificationReplyStore.consume(currentChatId);
            if (pendingReply) {
                console.debug('[MessageInput] Populating editor with pending notification reply:', pendingReply);
                tick().then(() => {
                    if (editor && !editor.isDestroyed) {
                        editor.commands.setContent(`<p>${pendingReply}</p>`);
                        editor.commands.focus('end');
                        hasContent = true;
                    }
                });
            }
        }
    });
 
</script>
 
<!-- Template -->
<div bind:this={messageInputWrapper} class="message-input-wrapper" role="none" onmousedown={handleMessageWrapperMouseDown}>
    <!-- PII Warning Banner - shown when sensitive data is detected in the input -->
    <PIIWarningBanner 
        matches={detectedPII}
        onUndoAll={handlePIIUndoAll}
    />
    
    <div
        class="message-field {isMessageFieldFocused ? 'focused' : ''} {$recordingState.isRecordingActive ? 'recording-active' : ''} {!shouldShowActionButtons ? 'compact' : ''} {showMaps ? 'maps-open' : ''}"
        class:drag-over={isDragging}
        style={containerStyle}
        ondragover={handleDragOver}
        ondragleave={handleDragLeave}
        ondrop={handleDrop}
        role="textbox"
        aria-multiline="true"
        tabindex="0"
    >
        <!-- Drop overlay: shown when user drags files over the message field.
             Uses the existing icon_files icon and a localised label. -->
        {#if isDragging}
            <div class="drop-overlay" aria-hidden="true">
                <span class="drop-overlay-icon clickable-icon icon_files"></span>
                <span class="drop-overlay-text">{$text('enter_message.attachments.drop_files')}</span>
            </div>
        {/if}

        {#if hasContent || isFullscreen}
            <button
                class="clickable-icon icon_fullscreen fullscreen-button"
                onclick={toggleFullscreen}
                aria-label={isFullscreen ? $text('enter_message.fullscreen.exit_fullscreen') : $text('enter_message.fullscreen.enter_fullscreen')}
                use:tooltip
            ></button>
        {/if}

        <!-- Only images and code/text files are supported. Extensions mirror isCodeOrTextFile() in utils/fileHelpers.ts. -->
        <input bind:this={fileInput} type="file" onchange={onFileSelected} style="display: none" multiple accept="image/*,.py,.js,.ts,.html,.css,.json,.svelte,.java,.cpp,.c,.h,.hpp,.rs,.go,.rb,.php,.swift,.kt,.txt,.md,.xml,.yaml,.yml,.sh,.bash,.sql,.vue,.jsx,.tsx,.scss,.less,.sass,Dockerfile" />
        <!-- Video capture disabled: video upload not yet supported. Remove video/* when re-enabling. -->
        <input bind:this={cameraInput} type="file" accept="image/*" capture="environment" onchange={onFileSelected} style="display: none" />

        <div class="scrollable-content" bind:this={scrollableContent} style={scrollableStyle}>
            <div class="content-wrapper">
                <div bind:this={editorElement} class="editor-content prose"></div>
            </div>
        </div>

        {#if showCamera}
            <!-- on:videorecorded removed — video recording disabled until upload support is added -->
            <CameraView bind:videoElement on:close={() => showCamera = false} on:focusEditor={focus} on:photocaptured={handlePhotoCaptured} />
        {/if}

        <!-- Action Buttons Component: fades in when input is focused, fades out when unfocused.
             The wrapper div has zero height and no layout impact; ActionButtons is absolutely
             positioned inside the parent .message-field, so the wrapper is transparent to layout. -->
        {#if shouldShowActionButtons}
            <div class="action-buttons-fade-wrapper" transition:fade={{ duration: 250 }}>
                <ActionButtons
                    showSendButton={hasContent}
                    isAuthenticated={$authStore.isAuthenticated}
                    isRecordButtonPressed={$recordingState.isRecordButtonPressed}
                    micPermissionState={$recordingState.micPermissionState}
                    {highlightPressHold}
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
            </div>
        {/if}

        <!-- Queued Message Indicator - shown when a message is queued due to active AI task -->
        {#if queuedMessageText}
            <div class="queued-message-indicator" transition:fade={{ duration: 200 }}>
                {queuedMessageText}
            </div>
        {/if}

        <!-- Mic permission hint — shown below action buttons.
             · denied → always-visible error telling user to unblock in settings
             · prompt/unknown + showRecordHint → timed hint to allow mic access
             · granted + single tap → handled by highlightPressHold prop on ActionButtons
               (no separate hint div needed; the inline label flashes instead) -->
        {#if $recordingState.micPermissionState === 'denied'}
            <div class="queued-message-indicator mic-permission-hint mic-permission-blocked" transition:fade={{ duration: 200 }}>
                {$text('enter_message.record_audio.microphone_blocked')}
            </div>
        {:else if $recordingState.showRecordHint && $recordingState.micPermissionState !== 'granted'}
            <div class="queued-message-indicator mic-permission-hint" transition:fade={{ duration: 200 }}>
                {$text('enter_message.record_audio.allow_microphone_access')}
            </div>
        {/if}

        <!-- Stop Processing Icon - shown when AI task is active -->
        <!-- Debug: activeAITaskId = {activeAITaskId}, currentChatId = {currentChatId} -->
        {#if activeAITaskId || awaitingAITaskStart}
            <button
                class="stop-processing-button {hasContent ? 'shifted-left' : ''}"
                onclick={handleCancelAITask}
                use:tooltip
                title={$text('enter_message.stop')}
                aria-label={$text('enter_message.stop')}
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
            <MapsView
                defaultImprecise={defaultImprecise}
                on:close={() => showMaps = false}
                on:locationselected={handleLocationSelected}
            />
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
