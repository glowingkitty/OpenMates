<!--
    SettingsAvatar — Circular profile picture with placeholder for settings pages.

    Replaces custom `.avatar`, `.avatar-placeholder`, `.profile-picture-container`
    patterns across settings pages with a single canonical component supporting
    small, medium, and large sizes with optional edit overlay.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    import type { Snippet } from 'svelte';
    /** Avatar size preset */
    type AvatarSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl';
    const iconAssets = import.meta.glob('../../../../static/icons/*.svg', {
        eager: true, query: '?url', import: 'default',
    }) as Record<string, string>;

    let {
        src = '',
        size = 'md' as AvatarSize,
        placeholder = '',
        editable = false,
        onEdit = undefined,
        ariaLabel = '',
        generatedIcon = '',
        generatedBackground = '',
        children = undefined,
    }: {
        src?: string;
        size?: AvatarSize;
        placeholder?: string;
        editable?: boolean;
        onEdit?: (() => void) | undefined;
        ariaLabel?: string;
        /** Optional Team-key-decrypted member avatar metadata. Existing neutral fallback stays unchanged. */
        generatedIcon?: string;
        generatedBackground?: string;
        /** Custom avatar content keeps encrypted Team image fetching in its own component. */
        children?: Snippet;
    } = $props();

    const safeIcon = $derived(/^[a-z0-9_-]+$/.test(generatedIcon) ? generatedIcon : 'mate');
    const iconUrl = $derived(iconAssets[`../../../../static/icons/${safeIcon}.svg`]
        ?? iconAssets['../../../../static/icons/mate.svg']);
    const safeBackground = $derived(/^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(generatedBackground)
        ? generatedBackground : '');

    function handleEditClick() {
        onEdit?.();
    }

</script>

<div class="settings-avatar">
    {#if editable}
    <button
        class="avatar-circle {size} editable"
        type="button"
        aria-label={ariaLabel || 'Edit avatar'}
        style:background={generatedIcon && !src ? safeBackground || 'var(--color-primary-start)' : undefined}
        onclick={handleEditClick}
    >
        {#if children}
            {@render children()}
        {:else if src}
            <img class="avatar-image" src={src} alt={ariaLabel || 'Avatar'} />
        {:else if generatedIcon}
            <span class="generated-avatar-icon" style:mask-image={`url("${iconUrl}")`}></span>
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
        style:background={generatedIcon && !src ? safeBackground || 'var(--color-primary-start)' : undefined}
    >
        {#if children}
            {@render children()}
        {:else if src}
            <img class="avatar-image" src={src} alt={ariaLabel || 'Avatar'} />
        {:else if generatedIcon}
            <span class="generated-avatar-icon" style:mask-image={`url("${iconUrl}")`}></span>
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
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 50%;
        overflow: hidden;
        flex-shrink: 0;
    }

    .generated-avatar-icon {
        width: 58%;
        height: 58%;
        background: var(--color-font-button);
        mask-size: contain;
        mask-position: center;
        mask-repeat: no-repeat;
    }

    /* ── Sizes ──────────────────────────────────────────────────── */
    .avatar-circle.xs {
        width: 2.625rem;
        height: 2.625rem;
    }

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

    .avatar-circle.xl {
        width: 9rem;
        height: 9rem;
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
