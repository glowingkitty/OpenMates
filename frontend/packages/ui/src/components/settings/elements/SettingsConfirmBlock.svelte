<!--
    SettingsConfirmBlock — Destructive action confirmation block with warning + toggle.

    Replaces custom `.delete-confirmation`, `.confirmation-section`, `.warning-box`
    patterns across settings pages with a single canonical component combining
    a warning message box and a consent toggle.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    import Toggle from '../../Toggle.svelte';

    /** Confirmation block severity variant */
    type ConfirmVariant = 'danger' | 'warning';

    let {
        warningText,
        confirmLabel,
        checked = $bindable(false),
        variant = 'danger' as ConfirmVariant,
        onChange = undefined,
    }: {
        warningText: string;
        confirmLabel: string;
        checked?: boolean;
        variant?: ConfirmVariant;
        onChange?: ((checked: boolean) => void) | undefined;
    } = $props();

    function handleToggleClick() {
        checked = !checked;
        onChange?.(checked);
    }

    function handleKeydown(event: KeyboardEvent) {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            handleToggleClick();
        }
    }
</script>

<div class="settings-confirm-block">
    <div class="warning-box {variant}">
        <span class="clickable-icon icon_warning warning-icon"></span>
        <span class="warning-text">{warningText}</span>
    </div>

    <div
        class="toggle-row"
        onclick={handleToggleClick}
        onkeydown={handleKeydown}
        role="checkbox"
        aria-checked={checked}
        aria-label={confirmLabel}
        tabindex="0"
    >
        <Toggle {checked} ariaLabel={confirmLabel} />
        <span class="toggle-label">{confirmLabel}</span>
    </div>
</div>

<style>
    .settings-confirm-block {
        padding: 0 0.625rem;
        display: flex;
        flex-direction: column;
        gap: 0.75rem;
    }

    .warning-box {
        display: flex;
        gap: 0.75rem;
        padding: 1rem;
        border-radius: 0.75rem;
    }

    .warning-box.danger {
        background: color-mix(in srgb, var(--color-error) 6%, transparent);
        border: 0.0625rem solid color-mix(in srgb, var(--color-error) 30%, transparent);
    }

    .warning-box.warning {
        background: color-mix(in srgb, var(--color-warning) 6%, transparent);
        border: 0.0625rem solid color-mix(in srgb, var(--color-warning) 30%, transparent);
    }

    .warning-icon {
        width: 1.5rem;
        height: 1.5rem;
        flex-shrink: 0;
    }

    .warning-box.danger .warning-icon {
        background-color: var(--color-error);
    }

    .warning-box.warning .warning-icon {
        background-color: var(--color-warning-dark, #856404);
    }

    .warning-text {
        font-size: var(--font-size-p, 0.875rem);
        color: var(--color-font-primary);
        line-height: 1.4;
    }

    .toggle-row {
        display: flex;
        gap: 0.75rem;
        align-items: center;
        cursor: pointer;
        padding: 0.5rem;
    }

    .toggle-row:focus-visible {
        outline: 0.125rem solid var(--color-primary-start);
        outline-offset: 0.125rem;
        border-radius: 0.5rem;
    }

    .toggle-label {
        font-size: var(--font-size-p, 0.875rem);
        color: var(--color-font-secondary);
    }
</style>
