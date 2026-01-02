<!--
Delete Account Settings - Component for deleting user account with preview, confirmation, and authentication
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { text, activeChatStore } from '@repo/ui';
    import { getApiEndpoint, apiEndpoints } from '../../../config/api';
    import { authStore } from '../../../stores/authStore';
    import * as cryptoService from '../../../services/cryptoService';
    import { getSessionId } from '../../../utils/sessionId';
    import { panelState } from '../../../stores/panelStateStore';
    import { settingsMenuVisible } from '../../Settings.svelte';
    import { phasedSyncState } from '../../../stores/phasedSyncStateStore';
    import Toggle from '../../Toggle.svelte';

    // State for preview data
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

    // State for loading and errors
    let isLoadingPreview = $state(false);
    let isLoadingDeletion = $state(false);
    let errorMessage: string | null = $state(null);
    let successMessage: string | null = $state(null);

    // State for user authentication methods
    let hasPasskey = $state(false);

    // State for confirmations
    // Note: No credits loss confirmation needed - all unused credits are refunded (except gift card credits)
    let confirmDataDeletion = $state(false);

    /**
     * Fetch preview data when component mounts
     */
    onMount(async () => {
        await fetchPreview();
        await fetchAuthMethods();
    });

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
            console.error('Error fetching deletion preview:', error);
            errorMessage = error instanceof Error ? error.message : 'Failed to load deletion preview';
        } finally {
            isLoadingPreview = false;
        }
    }

    /**
     * Fetch user authentication methods (passkey, 2FA)
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
                hasPasskey = data.has_passkey;
                // Note: 2FA authentication for account deletion is not yet supported
            }
        } catch (error) {
            console.error('Error fetching auth methods:', error);
        }
    }

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
     * Using $derived.by() to compute the boolean value from a function
     */
    let canProceed = $derived.by(() => {
        const hasPreviewData = !!previewData;
        const hasConfirmation = confirmDataDeletion;
        const result = hasPreviewData && hasConfirmation;
        console.log('[SettingsDeleteAccount] canProceed check:', { hasPreviewData, hasConfirmation, result });
        return result;
    });

    /**
     * Start deletion process - triggers passkey authentication inline
     * Note: Currently only passkey authentication is supported for account deletion.
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
        
        // Check if user has passkey set up (required for account deletion)
        if (!hasPasskey) {
            errorMessage = 'Passkey authentication required. Please set up a passkey first in Security settings.';
            return;
        }

        // Directly call handleDeleteAccount which handles passkey auth internally
        handleDeleteAccount();
    }

    /**
     * Handle passkey authentication for deletion
     * This is similar to PaymentAuth but we need to capture the credential_id
     */
    async function handlePasskeyAuthForDeletion(): Promise<string | null> {
        try {
            // Get user email for passkey authentication
            const email = await cryptoService.getEmailDecryptedWithMasterKey();
            if (!email) {
                throw new Error('Email not available');
            }

            // Hash email for lookup
            const emailHash = await cryptoService.hashEmail(email);

            // Initiate passkey assertion
            const initiateResponse = await fetch(getApiEndpoint(apiEndpoints.auth.passkey_assertion_initiate), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    hashed_email: emailHash,
                    session_id: getSessionId()
                })
            });

            if (!initiateResponse.ok) {
                throw new Error('Failed to initiate passkey authentication');
            }

            const initiateData = await initiateResponse.json();
            if (!initiateData.success) {
                throw new Error(initiateData.message || 'Passkey authentication failed');
            }

            // Convert base64url to ArrayBuffer
            function base64UrlToArrayBuffer(base64url: string): ArrayBuffer {
                let base64 = base64url.replace(/-/g, '+').replace(/_/g, '/');
                while (base64.length % 4) {
                    base64 += '=';
                }
                const binary = window.atob(base64);
                const bytes = new Uint8Array(binary.length);
                for (let i = 0; i < binary.length; i++) {
                    bytes[i] = binary.charCodeAt(i);
                }
                return bytes.buffer;
            }

            if (!initiateData.challenge || !initiateData.rp?.id) {
                throw new Error('Invalid passkey challenge response');
            }

            const challenge = base64UrlToArrayBuffer(initiateData.challenge);
            const prfEvalFirst = initiateData.extensions?.prf?.eval?.first || initiateData.challenge;
            const prfEvalFirstBuffer = base64UrlToArrayBuffer(prfEvalFirst);

            const publicKeyCredentialRequestOptions = {
                challenge: challenge,
                rpId: initiateData.rp.id,
                timeout: initiateData.timeout,
                userVerification: initiateData.userVerification as 'required' | 'preferred' | 'discouraged',
                allowCredentials: initiateData.allowCredentials?.length > 0
                    ? initiateData.allowCredentials.map((cred: { type: string; id: string; transports?: string[] }) => ({
                        type: 'public-key' as const,
                        id: base64UrlToArrayBuffer(cred.id),
                        transports: cred.transports as ('usb' | 'nfc' | 'ble' | 'internal' | 'hybrid')[]
                    }))
                    : [],
                extensions: {
                    prf: {
                        eval: {
                            first: prfEvalFirstBuffer
                        }
                    }
                }
            };

            // Request passkey authentication
            const credential = await navigator.credentials.get({
                publicKey: publicKeyCredentialRequestOptions
            }) as PublicKeyCredential;

            if (!credential) {
                throw new Error('Passkey authentication cancelled');
            }

            // Extract credential ID
            const uint8ArrayToBase64 = (arr: Uint8Array) => {
                return btoa(String.fromCharCode(...arr))
                    .replace(/\+/g, '-')
                    .replace(/\//g, '_')
                    .replace(/=/g, '');
            };

            const credentialId = uint8ArrayToBase64(new Uint8Array(credential.rawId));

            // Verify passkey assertion
            const verifyResponse = await fetch(getApiEndpoint(apiEndpoints.auth.passkey_assertion_verify), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    credential_id: credentialId,
                    assertion_response: {
                        authenticatorData: uint8ArrayToBase64(new Uint8Array((credential.response as AuthenticatorAssertionResponse).authenticatorData)),
                        clientDataJSON: uint8ArrayToBase64(new Uint8Array((credential.response as AuthenticatorAssertionResponse).clientDataJSON)),
                        signature: uint8ArrayToBase64(new Uint8Array((credential.response as AuthenticatorAssertionResponse).signature)),
                        userHandle: (credential.response as AuthenticatorAssertionResponse).userHandle 
                            ? uint8ArrayToBase64(new Uint8Array((credential.response as AuthenticatorAssertionResponse).userHandle!))
                            : null
                    },
                    client_data_json: uint8ArrayToBase64(new Uint8Array((credential.response as AuthenticatorAssertionResponse).clientDataJSON)),
                    authenticator_data: uint8ArrayToBase64(new Uint8Array((credential.response as AuthenticatorAssertionResponse).authenticatorData)),
                    session_id: getSessionId()
                })
            });

            if (!verifyResponse.ok) {
                const errorData = await verifyResponse.json();
                throw new Error(errorData.message || 'Passkey verification failed');
            }

            const verifyData = await verifyResponse.json();
            if (!verifyData.success) {
                throw new Error(verifyData.message || 'Passkey verification failed');
            }

            return credentialId;
        } catch (error) {
            console.error('Passkey authentication error:', error);
            throw error;
        }
    }


    /**
     * Submit account deletion request
     */
    async function handleDeleteAccount() {
        if (!canProceed) return;

        isLoadingDeletion = true;
        errorMessage = null;

        try {
            // Perform passkey authentication
            // Note: Currently only passkey is supported. 2FA support can be added later.
            if (!hasPasskey) {
                throw new Error('Passkey authentication required. Please set up a passkey first.');
            }

            const credentialId = await handlePasskeyAuthForDeletion();
            if (!credentialId) {
                throw new Error('Passkey authentication failed');
            }

            // For passkey, we use the credential_id as the auth code
            const authCode = credentialId;
            const authMethod = 'passkey';

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
                successMessage = data.message || 'Account deletion initiated successfully';
                
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
            console.error('Error deleting account:', error);
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
        color: white;
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
        color: white;
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


