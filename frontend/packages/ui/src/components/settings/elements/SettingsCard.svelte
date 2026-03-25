<!--
    SettingsCard — Section container card for settings pages.

    Replaces inline `.usage-card`, `.session-card`, `.passkey-item`,
    `.status-section` patterns across settings pages with a single canonical
    component supporting default, highlighted, and current variants.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    import type { Snippet } from 'svelte';

    /** Card visual variant */
    type CardVariant = 'default' | 'highlighted' | 'current';

    /** Card padding size */
    type CardPadding = 'sm' | 'md' | 'lg';

    /** Map padding prop to CSS values */
    const paddingMap: Record<CardPadding, string> = {
        sm: '1rem',
        md: '1.25rem',
        lg: '1.5rem',
    };

    let {
        variant = 'default' as CardVariant,
        highlightColor = '',
        padding = 'md' as CardPadding,
        ariaLabel = '',
        children,
    }: {
        variant?: CardVariant;
        highlightColor?: string;
        padding?: CardPadding;
        ariaLabel?: string;
        children: Snippet;
    } = $props();

    let resolvedHighlightColor = $derived(highlightColor || 'var(--color-primary-start)');
    let resolvedPadding = $derived(paddingMap[padding] || paddingMap.md);
</script>

<div
    class="settings-card {variant}"
    style="
        --card-padding: {resolvedPadding};
        --card-highlight-color: {resolvedHighlightColor};
    "
    aria-label={ariaLabel || undefined}
>
    {@render children()}
</div>

<style>
    .settings-card {
        padding: var(--card-padding);
        border-radius: 0.75rem;
        margin: 0 0.625rem;
        box-sizing: border-box;
    }

    /* ── Default variant ───────────────────────────────────────── */
    .settings-card.default {
        background: var(--color-grey-10);
        border: 0.0625rem solid var(--color-grey-25);
    }

    /* ── Highlighted variant ───────────────────────────────────── */
    .settings-card.highlighted {
        background: color-mix(in srgb, var(--card-highlight-color) 4%, var(--color-grey-0));
        border: 0.0625rem solid var(--card-highlight-color);
    }

    /* ── Current variant (highlighted + left accent) ───────────── */
    .settings-card.current {
        background: color-mix(in srgb, var(--card-highlight-color) 4%, var(--color-grey-0));
        border: 0.0625rem solid var(--card-highlight-color);
        border-left: 0.25rem solid var(--card-highlight-color);
    }
</style>
