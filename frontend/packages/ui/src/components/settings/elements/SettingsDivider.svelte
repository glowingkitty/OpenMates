<!--
    SettingsDivider — Horizontal section separator for settings pages.

    Replaces `.section-divider`, `hr` elements, and `border-bottom` patterns
    across settings pages with a single canonical component supporting
    three spacing variants.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    /** Vertical spacing around the divider */
    type DividerSpacing = 'sm' | 'md' | 'lg';

    let {
        spacing = 'md' as DividerSpacing,
    }: {
        spacing?: DividerSpacing;
    } = $props();
</script>

<hr class="settings-divider {spacing}" aria-hidden="true" />

<style>
    .settings-divider {
        height: 0.0625rem;
        background: var(--color-grey-25);
        border: none;
        margin-left: 0.625rem;
        margin-right: 0.625rem;
    }

    /* ── Spacing variants ──────────────────────────────────────── */
    .settings-divider.sm {
        margin-top: 0.5rem;
        margin-bottom: 0.5rem;
    }

    .settings-divider.md {
        margin-top: 0.75rem;
        margin-bottom: 0.75rem;
    }

    .settings-divider.lg {
        margin-top: 1rem;
        margin-bottom: 1rem;
    }
</style>
