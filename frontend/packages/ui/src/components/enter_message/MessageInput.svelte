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

    // Import external styles to keep component file manageable
    // Temporarily commenting out external CSS to test
    import './MessageInput.styles.css';

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
    import { isDesktop } from '../../utils/platform';

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
            
            // Check if there are streaming data for highlighting
            if (parsedDoc._streamingData && parsedDoc._streamingData.unclosedBlocks.length > 0) {
                console.info('[MessageInput] Found unclosed blocks for highlighting:', 
                    parsedDoc._streamingData.unclosedBlocks);
                
                // Apply highlighting colors for unclosed blocks
                applyHighlightingColors(editor, parsedDoc._streamingData.unclosedBlocks);
            }
            
            // For now, we'll apply previews only when blocks are completed
            // In a future iteration, we can add real-time preview updates
            
        } catch (error) {
            console.error('[MessageInput] Error in unified parsing:', error);
            // Log the error but don't fall back to legacy - we need to fix the unified parser
        }
    }
    
    /**
     * Apply TipTap decorations to highlight unclosed blocks in write mode
     * Uses TipTap's native decoration system to avoid DOM conflicts
     */
    function applyHighlightingColors(editor: Editor, unclosedBlocks: any[]) {
        console.debug('[MessageInput] Applying TipTap decorations for unclosed blocks:', 
            unclosedBlocks.map(block => ({ type: block.type, startLine: block.startLine })));
        
        if (unclosedBlocks.length === 0) {
            // Clear any existing decorations by updating the plugin state
            // We'll handle this by updating the decorations prop if needed
            console.debug('[MessageInput] No unclosed blocks, clearing decorations');
            return;
        }
        
        const { state, view } = editor;
        const { doc } = state;
        const text = editor.getText();
        
        console.debug('[MessageInput] Editor state:', {
            docSize: doc.content.size,
            textLength: text.length,
            text: text.substring(0, 100) + (text.length > 100 ? '...' : '')
        });
        
        try {
            // Find text ranges to highlight based on unclosed blocks
            const decorations = [];
            
            for (const block of unclosedBlocks) {
                let className = 'unclosed-block-default';
                
                switch (block.type) {
                    case 'code':
                        className = 'unclosed-block-code';
                        break;
                    case 'table':
                        className = 'unclosed-block-table';
                        break;
                    case 'document_html':
                        className = 'unclosed-block-html';
                        break;
                    case 'url':
                        className = 'unclosed-block-url';
                        break;
                }
                
                // Find the marker pattern in text
                let markerPattern = '';
                switch (block.type) {
                    case 'code':
                        markerPattern = '```';
                        break;
                    case 'table':
                        markerPattern = '|';
                        break;
                    case 'url':
                        // Look for http/https/www patterns
                        const urlMatches = text.match(/(https?:\/\/[^\s]+|www\.[^\s]+)/g);
                        if (urlMatches) {
                            for (const urlMatch of urlMatches) {
                                const startIndex = text.indexOf(urlMatch);
                                const endIndex = startIndex + urlMatch.length;
                                if (startIndex >= 0 && endIndex <= doc.content.size - 1) {
                                    decorations.push({
                                        from: startIndex + 1, // +1 for ProseMirror doc positions
                                        to: endIndex + 1,
                                        className,
                                        type: block.type
                                    });
                                }
                            }
                        }
                        continue; // Skip the general marker logic for URLs
                }
                
                // For code and table blocks, find the marker and highlight from there to end
                if (markerPattern) {
                    const markerIndex = text.indexOf(markerPattern);
                    if (markerIndex >= 0) {
                        // Highlight from the marker to the end of the text
                        const startPos = markerIndex + 1; // +1 for ProseMirror positions
                        const endPos = Math.min(text.length + 1, doc.content.size);
                        
                        if (startPos < endPos && startPos >= 1 && endPos <= doc.content.size) {
                            decorations.push({
                                from: startPos,
                                to: endPos,
                                className,
                                type: block.type
                            });
                        }
                    }
                }
            }
            
            console.debug('[MessageInput] Created decorations:', decorations);
            
            // Build ProseMirror decorations
            const tipTapDecorations = decorations.map(dec => 
                Decoration.inline(dec.from, dec.to, { 
                    class: dec.className,
                    'data-block-type': dec.type
                }, {
                    inclusiveStart: false,
                    inclusiveEnd: true
                })
            );

            // Create/update decoration set and attach via view.setProps once
            currentDecorationSet = DecorationSet.create(doc, tipTapDecorations);
            if (!decorationPropsSet) {
                view.setProps({
                    decorations: () => currentDecorationSet ?? DecorationSet.empty,
                });
                decorationPropsSet = true;
            }
            // Trigger redraw to apply decorations
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

        if (event.key === 'Escape') {
            if (showCamera) { event.preventDefault(); showCamera = false; }
            else if (showMaps) { event.preventDefault(); showMaps = false; }
            else if (showMenu) { event.preventDefault(); showMenu = false; isMenuInteraction = false; selectedNode = null; }
            else if (isMessageFieldFocused) { event.preventDefault(); editor?.commands.blur(); }
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
        } else if (shouldFocus && editor) {
            editor.commands.focus('end');
            hasContent = !isContentEmptyExceptMention(editor);
        }
    }
    export function clearMessageField(shouldFocus: boolean = true) {
        clearEditorAndResetDraftState(shouldFocus);
        hasContent = false;
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
    /* TipTap decoration-based highlighting styles for unclosed blocks */
    :global(.ProseMirror .unclosed-block-code) {
        color: #155D91 !important;
        background-color: color-mix(in srgb, #155D91 15%, transparent) !important;
        border-radius: 3px !important;
        padding: 2px 4px !important;
        font-family: 'JetBrains Mono', 'Courier New', monospace !important;
        border-left: 3px solid #155D91 !important;
        margin-left: 2px !important;
    }
    
    :global(.ProseMirror .unclosed-block-table) {
        color: #006400 !important;
        background-color: color-mix(in srgb, #006400 15%, transparent) !important;
        border-radius: 3px !important;
        padding: 2px 4px !important;
        border-left: 3px solid #006400 !important;
        margin-left: 2px !important;
    }
    
    :global(.ProseMirror .unclosed-block-url) {
        color: #DE1E66 !important;
        background-color: color-mix(in srgb, #DE1E66 15%, transparent) !important;
        border-radius: 3px !important;
        padding: 2px 4px !important;
        border-left: 3px solid #DE1E66 !important;
        margin-left: 2px !important;
    }
    
    :global(.ProseMirror .unclosed-block-html) {
        color: #6A737D !important;
        background-color: color-mix(in srgb, #6A737D 15%, transparent) !important;
        border-radius: 3px !important;
        padding: 2px 4px !important;
        border-left: 3px solid #6A737D !important;
        margin-left: 2px !important;
    }
    
    /* Fallback for any unclosed block */
    :global(.ProseMirror .unclosed-block-default) {
        color: #DE1E66 !important;
        background-color: color-mix(in srgb, #DE1E66 15%, transparent) !important;
        border-radius: 3px !important;
        padding: 2px 4px !important;
        border-left: 3px solid #DE1E66 !important;
        margin-left: 2px !important;
    }
</style>

