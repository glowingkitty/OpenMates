<!--
    SettingsDetailRow — Key-value pair row for displaying details in settings pages.

    Replaces custom `.billing-row`, `.detail-row`, `.status-row`, `.detail-item`
    patterns across settings pages with a single canonical component.
    Designed to be placed inside a SettingsCard with no wrapper padding.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    let {
        label,
        value = '',
        muted = false,
        highlight = false,
        icon = '',
        iconColor = '',
        ariaLabel = '',
    }: {
        label: string;
        value?: string;
        muted?: boolean;
        highlight?: boolean;
        icon?: string;
        iconColor?: string;
        ariaLabel?: string;
    } = $props();
</script>

<div
    class="settings-detail-row"
    class:muted
    aria-label={ariaLabel || undefined}
>
    <span class="detail-label">{label}</span>
    <span class="detail-value" class:highlight>
        {#if icon}
            <span
                class="detail-icon clickable-icon {icon}"
                style:background-color={iconColor || undefined}
            ></span>
        {/if}
        {value}
    </span>
</div>

<style>
    .settings-detail-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0.5rem 0;
        border-bottom: 0.0625rem solid var(--color-grey-20);
    }

    .settings-detail-row:last-child {
        border-bottom: none;
    }

    .settings-detail-row.muted {
        opacity: 0.7;
    }

    .detail-label {
        font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: var(--font-size-p, 0.875rem);
        color: var(--color-font-secondary);
    }

    .detail-value {
        display: flex;
        align-items: center;
        gap: 0.375rem;
        font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: var(--font-size-p, 0.875rem);
        font-weight: 500;
        color: var(--color-font-primary);
    }

    .detail-value.highlight {
        color: var(--color-primary-start);
    }

    .detail-icon {
        width: 1rem;
        height: 1rem;
        flex-shrink: 0;
    }
</style>
