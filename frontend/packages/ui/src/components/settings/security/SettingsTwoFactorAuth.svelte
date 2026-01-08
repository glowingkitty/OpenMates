<!--
SettingsTwoFactorAuth - Two-Factor Authentication settings management component
Allows users to:
- View 2FA status and app name
- Change 2FA app (re-setup with new secret)

Note: 2FA CANNOT be disabled once enabled - this is by design for security.
Users can only change their 2FA app by going through the setup flow again.

Props:
- autoStartSetup: Skip overview and auth, go directly to setup (used when embedded after password setup)
- skipAuth: Skip the auth step (user already authenticated in parent flow)
- onSetupComplete: Callback when 2FA setup is successfully completed
- embedded: Whether component is embedded in another flow (hides back buttons, modifies layout)
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { getApiEndpoint, apiEndpoints } from '../../../config/api';
    import { userProfile, updateProfile } from '../../../stores/userProfile';
    import { tfaApps, tfaAppIcons } from '../../../config/tfa';
    import { theme } from '../../../stores/theme';
    import * as cryptoService from '../../../services/cryptoService';
    import QRCode from 'qrcode-svg';
    import SecurityAuth from './SecurityAuth.svelte';
    import { copyToClipboard } from '../../../utils/clipboardUtils';

    // ========================================================================
    // PROPS
    // ========================================================================
    
    interface Props {
        /** Skip overview and go directly to setup (for embedding after password setup) */
        autoStartSetup?: boolean;
        /** Skip auth step (user already authenticated in parent flow) */
        skipAuth?: boolean;
        /** Callback when 2FA setup is successfully completed */
        onSetupComplete?: () => void;
        /** Callback when user cancels 2FA setup (only relevant when embedded) */
        onCancel?: () => void;
        /** Whether component is embedded in another flow */
        embedded?: boolean;
    }
    
    let { 
        autoStartSetup = false, 
        skipAuth = false, 
        onSetupComplete,
        onCancel,
        embedded = false 
    }: Props = $props();

    // ========================================================================
    // STATE
    // ========================================================================
    
    /** Current step in the 2FA flow */
    type TfaStep = 'overview' | 'auth' | 'setup' | 'verify' | 'select-app' | 'backup-codes' | 'success';
    let currentStep = $state<TfaStep>('overview');
    
    /** Loading states */
    let isLoading = $state(false);
    let isVerifying = $state(false);
    
    /** Error and success messages */
    let errorMessage = $state<string | null>(null);
    let successMessage = $state<string | null>(null);
    
    /** 2FA setup data */
    let tfaSecret = $state('');
    let otpauthUrl = $state('');
    let qrCodeSvg = $state('');
    let verificationCode = $state('');
    
    /** Selected 2FA app */
    let selectedApp = $state<string | null>(null);
    
    /** Backup codes */
    let backupCodes = $state<string[]>([]);
    let codesConfirmed = $state(false);
    
    /** User authentication methods */
    let hasPasskey = $state(false);
    let hasPassword = $state(false);
    let has2FA = $state(false);
    
    /** Show QR code toggle */
    let showQrCode = $state(true);
    let showCopiedText = $state(false);

    // ========================================================================
    // DERIVED
    // ========================================================================
    
    /** Get 2FA status from user profile */
    let tfaEnabled = $derived($userProfile.tfa_enabled);
    let tfaAppName = $derived($userProfile.tfa_app_name);

    // ========================================================================
    // LIFECYCLE
    // ========================================================================
    
    onMount(async () => {
        await fetchAuthMethods();
        
        // If autoStartSetup is enabled, skip overview and go directly to setup
        // This is used when embedding after password setup where user is already authenticated
        if (autoStartSetup) {
            console.log('[SettingsTwoFactorAuth] Auto-starting setup (embedded mode)');
            if (skipAuth) {
                // User already authenticated, go directly to setup
                currentStep = 'setup';
                await initiate2FASetup();
            } else {
                // Need authentication first
                currentStep = 'auth';
            }
        }
    });

    // ========================================================================
    // DATA FETCHING
    // ========================================================================
    
    /**
     * Fetch user's authentication methods.
     */
    async function fetchAuthMethods() {
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.getUserAuthMethods), {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include'
            });

            if (response.ok) {
                const data = await response.json();
                hasPasskey = data.has_passkey || false;
                hasPassword = data.has_password || false;
                has2FA = data.has_2fa || false;
                console.log('[SettingsTwoFactorAuth] Auth methods:', { hasPasskey, hasPassword, has2FA });
            }
        } catch (error) {
            console.error('[SettingsTwoFactorAuth] Error fetching auth methods:', error);
        }
    }

    // ========================================================================
    // QR CODE GENERATION
    // ========================================================================
    
    /**
     * Generate QR code SVG for the OTP auth URL.
     */
    function generateQrCode(url: string) {
        if (!url) return;
        
        const color = $theme === 'dark' ? '#FFFFFF' : '#000000';
        const bgColor = 'transparent';
        
        try {
            const qr = new QRCode({
                content: url,
                padding: 0,
                width: 180,
                height: 180,
                color: color,
                background: bgColor,
                ecl: 'M'
            });
            
            qrCodeSvg = qr.svg();
        } catch (err) {
            console.error('[SettingsTwoFactorAuth] Error generating QR code:', err);
        }
    }

    // Update QR code when theme changes
    $effect(() => {
        if (otpauthUrl) {
            generateQrCode(otpauthUrl);
        }
    });

    // ========================================================================
    // 2FA SETUP FLOW
    // ========================================================================
    
    /**
     * Start 2FA setup - requires authentication first.
     */
    function startSetup() {
        currentStep = 'auth';
        errorMessage = null;
    }
    
    /**
     * Handle successful authentication, proceed to setup.
     */
    async function handleAuthSuccess() {
        currentStep = 'setup';
        await initiate2FASetup();
    }
    
    /**
     * Handle authentication failure.
     * @param message - Error message from authentication
     */
    function handleAuthFailed(message: string) {
        console.error('[SettingsTwoFactorAuth] Authentication failed:', message);
        errorMessage = message;
        currentStep = 'overview';
    }
    
    /**
     * Handle authentication cancellation.
     */
    function handleAuthCancel() {
        currentStep = 'overview';
    }
    
    /**
     * Initiate 2FA setup - get secret and QR code from server.
     */
    async function initiate2FASetup() {
        isLoading = true;
        errorMessage = null;
        
        try {
            // Get email encryption key for 2FA setup (base64 encoded for API)
            const emailEncryptionKey = cryptoService.getEmailEncryptionKeyForApi();
            
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.setup_2fa), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    email_encryption_key: emailEncryptionKey
                })
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                tfaSecret = data.secret;
                otpauthUrl = data.otpauth_url;
                generateQrCode(data.otpauth_url);
                console.log('[SettingsTwoFactorAuth] 2FA setup initiated');
            } else {
                errorMessage = data.message || $text('settings.security.tfa_setup_failed.text');
                console.error('[SettingsTwoFactorAuth] 2FA setup failed:', data.message);
            }
        } catch (error) {
            console.error('[SettingsTwoFactorAuth] Error initiating 2FA setup:', error);
            errorMessage = $text('settings.security.tfa_setup_error.text');
        } finally {
            isLoading = false;
        }
    }
    
    /**
     * Verify the 2FA code entered by the user.
     */
    async function verifyCode() {
        if (verificationCode.length !== 6 || isVerifying) return;
        
        isVerifying = true;
        errorMessage = null;
        
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.verify_2fa_code), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ code: verificationCode })
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                console.log('[SettingsTwoFactorAuth] 2FA code verified');
                // Proceed to app selection
                currentStep = 'select-app';
            } else {
                errorMessage = data.message || $text('settings.security.tfa_invalid_code.text');
                verificationCode = '';
            }
        } catch (error) {
            console.error('[SettingsTwoFactorAuth] Error verifying code:', error);
            errorMessage = $text('settings.security.tfa_verify_error.text');
            verificationCode = '';
        } finally {
            isVerifying = false;
        }
    }
    
    /**
     * Handle code input - auto-verify when 6 digits entered.
     */
    function handleCodeInput(event: Event) {
        const input = event.target as HTMLInputElement;
        verificationCode = input.value.replace(/\D/g, '').slice(0, 6);
        
        if (verificationCode.length === 6) {
            verifyCode();
        }
    }
    
    /**
     * Save selected 2FA app provider.
     */
    async function saveSelectedApp() {
        if (!selectedApp) return;
        
        isLoading = true;
        errorMessage = null;
        
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.setup_2fa_provider), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ provider: selectedApp })
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                // Update local profile
                updateProfile({ tfa_app_name: selectedApp });
                console.log('[SettingsTwoFactorAuth] 2FA app saved:', selectedApp);
                
                // Proceed to backup codes
                await requestBackupCodes();
            } else {
                errorMessage = data.message || $text('settings.security.tfa_save_app_failed.text');
            }
        } catch (error) {
            console.error('[SettingsTwoFactorAuth] Error saving app:', error);
            errorMessage = $text('settings.security.tfa_save_app_error.text');
        } finally {
            isLoading = false;
        }
    }
    
    /**
     * Request backup codes from server.
     */
    async function requestBackupCodes() {
        isLoading = true;
        
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.request_backup_codes), {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include'
            });
            
            const data = await response.json();
            
            if (response.ok && data.success && data.backup_codes) {
                backupCodes = data.backup_codes;
                currentStep = 'backup-codes';
                console.log('[SettingsTwoFactorAuth] Backup codes received');
            } else {
                errorMessage = data.message || $text('settings.security.tfa_backup_codes_failed.text');
            }
        } catch (error) {
            console.error('[SettingsTwoFactorAuth] Error requesting backup codes:', error);
            errorMessage = $text('settings.security.tfa_backup_codes_error.text');
        } finally {
            isLoading = false;
        }
    }
    
    /**
     * Confirm backup codes are stored and complete setup.
     */
    async function confirmCodesStored() {
        if (!codesConfirmed) return;
        
        isLoading = true;
        
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.auth.confirm_codes_stored), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ confirmed: true })
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                // Update profile to reflect 2FA is now enabled
                updateProfile({ tfa_enabled: true, tfa_app_name: selectedApp });
                has2FA = true;
                
                currentStep = 'success';
                successMessage = $text('settings.security.tfa_setup_complete.text');
                console.log('[SettingsTwoFactorAuth] 2FA setup complete');
                
                // Call the completion callback if provided (for embedded mode)
                if (onSetupComplete) {
                    console.log('[SettingsTwoFactorAuth] Calling onSetupComplete callback');
                    onSetupComplete();
                }
            } else {
                errorMessage = data.message || $text('settings.security.tfa_confirm_failed.text');
            }
        } catch (error) {
            console.error('[SettingsTwoFactorAuth] Error confirming codes:', error);
            errorMessage = $text('settings.security.tfa_confirm_error.text');
        } finally {
            isLoading = false;
        }
    }

    // ========================================================================
    // UTILITY FUNCTIONS
    // ========================================================================
    
    /**
     * Copy secret to clipboard.
     * Uses Safari-compatible clipboard utility with fallback.
     * Note: The secret is already visible in the settings UI, so no need for alert fallback.
     */
    async function copySecret() {
        if (!tfaSecret) return;
        
        const result = await copyToClipboard(tfaSecret);
        
        if (result.success) {
            showCopiedText = true;
            
            setTimeout(() => {
                showCopiedText = false;
            }, 2000);
        } else {
            // Secret is already visible in UI, user can manually select and copy
            console.warn('[SettingsTwoFactorAuth] Clipboard copy failed, secret visible for manual copy');
        }
    }
    
    /**
     * Copy backup codes to clipboard.
     * Uses Safari-compatible clipboard utility with fallback.
     * Note: Backup codes are already visible in the UI, so no need for alert fallback.
     */
    async function copyBackupCodes() {
        if (backupCodes.length === 0) return;
        
        const codesText = backupCodes.join('\n');
        const result = await copyToClipboard(codesText);
        
        if (result.success) {
            showCopiedText = true;
            
            setTimeout(() => {
                showCopiedText = false;
            }, 2000);
        } else {
            // Backup codes are already visible in UI, user can manually select and copy
            console.warn('[SettingsTwoFactorAuth] Clipboard copy failed, codes visible for manual copy');
        }
    }
    
    /**
     * Return to overview.
     */
    function returnToOverview() {
        currentStep = 'overview';
        errorMessage = null;
        successMessage = null;
        // Reset setup state
        tfaSecret = '';
        otpauthUrl = '';
        qrCodeSvg = '';
        verificationCode = '';
        selectedApp = null;
        backupCodes = [];
        codesConfirmed = false;
    }

    /**
     * Get icon class for 2FA app.
     */
    function getAppIcon(appName: string): string {
        return tfaAppIcons[appName as keyof typeof tfaAppIcons] || 'tfa';
    }
</script>

<div class="tfa-settings">
    {#if currentStep === 'auth'}
        <!-- Authentication Required - Always for changing 2FA app -->
        <SecurityAuth
            {hasPasskey}
            {hasPassword}
            has2FA={tfaEnabled}
            title={$text('settings.security.verify_identity.text')}
            description={$text('settings.security.tfa_auth_required.text')}
            autoStart={true}
            onSuccess={handleAuthSuccess}
            onFailed={handleAuthFailed}
            onCancel={handleAuthCancel}
        />
    {:else if currentStep === 'overview'}
        <!-- Overview State -->
        <div class="tfa-overview">
            <div class="status-card enabled">
                <div class="status-icon">
                    <span class="icon icon_shield_check"></span>
                </div>
                <div class="status-info">
                    <h3>{$text('settings.security.tfa_enabled.text')}</h3>
                    {#if tfaAppName}
                        <p class="app-name">{$text('settings.security.tfa_app_used.text')}: {tfaAppName}</p>
                    {:else}
                        <p class="app-name">{$text('settings.security.tfa_app_unknown.text')}</p>
                    {/if}
                </div>
            </div>
            
            {#if successMessage}
                <div class="success-message">{successMessage}</div>
            {/if}
            
            <p class="tfa-info">{$text('settings.security.tfa_cannot_disable.text')}</p>
            
            <div class="action-buttons">
                <button class="btn-primary" onclick={startSetup}>
                    {$text('settings.security.tfa_change_app.text')}
                </button>
            </div>
        </div>
        
    {:else if currentStep === 'setup'}
        <!-- Setup State - Show QR Code -->
        <div class="tfa-setup">
            
            <h3>{$text('settings.security.tfa_scan_qr.text')}</h3>
            <p class="description">{$text('settings.security.tfa_scan_instructions.text')}</p>
            
            {#if isLoading}
                <div class="loading-container">
                    <div class="loading-spinner"></div>
                </div>
            {:else if qrCodeSvg}
                <div class="qr-container">
                    {#if showQrCode}
                        <div class="qr-code">
                            <!-- QR code SVG is generated client-side by qrcode-svg library (safe) -->
                            {@html qrCodeSvg}
                        </div>
                    {/if}
                </div>
                
                <div class="secret-container">
                    <p class="secret-label">{$text('settings.security.tfa_secret_key.text')}</p>
                    <div class="secret-value">
                        <code>{tfaSecret}</code>
                        <button class="copy-btn" onclick={copySecret}>
                            {showCopiedText ? $text('common.copied.text') : $text('common.copy.text')}
                        </button>
                    </div>
                </div>
                
                <div class="code-input-section">
                    <p>{$text('settings.security.tfa_enter_code.text')}</p>
                    <input
                        type="text"
                        inputmode="numeric"
                        pattern="[0-9]*"
                        maxlength="6"
                        bind:value={verificationCode}
                        oninput={handleCodeInput}
                        placeholder="000000"
                        disabled={isVerifying}
                        class="otp-input"
                        class:error={!!errorMessage}
                    />
                    {#if isVerifying}
                        <div class="verifying-indicator">
                            <div class="loading-spinner-small"></div>
                        </div>
                    {/if}
                </div>
            {/if}
            
            {#if errorMessage}
                <div class="error-message">{errorMessage}</div>
            {/if}
            
            <div class="help-link">
                <span>{$text('settings.security.tfa_no_app.text')}</span>
                <a href="https://search.brave.com/search?q=best+free+2fa+otp+apps" target="_blank" rel="noopener">
                    {$text('settings.security.tfa_find_apps.text')}
                </a>
            </div>

            <!-- Cancel button only shown when embedded (e.g., during password setup) -->
            {#if embedded && onCancel}
                <button class="btn-cancel" onclick={onCancel}>
                    {$text('common.cancel.text')}
                </button>
            {/if}
        </div>
        
    {:else if currentStep === 'select-app'}
        <!-- App Selection -->
        <div class="tfa-select-app">
            <h3>{$text('settings.security.tfa_select_app.text')}</h3>
            <p class="description">{$text('settings.security.tfa_select_app_description.text')}</p>
            
            <div class="app-list">
                {#each tfaApps as app}
                    <button
                        class="app-item"
                        class:selected={selectedApp === app}
                        onclick={() => selectedApp = app}
                    >
                        <span class="app-icon icon_{getAppIcon(app)}"></span>
                        <span class="app-name">{app}</span>
                        {#if selectedApp === app}
                            <span class="check-icon">✓</span>
                        {/if}
                    </button>
                {/each}
            </div>
            
            {#if errorMessage}
                <div class="error-message">{errorMessage}</div>
            {/if}
            
            <button
                class="btn-primary"
                onclick={saveSelectedApp}
                disabled={!selectedApp || isLoading}
            >
                {#if isLoading}
                    <div class="loading-spinner-small"></div>
                {/if}
                {$text('common.continue.text')}
            </button>

            <!-- Cancel button only shown when embedded -->
            {#if embedded && onCancel}
                <button class="btn-cancel" onclick={onCancel}>
                    {$text('common.cancel.text')}
                </button>
            {/if}
        </div>
        
    {:else if currentStep === 'backup-codes'}
        <!-- Backup Codes -->
        <div class="tfa-backup-codes">
            <h3>{$text('settings.security.tfa_backup_codes.text')}</h3>
            <p class="description">{$text('settings.security.tfa_backup_codes_description.text')}</p>
            
            <div class="codes-container">
                {#each backupCodes as code, i}
                    <div class="code-item">
                        <span class="code-number">{i + 1}.</span>
                        <code>{code}</code>
                    </div>
                {/each}
            </div>
            
            <button class="btn-secondary copy-codes-btn" onclick={copyBackupCodes}>
                {showCopiedText ? $text('common.copied.text') : $text('settings.security.tfa_copy_codes.text')}
            </button>
            
            <div class="confirm-checkbox">
                <label>
                    <input type="checkbox" bind:checked={codesConfirmed} />
                    {$text('settings.security.tfa_confirm_codes_stored.text')}
                </label>
            </div>
            
            {#if errorMessage}
                <div class="error-message">{errorMessage}</div>
            {/if}
            
            <button
                class="btn-primary"
                onclick={confirmCodesStored}
                disabled={!codesConfirmed || isLoading}
            >
                {#if isLoading}
                    <div class="loading-spinner-small"></div>
                {/if}
                {$text('settings.security.tfa_complete_setup.text')}
            </button>
        </div>
        
    {:else if currentStep === 'success'}
        <!-- Success State -->
        <div class="tfa-success">
            <div class="success-icon">
                <span class="icon icon_check_circle"></span>
            </div>
            <h3>{$text('settings.security.tfa_setup_complete.text')}</h3>
            <p class="description">{$text('settings.security.tfa_setup_complete_description.text')}</p>
            
            <!-- Only show done button when not embedded - parent handles navigation in embedded mode -->
            {#if !embedded}
                <button class="btn-primary" onclick={returnToOverview}>
                    {$text('common.done.text')}
                </button>
            {/if}
        </div>
        
    {/if}
</div>

<style>
    .tfa-settings {
        padding: 16px;
    }

    /* Overview State */
    .tfa-overview {
        display: flex;
        flex-direction: column;
        gap: 24px;
    }

    .status-card {
        display: flex;
        align-items: center;
        gap: 16px;
        padding: 20px;
        background: var(--color-grey-10);
        border-radius: 12px;
        border-left: 4px solid var(--color-grey-40);
    }

    .status-card.enabled {
        border-left-color: var(--color-success);
    }

    .status-icon {
        width: 48px;
        height: 48px;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--color-grey-20);
        border-radius: 50%;
    }

    .status-icon .icon {
        font-size: 24px;
    }

    .status-info h3 {
        margin: 0 0 4px 0;
        font-size: 16px;
        font-weight: 600;
        color: var(--color-grey-100);
    }

    .status-info .app-name {
        margin: 0;
        font-size: 14px;
        color: var(--color-grey-60);
    }

    .action-buttons {
        display: flex;
        gap: 12px;
    }

    /* Setup State */
    .tfa-setup,
    .tfa-select-app,
    .tfa-backup-codes,
    .tfa-success {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 20px;
    }
    
    .tfa-info {
        font-size: 13px;
        color: var(--color-grey-60);
        text-align: center;
        margin: 0;
    }

    h3 {
        margin: 0;
        font-size: 18px;
        font-weight: 600;
        color: var(--color-grey-100);
        text-align: center;
    }

    .description {
        margin: 0;
        font-size: 14px;
        color: var(--color-grey-60);
        text-align: center;
        max-width: 400px;
    }

    /* QR Code */
    .qr-container {
        padding: 16px;
        background: var(--color-grey-5);
        border-radius: 12px;
    }

    .qr-code {
        width: 180px;
        height: 180px;
    }

    /* Secret Key */
    .secret-container {
        width: 100%;
        max-width: 400px;
    }

    .secret-label {
        font-size: 12px;
        color: var(--color-grey-50);
        margin: 0 0 8px 0;
        text-align: center;
    }

    .secret-value {
        display: flex;
        align-items: center;
        gap: 8px;
        background: var(--color-grey-10);
        padding: 12px;
        border-radius: 8px;
    }

    .secret-value code {
        flex: 1;
        font-family: monospace;
        font-size: 12px;
        color: var(--color-grey-80);
        word-break: break-all;
    }

    .copy-btn {
        background: var(--color-grey-20);
        border: none;
        padding: 6px 12px;
        border-radius: 6px;
        font-size: 12px;
        cursor: pointer;
        color: var(--color-grey-80);
    }

    .copy-btn:hover {
        background: var(--color-grey-30);
    }

    /* Code Input */
    .code-input-section {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 12px;
        width: 100%;
    }

    .otp-input {
        width: 200px;
        padding: 16px;
        font-size: 24px;
        text-align: center;
        letter-spacing: 8px;
        border: 2px solid var(--color-grey-30);
        border-radius: 8px;
        background: var(--color-grey-5);
        color: var(--color-grey-100);
        font-family: monospace;
    }

    .otp-input:focus {
        outline: none;
        border-color: var(--color-primary);
    }

    .otp-input.error {
        border-color: var(--color-danger);
    }

    .verifying-indicator {
        display: flex;
        align-items: center;
        justify-content: center;
    }

    /* App Selection */
    .app-list {
        display: flex;
        flex-direction: column;
        gap: 8px;
        width: 100%;
        max-width: 400px;
    }

    .app-item {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 16px;
        background: var(--color-grey-10);
        border: 2px solid transparent;
        border-radius: 8px;
        cursor: pointer;
        transition: all 0.2s;
    }

    .app-item:hover {
        background: var(--color-grey-15);
    }

    .app-item.selected {
        border-color: var(--color-primary);
        background: var(--color-primary-light);
    }

    .app-item .app-icon {
        width: 32px;
        height: 32px;
    }

    .app-item .app-name {
        flex: 1;
        font-size: 14px;
        color: var(--color-grey-100);
        text-align: left;
    }

    .app-item .check-icon {
        color: var(--color-primary);
        font-size: 18px;
    }

    /* Backup Codes */
    .codes-container {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 8px;
        width: 100%;
        max-width: 400px;
        background: var(--color-grey-10);
        padding: 16px;
        border-radius: 8px;
    }

    .code-item {
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .code-number {
        font-size: 12px;
        color: var(--color-grey-50);
        min-width: 20px;
    }

    .code-item code {
        font-family: monospace;
        font-size: 14px;
        color: var(--color-grey-100);
    }

    .copy-codes-btn {
        width: 100%;
        max-width: 400px;
    }

    .confirm-checkbox {
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .confirm-checkbox label {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 14px;
        color: var(--color-grey-80);
        cursor: pointer;
    }

    .confirm-checkbox input[type="checkbox"] {
        width: 18px;
        height: 18px;
        cursor: pointer;
    }

    /* Success State */
    .success-icon {
        width: 64px;
        height: 64px;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 50%;
        background: var(--color-success-light);
    }

    .success-icon .icon {
        font-size: 32px;
        color: var(--color-success);
    }

    /* Buttons */
    .btn-primary,
    .btn-secondary {
        padding: 12px 24px;
        border: none;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.2s;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
    }

    .btn-primary {
        background: var(--color-primary);
        color: white;
    }

    .btn-primary:hover:not(:disabled) {
        background: var(--color-primary-dark);
    }

    .btn-primary:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .btn-secondary {
        background: var(--color-grey-20);
        color: var(--color-grey-100);
    }

    .btn-secondary:hover {
        background: var(--color-grey-30);
    }

    .btn-cancel {
        padding: 12px 24px;
        background: transparent;
        border: 1px solid var(--color-grey-40);
        border-radius: 8px;
        font-size: 14px;
        color: var(--color-grey-70);
        cursor: pointer;
        transition: all 0.2s;
        margin-top: 8px;
    }

    .btn-cancel:hover {
        background: var(--color-grey-10);
        border-color: var(--color-grey-50);
        color: var(--color-grey-90);
    }

    /* Messages */
    .error-message {
        color: var(--color-danger);
        font-size: 13px;
        text-align: center;
    }

    .success-message {
        color: var(--color-success);
        font-size: 14px;
        text-align: center;
        padding: 12px;
        background: var(--color-success-light);
        border-radius: 8px;
    }

    /* Help Link */
    .help-link {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 4px;
        font-size: 13px;
        color: var(--color-grey-60);
    }

    .help-link a {
        color: var(--color-primary);
        text-decoration: none;
    }

    .help-link a:hover {
        text-decoration: underline;
    }

    /* Loading */
    .loading-container {
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 40px;
    }

    .loading-spinner {
        width: 40px;
        height: 40px;
        border: 3px solid var(--color-grey-30);
        border-top-color: var(--color-primary);
        border-radius: 50%;
        animation: spin 1s linear infinite;
    }

    .loading-spinner-small {
        width: 16px;
        height: 16px;
        border: 2px solid rgba(255, 255, 255, 0.3);
        border-top-color: white;
        border-radius: 50%;
        animation: spin 1s linear infinite;
    }

    @keyframes spin {
        to {
            transform: rotate(360deg);
        }
    }
</style>

