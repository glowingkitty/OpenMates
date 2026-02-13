<!-- frontend/packages/ui/src/components/PushNotificationBanner.svelte -->
<!--
    In-chat banner prompting users to enable push notifications.
    
    Displayed after the user sends their first message, between the user message
    and the pending assistant response.
    
    Behavior:
    - Shows only if push notifications are supported and permission not yet decided
    - "Enable Notifications" triggers browser permission dialog
    - "Not Yet" dismisses for the session (won't show again until next session)
    - Never shows multiple times in the same chat
    - Never shows if user has already granted/denied permission
-->
<script lang="ts">
    import { createEventDispatcher, onMount } from 'svelte';
    import { slide } from 'svelte/transition';
    import { text } from '@repo/ui';
    import {
        pushNotificationStore,
        shouldShowPushBanner,
        requiresPWAInstall
    } from '../stores/pushNotificationStore';
    import { pushNotificationService } from '../services/pushNotificationService';
    import { authStore } from '../stores/authStore';
    import { updateProfile } from '../stores/userProfile';
    
    // Note: icons.css is loaded globally via index.ts and +layout.svelte
    // No need to import it here - global icon classes (clickable-icon, icon_*) are available
    
    const dispatch = createEventDispatcher();
    
    // Local state
    let isRequesting = $state(false);
    let showIOSInstructions = $state(false);
    
    // Mark the banner as shown once it renders, so it won't reappear in future sessions.
    // This persists to localStorage via the store AND syncs to server for cross-device persistence.
    onMount(() => {
        pushNotificationStore.markBannerShown();
        
        // Sync to server if user is authenticated (persists across devices)
        if ($authStore.isAuthenticated) {
            updateProfile({ push_notification_banner_shown: true });
            console.debug('[PushNotificationBanner] Synced banner_shown to server');
        }
    });
    
    /**
     * Handle "Enable Notifications" button click
     * Requests browser permission and subscribes to push notifications
     */
    async function handleEnable(): Promise<void> {
        // Check if iOS and not installed as PWA
        if ($requiresPWAInstall) {
            showIOSInstructions = true;
            return;
        }
        
        isRequesting = true;
        
        try {
            const result = await pushNotificationService.requestPermission();
            
            if (result.granted) {
                // Permission granted, dismiss banner
                dispatch('enabled');
            } else if (result.permission === 'denied') {
                // Permission denied, dismiss banner (can't ask again)
                dispatch('denied');
            }
            // If still 'default', user dismissed the dialog - keep banner visible
        } catch (error) {
            console.error('[PushNotificationBanner] Permission request failed:', error);
        } finally {
            isRequesting = false;
        }
    }
    
    /**
     * Handle "Not Yet" button click
     * Dismisses banner for the current session
     */
    function handleNotYet(): void {
        pushNotificationStore.dismissBannerForSession();
        dispatch('dismissed');
    }
    

</script>

    {#if $shouldShowPushBanner}
    <div 
        class="push-notification-banner"
        transition:slide={{ duration: 300 }}
        role="alert"
        aria-live="polite"
    >
        {#if $requiresPWAInstall || showIOSInstructions}
            <!-- iOS PWA Installation Instructions -->
            <!-- Shown directly when iOS Safari detects PWA install is needed,
                 or after user clicks Enable on a device that requires PWA first -->
            <div class="ios-instructions">
                <div class="ios-instructions-header">
                    <span class="clickable-icon icon_announcement banner-icon"></span>
                    <span class="ios-instructions-title">
                        {$text('notifications.push.ios_install_title', { default: 'Install OpenMates First' })}
                    </span>
                    <button
                        class="ios-close-btn"
                        onclick={handleNotYet}
                        aria-label="Close"
                    >
                        <span class="clickable-icon icon_close"></span>
                    </button>
                </div>
                <div class="ios-instructions-content">
                    <p>{$text('notifications.push.ios_install_step1', { default: '1. Tap the Share button in Safari' })}</p>
                    <p>{$text('notifications.push.ios_install_step2', { default: '2. Select "Add to Home Screen"' })}</p>
                    <p>{$text('notifications.push.ios_install_step3', { default: '3. Open OpenMates from your home screen' })}</p>
                    <p>{$text('notifications.push.ios_install_step4', { default: '4. Then you can enable notifications' })}</p>
                </div>
            </div>
        {:else}
            <!-- Standard Permission Banner -->
            <div class="banner-content">
                <span class="clickable-icon icon_announcement banner-icon"></span>
                <div class="banner-text">
                    <span class="banner-title">
                        {$text('notifications.push.banner_title', { default: 'Want to receive notifications when your assistant responds?' })}
                    </span>
                    <span class="banner-subtitle">
                        {$text('notifications.push.banner_subtitle', { default: "Even when you're not in the app." })}
                    </span>
                </div>
            </div>
            
            <div class="banner-actions">
                <button
                    class="banner-btn banner-btn-primary"
                    onclick={handleEnable}
                    disabled={isRequesting}
                >
                    {#if isRequesting}
                        {$text('notifications.push.requesting', { default: 'Requesting...' })}
                    {:else}
                        {$text('notifications.push.enable_btn', { default: 'Enable Notifications' })}
                    {/if}
                </button>
                <button
                    class="banner-btn banner-btn-secondary"
                    onclick={handleNotYet}
                    disabled={isRequesting}
                >
                    {$text('notifications.push.not_yet_btn', { default: 'Not Yet' })}
                </button>
            </div>
        {/if}
    </div>
{/if}

<style>
    .push-notification-banner {
        display: flex;
        flex-direction: column;
        gap: 12px;
        padding: 16px 20px;
        margin: 12px 0;
        background-color: var(--color-grey-10);
        border-radius: 12px;
        border: 1px solid var(--color-grey-20);
    }
    
    .banner-content {
        display: flex;
        align-items: flex-start;
        gap: 12px;
    }
    
    .banner-icon {
        width: 24px;
        height: 24px;
        background: var(--color-primary);
        flex-shrink: 0;
        margin-top: 2px;
    }
    
    .banner-text {
        display: flex;
        flex-direction: column;
        gap: 4px;
        flex: 1;
    }
    
    .banner-title {
        font-size: 14px;
        font-weight: 600;
        color: var(--color-font-primary);
        line-height: 1.4;
    }
    
    .banner-subtitle {
        font-size: 13px;
        font-weight: 400;
        color: var(--color-grey-60);
        line-height: 1.4;
    }
    
    .banner-actions {
        display: flex;
        gap: 12px;
        justify-content: flex-end;
    }
    
    .banner-btn {
        padding: 10px 20px;
        border-radius: 20px;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        transition: background-color 0.2s ease, opacity 0.2s ease;
        border: none;
    }
    
    .banner-btn:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }
    
    .banner-btn-primary {
        background-color: var(--color-button-primary);
        color: var(--color-font-button);
    }
    
    .banner-btn-primary:hover:not(:disabled) {
        background-color: var(--color-button-primary-hover);
    }
    
    .banner-btn-secondary {
        background-color: transparent;
        color: var(--color-grey-60);
        border: 1px solid var(--color-grey-30);
    }
    
    .banner-btn-secondary:hover:not(:disabled) {
        background-color: var(--color-grey-20);
    }
    
    /* iOS Instructions Styles */
    .ios-instructions {
        display: flex;
        flex-direction: column;
        gap: 12px;
    }
    
    .ios-instructions-header {
        display: flex;
        align-items: center;
        gap: 12px;
    }
    
    .ios-instructions-title {
        flex: 1;
        font-size: 14px;
        font-weight: 600;
        color: var(--color-font-primary);
    }
    
    .ios-close-btn {
        all: unset;
        cursor: pointer;
        padding: 4px;
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0.7;
        transition: opacity 0.2s ease;
    }
    
    .ios-close-btn:hover {
        opacity: 1;
    }
    
    .ios-close-btn :global(.clickable-icon) {
        width: 18px;
        height: 18px;
        background: var(--color-grey-60);
    }
    
    .ios-instructions-content {
        display: flex;
        flex-direction: column;
        gap: 8px;
        padding-left: 36px;
    }
    
    .ios-instructions-content p {
        margin: 0;
        font-size: 13px;
        color: var(--color-grey-70);
        line-height: 1.5;
    }
    
    /* Mobile responsiveness */
    @media (max-width: 480px) {
        .push-notification-banner {
            padding: 14px 16px;
            margin: 8px 0;
        }
        
        .banner-actions {
            flex-direction: column;
        }
        
        .banner-btn {
            width: 100%;
            text-align: center;
        }
    }
</style>
