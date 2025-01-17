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
                filename: { default: null }
            }
        },

        parseHTML() {
            return [{ tag: 'div[data-type="custom-embed"]' }]
        },

        renderHTML({ HTMLAttributes }) {
            // Add logging to help debug render process
            console.log('Rendering embed:', HTMLAttributes);

            if (HTMLAttributes.type === 'image') {
                // Return the new photo preview structure
                return ['div', {
                    class: 'photo-preview-container',
                    role: 'button',
                    tabindex: '0',
                    'data-type': 'custom-embed',
                    'data-src': HTMLAttributes.src,
                    'data-filename': HTMLAttributes.filename
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
                // Keep existing PDF rendering
                return ['div', {
                    class: 'pdf-preview-container',
                    role: 'button',
                    tabindex: '0',
                    'data-type': 'custom-embed',
                    'data-src': HTMLAttributes.src,
                    'data-filename': HTMLAttributes.filename
                }, 
                    ['div', { class: 'icon_rounded pdf' }],
                    ['div', { class: 'filename-container' },
                        ['span', { class: 'filename' }, HTMLAttributes.filename]
                    ]
                ]
            }
            // Default fallback
            return ['div', { class: 'embedded-unknown' }, HTMLAttributes.filename]
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
                url: { default: null }
            }
        },

        parseHTML() {
            return [{ tag: 'div[data-type="web-preview"]' }]
        },

        renderHTML({ HTMLAttributes }) {
            return ['div', {
                'data-type': 'web-preview',
                'data-url': HTMLAttributes.url,
                class: 'web-preview-container'
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
                Placeholder.configure({
                    placeholder: ({ editor }: { editor: EditorType }) => {
                        if (editor.isFocused) {
                            return $_('enter_message.enter_your_message.text');
                        }
                        return $_('enter_message.click_to_enter_message.text');
                    },
                    emptyEditorClass: 'is-editor-empty',
                }),
                Extension.create({
                    name: 'customKeyboardHandling',
                    priority: 1000,
                    onCreate() {
                        // Add DOM event listener for keydown
                        this.editor.view.dom.addEventListener('keydown', (event) => {
                            if (event.key === 'Enter') {
                                event.preventDefault();

                                if (event.shiftKey) {
                                    // Shift+Enter: Insert hard break
                                    this.editor.chain()
                                        .focus()
                                        .setHardBreak()
                                        .run();
                                } else {
                                    // Enter alone: Send message if not empty
                                    if (!this.editor.isEmpty) {
                                        handleSend();
                                    }
                                }
                                return true;
                            }
                        });
                    }
                })
            ],
            editorProps: {
                handleKeyDown: (view, event) => {
                    if (event.key === 'Enter' && event.shiftKey) {
                        event.preventDefault();
                        view.dispatch(view.state.tr.insertText('\n'));
                        return true;
                    }
                    return false;
                }
            },
            content: '',
            onFocus: () => {
                isMessageFieldFocused = true;
            },
            onBlur: () => {
                isMessageFieldFocused = false;
            },
            onUpdate: ({ editor }) => {
                const content = editor.getHTML();
                detectAndReplaceUrls(content);
            }
        });

        // Auto-focus the editor on mount
        editor.commands.focus();
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
                attrs: { url }
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
    });

    // Update the hasContent reactive declaration to check editor content
    $: hasContent = editor?.state?.doc.textContent.length > 0 || 
        editor?.state?.doc.content.childCount > 1;

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
        editor.chain().focus().insertContent({
            type: 'customEmbed',
            attrs: {
                type: 'image',
                src: url,
                filename: file.name
            }
        }).run();
    }

    async function insertFile(file: File) {
        console.log('Inserting PDF file:', file.name); // Add logging
        const url = URL.createObjectURL(file);
        
        // Force editor focus and insert at current position
        editor.chain()
            .focus()
            .insertContent({
                type: 'customEmbed',
                attrs: {
                    type: 'pdf',
                    src: url,
                    filename: file.name
                }
            })
            .run();
        
        console.log('PDF insertion complete'); // Add logging
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
        
        // Log the message content
        console.log('Sending message:', editor.getHTML());
        
        // Clear the editor content
        editor.commands.clearContent();
    }

    // Add prop for default mention
    export const defaultMention: string = 'sophia';
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

    .message-input {
        width: 100%;
        min-height: 2em;
        border: none;
        outline: none;
        resize: none;
        background: transparent;
        font-family: inherit;
        font-size: 1rem;
        line-height: 1.5;
        padding: 0.5rem 0;
        margin: 0;
        overflow: hidden;
        box-sizing: border-box;
        text-align: left;
        caret-color: var(--color-font-primary);
        animation: blink-caret 1s step-end infinite;
        height: auto;
        word-break: break-word;
        white-space: pre-wrap;
    }

    @keyframes blink-caret {
        from, to { caret-color: var(--color-font-primary); }
        50% { caret-color: transparent; }
    }

    .message-input::placeholder {
        text-align: center;
        transition: opacity 0.2s ease;
        position: absolute;
        left: 0;
        right: 0;
        color: var(--color-font-tertiary);
        font-weight: 500;
    }

    .message-input.has-content::placeholder {
        opacity: 0;
    }

    textarea {
        /* Reset all properties that could affect textarea height */
        margin: 0 !important;
        padding: 0 !important;
        border: none !important;
        line-height: normal !important;
        font-size: unset !important;
        font-family: unset !important;
        font-weight: 500 !important;
        min-height: unset !important;
        max-height: unset !important;
        box-sizing: content-box !important;
        color: var(--color-font-primary);
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

    .text-display {
        width: 100%;
        white-space: pre-wrap;
        cursor: text;
        text-align: left;
        color: var(--color-font-primary);
        font-weight: 500 !important; 
    }

    /* Add a new class for empty text display */
    .text-display.empty {
        text-align: center;
        color: var(--color-font-tertiary);
    }

    .file-attachment {
        display: flex;
        align-items: center;
        background: #f5f5f5;
        border-radius: 8px;
        padding: 0.75rem;
        margin: 0.5rem 0;
        gap: 1rem;
        max-width: 80%;
    }

    .file-icon {
        font-size: 1.5rem;
    }

    .file-info {
        display: flex;
        flex-direction: column;
    }

    .file-name {
        font-weight: 500;
        word-break: break-all;
    }

    .video-container {
        width: 100%;
        max-width: 80%;
        margin: 0.5rem 0;
        position: relative;
        background: var(--color-grey-20);
        border-radius: 8px;
        overflow: hidden;
    }

    .preview-video {
        width: 100%;
        max-height: 300px;
        object-fit: contain;
        background: #000;
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

    .message-input.before-attachment::placeholder,
    .text-display.before-attachment.empty {
        text-align: left;
        color: var(--color-font-tertiary);
    }

    .text-display.empty:not(.before-attachment) {
        text-align: center;
        color: var(--color-font-tertiary);
    }

    .placeholder {
        user-select: none;
        -webkit-user-select: none;
        -moz-user-select: none;
        -ms-user-select: none;
        color: var(--color-font-tertiary);
    }

    /* Update left-buttons style if needed */
    .left-buttons {
        display: flex;
        gap: 1rem;
        align-items: center;
        height: 100%;
    }

    .input-wrapper {
        position: relative;
        display: flex;
        align-items: center;
        width: 100%;
    }

    .mention-display {
        display: flex;
        align-items: center;
        gap: 4px;
        position: absolute;
        left: 0;
        top: 50%;
        transform: translateY(-50%);
        pointer-events: none;
        z-index: 1;
    }

    .at-symbol {
        color: var(--color-font-primary);
        font-weight: 500;
    }

    .message-input.has-mention {
        padding-left: 64px !important;
    }

    .text-display {
        position: relative;
        padding-left: 0;
        width: 100%;
        box-sizing: border-box;
    }

    .text-display:has(.mention-display) {
        padding-left: 64px;
    }

    /* Add new style to handle placeholder positioning when mate selection is visible */
    .input-wrapper:has(.mention-display) .message-input::placeholder {
        text-align: left;
        left: 64px;
        right: 0;
        width: calc(100% - 64px);
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
        height: 0;
    }

    /* Center placeholder when not focused */
    :global(.ProseMirror:not(:focus) p.is-editor-empty:first-child::before) {
        text-align: center;
        width: 100%;
    }

    /* Left align placeholder when focused */
    :global(.ProseMirror:focus p.is-editor-empty:first-child::before) {
        text-align: left;
    }
</style>