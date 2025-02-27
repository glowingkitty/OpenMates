<script lang="ts">
    import Toggle from './Toggle.svelte';
    import ModifyButton from './buttons/ModifyButton.svelte';

    // Props for the component
    export let icon: string; // CSS class for the icon
    export let title: string;
    export let subtitle: string = ""; // Optional subtitle for subsubmenu items
    export let type: 'heading' | 'submenu' | 'quickaction' | 'subsubmenu' = 'submenu'; // Type of settings item
    export let hasToggle = false; // Whether this item has a toggle switch
    export let checked = false; // Toggle state if hasToggle is true
    export let disabled = false; // Whether this item is disabled
    export let onClick: (() => void) | undefined = undefined;

    // Handler to prevent event bubbling for toggle clicks
    function handleToggleClick(event: Event): void {
        event.stopPropagation();
    }

    // Handler for modify button click
    function handleModifyClick(event: Event): void {
        event.stopPropagation();
        if (onClick) onClick();
    }

    // Keyboard handler for accessibility
    function handleKeydown(event: KeyboardEvent, action: (event: Event) => void): void {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            action(event);
        }
    }

    // Determine if the item is clickable
    $: isClickable = onClick !== undefined;
    
    // Determine the icon class based on item type - fix for heading icons
    $: iconClass = type === 'quickaction' || type === 'subsubmenu' 
        ? `icon settings_size subsetting_icon ${icon}` 
        : `icon settings_size ${icon}`;
</script>

<div 
    class="menu-item"
    class:clickable={isClickable}
    class:disabled={disabled}
    class:heading={type === 'heading'}
    class:submenu={type === 'submenu'}
    class:quickaction={type === 'quickaction'}
    class:subsubmenu={type === 'subsubmenu'}
    on:click={disabled || !isClickable ? () => {} : onClick}
    on:keydown={(e) => !disabled && isClickable && onClick && handleKeydown(e, onClick)}
    role={isClickable ? "menuitem" : "menuitemtext"}
    tabindex={disabled ? -1 : (isClickable ? 0 : undefined)}
>
    <div class="menu-item-content">
        <div class="menu-item-left">
            <!-- Fixed icon implementation to work consistently across all types -->
            <div class={iconClass}></div>
            
            <div class="text-container">
                {#if subtitle}
                    <div class="subtitle">{subtitle}</div>
                {/if}
                <span class="menu-title">
                    {#if type === 'heading'}
                        <strong>{title}</strong>
                    {:else if type === 'submenu'}
                        <mark>{title}</mark>
                    {:else}
                        {title}
                    {/if}
                </span>
            </div>
        </div>
        
        <!-- Right side controls based on item type -->
        {#if hasToggle && (type === 'quickaction' || type === 'submenu')}
            <div 
                on:click={handleToggleClick}
                on:keydown={(e) => handleKeydown(e, handleToggleClick)}
                role="button" 
                tabindex="0"
                class="toggle-container"
            >
                <Toggle 
                    bind:checked
                    name={title.toLowerCase()}
                    ariaLabel="Toggle {title.toLowerCase()} mode"
                    disabled={disabled}
                />
            </div>
        {/if}
        
        {#if type === 'subsubmenu'}
            <ModifyButton 
                on:click={handleModifyClick}
                on:keydown={(e) => handleKeydown(e, handleModifyClick)}
            />
        {/if}
    </div>
</div>

<style>
    .menu-item {
        display: flex;
        flex-direction: column;
        padding: 5px 10px;
        border-radius: 12px;
        transition: background-color 0.2s ease;
    }

    .menu-item-content {
        display: flex;
        justify-content: space-between;
        align-items: center;
        width: 100%;
    }

    .clickable {
        cursor: pointer;
    }

    .clickable:hover {
        background-color: var(--color-grey-30);
    }

    .menu-item.disabled {
        opacity: 0.5;
        cursor: default;
        pointer-events: none;
    }

    .menu-item-left {
        display: flex;
        align-items: center;
        gap: 12px;
    }
    
    .text-container {
        display: flex;
        flex-direction: column;
        justify-content: center;
    }

    .subtitle {
        font-size: 14px;
        color: var(--color-grey-60);
        margin-bottom: 2px;
    }

    .menu-title {
        text-align: left;
    }
    
    .menu-title mark {
        font-weight: 600;
    }
    
    .heading .menu-title strong {
        font-weight: 700;
    }
    
    .modify-button {
        width: 30px;
        height: 30px;
        border-radius: 15px;
        background-color: var(--color-grey-30);
        display: flex;
        align-items: center;
        justify-content: center;
        border: none;
        cursor: pointer;
        transition: background-color 0.2s ease;
    }
    
    .modify-button:hover {
        background-color: var(--color-grey-40);
    }
    
    .modify-button .clickable-icon {
        width: 13px;
        height: 13px;
    }
    
    .toggle-container {
        display: flex;
        align-items: center;
    }
</style>