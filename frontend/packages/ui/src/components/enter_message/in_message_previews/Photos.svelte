<script lang="ts">
    import { onDestroy } from 'svelte';
    import InlinePreviewBase from './InlinePreviewBase.svelte';
    
    // Props using Svelte 5 runes
    let { 
        src,
        filename,
        id,
        isRecording = false,
        originalUrl = undefined
    }: {
        src: string;
        filename: string;
        id: string;
        isRecording?: boolean;
        originalUrl?: string | undefined;
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
</script>

<InlinePreviewBase {id} type={isRecording ? 'photos_recording' : 'photos'} {src} {filename} height="200px">
    <div class="photo-container">
        <div 
            class="photo-preview" 
            style="background-image: url('{src}')"
            data-original-url={originalUrl || src}
        />
    </div>
</InlinePreviewBase>

<style>
    .photo-container {
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
    }
</style> 