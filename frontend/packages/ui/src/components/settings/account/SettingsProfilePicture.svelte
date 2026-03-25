<!--
Profile Picture - Account Settings Sub-page
Allows the user to upload a new profile picture from within account settings.

Image is processed client-side (canvas → square crop → 340×340 JPEG at quality 0.9)
before being sent to the upload server at POST /v1/upload/profile-image.

Response handling:
  - ok            → update userProfile store with new URL, show success state
  - rejected      → show content-safety warning (3rd attempt shows final warning)
  - account_deleted → set policy-violation lockout and logout immediately
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import InputWarning from '../../common/InputWarning.svelte';
    import { userProfile, updateProfileImage } from '../../../stores/userProfile';
    import { authStore } from '../../../stores/authStore';
    import { getUploadEndpoint, uploadEndpoints, getApiUrl } from '../../../config/api';
    import { getProfileImageBlobUrl, invalidateProfileImageCache } from '../../../services/profileImageService';
    import { fade } from 'svelte/transition';

    // =========================================================================
    // CONSTANTS
    // =========================================================================

    /** Maximum raw file size accepted before canvas processing (20 MB). */
    const MAX_FILE_SIZE = 20 * 1024 * 1024;

    /** Target pixel dimensions for the square output JPEG. */
    const TARGET_SIZE = 340;

    /** How long (ms) to display the final-warning message before restoring the upload button. */
    const WARNING_DISPLAY_TIME = 10_000;

    // =========================================================================
    // STATE
    // =========================================================================

    /** Whether the file is currently being processed / uploaded. */
    let isUploading = $state(false);

    /** Inline warning message. Empty string = no warning shown. */
    let warningMessage = $state('');

    /** Whether to show the upload button (hidden after 3rd violation). */
    let showUploadButton = $state(true);

    /** Whether to show the last-warning banner (replaces button after 3rd violation). */
    let showLastWarning = $state(false);

    /** Whether the last upload completed successfully. */
    let showSuccess = $state(false);

    /** Reference to the hidden file input. */
    let fileInput: HTMLInputElement = $state(undefined!);

    /**
     * Resolved blob URL (or legacy public URL) for the current profile image.
     * null while loading or if no profile image exists.
     */
    let resolvedAvatarUrl = $state<string | null>(null);

    $effect(() => {
        const rawUrl = $userProfile.profile_image_url;
        const userId = $userProfile.user_id ?? '';
        if (!rawUrl || !userId) {
            resolvedAvatarUrl = null;
            return;
        }
        // Stale-closure guard: if the effect re-runs before the previous fetch
        // resolves (e.g. due to an unrelated store update), cancel the old
        // .then() so it cannot overwrite the state set by a newer invocation.
        let cancelled = false;
        getProfileImageBlobUrl(rawUrl, getApiUrl(), userId).then((url) => {
            if (!cancelled) {
                resolvedAvatarUrl = url;
            }
        });
        return () => { cancelled = true; };
    });

    // =========================================================================
    // HELPERS
    // =========================================================================

    /**
     * Crop the given File to a square, resize to TARGET_SIZE, and return a JPEG Blob.
     * All processing happens on a canvas in the browser — the server never receives
     * the original raw image.
     */
    async function processImageToBlob(file: File): Promise<Blob> {
        const img = new Image();
        img.src = URL.createObjectURL(file);
        await new Promise<void>((resolve) => { img.onload = () => resolve(); });

        // Crop to square (center)
        const size = Math.min(img.width, img.height);
        const startX = (img.width - size) / 2;
        const startY = (img.height - size) / 2;

        const srcCanvas = document.createElement('canvas');
        srcCanvas.width = size;
        srcCanvas.height = size;
        srcCanvas.getContext('2d')!.drawImage(img, startX, startY, size, size, 0, 0, size, size);

        // Resize to TARGET_SIZE
        const destCanvas = document.createElement('canvas');
        destCanvas.width = TARGET_SIZE;
        destCanvas.height = TARGET_SIZE;
        destCanvas.getContext('2d')!.drawImage(srcCanvas, 0, 0, size, size, 0, 0, TARGET_SIZE, TARGET_SIZE);

        URL.revokeObjectURL(img.src);

        return new Promise<Blob>((resolve, reject) => {
            destCanvas.toBlob(
                (blob) => blob ? resolve(blob) : reject(new Error('Canvas toBlob returned null')),
                'image/jpeg',
                0.9
            );
        });
    }

    /**
     * Upload the processed JPEG blob to the upload server.
     * Returns the new profile image URL on success.
     * Throws on non-ok responses (after handling rejection / account_deleted states).
     */
    async function uploadBlob(blob: Blob): Promise<string> {
        const formData = new FormData();
        formData.append('file', blob);

        const response = await fetch(getUploadEndpoint(uploadEndpoints.profile_image), {
            method: 'POST',
            body: formData,
            credentials: 'include',
        });

        const data = await response.json();

        // Content safety violation
        if (data.status === 'rejected') {
            warningMessage = $text('settings.profile_image_not_allowed');

            if (data.reject_count === 3) {
                // 3rd violation — hide the upload button and show the final warning banner
                showUploadButton = false;
                setTimeout(() => {
                    warningMessage = '';
                    showLastWarning = true;
                    setTimeout(() => {
                        showLastWarning = false;
                        showUploadButton = true;
                    }, WARNING_DISPLAY_TIME);
                }, 300); // wait for upload-button fade-out transition
            }

            throw new Error('Image rejected by content safety');
        }

        // 4th violation — account deleted
        if (data.status === 'account_deleted') {
            localStorage.setItem('policy_violation_lockout', (Date.now() + 600_000).toString());
            sessionStorage.setItem('account_deleted', 'true');
            window.dispatchEvent(new CustomEvent('account-deleted'));
            authStore.logout({ skipServerLogout: true, isPolicyViolation: true });
            throw new Error('account_deleted');
        }

        if (!response.ok || data.status !== 'ok') {
            throw new Error(`Upload failed: ${data.detail ?? response.statusText}`);
        }

        return data.url as string;
    }

    // =========================================================================
    // EVENT HANDLERS
    // =========================================================================

    async function handleFileSelect(event: Event): Promise<void> {
        const input = event.target as HTMLInputElement;
        const file = input.files?.[0];
        if (!file) return;

        // Reset state
        warningMessage = '';
        showSuccess = false;

        // Validate before canvas work
        if (file.size > MAX_FILE_SIZE) {
            warningMessage = $text('settings.account.profile_picture.file_too_large');
            input.value = '';
            return;
        }

        if (!file.type.match(/^image\/(jpeg|png)$/)) {
            warningMessage = $text('settings.account.profile_picture.wrong_format');
            input.value = '';
            return;
        }

        isUploading = true;
        try {
            const blob = await processImageToBlob(file);
            const newUrl = await uploadBlob(blob);

            // Invalidate the cached blob URL so the next render fetches fresh
            const userId = $userProfile.user_id ?? '';
            if (userId) invalidateProfileImageCache(userId);

            // Force $effects watching profile_image_url to re-run even if the proxy URL
            // path is unchanged (same /v1/users/{id}/profile-image path before and after
            // re-upload). Svelte's $effect only re-runs when a reactive dependency changes
            // value — setting null first guarantees the subsequent set triggers all watchers.
            updateProfileImage(null);
            // Fetch the fresh blob URL for the local preview immediately, before the store
            // update so there is no flash of the placeholder.
            const freshBlobUrl = await getProfileImageBlobUrl(newUrl, getApiUrl(), userId);
            resolvedAvatarUrl = freshBlobUrl;
            // Now update the store — $effects in Settings.svelte and other consumers will
            // re-run (null → newUrl is a change) and pick up the already-cached blob URL.
            updateProfileImage(newUrl);
            showSuccess = true;
        } catch (err) {
            // rejection / account_deleted already handled inside uploadBlob;
            // only show generic error for unexpected failures
            const msg = err instanceof Error ? err.message : String(err);
            if (msg !== 'Image rejected by content safety' && msg !== 'account_deleted') {
                warningMessage = $text('settings.account.profile_picture.upload_error');
            }
            console.error('[SettingsProfilePicture] Upload error:', err);
        } finally {
            isUploading = false;
            input.value = '';
        }
    }
</script>

<div class="profile-picture-container">

    <!-- Current avatar preview.
         Uses resolvedAvatarUrl (blob: URL for encrypted images, direct URL for legacy).
         Falls back to placeholder while loading or when no image is set. -->
    <div class="avatar-section">
        {#if resolvedAvatarUrl}
            <img
                class="avatar"
                src={resolvedAvatarUrl}
                alt="Profile"
            />
        {:else}
            <div class="avatar avatar-placeholder"></div>
        {/if}
    </div>

    <!-- Upload control -->
    {#if showUploadButton}
        <div class="upload-section" transition:fade={{ duration: 300 }}>
            <label class="file-upload-label" class:disabled={isUploading}>
                <input
                    bind:this={fileInput}
                    type="file"
                    accept=".jpg,.jpeg,.png,image/jpeg,image/png"
                    class="file-input"
                    onchange={handleFileSelect}
                    disabled={isUploading}
                />
                <span class="file-upload-button" class:uploading={isUploading} class:error={!!warningMessage}>
                    <div class="file-icon"></div>
                    <span class="upload-text">
                        {isUploading
                            ? $text('settings.account.profile_picture.uploading')
                            : $text('settings.account.profile_picture.upload')}
                    </span>
                </span>
            </label>

            {#if warningMessage && !showLastWarning}
                <InputWarning message={warningMessage} />
            {/if}

            {#if showSuccess}
                <p class="success-message" transition:fade={{ duration: 200 }}>
                    {$text('settings.account.profile_picture.upload_success')}
                </p>
            {/if}
        </div>
    {:else if showLastWarning}
        <!-- Final policy warning — shown after 3rd violation, before account deletion -->
        <div class="last-warning-banner" transition:fade={{ duration: 300 }}>
            <!-- eslint-disable-next-line svelte/no-at-html-tags -->
            {@html $text('settings.last_warning_image_not_allowed')}
        </div>
    {/if}

</div>

<style>
    /* ── Page container ─────────────────────────────────────────────────────── */
    .profile-picture-container {
        padding: 24px;
        max-width: 480px;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 28px;
    }

    /* ── Avatar ─────────────────────────────────────────────────────────────── */
    .avatar-section {
        display: flex;
        justify-content: center;
    }

    .avatar {
        width: 120px;
        height: 120px;
        border-radius: 50%;
        object-fit: cover;
        border: 3px solid var(--color-grey-20);
    }

    .avatar-placeholder {
        background: var(--color-grey-20);
        display: flex;
        align-items: center;
        justify-content: center;
    }

    /* ── Upload section ─────────────────────────────────────────────────────── */
    .upload-section {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 16px;
        width: 100%;
    }

    /* Hidden native file input */
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

    .file-upload-label {
        display: block;
        cursor: pointer;
    }

    .file-upload-label.disabled {
        cursor: default;
        pointer-events: none;
    }

    /* Styled button wrapper */
    .file-upload-button {
        display: flex;
        align-items: center;
        gap: 0;
        padding: 12px 20px 12px 52px;
        border-radius: 24px;
        border: 2px solid var(--color-grey-0);
        background-color: var(--color-grey-0);
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
        transition: all 0.2s ease-in-out;
        position: relative;
    }

    .file-upload-button:hover {
        border-color: var(--color-grey-50);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
        transform: translateY(-1px);
    }

    .file-upload-button.uploading {
        opacity: 0.6;
        cursor: default;
    }

    .file-upload-button.error {
        border-color: var(--color-error);
        background-color: var(--color-error-light);
    }

    /* Upload icon */
    .file-icon {
        position: absolute;
        left: 18px;
        width: 20px;
        height: 20px;
        background: var(--color-primary);
        -webkit-mask: url('@openmates/ui/static/icons/files.svg') center / contain no-repeat;
        mask: url('@openmates/ui/static/icons/files.svg') center / contain no-repeat;
    }

    /* Gradient text label */
    .upload-text {
        font-size: 16px;
        color: transparent;
        background: var(--color-primary);
        -webkit-background-clip: text;
        background-clip: text;
        -webkit-text-fill-color: transparent;
        white-space: nowrap;
    }

    /* ── Success message ────────────────────────────────────────────────────── */
    .success-message {
        font-size: 14px;
        font-weight: 500;
        color: var(--color-success);
        margin: 0;
        text-align: center;
    }

    /* ── Last-warning banner ────────────────────────────────────────────────── */
    .last-warning-banner {
        padding: 16px;
        background-color: var(--color-error-light);
        color: var(--color-error-dark);
        border: 1px solid var(--color-error);
        border-radius: 12px;
        text-align: center;
        font-weight: 500;
        max-width: 380px;
    }
</style>
