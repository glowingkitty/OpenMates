<script lang="ts">
    import { _ } from 'svelte-i18n';
    import InputWarning from '../../../common/InputWarning.svelte';
    import Pica from 'pica';
    import { processedImageUrl } from '../../../../stores/profileImage';

    let errorMessage = '';
    let showWarning = false;
    let fileInput: HTMLInputElement;
    const MAX_FILE_SIZE = 2 * 1024 * 1024; // 1MB in bytes
    const TARGET_SIZE = 340;
    const pica = new Pica();

    async function processImage(file: File) {
        // Create source image
        const img = new Image();
        img.src = URL.createObjectURL(file);
        
        await new Promise((resolve) => img.onload = resolve);

        // Calculate crop dimensions
        const size = Math.min(img.width, img.height);
        const startX = (img.width - size) / 2;
        const startY = (img.height - size) / 2;

        // Create source canvas with cropped image
        const sourceCanvas = document.createElement('canvas');
        sourceCanvas.width = size;
        sourceCanvas.height = size;
        const ctx = sourceCanvas.getContext('2d')!;
        ctx.drawImage(img, startX, startY, size, size, 0, 0, size, size);

        // Create destination canvas
        const destCanvas = document.createElement('canvas');
        destCanvas.width = TARGET_SIZE;
        destCanvas.height = TARGET_SIZE;

        // Resize using pica
        await pica.resize(sourceCanvas, destCanvas, {
            unsharpAmount: 80,
            unsharpRadius: 0.6,
            unsharpThreshold: 2
        });

        // Convert to blob and create URL
        const blob = await pica.toBlob(destCanvas, 'image/jpeg', 0.9);
        const processedUrl = URL.createObjectURL(blob);
        
        // Update store
        processedImageUrl.set(processedUrl);

        // Cleanup
        URL.revokeObjectURL(img.src);
    }

    function handleFileSelect(event: Event) {
        const input = event.target as HTMLInputElement;
        const file = input.files?.[0];

        if (file) {
            if (file.size > MAX_FILE_SIZE) {
                errorMessage = $_('signup.image_too_large.text');
                showWarning = true;
                input.value = ''; // Clear the input
                return;
            }

            if (!file.type.match(/^image\/(jpeg|png)$/)) {
                errorMessage = $_('signup.image_wrong_filetype.text');
                showWarning = true;
                input.value = ''; // Clear the input
                return;
            }

            errorMessage = '';
            showWarning = false;
            processImage(file);
        }
    }
</script>

<div class="bottom-content">
    <label class="file-upload-field">
        <input 
            bind:this={fileInput}
            type="file"
            accept=".jpg,.jpeg,.png,image/jpeg,image/png"
            class="file-input"
            on:change={handleFileSelect}
        />
        <span class="file-upload-button" class:error={showWarning}>
            <div class="file-icon"></div>
            <span class="upload-text">{$_('signup.upload_profile_image.text')}</span>
        </span>
    </label>
    {#if showWarning && errorMessage}
        <InputWarning 
            message={errorMessage}
            target={fileInput}
        />
    {/if}
</div>

<style>
    .bottom-content {
        padding: 24px;
        display: flex;
        flex-direction: column;
        gap: 16px;
    }

    .file-upload-field {
        width: calc(100% - 60px);
        max-width: 350px;
        padding: 12px 16px 12px 45px; /* Add padding for icon */
        padding-left: 0px;

        /* Remove max-width since we're using fixed width */
        min-width: unset;  /* Remove min-width */
        cursor: pointer;
    }

    .file-input {
        position: absolute;
        width: 1px;
        height: 1px;
        padding: 0;
        margin: -1px;
        overflow: hidden;
        clip: rect(0, 0, 0, 0);
        border: 0;
    }

    .file-upload-button {
        display: flex;
        align-items: center;
        width: 100%;
        padding: 12px 16px 12px 48px;
        border-radius: 24px;
        border: 2px solid var(--color-grey-0);
        background-color: var(--color-grey-0);
        color: var(--color-grey-100);
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
        transition: all 0.2s ease-in-out;
        position: relative;
    }

    .file-upload-button:hover {
        border-color: var(--color-grey-50);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
        transform: translateY(-1px);
    }

    .file-upload-button.error {
        border-color: var(--color-error);
        background-color: var(--color-error-light);
    }

    .file-icon {
        position: absolute;
        left: 16px;
        width: 20px;
        height: 20px;
        background-image: url('@openmates/ui/static/icons/files.svg');
        background-position: center;
        background-repeat: no-repeat;
        background-size: contain;
        filter: brightness(0) saturate(100%) invert(65%) sepia(0%) saturate(0%) hue-rotate(153deg) brightness(89%) contrast(85%);
    }

    .upload-text {
        font-size: 16px;
        color: var(--color-grey-60);
    }

    .error-message {
        color: var(--color-error);
        font-size: 14px;
        margin-top: 8px;
        text-align: center;
    }
</style>
