<!--
    SettingsBadge — Status badge/pill for settings pages.

    Replaces custom `.current-badge`, `.new-badge`, `.sign-count` patterns
    across settings pages with a single canonical component supporting
    info, success, warning, danger, and neutral variants.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    /** Badge color variant */
    type BadgeVariant = 'info' | 'success' | 'warning' | 'danger' | 'neutral';

    let {
        variant = 'neutral' as BadgeVariant,
        text,
    }: {
        variant?: BadgeVariant;
        text: string;
    } = $props();
</script>

<span class="settings-badge {variant}">{text}</span>

<style>
    .settings-badge {
        display: inline-block;
        padding: 0.125rem 0.625rem;
        border-radius: 0.75rem;
        font-size: var(--processing-details-font-size, 0.6875rem);
        font-weight: 500;
        white-space: nowrap;
    }

    .settings-badge.info {
        background: color-mix(in srgb, var(--color-info) 12%, transparent);
        color: var(--color-info);
    }

    .settings-badge.success {
        background: color-mix(in srgb, var(--color-success) 12%, transparent);
        color: var(--color-success);
    }

    .settings-badge.warning {
        background: color-mix(in srgb, var(--color-warning) 12%, transparent);
        color: var(--color-warning-dark, #856404);
    }

    .settings-badge.danger {
        background: color-mix(in srgb, var(--color-error) 12%, transparent);
        color: var(--color-error);
    }

    .settings-badge.neutral {
        background: var(--color-grey-20);
        color: var(--color-font-secondary);
    }
</style>
