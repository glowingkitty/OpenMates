<!--
    SettingsPageContainer — Page-level wrapper for settings sub-pages.

    Replaces per-page `.container`, `.passkeys-container`, `.sessions-container`
    and similar custom wrappers with a single canonical component providing
    consistent padding, max-width, and centering.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    import type { Snippet } from 'svelte';

    /** Maximum width preset */
    type ContainerWidth = 'narrow' | 'default' | 'wide';

    let {
        maxWidth = 'default' as ContainerWidth,
        children,
    }: {
        maxWidth?: ContainerWidth;
        children: Snippet;
    } = $props();
</script>

<div class="settings-page-container {maxWidth}">
    {@render children()}
</div>

<style>
    .settings-page-container {
        padding: 0.75rem 0;
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
        margin: 0 auto;
        width: 100%;
        box-sizing: border-box;
    }

    /* ── Width variants ────────────────────────────────────────── */
    .settings-page-container.narrow {
        max-width: 24rem;
    }

    .settings-page-container.default {
        max-width: 32rem;
    }

    .settings-page-container.wide {
        max-width: 40rem;
    }
</style>
