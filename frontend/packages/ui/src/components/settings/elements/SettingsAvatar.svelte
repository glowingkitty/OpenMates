<!--
    SettingsAvatar — Circular profile picture with placeholder for settings pages.

    Replaces custom `.avatar`, `.avatar-placeholder`, `.profile-picture-container`
    patterns across settings pages with a single canonical component supporting
    small, medium, and large sizes with optional edit overlay.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    /** Avatar size preset */
    type AvatarSize = 'sm' | 'md' | 'lg';

    let {
        src = '',
        size = 'md' as AvatarSize,
        placeholder = '',
        editable = false,
        onEdit = undefined,
        ariaLabel = '',
    }: {
        src?: string;
        size?: AvatarSize;
        placeholder?: string;
        editable?: boolean;
        onEdit?: (() => void) | undefined;
        ariaLabel?: string;
    } = $props();

    function handleEditClick() {
        onEdit?.();
    }

    function handleKeydown(event: KeyboardEvent) {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            handleEditClick();
        }
    }
</script>

<div class="settings-avatar">
    {#if editable}
    <button
        class="avatar-circle {size} editable"
        type="button"
        aria-label={ariaLabel || 'Edit avatar'}
        onclick={handleEditClick}
    >
        {#if src}
            <img class="avatar-image" src={src} alt={ariaLabel || 'Avatar'} />
        {:else}
            <span class="avatar-placeholder clickable-icon {placeholder || 'icon_user'}"></span>
        {/if}
        <div class="avatar-edit-overlay">
            <span class="edit-icon clickable-icon icon_edit"></span>
        </div>
    </button>
    {:else}
    <div
        class="avatar-circle {size}"
        aria-label={ariaLabel || 'Avatar'}
    >
        {#if src}
            <img class="avatar-image" src={src} alt={ariaLabel || 'Avatar'} />
        {:else}
            <span class="avatar-placeholder clickable-icon {placeholder || 'icon_user'}"></span>
        {/if}
    </div>
    {/if}
</div>

<style>
    .settings-avatar {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 0.75rem;
    }

    .avatar-circle {
        position: relative;
        border-radius: 50%;
        overflow: hidden;
        flex-shrink: 0;
    }

    /* ── Sizes ──────────────────────────────────────────────────── */
    .avatar-circle.sm {
        width: 3rem;
        height: 3rem;
    }

    .avatar-circle.md {
        width: 5rem;
        height: 5rem;
    }

    .avatar-circle.lg {
        width: 7.5rem;
        height: 7.5rem;
    }

    /* ── Image ──────────────────────────────────────────────────── */
    .avatar-image {
        width: 100%;
        height: 100%;
        border-radius: 50%;
        object-fit: cover;
        border: 0.1875rem solid var(--color-grey-25);
    }

    /* ── Placeholder ────────────────────────────────────────────── */
    .avatar-placeholder {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 100%;
        height: 100%;
        background-color: var(--color-font-secondary);
        border-radius: 50%;
        -webkit-mask-size: 40%;
        mask-size: 40%;
        -webkit-mask-position: center;
        mask-position: center;
        -webkit-mask-repeat: no-repeat;
        mask-repeat: no-repeat;
    }

    .avatar-circle:not(.editable) .avatar-placeholder {
        background: var(--color-grey-20);
    }

    /* Placeholder icon inside the grey circle */
    .avatar-circle:not(.editable) .avatar-placeholder {
        background-color: var(--color-font-secondary);
    }

    /* ── Editable (button reset) ──────────────────────────────── */
    button.avatar-circle {
        all: unset;
        position: relative;
        border-radius: 50%;
        overflow: hidden;
        flex-shrink: 0;
        cursor: pointer;
        box-sizing: border-box;
    }

    .avatar-edit-overlay {
        position: absolute;
        inset: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        background: rgba(0, 0, 0, 0.4);
        opacity: 0;
        transition: opacity var(--duration-normal) var(--easing-default);
        border-radius: 50%;
    }

    .avatar-circle.editable:hover .avatar-edit-overlay,
    .avatar-circle.editable:focus-visible .avatar-edit-overlay {
        opacity: 1;
    }

    .avatar-circle.editable:focus-visible {
        outline: 0.125rem solid var(--color-primary-start);
        outline-offset: 0.125rem;
    }

    .edit-icon {
        width: 1.5rem;
        height: 1.5rem;
        background-color: var(--color-grey-0);
    }
</style>
