<!--
    SettingsGradientLink — Gradient-colored clickable text link for settings pages.

    Replaces `.settings-gradient-link`, `.btn-link` patterns across settings
    pages with a single canonical component. Renders as an `<a>` when href
    is provided, otherwise as a `<button>` with reset styles.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    import type { Snippet } from 'svelte';

    let {
        href = '',
        external = false,
        onClick = undefined,
        ariaLabel = '',
        children,
    }: {
        href?: string;
        external?: boolean;
        onClick?: (() => void) | undefined;
        ariaLabel?: string;
        children: Snippet;
    } = $props();

    let isLink = $derived(!!href);

    function handleClick() {
        onClick?.();
    }
</script>

<div class="settings-gradient-link-wrapper">
    {#if isLink}
        <a
            class="settings-gradient-link"
            {href}
            target={external ? '_blank' : undefined}
            rel={external ? 'noopener noreferrer' : undefined}
            aria-label={ariaLabel || undefined}
            onclick={onClick ? handleClick : undefined}
        >
            {@render children()}
        </a>
    {:else}
        <button
            class="settings-gradient-link settings-gradient-link-button"
            aria-label={ariaLabel || undefined}
            onclick={handleClick}
        >
            {@render children()}
        </button>
    {/if}
</div>

<style>
    .settings-gradient-link-wrapper {
        padding: 0 0.625rem;
    }

    .settings-gradient-link {
        font-size: var(--font-size-p, 1rem);
        font-weight: 700;
        background: var(--color-primary);
        -webkit-background-clip: text;
        background-clip: text;
        -webkit-text-fill-color: transparent;
        text-decoration: none;
        cursor: pointer;
        transition: opacity var(--duration-normal) var(--easing-default);
    }

    .settings-gradient-link:hover {
        opacity: 0.8;
    }

    .settings-gradient-link:focus-visible {
        outline: 0.125rem solid var(--color-primary-start);
        outline-offset: 0.125rem;
        border-radius: 0.25rem;
    }

    /* ── Button reset ──────────────────────────────────────────── */
    .settings-gradient-link-button {
        all: unset;
        font-size: var(--font-size-p, 1rem);
        font-weight: 700;
        background: var(--color-primary);
        -webkit-background-clip: text;
        background-clip: text;
        -webkit-text-fill-color: transparent;
        text-decoration: none;
        cursor: pointer;
        transition: opacity var(--duration-normal) var(--easing-default);
    }

    .settings-gradient-link-button:hover {
        opacity: 0.8;
    }

    .settings-gradient-link-button:focus-visible {
        outline: 0.125rem solid var(--color-primary-start);
        outline-offset: 0.125rem;
        border-radius: 0.25rem;
    }
</style>
