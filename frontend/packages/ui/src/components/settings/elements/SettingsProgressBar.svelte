<!--
    SettingsProgressBar — Progress indicator bar for settings pages.

    Replaces custom `.progress-bar`, `.progress-fill` patterns across
    Storage and Export pages with a single canonical component supporting
    default, warning, and success variants.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    /** Progress bar color variant */
    type ProgressVariant = 'default' | 'warning' | 'success';

    let {
        value,
        variant = 'default' as ProgressVariant,
        label = '',
        showPercent = false,
    }: {
        value: number;
        variant?: ProgressVariant;
        label?: string;
        showPercent?: boolean;
    } = $props();

    /** Clamp value to 0–100 range */
    let clampedValue = $derived(Math.min(100, Math.max(0, value)));
</script>

<div class="settings-progress-bar">
    {#if label || showPercent}
        <div class="progress-label-row">
            {#if label}
                <span class="progress-label">{label}</span>
            {/if}
            {#if showPercent}
                <span class="progress-percent">{Math.round(clampedValue)}%</span>
            {/if}
        </div>
    {/if}
    <div
        class="progress-track"
        role="progressbar"
        aria-valuenow={clampedValue}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label || 'Progress'}
    >
        <div
            class="progress-fill {variant}"
            style:width="{clampedValue}%"
        ></div>
    </div>
</div>

<style>
    .settings-progress-bar {
        padding: 0 0.625rem;
    }

    .progress-label-row {
        display: flex;
        justify-content: space-between;
        margin-bottom: 0.5rem;
    }

    .progress-label {
        font-size: var(--processing-details-font-size, 0.8125rem);
        font-weight: 600;
        color: var(--color-font-primary);
    }

    .progress-percent {
        font-size: var(--processing-details-font-size, 0.8125rem);
        color: var(--color-font-secondary);
    }

    .progress-track {
        height: 0.5rem;
        background: var(--color-grey-20);
        border-radius: 0.25rem;
        overflow: hidden;
    }

    .progress-fill {
        height: 100%;
        border-radius: 0.25rem;
        transition: width var(--duration-slow) var(--easing-default);
    }

    .progress-fill.default {
        background: var(--color-primary);
    }

    .progress-fill.warning {
        background: var(--color-warning);
    }

    .progress-fill.success {
        background: var(--color-success);
    }
</style>
