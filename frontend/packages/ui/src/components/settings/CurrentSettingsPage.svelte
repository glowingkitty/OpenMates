
<script lang="ts">
    import { text } from '@repo/ui';
    import { fly } from 'svelte/transition';
    import { cubicOut } from 'svelte/easing';
    import { userProfile } from '../../stores/userProfile';
    import { webSocketService } from '../../services/websocketService';
    import SettingsItem from '../SettingsItem.svelte';
    import { createEventDispatcher, onMount, tick } from 'svelte';
    import type { SvelteComponent } from 'svelte';

    // Props using Svelte 5 runes
    let { 
        activeSettingsView = 'main',
        direction = 'forward',
        username = '',
        isInSignupMode = false,
        settingsViews = {},
        isIncognitoEnabled = $bindable(false),
        isGuestEnabled = $bindable(false),
        isOfflineEnabled = $bindable(false),
        menuItemsCount = $bindable(0),
        sliderElement = null
    }: {
        activeSettingsView?: string;
        direction?: string;
        username?: string;
        isInSignupMode?: boolean;
        settingsViews?: Record<string, typeof SvelteComponent>;
        isIncognitoEnabled?: boolean;
        isGuestEnabled?: boolean;
        isOfflineEnabled?: boolean;
        menuItemsCount?: number;
        sliderElement?: HTMLDivElement | null;
    } = $props();
    
    // Calculate the actual count of menu items for height adjustment using Svelte 5 runes
    $effect(() => {
        // Count all settings items plus logout
        const settingsCount = Object.keys(settingsViews).length + 1;
        // Quick settings are currently commented out (TODO), so don't reduce height in signup mode
        // This ensures consistent height and prevents content cutoff
        const quickSettingsCount = 3; // Keep consistent height regardless of signup mode
        menuItemsCount = settingsCount + quickSettingsCount;
    });

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
    let visibleViews = $state(new Set([activeSettingsView]));
    // Track the previous active view for transitions
    let previousView = $state(activeSettingsView);
    
    // Keep track of transition state
    let inTransition = false;

    // Handle view changes reactively using Svelte 5 runes
    $effect(() => {
        if (activeSettingsView && activeSettingsView !== previousView) {
            handleViewChange(activeSettingsView);
        }
    });

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

    function showSettingsView(viewName, event) {
        // Stop propagation to prevent document click handler from closing menu
        if (event) event.stopPropagation();
        
        dispatch('openSettings', { 
            settingsPath: viewName, 
            direction: 'forward',
            icon: viewName,
            title: $text(`settings.${viewName}.text`)
        });
        
        // Find settings content element and scroll to top
        // Fixed: Use document.querySelector instead of document.closest
        const settingsContent = document.querySelector('.settings-content-wrapper');
        if (settingsContent) {
            settingsContent.scrollTo({
                top: 0,
                behavior: 'smooth'
            });
        }
    }
    
    // Add function to filter out nested views from main menu
    function isTopLevelView(key: string): boolean {
        return !key.includes('/');
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

        const handleCreditsUpdate = (payload) => {
            if (payload && typeof payload.credits === 'number') {
                userProfile.update(profile => ({ ...profile, credits: payload.credits }));
            }
        };

        webSocketService.on('user_credits_updated', handleCreditsUpdate);

        return () => {
            webSocketService.off('user_credits_updated', handleCreditsUpdate);
        };
    });

    // Get credits from userProfile store using Svelte 5 runes
    let credits = $derived($userProfile.credits || 0);
</script>

<div class="settings-content-slider" style="min-height: {menuItemsCount * 50 + 140}px;" bind:this={sliderElement}>
	<!-- Main user info header that slides with settings items -->
	{#if visibleViews.has('main')}

        <!-- Main settings items -->
        <div 
            class="settings-items"
            class:active={activeSettingsView === 'main'}
            in:fly={getFlyParams(true, direction)}
            out:fly={getFlyParams(false, direction)}
            style="z-index: {activeSettingsView === 'main' ? 2 : 1};"
            onoutroend={() => handleAnimationComplete('main')}
        >
            <div class="user-info-container">
                <div class="username">{username}</div>
                <div class="credits-container">
                    <span class="credits-icon"></span>
                    <div class="credits-text">
                        <span class="credits-amount"><mark>{$text('settings.credits_amount.text').replace('{credits_amount}', credits.toString())}</mark></span>
                    </div>
                </div>
            </div>
            <!-- Quick Settings - Only show when not in signup process -->
            {#if !isInSignupMode}
                <!-- TODO: unhide again once features implemented -->
                <!-- <SettingsItem 
                    type="quickaction" 
                    icon="subsetting_icon subsetting_icon_incognito"
                    title={$text('settings.incognito.text')}
                    hasToggle={true}
                    bind:checked={isIncognitoEnabled}
                    onClick={() => handleQuickSettingClick('incognito')}
                />
                <SettingsItem 
                    type="quickaction" 
                    icon="subsetting_icon subsetting_icon_guest"
                    title={$text('settings.guest.text')}
                    hasToggle={true}
                    bind:checked={isGuestEnabled}
                    onClick={() => handleQuickSettingClick('guest')}
                />
                <SettingsItem 
                    type="quickaction" 
                    icon="subsetting_icon subsetting_icon_offline"
                    title={$text('settings.offline.text')}
                    hasToggle={true}
                    bind:checked={isOfflineEnabled}
                    onClick={() => handleQuickSettingClick('offline')}
                /> -->
            {/if}

            <!-- Regular Settings -->
            {#each Object.entries(settingsViews).filter(([key, _]) => isTopLevelView(key)) as [key, _]}
                <SettingsItem 
                    icon={key} 
                    title={$text(`settings.${key}.text`)} 
                    onClick={() => showSettingsView(key, null)} 
                />
            {/each}

            <SettingsItem 
                icon="subsetting_icon subsetting_icon_logout" 
                title={$text('settings.logout.text')} 
                onClick={handleLogout} 
            />
        </div>
    {/if}
    
    <!-- Render only needed subsettings views -->
    {#each Object.entries(settingsViews) as [key, component]}
        {@const Component = component}
        {#if visibleViews.has(key)}
            <div 
                class="settings-submenu-content"
                class:active={activeSettingsView === key}
                in:fly={getFlyParams(true, direction)}
                out:fly={getFlyParams(false, direction)}
                style="z-index: {activeSettingsView === key ? 2 : 1};"
                onoutroend={() => handleAnimationComplete(key)}
            >
                <Component 
                    on:openSettings={event => {
                        // Bubble up nested view change events
                        dispatch('openSettings', event.detail);
                    }}
                />
            </div>
        {/if}
    {/each}
</div>

<style>
    .user-info-container {
        margin-left: 85px;
        display: flex;
        flex-direction: column;
        gap: 4px;
        padding-bottom: 10px;
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

    .settings-content-slider {
        position: relative;
        width: 100%;
        overflow: hidden;
        padding-top: 10px;
        /* min-height now set dynamically via style attribute */
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
</style>
