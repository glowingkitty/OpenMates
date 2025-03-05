<script lang="ts">
    import { onMount, onDestroy, createEventDispatcher } from 'svelte';
    import Toggle from './Toggle.svelte';
    import ModifyButton from './buttons/ModifyButton.svelte';
    import { _ } from 'svelte-i18n';

    const dispatch = createEventDispatcher();

    // Core properties
    export let icon: string; // Icon name (mandatory)
    export let type: 'heading' | 'submenu' | 'quickaction' | 'subsubmenu' | 'nested' = 'submenu';

    // Text properties
    export let title: string | undefined = undefined; // Main title (optional)
    export let subtitleTop: string = ""; // Text above the title (optional)
    export let subtitle: string = ""; // For backward compatibility, maps to subtitleTop
    export let subtitleBottom: string = ""; // Text below the title (optional)
    
    // Credits display
    export let showCredits: boolean = false;
    export let creditAmount: number | undefined = undefined;
    export let creditCurrency: string = "";

    // App/Provider icons
    export let appIcons: Array<{ name: string, type?: 'app' | 'provider' }> = [];
    export let maxVisibleIcons: number = 4; // Maximum number of icons to show before using a "+" indicator

    // Interactive properties
    export let hasToggle: boolean = false;
    export let hasModifyButton: boolean = false;
    export let checked: boolean = false;
    export let disabled: boolean = false;
    export let onClick: (() => void) | undefined = undefined;
    
    // Nested content
    export let hasNestedItems: boolean = false;

    // For backward compatibility
    $: if (subtitle && !subtitleTop) {
        subtitleTop = subtitle;
    }

    // Translation handling
    $: translatedTitle = title?.startsWith('settings.') ? 
        $_(`${title}.text`, { default: title }) : title;
    $: translatedSubtitleTop = subtitleTop?.startsWith('settings.') ? 
        $_(`${subtitleTop}.text`, { default: subtitleTop }) : subtitleTop;
    $: translatedSubtitleBottom = subtitleBottom?.startsWith('settings.') ? 
        $_(`${subtitleBottom}.text`, { default: subtitleBottom }) : subtitleBottom;
    $: translatedCredits = showCredits && creditAmount !== undefined ? 
        $_('signup.amount_currency.text', { values: { amount: creditAmount, currency: creditCurrency } }) : "";

    // Derived properties
    $: isClickable = onClick !== undefined;
    $: isSubmenuWithoutModify = type === 'submenu' && !hasModifyButton;
    $: hasAnySubtitle = subtitleTop || subtitleBottom;
    $: iconClass = type === 'quickaction' || type === 'subsubmenu' ? 
        `icon settings_size subsetting_icon ${icon}` : `icon settings_size ${icon}`;

    // Handle events
    function handleToggleClick(event: Event): void {
        event.stopPropagation();
        dispatch('toggleClick', event);
    }

    function handleModifyClick(event: Event): void {
        event.stopPropagation();
        if (onClick) onClick();
    }

    function handleItemClick(event: Event): void {
        if (disabled || !isClickable) return;
        event.stopPropagation();
        if (onClick) onClick();
    }

    function handleKeydown(event: KeyboardEvent, action: (event: Event) => void): void {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            action(event);
        }
    }

    // Language change handler
    let languageChangeHandler: () => void;
    
    onMount(() => {
        languageChangeHandler = () => {
            // This empty function will trigger reactivity
        };
        window.addEventListener('language-changed', languageChangeHandler);
    });
    
    onDestroy(() => {
        window.removeEventListener('language-changed', languageChangeHandler);
    });

    // Calculate how many icons to show and how many are remaining
    $: visibleIcons = appIcons.slice(0, maxVisibleIcons);
    $: remainingIcons = Math.max(0, appIcons.length - maxVisibleIcons);
</script>

<!-- 

A settingsitem can have any of these things:
- left aligned: an icon (mandatory)
    - always with 'settings_size' class to set the right size
    - for styling:
        - can be a main settings icon: example - 'icon settings_size user'
        - can be a subsetting icon: example - 'icon settings_size subsetting_icon settings'
        - can be an app icon: example - 'icon settings_size app-ai'
        - can be a provider icon: example - 'icon settings_size provider-google'
- left aligned but right next to icon:
    - a subtitle_top (optional)
        - by default in color --color-grey-60
        - size 14px
        - left aligned text
        - single line
        - if beyond single line, shorten end with '...'
        - always aligned to the top of the settingsitem
        - above the title
    - a title (optional)
        - by default in color --color-grey-100, but if the settingsitem opens a menu/submenu AND settingsitem does NOT have a modify button, the title is <mark> tags
        - medium thickness
        - size 16px
        - left aligned text
        - up to three lines
        - if beyond three lines, shorten end with '...'
        - if both title and subtitle, make subtitle aligned to the top and title aligned to the bottom
        - if only title, center it vertically
    - a subtitle_bottom (optional)
        - by default in color --color-grey-60
        - size 14px
        - left aligned text
        - single line
        - if beyond single line, shorten end with '...'
        - always aligned to the bottom of the settingsitem
        - below the title
    - number of credits (optional)
        - by default in color --color-grey-60
        - text: signup.amount_currency.text with variables amount and currency replaced with the actual values
        - size 16px
    - one or multiple apps or providers without text (optional)
        - shows all the icons of the apps or providers in settings_size in a row behind each other (first icon is left aligned, then the second is z position behind it, the third behind the second, etc.)
        - icons are stacked in position: the second and followup icons have a negative margin-left of 20px, so they are partially hidden behind the previous icon
        - if there are more than 4, show 4 icons and a '+{remaining}' text in --color-grey-100 16px
    - one or multiple apps or providers with text (optional)
        - left aligned: an icon (mandatory)
            - always with 'settings_size' class to set the right size
            - for styling:
                - can be an app icon: example - 'icon settings_size app-ai'
                - can be a provider icon: example - 'icon settings_size provider-google'
        - left aligned but right next to icon:
            - a subtitle_top (optional)
                - by default in color --color-grey-60
                - size 14px
                - left aligned text
                - single line
                - if beyond single line, shorten end with '...'
                - always aligned to the top of the settingsitem
                - above the title
            - a title (optional)
                - by default in color --color-grey-100, but if the settingsitem opens a menu/submenu AND settingsitem does NOT have a modify button, the title is <mark> tags
                - medium thickness
                - size 16px
                - left aligned text
                - up to three lines
                - if beyond three lines, shorten end with '...'
                - if both title and subtitle, make subtitle aligned to the top and title aligned to the bottom
                - if only title, center it vertically
            - a subtitle_bottom (optional)
                - by default in color --color-grey-60
                - size 14px
                - left aligned text
                - single line
                - if beyond single line, shorten end with '...'
                - always aligned to the bottom of the settingsitem
                - below the title
- right aligned:
    - toggle (optional)
    - modify button (optional)
- a link that opens a submenu on click of the settingsitem (optional)
    - if settingsitem has a modify button, forward the click on modify button also to the settingsitem click handler
    - if settingsitem has a toggle, do not forward the click on the toggle to the settingsitem click handler but to the toggle click handler
    - if settingsitem has a toggle and no settingsitem click handler, forward the click to the toggle and toggle click handler

-->

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
    on:click={handleItemClick}
    on:keydown={(e) => !disabled && isClickable && handleKeydown(e, handleItemClick)}
    role={isClickable ? "menuitem" : "menuitemtext"}
    tabindex={disabled ? -1 : (isClickable ? 0 : undefined)}
>
    <div class="menu-item-content">
        <div class="menu-item-left">
            <!-- Main icon - width and size preserved -->
            <div class="icon-container">
                <div class={iconClass}>
                    <slot name="icon"></slot>
                </div>
            </div>
            
            <div class="text-and-nested-container">
                <div class="text-container" class:has-title={!!title} class:has-subtitle={hasAnySubtitle} class:heading-text={type === 'heading'}>
                    <!-- Top subtitle if present -->
                    {#if subtitleTop}
                        <div class="subtitle subtitle-top">{translatedSubtitleTop}</div>
                    {/if}
                    
                    <!-- Main title if present -->
                    {#if title}
                        <div class="menu-title">
                            {#if type === 'heading'}
                                <strong>{translatedTitle}</strong>
                            {:else if isSubmenuWithoutModify}
                                <mark>{translatedTitle}</mark>
                            {:else}
                                {translatedTitle}
                            {/if}
                        </div>
                    {/if}
                    
                    <!-- Bottom subtitle if present -->
                    {#if subtitleBottom}
                        <div class="subtitle subtitle-bottom">{translatedSubtitleBottom}</div>
                    {/if}
                    
                    <!-- Credits display if enabled -->
                    {#if showCredits && translatedCredits}
                        <div class="credits">{translatedCredits}</div>
                    {/if}
                    
                    <!-- App/provider icons without text -->
                    {#if appIcons.length > 0}
                        <div class="app-icons-container">
                            {#each visibleIcons as appIcon, i}
                                <div 
                                    class="icon settings_size {appIcon.type || 'app'}-{appIcon.name.toLowerCase()}" 
                                    style="margin-left: {i > 0 ? '-20px' : '0'}; z-index: {visibleIcons.length - i};"
                                ></div>
                            {/each}
                            {#if remainingIcons > 0}
                                <div class="icon-remaining">+{remainingIcons}</div>
                            {/if}
                        </div>
                    {/if}
                </div>
                
                <!-- Nested items container - now inside text-and-nested-container -->
                {#if hasNestedItems}
                    <div class="nested-items-container">
                        <slot></slot>
                    </div>
                {/if}
            </div>
        </div>
        
        <!-- Right aligned content - now absolutely positioned -->
        <div class="menu-item-right">
            <!-- Toggle switch if enabled -->
            {#if hasToggle}
                <div 
                    on:click={handleToggleClick}
                    on:keydown={(e) => handleKeydown(e, handleToggleClick)}
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
                <ModifyButton 
                    on:click={handleModifyClick}
                    on:keydown={(e) => handleKeydown(e, handleModifyClick)}
                />
            {/if}
        </div>
    </div>
</div>

<style>
    .menu-item {
        display: flex;
        flex-direction: column;
        padding: 5px 10px;
        border-radius: 12px;
        transition: background-color 0.2s ease;
        position: relative; /* Establish positioning context */
    }

    /* Remove padding for nested menu items */
    .menu-item.nested {
        padding-left: 0;
        padding-right: 0;
    }

    /* Remove top padding for the first nested menu item */
    .menu-item.nested:first-child {
        padding-top: 0;
    }

    .menu-item-content {
        display: flex;
        width: 100%;
        position: relative; /* For positioning child elements */
    }

    .menu-item-left {
        display: flex;
        align-items: center; /* Default alignment for standard items */
        gap: 12px;
        flex-grow: 1;
        overflow: hidden;
    }

    /* Special alignment for items with nested content - align items to the top */
    .has-nested-items .menu-item-left {
        align-items: flex-start;
    }

    .icon-container {
        flex-shrink: 0; /* Prevents icon from shrinking */
        display: flex;
        align-items: center;
    }

    .text-and-nested-container {
        display: flex;
        flex-direction: column;
        flex-grow: 1;
        overflow: hidden;
        justify-content: center; /* Center content vertically when no nested items */
    }

    /* Only align to flex-start when nested items are present */
    .has-nested-items .text-and-nested-container {
        justify-content: flex-start;
    }

    .menu-item-right {
        position: absolute;
        right: 0;
        top: 6px;
        /* Remove transform that was causing positioning issues */
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .text-container {
        display: flex;
        flex-direction: column;
        overflow: hidden;
        justify-content: center; /* Center content vertically */
        min-height: 24px; /* Ensure consistent height */
    }
    
    /* For title-only items, center the title vertically */
    .text-container.has-title:not(.has-subtitle) {
        justify-content: center;
    }
    
    /* Specific styles for heading type */
    .heading-text {
        justify-content: center; /* Center the content vertically */
    }

    .subtitle {
        font-size: 14px;
        color: var(--color-grey-60);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        text-align: left;
    }

    .subtitle-top {
        margin-bottom: 2px;
    }

    .subtitle-bottom {
        margin-top: 2px;
    }

    .menu-title {
        font-size: 16px;
        color: var(--color-grey-100);
        text-align: left;
        display: -webkit-box;
        -webkit-line-clamp: 3;
        -webkit-box-orient: vertical;
        overflow: hidden;
        font-weight: 500;
    }

    .heading .menu-title strong {
        font-weight: 700;
    }

    .credits {
        font-size: 16px;
        color: var(--color-grey-60);
    }

    .app-icons-container {
        display: flex;
        align-items: center;
        margin-top: 4px;
    }

    .icon-remaining {
        font-size: 16px;
        color: var(--color-grey-100);
        margin-left: 4px;
    }

    .toggle-container {
        display: flex;
        align-items: center;
    }

    .nested-items-container {
        margin-top: 8px;
        width: 100%;
    }

    .has-nested-items {
        padding-bottom: 10px;
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
</style>