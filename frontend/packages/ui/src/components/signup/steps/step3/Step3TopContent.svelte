<script lang="ts">
    import { text } from '@repo/ui';
    import { processedImageUrl } from '../../../../stores/profileImage';
    export let username: string;
    export let isProcessing = false;
    export let isUploading = false;
</script>

<div class="content">
    <h2>{@html $text('chat.welcome.hey.text')} {username}</h2>
    <div class="image-container">
        <div class="image-circle">
            {#if $processedImageUrl}
                <div 
                    class="preview-image" 
                    class:dimmed={isUploading}
                    style="background-image: url({$processedImageUrl})"
                ></div>
            {:else}
                <div class="clickable-icon icon_image"></div>
            {/if}
        </div>
        {#if isProcessing || isUploading}
            <div class="upload-indicator" class:processing={isProcessing}></div>
        {/if}
    </div>
</div>

<style>
    .content {
        padding: 24px;
        height: 100%;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 24px;
    }

    .image-container {
        position: relative;
        width: 170px;
        height: 170px;
    }

    .image-circle {
        position: absolute;
        width: 100%;
        height: 100%;
        border-radius: 50%;
        background-color: var(--color-grey-10);
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        display: flex;
        justify-content: center;
        align-items: center;
        overflow: hidden;
    }

    .image-circle.uploading .preview-image {
        opacity: 0.5;
    }

    .image-circle :global(.clickable-icon) {
        width: 75px;
        height: 75px;
        opacity: 0.5;
        cursor: unset;
    }

    .preview-image {
        width: 100%;
        height: 100%;
        background-size: cover;
        background-position: center;
        transition: opacity 0.3s ease;
    }

    .preview-image.dimmed {
        opacity: 0.5;
    }

    .upload-indicator {
        position: absolute;
        bottom: 0;
        right: 0;
        width: 32px;
        height: 32px;
        background: var(--color-primary);
        -webkit-mask: url('@openmates/ui/static/icons/upload.svg') center / contain no-repeat;
        mask: url('@openmates/ui/static/icons/upload.svg') center / contain no-repeat;
    }

    .upload-indicator.processing {
        animation: pulse 1.5s ease-in-out infinite;
    }

    @keyframes pulse {
        0% { opacity: 0.4; }
        50% { opacity: 1; }
        100% { opacity: 0.4; }
    }
</style>
