<script lang="ts">
    import { tick, onDestroy } from 'svelte';

    type TextSegment = {
        id: string;
        text: string;
    }

    type InlineImage = { 
        id: string, 
        blob: Blob, 
        filename: string
    };

    let textSegments: TextSegment[] = [{ id: 'initial', text: '' }];
    let inlineImages: InlineImage[] = [];
    let activeSegmentId = 'initial';

    // References for file input and camera input
    let fileInput: HTMLInputElement;
    let cameraInput: HTMLInputElement;
    let videoElement: HTMLVideoElement;
    let stream: MediaStream | null = null;
    let showCamera = false;

    // Insert image after the active segment
    function insertImageAtCursor(imageBlob: Blob) {
        const imageId = crypto.randomUUID();
        const newSegmentId = crypto.randomUUID();
        
        const newImage: InlineImage = { 
            id: imageId, 
            blob: imageBlob, 
            filename: `image_${imageId}.jpg`
        };
        
        // Find index of active segment
        const activeIndex = textSegments.findIndex(s => s.id === activeSegmentId);
        
        // Insert new segment after the image
        const newSegments = [
            ...textSegments.slice(0, activeIndex + 1),
            { id: newSegmentId, text: '' }
        ];
        
        textSegments = newSegments;
        inlineImages = [...inlineImages, newImage];
        activeSegmentId = newSegmentId;
        
        // Focus new segment
        setTimeout(() => {
            const newTextarea = document.getElementById(newSegmentId) as HTMLTextAreaElement;
            if (newTextarea) newTextarea.focus();
        }, 0);
    }

    // Get complete content in markdown format
    export function getMarkdownContent(): string {
        return textSegments.map((segment, index) => {
            const img = inlineImages[index];
            return segment.text + (img ? `\n![${img.filename}](${img.filename})\n` : '');
        }).join('');
    }

    // Handler for file selection
    function handleFileSelect() {
        fileInput.click();
    }

    // Handler for camera activation
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

    // Function to capture photo
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
                    insertImageAtCursor(blob);
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

    onDestroy(() => {
        closeCamera();
    });

    function onFileSelected(event: Event) {
        const input = event.target as HTMLInputElement;
        if (input.files && input.files.length > 0) {
            const file = input.files[0];
            insertImageAtCursor(file);
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

    <div class="scrollable-content">
        <div class="content-wrapper">
            {#each textSegments as segment, index}
                <textarea
                    id={segment.id}
                    bind:value={segment.text}
                    on:focus={() => activeSegmentId = segment.id}
                    placeholder="Type your message here..."
                    rows="1"
                ></textarea>
                
                {#if index < inlineImages.length}
                    <div class="image-container">
                        <img
                            src={URL.createObjectURL(inlineImages[index].blob)}
                            alt="Inline"
                            class="preview-image"
                        />
                    </div>
                {/if}
            {/each}
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
        <button class="icon-button" on:click={handleFileSelect}>
            📎
        </button>
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
        position: relative;
    }

    .scrollable-content {
        width: 100%;
        height: 100%;
        max-height: 250px; /* Adjust based on your needs */
        overflow-y: auto;
        position: relative;
        padding: 0.5rem 0;
    }

    .content-wrapper {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }

    textarea {
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
    }

    .image-container {
        width: 100%;
        height: 100px;
        margin: 0.5rem 0;
    }

    .preview-image {
        height: 100%;
        width: auto;
        max-width: 80%;
        object-fit: contain;
        border-radius: 6px;
        background: #f5f5f5;
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
</style>
