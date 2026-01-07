<!--
Delete Account Settings - Component for deleting user account with preview, confirmation, and authentication
Uses the shared SecurityAuth component for unified authentication (passkey, 2FA OTP).
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { text, activeChatStore } from '@repo/ui';
    import { getApiEndpoint, apiEndpoints } from '../../../config/api';
    import { authStore } from '../../../stores/authStore';
    import { panelState } from '../../../stores/panelStateStore';
    import { settingsMenuVisible } from '../../Settings.svelte';
    import { phasedSyncState } from '../../../stores/phasedSyncStateStore';
    import Toggle from '../../Toggle.svelte';
    import SecurityAuth from '../security/SecurityAuth.svelte';

    // ========================================================================
    // STATE - Preview Data
    // ========================================================================
    
    // Policy: All unused credits are refunded EXCEPT credits from gift card redemptions
    let previewData = $state<{
        total_credits: number;  // User's current total credit balance
        refundable_credits: number;  // Credits that will be refunded (excludes gift card credits)
        credits_from_gift_cards: number;  // Credits from gift card redemptions (not refundable)
        has_refundable_credits: boolean;  // Whether there are credits to refund
        auto_refunds: {
            total_refund_amount_cents: number;
            total_refund_currency: string;
            eligible_invoices: Array<{
                invoice_id: string;
                order_id: string;
                date: string;
                total_credits: number;
                amount_cents: number;
                currency: string;
            }>;
            gift_card_purchases: Array<{
                gift_card_code: string;
                credits_value: number;
                purchased_at: string;
                is_redeemed: boolean;
            }>;
        };
    } | null>(null);

    // ========================================================================
    // STATE - UI
    // ========================================================================
    
    let isLoadingPreview = $state(false);
    let isLoadingDeletion = $state(false);
    let errorMessage: string | null = $state(null);
    let successMessage: string | null = $state(null);

    // ========================================================================
    // STATE - Authentication
    // ========================================================================
    
    /** User authentication methods - needed for SecurityAuth component */
    /** Note: We only use passkey and 2FA for account deletion (not password) */
    let hasPasskey = $state(false);
    let has2FA = $state(false);
    
    /** Whether the SecurityAuth modal is shown */
    let showAuthModal = $state(false);

    // ========================================================================
    // STATE - Confirmations
    // ========================================================================
    
    // Note: No credits loss confirmation needed - all unused credits are refunded (except gift card credits)
    let confirmDataDeletion = $state(false);

    // ========================================================================
    // LIFECYCLE
    // ========================================================================

    /**
     * Fetch preview data and auth methods when component mounts
     */
    onMount(async () => {
        await fetchPreview();
        await fetchAuthMethods();
    });

    // ========================================================================
    // DATA FETCHING
    // ========================================================================

    /**
     * Fetch preview data about what will happen during account deletion
     */
    async function fetchPreview() {
        isLoadingPreview = true;
        errorMessage = null;

        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.settings.deleteAccountPreview), {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include'
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Failed to fetch deletion preview');
            }

            const data = await response.json();
            previewData = data;
        } catch (error) {
            console.error('[SettingsDeleteAccount] Error fetching deletion preview:', error);
            errorMessage = error instanceof Error ? error.message : 'Failed to load deletion preview';
        } finally {
            isLoadingPreview = false;
        }
    }

    /**
     * Fetch user authentication methods (passkey, 2FA)
     * Both are supported for account deletion authentication via SecurityAuth.
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
                has2FA = data.has_2fa || false;
                console.log('[SettingsDeleteAccount] Auth methods fetched:', { hasPasskey, has2FA });
            }
        } catch (error) {
            console.error('[SettingsDeleteAccount] Error fetching auth methods:', error);
        }
    }

    // ========================================================================
    // COMPUTED
    // ========================================================================

    /**
     * Format credits for display
     */
    function formatCredits(credits: number): string {
        return new Intl.NumberFormat('en-US').format(credits);
    }

    /**
     * Format currency amount for display
     */
    function formatCurrency(cents: number, currency: string): string {
        const amount = cents / 100;
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: currency.toUpperCase()
        }).format(amount);
    }

    /**
     * Check if deletion can proceed (data deletion confirmation must be toggled on)
     * Note: No credits loss confirmation needed - all unused credits are refunded (except gift card credits)
     */
    let canProceed = $derived.by(() => {
        const hasPreviewData = !!previewData;
        const hasConfirmation = confirmDataDeletion;
        const result = hasPreviewData && hasConfirmation;
        return result;
    });
    
    /**
     * Check if user has any authentication method available
     */
    let hasAnyAuthMethod = $derived(hasPasskey || has2FA);

    // ========================================================================
    // AUTHENTICATION FLOW
    // ========================================================================

    /**
     * Start deletion process - opens SecurityAuth modal for authentication
     */
    function startDeletion() {
        // CRITICAL: Prevent deletion if confirmation toggle is not checked
        if (!confirmDataDeletion) {
            console.log('[SettingsDeleteAccount] Deletion blocked - confirmation toggle not checked');
            return;
        }
        
        if (!canProceed) {
            console.log('[SettingsDeleteAccount] Deletion blocked - canProceed is false');
            return;
        }
        
        // Check if user has any authentication method set up
        if (!hasAnyAuthMethod) {
            errorMessage = $text('settings.account.delete_account_no_auth_method.text');
            console.log('[SettingsDeleteAccount] Deletion blocked - no auth method available');
            return;
        }

        // Show the unified SecurityAuth modal
        console.log('[SettingsDeleteAccount] Opening SecurityAuth modal');
        errorMessage = null;
        showAuthModal = true;
    }

    /**
     * Called when authentication succeeds via SecurityAuth
     * Proceeds to submit the deletion request with auth data
     */
    async function handleAuthSuccess(data: { method: 'passkey' | 'password' | '2fa'; credentialId?: string }) {
        console.log('[SettingsDeleteAccount] Authentication successful:', data.method);
        showAuthModal = false;
        
        // Store auth data and submit deletion
        // Map 'password' auth method to '2fa' for backend (backend only accepts passkey or 2fa_otp)
        // Note: Password auth alone is not sufficient for account deletion - 
        // if password auth triggers 2FA, SecurityAuth will handle that
        const authMethod = data.method === 'passkey' ? 'passkey' : '2fa_otp';
        const authCode = data.credentialId || '';  // For 2FA, the code was already verified by SecurityAuth
        
        await submitDeletionRequest(authMethod, authCode);
    }

    /**
     * Called when authentication fails via SecurityAuth
     */
    function handleAuthFailed(message: string) {
        console.log('[SettingsDeleteAccount] Authentication failed:', message);
        showAuthModal = false;
        errorMessage = message || $text('settings.account.delete_account_auth_failed.text');
    }

    /**
     * Called when user cancels authentication via SecurityAuth
     */
    function handleAuthCancel() {
        console.log('[SettingsDeleteAccount] Authentication cancelled');
        showAuthModal = false;
    }

    // ========================================================================
    // DELETION REQUEST
    // ========================================================================

    /**
     * Submit the account deletion request to the server
     * @param authMethod - 'passkey' or '2fa_otp'
     * @param authCode - credential_id for passkey, empty for 2FA (already verified)
     */
    async function submitDeletionRequest(authMethod: string, authCode: string) {
        isLoadingDeletion = true;
        errorMessage = null;

        try {
            // Submit deletion request
            // Note: All unused credits are automatically refunded (except gift card credits)
            const response = await fetch(getApiEndpoint(apiEndpoints.settings.deleteAccount), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    confirm_data_deletion: confirmDataDeletion,
                    auth_method: authMethod,
                    auth_code: authCode
                })
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Failed to delete account');
            }

            const data = await response.json();
            if (data.success) {
                successMessage = data.message || $text('settings.account.delete_account_success.text');
                
                // Perform logout actions after a short delay to show success message
                setTimeout(async () => {
                    // CRITICAL: Close settings menu first
                    // This ensures the menu closes before logout clears state
                    settingsMenuVisible.set(false);
                    panelState.closeSettings();
                    console.debug('[SettingsDeleteAccount] Closed settings menu before logout');
                    
                    // CRITICAL: Dispatch logout event to clear user chats and load demo chat
                    // This must happen before database deletion to ensure UI updates right away
                    console.debug('[SettingsDeleteAccount] Dispatching userLoggingOut event to clear chats and load demo');
                    window.dispatchEvent(new CustomEvent('userLoggingOut'));
                    
                    // CRITICAL: Force ActiveChat to load demo-welcome by setting activeChatStore directly
                    // This ensures demo-welcome loads even if event handlers have timing issues
                    // Small delay to ensure auth state changes are processed first
                    await new Promise(resolve => setTimeout(resolve, 50));
                    activeChatStore.setActiveChat('demo-welcome');
                    console.debug('[SettingsDeleteAccount] Directly set activeChatStore to demo-welcome during account deletion');
                    
                    // CRITICAL: Ensure URL hash is set to demo-welcome
                    if (typeof window !== 'undefined') {
                        window.location.hash = 'chat-id=demo-welcome';
                        console.debug('[SettingsDeleteAccount] Set URL hash to demo-welcome during account deletion');
                    }
                    
                    // CRITICAL: Mark phased sync as completed for non-authenticated users
                    // This prevents "Loading chats..." from showing after logout
                    phasedSyncState.markSyncCompleted();
                    console.debug('[SettingsDeleteAccount] Marked phased sync as completed after account deletion (non-auth user)');
                    
                    // Small delay to allow settings menu to close visually and state to clear
                    await new Promise(resolve => setTimeout(resolve, 200));
                    
                    // Now perform the actual logout
                    authStore.logout();
                }, 2000);
            } else {
                throw new Error(data.message || 'Account deletion failed');
            }
        } catch (error) {
            console.error('[SettingsDeleteAccount] Error deleting account:', error);
            errorMessage = error instanceof Error ? error.message : 'Failed to delete account';
        } finally {
            isLoadingDeletion = false;
        }
    }

</script>

<div class="delete-account-container">
    {#if isLoadingPreview}
        <div class="loading-message">
            <p>{$text('settings.account.delete_account_loading_preview.text')}</p>
        </div>
    {:else if previewData}
        <!-- Refund Information - All unused credits are refunded (except gift card credits) -->
        {#if previewData.has_refundable_credits}
            <div class="info-box refund-info">
                <h3>{$text('settings.account.delete_account_auto_refund_title.text')}</h3>
                <p>{$text('settings.account.delete_account_refund_all_description.text')}</p>
                <ul class="refund-details">
                    <li>
                        <strong>{$text('settings.account.delete_account_auto_refund_total_refund.text')}:</strong>
                        {formatCurrency(previewData.auto_refunds.total_refund_amount_cents, previewData.auto_refunds.total_refund_currency)}
                    </li>
                    <li>
                        <strong>{$text('settings.account.delete_account_refundable_credits.text')}:</strong>
                        {formatCredits(previewData.refundable_credits)}
                    </li>
                    {#if previewData.auto_refunds.eligible_invoices.length > 0}
                        <li>
                            <strong>{$text('settings.account.delete_account_auto_refund_eligible_invoices.text')}:</strong>
                            {previewData.auto_refunds.eligible_invoices.length}
                        </li>
                    {/if}
                </ul>
            </div>
        {/if}

        <!-- Gift Card Credits Notice - These credits are not refundable -->
        {#if previewData.credits_from_gift_cards > 0}
            <div class="info-box gift-card-notice">
                <h3>{$text('settings.account.delete_account_gift_card_credits_title.text')}</h3>
                <p>
                    {$text('settings.account.delete_account_gift_card_credits_message.text').replace('{count}', formatCredits(previewData.credits_from_gift_cards))}
                </p>
            </div>
        {/if}

        <!-- Data Deletion Warning with Toggle -->
        <div class="warning-box data-warning">
            <h3>{$text('settings.account.delete_account_data_deletion_warning_title.text')}</h3>
            <p>{$text('settings.account.delete_account_data_deletion_warning_message.text')}</p>
            <div class="toggle-label">
                <Toggle 
                    bind:checked={confirmDataDeletion}
                    disabled={isLoadingDeletion}
                    ariaLabel={$text('settings.account.delete_account_data_deletion_warning_confirm.text')}
                />
                <span>{$text('settings.account.delete_account_data_deletion_warning_confirm.text')}</span>
            </div>
        </div>

        <!-- Error Message -->
        {#if errorMessage}
            <div class="error-message">{errorMessage}</div>
        {/if}

        <!-- Success Message -->
        {#if successMessage}
            <div class="success-message">{successMessage}</div>
        {/if}

        <!-- Delete Button - disabled when confirmation toggle is off or deletion is in progress -->
        <div class="action-buttons">
            <button
                class="delete-button"
                class:disabled={!confirmDataDeletion || isLoadingDeletion}
                onclick={startDeletion}
                disabled={!confirmDataDeletion || isLoadingDeletion}
            >
                {#if isLoadingDeletion}
                    {$text('settings.account.delete_account_deleting.text')}
                {:else}
                    {$text('settings.account.delete_account_delete_button.text')}
                {/if}
            </button>
        </div>
    {:else if errorMessage}
        <div class="error-message">{errorMessage}</div>
        <button class="retry-button" onclick={fetchPreview}>
            {$text('settings.account.delete_account_retry.text')}
        </button>
    {/if}
</div>

<!-- SecurityAuth Modal - Unified authentication component (passkey or 2FA OTP only) -->
<!-- Note: We pass hasPassword={false} to skip password auth - account deletion only accepts passkey or 2FA OTP -->
{#if showAuthModal}
    <SecurityAuth
        {hasPasskey}
        hasPassword={false}
        has2FA={has2FA}
        title={$text('settings.account.delete_account_auth_title.text')}
        description={$text('settings.account.delete_account_auth_description.text')}
        autoStart={true}
        onSuccess={handleAuthSuccess}
        onFailed={handleAuthFailed}
        onCancel={handleAuthCancel}
    />
{/if}

<style>
    .loading-message {
        text-align: center;
        padding: 40px;
        color: var(--color-grey-60);
    }

    .warning-box,
    .info-box {
        padding: 20px;
        border-radius: 8px;
        margin-bottom: 20px;
    }

    .warning-box {
        background: var(--color-warning-light);
        border: 1px solid var(--color-warning);
    }

    .info-box {
        background: var(--color-info-light);
        border: 1px solid var(--color-info);
    }

    .warning-box h3,
    .info-box h3 {
        font-size: 18px;
        font-weight: 600;
        margin-bottom: 12px;
        color: var(--color-grey-80);
    }

    .warning-box p,
    .info-box p {
        margin-bottom: 16px;
        color: var(--color-grey-70);
        line-height: 1.5;
    }

    .toggle-label {
        display: flex;
        align-items: center;
        gap: 12px;
        user-select: none;
    }

    .toggle-label span {
        flex: 1;
        color: var(--color-grey-80);
        line-height: 1.5;
    }

    .refund-details {
        list-style: none;
        padding: 0;
        margin: 16px 0 0 0;
    }

    .refund-details li {
        padding: 8px 0;
        border-bottom: 1px solid var(--color-grey-20);
    }

    .refund-details li:last-child {
        border-bottom: none;
    }

    .refund-details strong {
        color: var(--color-grey-80);
    }

    .error-message {
        padding: 16px;
        background: var(--color-danger-light);
        border: 1px solid var(--color-danger);
        border-radius: 8px;
        color: var(--color-danger);
        margin-bottom: 20px;
    }

    .success-message {
        padding: 16px;
        background: var(--color-success-light);
        border: 1px solid var(--color-success);
        border-radius: 8px;
        color: var(--color-success);
        margin-bottom: 20px;
    }

    .action-buttons {
        margin-top: 32px;
    }

    .delete-button {
        width: 100%;
        padding: 14px 24px;
        background: var(--color-danger);
        color: var(--color-grey-100);
        border: none;
        border-radius: 8px;
        font-size: 16px;
        font-weight: 600;
        cursor: pointer;
        transition: background 0.2s, opacity 0.2s;
    }

    .delete-button:hover:not(:disabled) {
        background: var(--color-danger-dark);
    }

    .delete-button:disabled,
    .delete-button.disabled {
        opacity: 0.4 !important;
        cursor: not-allowed !important;
        background: var(--color-grey-50) !important;
        pointer-events: none;
    }

    .retry-button {
        padding: 12px 24px;
        background: var(--color-primary);
        color: var(--color-grey-100);
        border: none;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 600;
        cursor: pointer;
        margin-top: 16px;
    }

    .retry-button:hover {
        background: var(--color-primary-dark);
    }
</style>
