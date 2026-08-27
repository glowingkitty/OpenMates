<!--
    SettingsItem — Generic menu row for settings pages.

    Handles common row types (submenu, action, etc.) with optional icon,
    title, subtitle, and toggle. Used for per-category opt-in toggles in
    the newsletter settings and any other toggle-row use case.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    import Toggle from '../../Toggle.svelte';
    import type { AiCapabilityLevel } from '../../../utils/aiModelDisplay';
    import SettingsCapabilityScale from './SettingsCapabilityScale.svelte';

    let {
        type = 'submenu',
        icon = '',
        iconSrc = '',
        iconAlt = '',
        title,
        subtitleTop = '',
        subtitleBottom = '',
        hasToggle = false,
        checked = false,
        disabled = false,
        capability = undefined,
        capabilityLabel = '',
        onClick = undefined,
        onToggleClick = undefined,
        'data-testid': testid = undefined,
    }: {
        type?: string;
        icon?: string;
        iconSrc?: string;
        iconAlt?: string;
        title: string;
        subtitleTop?: string;
        subtitleBottom?: string;
        hasToggle?: boolean;
        checked?: boolean;
        disabled?: boolean;
        capability?: AiCapabilityLevel | undefined;
        capabilityLabel?: string;
        onClick?: (() => void) | undefined;
        onToggleClick?: (() => void) | undefined;
        'data-testid'?: string | undefined;
    } = $props();

    function handleClick() {
        if (!disabled) onClick?.();
    }

    function handleKeydown(event: KeyboardEvent) {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            handleClick();
        }
    }

    function handleToggleClick(event: Event) {
        event.preventDefault();
        event.stopPropagation();
        if (!disabled) (onToggleClick ?? onClick)?.();
    }

    function handleToggleKeydown(event: KeyboardEvent) {
        if (event.key === 'Enter' || event.key === ' ') {
            handleToggleClick(event);
        }
    }

    let itemIconClass = $derived(
        icon.includes('subsetting_icon')
            ? `item-icon ${icon}`
            : `item-icon icon settings_size ${icon}`
    );
</script>

{#snippet itemContent()}
    {#if capability && capabilityLabel}
        <SettingsCapabilityScale level={capability} label={capabilityLabel} compact={true} />
    {:else if iconSrc}
        <span class="item-image"><img src={iconSrc} alt={iconAlt} /></span>
    {:else if icon}
        <span class={itemIconClass}></span>
    {/if}
    <div class="item-text">
        <span class="item-title">{title}</span>
        {#if subtitleTop}
            <span class="item-subtitle">{subtitleTop}</span>
        {/if}
        {#if subtitleBottom}
            <span class="item-subtitle">{subtitleBottom}</span>
        {/if}
    </div>
    {#if hasToggle}
        <div
            class="item-toggle"
            role="button"
            tabindex={disabled ? -1 : 0}
            onclick={handleToggleClick}
            onkeydown={handleToggleKeydown}
            data-testid={testid ? `${testid}-toggle` : undefined}
        >
            <Toggle {checked} {disabled} ariaLabel={title} />
        </div>
    {/if}
{/snippet}

{#if onClick}
<div
    class="settings-item settings-item--{type} clickable"
    class:disabled
    onclick={handleClick}
    onkeydown={handleKeydown}
    role="button"
    tabindex={disabled ? -1 : 0}
    data-testid={testid}
    aria-disabled={disabled || undefined}
>
    {@render itemContent()}
</div>
{:else}
<div
    class="settings-item settings-item--{type}"
    class:disabled
    data-testid={testid}
>
    {@render itemContent()}
</div>
{/if}

<style>
    .settings-item {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 0.75rem 0.625rem;
        border-radius: 0.5rem;
        transition: background-color var(--duration-normal, 150ms) var(--easing-default, ease);
    }

    .settings-item.clickable {
        cursor: pointer;
    }

    .settings-item.clickable:hover:not(.disabled) {
        background-color: var(--color-grey-10);
    }

    .settings-item.clickable:focus-visible {
        outline: 0.125rem solid var(--color-primary-start);
        outline-offset: 0.125rem;
    }

    .settings-item.disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .item-icon {
        width: 2rem;
        height: 2rem;
        min-width: 2rem;
        flex-shrink: 0;
    }

    .item-image {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 2rem;
        height: 2rem;
        min-width: 2rem;
        padding: 0.25rem;
        overflow: hidden;
        background: var(--color-grey-10);
        border-radius: var(--radius-3);
        box-sizing: border-box;
    }

    .item-image img {
        width: 100%;
        height: 100%;
        object-fit: contain;
    }

    .item-text {
        display: flex;
        flex-direction: column;
        gap: 0.125rem;
        flex: 1;
        min-width: 0;
    }

    .item-title {
        font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: var(--font-size-p, 0.875rem);
        font-weight: 500;
        color: var(--color-font-primary);
        line-height: 1.3;
    }

    .item-subtitle {
        font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-size: var(--font-size-small, 0.75rem);
        color: var(--color-font-secondary);
        line-height: 1.3;
    }

    .item-toggle {
        flex-shrink: 0;
    }

    .item-toggle :global(.toggle) { pointer-events: none; }

    .settings-item--ai-row,
    .settings-item--ai-price-row {
        min-height: 2.73125rem;
        gap: 0.8125rem;
        padding: 0 var(--spacing-10);
        border-radius: 0.559rem;
    }

    .settings-item--ai-row .item-image,
    .settings-item--ai-row .item-icon,
    .settings-item--ai-price-row .item-image,
    .settings-item--ai-price-row .item-icon {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 2.73125rem;
        height: 2.73125rem;
        min-width: 2.73125rem;
        padding: 0.5625rem;
        border-radius: 0.559rem;
        background: linear-gradient(135deg, var(--color-ai-icon-tile-start, var(--color-grey-10)) 9.04%, var(--color-ai-icon-tile-end, var(--color-grey-20)) 90.06%);
        box-shadow: 0.063rem 0.063rem 0.127rem rgba(0, 0, 0, 0.25);
        box-sizing: border-box;
    }

    .settings-item--ai-row .item-icon,
    .settings-item--ai-price-row .item-icon {
        --icon-color: var(--color-primary-start);
    }

    .settings-item--ai-row .item-image img,
    .settings-item--ai-price-row .item-image img {
        width: 100%;
        height: 100%;
    }

    .settings-item--ai-row .item-text,
    .settings-item--ai-price-row .item-text {
        gap: 0;
    }

    .settings-item--ai-row .item-title {
        color: transparent;
        background: var(--icon-focus-background, var(--color-primary));
        -webkit-background-clip: text;
        background-clip: text;
        font-size: var(--font-size-p);
        font-weight: 700;
        line-height: 1.25;
    }

    .settings-item--ai-row .item-subtitle,
    .settings-item--ai-price-row .item-title {
        color: var(--color-ai-settings-muted, var(--color-font-secondary));
        font-size: var(--font-size-small);
        font-weight: 700;
        line-height: 1.25;
    }

    .settings-item--ai-price-row .item-subtitle {
        color: var(--color-font-primary);
        font-size: var(--font-size-p);
        font-weight: 500;
        line-height: 1.25;
    }

    .settings-item--ai-row .item-toggle :global(.toggle),
    .settings-item--ai-price-row .item-toggle :global(.toggle) {
        width: 3.0625rem;
        min-width: 3.0625rem;
        height: 1.8125rem;
    }

    .settings-item--ai-row .item-toggle :global(.toggle .slider:before),
    .settings-item--ai-price-row .item-toggle :global(.toggle .slider:before) {
        width: 1.5625rem;
        height: 1.5625rem;
        left: 0.125rem;
        bottom: 0.125rem;
    }

    .settings-item--ai-row .item-toggle :global(.toggle input:checked + .slider:before),
    .settings-item--ai-row .item-toggle :global(.toggle .presentation-input.checked + .slider:before),
    .settings-item--ai-price-row .item-toggle :global(.toggle input:checked + .slider:before),
    .settings-item--ai-price-row .item-toggle :global(.toggle .presentation-input.checked + .slider:before) {
        transform: translateX(1.25rem);
    }

    .settings-item--ai-example-card {
        min-height: 9.9375rem;
        margin: 0 var(--spacing-10);
        padding: var(--spacing-8) var(--spacing-10);
        flex-direction: column;
        justify-content: center;
        gap: var(--spacing-5);
        border-radius: 1.4375rem;
        background: var(--color-app-web, var(--color-primary));
        box-shadow: 0 0.25rem 0.25rem rgba(0, 0, 0, 0.25);
        text-align: center;
    }

    .settings-item--ai-example-card .item-icon {
        width: 1.625rem;
        height: 1.625rem;
        min-width: 1.625rem;
        --icon-color: var(--color-font-button);
    }

    .settings-item--ai-example-card .item-text {
        align-items: center;
        gap: var(--spacing-3);
    }

    .settings-item--ai-example-card .item-title {
        color: var(--color-font-button);
        font-size: var(--font-size-p);
        font-weight: 700;
        line-height: 1.25;
    }

    .settings-item--ai-example-card .item-subtitle {
        max-width: 13.0625rem;
        color: rgba(255, 255, 255, 0.85);
        font-size: 0.75rem;
        font-weight: 700;
        line-height: 1.25;
        text-align: center;
    }
</style>
