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

    let {
        type = 'submenu',
        icon = '',
        title,
        subtitleTop = '',
        hasToggle = false,
        checked = false,
        disabled = false,
        onClick = undefined,
        'data-testid': testid = undefined,
    }: {
        type?: string;
        icon?: string;
        title: string;
        subtitleTop?: string;
        hasToggle?: boolean;
        checked?: boolean;
        disabled?: boolean;
        onClick?: (() => void) | undefined;
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
</script>

{#snippet itemContent()}
    {#if icon}
        <span class="item-icon clickable-icon {icon}"></span>
    {/if}
    <div class="item-text">
        <span class="item-title">{title}</span>
        {#if subtitleTop}
            <span class="item-subtitle">{subtitleTop}</span>
        {/if}
    </div>
    {#if hasToggle}
        <div class="item-toggle">
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
        pointer-events: none;
    }
</style>
