
<script lang="ts">
    import { text } from '@repo/ui';
    import { cubicOut } from 'svelte/easing';
    import { userProfile } from '../../stores/userProfile';
    import { authStore } from '../../stores/authStore';
    import { featureAvailabilityStore, initializeFeatureAvailability } from '../../stores/appSkillsStore';
    import { incognitoMode } from '../../stores/incognitoModeStore'; // Import incognito mode store
    import { isLearningModeAuthError, learningMode } from '../../stores/learningModeStore';
    import { notificationStore } from '../../stores/notificationStore';
    import SettingsItem from '../SettingsItem.svelte';
    import { createEventDispatcher, onMount } from 'svelte';
    import type { SvelteComponent } from 'svelte';

    // Props using Svelte 5 runes
    let { 
        activeSettingsView = 'main',
        direction = 'forward',
        username = '',
        accountId = null,
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        isInSignupMode = false,
        settingsViews = {},
        isIncognitoEnabled = $bindable(false),
        isGuestEnabled = $bindable(false),
        isOfflineEnabled = $bindable(false),
        menuItemsCount = $bindable(0),
        isMenuVisible = false,
        paymentEnabled = true,
        isSelfHosted = false,
        // When true (default), renders the docked profile avatar + username + credits inline.
        // Set to false when a SettingsMainHeader gradient banner is rendered above, so the
        // profile section is not duplicated.
        showProfileHeader = true,
        // Pre-resolved blob URL (or legacy https:// URL) for the profile avatar.
        // Passed from the parent (Settings.svelte) which fetches it via profileImageService
        // so that auth-gated proxy paths work correctly. Falls back to the raw store value
        // for the legacy case where showProfileHeader=true is used standalone.
        resolvedProfileImageUrl = null,
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
        isMenuVisible?: boolean;
        paymentEnabled?: boolean;
        isSelfHosted?: boolean;
        showProfileHeader?: boolean;
        resolvedProfileImageUrl?: string | null;
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
    let disabledFeatures = $derived($featureAvailabilityStore.disabledById);
    
    // Local state for incognito toggle that syncs with store
    let incognitoToggleChecked = $state(false);
    
    // Guard to prevent the onClick handler from firing twice in the same tick.
    // Toggle.svelte uses bind:checked on a checkbox inside a <label>, and SettingsItem wraps
    // it in a div with its own onclick. In Safari and some other browsers this can trigger
    // the parent onClick callback twice (once from the toggle-container div click, once from
    // the label/input synthetic click), causing a double-toggle where deactivation immediately
    // re-activates incognito mode.
    let incognitoClickInProgress = $state(false);
    
    // Sync local toggle state with store.
    // Note: we only sync FROM the store TO local state (not the other way around).
    // The local state is the source of truth for the UI; the store is updated explicitly
    // in the onClick handler.
    $effect(() => {
        incognitoToggleChecked = $incognitoMode;
    });

    $effect(() => {
        if (!isAuthenticated) {
            if ($learningMode.source === 'guest_session' || $learningMode.loading) return;
            learningMode.loadGuest();
            return;
        }
        if (($learningMode.loaded && $learningMode.source === 'account') || $learningMode.loading) return;
        learningMode.load().catch((error) => {
            console.error('[CurrentSettingsPage] Failed to load Learning Mode status:', error);
            if (isLearningModeAuthError(error)) return;
            notificationStore.error($text('settings.learning_mode_load_error'));
        });
    });
    
    // Calculate the actual count of menu items for height adjustment using Svelte 5 runes
    $effect(() => {
        // Count only top-level settings items (exclude nested routes like apps/web, billing/buy-credits, etc.)
        // This matches what's actually displayed in the main menu (filtered by isTopLevelView)
        const topLevelSettingsCount = Object.keys(settingsViews).filter(key => isVisibleTopLevelView(key)).length;
        // Add 1 for logout button (only shown for authenticated users, but we count it for consistent height)
        const settingsCount = topLevelSettingsCount + 1;
        // Quick settings are currently commented out (TODO), so don't reduce height in signup mode
        // This ensures consistent height and prevents content cutoff
        const quickSettingsCount = 4; // Keep consistent height regardless of signup mode
        menuItemsCount = settingsCount + quickSettingsCount;
    });

    /** Fade in the incoming view without moving content outside the settings panel. */
    function fadeIn(_node: Element, _params: { dir: string }) {
        const duration = 200; // Fast, snappy animation

        return {
            duration,
            easing: cubicOut,
            css: (t: number) => `opacity: ${t};`
        };
    }

    const dispatch = createEventDispatcher();

    function handleQuickSettingClick(toggleName) {
        dispatch('quickSettingClick', { toggleName });
    }

    const SETTINGS_VIEW_TITLE_KEYS: Record<string, string> = {
        'learning-mode/setup': 'settings.learning_mode',
    };

    const SETTINGS_VIEW_ICON_OVERRIDES: Record<string, string> = {
        'learning-mode/setup': 'study',
        'projects': 'project',
        'teams': 'team',
    };

    function showSettingsView(viewName, event) {
        // Stop propagation to prevent document click handler from closing menu
        if (event) event.stopPropagation();

        const isLogsView = viewName === 'logs';
        const titleKey = SETTINGS_VIEW_TITLE_KEYS[viewName] ?? `settings.${viewName}`;
        dispatch('openSettings', {
            settingsPath: viewName,
            direction: 'forward',
            icon: SETTINGS_VIEW_ICON_OVERRIDES[viewName] ?? (isLogsView ? 'server' : viewName),
            title: isLogsView ? 'Logs' : $text(titleKey)
        });
    }
    
    // Routes that are accessible only via deep link (e.g. from the chat context menu)
    // and must NOT appear in the settings nav sidebar.
    const DEEPLINK_ONLY_VIEWS = new Set(['fork']);

    onMount(() => {
        void initializeFeatureAvailability();
    });

    // Add function to filter out nested views from main menu
    function isTopLevelView(key: string): boolean {
        return !key.includes('/') && !DEEPLINK_ONLY_VIEWS.has(key);
    }

    function isSettingsViewFeatureEnabled(key: string): boolean {
        if (key === 'projects') {
            return disabledFeatures !== null && disabledFeatures['platform:projects'] !== true;
        }
        if (key === 'teams') {
            return disabledFeatures !== null && disabledFeatures['platform:teams'] !== true;
        }
        return true;
    }

    function isVisibleTopLevelView(key: string): boolean {
        return isTopLevelView(key) && isSettingsViewFeatureEnabled(key);
    }

    function handleLogout() {
        dispatch('logout');
    }

    // Get credits from userProfile store using Svelte 5 runes
    let credits = $derived($userProfile.credits || 0);
    let isAdminUser = $derived($userProfile.is_admin === true);
    let ActiveSettingsComponent = $derived(settingsViews[activeSettingsView]);

</script>

<div
    class="settings-content-slider"
    data-testid="settings-content-slider"
>
	<!-- Main settings menu - shown only when active -->
	{#if activeSettingsView === 'main'}
        <div 
            class="settings-items active"
            data-testid="settings-page-content"
            in:fadeIn={{ dir: direction }}
        >
            <!-- Profile header: docked avatar + username + credits.
                 Hidden when showProfileHeader=false (e.g. SettingsMainHeader gradient banner
                 is already rendered above by Settings.svelte, so we skip it here). -->
            {#if showProfileHeader}
                <!-- Profile container that scrolls with content (appears after 400ms delay) -->
                {#if showDockedProfile}
                    <div class="profile-container-docked">
                        {#if !isAuthenticated}
                            <div class="profile-picture language-icon-container">
                                <!-- Show user icon when menu is open (same behavior as original profile container) -->
                                <div class="clickable-icon icon_user"></div>
                            </div>
                        {:else}
                            <!-- Use resolvedProfileImageUrl (fetched via profileImageService with
                                 credentials) so auth-gated proxy paths work. Falls back to the
                                 raw profileImageUrl only for legacy public https:// URLs which
                                 don't need credential forwarding. Never use the raw proxy path
                                 directly in CSS background-image — browsers don't send cookies. -->
                            {@const avatarUrl = resolvedProfileImageUrl ?? (profileImageUrl?.startsWith('http') ? profileImageUrl : null)}
                            <div
                                class="profile-picture"
                                data-testid="profile-picture"
                                class:profile-picture-img={!!avatarUrl}
                            >
                                {#if avatarUrl}
                                    <img class="profile-picture-avatar" src={avatarUrl} alt="Profile" />
                                {:else}
                                    <div class="default-user-icon"></div>
                                {/if}
                            </div>
                        {/if}
                    </div>
                {/if}
                <div class="user-info-container">
                    <div class="username" class:shifted={!paymentEnabled}>{username || 'Guest'}</div>
                    <!-- Credits container - hidden visually when payment is disabled (self-hosted) but maintains layout space -->
                    <div class="credits-container" data-testid="credits-container" class:hidden={!paymentEnabled}>
                        <span class="credits-icon"></span>
                        <div class="credits-text">
                            <span class="credits-amount"><mark>{$text('settings.credits_amount').replace('{credits_amount}', credits.toString())}</mark></span>
                        </div>
                    </div>
                </div>
            {/if}
            
            <!-- Incognito mode toggle - appears above Usage like language toggles -->
            <!-- Only show for authenticated users -->
            {#if isAuthenticated}
                <div data-testid="incognito-toggle-wrapper">
                    <SettingsItem
                        type="quickaction"
                        icon="subsetting_icon incognito"
                        title={$text('settings.incognito')}
                        hasToggle={true}
                        checked={incognitoToggleChecked}
                        onClick={async () => {
                            // Guard against double-fire: in Safari, clicking the toggle can trigger
                            // onClick twice in the same tick (once from the toggle-container div,
                            // once from the label's synthetic click event). Without this guard,
                            // deactivation would immediately re-activate incognito mode.
                            if (incognitoClickInProgress) {
                                return;
                            }
                            incognitoClickInProgress = true;
                            // Reset the guard after the current microtask queue is flushed.
                            // Using Promise.resolve() ensures the guard is active for any synchronous
                            // re-entrant calls but resets before the next user interaction.
                            Promise.resolve().then(() => { incognitoClickInProgress = false; });

                            // Read the intended new value from the store (source of truth).
                            // We read from the store (not incognitoToggleChecked) because the Toggle's
                            // bind:checked may have already flipped the local state before onClick fires.
                            const currentValue = $incognitoMode;
                            const newValue = !currentValue;

                            // CRITICAL: If mode is currently ON and we're turning it OFF, just toggle it off.
                            // Don't show the info screen when turning off.
                            if (currentValue && !newValue) {
                                // Update local state immediately for responsive UI
                                incognitoToggleChecked = false;

                                // Update store (handles deletion of incognito chats when disabling)
                                await incognitoMode.set(false);

                                // Dispatch to parent for any additional handling
                                handleQuickSettingClick('incognito');
                                return; // Exit early - don't navigate to info screen
                            }

                            // If mode is currently OFF and we're turning it ON:
                            // - If the user has already seen the explainer before, activate immediately.
                            // - Otherwise show the info/explainer screen first so the user confirms.
                            if (newValue) {
                                if ($userProfile.incognito_explainer_seen) {
                                    // User already confirmed the explainer before — activate immediately.
                                    await incognitoMode.set(true);
                                    incognitoToggleChecked = true;
                                } else {
                                    // First time — show explainer. Keep toggle OFF until user confirms.
                                    // The Toggle's bind:checked may have already flipped it to true (optimistic),
                                    // so we reset it here to wait for confirmation.
                                    incognitoToggleChecked = false;

                                    // Navigate to incognito info submenu - user will confirm activation there
                                    showSettingsView('incognito/info', null);
                                }
                            }

                            // Dispatch to parent for any additional handling
                            handleQuickSettingClick('incognito');
                        }}
                    />
                </div>

            {/if}

            {#if isAuthenticated}
                <div data-testid="learning-mode-toggle-wrapper">
                    <SettingsItem
                        type="quickaction"
                        icon="study"
                        title={$text('settings.learning_mode')}
                        hasToggle={true}
                        checked={$learningMode.enabled}
                        disabled={$learningMode.loading}
                        onClick={() => showSettingsView('learning-mode/setup', null)}
                    />
                </div>
            {/if}

            <!-- Regular Settings -->
            {#each Object.entries(settingsViews).filter(([key]) => isVisibleTopLevelView(key) && (key !== 'logs' || isAdminUser)) as [key]}
                <SettingsItem
                    type="submenu"
                    icon={SETTINGS_VIEW_ICON_OVERRIDES[key] ?? (key === 'logs' ? 'server' : key)}
                    title={key === 'logs' ? 'Logs' : $text(`settings.${key}`)}
                    data-testid={key === 'teams' ? 'settings-teams-item' : undefined}
                    onClick={() => showSettingsView(key, null)}
                />
            {/each}

            <!-- Only show logout button for authenticated users -->
            {#if username}
                <SettingsItem
                    type="quickaction"
                    icon="subsetting_icon logout"
                    title={$text('settings.logout')}
                    onClick={handleLogout}
                />
            {/if}
        </div>
    {/if}
    
    <!-- Key the single active component so dynamically registered routes cannot reuse stale page state. -->
    {#if ActiveSettingsComponent && isSettingsViewFeatureEnabled(activeSettingsView)}
        {#key activeSettingsView}
            <div 
                class="settings-submenu-content active"
                data-testid="settings-page-content"
                in:fadeIn={{ dir: direction }}
            >
                <ActiveSettingsComponent
                    activeSettingsView={activeSettingsView}
                    accountId={accountId}
                    {isSelfHosted}
                    on:openSettings={(event: CustomEvent) => dispatch('openSettings', event.detail)}
                    on:navigateBack={() => dispatch('navigateBack')}
                    on:chatSelected={(event: CustomEvent) => dispatch('chatSelected', event.detail)}
                    on:closeSettings={() => dispatch('closeSettings')}
                />
            </div>
        {/key}
    {/if}
</div>

<style>
    .profile-container-docked {
        position: absolute;
        left: 10px;
        width: 50px;
        height: 50px;
        z-index: var(--z-index-raised);
        /* Disable pointer events and cursor to make it non-clickable */
        pointer-events: none;
        cursor: default;
        /* This container scrolls naturally with the content since it's in normal flow */
    }
    
    .profile-container-docked .profile-picture {
        border-radius: 50%;
        width: 100%;
        height: 100%;
        background-color: var(--color-grey-20);
        box-shadow: var(--shadow-xs);
        display: flex;
        align-items: center;
        justify-content: center;
    }

    /* When a profile image blob URL is available, clip the <img> to the circle */
    .profile-container-docked .profile-picture.profile-picture-img {
        overflow: hidden;
    }

    .profile-container-docked .profile-picture-avatar {
        width: 100%;
        height: 100%;
        object-fit: cover;
        border-radius: 50%;
        display: block;
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
        /* Logical property: indent text to clear the avatar on the inline-start side */
        margin-inline-start: 85px;
        display: flex;
        flex-direction: column;
        gap: var(--spacing-2);
        padding-bottom: var(--spacing-5);
    }

    .username {
        font-size: var(--font-size-xl);
        font-weight: 500;
        color: var(--color-grey-100);
        transition: transform var(--duration-slow) var(--easing-default);
    }

    /* Move username down when credits are hidden to fill the space */
    /* Credits container height: icon (19px) + gap (8px) + text line-height (~20px) = ~47px */
    .username.shifted {
        transform: translateY(13px);
    }

    .credits-container {
        display: flex;
        align-items: center;
        gap: var(--spacing-4);
    }

    /* Hide credits visually when payment is disabled (self-hosted) while maintaining layout space */
    .credits-container.hidden {
        visibility: hidden;
    }

    .credits-text {
        color: var(--color-grey-100);
        font-size: var(--font-size-p);
        background: none;
        padding: 0;
        display: flex;
        align-items: center;
        gap: var(--spacing-4);
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
        width: 100%;
        padding-top: var(--spacing-0);
    }
    
    .settings-items, 
    .settings-submenu-content {
        width: 100%;
        background-color: var(--color-grey-20);
    }

</style>
