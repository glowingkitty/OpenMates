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
        dataTestid,
        onFileSelected,
    }: {
        accept?: string;
        label?: string;
        disabled?: boolean;
        ariaLabel?: string;
        dataTestid: string;
        onFileSelected: (file: File) => void;
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
        data-testid={`${dataTestid}-input`}
    />

    <!-- Styled clickable area -->
    {#if disabled}
    <div
        class="settings-file-upload disabled"
        class:has-file={selectedFileName}
        onclick={handleClick}
        onkeydown={handleKeydown}
        role="button"
        tabindex="-1"
        aria-label={ariaLabel || label || 'Select file'}
        data-testid={dataTestid}
    >
        <div class="file-icon" aria-hidden="true"></div>
        <span class="file-label">{selectedFileName || label}</span>
    </div>
    {:else}
    <div
        class="settings-file-upload"
        class:has-file={selectedFileName}
        onclick={handleClick}
        onkeydown={handleKeydown}
        role="button"
        tabindex="0"
        aria-label={ariaLabel || label || 'Select file'}
        data-testid={dataTestid}
    >
        <div class="file-icon" aria-hidden="true"></div>
        <span class="file-label">{selectedFileName || label}</span>
    </div>
    {/if}
</div>

<style>
    .settings-file-upload-wrapper {
        padding: 0 var(--spacing-5);
    }

    .file-input-hidden {
        position: absolute;
        width: var(--spacing-1);
        height: var(--spacing-1);
        overflow: hidden;
        clip: rect(0, 0, 0, 0);
        white-space: nowrap;
        border: 0;
    }

    .settings-file-upload {
        display: flex;
        align-items: center;
        gap: var(--spacing-8);
        width: 100%;
        padding: var(--spacing-6) var(--spacing-12);
        background: var(--color-grey-0);
        border: none;
        border-radius: var(--radius-full);
        box-shadow: var(--shadow-xs);
        cursor: pointer;
        transition: box-shadow var(--duration-normal) var(--easing-default);
        box-sizing: border-box;
    }

    .settings-file-upload:hover {
        box-shadow: var(--shadow-md);
    }

    .settings-file-upload:focus-visible {
        box-shadow: var(--shadow-md),
                    0 0 0 var(--spacing-1) var(--color-primary-start);
    }

    .settings-file-upload.disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .file-icon {
        flex-shrink: 0;
        width: var(--icon-size-md);
        height: var(--icon-size-md);
        -webkit-mask-image: url('@openmates/ui/static/icons/files.svg');
        -webkit-mask-size: contain;
        -webkit-mask-repeat: no-repeat;
        -webkit-mask-position: center;
        mask-image: url('@openmates/ui/static/icons/files.svg');
        mask-size: contain;
        mask-repeat: no-repeat;
        mask-position: center;
        background: var(--color-primary);
    }

    .file-label {
        font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-weight: 700;
        font-size: var(--input-font-size);
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
        background: var(--color-primary-start);
    }
</style>
