<script lang="ts">
    import { onMount, onDestroy, tick, mount } from 'svelte';
    import { Editor } from '@tiptap/core';
    import StarterKit from '@tiptap/starter-kit';
    import { Node } from '@tiptap/core';
    import Web from './in_message_previews/Web.svelte';
    import { _ } from 'svelte-i18n';
    import type { SvelteComponent } from 'svelte';
    import Placeholder from '@tiptap/extension-placeholder';
    import type { Editor as EditorType } from '@tiptap/core';
    import { EditorView } from 'prosemirror-view';
    import { Extension } from '@tiptap/core';
    import PressAndHoldMenu from './in_message_previews/PressAndHoldMenu.svelte';
    import CameraView from './CameraView.svelte';
    import RecordAudio from './RecordAudio.svelte';
    import { slide } from 'svelte/transition';
    import Photos from './in_message_previews/Photos.svelte';
    import PDF from './in_message_previews/PDF.svelte';
    import Audio from './in_message_previews/Audio.svelte';
    import FilePreview from './in_message_previews/File.svelte';
    import Code from './in_message_previews/Code.svelte';
    import Videos from './in_message_previews/Videos.svelte';

    // File size limits in MB
    const FILE_SIZE_LIMITS = {
        TOTAL_MAX_SIZE: 100,
        PER_FILE_MAX_SIZE: 100
    };

    const MAX_TOTAL_SIZE = FILE_SIZE_LIMITS.TOTAL_MAX_SIZE * 1024 * 1024;
    const MAX_PER_FILE_SIZE = FILE_SIZE_LIMITS.PER_FILE_MAX_SIZE * 1024 * 1024;

    // References for file inputs
    let fileInput: HTMLInputElement;
    let cameraInput: HTMLInputElement;
    let videoElement: HTMLVideoElement;
    let stream: MediaStream | null = null;
    let showCamera = false;
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
    let isFullscreen = false;
    let isScrollable = false;
    let scrollableContent: HTMLElement;

    // Add this constant near the top of the file, after the imports
    const VALID_MATES = [
        'burton',
        'lisa', 
        'sophia',
        'melvin',
        'finn',
        'elton',
        'denise',
        'mark',
        'colin'
    ];

    // Custom node for embedded content (images, files, etc.)
    const CustomEmbed = Node.create({
        name: 'customEmbed',
        group: 'inline',
        inline: true,
        selectable: true,
        draggable: true,

        addAttributes() {
            return {
                type: { default: 'image' },
                src: { default: null },
                filename: { default: null },
                id: { default: () => crypto.randomUUID() },
                duration: { default: null },
                language: { default: null }
            }
        },

        parseHTML() {
            return [{ tag: 'div[data-type="custom-embed"]' }]
        },

        renderHTML({ HTMLAttributes }) {
            const elementId = `embed-${HTMLAttributes.id}`;
            const container = document.createElement('div');
            
            if (HTMLAttributes.type === 'image') {
                mount(Photos, {
                    target: container,
                    props: {
                        src: HTMLAttributes.src,
                        filename: HTMLAttributes.filename,
                        id: HTMLAttributes.id
                    }
                });
                return container;
            } else if (HTMLAttributes.type === 'video') {
                mount(Videos, {
                    target: container,
                    props: {
                        src: HTMLAttributes.src,
                        filename: HTMLAttributes.filename,
                        id: HTMLAttributes.id,
                        duration: HTMLAttributes.duration || '00:00'
                    }
                });
                return container;
            } else if (HTMLAttributes.type === 'pdf') {
                mount(PDF, {
                    target: container,
                    props: {
                        src: HTMLAttributes.src,
                        filename: HTMLAttributes.filename,
                        id: HTMLAttributes.id
                    }
                });
                return container;
            } else if (HTMLAttributes.type === 'audio' || HTMLAttributes.type === 'recording') {
                mount(Audio, {
                    target: container,
                    props: {
                        src: HTMLAttributes.src,
                        filename: HTMLAttributes.filename,
                        id: HTMLAttributes.id,
                        duration: HTMLAttributes.duration || '00:00',
                        type: HTMLAttributes.type
                    }
                });
                return container;
            } else if (HTMLAttributes.type === 'file') {
                mount(FilePreview, {
                    target: container,
                    props: {
                        src: HTMLAttributes.src,
                        filename: HTMLAttributes.filename,
                        id: HTMLAttributes.id
                    }
                });
                return container;
            } else if (HTMLAttributes.type === 'code') {
                mount(Code, {
                    target: container,
                    props: {
                        src: HTMLAttributes.src,
                        filename: HTMLAttributes.filename,
                        id: HTMLAttributes.id,
                        language: HTMLAttributes.language
                    }
                });
                return container;
            }
            
            // Default fallback
            return ['div', { 
                class: 'embedded-unknown',
                'data-id': HTMLAttributes.id,
                id: elementId
            }, HTMLAttributes.filename];
        }
    });

    // Add URL detection regex
    const urlRegex = /https?:\/\/[^\s]+\.[a-z]{2,}(?:\/[^\s]*)?/gi;

    // Add new WebPreview node type
    const WebPreview = Node.create({
        name: 'webPreview',
        group: 'inline',
        inline: true,
        selectable: true,
        draggable: true,

        addAttributes() {
            return {
                url: { default: null },
                id: { default: () => crypto.randomUUID() }
            }
        },

        parseHTML() {
            return [{ tag: 'div[data-type="web-preview"]' }]
        },

        renderHTML({ HTMLAttributes }) {
            const elementId = `embed-${HTMLAttributes.id}`;
            const container = document.createElement('div');

            // Set container attributes
            container.setAttribute('data-type', 'web-preview');
            container.setAttribute('data-url', HTMLAttributes.url);
            container.setAttribute('data-id', HTMLAttributes.id);
            container.setAttribute('id', elementId);
            container.className = 'web-preview-container';

            // Mount Web component
            mount(Web, {
                target: container,
                props: { url: HTMLAttributes.url, id: HTMLAttributes.id }
            });

            // Add click handler
            container.onclick = () => {
                document.dispatchEvent(new CustomEvent('embedclick', { 
                    bubbles: true, 
                    detail: { 
                        id: HTMLAttributes.id,
                        elementId: elementId
                    }
                }));
            };

            return container;
        },

        // Keep keyboard shortcuts handler
        addKeyboardShortcuts() {
            return {
                Backspace: ({ editor }) => {
                    const { empty, $anchor } = editor.state.selection
                    if (!empty) return false

                    const pos = $anchor.pos
                    const node = editor.state.doc.nodeAt(pos - 1)

                    if (node?.type.name === 'webPreview') {
                        const url = node.attrs.url
                        const from = pos - node.nodeSize
                        const to = pos

                        // First delete any preceding space
                        const beforeNode = editor.state.doc.textBetween(Math.max(0, from - 1), from)
                        const extraOffset = beforeNode === ' ' ? 1 : 0

                        editor
                            .chain()
                            .focus()
                            .deleteRange({ from: from - extraOffset, to })
                            .insertContent(url)
                            .run()

                        return true
                    }
                    return false
                }
            }
        },

        addNodeView() {
            return ({ node, HTMLAttributes, getPos }) => {
                const dom = document.createElement('div')
                dom.setAttribute('data-type', 'web-preview')

                const component = mount(Web, {
                    target: dom,
                    props: { url: node.attrs.url, id: node.attrs.id },
                    events: {
                        delete: () => {
                            if (typeof getPos === 'function') {
                                const pos = getPos()
                                const beforeNode = editor.state.doc.textBetween(Math.max(0, pos - 1), pos)
                                const extraOffset = beforeNode === ' ' ? 1 : 0

                                editor
                                    .chain()
                                    .focus()
                                    .deleteRange({ from: pos - extraOffset, to: pos + node.nodeSize })
                                    .insertContent(node.attrs.url)
                                    .run()
                            }
                        }
                    }
                })

                return {
                    dom,
                    destroy: () => {
                        // Component cleanup handled automatically in Svelte 5
                    }
                }
            }
        }
    });

    // Move MateNode definition to the top level, near other node definitions
    const MateNode = Node.create({
        name: 'mate',
        group: 'inline',
        inline: true,
        selectable: true,
        draggable: true,

        addAttributes() {
            return {
                name: { default: null },
                id: { default: () => crypto.randomUUID() }
            }
        },

        parseHTML() {
            return [{ tag: 'span[data-type="mate"]' }]
        },

        renderHTML({ HTMLAttributes }) {
            const elementId = `mate-${HTMLAttributes.id}`;
            return [
                'span',
                {
                    'data-type': 'mate',
                    'data-id': HTMLAttributes.id,
                    'data-name': HTMLAttributes.name,
                    id: elementId,
                    class: 'mate-mention',
                    onclick: `document.dispatchEvent(new CustomEvent('mateclick', { 
                        bubbles: true, 
                        detail: { 
                            id: '${HTMLAttributes.id}',
                            elementId: '${elementId}'
                        }
                    }))`,
                },
                ['span', { class: 'at-symbol' }, '@'],
                ['div', { 
                    class: `mate-profile mate-profile-small ${HTMLAttributes.name}`
                }]
            ];
        },

        // Add keyboard shortcuts handler
        addKeyboardShortcuts() {
            return {
                Backspace: ({ editor }) => {
                    const { empty, $anchor } = editor.state.selection
                    if (!empty) return false

                    const pos = $anchor.pos
                    const node = editor.state.doc.nodeAt(pos - 1)

                    if (node?.type.name === 'mate') {
                        const name = node.attrs.name
                        const from = pos - node.nodeSize
                        const to = pos

                        // First delete any preceding space
                        const beforeNode = editor.state.doc.textBetween(Math.max(0, from - 1), from)
                        const extraOffset = beforeNode === ' ' ? 1 : 0

                        editor
                            .chain()
                            .focus()
                            .deleteRange({ from: from - extraOffset, to })
                            .insertContent(`@${name}`)
                            .run()

                        return true
                    }
                    return false
                }
            }
        }
    });

    // Add this function to detect and replace mate mentions
    function detectAndReplaceMates(content: string) {
        if (!editor) return;

        // Get current cursor position
        const { from } = editor.state.selection;
        
        // Get the text content up to the cursor
        const text = editor.state.doc.textBetween(Math.max(0, from - 1000), from);
        
        // Only process if content ends with space or newline
        const lastChar = text.slice(-1);
        if (lastChar !== ' ' && lastChar !== '\n') return;

        // Match @username pattern
        const mateRegex = /@(\w+)(?=\s|$)/g;  // Match @ followed by word chars
        const matches = Array.from(text.matchAll(mateRegex));
        if (!matches.length) return;
        
        // Get the last match
        const lastMatch = matches[matches.length - 1];
        const mateName = lastMatch[1].toLowerCase(); // Convert to lowercase for comparison
        
        // Only process known mates
        if (!VALID_MATES.includes(mateName)) return;

        // Calculate absolute positions
        const matchStart = from - (text.length - lastMatch.index!);
        const matchEnd = matchStart + lastMatch[0].length;

        // Check if this mention is already a mate node
        const nodeAtPos = editor.state.doc.nodeAt(matchStart);
        if (nodeAtPos?.type.name === 'mate') return;

        // Replace text with mate node
        editor
            .chain()
            .focus()
            .deleteRange({ from: matchStart, to: matchEnd })
            .insertContent([
                {
                    type: 'mate',
                    attrs: { 
                        name: mateName,
                        id: crypto.randomUUID()
                    }
                },
                {
                    type: 'text',
                    text: ' '  // Add space after mention
                }
            ])
            .run();
    }

    // Add this helper function to check if content is empty except for mate mention
    function isContentEmptyExceptMention(editor: Editor): boolean {
        let hasOnlyMention = true;
        let mentionCount = 0;
        
        editor.state.doc.descendants((node) => {
            if (node.type.name === 'mate') {
                mentionCount++;
            } else if (node.type.name === 'text') {
                // Only consider non-whitespace text as content
                if (node.text?.trim()) {
                    hasOnlyMention = false;
                }
            } else if (node.type.name !== 'paragraph') {
                hasOnlyMention = false;
            }
        });
        
        // Return true only if we have exactly one mention and no other content
        return hasOnlyMention && mentionCount === 1;
    }

    // Update the Placeholder extension configuration
    const placeholderExtension = Placeholder.configure({
        placeholder: ({ editor }: { editor: EditorType }) => {
            // Show placeholder when:
            // 1. Editor is completely empty (no content at all) AND not focused
            // 2. Editor only contains a mate mention (considered empty) AND not focused
            return (editor.isEmpty || isContentEmptyExceptMention(editor)) && !isMessageFieldFocused 
                ? $_('enter_message.click_to_enter_message.text') 
                : '';
        },
        emptyEditorClass: 'is-editor-empty',
        showOnlyWhenEditable: true,
    });

    // Add this new function to manage initial content
    function getInitialContent() {
        return {
            type: 'doc',
            content: [{
                type: 'paragraph',
                content: []  // Start with empty content
            }]
        };
    }

    // Update this helper function to check for actual content
    function hasActualContent(editor: Editor): boolean {
        if (!editor) return false;
        
        // First check if editor is completely empty
        if (editor.isEmpty) return false;
        
        // If not empty, check if it only contains a mate mention
        return !isContentEmptyExceptMention(editor);
    }

    // Add vibration function
    function vibrateMessageField() {
        const container = document.querySelector('.message-container');
        if (!container) return;
        
        container.animate([
            { transform: 'translateX(-4px)' },
            { transform: 'translateX(4px)' },
            { transform: 'translateX(-4px)' },
            { transform: 'translateX(4px)' },
            { transform: 'translateX(0)' }
        ], {
            duration: 200,
            easing: 'ease-in-out'
        });
        
        // Also trigger device vibration if available
        if (navigator.vibrate) {
            navigator.vibrate(100);
        }
    }

    // Update the keyboard shortcuts extension configuration
    const keyboardExtension = Extension.create({
        name: 'customKeyboardHandling',
        priority: 1000,
        addKeyboardShortcuts() {
            return {
                Enter: ({ editor }) => {
                    if (hasActualContent(editor)) {
                        handleSend();
                    } else {
                        vibrateMessageField();
                    }
                    return true;
                },
                'Shift-Enter': ({ editor }) => {
                    editor.commands.setHardBreak();
                    return true;
                }
            }
        }
    });

    // Add a reactive variable to track content state
    let hasContent = false;

    // Add a flag to track menu interaction
    let isMenuInteraction = false;

    // Add a new variable to track if recording has started
    let hasRecordingStarted = false;

    let isRecordingActive = false;
    
    // Add handler for layout changes
    function handleRecordingLayoutChange(event: CustomEvent<{ active: boolean }>) {
        isRecordingActive = event.detail.active;
    }

    // Add function to check if content is scrollable
    function checkScrollable() {
        if (scrollableContent) {
            isScrollable = scrollableContent.scrollHeight > scrollableContent.clientHeight;
        }
    }

    // Add these new functions for drag & drop and paste handling
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

    async function handleDrop(event: DragEvent) {
        event.preventDefault();
        event.stopPropagation();
        
        editorElement?.classList.remove('drag-over');
        
        // Get dropped files
        const droppedFiles = Array.from(event.dataTransfer?.files || []);
        if (!droppedFiles.length) return;

        await processFiles(droppedFiles);
    }

    async function handlePaste(event: ClipboardEvent) {
        const items = Array.from(event.clipboardData?.items || []);
        const files: File[] = [];

        // Check for files in clipboard
        for (const item of items) {
            // Handle images from clipboard
            if (item.type.startsWith('image/')) {
                const file = item.getAsFile();
                if (file) files.push(file);
                continue;
            }

            // Handle text content separately to avoid duplicating it
            // (since TipTap will handle text paste automatically)
            if (item.type === 'text/plain') {
                continue;
            }

            // Handle other file types
            if (item.kind === 'file') {
                const file = item.getAsFile();
                if (file) files.push(file);
            }
        }

        if (files.length > 0) {
            event.preventDefault(); // Prevent default paste only if we have files
            await processFiles(files);
        }
    }

    // Common function to process files from drag & drop or paste
    async function processFiles(files: File[]) {
        console.log('Processing files:', files.map(f => ({ name: f.name, type: f.type })));

        const totalSize = files.reduce((sum, file) => sum + file.size, 0);
        if (totalSize > MAX_TOTAL_SIZE) {
            alert($_('enter_message.file_size_limits.total_exceeded.text', {
                size: FILE_SIZE_LIMITS.TOTAL_MAX_SIZE,
                current: (totalSize / 1024 / 1024).toFixed(1),
                attempted: (totalSize / 1024 / 1024).toFixed(1)
            } as any));
            return;
        }

        // Process each file
        for (const file of files) {
            if (file.size > MAX_PER_FILE_SIZE) {
                alert($_('enter_message.file_size_limits.per_file_exceeded.text', {
                    size: FILE_SIZE_LIMITS.PER_FILE_MAX_SIZE,
                    filename: file.name,
                    filesize: (file.size / 1024 / 1024).toFixed(1)
                } as any));
                continue;
            }

            console.log('Processing file:', file.name);
            
            // Check if it's a video file first
            if (isVideoFile(file)) {
                console.log('Handling as video:', file.name);
                await insertVideo(file, undefined);
            } else if (isCodeOrTextFile(file.name)) {
                await insertCodeFile(file);
            } else if (file.type.startsWith('image/')) {
                await insertImage(file);
            } else if (file.type === 'application/pdf') {
                await insertFile(file, 'pdf');
            } else if (file.type.startsWith('audio/')) {
                await insertAudio(file);
            } else {
                console.log('Falling back to generic file handler for:', file.name);
                await insertFile(file, 'file');
            }
            
            // Add a space after each insert
            editor.commands.insertContent(' ');
        }
    }

    onMount(() => {
        // Wait for element to be available
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
                CustomEmbed,
                WebPreview,
                MateNode,
                placeholderExtension,
                keyboardExtension
            ],
            content: getInitialContent(),
            onFocus: () => {
                isMessageFieldFocused = true;
                // Add the mate mention only when focusing an empty editor
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
                
                // Don't clear content if we're interacting with the menu
                if (isMenuInteraction) {
                    return;
                }
                
                // Check if editor is truly empty (no content, no embeds, no files)
                const isEmpty = editor.isEmpty || (
                    editor.state.doc.textContent.trim() === '' && 
                    !editor.state.doc.content.content.some(node => 
                        node.content?.content?.some((n: any) => 
                            ['customEmbed', 'webPreview'].includes(n.type.name)
                        )
                    )
                );

                if (isEmpty) {
                    // Clear any remaining content and ensure it's completely empty
                    editor.commands.setContent(getInitialContent());
                }
            },
            onUpdate: ({ editor }) => {
                // Update hasContent whenever editor content changes
                hasContent = !editor.isEmpty && !isContentEmptyExceptMention(editor);
                
                const content = editor.getHTML();
                detectAndReplaceUrls(content);
                detectAndReplaceMates(content);
            }
        });

        // Add global event listener for embed clicks
        document.addEventListener('embedclick', ((event: CustomEvent) => {
            const { id } = event.detail;
            handleEmbedInteraction(event, id);
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
        }, 100); // Small delay to ensure editor is fully initialized

        const resizeObserver = new ResizeObserver(() => {
            checkScrollable();
        });

        if (scrollableContent) {
            resizeObserver.observe(scrollableContent);
        }

        // Add paste event listener to editor element
        editorElement?.addEventListener('paste', handlePaste);

        return () => {
            resizeObserver.disconnect();
            editorElement?.removeEventListener('paste', handlePaste);
        };
    });

    // Update the URL detection and replacement function
    function detectAndReplaceUrls(content: string) {
        if (!editor) return;

        // Get current cursor position
        const { from } = editor.state.selection;
        
        // Get the text content up to the cursor
        const text = editor.state.doc.textBetween(Math.max(0, from - 1000), from);
        
        // Only process if content ends with space or newline
        const lastChar = text.slice(-1);
        if (lastChar !== ' ' && lastChar !== '\n') return;

        // Find the last URL before the cursor
        const matches = Array.from(text.matchAll(urlRegex));
        if (!matches.length) return;
        
        // Get the last match
        const lastMatch = matches[matches.length - 1];
        const url = lastMatch[0];
        
        // Calculate absolute positions
        const matchStart = from - text.length + lastMatch.index!;
        const matchEnd = matchStart + url.length;

        // Check if this URL is already a web preview
        const nodeAtPos = editor.state.doc.nodeAt(matchStart);
        if (nodeAtPos?.type.name === 'webPreview') return;

        // Replace URL with web preview node
        editor
            .chain()
            .focus()
            .deleteRange({ from: matchStart, to: matchEnd })
            .insertContent({
                type: 'webPreview',
                attrs: { 
                    url,
                    id: crypto.randomUUID()
                }
            })
            .run();
    }

    onDestroy(() => {
        if (editor) {
            editor.destroy();
        }
        handleCameraClose();
        document.removeEventListener('embedclick', (() => {}) as EventListener);
    });

    // Handle file selection
    function handleFileSelect() {
        fileInput.multiple = true;
        fileInput.click();
    }

    async function onFileSelected(event: Event) {
        const input = event.target as HTMLInputElement;
        if (!input.files?.length) return;

        const files = Array.from(input.files);
        console.log('Selected files:', files.map(f => ({ name: f.name, type: f.type })));

        const totalSize = files.reduce((sum, file) => sum + file.size, 0);

        if (totalSize > MAX_TOTAL_SIZE) {
            alert($_('enter_message.file_size_limits.total_exceeded.text', {
                size: FILE_SIZE_LIMITS.TOTAL_MAX_SIZE,
                current: (totalSize / 1024 / 1024).toFixed(1),
                attempted: (totalSize / 1024 / 1024).toFixed(1)
            } as any));
            return;
        }

        // Process each file sequentially
        for (const file of files) {
            if (file.size > MAX_PER_FILE_SIZE) {
                alert($_('enter_message.file_size_limits.per_file_exceeded.text', {
                    size: FILE_SIZE_LIMITS.PER_FILE_MAX_SIZE,
                    filename: file.name,
                    filesize: (file.size / 1024 / 1024).toFixed(1)
                } as any));
                continue;
            }

            console.log('Processing file:', file.name);
            
            // Check if it's a video file first
            if (isVideoFile(file)) {
                console.log('Handling as video:', file.name);
                await insertVideo(file, undefined);
            } else if (isCodeOrTextFile(file.name)) {
                await insertCodeFile(file);
            } else if (file.type.startsWith('image/')) {
                await insertImage(file);
            } else if (file.type === 'application/pdf') {
                await insertFile(file, 'pdf');
            } else if (file.type.startsWith('audio/')) {
                await insertAudio(file);
            } else {
                console.log('Falling back to generic file handler for:', file.name);
                await insertFile(file, 'file');
            }
            
            // Add a space after each insert
            editor.commands.insertContent(' ');
        }

        // Clear the input
        input.value = '';
    }

    // Update the isCodeOrTextFile function to include Dockerfile detection
    function isCodeOrTextFile(filename: string): boolean {
        // First check for Dockerfile (case-insensitive)
        if (filename.toLowerCase() === 'dockerfile') {
            return true;
        }

        const codeExtensions = [
            'py', 'js', 'ts', 'html', 'css', 'json', 'svelte',
            'java', 'cpp', 'c', 'rs', 'go', 'rb', 'php', 'swift',
            'kt', 'txt', 'md', 'xml', 'yaml', 'yml', 'sh', 'bash',
            'sql', 'vue', 'jsx', 'tsx', 'scss', 'less', 'sass',
            'dockerfile'  // Add dockerfile extension support
        ];
        
        const extension = filename.split('.').pop()?.toLowerCase();
        return extension ? codeExtensions.includes(extension) : false;
    }

    // Update getLanguageFromFilename to include Dockerfile
    function getLanguageFromFilename(filename: string): string {
        // Special case for Dockerfile (no extension)
        if (filename.toLowerCase() === 'dockerfile') {
            return 'dockerfile';
        }

        const ext = filename.split('.').pop()?.toLowerCase() || '';
        const languageMap: { [key: string]: string } = {
            'py': 'python',
            'js': 'javascript',
            'ts': 'typescript',
            'html': 'html',
            'css': 'css',
            'json': 'json',
            'svelte': 'svelte',
            'java': 'java',
            'cpp': 'cpp',
            'c': 'c',
            'rs': 'rust',
            'go': 'go',
            'rb': 'ruby',
            'php': 'php',
            'swift': 'swift',
            'kt': 'kotlin',
            'md': 'markdown',
            'xml': 'xml',
            'yaml': 'yaml',
            'yml': 'yaml',
            'sh': 'bash',
            'bash': 'bash',
            'sql': 'sql',
            'vue': 'vue',
            'jsx': 'javascript',
            'tsx': 'typescript',
            'scss': 'scss',
            'less': 'less',
            'sass': 'sass',
            'dockerfile': 'dockerfile'  // Add dockerfile mapping
        };
        return languageMap[ext] || 'plaintext';
    }

    // Add function to insert code files
    async function insertCodeFile(file: File): Promise<void> {
        console.log('Inserting code file:', file.name);
        const url = URL.createObjectURL(file);
        const language = getLanguageFromFilename(file.name);

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
                        },
                        {
                            type: 'customEmbed',
                            attrs: {
                                type: 'code',
                                src: url,
                                filename: file.name,
                                language: language,
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
        } else {
            editor
                .chain()
                .focus()
                .insertContent({
                    type: 'customEmbed',
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
    }

    async function insertImage(file: File): Promise<void> {
        const url = URL.createObjectURL(file);
        
        if (editor.isEmpty) {
            // If empty, first insert default mention
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
                        },
                        {
                            type: 'customEmbed',
                            attrs: {
                                type: 'image',
                                src: url,
                                filename: file.name,
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
        } else {
            editor.commands.insertContent([
                {
                    type: 'customEmbed',
                    attrs: {
                        type: 'image',
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
        }

        // Force focus and set cursor position after a short delay
        setTimeout(() => {
            editor.commands.focus('end');
        }, 50);
    }

    async function insertFile(file: File, type: 'pdf' | 'file'): Promise<void> {
        console.log(`Inserting ${type} file:`, file.name);
        const url = URL.createObjectURL(file);
        
        if (editor.isEmpty) {
            // If empty, first insert default mention
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
                        },
                        {
                            type: 'customEmbed',
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
                    ]
                }]
            });
        } else {
            editor.commands.insertContent([
                {
                    type: 'customEmbed',
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
        }

        // Force focus and set cursor position after a short delay
        setTimeout(() => {
            editor.commands.focus('end');
        }, 50);
    }

    async function insertAudio(file: File) {
        console.log('Inserting audio:', file.name);
        const url = URL.createObjectURL(file);
        
        if (editor.isEmpty) {
            // If empty, first insert default mention
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
                        },
                        {
                            type: 'customEmbed',
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
                    ]
                }]
            });
        } else {
            editor.chain()
                .focus()
                .insertContent([
                    {
                        type: 'customEmbed',
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
        }
        
        // Replace the old cursor positioning with the working timeout focus
        setTimeout(() => {
            editor.commands.focus('end');
        }, 50);
    }

    function handleCameraClick() {
        showCamera = true;
    }

    function handleCameraClose() {
        showCamera = false;
    }

    async function handlePhotoCaptured(event: CustomEvent) {
        const { blob } = event.detail;
        const file = new File([blob], `camera_${Date.now()}.jpg`, { type: 'image/jpeg' });
        showCamera = false;
        // Wait for camera to fully close
        await new Promise(resolve => setTimeout(resolve, 150));
        await insertImage(file);
    }

    async function handleVideoRecorded(event: CustomEvent<{ blob: Blob, duration: string }>) {
        const { blob, duration } = event.detail;
        const file = new File([blob], `video_${Date.now()}.webm`, { type: 'video/webm' });
        await insertVideo(file, duration);
        showCamera = false;
    }

    // Update the handleSend button click handler in the template
    function handleSend() {
        if (!editor || !hasActualContent(editor)) {
            vibrateMessageField();
            return;
        }
        
        let markdown = '';
        let isFirstParagraph = true;
        let lastNodeWasEmbed = false;
        let lastNodeWasMate = false;
        
        // Process the document directly using editor's state
        editor.state.doc.descendants((node, pos) => {
            if (node.type.name === 'paragraph') {
                // Add newline between paragraphs, but not before the first one
                // Also don't add extra newline if last node was an embed
                if (!isFirstParagraph && !lastNodeWasEmbed) {
                    markdown += '\n';
                }
                isFirstParagraph = false;
                lastNodeWasEmbed = false;
                lastNodeWasMate = false;

                // Track if we've added content to this paragraph
                let hasContent = false;

                node.content.forEach((child: any, pos: number, index: number) => {
                    if (child.type.name === 'mate') {
                        markdown += `@${child.attrs.name}`;
                        // Always add a space after mate mention if next node exists and is text
                        const nextNode = child.nextSibling;
                        if (nextNode && nextNode.type.name === 'text' && !nextNode.text?.startsWith(' ')) {
                            markdown += ' ';
                        }
                        hasContent = true;
                        lastNodeWasEmbed = false;
                        lastNodeWasMate = true;
                    } else if (child.type.name === 'webPreview') {
                        // Add space after mate if previous node was mate
                        if (lastNodeWasMate) {
                            markdown += ' ';
                        }
                        markdown += `${child.attrs.url}\n`;  // Add newline after web preview
                        hasContent = true;
                        lastNodeWasEmbed = true;
                        lastNodeWasMate = false;
                    } else if (child.type.name === 'customEmbed') {
                        // Add space after mate if previous node was mate
                        if (lastNodeWasMate) {
                            markdown += ' ';
                        }
                        const { type, filename } = child.attrs;
                        if (type === 'image' || type === 'pdf') {
                            markdown += `[${filename}]\n`;  // Add newline after image/pdf
                            hasContent = true;
                            lastNodeWasEmbed = true;
                            lastNodeWasMate = false;
                        }
                    } else if (child.type.name === 'text') {
                        // Only add space before text if it doesn't start with space and previous node was mate
                        if (lastNodeWasMate && child.text && !child.text.startsWith(' ')) {
                            markdown += ' ';
                        }
                        markdown += child.text || '';
                        hasContent = true;
                        lastNodeWasEmbed = false;
                        lastNodeWasMate = false;
                    } else if (child.type.name === 'hardBreak') {
                        markdown += '\n';
                        hasContent = true;
                        lastNodeWasEmbed = false;
                        lastNodeWasMate = false;
                    }
                });

                // Add newline after paragraph if it had content and wasn't an embed
                if (hasContent && !lastNodeWasEmbed) {
                    markdown += '\n';
                }
            }
        });
        
        // Log the markdown for debugging
        console.log('Final markdown:', markdown);
        
        // Clear the editor content and add the default mention
        editor.commands.clearContent();
        
        // Reset hasContent state
        hasContent = false;
        
        // Add the default mention after a short delay to ensure proper rendering
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
        }, 0);
    }

    // Add prop for default mention
    export const defaultMention: string = 'sophia';

    // Add this function to handle press/click on embeds
    function handleEmbedInteraction(event: CustomEvent, embedId: string) {
        event.preventDefault();
        
        // Set the flag before showing menu
        isMenuInteraction = true;
        
        // Find the element using the elementId from the event detail
        const element = document.getElementById(event.detail.elementId);
        if (!element) return;

        // Get element's position relative to viewport
        const rect = element.getBoundingClientRect();
        
        // Calculate position relative to the message container
        const container = element.closest('.message-container');
        if (!container) return;
        
        const containerRect = container.getBoundingClientRect();
        
        // Position menu relative to the clicked element
        menuX = rect.left - containerRect.left + (rect.width / 2);
        menuY = rect.top - containerRect.top;
        
        selectedEmbedId = embedId;
        showMenu = true;

        // Determine the type of content for the menu
        const contentType = element.getAttribute('data-type');
        menuType = contentType === 'pdf' ? 'pdf' : 
                   contentType === 'custom-embed' && element.hasAttribute('data-url') ? 'web' : 
                   'default';
    }

    // Add these handlers for the menu actions
    async function handleMenuAction(action: 'delete' | 'download' | 'view' | 'copy') {
        if (!selectedEmbedId) return;

        let foundNode: any = null;
        editor.state.doc.descendants((node: any, pos: number) => {
            if (node.attrs?.id === selectedEmbedId) {
                foundNode = { node, pos };
                return false;
            }
            return true;
        });

        if (!foundNode) return;

        const { node, pos } = foundNode;

        switch (action) {
            case 'delete':
                editor.chain().focus().deleteRange({ from: pos, to: pos + node.nodeSize }).run();
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
                if (node.attrs.src || node.attrs.url) {
                    window.open(node.attrs.src || node.attrs.url, '_blank');
                }
                break;

            case 'copy':
                if (node.attrs.url) {
                    await navigator.clipboard.writeText(node.attrs.url);
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
    }

    // Update the handleAudioRecorded function
    async function handleAudioRecorded(event: CustomEvent) {
        const { blob, duration } = event.detail;
        console.log('Received audio blob:', { size: blob.size, duration });

        const url = URL.createObjectURL(blob);
        const filename = `audio_${Date.now()}.webm`;
        const formattedDuration = formatDuration(duration);

        // Get current cursor position before any modifications
        const currentPos = editor.state.selection.from;

        // If editor is empty, handle special case
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
                        },
                        {
                            type: 'customEmbed',
                            attrs: {
                                type: 'recording',
                                src: url,
                                filename: filename,
                                duration: formattedDuration,
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
        } else {
            // Insert at current cursor position
            editor
                .chain()
                .focus()
                .insertContentAt(currentPos, [
                    {
                        type: 'customEmbed',
                        attrs: {
                            type: 'recording',
                            src: url,
                            filename: filename,
                            duration: formattedDuration,
                            id: crypto.randomUUID()
                        }
                    },
                    {
                        type: 'text',
                        text: ' '
                    }
                ])
                .run();
        }

        // Move cursor after the inserted content
        editor.commands.focus();

        console.log('Added audio recording:', { 
            filename, 
            duration: formattedDuration, 
            position: currentPos 
        });
    }

    // Add helper function to format duration
    function formatDuration(seconds: number): string {
        const minutes = Math.floor(seconds / 60);
        const remainingSeconds = Math.floor(seconds % 60);
        return `${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
    }

    // Function to toggle fullscreen mode
    function toggleFullscreen() {
        isFullscreen = !isFullscreen;
    }

    $: containerStyle = isFullscreen ? 
        `height: calc(100vh - 100px); max-height: calc(100vh - 120px);` : 
        'height: auto; max-height: 350px;';  // Add default height when not fullscreen
    $: scrollableStyle = isFullscreen ? 
        `max-height: calc(100vh - 190px);` : 
        'max-height: 250px;';  // Add default height when not fullscreen

    // Add new insertVideo function after other insert functions
    async function insertVideo(file: File, duration?: string) {
        const url = URL.createObjectURL(file);
        
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
                        },
                        {
                            type: 'customEmbed',
                            attrs: {
                                type: 'video',
                                src: url,
                                filename: file.name,
                                duration: duration || '00:00',
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
        } else {
            editor
                .chain()
                .focus()
                .insertContent([
                    {
                        type: 'customEmbed',
                        attrs: {
                            type: 'video',
                            src: url,
                            filename: file.name,
                            duration: duration || '00:00',
                            id: crypto.randomUUID()
                        }
                    },
                    {
                        type: 'text',
                        text: ' '
                    }
                ])
                .run();
        }
    }

    // Add this helper function near the top with other helper functions
    function isVideoFile(file: File): boolean {
        // List of common video file extensions
        const videoExtensions = [
            '.mp4', '.webm', '.ogg', '.mov', '.m4v', 
            '.mkv', '.avi', '.3gp', '.wmv', '.flv'
        ];
        
        // Log file details for debugging
        console.log('Checking if file is video:', {
            fileName: file.name,
            fileType: file.type,
            size: file.size
        });
        
        // Check file type first
        if (file.type.startsWith('video/')) {
            console.log('Detected video by MIME type:', file.type);
            return true;
        }
        
        // Fallback to extension check
        const fileName = file.name.toLowerCase();
        const isVideoByExtension = videoExtensions.some(ext => fileName.endsWith(ext));
        console.log('Extension check result:', isVideoByExtension);
        return isVideoByExtension;
    }
</script>

<div class="message-container {isMessageFieldFocused ? 'focused' : ''} {isRecordingActive ? 'recording-active' : ''}"
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
            class="fullscreen-button" 
            class:active={isFullscreen}
            on:click={toggleFullscreen}
            aria-label={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
        >
            <div class="clickable-icon icon_fullscreen"></div>
        </button>
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
                // Add small delay to ensure DOM is updated
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
                aria-label={$_('enter_message.attachments.attach_files.text')}
            ></button>
            <button 
                class="clickable-icon icon_maps" 
                aria-label={$_('enter_message.attachments.share_location.text')}
            ></button>
        </div>
        <div class="right-buttons">
            <button 
                class="clickable-icon icon_camera" 
                on:click={handleCameraClick} 
                aria-label={$_('enter_message.attachments.take_photo.text')}
            ></button>
            
            {#if showRecordHint}
                <span 
                    class="record-hint-inline" 
                    transition:slide={{ duration: 200 }}
                >
                    {$_('enter_message.record_audio.press_and_hold_reminder.text')}
                </span>
            {/if}
            
            <button 
                class="record-button {isRecordButtonPressed ? 'recording' : ''}"
                style="z-index: 901;"
                on:mousedown={(event) => {
                    hasRecordingStarted = false;  // Reset the flag
                    recordStartTimeout = setTimeout(() => {
                        recordStartPosition = { 
                            x: event.clientX, 
                            y: event.clientY 
                        };
                        isRecordButtonPressed = true;
                        showRecordAudio = true;
                        hasRecordingStarted = true;  // Set flag when recording starts
                        // Clear any existing hint when starting to record
                        if (showRecordHint) {
                            showRecordHint = false;
                            clearTimeout(recordHintTimeout);
                        }
                    }, 500);
                }}
                on:mouseup={() => {
                    // If released before 500ms and recording hasn't started, show the hint
                    if (recordStartTimeout) {
                        clearTimeout(recordStartTimeout);
                        if (!hasRecordingStarted) {
                            showRecordHint = true;
                            // Auto-hide hint after 2 seconds
                            clearTimeout(recordHintTimeout);
                            recordHintTimeout = setTimeout(() => {
                                showRecordHint = false;
                            }, 2000);
                        }
                    }
                    isRecordButtonPressed = false;
                    showRecordAudio = false;
                    hasRecordingStarted = false;  // Reset the flag
                }}
                on:mouseleave={() => {
                    if (isRecordButtonPressed) {
                        isRecordButtonPressed = false;
                        showRecordAudio = false;
                        hasRecordingStarted = false;  // Reset the flag
                        clearTimeout(recordStartTimeout);
                    }
                }}
                on:touchstart|preventDefault={(event) => {
                    hasRecordingStarted = false;  // Reset the flag
                    recordStartTimeout = setTimeout(() => {
                        recordStartPosition = { 
                            x: event.touches[0].clientX, 
                            y: event.touches[0].clientY 
                        };
                        isRecordButtonPressed = true;
                        showRecordAudio = true;
                        hasRecordingStarted = true;  // Set flag when recording starts
                        if (showRecordHint) {
                            showRecordHint = false;
                            clearTimeout(recordHintTimeout);
                        }
                    }, 500);
                }}
                on:touchend={() => {
                    // If released before 500ms and recording hasn't started, show the hint
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
                    hasRecordingStarted = false;  // Reset the flag
                }}
                aria-label={$_('enter_message.attachments.record_audio.text')}
            >
                <div class="clickable-icon icon_recordaudio"></div>
            </button>
            {#if hasContent}
                <button 
                    class="send-button" 
                    on:click={handleSend}
                    aria-label={$_('enter_message.send.text')}
                >
                    {$_('enter_message.send.text')}
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
            on:close={() => {
                showMenu = false;
                isMenuInteraction = false; // Reset the flag when menu is closed
            }}
            on:delete={() => handleMenuAction('delete')}
            on:download={() => handleMenuAction('download')}
            on:view={() => handleMenuAction('view')}
            on:copy={() => handleMenuAction('copy')}
        />
    {/if}

    {#if showRecordAudio}
        <RecordAudio
            initialPosition={recordStartPosition}
            on:audiorecorded={handleAudioRecorded}
            on:close={() => showRecordAudio = false}
            on:layoutChange={handleRecordingLayoutChange}
        />
    {/if}
</div>

<style>
    /* Reuse all your existing styles from EnterMessageField.svelte */
    .message-container {
        width: 100%;
        min-height: 100px;
        max-height: 350px;
        background-color: var(--color-grey-blue);
        border-radius: 24px;
        padding: 0 1rem 50px 1rem;
        box-sizing: border-box;
        position: relative;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
        transition: all 0.3s ease-in-out; /* Update transition to include all properties */
        transform-origin: center;
        will-change: transform, padding-bottom, max-height, height;
    }

    /* Add new style for recording active state */
    .message-container.recording-active {
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
        gap: 0.5rem;
        width: 100%;
        box-sizing: border-box;
        padding: 0 0.5rem;
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
        top: 8px;
        right: -10px;
        background: none;
        border: none;
        padding: 4px;
        cursor: pointer;
        opacity: 0.5;
        transition: opacity 0.2s ease-in-out;
        z-index: 1000;
    }

    .fullscreen-button:hover {
        opacity: 1;
    }

    .fullscreen-button.active {
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