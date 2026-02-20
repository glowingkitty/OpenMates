<script lang="ts">
    import { onDestroy } from 'svelte';
    import InlinePreviewBase from './InlinePreviewBase.svelte';
    
    // Props using Svelte 5 runes
    let { 
        src,
        filename,
        id,
        isRecording = false,
        originalUrl = undefined,
        // Upload state props — present on newly-inserted images before server confirms upload
        status = 'finished',
        uploadError = undefined
    }: {
        src: string;
        filename: string;
        id: string;
        isRecording?: boolean;
        originalUrl?: string | undefined;
        /** Embed status: 'uploading' | 'finished' | 'error' */
        status?: string;
        /** Error message when status is 'error' */
        uploadError?: string | undefined;
    } = $props();

    onDestroy(() => {
        // Clean up object URLs when component is destroyed
        if (src?.startsWith('blob:')) {
            URL.revokeObjectURL(src);
        }
        if (originalUrl?.startsWith('blob:')) {
            URL.revokeObjectURL(originalUrl);
        }
    });

    // Derived: whether to show the uploading overlay
    let isUploading = $derived(status === 'uploading');
    let isError = $derived(status === 'error');

    // --- Portrait detection ---
    // Detect if the image is portrait (taller than wide) so we can show
    // its full height instead of cropping it.
    // The preview container width is fixed at 300px (InlinePreviewBase).
    // For portrait images we compute a proportional height capped at 400px.
    const DEFAULT_HEIGHT_PX = 200;
    const MAX_HEIGHT_PX = 400;
    const CONTAINER_WIDTH_PX = 300;

    let isPortrait = $state(false);
    let cardHeight = $state(`${DEFAULT_HEIGHT_PX}px`);

    $effect(() => {
        // Re-run when src changes (e.g. after blob URL is replaced by S3 URL)
        if (!src) return;

        const img = new Image();
        img.onload = () => {
            const { naturalWidth, naturalHeight } = img;
            if (!naturalWidth || !naturalHeight) return;

            if (naturalHeight > naturalWidth) {
                // Portrait: scale height proportionally to the 300px container width
                const neededHeight = Math.round((CONTAINER_WIDTH_PX * naturalHeight) / naturalWidth);
                isPortrait = true;
                cardHeight = `${Math.min(neededHeight, MAX_HEIGHT_PX)}px`;
            } else {
                isPortrait = false;
                cardHeight = `${DEFAULT_HEIGHT_PX}px`;
            }
        };
        img.src = src;
    });
</script>

<InlinePreviewBase {id} type={isRecording ? 'photos_recording' : 'photos'} {src} {filename} height={cardHeight}>
    <div class="photo-container">
        <div 
            class="photo-preview" 
            class:uploading={isUploading}
            class:portrait={isPortrait}
            style="background-image: url('{src}')"
            data-original-url={originalUrl || src}
        ></div>
        {#if isUploading}
            <!-- Uploading overlay: dimmed photo + spinner -->
            <div class="upload-overlay">
                <div class="upload-spinner" aria-label="Uploading…"></div>
                <span class="upload-label">Uploading…</span>
            </div>
        {:else if isError}
            <!-- Error overlay: dimmed photo + error message -->
            <div class="upload-overlay upload-overlay--error">
                <span class="upload-error-icon">!</span>
                <span class="upload-label">{uploadError || 'Upload failed'}</span>
            </div>
        {/if}
    </div>
</InlinePreviewBase>

<style>
    .photo-container {
        position: relative;
        width: 100%;
        height: 100%;
        background: var(--color-grey-20);
        border-radius: 24px;
        overflow: hidden;
    }

    .photo-preview {
        width: 100%;
        height: 100%;
        background-position: center;
        background-size: cover;
        background-repeat: no-repeat;
        transition: opacity 0.2s ease;
    }

    /*
     * Portrait (vertical) images: use contain so the full image height is
     * visible. The container height is expanded dynamically via the cardHeight
     * state variable passed to InlinePreviewBase.
     */
    .photo-preview.portrait {
        background-size: contain;
        background-color: var(--color-grey-15, #f0f0f0);
    }

    /* Dim the photo while uploading or on error */
    .photo-preview.uploading {
        opacity: 0.45;
    }

    /* ---- Upload overlay (shared by uploading + error states) ---- */
    .upload-overlay {
        position: absolute;
        inset: 0;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 8px;
        border-radius: 24px;
        pointer-events: none;
    }

    .upload-label {
        font-size: 0.75rem;
        font-weight: 500;
        color: #fff;
        text-shadow: 0 1px 3px rgba(0, 0, 0, 0.6);
        letter-spacing: 0.02em;
    }

    /* ---- Spinner ---- */
    .upload-spinner {
        width: 28px;
        height: 28px;
        border: 3px solid rgba(255, 255, 255, 0.4);
        border-top-color: #fff;
        border-radius: 50%;
        animation: spin 0.75s linear infinite;
    }

    @keyframes spin {
        to { transform: rotate(360deg); }
    }

    /* ---- Error icon ---- */
    .upload-error-icon {
        width: 28px;
        height: 28px;
        border-radius: 50%;
        background: rgba(220, 38, 38, 0.85);
        color: #fff;
        font-size: 1rem;
        font-weight: 700;
        display: flex;
        align-items: center;
        justify-content: center;
        line-height: 1;
    }
</style>
