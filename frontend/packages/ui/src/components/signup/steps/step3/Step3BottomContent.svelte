<script lang="ts">
    import { text } from '@repo/ui';
    import InputWarning from '../../../common/InputWarning.svelte';
    import Pica from 'pica';
    import { processedImageUrl } from '../../../../stores/profileImage';
    import { createEventDispatcher } from 'svelte';
    import { updateProfileImage } from '../../../../stores/userProfile';
    import { getApiEndpoint, apiEndpoints } from '../../../../config/api';
    import { fade } from 'svelte/transition';
    import { authStore } from '../../../../stores/authStore';

    let errorMessage = '';
    let showWarning = false;
    let fileInput: HTMLInputElement;
    const MAX_FILE_SIZE = 2 * 1024 * 1024; // 1MB in bytes
    const TARGET_SIZE = 340;
    const pica = new Pica();
    let isProcessing = false;
    let isUploading = false;
    const dispatch = createEventDispatcher();
    let showUploadButton = true;
    let showLastWarning = false;
    const WARNING_DISPLAY_TIME = 10000; // 10 seconds

    async function uploadImage(blob: Blob): Promise<string> {
        const formData = new FormData();
        formData.append('file', blob);

        const response = await fetch(getApiEndpoint(apiEndpoints.settings.user.update_profile_image), {
            method: 'POST',
            body: formData,
            credentials: 'include'
        });

        const data = await response.json();
        
        if (data.status === 'error') {
            if (data.detail === "Image not allowed") {
                errorMessage = $text('settings.profile_image_not_allowed.text');
                showWarning = true;

                if (data.reject_count === 3) {  // Show last warning on 3rd attempt
                    // Hide upload button
                    showUploadButton = false;
                    
                    // After upload button fades out, show last warning
                    setTimeout(() => {
                        showWarning = false; // Hide the normal warning
                        showLastWarning = true;
                        // Show the warning for 10 seconds
                        setTimeout(() => {
                            showLastWarning = false;
                            showUploadButton = true;
                        }, WARNING_DISPLAY_TIME);
                    }, 300); // Wait for fade out to complete
                    
                    errorMessage = $text('settings.last_warning_image_not_allowed.text');
                }
                throw new Error(data.detail);
            }
        }

        if (data.status === 'account_deleted') {
            // Set local storage flag for 10 minute lockout
            localStorage.setItem('policy_violation_lockout', (Date.now() + 600000).toString());
            
            // Set flag in sessionStorage to show deletion message on login page
            sessionStorage.setItem('account_deleted', 'true');
            
            // Create and dispatch a custom event before logout
            window.dispatchEvent(new CustomEvent('account-deleted'));
            
            // Trigger logout with special flag for policy violation
            authStore.logout({ 
                skipServerLogout: true,
                isPolicyViolation: true 
            });
            throw new Error('account_deleted');
        }

        if (!response.ok) {
            throw new Error('Upload failed');
        }

        return data.url;
    }

    async function processImage(file: File) {
        isProcessing = true;
        dispatch('uploading', { isProcessing, isUploading });
        showWarning = false; // Reset warning state

        try {
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

            // After processing, start upload
            isProcessing = false;
            isUploading = true;
            dispatch('uploading', { isProcessing, isUploading });

            const imageUrl = await uploadImage(blob);

            // Update store only if upload was successful
            processedImageUrl.set(processedUrl);
            
            // Also update the user profile store with the uploaded image URL
            updateProfileImage(imageUrl);

            // Cleanup
            URL.revokeObjectURL(img.src);

            // Auto-progress to next step only if everything succeeded
            dispatch('step', { step: 4 });
        } finally {
            isProcessing = false;
            isUploading = false;
            dispatch('uploading', { isProcessing, isUploading });
        }
    }

    function handleFileSelect(event: Event) {
        const input = event.target as HTMLInputElement;
        const file = input.files?.[0];

        if (file) {
            if (file.size > MAX_FILE_SIZE) {
                errorMessage = $text('signup.image_too_large.text');
                showWarning = true;
                input.value = ''; // Clear the input
                return;
            }

            if (!file.type.match(/^image\/(jpeg|png)$/)) {
                errorMessage = $text('signup.image_wrong_filetype.text');
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
    {#if showUploadButton}
        <label class="file-upload-field" transition:fade={{ duration: 300 }}>
            <input 
                bind:this={fileInput}
                type="file"
                accept=".jpg,.jpeg,.png,image/jpeg,image/png"
                class="file-input"
                on:change={handleFileSelect}
            />
            <span class="file-upload-button" class:error={showWarning}>
                <div class="file-icon"></div>
                <span class="upload-text">{@html $text('signup.upload_profile_image.text')}</span>
            </span>
        </label>
        {#if showWarning && errorMessage && !showLastWarning}
            <InputWarning 
                message={errorMessage}
                target={fileInput}
            />
        {/if}
    {:else if showLastWarning}
        <div class="warning-message" transition:fade={{ duration: 300 }}>
            {@html $text('settings.last_warning_image_not_allowed.text')}
        </div>
    {/if}
</div>

<style>
    .bottom-content {
        padding: 24px;
        display: flex;
        flex-direction: column;
        align-items: center;  /* Add this line */
        gap: 16px;
    }

    .file-upload-field {
        padding: 12px 16px 12px 45px;
        padding-left: 0px;
        display: block;  /* Add this line */
        margin: 0 auto;  /* Add this line */
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
        background: var(--color-primary);
        -webkit-mask: url('@openmates/ui/static/icons/files.svg') center / contain no-repeat;
        mask: url('@openmates/ui/static/icons/files.svg') center / contain no-repeat;
    }

    .upload-text {
        font-size: 16px;
        color: transparent;
        background: var(--color-primary);
        -webkit-background-clip: text;
        background-clip: text;
        -webkit-text-fill-color: transparent;
    }

    .loading-text {
        text-align: center;
        color: var(--color-grey-60);
        font-size: 14px;
        margin-bottom: 8px;
    }

    .warning-message {
        padding: 16px;
        background-color: var(--color-error-light);
        color: var(--color-error-dark);
        border: 1px solid var(--color-error);
        border-radius: 12px;
        text-align: center;
        font-weight: 500;
        max-width: 350px;
        margin: 0 auto;
    }
</style>
