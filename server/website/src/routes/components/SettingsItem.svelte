<script lang="ts">
    import Toggle from './Toggle.svelte';

    // Props for the component
    export let icon: string; // CSS class for the icon
    export let title: string;
    export let hasToggle = false; // Whether this item has a toggle switch
    export let checked = false; // Toggle state if hasToggle is true
    export let onClick: (() => void) | undefined = undefined;

    // Check if this is a logout item
    const isLogout = title.toLowerCase() === 'logout';

    // Handler to prevent event bubbling for toggle clicks
    function handleToggleClick(event: Event): void {
        event.stopPropagation();
    }

    // Keyboard handler for accessibility
    function handleKeydown(event: KeyboardEvent, action: (event: Event) => void): void {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            action(event);
        }
    }
</script>

<div 
    class="menu-item"
    class:clickable={onClick !== undefined}
    on:click={onClick}
    on:keydown={(e) => onClick && handleKeydown(e, onClick)}
    role="menuitem"
    tabindex={onClick ? 0 : undefined}
>
    <div class="menu-item-left">
        <div class="{isLogout ? 'clickable-icon icon_logout' : 'icon settings_size'} {icon}"></div>
        <span class="menu-title"><mark>{title}</mark></span>
    </div>
    {#if hasToggle}
        <div 
            on:click={handleToggleClick}
            on:keydown={(e) => handleKeydown(e, handleToggleClick)}
            role="button" 
            tabindex="0"
        >
            <Toggle 
                bind:checked
                name={title.toLowerCase()}
                ariaLabel="Toggle {title.toLowerCase()} mode"
            />
        </div>
    {/if}
</div>

<style>
    .menu-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 8px 10px;
        border-radius: 12px;
        transition: background-color 0.2s ease;
        user-select: none;
        -webkit-user-select: none;
        -moz-user-select: none;
        -ms-user-select: none;
    }

    .clickable {
        cursor: pointer;
    }

    .clickable:hover {
        background-color: var(--color-grey-30);
    }


    .menu-item-left {
        display: flex;
        align-items: center;
        gap: 12px;
    }

    .menu-title {
        text-align: left;
    }
</style> 