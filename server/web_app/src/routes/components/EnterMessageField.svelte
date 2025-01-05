<script lang="ts">
    import { tick, onDestroy } from 'svelte';

    // State for the input text
    let messageText = '';
    // Track cursor position for image insertion
    let cursorPosition = 0;
    // Store for inline images
    type InlineImage = { 
        id: string, 
        blob: Blob, 
        filename: string,
        lineIndex: number  // Track which line the image is on
    };
    let inlineImages: InlineImage[] = [];

    // Track the height of the input field for auto-resizing
    let textareaElement: HTMLTextAreaElement;
    
    // References for file input and camera input
    let fileInput: HTMLInputElement;
    let cameraInput: HTMLInputElement;

    // State for camera view
    let showCamera = false;
    let videoElement: HTMLVideoElement;
    let stream: MediaStream | null = null;

    // Track cursor position when typing
    function handleInput() {
        adjustHeight();
        if (textareaElement) {
            cursorPosition = textareaElement.selectionStart;
        }
    }

    // Insert image at current cursor position
    function insertImageAtCursor(imageBlob: Blob) {
        const id = crypto.randomUUID();
        const filename = `image_${id}.jpg`;
        
        // Find the current line number based on cursor position
        const lines = messageText.slice(0, cursorPosition).split('\n');
        const currentLineIndex = lines.length - 1;
        
        // Insert newlines to create space for the image
        const before = messageText.slice(0, cursorPosition);
        const after = messageText.slice(cursorPosition);
        
        // Add extra newlines to create space for the image
        messageText = before + 
            '\n\u200B\n\n' +  // Zero-width space as placeholder with extra newlines
            after;
        
        const newImage: InlineImage = { 
            id, 
            blob: imageBlob, 
            filename,
            lineIndex: currentLineIndex + 1  // Position after the current line
        };
        inlineImages = [...inlineImages, newImage];
        
        // Adjust cursor position after insertion
        setTimeout(() => {
            if (textareaElement) {
                textareaElement.selectionStart = cursorPosition + 3;
                textareaElement.selectionEnd = cursorPosition + 3;
                textareaElement.focus();
            }
        }, 0);
    }

    // Function to handle auto-resizing of the textarea
    function adjustHeight() {
        if (textareaElement) {
            textareaElement.style.height = 'auto';
            textareaElement.style.height = Math.min(textareaElement.scrollHeight, 250) + 'px';
        }
    }

    // Handler for file selection
    function handleFileSelect() {
        fileInput.click();
    }

    // Handler for camera activation
    async function handleCameraClick() {
        try {
            // Request camera access
            stream = await navigator.mediaDevices.getUserMedia({ 
                video: { facingMode: 'environment' },
                audio: false 
            });
            
            if (stream) {
                showCamera = true;
                // Wait for DOM update
                await tick();
                if (videoElement) {
                    videoElement.srcObject = stream;
                }
            }
        } catch (err) {
            console.error('Camera access error:', err);
            // Fallback to basic file input if camera access fails
            cameraInput.removeAttribute('capture');
            cameraInput.click();
        }
    }

    // Function to capture photo
    async function capturePhoto() {
        if (!videoElement) return;

        const canvas = document.createElement('canvas');
        canvas.width = videoElement.videoWidth;
        canvas.height = videoElement.videoHeight;
        const ctx = canvas.getContext('2d');
        
        if (ctx) {
            ctx.drawImage(videoElement, 0, 0);
            
            // Convert to file
            canvas.toBlob((blob) => {
                if (blob) {
                    insertImageAtCursor(blob);
                }
            }, 'image/jpeg');
        }

        closeCamera();
    }

    // Function to close camera
    function closeCamera() {
        if (stream) {
            stream.getTracks().forEach(track => track.stop());
            stream = null;
        }
        showCamera = false;
    }

    // Clean up on component destruction
    onDestroy(() => {
        closeCamera();
    });

    // Handler for when files are selected
    function onFileSelected(event: Event) {
        const input = event.target as HTMLInputElement;
        if (input.files && input.files.length > 0) {
            // TODO: Handle the selected file
            console.log('File selected:', input.files[0]);
        }
    }

    // Handler for when media is captured
    function onMediaCaptured(event: Event) {
        const input = event.target as HTMLInputElement;
        if (input.files && input.files.length > 0) {
            // TODO: Handle the captured media
            console.log('Media captured:', input.files[0]);
        }
    }

    // Get markdown representation of the content
    export function getMarkdownContent(): string {
        const lines = messageText.split('\n');
        
        // Replace zero-width spaces with image tags
        for (const img of inlineImages) {
            if (img.lineIndex < lines.length) {
                if (lines[img.lineIndex].includes('\u200B')) {
                    lines[img.lineIndex] = `![${img.filename}](${img.filename})`;
                }
            }
        }
        return lines.join('\n');
    }
</script>

<div class="message-container">
    <!-- Hidden file input -->
    <input
        bind:this={fileInput}
        type="file"
        on:change={onFileSelected}
        style="display: none"
    />
    
    <!-- Hidden camera input -->
    <input
        bind:this={cameraInput}
        type="file"
        accept="image/*"
        capture="environment"
        on:change={onMediaCaptured}
        style="display: none"
    />

    <div class="content-wrapper">
        <textarea
            bind:this={textareaElement}
            bind:value={messageText}
            on:input={handleInput}
            on:click={handleInput}
            placeholder="Type your message here..."
            rows="1"
        ></textarea>

        <!-- Inline images that follow text position -->
        {#each inlineImages as img}
            {@const lines = messageText.slice(0, messageText.length).split('\n')}
            {#if img.lineIndex < lines.length && lines[img.lineIndex].includes('\u200B')}
                <div 
                    class="inline-image-wrapper"
                    style="--line-position: {img.lineIndex * 1.5}em"
                >
                    <img
                        src={URL.createObjectURL(img.blob)}
                        alt="Inline"
                        class="inline-image"
                    />
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

    <!-- Action buttons container -->
    <div class="action-buttons">
        <!-- File upload button -->
        <button class="icon-button" on:click={handleFileSelect}>
            📎
        </button>
        
        <!-- Camera button -->
        <button class="icon-button" on:click={handleCameraClick}>
            📷
        </button>
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
        overflow-y: hidden;
        position: relative;
    }

    textarea {
        width: 100%;
        min-height: 60px;
        max-height: 168px;
        border: none;
        outline: none;
        resize: none;
        background: transparent;
        font-family: inherit;
        font-size: 1rem;
        line-height: 1.5;
        padding: 0.5rem 0;
        margin: 0;
        overflow-y: auto;
    }

    textarea::placeholder {
        color: #888;
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

    .content-wrapper {
        position: relative;
        width: 100%;
    }

    textarea {
        width: 100%;
        min-height: 60px;
        max-height: 168px;
        border: none;
        outline: none;
        resize: none;
        background: transparent;
        font-family: inherit;
        font-size: 1rem;
        line-height: 1.5;
        padding: 0.5rem 0;
        margin: 0;
        overflow-y: auto;
    }

    .inline-image-wrapper {
        position: absolute;
        left: 0;
        top: var(--line-position);
        height: 100px;
        margin-top: 10px;
        margin-bottom: 10px;
        background: #f5f5f5;
        border-radius: 8px;
        z-index: 1;
    }

    .inline-image {
        height: 100%;
        width: auto;
        object-fit: contain;
        border-radius: 6px;
    }

    /* Add padding to textarea lines that contain images */
    textarea {
        line-height: 1.5;
        padding-bottom: 90px; /* Ensure space for images */
    }
</style>
