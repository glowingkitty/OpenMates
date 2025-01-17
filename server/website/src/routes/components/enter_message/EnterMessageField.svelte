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
                id: { default: () => crypto.randomUUID() }
            }
        },

        parseHTML() {
            return [{ tag: 'div[data-type="custom-embed"]' }]
        },

        renderHTML({ HTMLAttributes }) {
            // Add logging to help debug render process
            console.log('Rendering embed:', HTMLAttributes);

            const elementId = `embed-${HTMLAttributes.id}`;
            
            if (HTMLAttributes.type === 'image') {
                // Return the new photo preview structure
                return ['div', {
                    class: 'photo-preview-container',
                    role: 'button',
                    tabindex: '0',
                    'data-type': 'custom-embed',
                    'data-src': HTMLAttributes.src,
                    'data-filename': HTMLAttributes.filename,
                    'data-id': HTMLAttributes.id,
                    id: elementId,
                    onclick: `document.dispatchEvent(new CustomEvent('embedclick', { 
                        bubbles: true, 
                        detail: { 
                            id: '${HTMLAttributes.id}',
                            elementId: '${elementId}'
                        }
                    }))`,
                },
                    // Checkerboard background container
                    ['div', { class: 'checkerboard-background' },
                        ['img', {
                            src: HTMLAttributes.src,
                            alt: 'Preview',
                            class: 'preview-image fill-container'
                        }]
                    ],
                    // Photos icon
                    ['div', { class: 'icon_rounded photos' }]
                ]
            } else if (HTMLAttributes.type === 'pdf') {
                return ['div', {
                    class: 'pdf-preview-container',
                    role: 'button',
                    tabindex: '0',
                    'data-type': 'custom-embed',
                    'data-src': HTMLAttributes.src,
                    'data-filename': HTMLAttributes.filename,
                    'data-id': HTMLAttributes.id,
                    id: elementId,
                    onclick: `document.dispatchEvent(new CustomEvent('embedclick', { 
                        bubbles: true, 
                        detail: { 
                            id: '${HTMLAttributes.id}',
                            elementId: '${elementId}'
                        }
                    }))`,
                }, 
                    ['div', { class: 'icon_rounded pdf' }],
                    ['div', { class: 'filename-container' },
                        ['span', { class: 'filename' }, HTMLAttributes.filename]
                    ]
                ]
            }
            // Default fallback
            return ['div', { 
                class: 'embedded-unknown',
                'data-id': HTMLAttributes.id,
                id: elementId,
                onclick: `document.dispatchEvent(new CustomEvent('embedclick', { 
                    bubbles: true, 
                    detail: { 
                        id: '${HTMLAttributes.id}',
                        elementId: '${elementId}'
                    }
                }))`,
            }, HTMLAttributes.filename]
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
            return ['div', {
                'data-type': 'web-preview',
                'data-url': HTMLAttributes.url,
                'data-id': HTMLAttributes.id,
                id: elementId,
                class: 'web-preview-container',
                onclick: `document.dispatchEvent(new CustomEvent('embedclick', { 
                    bubbles: true, 
                    detail: { 
                        id: '${HTMLAttributes.id}',
                        elementId: '${elementId}'
                    }
                }))`,
            }]
        },

        // Update keyboard shortcuts handler
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
                    props: { url: node.attrs.url },
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
        let isEmpty = true;
        let hasMention = false;
        let hasOtherContent = false;
        
        editor.state.doc.descendants((node) => {
            if (node.type.name === 'mate') {
                hasMention = true;
            } else if (node.type.name === 'text') {
                // Only consider non-whitespace text as content
                if (node.text?.trim()) {
                    hasOtherContent = true;
                    isEmpty = false;
                }
            } else if (node.type.name !== 'paragraph') {
                // Any other node type counts as content
                hasOtherContent = true;
                isEmpty = false;
            }
        });
        
        // Return true only if we have the mention and no other content
        return hasMention && !hasOtherContent;
    }

    // Update the Placeholder extension configuration
    const placeholderExtension = Placeholder.configure({
        placeholder: ({ editor }: { editor: EditorType }) => {
            // Return empty string to remove placeholder
            return '';
        },
        emptyEditorClass: 'is-editor-empty',
        showOnlyWhenEditable: true,
    });

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
                Extension.create({
                    name: 'customKeyboardHandling',
                    priority: 1000,
                    addKeyboardShortcuts() {
                        return {
                            Enter: ({ editor }) => {
                                // Handle regular Enter
                                if (!editor.isEmpty) {
                                    handleSend();
                                }
                                return true;
                            },
                            'Shift-Enter': ({ editor }) => {
                                // Handle Shift+Enter with native TipTap command
                                editor.commands.setHardBreak();
                                return true;
                            }
                        }
                    }
                })
            ],
            content: {
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
            },
            onFocus: () => {
                isMessageFieldFocused = true;
            },
            onBlur: () => {
                isMessageFieldFocused = false;
                // Remove the check for empty content since we always want to keep the mention
            },
            onUpdate: ({ editor }) => {
                const content = editor.getHTML();
                // Process URLs first
                detectAndReplaceUrls(content);
                // Then process mates
                detectAndReplaceMates(content);
            }
        });

        // Update cursor position after editor initialization
        if (defaultMention) {
            // Move cursor to end of document
            editor.commands.focus('end');
        } else {
            editor.commands.focus();
        }

        // Add global event listener for embed clicks with proper typing
        document.addEventListener('embedclick', ((event: CustomEvent) => {
            const { id } = event.detail;
            handleEmbedInteraction(event, id);
        }) as EventListener);
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

    // Add a more specific transaction handler if needed
    $: if (editor) {
        editor.on('transaction', ({ transaction }) => {
            // Only update if the transaction affects the doc structure
            if (transaction.docChanged) {
                // Check if it's just a text change
                const isOnlyTextChange = transaction.steps.every(step => 
                    step.toJSON().stepType === 'replace' && !step.toJSON().mark
                );
                
                // Only force update if it's not just a text change
                if (!isOnlyTextChange) {
                    editor = editor;
                }
            }
        });
    }

    onDestroy(() => {
        if (editor) {
            editor.destroy();
        }
        closeCamera();
        document.removeEventListener('embedclick', (() => {}) as EventListener);
    });

    // Update the hasContent reactive declaration
    $: hasContent = editor && !isContentEmptyExceptMention(editor);

    // Handle file selection
    function handleFileSelect() {
        fileInput.multiple = true;
        fileInput.click();
    }

    async function onFileSelected(event: Event) {
        const input = event.target as HTMLInputElement;
        if (!input.files?.length) return;

        const files = Array.from(input.files);
        const totalSize = files.reduce((sum, file) => sum + file.size, 0);

        if (totalSize > MAX_TOTAL_SIZE) {
            alert($_('enter_message.file_size_limits.total_exceeded.text', {
                size: FILE_SIZE_LIMITS.TOTAL_MAX_SIZE,
                current: (totalSize / 1024 / 1024).toFixed(1),
                attempted: (totalSize / 1024 / 1024).toFixed(1)
            } as any));
            return;
        }

        for (const file of files) {
            if (file.type.startsWith('image/')) {
                await insertImage(file);
            } else if (file.type === 'application/pdf') {
                await insertFile(file);
            } else if (file.type.startsWith('video/')) {
                await insertVideo(file);
            }
        }

        input.value = '';
    }

    async function insertImage(file: File) {
        const url = URL.createObjectURL(file);
        const id = crypto.randomUUID();
        
        editor.chain().focus().insertContent({
            type: 'customEmbed',
            attrs: {
                type: 'image',
                src: url,
                filename: file.name,
                id
            }
        }).run();
    }

    async function insertFile(file: File) {
        console.log('Inserting PDF file:', file.name);
        const url = URL.createObjectURL(file);
        
        // Add unique ID for PDFs
        editor.chain()
            .focus()
            .insertContent({
                type: 'customEmbed',
                attrs: {
                    type: 'pdf',
                    src: url,
                    filename: file.name,
                    id: crypto.randomUUID() // Add unique ID for PDFs
                }
            })
            .run();
        
        console.log('PDF insertion complete');
    }

    async function insertVideo(file: File) {
        console.log('Inserting video:', file.name);
        const url = URL.createObjectURL(file);
        editor.chain().focus().insertContent({
            type: 'customEmbed',
            attrs: {
                type: 'video',
                src: url,
                filename: file.name,
                id: crypto.randomUUID()
            }
        }).run();
    }

    function handleCameraClick() {
        if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
            navigator.mediaDevices.getUserMedia({ 
                video: { facingMode: 'environment' },
                audio: false 
            })
            .then(mediaStream => {
                stream = mediaStream;
                showCamera = true;
                tick().then(() => {
                    if (videoElement) {
                        videoElement.srcObject = stream;
                    }
                });
            })
            .catch(err => {
                console.error('Camera access error:', err);
                cameraInput.click();
            });
        } else {
            cameraInput.click();
        }
    }

    async function capturePhoto() {
        if (!videoElement) return;

        const canvas = document.createElement('canvas');
        canvas.width = videoElement.videoWidth;
        canvas.height = videoElement.videoHeight;
        const ctx = canvas.getContext('2d');
        
        if (ctx) {
            ctx.drawImage(videoElement, 0, 0);
            canvas.toBlob(async (blob) => {
                if (blob) {
                    const file = new File([blob], `camera_${Date.now()}.jpg`, { type: 'image/jpeg' });
                    await insertImage(file);
                }
            }, 'image/jpeg');
        }
        closeCamera();
    }

    function closeCamera() {
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
            stream = null;
        }
        showCamera = false;
    }

    // Update the handleSend button click handler in the template
    function handleSend() {
        if (!editor || editor.isEmpty) return;
        
        let markdown = '';
        let isFirstParagraph = true;
        let lastNodeWasEmbed = false;
        
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

                // Track if we've added content to this paragraph
                let hasContent = false;

                node.content.forEach((child, index, array) => {
                    if (child.type.name === 'mate') {
                        markdown += `@${child.attrs.name}`;
                        hasContent = true;
                        lastNodeWasEmbed = false;
                    } else if (child.type.name === 'webPreview') {
                        markdown += `${child.attrs.url}\n`;  // Add newline after web preview
                        hasContent = true;
                        lastNodeWasEmbed = true;
                    } else if (child.type.name === 'customEmbed') {
                        const { type, filename } = child.attrs;
                        if (type === 'image' || type === 'pdf') {
                            markdown += `[${filename}]\n`;  // Add newline after image/pdf
                            hasContent = true;
                            lastNodeWasEmbed = true;
                        }
                    } else if (child.type.name === 'text') {
                        markdown += child.text;
                        hasContent = true;
                        lastNodeWasEmbed = false;
                    } else if (child.type.name === 'hardBreak') {
                        markdown += '\n';
                        hasContent = true;
                        lastNodeWasEmbed = false;
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
        
        // Find the element using the elementId from the event detail
        const element = document.getElementById(event.detail.elementId);
        if (!element) return;

        // Find the node with this ID
        let foundNode: any = null;
        editor.state.doc.descendants((node: any, pos: number) => {
            if (node.attrs?.id === embedId) {
                foundNode = { node, pos };
                return false;
            }
            return true;
        });

        if (!foundNode) return;

        const rect = element.getBoundingClientRect();
        menuX = rect.left + (rect.width / 2);
        menuY = rect.top;
        
        selectedEmbedId = embedId;
        showMenu = true;

        // Determine the type of content for the menu
        const contentType = foundNode.node.attrs.type;
        menuType = contentType === 'pdf' ? 'pdf' : 
                   contentType === 'webPreview' ? 'web' : 
                   'default';
    }

    // Add these handlers for the menu actions
    function handleMenuAction(action: 'delete' | 'download' | 'view' | 'copy') {
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
                // Use the correct src from the found node
                if (node.attrs.src) {
                    window.open(node.attrs.src, '_blank');
                }
                break;

            case 'copy':
                if (node.attrs.url) {
                    navigator.clipboard.writeText(node.attrs.url).catch(console.error);
                }
                break;
        }
        showMenu = false;
    }
</script>

<div class="message-container {isMessageFieldFocused ? 'focused' : ''}">
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

    <div class="scrollable-content">
        <div class="content-wrapper">
            <div 
                bind:this={editorElement} 
                class="editor-content prose"
            ></div>
        </div>
    </div>

    {#if showCamera}
        <div class="camera-overlay">
            <video
                bind:this={videoElement}
                autoplay
                playsinline
                class="camera-preview"
            >
                <track kind="captions" />
            </video>
            <div class="camera-controls">
                <button class="camera-button" on:click={closeCamera}>
                    ❌
                </button>
                <button class="camera-button" on:click={capturePhoto}>
                    📸
                </button>
            </div>
        </div>
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
            <button 
                class="clickable-icon icon_recordaudio" 
                aria-label={$_('enter_message.attachments.record_audio.text')}
            ></button>
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
            on:close={() => showMenu = false}
            on:delete={() => handleMenuAction('delete')}
            on:download={() => handleMenuAction('download')}
            on:view={() => handleMenuAction('view')}
            on:copy={() => handleMenuAction('copy')}
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
        transition: box-shadow 0.2s ease-in-out;
    }

    .message-container.focused {
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.15);
    }

    /* Add Tiptap-specific styles */
    :global(.ProseMirror) {
        outline: none;
        min-height: 2em;
        padding: 0.5rem 0;
    }

    :global(.ProseMirror p) {
        margin: 0;
    }

    :global(.custom-embed) {
        display: inline-flex;
        align-items: center;
        background: #f5f5f5;
        border-radius: 4px;
        padding: 4px 8px;
        margin: 0 2px;
        cursor: pointer;
    }

    :global(.custom-embed img) {
        max-width: 200px;
        max-height: 200px;
        object-fit: contain;
    }

    :global(.custom-embed.file) {
        background: #e8f0fe;
    }

    :global(.custom-embed.video) {
        background: #fce8e8;
    }

    /* Rest of your existing styles... */
    /* Copy all remaining styles from your original component */

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
    }

    .scrollable-content::-webkit-scrollbar {
        width: 6px;
    }

    .scrollable-content::-webkit-scrollbar-track {
        background: transparent;
    }

    .scrollable-content::-webkit-scrollbar-thumb {
        background-color: rgba(0, 0, 0, 0.2);
        border-radius: 3px;
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

    .camera-overlay {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.9);
        z-index: 1000;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
    }

    .camera-preview {
        max-width: 100%;
        max-height: 80vh;
        background: #000;
    }

    .camera-controls {
        position: absolute;
        bottom: 2rem;
        left: 0;
        right: 0;
        display: flex;
        justify-content: center;
        gap: 2rem;
    }

    .camera-button {
        background: rgba(255, 255, 255, 0.2);
        border: none;
        border-radius: 50%;
        width: 60px;
        height: 60px;
        font-size: 1.5rem;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background-color 0.2s;
    }

    .camera-button:hover {
        background: rgba(255, 255, 255, 0.3);
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
        min-height: 2em;
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
        padding: 0.5rem;
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
        position: relative;
        padding-left: 4px;
    }

    /* Center placeholder when not focused */
    :global(.ProseMirror:not(:focus) p.is-editor-empty:first-child::before) {
        text-align: center;
        width: 100%;
        display: block;
    }

    /* Left align placeholder when focused */
    :global(.ProseMirror:focus p.is-editor-empty:first-child::before) {
        text-align: left;
        display: block;
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
        position: relative;
        padding-left: 4px;
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
        position: relative;
    }

    /* Add this new style to ensure placeholder text is visible */
    :global(.ProseMirror.is-editor-empty:first-child::before) {
        opacity: 1;
        display: block;
    }
</style>