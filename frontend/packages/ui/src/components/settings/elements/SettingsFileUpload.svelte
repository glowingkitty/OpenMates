<!--
    SettingsFileUpload — Shared file upload input for settings pages.

    Matches Figma "Input field - File upload" element:
    White background, 24px border-radius, box-shadow, file icon on left,
    "Select {filetypes} file" text with gradient. Clickable to open file dialog.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    let {
        accept = '',
        label = '',
        disabled = false,
        ariaLabel = '',
        onFileSelected = undefined,
    }: {
        accept?: string;
        label?: string;
        disabled?: boolean;
        ariaLabel?: string;
        onFileSelected?: ((file: File) => void) | undefined;
    } = $props();

    let fileInput: HTMLInputElement | undefined = $state();
    let selectedFileName = $state('');

    function handleClick() {
        if (!disabled && fileInput) {
            fileInput.click();
        }
    }

    function handleFileChange(event: Event) {
        const target = event.target as HTMLInputElement;
        const file = target.files?.[0];
        if (file) {
            selectedFileName = file.name;
            onFileSelected?.(file);
        }
    }

    function handleKeydown(event: KeyboardEvent) {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            handleClick();
        }
    }
</script>

<div class="settings-file-upload-wrapper">
    <!-- Hidden native file input -->
    <input
        bind:this={fileInput}
        type="file"
        {accept}
        {disabled}
        class="file-input-hidden"
        onchange={handleFileChange}
        tabindex="-1"
    />

    <!-- Styled clickable area -->
    <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
    <div
        class="settings-file-upload"
        class:disabled
        class:has-file={selectedFileName}
        onclick={handleClick}
        onkeydown={handleKeydown}
        role="button"
        tabindex={disabled ? -1 : 0}
        aria-label={ariaLabel || label || 'Select file'}
    >
        <div class="file-icon" aria-hidden="true">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                <polyline points="14 2 14 8 20 8"></polyline>
            </svg>
        </div>
        <span class="file-label">{selectedFileName || label}</span>
    </div>
</div>

<style>
    .settings-file-upload-wrapper {
        padding: 0 0.625rem;
    }

    .file-input-hidden {
        position: absolute;
        width: 1px;
        height: 1px;
        overflow: hidden;
        clip: rect(0, 0, 0, 0);
        white-space: nowrap;
        border: 0;
    }

    .settings-file-upload {
        display: flex;
        align-items: center;
        gap: 1rem;
        width: 100%;
        padding: 0.875rem 1.4375rem;
        background: var(--color-grey-0);
        border: none;
        border-radius: 1.5rem;
        box-shadow: 0 0.25rem 0.25rem rgba(0, 0, 0, 0.1);
        cursor: pointer;
        transition: box-shadow 0.2s ease;
        box-sizing: border-box;
    }

    .settings-file-upload:hover {
        box-shadow: 0 0.25rem 0.5rem rgba(0, 0, 0, 0.15);
    }

    .settings-file-upload:focus-visible {
        box-shadow: 0 0.25rem 0.5rem rgba(0, 0, 0, 0.15),
                    0 0 0 0.125rem var(--color-primary-start);
        outline: none;
    }

    .settings-file-upload.disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .file-icon {
        flex-shrink: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--color-grey-60);
    }

    .file-label {
        font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-weight: 700;
        font-size: var(--input-font-size, 1rem);
        line-height: 1.25;
        text-align: center;
        background: var(--color-primary);
        -webkit-background-clip: text;
        background-clip: text;
        -webkit-text-fill-color: transparent;
    }

    .has-file .file-label {
        /* When a file is selected, show filename in plain color instead of gradient */
        background: none;
        -webkit-background-clip: unset;
        background-clip: unset;
        -webkit-text-fill-color: var(--color-grey-100);
        color: var(--color-grey-100);
        font-weight: 500;
    }

    .has-file .file-icon {
        color: var(--color-primary-start);
    }
</style>
