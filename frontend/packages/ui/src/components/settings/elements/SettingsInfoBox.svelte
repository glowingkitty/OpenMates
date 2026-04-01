<!--
    SettingsInfoBox — Reusable info/success/error/warning message box for settings pages.

    Replaces custom `.disclaimer`, `.message`, `.error-message`, `.success-message`,
    `.processing-message`, `.cancellation-notice` patterns across settings pages with
    a single canonical component.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    import type { Snippet } from 'svelte';

    /** Box variant — controls background, border, and icon colors */
    type InfoBoxType = 'info' | 'success' | 'error' | 'warning';

    let {
        type = 'info' as InfoBoxType,
        icon = '' as string,
        ariaLabel = '',
        children,
    }: {
        type?: InfoBoxType;
        icon?: string;
        ariaLabel?: string;
        children: Snippet;
    } = $props();

    /** Default icon per type (can be overridden via the icon prop) */
    const defaultIcons: Record<InfoBoxType, string> = {
        info: 'icon_info',
        success: 'icon_check',
        error: 'icon_warning',
        warning: 'icon_warning',
    };

    let resolvedIcon = $derived(icon || defaultIcons[type] || defaultIcons.info);
</script>

<div
    class="settings-info-box {type}"
    data-testid={type === 'success' ? 'settings-info-box-success' : undefined}
    role={type === 'error' || type === 'warning' ? 'alert' : 'status'}
    aria-label={ariaLabel || undefined}
>
    <span class="clickable-icon {resolvedIcon} info-box-icon"></span>
    <div class="info-box-content">
        {@render children()}
    </div>
</div>

<style>
    .settings-info-box {
        display: flex;
        align-items: flex-start;
        gap: 0.75rem;
        padding: 1rem 1.125rem;
        border-radius: 1.5rem;
        margin: 0 0.625rem;
        background: var(--color-grey-0);
        box-shadow: 0 0.25rem 0.25rem rgba(0, 0, 0, 0.1);
        border-left: 0.25rem solid transparent;
    }

    /* Type-specific border + icon colors */
    .settings-info-box.info {
        border-left-color: var(--color-info, #2196f3);
    }

    .settings-info-box.success {
        border-left-color: var(--color-success, #4caf50);
    }

    .settings-info-box.error {
        border-left-color: var(--color-error, #f44336);
    }

    .settings-info-box.warning {
        border-left-color: var(--color-warning, #ffc107);
    }

    .info-box-icon {
        width: 1.25rem;
        height: 1.25rem;
        margin-top: 0.125rem;
        flex-shrink: 0;
    }

    .settings-info-box.info .info-box-icon {
        background-color: var(--color-info, #2196f3);
    }

    .settings-info-box.success .info-box-icon {
        background-color: var(--color-success, #4caf50);
    }

    .settings-info-box.error .info-box-icon {
        background-color: var(--color-error, #f44336);
    }

    .settings-info-box.warning .info-box-icon {
        background-color: var(--color-warning-dark, #856404);
    }

    .info-box-content {
        flex: 1;
        font-size: var(--font-size-p, 0.875rem);
        line-height: 1.4;
        color: var(--color-font-primary);
    }

    .info-box-content :global(p) {
        margin: 0 0 0.5rem 0;
    }

    .info-box-content :global(p:last-child) {
        margin-bottom: 0;
    }
</style>
