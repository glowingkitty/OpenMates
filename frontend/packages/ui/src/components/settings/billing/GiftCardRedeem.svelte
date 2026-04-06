<!--
Gift Card Redeem - Component for redeeming gift card codes.
Supports an optional initialCode prop to pre-fill the input field (used by the
/#gift-card=CODE deep link in +page.svelte). When no initialCode is supplied the
component also checks sessionStorage for a 'pending_gift_card_code' value so the
code survives across the signup flow.

Tests: (none yet)
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { apiEndpoints, getApiEndpoint } from '../../../config/api';
    import { updateProfile } from '../../../stores/userProfile';
    import * as cryptoService from '../../../services/cryptoService';

    const dispatch = createEventDispatcher();

    // Props to control behavior in different contexts
    let {
        hideSuccessMessage = false, // When true, don't show success message (e.g., during signup)
        initialCode = ''            // Optional pre-filled code (e.g., from /#gift-card=CODE deep link)
    }: {
        hideSuccessMessage?: boolean;
        initialCode?: string;
    } = $props();

    let giftCardCode = $state('');
    let isRedeeming = $state(false);
    let errorMessage: string | null = $state(null);
    let successMessage: string | null = $state(null);

    // Pre-fill from prop or sessionStorage on mount
    $effect(() => {
        if (initialCode) {
            giftCardCode = initialCode.toUpperCase();
        } else if (typeof window !== 'undefined') {
            const pending = sessionStorage.getItem('pending_gift_card_code');
            if (pending) {
                giftCardCode = pending.toUpperCase();
                console.debug('[GiftCardRedeem] Pre-filled code from sessionStorage');
            }
        }
    });

    /**
     * Redeem the gift card code
     */
    async function redeemCode() {
        // Validate input
        if (!giftCardCode.trim()) {
            errorMessage = $text('settings.billing.gift_card.error.invalid');
            return;
        }

        // Clear previous messages
        errorMessage = null;
        successMessage = null;
        isRedeeming = true;

        try {
            const normalizedCode = giftCardCode.trim().toUpperCase();

            // Include the client-held email encryption key when available.
            // The backend only reads it when the gift card has
            // `allowed_email_domain` set (OPE-76 reusable prod smoke test card).
            // Standard single-use user cards ignore this field, so it's a
            // strictly additive change that keeps existing redemption flows
            // byte-for-byte compatible.
            const emailEncryptionKey = cryptoService.getEmailEncryptionKeyForApi();

            const requestBody: { code: string; email_encryption_key?: string } = {
                code: normalizedCode
            };
            if (emailEncryptionKey) {
                requestBody.email_encryption_key = emailEncryptionKey;
            }

            const response = await fetch(getApiEndpoint(apiEndpoints.payments.redeemGiftCard), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'Origin': window.location.origin
                },
                body: JSON.stringify(requestBody),
                credentials: 'include' // Important for sending auth cookies
            });

            const result = await response.json();

            if (response.ok && result.success) {
                console.info("Gift card redeemed successfully:", result);

                if (typeof window !== 'undefined') {
                    const pendingCode = sessionStorage.getItem('pending_gift_card_code');
                    if (pendingCode?.toUpperCase() === normalizedCode) {
                        sessionStorage.removeItem('pending_gift_card_code');
                        console.debug('[GiftCardRedeem] Cleared pending gift card code from sessionStorage after successful redemption');
                    }
                }
                
                // Update profile store with new credit amount
                if (typeof result.current_credits === 'number') {
                    updateProfile({ credits: result.current_credits });
                }

                // Only show success message if not hidden (e.g., during signup we navigate away immediately)
                if (!hideSuccessMessage) {
                    successMessage = result.message || $text('settings.billing.gift_card.success');
                }
                
                // Dispatch success event - if hideSuccessMessage is true, dispatch immediately, otherwise wait to show message
                const delay = hideSuccessMessage ? 0 : 1500;
                setTimeout(() => {
                    dispatch('redeemed', {
                        credits_added: result.credits_added || 0,
                        current_credits: result.current_credits || 0
                    });
                }, delay);
            } else {
                console.error("Failed to redeem gift card:", result.message);
                errorMessage = result.message || $text('settings.billing.gift_card.error.invalid');
            }
        } catch (error) {
            console.error("Error redeeming gift card:", error);
            errorMessage = $text('settings.billing.gift_card.error.invalid');
        } finally {
            isRedeeming = false;
        }
    }

    /**
     * Handle cancel button click
     */
    function handleCancel() {
        giftCardCode = '';
        errorMessage = null;
        successMessage = null;
        dispatch('cancel');
    }

    /**
     * Handle Enter key press in input field
     */
    function handleKeyPress(event: KeyboardEvent) {
        if (event.key === 'Enter' && !isRedeeming && giftCardCode.trim()) {
            redeemCode();
        }
    }
</script>

<div class="gift-card-redeem-container">
    <div class="gift-card-form">
        <label class="gift-card-label" for="gift-card-code">
            {@html $text('settings.billing.gift_card.enter_code')}
        </label>
        
        <input
            id="gift-card-code"
            type="text"
            class="gift-card-input"
            placeholder={$text('settings.billing.gift_card.placeholder')}
            bind:value={giftCardCode}
            onkeypress={handleKeyPress}
            disabled={isRedeeming}
            autocomplete="off"
        />

        {#if errorMessage}
            <div class="error-message">
                {errorMessage}
            </div>
        {/if}

        {#if successMessage}
            <div class="success-message">
                {successMessage}
            </div>
        {/if}

        <div class="button-container">
            <button
                id="signup-gift-card-cancel"
                class="cancel-button"
                onclick={handleCancel}
                disabled={isRedeeming}
            >
                {@html $text('common.cancel')}
            </button>
            
            <button
                class="redeem-button"
                onclick={redeemCode}
                disabled={isRedeeming || !giftCardCode.trim()}
            >
                {#if isRedeeming}
                    {@html $text('settings.billing.gift_card.redeem')}...
                {:else}
                    {@html $text('settings.billing.gift_card.redeem')}
                {/if}
            </button>
        </div>
    </div>
</div>

<style>
    .gift-card-redeem-container {
        padding: var(--spacing-10) var(--spacing-5);
    }

    .gift-card-form {
        display: flex;
        flex-direction: column;
        gap: 15px;
    }

    .gift-card-label {
        font-size: var(--font-size-small);
        font-weight: 500;
        color: var(--text-primary, #333);
        margin-bottom: 5px;
    }

    .gift-card-input {
        width: 100%;
        padding: var(--spacing-6) var(--spacing-8);
        font-size: var(--font-size-p);
        border: 1px solid var(--border-color, #ddd);
        border-radius: var(--radius-3);
        background-color: var(--input-background, #fff);
        color: var(--text-primary, #333);
        box-sizing: border-box;
        text-transform: uppercase;
        letter-spacing: 1px;
    }

    .gift-card-input:focus {
        border-color: var(--primary-color, #007bff);
        box-shadow: 0 0 0 3px rgba(0, 123, 255, 0.1);
    }

    .gift-card-input:disabled {
        background-color: var(--input-disabled-background, #f5f5f5);
        cursor: not-allowed;
    }

    .error-message {
        padding: var(--spacing-5);
        background-color: var(--error-background, #fee);
        color: var(--error-text, #c33);
        border-radius: var(--radius-2);
        font-size: var(--font-size-small);
    }

    .success-message {
        padding: var(--spacing-5);
        background-color: var(--success-background, #efe);
        color: var(--success-text, #3c3);
        border-radius: var(--radius-2);
        font-size: var(--font-size-small);
    }

    .button-container {
        display: flex;
        gap: var(--spacing-5);
        margin-top: var(--spacing-5);
    }

    .cancel-button,
    .redeem-button {
        flex: 1;
        padding: var(--spacing-6) var(--spacing-12);
        font-size: var(--font-size-p);
        font-weight: 500;
        border: none;
        border-radius: var(--radius-3);
        cursor: pointer;
        transition: all var(--duration-normal) var(--easing-default);
    }

    .cancel-button {
        background-color: var(--button-secondary-background, #f0f0f0);
        color: var(--button-secondary-text, #333);
    }

    .cancel-button:hover:not(:disabled) {
        background-color: var(--button-secondary-hover, #e0e0e0);
    }

    .redeem-button {
        background-color: var(--primary-color, #007bff);
        color: var(--button-primary-text, #fff);
    }

    .redeem-button:hover:not(:disabled) {
        background-color: var(--primary-hover, #0056b3);
    }

    .cancel-button:disabled,
    .redeem-button:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }

    /* Responsive Styles */
    @media (max-width: 480px) {
        .gift-card-redeem-container {
            padding: 15px 5px;
        }

        .button-container {
            flex-direction: column;
        }

        .cancel-button,
        .redeem-button {
            width: 100%;
        }
    }
</style>
