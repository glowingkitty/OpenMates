<!--
    SettingsLoadingState — Loading spinner, empty state, and generating state.

    Replaces ~190 inline spinner definitions across settings pages with a
    single canonical component supporting spinner, empty, and generating
    variants with optional text and hint messages.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    /** Loading state variant */
    type LoadingVariant = 'spinner' | 'empty' | 'generating';

    let {
        variant = 'spinner' as LoadingVariant,
        text = '',
        hint = '',
    }: {
        variant?: LoadingVariant;
        text?: string;
        hint?: string;
    } = $props();

    let showSpinner = $derived(variant === 'spinner' || variant === 'generating');
</script>

<div
    class="settings-loading-state {variant}"
    role="status"
    aria-label={text || 'Loading'}
>
    {#if showSpinner}
        <div class="settings-loading-spinner" aria-hidden="true"></div>
    {/if}

    {#if text}
        <p class="settings-loading-text" class:pulse={variant === 'generating'}>{text}</p>
    {/if}

    {#if hint}
        <p class="settings-loading-hint">{hint}</p>
    {/if}
</div>

<style>
    .settings-loading-state {
        text-align: center;
        padding: 2.5rem 1.25rem;
        color: var(--color-font-secondary);
    }

    /* ── Spinner ────────────────────────────────────────────────── */
    .settings-loading-spinner {
        width: 1.5rem;
        height: 1.5rem;
        border: 0.1875rem solid var(--color-grey-30);
        border-top-color: var(--color-primary-start);
        border-radius: 50%;
        animation: settings-spin 1s linear infinite;
        margin: 0 auto;
    }

    /* ── Text ───────────────────────────────────────────────────── */
    .settings-loading-text {
        font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: var(--font-size-p, 0.875rem);
        font-weight: 500;
        line-height: 1.4;
        margin: 1rem 0 0 0;
        color: var(--color-font-secondary);
    }

    .settings-loading-text.pulse {
        animation: settings-pulse 2s ease-in-out infinite;
    }

    /* ── Hint ───────────────────────────────────────────────────── */
    .settings-loading-hint {
        font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: var(--processing-details-font-size, 0.8125rem);
        font-weight: 400;
        line-height: 1.4;
        margin: 0.5rem 0 0 0;
        color: var(--color-font-tertiary, var(--color-grey-50));
    }

    /* ── Keyframes ──────────────────────────────────────────────── */
    @keyframes settings-spin {
        to {
            transform: rotate(360deg);
        }
    }

    @keyframes settings-pulse {
        0%, 100% {
            opacity: 1;
        }
        50% {
            opacity: 0.5;
        }
    }
</style>
