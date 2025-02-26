<script lang="ts">
    import { text } from '@repo/ui';
    import { fly } from 'svelte/transition';
    import { cubicOut } from 'svelte/easing';
    import { userProfile } from '../../stores/userProfile';
    import SettingsItem from '../SettingsItem.svelte';
    import { createEventDispatcher, onMount, tick } from 'svelte';
    import type { SvelteComponent } from 'svelte';

    // Pass in necessary props
    export let activeSettingsView = 'main';
    export let direction = 'forward';
    export let username = '';
    export let isInSignupMode = false;
    export let settingsViews: Record<string, typeof SvelteComponent> = {};
    export let isIncognitoEnabled = false;
    export let isGuestEnabled = false;
    export let isOfflineEnabled = false;

    // Animation parameters - now direction-aware
    const getFlyParams = (isIn: boolean, dir: string) => {
        return {
            duration: 400,
            x: dir === 'forward' ? 
                (isIn ? 300 : -300) : 
                (isIn ? -300 : 300),
            easing: cubicOut
        };
    };

    // Track views that should be present in the DOM
    let visibleViews = new Set([activeSettingsView]);
    // Track the previous active view for transitions
    let previousView = activeSettingsView;
    
    // Keep track of transition state
    let inTransition = false;

    // Handle view changes reactively
    $: if (activeSettingsView && activeSettingsView !== previousView) {
        handleViewChange(activeSettingsView);
    }

    // Function to properly manage view transitions
    async function handleViewChange(newView: string) {
        inTransition = true;
        
        // Keep track of the previous view for proper transitions
        const oldView = previousView;
        previousView = newView;
        
        // Add both the current and previous view to the visible set
        visibleViews.add(oldView);
        visibleViews.add(newView);
        
        // Force reactivity
        visibleViews = new Set([...visibleViews]);
        
        // Schedule cleanup after the animation completes
        setTimeout(() => {
            if (inTransition && oldView !== newView) {
                // Clean up the old view if it's not the current view
                visibleViews.delete(oldView);
                visibleViews = new Set([...visibleViews]);
                inTransition = false;
            }
        }, getFlyParams(true, direction).duration + 50); // Add a small buffer
    }

    const dispatch = createEventDispatcher();

    function handleQuickSettingClick(toggleName) {
        dispatch('quickSettingClick', { toggleName });
    }

    function showSettingsView(viewName) {
        dispatch('viewChange', { viewName, direction: 'forward' });
    }

    function handleLogout() {
        dispatch('logout');
    }
    
    // Called when an animation is complete
    function handleAnimationComplete(view) {
        // Only remove if it's not the active view
        if (view !== activeSettingsView) {
            visibleViews.delete(view);
            visibleViews = new Set([...visibleViews]);
        }
    }
    
    // Make sure we initialize with the right view
    onMount(() => {
        visibleViews = new Set([activeSettingsView]);
        previousView = activeSettingsView;
    });
</script>

<div class="content-slider">
    <!-- Main user info header that slides with settings items -->
    {#if visibleViews.has('main')}
        <div 
            class="header-bottom"
            class:active={activeSettingsView === 'main'}
            in:fly={getFlyParams(true, direction)}
            out:fly={getFlyParams(false, direction)}
            style="z-index: {activeSettingsView === 'main' ? 2 : 1};"
            on:outroend={() => handleAnimationComplete('main')}
        >
            <div class="user-info-container">
                <div class="username">{username}</div>
                <div class="credits-container">
                    <span class="credits-icon"></span>
                    <div class="credits-text">
                        <span class="credits-amount"><mark>4800 {$text('settings.credits.text')}</mark></span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Main settings items -->
        <div 
            class="settings-items"
            class:active={activeSettingsView === 'main'}
            in:fly={getFlyParams(true, direction)}
            out:fly={getFlyParams(false, direction)}
            style="z-index: {activeSettingsView === 'main' ? 2 : 1};"
            on:outroend={() => handleAnimationComplete('main')}
        >
            <!-- Quick Settings - Only show when not in signup process -->
            {#if !isInSignupMode}
                <SettingsItem 
                    icon="quicksetting_icon quicksetting_icon_incognito"
                    title={$text('settings.incognito.text')}
                    hasToggle={true}
                    bind:checked={isIncognitoEnabled}
                    onClick={() => handleQuickSettingClick('incognito')}
                />
                <SettingsItem 
                    icon="quicksetting_icon quicksetting_icon_guest"
                    title={$text('settings.guest.text')}
                    hasToggle={true}
                    bind:checked={isGuestEnabled}
                    onClick={() => handleQuickSettingClick('guest')}
                />
                <SettingsItem 
                    icon="quicksetting_icon quicksetting_icon_offline"
                    title={$text('settings.offline.text')}
                    hasToggle={true}
                    bind:checked={isOfflineEnabled}
                    onClick={() => handleQuickSettingClick('offline')}
                />
            {/if}

            <!-- Regular Settings -->
            {#each Object.entries(settingsViews) as [key, _]}
                <SettingsItem 
                    icon={key} 
                    title={$text(`settings.${key}.text`)} 
                    onClick={() => showSettingsView(key)} 
                />
            {/each}

            <SettingsItem 
                icon="quicksetting_icon quicksetting_icon_logout" 
                title={$text('settings.logout.text')} 
                onClick={handleLogout} 
            />
        </div>
    {/if}
    
    <!-- Render only needed subsettings views -->
    {#each Object.entries(settingsViews) as [key, component]}
        {#if visibleViews.has(key)}
            <div 
                class="settings-submenu-content"
                class:active={activeSettingsView === key}
                in:fly={getFlyParams(true, direction)}
                out:fly={getFlyParams(false, direction)}
                style="z-index: {activeSettingsView === key ? 2 : 1};"
                on:outroend={() => handleAnimationComplete(key)}
            >
                <svelte:component this={component} />
            </div>
        {/if}
    {/each}
</div>

<style>
    .header-bottom {
        display: flex;
        align-items: flex-start;
        opacity: 0;
        pointer-events: none;
        top: 0;
        left: 0;
        width: 100%;
        transform: translateX(-300px);
        transition: opacity 0.3s ease, transform 0.4s cubic-bezier(0.215, 0.61, 0.355, 1);
        padding-bottom: 10px;
    }

    .header-bottom.active {
        opacity: 1;
        pointer-events: auto;
        transform: translateX(0);
    }

    .user-info-container {
        margin-left: 72px;
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .username {
        font-size: 22px;
        font-weight: 500;
        color: var(--color-grey-100);
    }

    .credits-container {
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .credits-text {
        color: var(--color-grey-100);
        font-size: 16px;
        background: none;
        padding: 0;
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .credits-icon {
        width: 19px;
        height: 19px;
        -webkit-mask-image: url('@openmates/ui/static/icons/coins.svg');
        -webkit-mask-size: cover;
        -webkit-mask-position: center;
        -webkit-mask-repeat: no-repeat;
        mask-image: url('@openmates/ui/static/icons/coins.svg');
        mask-size: cover;
        mask-position: center;
        mask-repeat: no-repeat;
        background: var(--color-primary);
    }

    .content-slider {
        position: relative;
        width: 100%;
        min-height: 300px;
        overflow: hidden;
    }
    
    .settings-items, 
    .settings-submenu-content {
        position: absolute;
        left: 0;
        width: 100%;
        opacity: 0;
        pointer-events: none;
        transform: translateX(-300px);
        transition: opacity 0.3s ease, transform 0.4s cubic-bezier(0.215, 0.61, 0.355, 1);
    }
    
    .settings-items.active,
    .settings-submenu-content.active {
        opacity: 1;
        pointer-events: auto;
        transform: translateX(0);
    }
    
    .settings-items {
        padding: 0;
    }
    
    .settings-submenu-content {
        padding: 0 16px;
    }
</style>
