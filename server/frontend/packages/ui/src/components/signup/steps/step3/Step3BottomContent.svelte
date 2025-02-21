<script lang="ts">
    import { _ } from 'svelte-i18n';
    import InputWarning from '../../../common/InputWarning.svelte';

    let errorMessage = '';
    let showWarning = false;
    let fileInput: HTMLInputElement;
    const MAX_FILE_SIZE = 1 * 1024 * 1024; // 1MB in bytes

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
            // Handle valid file here
        }
    }

    // TODO Image processing: crop image to square and scale down to 340x340px using pica before showing in preview and uploading
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
