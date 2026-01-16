<!--
Delete Account Settings - Component for deleting user account with preview, confirmation, and authentication
Uses SecurityAuth component for passkey/2FA verification.
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { text, activeChatStore } from '@repo/ui';
    import { getApiEndpoint, apiEndpoints } from '../../../config/api';
    import { authStore } from '../../../stores/authStore';
    import { panelState } from '../../../stores/panelStateStore';
    import { settingsMenuVisible } from '../../Settings.svelte';
    import { phasedSyncState } from '../../../stores/phasedSyncStateStore';
    import { isInSignupProcess, currentSignupStep } from '../../../stores/signupState';
    import Toggle from '../../Toggle.svelte';
    import SecurityAuth from '../security/SecurityAuth.svelte';

    let { accountId = null }: { accountId?: string | null } = $props();

    // ========================================================================
    // STATE
    // ========================================================================
    
    // Account status state
    let canDeleteWithoutLogin = $state(false);
    let isCheckingStatus = $state(false);
    let deletionScheduled = $state(false);
    
    // Preview data
    let previewData = $state<{
        total_credits: number;
        refundable_credits: number;
        credits_from_gift_cards: number;
        has_refundable_credits: boolean;
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

    // UI state
    let isLoadingPreview = $state(false);
    let isLoadingDeletion = $state(false);
    let errorMessage: string | null = $state(null);
    let successMessage: string | null = $state(null);

    // Auth state
    let hasPasskey = $state(false);
    let has2FA = $state(false);
    let showAuthModal = $state(false);

    // Confirmation
    let confirmDataDeletion = $state(false);

    // ========================================================================
    // LIFECYCLE
    // ========================================================================

    onMount(async () => {
        if ($authStore.isAuthenticated) {
            await fetchPreview();
            await fetchAuthMethods();
        } else if (accountId) {
            await checkAccountStatus();
        }
    });

    async function checkAccountStatus() {
        if (!accountId) return;
        isCheckingStatus = true;
        errorMessage = null;
        try {
            const response = await fetch(getApiEndpoint(`/v1/settings/account-status/${accountId}`), {
                method: 'GET',
                headers: { 'Content-Type': 'application/json' }
            });
            if (response.ok) {
                const data = await response.json();
                canDeleteWithoutLogin = data.can_delete_without_login;
            } else {
                errorMessage = $text('settings.account.delete_account_status_error.text');
            }
        } catch (error) {
            console.error('[SettingsDeleteAccount] Error checking status:', error);
            errorMessage = 'Failed to check account status';
        } finally {
            isCheckingStatus = false;
        }
    }

    async function handleDeletionSuccess(customMessage?: string) {
        successMessage = customMessage || $text('settings.account.delete_account_success.text');
        deletionScheduled = true;
        
        setTimeout(async () => {
            // Close settings panel
            settingsMenuVisible.set(false);
            panelState.closeSettings();
            
            // Close signup flow if user was in signup process
            isInSignupProcess.set(false);
            currentSignupStep.set('');
            
            // Notify other components that user is logging out
            window.dispatchEvent(new CustomEvent('userLoggingOut'));
            
            await new Promise(resolve => setTimeout(resolve, 50));
            activeChatStore.setActiveChat('demo-welcome');
            
            // Reset URL to demo welcome page
            if (typeof window !== 'undefined') {
                window.location.hash = 'chat-id=demo-welcome';
            }
            
            phasedSyncState.markSyncCompleted();
            await new Promise(resolve => setTimeout(resolve, 200));
            
            // For authenticated users, perform full logout
            // For guest users, the above cleanup is sufficient
            if ($authStore.isAuthenticated) {
                authStore.logout();
            }
            
            console.log('[SettingsDeleteAccount] Account deleted, session cleaned up, signup flow closed');
        }, 2000);
    }

    async function handleDeleteUncompletedAccount() {
        if (!accountId || !canDeleteWithoutLogin) return;
        isLoadingDeletion = true;
        errorMessage = null;
        try {
            const response = await fetch(getApiEndpoint(`/v1/settings/delete-uncompleted-account/${accountId}`), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            if (response.ok) {
                await handleDeletionSuccess();
            } else {
                const data = await response.json();
                errorMessage = data.detail || 'Failed to delete account';
            }
        } catch (error) {
            console.error('[SettingsDeleteAccount] Error deleting uncompleted account:', error);
            errorMessage = 'An error occurred during account deletion';
        } finally {
            isLoadingDeletion = false;
        }
    }

    // ========================================================================
    // DATA FETCHING
    // ========================================================================

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

            previewData = await response.json();
        } catch (error) {
            console.error('[SettingsDeleteAccount] Error fetching preview:', error);
            errorMessage = error instanceof Error ? error.message : 'Failed to load deletion preview';
        } finally {
            isLoadingPreview = false;
        }
    }

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
            }
        } catch (error) {
            console.error('[SettingsDeleteAccount] Error fetching auth methods:', error);
        }
    }

    // ========================================================================
    // HELPERS
    // ========================================================================

    function formatCredits(credits: number): string {
        return new Intl.NumberFormat('en-US').format(credits);
    }

    function formatCurrency(cents: number, currency: string): string {
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: currency.toUpperCase()
        }).format(cents / 100);
    }

    let canProceed = $derived(!!previewData && confirmDataDeletion);
    let hasAnyAuthMethod = $derived(hasPasskey || has2FA);

    // ========================================================================
    // ACTIONS
    // ========================================================================

    function startDeletion() {
        if (!canProceed) return;
        
        if (!hasAnyAuthMethod) {
            errorMessage = $text('settings.account.delete_account_no_auth_method.text');
            return;
        }

        errorMessage = null;
        showAuthModal = true;
    }

    async function handleAuthSuccess(data: { method: 'passkey' | 'password' | '2fa'; credentialId?: string; tfaCode?: string }) {
        showAuthModal = false;
        
        // Determine auth method and code based on the authentication type used
        const authMethod = data.method === 'passkey' ? 'passkey' : '2fa_otp';
        // Use credentialId for passkey, tfaCode for 2FA
        const authCode = data.method === 'passkey' ? (data.credentialId || '') : (data.tfaCode || '');
        
        console.log(`[SettingsDeleteAccount] Auth success - method: ${authMethod}, code present: ${!!authCode}`);
        
        await submitDeletionRequest(authMethod, authCode);
    }

    function handleAuthFailed(message: string) {
        showAuthModal = false;
        errorMessage = message;
    }

    function handleAuthCancel() {
        showAuthModal = false;
    }

    async function submitDeletionRequest(authMethod: string, authCode: string) {
        isLoadingDeletion = true;
        errorMessage = null;

        try {
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
                await handleDeletionSuccess(data.message);
            } else {
                throw new Error(data.message || 'Account deletion failed');
            }
        } catch (error) {
            console.error('[SettingsDeleteAccount] Deletion error:', error);
            errorMessage = error instanceof Error ? error.message : 'Failed to delete account';
        } finally {
            isLoadingDeletion = false;
        }
    }
</script>

<div class="delete-account-container">
    {#if isCheckingStatus || isLoadingPreview}
        <div class="loading-message">
            <p>{$text('settings.account.delete_account_loading_preview.text')}</p>
        </div>
    {:else if !$authStore.isAuthenticated && canDeleteWithoutLogin}
        <div class="warning-box">
            <h3>{$text('settings.account.delete_account_uncompleted_title.text')}</h3>
            <p>{$text('settings.account.delete_account_uncompleted_message.text')}</p>
        </div>

        {#if errorMessage}
            <div class="error-message">{errorMessage}</div>
        {/if}

        {#if successMessage}
            <div class="success-message">{successMessage}</div>
        {/if}

        {#if !deletionScheduled}
            <div class="action-buttons">
                <button
                    class="delete-button"
                    onclick={handleDeleteUncompletedAccount}
                    disabled={isLoadingDeletion}
                >
                    {#if isLoadingDeletion}
                        {$text('settings.account.delete_account_deleting.text')}
                    {:else}
                        {$text('settings.account.delete_account_delete_button.text')}
                    {/if}
                </button>
            </div>
        {/if}
    {:else if !$authStore.isAuthenticated && !canDeleteWithoutLogin && accountId}
        <div class="info-box">
            <h3>{$text('settings.account.delete_account_login_required_title.text')}</h3>
            <p>{$text('settings.account.delete_account_login_required_message.text')}</p>
        </div>
        <div class="action-buttons">
            <button class="retry-button" onclick={() => window.location.hash = 'login'}>
                {$text('login.login.text')}
            </button>
        </div>
    {:else if previewData}
        {#if previewData.has_refundable_credits}
            <div class="info-box">
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
                </ul>
            </div>
        {/if}

        {#if previewData.credits_from_gift_cards > 0}
            <div class="info-box">
                <h3>{$text('settings.account.delete_account_gift_card_credits_title.text')}</h3>
                <p>{$text('settings.account.delete_account_gift_card_credits_message.text').replace('{count}', formatCredits(previewData.credits_from_gift_cards))}</p>
            </div>
        {/if}

        <div class="warning-box">
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

        {#if errorMessage}
            <div class="error-message">{errorMessage}</div>
        {/if}

        {#if successMessage}
            <div class="success-message">{successMessage}</div>
        {/if}

        <div class="action-buttons">
            <button
                class="delete-button"
                onclick={startDeletion}
                disabled={!canProceed || isLoadingDeletion}
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

    .warning-box, .info-box {
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

    .warning-box h3, .info-box h3 {
        font-size: 16px;
        font-weight: 600;
        margin-bottom: 12px;
        color: var(--color-grey-80);
    }

    .warning-box p, .info-box p {
        margin-bottom: 16px;
        color: var(--color-grey-70);
        line-height: 1.5;
        font-size: 14px;
    }

    .toggle-label {
        display: flex;
        align-items: center;
        gap: 12px;
    }

    .toggle-label span {
        flex: 1;
        color: var(--color-grey-80);
        font-size: 14px;
    }

    .refund-details {
        list-style: none;
        padding: 0;
        margin: 16px 0 0 0;
    }

    .refund-details li {
        padding: 8px 0;
        border-bottom: 1px solid var(--color-grey-20);
        font-size: 14px;
    }

    .refund-details li:last-child {
        border-bottom: none;
    }

    .error-message {
        padding: 12px 16px;
        background: var(--color-danger-light);
        border: 1px solid var(--color-danger);
        border-radius: 8px;
        color: var(--color-danger);
        margin-bottom: 16px;
        font-size: 14px;
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
        margin-top: 24px;
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
    }

    .delete-button:hover:not(:disabled) {
        background: var(--color-danger-dark);
    }

    .delete-button:disabled {
        opacity: 0.4;
        cursor: not-allowed;
        background: var(--color-grey-50);
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
</style>
