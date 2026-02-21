<!--
Security Settings - Menu for security-related settings including Passkeys, Password, and 2FA
-->

<script lang="ts">
    import { createEventDispatcher, onMount } from 'svelte';
    import { text } from '@repo/ui';
    import SettingsItem from '../SettingsItem.svelte';
    import { getApiEndpoint, apiEndpoints } from '../../config/api';
    import { userProfile } from '../../stores/userProfile';

    const dispatch = createEventDispatcher();

    // ========================================================================
    // STATE
    // ========================================================================
    
    /** Whether user has a password configured */
    let hasPassword = $state<boolean | null>(null);
    
    /** Whether user has 2FA configured */
    let has2FA = $state<boolean | null>(null);
    
    /** Whether user has a recovery key configured */
    let hasRecoveryKey = $state<boolean | null>(null);
    
    /** Whether the auth methods are loading */
    let isLoading = $state(true);

    // ========================================================================
    // DERIVED
    // ========================================================================
    
    /** Get 2FA app name from user profile */
    let tfaAppName = $derived($userProfile.tfa_app_name);

    // ========================================================================
    // LIFECYCLE
    // ========================================================================
    
    onMount(async () => {
        await fetchAuthMethods();
    });

    // ========================================================================
    // DATA FETCHING
    // ========================================================================
    
    /**
     * Fetch user's authentication methods to determine if password/2FA is set.
     */
    async function fetchAuthMethods() {
        isLoading = true;
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.getUserAuthMethods), {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include'
            });

            if (response.ok) {
                const data = await response.json();
                hasPassword = data.has_password || false;
                has2FA = data.has_2fa || false;
                hasRecoveryKey = data.has_recovery_key || false;
                console.log('[SettingsSecurity] Auth methods loaded:', { hasPassword, has2FA, hasRecoveryKey });
            } else {
                console.error('[SettingsSecurity] Failed to fetch auth methods');
                hasPassword = null;
                has2FA = null;
                hasRecoveryKey = null;
            }
        } catch (error) {
            console.error('[SettingsSecurity] Error fetching auth methods:', error);
            hasPassword = null;
            has2FA = null;
            hasRecoveryKey = null;
        } finally {
            isLoading = false;
        }
    }

    // ========================================================================
    // COMPUTED
    // ========================================================================
    
    /** Password menu item subtitle based on whether user has password */
    let passwordSubtitle = $derived.by(() => {
        if (isLoading || hasPassword === null) {
            return '';
        }
        return hasPassword 
            ? $text('settings.account.password_change')
            : $text('settings.account.password_add');
    });
    
    /** 2FA menu item subtitle based on whether user has 2FA enabled */
    let tfaSubtitle = $derived.by(() => {
        if (isLoading || has2FA === null) {
            return '';
        }
        if (has2FA) {
            return tfaAppName 
                ? tfaAppName 
                : $text('settings.security.tfa_enabled_short');
        }
        return $text('settings.security.tfa_disabled_short');
    });
    
    /** Recovery Key menu item subtitle based on whether user has recovery key set */
    let recoveryKeySubtitle = $derived.by(() => {
        if (isLoading || hasRecoveryKey === null) {
            return '';
        }
        return hasRecoveryKey 
            ? $text('settings.security.recovery_key_set')
            : $text('settings.security.recovery_key_not_set');
    });

    // ========================================================================
    // NAVIGATION
    // ========================================================================

    /**
     * Navigate to Passkeys submenu.
     * Dispatches navigation event to parent Settings component.
     */
    function navigateToPasskeys() {
        dispatch('openSettings', {
            settingsPath: 'account/security/passkeys',
            direction: 'forward',
            icon: 'passkeys',
            title: $text('settings.account.passkeys')
        });
    }

    /**
     * Navigate to Password submenu.
     * Dispatches navigation event to parent Settings component.
     */
    function navigateToPassword() {
        const title = hasPassword 
            ? $text('settings.account.change_password')
            : $text('settings.account.add_password');
        
        dispatch('openSettings', {
            settingsPath: 'account/security/password',
            direction: 'forward',
            icon: 'password',
            title: title
        });
    }
    
    /**
     * Navigate to 2FA submenu.
     * Dispatches navigation event to parent Settings component.
     */
    function navigateTo2FA() {
        dispatch('openSettings', {
            settingsPath: 'account/security/2fa',
            direction: 'forward',
            icon: '2fa',
            title: $text('settings.security.tfa_title')
        });
    }
    
    /**
     * Navigate to Recovery Key submenu.
     * Dispatches navigation event to parent Settings component.
     */
    function navigateToRecoveryKey() {
        dispatch('openSettings', {
            settingsPath: 'account/security/recovery-key',
            direction: 'forward',
            icon: 'recovery_key',
            title: $text('settings.security.recovery_key_title')
        });
    }
</script>

<!-- Passkeys Section -->
<SettingsItem
    type="submenu"
    icon="passkeys"
    title={$text('settings.account.passkeys')}
    onClick={navigateToPasskeys}
/>

<!-- Password Section -->
<SettingsItem
    type="submenu"
    icon="password"
    title={$text('settings.account.password')}
    subtitle={passwordSubtitle}
    onClick={navigateToPassword}
/>

<!-- 2FA Section -->
<SettingsItem
    type="submenu"
    icon="tfa"
    title={$text('settings.security.tfa_title')}
    subtitle={tfaSubtitle}
    onClick={navigateTo2FA}
/>

<!-- Recovery Key Section -->
<SettingsItem
    type="submenu"
    icon="recovery_key"
    title={$text('settings.security.recovery_key_title')}
    subtitle={recoveryKeySubtitle}
    onClick={navigateToRecoveryKey}
/>