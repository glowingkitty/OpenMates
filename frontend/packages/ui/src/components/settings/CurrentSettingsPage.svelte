
<script lang="ts">
    import { text } from '@repo/ui';
    import { fly } from 'svelte/transition';
    import { cubicOut } from 'svelte/easing';
    import { userProfile } from '../../stores/userProfile';
    import { authStore } from '../../stores/authStore';
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
        sliderElement = null,
        isMenuVisible = false
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
        isMenuVisible?: boolean;
    } = $props();
    
    // State for docked profile visibility
    // Show after a delay to match the original profile container animation (400ms)
    let showDockedProfile = $state(false);
    let dockedProfileTimeout: ReturnType<typeof setTimeout> | null = null;
    
    $effect(() => {
        // Clear any existing timeout
        if (dockedProfileTimeout) {
            clearTimeout(dockedProfileTimeout);
            dockedProfileTimeout = null;
        }
        
        if (isMenuVisible && activeSettingsView === 'main') {
            // Delay fade-in to match original profile animation timing (400ms transition)
            dockedProfileTimeout = setTimeout(() => {
                showDockedProfile = true;
            }, 400);
        } else {
            // Hide immediately when menu closes or view changes
            showDockedProfile = false;
        }
        
        return () => {
            if (dockedProfileTimeout) {
                clearTimeout(dockedProfileTimeout);
            }
        };
    });
    
    let isAuthenticated = $derived($authStore.isAuthenticated);
    let profileImageUrl = $derived($userProfile.profile_image_url);
    
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

        // REMOVED: Duplicate handler for 'user_credits_updated'
        // The parent Settings.svelte already handles this event and updates the store
        // No need to register the same handler here (was causing duplicate execution)
        
        return () => {
            // Cleanup if needed
        };
    });

    // Get credits from userProfile store using Svelte 5 runes
    let credits = $derived($userProfile.credits || 0);
    
    /**
     * Track measured content height for submenu views.
     * This is updated by a ResizeObserver that watches the active content element.
     */
    let measuredContentHeight = $state<number | null>(null);
    
    /**
     * Measure the active content height using ResizeObserver.
     * This ensures the slider adapts to the actual content height for all submenu views.
     */
    $effect(() => {
        if (!sliderElement || activeSettingsView === 'main') {
            measuredContentHeight = null;
            return;
        }
        
        let resizeObserver: ResizeObserver | null = null;
        let isActive = true; // Track if this effect instance is still active
        
        // Wait for DOM to update
        tick().then(() => {
            // Check if effect is still active (not cleaned up)
            if (!isActive || !sliderElement) {
                return;
            }
            
            const activeContent = sliderElement.querySelector('.settings-items.active, .settings-submenu-content.active');
            if (!activeContent) {
                measuredContentHeight = null;
                return;
            }
            
            // Measure initial height
            measuredContentHeight = activeContent.scrollHeight;
            
            // Use ResizeObserver to track height changes
            resizeObserver = new ResizeObserver((entries) => {
                // Only update if this effect instance is still active
                if (isActive) {
                    for (const entry of entries) {
                        measuredContentHeight = entry.target.scrollHeight;
                    }
                }
            });
            
            resizeObserver.observe(activeContent);
        });
        
        // Cleanup on unmount or view change
        return () => {
            isActive = false; // Mark as inactive
            if (resizeObserver) {
                resizeObserver.disconnect();
            }
        };
    });
    
    /**
     * Calculate min-height for settings-content-slider based on active view.
     * 
     * **Main menu**: Uses calculated height based on menu items count.
     * **Submenu views**: Uses measured content height to adapt to actual content
     * (e.g., app store, interface, language settings).
     * 
     * **Why measure content height?**
     * Submenu content is absolutely positioned for slide animations, so it doesn't
     * contribute to the parent's height. By measuring the actual content height,
     * we ensure the slider is exactly tall enough without creating excessive gaps.
     * 
     * This prevents content cutoff and excessive spacing when viewing submenus.
     */
    let sliderMinHeight = $derived.by(() => {
        // For main menu, use calculated height based on menu items
        if (activeSettingsView === 'main') {
            return `${menuItemsCount * 50 + 140}px`;
        }
        // For submenu views, use measured content height if available
        // Fallback to a reasonable default if measurement hasn't completed yet
        if (measuredContentHeight !== null && measuredContentHeight > 0) {
            return `${measuredContentHeight}px`;
        }
        // Temporary fallback while measuring (prevents layout shift)
        return '500px';
    });
</script>

<div class="settings-content-slider" style="min-height: {sliderMinHeight};" bind:this={sliderElement}>
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
            <!-- Show user info for all users (authenticated shows username, non-authenticated shows "Guest") -->
            <!-- Profile container that scrolls with content (appears instantly when menu opens) -->
            {#if showDockedProfile}
                <div class="profile-container-docked">
                    {#if !isAuthenticated}
                        <div class="profile-picture language-icon-container">
                            <!-- Show user icon when menu is open (same behavior as original profile container) -->
                            <div class="clickable-icon icon_user"></div>
                        </div>
                    {:else}
                        <div
                            class="profile-picture"
                            style={profileImageUrl ? `background-image: url(${profileImageUrl})` : ''}
                        >
                            {#if !profileImageUrl}
                                <div class="default-user-icon"></div>
                            {/if}
                        </div>
                    {/if}
                </div>
            {/if}
            <div class="user-info-container">
                <div class="username">{username || 'Guest'}</div>
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

            <!-- Only show logout button for authenticated users -->
            {#if username}
                <SettingsItem 
                    icon="subsetting_icon subsetting_icon_logout" 
                    title={$text('settings.logout.text')} 
                    onClick={handleLogout} 
                />
            {/if}
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
                    activeSettingsView={activeSettingsView}
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
    .profile-container-docked {
        position: absolute;
        left: 10px;
        width: 50px;
        height: 50px;
        z-index: 1;
        /* Disable pointer events and cursor to make it non-clickable */
        pointer-events: none;
        cursor: default;
        /* This container scrolls naturally with the content since it's in normal flow */
    }
    
    .profile-container-docked .profile-picture {
        border-radius: 50%;
        width: 100%;
        height: 100%;
        background-size: cover;
        background-position: center;
        background-repeat: no-repeat;
        background-color: var(--color-grey-20);
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        display: flex;
        align-items: center;
        justify-content: center;
    }
    
    .profile-container-docked .language-icon-container {
        background-color: var(--color-primary);
        display: flex;
        align-items: center;
        justify-content: center;
    }
    
    .profile-container-docked .language-icon-container .clickable-icon {
        width: 25px;
        height: 25px;
        background-color: white;
    }
    
    .profile-container-docked .default-user-icon {
        width: 32px;
        height: 32px;
        -webkit-mask-image: url('@openmates/ui/static/icons/user.svg');
        -webkit-mask-size: contain;
        -webkit-mask-position: center;
        -webkit-mask-repeat: no-repeat;
        mask-image: url('@openmates/ui/static/icons/user.svg');
        mask-size: contain;
        mask-position: center;
        mask-repeat: no-repeat;
        background-color: var(--color-grey-60);
    }

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
        padding-top: 0px; /* Removed padding to eliminate top gap */
        /* min-height now set dynamically via style attribute based on content height */
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
