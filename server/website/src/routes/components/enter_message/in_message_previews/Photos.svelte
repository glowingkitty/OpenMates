<script lang="ts">
    import InlinePreviewBase from './InlinePreviewBase.svelte';
    
    // Props for the image preview
    export let src: string;
    export let filename: string;
    export let id: string;
    export let isRecording: boolean = false;
</script>

<InlinePreviewBase {id} type={isRecording ? 'photos_recording' : 'photos'} {src} {filename} height="200px">
    <div class="checkerboard-background">
        <img {src} alt="Preview" class="preview-image fill-container" />
    </div>
</InlinePreviewBase>

<style>
    .checkerboard-background {
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

    .preview-image.fill-container {
        width: 100%;
        height: 100%;
        object-fit: cover;
    }
</style> 