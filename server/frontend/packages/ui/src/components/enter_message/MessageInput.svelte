<script lang="ts">
    import { onMount, onDestroy, tick } from 'svelte';
    import { Editor } from '@tiptap/core';
    import StarterKit from '@tiptap/starter-kit';
    import { slide } from 'svelte/transition';
    import JSZip from 'jszip';
    import { createEventDispatcher } from 'svelte';
    import { tooltip } from '../../actions/tooltip'; // Assuming this path

    //Import extensions
    import { CustomKeyboardHandling } from './extensions/Keyboard';
    import { CustomPlaceholder } from './extensions/Placeholder';
    import { WebPreview } from './extensions/WebPreview';
    import { MateNode } from './extensions/MateNode';
    import * as EmbedNodes from "./extensions/embeds";

    // Import components
    import CameraView from './CameraView.svelte';
    import RecordAudio from './RecordAudio.svelte';
    import MapsView from './MapsView.svelte';
    import PressAndHoldMenu from './in_message_previews/PressAndHoldMenu.svelte';

    // Import utils
    import {
        formatDuration,
        isLikelyCode,
        detectLanguage,
        isContentEmptyExceptMention,
        hasActualContent,
        getInitialContent,
        convertToMarkdown,
        insertCodeContent,
        insertTextContent,
        extractEpubCover,
        getEpubMetadata,
        isEpubFile,
        isVideoFile,
        isCodeOrTextFile,
        getLanguageFromFilename,
        detectAndReplaceMates,
        detectAndReplaceUrls,
        vibrateMessageField,
        isLargeText
    } from './utils';

    const dispatch = createEventDispatcher();

    // File size limits in MB
    const FILE_SIZE_LIMITS = {
        TOTAL_MAX_SIZE: 100,
        PER_FILE_MAX_SIZE: 100
    };

    const MAX_TOTAL_SIZE = FILE_SIZE_LIMITS.TOTAL_MAX_SIZE * 1024 * 1024;
    const MAX_PER_FILE_SIZE = FILE_SIZE_LIMITS.PER_FILE_MAX_SIZE * 1024 * 1024;

    // Refs
    let fileInput: HTMLInputElement;
    let cameraInput: HTMLInputElement;
    let videoElement: HTMLVideoElement;
    let showCamera = false;
    let showMaps = false;
    let editor: Editor;
    let isMessageFieldFocused = false;
    let editorElement: HTMLElement | undefined = undefined;
    let showMenu = false;
    let menuX = 0;
    let menuY = 0;
    let selectedEmbedId: string | null = null;
    let menuType: 'default' | 'pdf' | 'web' = 'default';
    let showRecordAudio = false;
    let isRecordButtonPressed = false;
    let recordStartPosition = { x: 0, y: 0 };
    let recordStartTimeout: ReturnType<typeof setTimeout> = setTimeout(() => {}, 0);
    let showRecordHint = false;
    let recordHintTimeout: ReturnType<typeof setTimeout>;
    export let isFullscreen = false;
    let isScrollable = false;
    let scrollableContent: HTMLElement;

    // Add prop for default mention
    export let defaultMention: string = 'sophia'; // Or any default

    // Add this near other state variables at the top
    let selectedNode: { node: any; pos: number } | null = null;

    // Add a reactive variable to track content state
    export let hasContent = false; // Exported so parent components can bind to it

    // Add a flag to track menu interaction
    let isMenuInteraction = false;
    let hasRecordingStarted = false; //for the audio recording
    let isRecordingActive = false;
    let recordingStream: MediaStream | null = null; //for the microphone
    let micPermissionGranted: boolean = false;//for microphone

    let messageInputWrapper: HTMLElement; //for monitoring the height

    // --- Function Definitions ---
    // (All your utility functions are now imported from './utils', so no need
    //  to define them here again)
    async function handleDrop(event: DragEvent) {
        event.preventDefault();
        event.stopPropagation();

        editorElement?.classList.remove('drag-over');

        const droppedFiles = Array.from(event.dataTransfer?.files || []);
        if (!droppedFiles.length) return;

        await processFiles(droppedFiles);
    }

    function handleDragOver(event: DragEvent) {
        event.preventDefault();
        event.stopPropagation();
        editorElement?.classList.add('drag-over');
    }

    function handleDragLeave(event: DragEvent) {
        event.preventDefault();
        event.stopPropagation();
        editorElement?.classList.remove('drag-over');
    }
    async function handlePaste(event: ClipboardEvent) {
        // Only handle file pastes here
        const files: File[] = [];
        for (const item of event.clipboardData?.items || []) {
            if (item.type.startsWith('image/') || item.kind === 'file') {
                const file = item.getAsFile();
                if (file) files.push(file);
            }
        }

        if (files.length > 0) {
            event.preventDefault();
            await processFiles(files);
        }
    }

    async function processFiles(files: File[]) {
        const totalSize = files.reduce((sum, file) => sum + file.size, 0);
        if (totalSize > MAX_TOTAL_SIZE) {
            alert(`Total file size exceeds ${FILE_SIZE_LIMITS.TOTAL_MAX_SIZE}MB`);
            return;
        }

        if (editor.isEmpty) {
            editor.commands.setContent({
                type: 'doc',
                content: [{
                    type: 'paragraph',
                    content: [
                        {
                            type: 'mate',
                            attrs: {
                                name: defaultMention,
                                id: crypto.randomUUID()
                            }
                        },
                        {
                            type: 'text',
                            text: ' '
                        }
                    ]
                }]
            });
            await tick();
        }

        for (const file of files) {
            if (file.size > MAX_PER_FILE_SIZE) {
                alert(`File ${file.name} exceeds the size limit of ${FILE_SIZE_LIMITS.PER_FILE_MAX_SIZE}MB`);
                continue;
            }

            editor.commands.focus('end');

            if (isVideoFile(file)) {
                await insertVideo(file, undefined, false);
            } else if (isCodeOrTextFile(file.name)) {
                await insertCodeFile(file);
            } else if (file.type.startsWith('image/')) {
                await insertImage(file);
            } else if (file.type === 'application/pdf') {
                await insertFile(file, 'pdf');
            } else if (file.type.startsWith('audio/')) {
                await insertAudio(file);
            }  else if (isEpubFile(file)) { //check for epub
                await insertEpub(file);
            }else {
                await insertFile(file, 'file');
            }

            editor.commands.insertContent(' ');
        }
    }

    async function insertVideo(file: File, duration?: string, isRecording: boolean = false) {
        const url = URL.createObjectURL(file);
        editor.commands.insertContent([
            {
                type: 'videoEmbed',
                attrs: {
                    type: 'video',
                    src: url,
                    filename: file.name,
                    duration: duration || '00:00',
                    id: crypto.randomUUID(),
                    isRecording
                }
            },
            {
                type: 'text',
                text: ' '
            }
        ]);
         setTimeout(() => {
            editor.commands.focus('end');
        }, 50);
    }
    async function insertImage(file: File, isRecording: boolean = false): Promise<void> {
        const url = URL.createObjectURL(file);
        editor.commands.insertContent([
                {
                    type: 'imageEmbed',
                    attrs: {
                        type: 'image',
                        src: url,
                        filename: file.name,
                        id: crypto.randomUUID(),
                        isRecording
                    }
                },
                {
                    type: 'text',
                    text: ' '
                }
            ]);
        setTimeout(() => {
            editor.commands.focus('end');
        }, 50);
    }

    async function insertFile(file: File, type: 'pdf' | 'file'): Promise<void> {
        const url = URL.createObjectURL(file);
        editor.commands.insertContent([
                {
                    type: type === 'pdf' ? 'pdfEmbed' : 'fileEmbed',
                    attrs: {
                        type,
                        src: url,
                        filename: file.name,
                        id: crypto.randomUUID()
                    }
                },
                {
                    type: 'text',
                    text: ' '
                }
            ]);
        setTimeout(() => {
            editor.commands.focus('end');
        }, 50);
    }

    async function insertAudio(file: File) {
        const url = URL.createObjectURL(file);
        editor.chain()
            .focus()
            .insertContent([
                {
                    type: 'audioEmbed',
                    attrs: {
                        type: 'audio',
                        src: url,
                        filename: file.name,
                        id: crypto.randomUUID()
                    }
                },
                {
                    type: 'text',
                    text: ' '
                }
            ])
            .run();
        setTimeout(() => {
            editor.commands.focus('end');
        }, 50);
    }

    async function insertCodeFile(file: File): Promise<void> {
        const url = URL.createObjectURL(file);
        const language = getLanguageFromFilename(file.name);

        editor
            .chain()
            .focus()
            .insertContent({
                type: 'codeEmbed',
                attrs: {
                    type: 'code',
                    src: url,
                    filename: file.name,
                    language: language,
                    id: crypto.randomUUID()
                }
            })
            .run();
    }
    async function insertEpub(file: File): Promise<void> {
        try {
            const coverUrl = await extractEpubCover(file);
            const epubMetadata = await getEpubMetadata(file);
            const { title, creator } = epubMetadata;

            const bookEmbed = {
                type: 'bookEmbed',
                attrs: {
                    type: 'book',
                    src: URL.createObjectURL(file),
                    filename: file.name,
                    id: crypto.randomUUID(),
                    bookname: title || undefined,
                    author: creator || undefined,
                    coverUrl: coverUrl || undefined
                }
            };
            editor.commands.insertContent([bookEmbed, { type: 'text', text: ' ' }]);

            editor.commands.focus();
        } catch (error) {
            console.error('Error inserting EPUB:', error);
            await insertFile(file, 'file'); // Fallback
        }
    }
    function handleCameraClick() {
        const isMobile = window.matchMedia('(max-width: 768px), (pointer: coarse)').matches &&
                          ('ontouchstart' in window || navigator.maxTouchPoints > 0);

        if (isMobile) {
            cameraInput?.click();
        } else {
            showCamera = true;
        }
    }

    function handleCameraClose() {
        showCamera = false;
    }

    async function handlePhotoCaptured(event: CustomEvent) {
        const { blob } = event.detail;
        const file = new File([blob], `camera_${Date.now()}.jpg`, { type: 'image/jpeg' });
        showCamera = false;
        await new Promise(resolve => setTimeout(resolve, 150));
        await insertImage(file, true);
    }

    async function handleVideoRecorded(event: CustomEvent<{ blob: Blob, duration: string }>) {
        const { blob, duration } = event.detail;
        const file = new File([blob], `video_${Date.now()}.webm`, { type: 'video/webm' });
        await insertVideo(file, duration, true);
        showCamera = false;
    }

    async function handleAudioRecorded(event: CustomEvent) {
        const { blob, duration } = event.detail;
        const url = URL.createObjectURL(blob);
        const filename = `audio_${Date.now()}.webm`;
        const formattedDuration = formatDuration(duration);

        // First check if editor is empty and needs mate node
        if (editor.isEmpty) {
            editor.commands.setContent({
                type: 'doc',
                content: [{
                    type: 'paragraph',
                    content: [
                        {
                            type: 'mate',
                            attrs: {
                                name: defaultMention,
                                id: crypto.randomUUID()
                            }
                        },
                        { type: 'text', text: ' ' }
                    ]
                }]
            });
        }

        // Then insert the recording embed
        editor.chain()
            .focus()
            .insertContent([
                {
                    type: 'recordingEmbed',
                    attrs: {
                        type: 'recording',
                        src: url,
                        filename: filename,
                        duration: formattedDuration,
                        id: crypto.randomUUID()
                    }
                },
                { type: 'text', text: ' ' }
            ])
            .run();

        // Log the editor content after insert
        console.debug('Editor content after recording insert:', {
            html: editor.getHTML(),
            json: editor.getJSON()
        });

        editor.commands.focus();
    }

    function handleLocationClick() {
        showMaps = true;
    }

    async function handleLocationSelected(event: CustomEvent<{
        type: string;
        attrs: {
            type: string;
            src: string;
            filename: string;
            id: string;
        };
    }>) {
        const previewData = event.detail;
        
        // First check if editor is empty and needs mate node
        if (editor.isEmpty) {
            editor.commands.setContent({
                type: 'doc',
                content: [{
                    type: 'paragraph',
                    content: [
                        {
                            type: 'mate',
                            attrs: {
                                name: defaultMention,
                                id: crypto.randomUUID()
                            }
                        },
                        { type: 'text', text: ' ' }
                    ]
                }]
            });
        }

        // Then insert the map embed
        editor.commands.insertContent([
            previewData,
            { type: 'text', text: ' ' }
        ]);

        // Log the editor content after insert
        console.debug('Editor content after map insert:', {
            html: editor.getHTML(),
            json: editor.getJSON()
        });
    }

    function checkScrollable() {
        if (scrollableContent) {
            isScrollable = scrollableContent.scrollHeight > scrollableContent.clientHeight;
        }
    }

    // Function to toggle fullscreen mode
    function toggleFullscreen() {
        isFullscreen = !isFullscreen;
    }

    //For the audio recording
    function handleRecordingLayoutChange(event: CustomEvent<{ active: boolean }>) {
        isRecordingActive = event.detail.active;
    }
    async function preRequestMicAccess(event: MouseEvent | TouchEvent): Promise<void> {
        if (micPermissionGranted) {
            return;
        }
        try {
            const audioStream = await navigator.mediaDevices.getUserMedia({
                audio: { echoCancellation: true, noiseSuppression: true }
            });
            micPermissionGranted = true;
            recordingStream = audioStream;
        } catch (err) {
            console.error('Error requesting microphone access:', err);
        }
    }

    function handleStopRecording(): void {
      showRecordAudio = false;
      if (recordingStream) {
        recordingStream.getTracks().forEach((track) => {
          track.stop();
        });
        recordingStream = null;
      }
    }
    function updateHeight() {
        if (messageInputWrapper) {
            const height = messageInputWrapper.offsetHeight;
            dispatch('heightchange', { height });
        }
    }

    // Add this function to handle press/click on embeds
    function handleEmbedInteraction(event: CustomEvent, embedId: string) {
        editor.state.doc.descendants((node: any, pos: number) => {
            if (node.attrs?.id === embedId) {
                selectedNode = { node, pos };
                return false;
            }
            return true;
        });

        event.preventDefault();
        if (!selectedNode) return;
        isMenuInteraction = true;

        const element = document.getElementById(event.detail.elementId);
        if (!element) return;

        const rect = element.getBoundingClientRect();
        const container = element.closest('.message-field');
        if (!container) return;

        menuX = rect.left - container.getBoundingClientRect().left + (rect.width / 2);
        menuY = rect.top - container.getBoundingClientRect().top;

        selectedEmbedId = embedId;
        showMenu = true;

        const node = selectedNode?.node;
        if (!node) return;

        if (node.type.name === 'webPreview') {
            menuType = 'web';
        } else if (node.attrs?.type === 'pdf') {
            menuType = 'pdf';
        } else {
            menuType = 'default';
        }
    }

        // Add these handlers for the menu actions
    async function handleMenuAction(action: string) {
        if (!selectedNode) return;
        
        const { node } = selectedNode;

        switch (action) {
            case 'delete':
                editor.chain().focus().deleteRange({ from: selectedNode.pos, to: selectedNode.pos + node.nodeSize }).run();
                break;

            case 'download':
                const a = document.createElement('a');
                a.href = node.attrs.src;
                a.download = node.attrs.filename || '';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                break;

            case 'view':
                if (node.type.name === 'codeEmbed') {
                    try {
                        const response = await fetch(node.attrs.src);
                        const code = await response.text();
                        dispatch('codefullscreen', {
                            code,
                            filename: node.attrs.filename,
                            language: node.attrs.language || getLanguageFromFilename(node.attrs.filename)
                        });
                    } catch (error) {
                        console.error('Error loading code content:', error);
                    }
                } else if (node.attrs.src || node.attrs.url || (node.attrs.isYouTube && node.attrs.videoId)) {
                    const url = node.attrs.isYouTube ?
                        `https://www.youtube.com/watch?v=${node.attrs.videoId}` :
                        (node.attrs.src || node.attrs.url);
                    window.open(url, '_blank');
                }
                break;

            case 'copy':
                const urlToCopy = node.attrs.isYouTube ?
                    `https://www.youtube.com/watch?v=${node.attrs.videoId}` :
                    (node.attrs.url || node.attrs.src);

                if (urlToCopy) {
                    await navigator.clipboard.writeText(urlToCopy);
                    const element = document.getElementById(`embed-${selectedEmbedId}`);
                    if (element) {
                        element.classList.add('show-copied');
                        setTimeout(() => element.classList.remove('show-copied'), 2000);
                    }
                }
                break;
        }
        showMenu = false;
        isMenuInteraction = false;
        selectedNode = null;
    }

    // Handle file selection
    function handleFileSelect() {
        fileInput.multiple = true;
        fileInput.click();
    }

    async function onFileSelected(event: Event) {
        const input = event.target as HTMLInputElement;
        if (!input.files?.length) return;
        const files = Array.from(input.files);
        await processFiles(files);
        input.value = ''; // Clear input
    }

    function handleSend() {
        if (!editor || !hasActualContent(editor)) {
            vibrateMessageField();
            return;
        }
        const messagePayload = {
            id: crypto.randomUUID(),
            role: "user",
            messageParts: [] as { type: string; content?: string; url?: string; filename?: string; id?: string; duration?: string; latitude?: number; longitude?: number; address?: string; language?: string; bookname?:string; author?: string; }[]
        };

        editor.state.doc.content.forEach(node => {
            if (node.type.name === 'paragraph') {
                const textContent = node.textContent;
                const markdownContent = convertToMarkdown(textContent);
                messagePayload.messageParts.push({
                    type: 'text',
                    content: markdownContent
                });
            } else if (node.type.name === 'webPreview') {
                messagePayload.messageParts.push({
                    type: 'web',
                    url: node.attrs.url,
                    id: node.attrs.id
                });
            } else if (node.type.name === 'imageEmbed') {
                messagePayload.messageParts.push({
                    type: 'image',
                    filename: node.attrs.filename,
                    id: node.attrs.id
                });
            } else if (node.type.name === 'videoEmbed') {
                messagePayload.messageParts.push({
                  type: 'video',
                  filename: node.attrs.filename,
                  id: node.attrs.id,
                  duration: node.attrs.duration
                });
            } else if (node.type.name === 'mate') {
                const textContent = `@${node.attrs.name} `;
                messagePayload.messageParts.push({
                    type: 'text',
                    content: textContent
                });
            }  else if (node.type.name === 'codeEmbed') {
                messagePayload.messageParts.push({
                    type: 'code',
                    filename: node.attrs.filename,
                    language: node.attrs.language,
                    id: node.attrs.id,
                    content: node.attrs.content // Include code content for LLM
                });
            } else if (node.type.name === 'audioEmbed') {
                messagePayload.messageParts.push({
                    type: 'audio',
                    filename: node.attrs.filename,
                    duration: node.attrs.duration,
                    id: node.attrs.id
                });
            }  else if (node.type.name === 'recordingEmbed') {
                messagePayload.messageParts.push({
                    type: 'audio',
                    filename: node.attrs.filename,
                    duration: node.attrs.duration,
                    id: node.attrs.id
                });
            } else if (node.type.name === 'fileEmbed') {
                messagePayload.messageParts.push({
                    type: 'file',
                    filename: node.attrs.filename,
                    id: node.attrs.id
                });
            } else if (node.type.name === 'pdfEmbed') {
                messagePayload.messageParts.push({
                    type: 'pdf',
                    filename: node.attrs.filename,
                    id: node.attrs.id
                });
            } else if (node.type.name === 'bookEmbed') {
                messagePayload.messageParts.push({
                  type: 'book',
                  filename: node.attrs.filename,
                  id: node.attrs.id,
                  bookname: node.attrs.bookname,
                  author: node.attrs.author
                });
            } else if(node.type.name === 'textEmbed'){
                const textContent = node.attrs.content;
                const markdownContent = convertToMarkdown(textContent);
                messagePayload.messageParts.push({
                    type: 'text',
                    content: markdownContent
                });
            }
        });

        dispatch("sendMessage", messagePayload);
        hasContent = false;
        editor.commands.clearContent();

        setTimeout(() => {
            editor.commands.setContent(getInitialContent());
            editor.commands.focus('end');
            hasContent = false;
        }, 0);
    }
    /**
       * Clears the message input field and resets it to the default state.
       */
    export function clearMessageField() {
        if (!editor) return;
        editor.commands.clearContent();
        hasContent = false;
        setTimeout(() => {
            editor.commands.setContent(getInitialContent());
            editor.commands.focus('end');
            hasContent = false;
        }, 0);
    }
    export function setDraftContent(content: string) {
        if (!editor) return;
        editor.commands.setContent({
            type: 'doc',
            content: [{
                type: 'paragraph',
                content: [
                    { type: 'text', text: content }
                ]
            }]
        });
        editor.commands.focus('end');
    }

    // --- Lifecycle Hooks ---

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
                ...Object.values(EmbedNodes), // Correctly includes all embed nodes
                WebPreview,
                MateNode,
                CustomPlaceholder,
                CustomKeyboardHandling
            ],
            content: getInitialContent(),
             onFocus: () => {
                isMessageFieldFocused = true;
                if (editor.isEmpty) {
                    editor.commands.setContent({
                        type: 'doc',
                        content: [{
                            type: 'paragraph',
                            content: [
                                {
                                    type: 'mate',
                                    attrs: {
                                        name: defaultMention,
                                        id: crypto.randomUUID()
                                    }
                                },
                                {
                                    type: 'text',
                                    text: ' '  // Add space after mention
                                }
                            ]
                        }]
                    });
                    editor.commands.focus('end');
                }
            },
            onBlur: () => {
                isMessageFieldFocused = false;

                if (isMenuInteraction) {
                    return;
                }

                // Replace the existing isEmpty check with a more accurate one
                const hasEmbeds = editor.state.doc.content.content.some(node => 
                    node.content?.content?.some((n: any) => n.type.name.endsWith('Embed'))
                );

                const hasOnlyEmptyParagraph = editor.state.doc.content.size === 2 && 
                    editor.state.doc.content.content[0].type.name === 'paragraph' &&
                    editor.state.doc.content.content[0].content.size === 0;

                // Only reset if we have no embeds and either empty or just a mate mention
                if (!hasEmbeds && (hasOnlyEmptyParagraph || isContentEmptyExceptMention(editor))) {
                    editor.commands.setContent(getInitialContent());
                }
            },
            onUpdate: ({ editor }) => {
                hasContent = !editor.isEmpty && !isContentEmptyExceptMention(editor);
                const content = editor.getHTML(); //still needed for detectAndReplaceUrls and detectAndReplaceMates?
				detectAndReplaceUrls(editor, content);
                detectAndReplaceMates(editor, content);
            }
        });

        // Add global event listener for embed clicks and mate clicks
        document.addEventListener('embedclick', ((event: CustomEvent) => {
            const { id } = event.detail;
            handleEmbedInteraction(event, id);
        }) as EventListener);

        document.addEventListener('mateclick', ((event: CustomEvent) => {
            // Handle the @mention click.  You'll likely want to open a profile
            // or perform some other action related to the mentioned user.
            const { id, elementId } = event.detail;
            console.log('Mate clicked:', id, elementId);
            // Example: dispatch('mateclick', { id });
        }) as EventListener);

        // Add this after editor initialization to auto-focus and add default mention
        setTimeout(() => {
            editor.commands.setContent({
                type: 'doc',
                content: [{
                    type: 'paragraph',
                    content: [
                        {
                            type: 'mate',
                            attrs: {
                                name: defaultMention,
                                id: crypto.randomUUID()
                            }
                        },
                        {
                            type: 'text',
                            text: ' '  // Add space after mention
                        }
                    ]
                }]
            });
            editor.commands.focus('end');
        }, 100); // Small delay

        const resizeObserver = new ResizeObserver(() => {
            checkScrollable();
        });

        if (scrollableContent) {
            resizeObserver.observe(scrollableContent);
        }

        editorElement?.addEventListener('paste', handlePaste);
        // Listen for the custom send event (triggered by the keyboard extension)
        editorElement?.addEventListener('custom-send-message', handleSend as EventListener);

        // Add listener for codefullscreen events
        editorElement?.addEventListener('codefullscreen', ((event: CustomEvent) => {
            dispatch('codefullscreen', event.detail);
        }) as EventListener);

        return () => {
            resizeObserver.disconnect();
            editorElement?.removeEventListener('paste', handlePaste);
             editorElement?.removeEventListener('custom-send-message', handleSend as EventListener);
            document.removeEventListener('embedclick', (() => {}) as EventListener);
            document.removeEventListener('mateclick', (() => {}) as EventListener);
            editorElement?.removeEventListener('codefullscreen', (() => {}) as EventListener);
        };
    });

    onDestroy(() => {
        if (editor) {
            editor.destroy();
        }
        handleCameraClose();
        handleStopRecording(); // Clean up recording resources
        document.removeEventListener('embedclick', (() => {}) as EventListener);
        document.removeEventListener('mateclick', (() => {}) as EventListener);
    });


    // --- Reactive Statements ---

    $: containerStyle = isFullscreen ?
        `height: calc(100vh - 100px); max-height: calc(100vh - 120px); height: calc(100dvh - 100px); max-height: calc(100dvh - 120px);` :
        'height: auto; max-height: 350px;';  // Add default height when not fullscreen
    $: scrollableStyle = isFullscreen ?
        `max-height: calc(100vh - 190px); max-height: calc(100dvh - 190px);` :
        'max-height: 250px;';  // Add default height when not fullscreen

</script>

<div bind:this={messageInputWrapper}>
    <div class="message-field {isMessageFieldFocused ? 'focused' : ''} {isRecordingActive ? 'recording-active' : ''}"
         style={containerStyle}
         on:dragover={handleDragOver}
         on:dragleave={handleDragLeave}
         on:drop={handleDrop}
         role="textbox"
         aria-multiline="true"
         tabindex="0"
    >
        {#if isScrollable || isFullscreen}
            <button
                class="clickable-icon icon_fullscreen fullscreen-button"
                on:click={toggleFullscreen}
                aria-label={isFullscreen ? "Exit Fullscreen" : "Enter Fullscreen"}
            ></button>
        {/if}

        <!-- Hidden file inputs -->
        <input
            bind:this={fileInput}
            type="file"
            on:change={onFileSelected}
            style="display: none"
            multiple
        />

        <input
            bind:this={cameraInput}
            type="file"
            accept="image/*"
            capture="environment"
            on:change={onFileSelected}
            style="display: none"
            multiple
        />

        <div class="scrollable-content"
             bind:this={scrollableContent}
             style={scrollableStyle}>
            <div class="content-wrapper">
                <div
                    bind:this={editorElement}
                    class="editor-content prose"
                ></div>
            </div>
        </div>

        {#if showCamera}
            <CameraView
                bind:videoElement
                on:close={handleCameraClose}
                on:focusEditor={() => {
                    setTimeout(() => {
                        editor?.commands.focus();
                    }, 0);
                }}
                on:photocaptured={handlePhotoCaptured}
                on:videorecorded={handleVideoRecorded}
            />
        {/if}

        <!-- Action buttons -->
        <div class="action-buttons">
            <div class="left-buttons">
                <button
                    class="clickable-icon icon_files"
                    on:click={handleFileSelect}
                    aria-label="Attach Files"
                    use:tooltip
                ></button>
                <button
                    class="clickable-icon icon_maps"
                    on:click={handleLocationClick}
                    aria-label="Share Location"
                    use:tooltip
                ></button>
            </div>
            <div class="right-buttons">
                <button
                    class="clickable-icon icon_camera"
                    on:click|stopPropagation={(e) => {
                        e.preventDefault();
                        handleCameraClick();
                    }}
                    aria-label="Take Photo"
                    use:tooltip
                ></button>

                {#if showRecordHint}
                    <span
                        class="record-hint-inline"
                        transition:slide={{ duration: 200 }}
                    >
                        Press and hold to record
                    </span>
                {/if}

                <button
                    class="record-button {isRecordButtonPressed ? 'recording' : ''}"
                    style="z-index: 901;"
                    on:mousedown={(event) => {
                        if (!micPermissionGranted) {
                            preRequestMicAccess(event);
                            showRecordHint = true;
                            return;
                        }
                        hasRecordingStarted = false;
                        recordStartTimeout = setTimeout(() => {
                            recordStartPosition = {
                                x: event.clientX,
                                y: event.clientY
                            };
                            isRecordButtonPressed = true;
                            showRecordAudio = true;
                            hasRecordingStarted = true;
                            if (showRecordHint) {
                                showRecordHint = false;
                                clearTimeout(recordHintTimeout);
                            }
                        }, 500);
                    }}
                    on:mouseup={() => {
                        if (recordStartTimeout) {
                            clearTimeout(recordStartTimeout);
                            if (!hasRecordingStarted) {
                                showRecordHint = true;
                                clearTimeout(recordHintTimeout);
                                recordHintTimeout = setTimeout(() => {
                                    showRecordHint = false;
                                }, 2000);
                            }
                        }
                        isRecordButtonPressed = false;
                        showRecordAudio = false;
                        hasRecordingStarted = false;
                    }}
                    on:mouseleave={() => {
                        if (isRecordButtonPressed) {
                            isRecordButtonPressed = false;
                            showRecordAudio = false;
                            hasRecordingStarted = false;
                            clearTimeout(recordStartTimeout);
                        }
                    }}
                    on:touchstart|preventDefault={(event) => {
                        if (!micPermissionGranted) {
                            preRequestMicAccess(event);
                            showRecordHint = true;
                            return;
                        }
                        hasRecordingStarted = false;
                        recordStartTimeout = setTimeout(() => {
                            recordStartPosition = {
                                x: event.touches[0].clientX,
                                y: event.touches[0].clientY
                            };
                            isRecordButtonPressed = true;
                            showRecordAudio = true;
                            hasRecordingStarted = true;
                            if (showRecordHint) {
                                showRecordHint = false;
                                clearTimeout(recordHintTimeout);
                            }
                        }, 500);
                    }}
                    on:touchend={() => {
                        if (recordStartTimeout) {
                            clearTimeout(recordStartTimeout);
                        }
                        isRecordButtonPressed = false;
                        showRecordAudio = false;
                        hasRecordingStarted = false;
                    }}
                    aria-label="Record Audio"
                    use:tooltip
                >
                    <div class="clickable-icon icon_recordaudio"></div>
                </button>
                {#if hasContent}
                    <button
                        class="send-button"
                        on:click={handleSend}
                        aria-label="Send"
                    >
                       Send
                    </button>
                {/if}
            </div>
        </div>

        {#if showMenu}
            <PressAndHoldMenu
                x={menuX}
                y={menuY}
                show={showMenu}
                type={menuType}
                isYouTube={selectedNode?.node?.attrs?.isYouTube || false}
                on:close={() => {
                    showMenu = false;
                    isMenuInteraction = false;
                    selectedNode = null;
                }}
                on:delete={() => handleMenuAction('delete')}
                on:download={() => handleMenuAction('download')}
                on:view={() => handleMenuAction('view')}
                on:copy={() => handleMenuAction('copy')}
            />
        {/if}

        {#if showRecordAudio}
            <RecordAudio
                externalStream={recordingStream}
                initialPosition={recordStartPosition}
                on:audiorecorded={handleAudioRecorded}
                on:close={handleStopRecording}
                on:cancel={handleStopRecording}
            />
        {/if}

        {#if showMaps}
            <MapsView
                on:close={() => showMaps = false}
                on:locationselected={handleLocationSelected}
            />
        {/if}
    </div>
</div>

<style>
    /* Rename .message-container to .message-field */
    .message-field {
        width: 100%;
        min-height: 100px;
        max-height: 350px;
        background-color: var(--color-grey-blue);
        border-radius: 24px;
        padding: 0px 0px 60px 0px;
        box-sizing: border-box;
        position: relative;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
        transition: all 0.3s ease-in-out;
        transform-origin: center;
        will-change: transform, padding-bottom, max-height, height;
    }

    /* Add new style for recording active state */
    .message-field.recording-active {
        padding-bottom: 120px; /* Increase padding to make space for recording interface */
        max-height: 420px; /* Increase max-height by the same amount */
    }

    .scrollable-content {
        width: 100%;
        height: 100%;
        max-height: 250px;
        overflow-y: auto;
        position: relative;
        padding-top: 1em;
        scrollbar-width: thin;
        scrollbar-color: color-mix(in srgb, var(--color-grey-100) 20%, transparent) transparent;
        overflow-x: hidden;
        box-sizing: border-box;
        transition: all 0.3s ease-in-out;
    }

    .content-wrapper {
        display: flex;
        flex-direction: column;
        width: 100%;
        box-sizing: border-box;
    }

    @keyframes blink-caret {
        from, to { caret-color: var(--color-font-primary); }
        50% { caret-color: transparent; }
    }

    .action-buttons {
        position: absolute;
        bottom: 1rem;
        left: 1rem;
        right: 1rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
        height: 40px;
    }

    .left-buttons {
        display: flex;
        gap: 1rem;
        align-items: center;
        height: 100%;
    }

    .right-buttons {
        display: flex;
        align-items: center;
        gap: 1rem;
        height: 100%;
    }
    .send-button {
        user-select: none;
        -webkit-user-select: none;
        -moz-user-select: none;
        -ms-user-select: none;
    }

    /* Update icon styles */
    .clickable-icon {
        display: flex;
        align-items: center;
        height: 50px;
        margin-top: 10px;
    }

    /* Update left-buttons style if needed */
    .left-buttons {
        display: flex;
        gap: 1rem;
        align-items: center;
        height: 100%;
    }


    /* Add essential Tiptap styles */
    :global(.editor-content) {
        min-height: 2em;
        padding: 0.5rem;
        box-sizing: border-box;
        overflow-x: hidden;
    }

    :global(.ProseMirror) {
        outline: none;
        white-space: pre-wrap;
        word-wrap: break-word;
        padding: 0.5rem;
        min-height: 2em;
        max-width: 100%;
        box-sizing: border-box;
        overflow-x: hidden;
    }

    :global(.ProseMirror p) {
        margin: 0;
        line-height: 1.5;
        max-width: 100%;
        box-sizing: border-box;
        word-wrap: break-word;
        overflow-wrap: break-word;
    }

    :global(.custom-embed-container) {
        display: inline-block;
        margin: 4px 0;
        vertical-align: bottom;
    }

    /* Remove these conflicting styles */
    :global(.custom-embed) {
        display: none !important;
    }

    :global(.custom-embed img) {
        display: none !important;
    }

    :global(.custom-embed.file) {
        display: none !important;
    }

    :global(.custom-embed.video) {
        display: none !important;
    }

    /* Add new styles for proper embedding */
    :global(.custom-embed-wrapper) {
        display: inline-block;
        margin: 4px 0;
        vertical-align: bottom;
        max-width: 100%;
    }

    :global(.ProseMirror .custom-embed-wrapper) {
        cursor: pointer;
        user-select: none;
    }

    /* Ensure the editor can handle the embeds */
    .editor-content {
        width: 100%;
        min-height: 2em;
        padding: 0.5rem;
        overflow-x: hidden;
    }

    :global(.ProseMirror) {
        outline: none;
        white-space: pre-wrap;
        word-wrap: break-word;
        padding: 0.5rem;
    }

    :global(.ProseMirror p) {
        margin: 0;
        line-height: 1.5;
    }

    /* Add simple embed styles */
    :global(.embedded-image) {
        max-width: 300px;
        max-height: 200px;
        border-radius: 8px;
        margin: 4px 0;
        object-fit: contain;
    }

    :global(.embedded-file) {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        background-color: var(--color-grey-20);
        padding: 8px 16px;
        border-radius: 8px;
        margin: 4px 0;
    }

    :global(.file-icon) {
        font-size: 24px;
    }

    :global(.file-name) {
        font-size: 14px;
        color: var(--color-font-primary);
    }

    /* Remove all custom-embed related styles */
    :global(.custom-embed),
    :global(.custom-embed-wrapper),
    :global(.custom-embed-container) {
        display: none;
    }

    /* Keep essential editor styles */
    .editor-content {
        width: 100%;
        min-height: 2em;
        padding: 0.5rem;
    }

    :global(.ProseMirror) {
        outline: none;
        white-space: pre-wrap;
        word-wrap: break-word;
        min-height: 2em;
        padding: 0.5rem;
        color: var(--color-font-primary);
    }

    :global(.ProseMirror p) {
        margin: 0;
    }

    /* Add new PDF-specific styles */
    :global(.embedded-pdf) {
        display: inline-flex !important;
        background-color: var(--color-grey-20);
        border-radius: 8px;
        padding: 8px 12px;
        margin: 4px 2px;
        max-width: 300px;
    }

    :global(.pdf-content) {
        display: flex;
        align-items: center;
        gap: 8px;
        cursor: pointer;
    }

    :global(.pdf-icon) {
        font-size: 24px;
        flex-shrink: 0;
    }

    :global(.pdf-filename) {
        font-size: 14px;
        color: var(--color-font-primary);
        word-break: break-all;
        max-width: 240px;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    /* Remove conflicting styles */
    :global(.custom-embed),
    :global(.custom-embed-wrapper),
    :global(.custom-embed-container) {
        display: inline-flex !important;
    }

    /* Ensure editor content is visible */
    .editor-content {
        width: 100%;
        min-height: 2em;
        padding: 0.5rem;
        background-color: transparent;
    }

    :global(.ProseMirror) {
        outline: none;
        white-space: pre-wrap;
        word-wrap: break-word;
        min-height: 2em;
        padding: 0.5rem;
        color: var(--color-font-primary);
    }

    /* Remove the old PDF styles */
    :global(.embedded-pdf),
    :global(.pdf-content),
    :global(.pdf-icon),
    :global(.pdf-filename) {
        display: none !important;
    }

    /* Add the new PDF preview styles */
    :global(.pdf-preview-container) {
        width: 300px;
        height: 60px;
        background-color: var(--color-grey-20);
        border-radius: 30px;
        position: relative;
        cursor: pointer;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        transition: background-color 0.2s;
        display: flex;
        align-items: center;
        margin: 4px 0;
    }

    :global(.pdf-preview-container:hover) {
        background-color: var(--color-grey-30);
    }

    :global(.pdf-preview-container .filename-container) {
        position: absolute;
        left: 65px;
        right: 16px;
        min-height: 40px;
        padding: 5px 0;
        display: flex;
        align-items: center;
    }

    :global(.pdf-preview-container .filename) {
        display: -webkit-box;
        -webkit-line-clamp: 2;
        line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
        text-overflow: ellipsis;
        line-height: 1.3;
        font-size: 14px;
        color: var(--color-font-primary);
        width: 100%;
        word-break: break-word;
        max-height: 2.6em;
    }

    /* Add new photo preview styles */
    :global(.photo-preview-container) {
        width: 300px;
        height: 200px;
        border-radius: 30px;
        position: relative;
        overflow: hidden;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        cursor: pointer;
        margin: 4px 0;
    }

    :global(.checkerboard-background) {
        width: 100%;
        height: 100%;
        background-image: linear-gradient(45deg, var(--color-grey-20) 25%, transparent 25%),
                          linear-gradient(-45deg, var(--color-grey-20) 25%, transparent 25%),
                          linear-gradient(45deg, transparent 75%, var(--color-grey-20) 75%),
                          linear-gradient(-45deg, transparent 75%, var(--color-grey-20) 75%);
        background-size: 20px 20px;
        background-position: 0 0, 0 10px, 10px -10px, -10px 0px;
        background-color: var(--color-grey-0);
        display: flex;
        align-items: center;
        justify-content: center;
    }

    :global(.preview-image) {
        display: block;
    }

    :global(.preview-image.fill-container) {
        width: 100%;
        height: 100%;
        object-fit: cover;
    }

    /* Remove old image preview styles */
    :global(.embedded-image) {
        display: none !important;
    }

    /* Add web preview styles */
    :global(.web-preview-container) {
        display: inline-block;
        margin: 4px 0;
        vertical-align: bottom;
    }

    /* Placeholder styling */
    :global(.ProseMirror p.is-editor-empty:first-child::before) {
        content: attr(data-placeholder);
        float: left;
        color: var(--color-font-tertiary);
        pointer-events: none;
        height: auto;
        position: absolute;
        width: 100%;
        text-align: center;
    }

    /* Left align placeholder when focused */
    :global(.ProseMirror.is-focused p.is-editor-empty:first-child::before) {
        text-align: left;
        position: relative;
        float: left;
        width: auto;
        padding-left: 4px;
    }

    :global(.photo-preview-container) {
        cursor: pointer;
        user-select: none;
        -webkit-user-select: none;
    }

    :global(.photo-preview-container:hover) {
        opacity: 0.9;
    }

    :global(.photo-preview-container:active) {
        opacity: 0.8;
    }

    /* Add new styles for mate mentions */
    :global(.mate-mention) {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 2px 4px;
        border-radius: 4px;
        cursor: pointer;
        user-select: none;
    }

    :global(.mate-mention .at-symbol) {
        color: var(--color-font-primary);
        font-weight: 500;
    }

    :global(.mate-mention .mate-profile) {
        width: 24px;
        height: 24px;
        display: inline-block;
        vertical-align: middle;
    }

    :global(.ProseMirror p:first-child) {
        margin-top: 0;
    }

    :global(.ProseMirror p:last-child) {
        margin-bottom: 0;
    }

    /* Update placeholder styling in the style section */
    :global(.ProseMirror p.is-editor-empty:first-child::before) {
        content: attr(data-placeholder);
        float: left;
        color: var(--color-font-tertiary);
        pointer-events: none;
        height: auto;
        position: absolute;
        width: 100%;
        text-align: center;
    }

    /* Update editor content styles */
    .editor-content {
        width: 100%;
        min-height: 2em;
        padding: 0.5rem;
        position: relative;
    }

    :global(.ProseMirror) {
        outline: none;
        white-space: pre-wrap;
        word-wrap: break-word;
        min-height: 2em;
        padding: 0.5rem;
        color: var(--color-font-primary);
    }

    /* Add this new style to ensure placeholder text is visible */
    :global(.ProseMirror.is-editor-empty:first-child::before) {
        opacity: 1;
        display: block;
    }

    /* Add animation styles */
    @keyframes shake {
        0%, 100% { transform: translateX(0); }
        25% { transform: translateX(-4px); }
        75% { transform: translateX(4px); }
    }

    .record-button {
        position: relative;
        border: none;
        cursor: pointer;
        background: none;
        display: flex;
        align-items: center;
        justify-content: center;
        width: 25px;
        height: 50px;
        min-width: 25px;
        padding: 0;
        margin-top: 10px;
    }

    .record-button::before {
        content: '';
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        width: 0;
        height: 0;
        border-radius: 50%;
        background: var(--color-app-audio);
        transition: all 0.3s ease-out;
        z-index: -1;
        opacity: 0;
    }

    .record-button.recording::before {
        width: 60px;
        height: 60px;
        opacity: 1;
    }

    .record-button .clickable-icon {
        margin: 0;
        padding: 0;
        position: relative;
        z-index: 1;
        width: 25px;
        height: 25px;
        transition: background-color 0.3s ease-out;
    }

    .record-button.recording .clickable-icon {
        background-color: white;
    }

    /* Add new inline hint style */
    .record-hint-inline {
        font-size: 14px;
        color: var(--color-font-secondary);
        white-space: nowrap;
        padding: 4px 8px;
        background: var(--color-grey-20);
        border-radius: 12px;
        margin-top: 10px;
        display: inline-block;
    }

    /* Update right-buttons to handle inline elements */
    .right-buttons {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        height: 100%;
        flex-wrap: nowrap;
    }

    .fullscreen-button {
        position: absolute;  /* Change back to absolute since it's relative to message-container */
        top: 0;
        right: 20px;
        opacity: 0.5;
        transition: opacity 0.2s ease-in-out;
        z-index: 1000;
    }

    .fullscreen-button:hover {
        opacity: 1;
    }

    /* Add drag & drop styles */
    :global(.drag-over) {
        background-color: var(--color-grey-20) !important;
        border: 2px dashed var(--color-primary) !important;
        border-radius: 12px;
    }

    :global(.drag-over::after) {
        content: 'Drop files here';
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        font-size: 1.2em;
        color: var(--color-font-secondary);
        pointer-events: none;
    }

    /* Update editor content styles to handle drag & drop visual feedback */
    .editor-content {
        width: 100%;
        min-height: 2em;
        padding: 0.5rem;
        position: relative;
        transition: all 0.2s ease-in-out;
    }
</style>
