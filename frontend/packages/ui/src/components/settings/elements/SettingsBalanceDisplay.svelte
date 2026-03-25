<!--
    SettingsBalanceDisplay — Hero-style amount/balance display for settings pages.

    Replaces custom `.balance-display`, `.balance-amount`, `.balance-label`,
    `.coin-icon` patterns across billing pages with a single canonical component
    for displaying formatted amounts with optional icon and label.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    let {
        amount,
        label = '',
        icon = '',
        iconColor = '',
    }: {
        amount: string;
        label?: string;
        icon?: string;
        iconColor?: string;
    } = $props();
</script>

<div class="settings-balance-display">
    <div class="balance-row">
        {#if icon}
            <span
                class="balance-icon clickable-icon {icon}"
                style:background-color={iconColor || undefined}
            ></span>
        {/if}
        <span class="balance-amount">{amount}</span>
    </div>
    {#if label}
        <span class="balance-label">{label}</span>
    {/if}
</div>

<style>
    .settings-balance-display {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 0.25rem;
        padding: 1.25rem;
        background: var(--color-grey-10);
        border-radius: 0.75rem;
        margin: 0 0.625rem;
    }

    .balance-row {
        display: flex;
        align-items: center;
        gap: 0.625rem;
    }

    .balance-icon {
        width: 1.75rem;
        height: 1.75rem;
        flex-shrink: 0;
        background-color: var(--color-primary-start);
    }

    .balance-amount {
        font-size: 1.75rem;
        font-weight: 600;
        color: var(--color-font-primary);
    }

    .balance-label {
        font-size: var(--font-size-p, 0.875rem);
        color: var(--color-font-secondary);
        margin-top: 0.25rem;
    }
</style>
