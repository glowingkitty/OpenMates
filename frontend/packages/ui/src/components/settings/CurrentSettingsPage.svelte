
<script lang="ts">
    import { text } from '@repo/ui';
    import { cubicOut } from 'svelte/easing';
    import { userProfile } from '../../stores/userProfile';
    import { authStore } from '../../stores/authStore';
    import { webSocketService } from '../../services/websocketService';
    import { incognitoMode } from '../../stores/incognitoModeStore'; // Import incognito mode store
    import SettingsItem from '../SettingsItem.svelte';
    import { createEventDispatcher, onMount, tick } from 'svelte';
    import type { SvelteComponent } from 'svelte';

    // Props using Svelte 5 runes
    let { 
        activeSettingsView = 'main',
        direction = 'forward',
        username = '',
        accountId = null,
        isInSignupMode = false,
        settingsViews = {},
        isIncognitoEnabled = $bindable(false),
        isGuestEnabled = $bindable(false),
        isOfflineEnabled = $bindable(false),
        menuItemsCount = $bindable(0),
        sliderElement = null,
        isMenuVisible = false,
        paymentEnabled = true
    }: {
        activeSettingsView?: string;
        direction?: string;
        username?: string;
        accountId?: string | null;
        isInSignupMode?: boolean;
        settingsViews?: Record<string, typeof SvelteComponent>;
        isIncognitoEnabled?: boolean;
        isGuestEnabled?: boolean;
        isOfflineEnabled?: boolean;
        menuItemsCount?: number;
        sliderElement?: HTMLDivElement | null;
        isMenuVisible?: boolean;
        paymentEnabled?: boolean;
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
        
        // Only show profile on main settings view
        // Hide immediately for all sub-settings views (including when opened via deep link)
        if (isMenuVisible && activeSettingsView === 'main') {
            // Delay fade-in to match original profile animation timing (400ms transition)
            dockedProfileTimeout = setTimeout(() => {
                showDockedProfile = true;
            }, 400);
        } else {
            // Hide immediately when menu closes or view changes to any non-main view
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
    
    // Local state for incognito toggle that syncs with store
    let incognitoToggleChecked = $state(false);
    
    // Sync local toggle state with store
    $effect(() => {
        incognitoToggleChecked = $incognitoMode;
    });
    
    // Calculate the actual count of menu items for height adjustment using Svelte 5 runes
    $effect(() => {
        // Count only top-level settings items (exclude nested routes like app_store/web, billing/buy-credits, etc.)
        // This matches what's actually displayed in the main menu (filtered by isTopLevelView)
        const topLevelSettingsCount = Object.keys(settingsViews).filter(key => isTopLevelView(key)).length;
        // Add 1 for logout button (only shown for authenticated users, but we count it for consistent height)
        const settingsCount = topLevelSettingsCount + 1;
        // Quick settings are currently commented out (TODO), so don't reduce height in signup mode
        // This ensures consistent height and prevents content cutoff
        const quickSettingsCount = 3; // Keep consistent height regardless of signup mode
        menuItemsCount = settingsCount + quickSettingsCount;
    });

    /**
     * Simple slide-in transition for settings views.
     * Only the incoming view is animated - the old view is immediately hidden.
     * This avoids all visual glitches from overlapping views.
     */
    function slideIn(node: Element, { dir }: { dir: string }) {
        const duration = 200; // Fast, snappy animation
        const x = dir === 'forward' ? 250 : -250;
        
        return {
            duration,
            easing: cubicOut,
            css: (t: number) => `transform: translateX(${(1 - t) * x}px);`
        };
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
            title: $text(`settings.${viewName}`)
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
	<!-- Main settings menu - shown only when active -->
	{#if activeSettingsView === 'main'}
        <div 
            class="settings-items active"
            in:slideIn={{ dir: direction }}
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
                <div class="username" class:shifted={!paymentEnabled}>{username || 'Guest'}</div>
                <!-- Credits container - hidden visually when payment is disabled (self-hosted) but maintains layout space -->
                <div class="credits-container" class:hidden={!paymentEnabled}>
                    <span class="credits-icon"></span>
                    <div class="credits-text">
                        <span class="credits-amount"><mark>{$text('settings.credits_amount').replace('{credits_amount}', credits.toString())}</mark></span>
                    </div>
                </div>
            </div>
            
            <!-- Incognito mode toggle - appears above Usage like language toggles -->
            <!-- Only show for authenticated users -->
            {#if isAuthenticated}
                <div data-testid="incognito-toggle-wrapper">
                    <SettingsItem
                        type="quickaction"
                        icon="subsetting_icon subsetting_icon_incognito"
                        title={$text('settings.incognito')}
                        hasToggle={true}
                        checked={incognitoToggleChecked}
                        onClick={async () => {
                            // Get current value from store to ensure we're toggling from the correct state
                            const currentValue = $incognitoMode;
                            const newValue = !currentValue;

                            // CRITICAL: If mode is currently ON and we're turning it OFF, just toggle it off
                            // Don't show the info screen when turning off
                            if (currentValue && !newValue) {
                                // Update local state immediately for responsive UI
                                incognitoToggleChecked = newValue;

                                // Update store (handles deletion of incognito chats when disabling)
                                await incognitoMode.set(newValue);

                                // Dispatch to parent for any additional handling
                                handleQuickSettingClick('incognito');
                                return; // Exit early - don't navigate to info screen
                            }

                            // If mode is currently OFF and we're turning it ON, show info screen first
                            // The info screen will handle actually activating the mode when user confirms
                            // Don't update the toggle state yet - let the info screen handle activation
                            // This prevents the toggle from appearing "on" before the user confirms
                            if (newValue) {
                                // Navigate to incognito info submenu - user will confirm activation there
                                showSettingsView('incognito/info', null);
                            } else {
                                // This shouldn't happen (we already handled turning off above), but just in case
                                incognitoToggleChecked = newValue;
                                await incognitoMode.set(newValue);
                            }

                            // Dispatch to parent for any additional handling
                            handleQuickSettingClick('incognito');
                        }}
                    />
                </div>
            {/if}

            <!-- Regular Settings -->
            {#each Object.entries(settingsViews).filter(([key, _]) => isTopLevelView(key)) as [key, _]}
                <SettingsItem 
                    icon={key} 
                    title={$text(`settings.${key}`)} 
                    onClick={() => showSettingsView(key, null)} 
                />
            {/each}

            <!-- Only show logout button for authenticated users -->
            {#if username}
                <SettingsItem 
                    icon="subsetting_icon subsetting_icon_logout" 
                    title={$text('settings.logout')} 
                    onClick={handleLogout} 
                />
            {/if}
        </div>
    {/if}
    
    <!-- Render only the active subsettings view -->
    {#each Object.entries(settingsViews) as [key, component]}
        {@const Component = component}
        {#if activeSettingsView === key}
            <div 
                class="settings-submenu-content active"
                in:slideIn={{ dir: direction }}
            >
                <Component 
                    activeSettingsView={key}
                    accountId={accountId}
                    on:openSettings={(event: any) => dispatch('openSettings', event.detail)}
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
        transition: transform 0.3s ease;
    }

    /* Move username down when credits are hidden to fill the space */
    /* Credits container height: icon (19px) + gap (8px) + text line-height (~20px) = ~47px */
    .username.shifted {
        transform: translateY(13px);
    }

    .credits-container {
        display: flex;
        align-items: center;
        gap: 8px;
    }

    /* Hide credits visually when payment is disabled (self-hosted) while maintaining layout space */
    .credits-container.hidden {
        visibility: hidden;
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
        pointer-events: none;
        /* 
         * Background ensures content behind doesn't show through during transitions.
         * The custom flyFade Svelte transition handles opacity and transform animations.
         * Do NOT add CSS transition properties - they conflict with Svelte's JS transitions.
         */
        background-color: var(--color-grey-20);
    }
    
    .settings-items.active,
    .settings-submenu-content.active {
        pointer-events: auto;
    }
</style>
