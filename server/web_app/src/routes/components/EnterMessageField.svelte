<script lang="ts">
    import { tick, onDestroy, onMount } from 'svelte';

    // Content block types
    type Block = {
        id: string;
        type: 'text' | 'image';
        content: string | ImageContent;
    }

    type ImageContent = {
        blob: Blob;
        filename: string;
        altText: string;
    }

    // State
    let blocks: Block[] = [{ id: crypto.randomUUID(), type: 'text', content: '' }];
    let editorRef: HTMLDivElement;
    let currentSelection: Range | null = null;
    
    // File and camera refs (keeping existing camera functionality)
    let fileInput: HTMLInputElement;
    let cameraInput: HTMLInputElement;
    let videoElement: HTMLVideoElement;
    let stream: MediaStream | null = null;
    let showCamera = false;

    // Track if there's content
    $: hasContent = blocks.some(block => 
        block.type === 'text' ? block.content.toString().trim().length > 0 : true
    );

    onMount(() => {
        // Track selection changes
        document.addEventListener('selectionchange', () => {
            const selection = window.getSelection();
            if (selection && selection.rangeCount > 0) {
                currentSelection = selection.getRangeAt(0);
            }
        });
    });

    // Handle content updates
    function handleInput(event: Event, block: Block) {
        if (block.type === 'text') {
            const div = event.target as HTMLDivElement;
            block.content = div.innerText;
        }
    }

    // Insert image at current selection or at end
    function insertImage(blob: Blob) {
        const imageId = crypto.randomUUID();
        const newBlock: Block = {
            id: imageId,
            type: 'image',
            content: {
                blob,
                filename: `image_${imageId}.jpg`,
                altText: ''
            }
        };

        let insertIndex = blocks.length;
        
        // Find insertion point from current selection
        if (currentSelection) {
            const blockEl = currentSelection.startContainer.parentElement?.closest('[data-block-id]');
            if (blockEl) {
                const blockId = blockEl.getAttribute('data-block-id');
                const foundIndex = blocks.findIndex(b => b.id === blockId);
                if (foundIndex !== -1) {
                    insertIndex = foundIndex + 1;
                }
            }
        }

        // Insert image and new text block
        blocks = [
            ...blocks.slice(0, insertIndex),
            newBlock,
            { id: crypto.randomUUID(), type: 'text', content: '' },
            ...blocks.slice(insertIndex)
        ];
    }

    function handleKeydown(event: KeyboardEvent, block: Block, index: number) {
        if (event.key === 'Enter') {
            if (!event.shiftKey) {
                event.preventDefault();
                if (hasContent) {
                    handleSend();
                } else {
                    // Insert new block
                    const newBlock: Block = { 
                        id: crypto.randomUUID(), 
                        type: 'text', 
                        content: '' 
                    };
                    blocks = [
                        ...blocks.slice(0, index + 1),
                        newBlock,
                        ...blocks.slice(index + 1)
                    ];
                    // Focus new block after render
                    tick().then(() => {
                        const newDiv = document.querySelector(`[data-block-id="${newBlock.id}"]`);
                        if (newDiv) {
                            (newDiv as HTMLElement).focus();
                        }
                    });
                }
            }
        }

        // Handle backspace
        if (event.key === 'Backspace') {
            if (block.type === 'text') {
                if (window.getSelection()?.anchorOffset === 0 && index > 0) {
                    event.preventDefault();
                    // If previous block is an image, delete it
                    if (blocks[index - 1].type === 'image') {
                        blocks = [
                            ...blocks.slice(0, index - 1),
                            ...blocks.slice(index)
                        ];
                    } else {
                        mergeWithPreviousBlock(index);
                    }
                }
            } else if (block.type === 'image') {
                event.preventDefault();
                blocks = blocks.filter(b => b.id !== block.id);
            }
        }
    }

    function mergeWithPreviousBlock(index: number) {
        const currentBlock = blocks[index];
        const previousBlock = blocks[index - 1];

        if (currentBlock.type === 'text' && previousBlock.type === 'text') {
            const mergedContent = (previousBlock.content as string) + (currentBlock.content as string);
            blocks = [
                ...blocks.slice(0, index - 1),
                { ...previousBlock, content: mergedContent },
                ...blocks.slice(index + 1)
            ];
            // Focus end of previous block
            tick().then(() => {
                const prevDiv = document.querySelector(`[data-block-id="${previousBlock.id}"]`);
                if (prevDiv) {
                    const range = document.createRange();
                    const sel = window.getSelection();
                    range.selectNodeContents(prevDiv);
                    range.collapse(false);
                    sel?.removeAllRanges();
                    sel?.addRange(range);
                }
            });
        }
    }

    // Get markdown content
    function getMarkdownContent(): string {
        return blocks.map(block => {
            if (block.type === 'text') {
                return block.content;
            } else {
                const img = block.content as ImageContent;
                return `![${img.altText}](${img.filename})`;
            }
        }).join('\n');
    }

    // Handle file selection
    function handleFileSelect() {
        fileInput.click();
    }

    // Handle file input change
    function onFileSelected(event: Event) {
        const input = event.target as HTMLInputElement;
        if (input.files && input.files.length > 0) {
            const file = input.files[0];
            insertImage(file);
        }
    }

    // Handle camera activation
    async function handleCameraClick() {
        try {
            stream = await navigator.mediaDevices.getUserMedia({ 
                video: { facingMode: 'environment' },
                audio: false 
            });
            
            if (stream) {
                showCamera = true;
                await tick();
                if (videoElement) {
                    videoElement.srcObject = stream;
                }
            }
        } catch (err) {
            console.error('Camera access error:', err);
            cameraInput.removeAttribute('capture');
            cameraInput.click();
        }
    }

    // Capture photo from camera
    async function capturePhoto() {
        if (!videoElement) return;

        const canvas = document.createElement('canvas');
        canvas.width = videoElement.videoWidth;
        canvas.height = videoElement.videoHeight;
        const ctx = canvas.getContext('2d');
        
        if (ctx) {
            ctx.drawImage(videoElement, 0, 0);
            canvas.toBlob((blob) => {
                if (blob) {
                    insertImage(blob);
                }
            }, 'image/jpeg');
        }
        closeCamera();
    }

    // Close camera
    function closeCamera() {
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
            stream = null;
        }
        showCamera = false;
    }

    onDestroy(() => {
        closeCamera();
    });

    function handleSend() {
        const content = getMarkdownContent();
        console.log('Sending:', content);
        
        // Reset content
        blocks = [{ id: crypto.randomUUID(), type: 'text', content: '' }];
    }

    // Add keyboard shortcut handler
    function handleEditorKeydown(event: KeyboardEvent) {
        // Handle Cmd/Ctrl + A
        if ((event.metaKey || event.ctrlKey) && event.key === 'a') {
            event.preventDefault();
            const selection = window.getSelection();
            const range = document.createRange();
            range.selectNodeContents(editorRef);
            selection?.removeAllRanges();
            selection?.addRange(range);
        }
    }
</script>

<div class="message-container">
    <!-- Hidden file inputs -->
    <input
        bind:this={fileInput}
        type="file"
        accept="image/*"
        on:change={onFileSelected}
        style="display: none"
    />
    
    <input
        bind:this={cameraInput}
        type="file"
        accept="image/*"
        capture="environment"
        on:change={onFileSelected}
        style="display: none"
    />

    <div 
        class="editor-content" 
        bind:this={editorRef}
        role="textbox"
        tabindex="0"
        on:keydown={handleEditorKeydown}
    >
        {#each blocks as block, index}
            {#if block.type === 'text'}
                <div
                    class="content-block text-block"
                    data-block-id={block.id}
                    contenteditable="true"
                    role="textbox"
                    tabindex="0"
                    on:input={(e) => handleInput(e, block)}
                    on:keydown={(e) => handleKeydown(e, block, index)}
                    data-placeholder={index === 0 && !block.content ? "Type your message here..." : ""}
                >{block.content}</div>
            {:else if block.type === 'image'}
                {@const imgContent = block.content as ImageContent}
                <div 
                    class="content-block image-block" 
                    data-block-id={block.id}
                    tabindex="0"
                    role="button"
                    on:keydown={(e) => handleKeydown(e, block, index)}
                >
                    <img
                        src={URL.createObjectURL(imgContent.blob)}
                        alt={imgContent.altText}
                        class="preview-image"
                    />
                    <div 
                        class="image-caption"
                        contenteditable="true"
                        role="textbox"
                        tabindex="0"
                        on:input={(e) => imgContent.altText = (e.target as HTMLDivElement).innerText}
                    >{imgContent.altText}</div>
                </div>
            {/if}
        {/each}
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
            <button class="icon-button" on:click={handleFileSelect}>
                📎
            </button>
            <button class="icon-button" on:click={handleCameraClick}>
                📷
            </button>
        </div>
        
        {#if hasContent}
            <button class="send-button" on:click={handleSend}>
                Send ➤
            </button>
        {/if}
    </div>
</div>

<style>
    .message-container {
        width: 100%;
        min-height: 100px;
        max-height: 350px;
        background-color: #FFFFFF;
        border-radius: 24px;
        padding: 1rem 1rem 50px 1rem;
        box-sizing: border-box;
        position: relative;
    }

    .editor-content {
        width: 100%;
        min-height: 100px;
        max-height: 250px;
        overflow-y: auto;
        padding: 0.5rem;
    }

    .content-block {
        margin: 0.5rem 0;
    }

    .text-block {
        min-height: 1.5em;
        padding: 0.5rem 0;
        outline: none;
    }

    .text-block:empty::before {
        content: attr(data-placeholder);
        color: #999;
        pointer-events: none;
    }

    .image-block {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
        align-items: flex-start;
    }

    .preview-image {
        max-height: 200px;
        max-width: 100%;
        object-fit: contain;
        border-radius: 6px;
    }

    .image-caption {
        font-size: 0.9em;
        color: #666;
        padding: 0.25rem 0;
        outline: none;
        min-width: 100px;
    }

    .action-buttons {
        position: absolute;
        bottom: 1rem;
        left: 1rem;
        right: 1rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    .left-buttons {
        display: flex;
        gap: 0.5rem;
    }

    .send-button {
        background-color: #007AFF;
        color: white;
        border: none;
        border-radius: 18px;
        padding: 0.5rem 1rem;
        font-size: 1rem;
        cursor: pointer;
        transition: background-color 0.2s, transform 0.1s;
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }

    .send-button:hover {
        background-color: #0056b3;
    }

    .send-button:active {
        transform: scale(0.98);
    }

    .icon-button {
        background: none;
        border: none;
        cursor: pointer;
        font-size: 1.5rem;
        padding: 0.5rem;
        transition: opacity 0.2s;
    }

    .icon-button:hover {
        opacity: 0.7;
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
</style>
