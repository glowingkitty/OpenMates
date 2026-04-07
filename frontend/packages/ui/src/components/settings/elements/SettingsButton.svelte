<!--
    SettingsButton — Shared action button for settings pages.

    Replaces ~82 inline `.save-button`, `.primary-button`, `.delete-button`,
    `.cancel-button` patterns across settings pages with a single canonical
    component supporting primary, danger, secondary, and ghost variants.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    import type { Snippet } from 'svelte';

    /** Button visual variant */
    type ButtonVariant = 'primary' | 'danger' | 'secondary' | 'ghost';

    /** Button size */
    type ButtonSize = 'sm' | 'md';

    let {
        variant = 'primary' as ButtonVariant,
        disabled = false,
        loading = false,
        fullWidth = false,
        size = 'md' as ButtonSize,
        ariaLabel = '',
        dataTestid = '',
        onClick = undefined,
        children,
    }: {
        variant?: ButtonVariant;
        disabled?: boolean;
        loading?: boolean;
        fullWidth?: boolean;
        size?: ButtonSize;
        ariaLabel?: string;
        dataTestid?: string;
        onClick?: (() => void) | undefined;
        children: Snippet;
    } = $props();

    let isDisabled = $derived(disabled || loading);

    function handleClick() {
        if (!isDisabled) {
            onClick?.();
        }
    }
</script>

<div class="settings-button-wrapper">
    <button
        class="settings-button {variant} {size}"
        class:full-width={fullWidth}
        class:loading
        {disabled}
        aria-label={ariaLabel || undefined}
        aria-busy={loading || undefined}
        data-testid={dataTestid || undefined}
        onclick={handleClick}
    >
        {#if loading}
            <span class="settings-button-spinner" aria-hidden="true"></span>
        {/if}
        <span class="settings-button-label">
            {@render children()}
        </span>
    </button>
</div>

<style>
    .settings-button-wrapper {
        padding: 0 0.625rem;
    }

    .settings-button {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 0.5rem;
        border: none;
        border-radius: 1.5rem;
        font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-weight: 600;
        line-height: 1.25;
        cursor: pointer;
        transition: box-shadow var(--duration-normal) var(--easing-default), background var(--duration-normal) var(--easing-default), opacity var(--duration-normal) var(--easing-default);
        box-sizing: border-box;
    }

    /* ── Sizes ──────────────────────────────────────────────────── */
    .settings-button.sm {
        padding: 0.5rem 1rem;
        font-size: var(--processing-details-font-size, 0.8125rem);
    }

    .settings-button.md {
        padding: 0.75rem 1.5rem;
        font-size: var(--font-size-p, 0.875rem);
    }

    /* ── Variants ───────────────────────────────────────────────── */
    .settings-button.primary {
        background: linear-gradient(135deg, var(--color-primary-start), var(--color-primary-end));
        color: var(--color-grey-0);
        box-shadow: 0 0.25rem 0.25rem rgba(0, 0, 0, 0.1);
    }

    .settings-button.primary:hover:not(:disabled) {
        box-shadow: 0 0.375rem 0.5rem rgba(0, 0, 0, 0.15);
    }

    .settings-button.danger {
        background: var(--color-error);
        color: var(--color-grey-0);
        box-shadow: 0 0.25rem 0.25rem rgba(0, 0, 0, 0.1);
    }

    .settings-button.danger:hover:not(:disabled) {
        box-shadow: 0 0.375rem 0.5rem rgba(0, 0, 0, 0.15);
    }

    .settings-button.secondary {
        background: var(--color-grey-0);
        border: 0.0625rem solid var(--color-grey-30);
        color: var(--color-font-primary);
    }

    .settings-button.secondary:hover:not(:disabled) {
        background: var(--color-grey-10);
    }

    .settings-button.ghost {
        background: transparent;
        color: var(--color-font-secondary);
        border: none;
    }

    .settings-button.ghost:hover:not(:disabled) {
        background: var(--color-grey-10);
    }

    /* ── States ─────────────────────────────────────────────────── */
    .settings-button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .settings-button.full-width {
        width: 100%;
    }

    .settings-button:focus-visible {
        outline: 0.125rem solid var(--color-primary-start);
        outline-offset: 0.125rem;
    }

    /* ── Loading spinner ───────────────────────────────────────── */
    .settings-button-spinner {
        display: inline-block;
        width: 1rem;
        height: 1rem;
        border: 0.125rem solid rgba(255, 255, 255, 0.3);
        border-top-color: #ffffff;
        border-radius: 50%;
        animation: settings-button-spin 1s linear infinite;
        flex-shrink: 0;
    }

    .settings-button.secondary .settings-button-spinner,
    .settings-button.ghost .settings-button-spinner {
        border-color: var(--color-grey-30);
        border-top-color: var(--color-font-primary);
    }

    .settings-button-label {
        display: inline-flex;
        align-items: center;
    }

    @keyframes settings-button-spin {
        to {
            transform: rotate(360deg);
        }
    }
</style>
