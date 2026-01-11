<script lang="ts">
    import Toggle from './Toggle.svelte';
    import ModifyButton from './buttons/ModifyButton.svelte';
    import Icon from './Icon.svelte';
    import { text } from '@repo/ui';

    // Props using Svelte 5 runes
    let { 
        icon,
        type = 'heading',
        title = undefined,
        subtitleTop = undefined,
        subtitle = undefined,
        subtitleBottom = undefined,
        showCredits = false,
        creditAmount = undefined,
        creditCurrency = undefined,
        appIcons = undefined,
        maxVisibleIcons = 3,
        hasToggle = false,
        hasModifyButton = false,
        checked = false,
        disabled = false,
        onClick = undefined,
        hasNestedItems = false,
        iconType = 'default',
        children
    }: {
        icon: string;
        type?: 'heading' | 'submenu' | 'quickaction' | 'subsubmenu' | 'nested';
        title?: string | undefined;
        subtitleTop?: string;
        subtitle?: string;
        subtitleBottom?: string;
        showCredits?: boolean;
        creditAmount?: number | undefined;
        creditCurrency?: string;
        appIcons?: Array<{ name: string, type?: 'app' | 'provider' }>;
        maxVisibleIcons?: number;
        hasToggle?: boolean;
        hasModifyButton?: boolean;
        checked?: boolean;
        disabled?: boolean;
        onClick?: (() => void) | undefined;
        hasNestedItems?: boolean;
        iconType?: 'default' | 'app';
        children?: any;
    } = $props();

    // Backward-compat: `subtitle` is an alias for `subtitleTop`, without mutating props.
    let displaySubtitleTop = $derived(subtitleTop ?? subtitle);

    // Computed values
    let isClickable = $derived(onClick !== undefined);
    let isSubmenuWithoutModify = $derived(type === 'submenu' && !hasModifyButton);
    let hasAnySubtitle = $derived(displaySubtitleTop || subtitleBottom);
    let iconClass = $derived(type === 'quickaction' || type === 'subsubmenu' ? 
        `icon settings_size subsetting_icon ${icon}` : `icon settings_size ${icon}`);

    // Handle events
    function handleItemClick(event) {
        // Prevent event bubbling to avoid closing parent menus
        event.stopPropagation();
        
        if (!disabled && isClickable && onClick) {
            onClick();
        }
    }

    function handleToggleClick(event) {
        // Prevent event bubbling to avoid closing parent menus
        event.stopPropagation();
        
        if (!disabled) {
            // Don't mutate the checked prop directly - let the parent control it
            // Just trigger the onClick callback which will update the parent's state
            if (isClickable && onClick) {
                onClick();
            }
        }
    }

    function handleModifyClick(event) {
        // Prevent event bubbling to avoid closing parent menus
        event.stopPropagation();
        
        // Handle modify button click
        console.log('Modify button clicked');
    }

    function handleKeydown(event: KeyboardEvent, handler: () => void) {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            event.stopPropagation();
            handler();
        }
    }
</script>


<!--
    SettingsItem Component
    
    This component renders a menu item with various configurations:
    - Can be clickable or non-clickable
    - Can have toggle switches
    - Can have modify buttons
    - Can display app icons
    - Can show credits
    - Supports nested content
    
    Accessibility considerations:
    - if settingsitem has a toggle, do not forward the click on the toggle to the settingsitem click handler but to the toggle click handler
    - if settingsitem has a toggle and no settingsitem click handler, forward the click to the toggle and toggle click handler

-->

{#if isClickable}
<div 
    class="menu-item"
    class:clickable={isClickable}
    class:disabled={disabled}
    class:heading={type === 'heading'}
    class:submenu={type === 'submenu'}
    class:quickaction={type === 'quickaction'}
    class:subsubmenu={type === 'subsubmenu'}
    class:nested={type === 'nested'}
    class:has-nested-items={hasNestedItems}
    onclick={handleItemClick}
    onkeydown={(e) => !disabled && handleKeydown(e, () => handleItemClick(e))}
    role="menuitem"
    tabindex={disabled ? -1 : 0}
>
    <div class="menu-item-content">
        <div class="menu-item-left">
            <!-- Main icon - width and size preserved -->
            <!-- Use Icon component with type="app" for app icons to render proper app-style icon -->
            {#if iconType === 'app'}
                <div class="app-icon-wrapper">
                    <Icon 
                        name={icon}
                        type="app"
                        size="38px"
                        className="app-icon-main no-fade"
                        borderColor="#ffffff"
                    />
                </div>
            {:else}
                <div class="icon-container">
                    <div class={iconClass}>
                    </div>
                </div>
            {/if}
            
                <div class="text-and-nested-container">
                    <div class="text-container" class:has-title={!!title} class:has-subtitle={hasAnySubtitle} class:heading-text={type === 'heading'}>
                    <!-- Top subtitle if present -->
                    {#if displaySubtitleTop}
                        <div class="menu-subtitle-top">{displaySubtitleTop}</div>
                    {/if}
                    
                    <!-- Main title -->
                    {#if title}
                        <div class="menu-title">
                            {#if type === 'heading'}
                                <strong>{title}</strong>
                            {:else}
                                {title}
                            {/if}
                        </div>
                    {/if}
                    
                    <!-- Bottom subtitle if present -->
                    {#if subtitleBottom}
                        <div class="menu-subtitle-bottom">{subtitleBottom}</div>
                    {/if}
                    
                    <!-- Credits display if enabled -->
                    {#if showCredits && creditAmount !== undefined}
                        <div class="menu-credits">
                            {creditAmount} {creditCurrency || 'credits'}
                        </div>
                    {/if}
                </div>
                
                <!-- Nested content if present -->
                {#if hasNestedItems && children}
                    <div class="nested-content">
                        {@render children()}
                    </div>
                {/if}
            </div>
        </div>
        
        <div class="menu-item-right">
            <!-- App icons if present -->
            {#if appIcons && appIcons.length > 0}
                <div class="app-icons-container">
                    {#each appIcons.slice(0, maxVisibleIcons || 3) as appIcon}
                        <div class="app-icon" class:app={appIcon.type === 'app'} class:provider={appIcon.type === 'provider'}>
                            {appIcon.name}
                        </div>
                    {/each}
                    {#if appIcons.length > (maxVisibleIcons || 3)}
                        <div class="app-icon more">+{appIcons.length - (maxVisibleIcons || 3)}</div>
                    {/if}
                </div>
            {/if}
            
            <!-- Toggle if present -->
            {#if hasToggle}
                <div 
                    onclick={handleToggleClick}
                    onkeydown={(e) => handleKeydown(e, () => handleToggleClick(e))}
                    role="button" 
                    tabindex="0"
                    class="toggle-container"
                >
                    <Toggle 
                        bind:checked
                        name={title || displaySubtitleTop?.toLowerCase?.() || ''}
                        ariaLabel={`Toggle ${(title || displaySubtitleTop || '').toLowerCase()} mode`}
                        disabled={disabled}
                    />
                </div>
            {/if}
            
            <!-- Modify button if enabled -->
            {#if hasModifyButton || type === 'subsubmenu'}
                <ModifyButton />
            {/if}
        </div>
    </div>
</div>
{:else}
<div 
    class="menu-item"
    class:clickable={isClickable}
    class:disabled={disabled}
    class:heading={type === 'heading'}
    class:submenu={type === 'submenu'}
    class:quickaction={type === 'quickaction'}
    class:subsubmenu={type === 'subsubmenu'}
    class:nested={type === 'nested'}
    class:has-nested-items={hasNestedItems}
    role="presentation"
>
    <div class="menu-item-content">
        <div class="menu-item-left">
            <!-- Main icon - width and size preserved -->
            <!-- Use Icon component with type="app" for app icons to render proper app-style icon -->
            {#if iconType === 'app'}
                <div class="app-icon-wrapper">
                    <Icon 
                        name={icon}
                        type="app"
                        size="38px"
                        className="app-icon-main no-fade"
                        borderColor="#ffffff"
                    />
                </div>
            {:else}
                <div class="icon-container">
                    <div class={iconClass}>
                    </div>
                </div>
            {/if}
            
            <div class="text-and-nested-container">
                <div class="text-container" class:has-title={!!title} class:has-subtitle={hasAnySubtitle} class:heading-text={type === 'heading'}>
                    <!-- Top subtitle if present -->
                    {#if subtitleTop}
                        <div class="menu-subtitle-top">{subtitleTop}</div>
                    {/if}
                    
                    <!-- Main title -->
                    {#if title}
                        <div class="menu-title">
                            {#if type === 'heading'}
                                <strong>{title}</strong>
                            {:else}
                                {title}
                            {/if}
                        </div>
                    {/if}
                    
                    <!-- Bottom subtitle if present -->
                    {#if subtitleBottom}
                        <div class="menu-subtitle-bottom">{subtitleBottom}</div>
                    {/if}
                    
                    <!-- Credits display if enabled -->
                    {#if showCredits && creditAmount !== undefined}
                        <div class="menu-credits">
                            {creditAmount} {creditCurrency || 'credits'}
                        </div>
                    {/if}
                </div>
                
                <!-- Nested content if present -->
                {#if hasNestedItems && children}
                    <div class="nested-content">
                        {@render children()}
                    </div>
                {/if}
            </div>
        </div>
        
        <div class="menu-item-right">
            <!-- App icons if present -->
            {#if appIcons && appIcons.length > 0}
                <div class="app-icons-container">
                    {#each appIcons.slice(0, maxVisibleIcons || 3) as appIcon}
                        <div class="app-icon" class:app={appIcon.type === 'app'} class:provider={appIcon.type === 'provider'}>
                            {appIcon.name}
                        </div>
                    {/each}
                    {#if appIcons.length > (maxVisibleIcons || 3)}
                        <div class="app-icon more">+{appIcons.length - (maxVisibleIcons || 3)}</div>
                    {/if}
                </div>
            {/if}
            
            <!-- Toggle if present -->
            {#if hasToggle}
                <div 
                    onclick={handleToggleClick}
                    onkeydown={(e) => handleKeydown(e, () => handleToggleClick(e))}
                    role="button" 
                    tabindex="0"
                    class="toggle-container"
                >
                    <Toggle 
                        bind:checked
                        name={title || subtitleTop.toLowerCase()}
                        ariaLabel={`Toggle ${(title || subtitleTop).toLowerCase()} mode`}
                        disabled={disabled}
                    />
                </div>
            {/if}
            
            <!-- Modify button if enabled -->
            {#if hasModifyButton || type === 'subsubmenu'}
                <ModifyButton />
            {/if}
        </div>
    </div>
</div>
{/if}

<style>
    .menu-item {
        display: flex;
        flex-direction: column;
        padding: 5px 10px;
        border-radius: 8px;
        transition: background-color 0.2s ease;
        cursor: default;
        position: relative;
    }

    .menu-item.clickable {
        cursor: pointer;
    }

    .menu-item.clickable:hover {
        background-color: var(--color-grey-10);
    }

    .menu-item.disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .menu-item-content {
        display: flex;
        align-items: center;
        justify-content: space-between;
        width: 100%;
        min-height: 40px;
    }

    .menu-item-left {
        display: flex;
        align-items: center;
        flex: 1;
        min-width: 0;
    }

    .icon-container {
        width: 44px;
        height: 44px;
        margin-right: 12px;
        flex-shrink: 0;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    /* App icon wrapper for displaying app icons using the Icon component */
    .app-icon-wrapper {
        width: 44px;
        height: 44px;
        margin-right: 12px;
        flex-shrink: 0;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .text-and-nested-container {
        display: flex;
        flex-direction: column;
        flex: 1;
        min-width: 0;
    }

    .text-container {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }

    .text-container.has-title {
        gap: 4px;
    }

    .text-container.has-subtitle {
        gap: 2px;
    }

    .menu-title {
        font-size: 16px;
        color: var(--color-grey-100);
        text-align: left;
        display: -webkit-box;
        -webkit-line-clamp: 3;
        line-clamp: 3;
        -webkit-box-orient: vertical;
        overflow: hidden;
        font-weight: 500;
    }

    .heading .menu-title strong {
        font-weight: 600;
    }

    .menu-subtitle-top,
    .menu-subtitle-bottom {
        font-size: 14px;
        color: var(--color-grey-60);
        text-align: left;
    }

    .menu-credits {
        font-size: 12px;
        color: var(--color-grey-50);
        font-weight: 500;
    }

    .nested-content {
        margin-top: 8px;
        padding-left: 36px;
    }

    .menu-item-right {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-shrink: 0;
    }

    .app-icons-container {
        display: flex;
        gap: 4px;
        align-items: center;
    }

    .app-icon {
        width: 20px;
        height: 20px;
        border-radius: 4px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 10px;
        font-weight: 500;
        color: white;
        background-color: var(--color-grey-40);
    }

    .app-icon.app {
        background-color: var(--color-primary);
    }

    .app-icon.provider {
        background-color: var(--color-secondary);
    }

    .app-icon.more {
        background-color: var(--color-grey-50);
    }

    .toggle-container {
        display: flex;
        align-items: center;
        cursor: pointer;
        padding: 4px;
        border-radius: 4px;
        transition: background-color 0.2s ease;
    }

    .toggle-container:hover {
        background-color: var(--color-grey-10);
    }

    .toggle-container:focus {
        outline: 2px solid var(--color-primary);
        outline-offset: 2px;
    }

    /* Responsive adjustments */
    @media (max-width: 600px) {
        .menu-item {
            padding: 4px 10px;
        }
    }
</style>
