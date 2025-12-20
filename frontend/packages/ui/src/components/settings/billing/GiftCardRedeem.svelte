<!--
Gift Card Redeem - Component for redeeming gift card codes
-->

<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { apiEndpoints, getApiEndpoint } from '../../../config/api';
    import { userProfile, updateProfile } from '../../../stores/userProfile';

    const dispatch = createEventDispatcher();

    let giftCardCode = $state('');
    let isRedeeming = $state(false);
    let errorMessage: string | null = $state(null);
    let successMessage: string | null = $state(null);

    /**
     * Redeem the gift card code
     */
    async function redeemCode() {
        // Validate input
        if (!giftCardCode.trim()) {
            errorMessage = $text('settings.billing.gift_card.error.invalid.text');
            return;
        }

        // Clear previous messages
        errorMessage = null;
        successMessage = null;
        isRedeeming = true;

        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.redeemGiftCard), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'Origin': window.location.origin
                },
                body: JSON.stringify({ code: giftCardCode.trim().toUpperCase() }),
                credentials: 'include' // Important for sending auth cookies
            });

            const result = await response.json();

            if (response.ok && result.success) {
                console.info("Gift card redeemed successfully:", result);
                
                // Update profile store with new credit amount
                if (typeof result.current_credits === 'number') {
                    updateProfile({ credits: result.current_credits });
                }

                successMessage = result.message || $text('settings.billing.gift_card.success.text');
                
                // Dispatch success event after a short delay to show success message
                // Include credits information for signup flow
                setTimeout(() => {
                    dispatch('redeemed', {
                        credits_added: result.credits_added || 0,
                        current_credits: result.current_credits || 0
                    });
                }, 1500);
            } else {
                console.error("Failed to redeem gift card:", result.message);
                errorMessage = result.message || $text('settings.billing.gift_card.error.invalid.text');
            }
        } catch (error) {
            console.error("Error redeeming gift card:", error);
            errorMessage = $text('settings.billing.gift_card.error.invalid.text');
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
            {@html $text('settings.billing.gift_card.enter_code.text')}
        </label>
        
        <input
            id="gift-card-code"
            type="text"
            class="gift-card-input"
            placeholder={$text('settings.billing.gift_card.placeholder.text')}
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
                class="cancel-button"
                onclick={handleCancel}
                disabled={isRedeeming}
            >
                {@html $text('settings.billing.gift_card.cancel.text')}
            </button>
            
            <button
                class="redeem-button"
                onclick={redeemCode}
                disabled={isRedeeming || !giftCardCode.trim()}
            >
                {#if isRedeeming}
                    {@html $text('settings.billing.gift_card.redeem.text')}...
                {:else}
                    {@html $text('settings.billing.gift_card.redeem.text')}
                {/if}
            </button>
        </div>
    </div>
</div>

<style>
    .gift-card-redeem-container {
        padding: 20px 10px;
    }

    .gift-card-form {
        display: flex;
        flex-direction: column;
        gap: 15px;
    }

    .gift-card-label {
        font-size: 14px;
        font-weight: 500;
        color: var(--text-primary, #333);
        margin-bottom: 5px;
    }

    .gift-card-input {
        width: 100%;
        padding: 12px 16px;
        font-size: 16px;
        border: 1px solid var(--border-color, #ddd);
        border-radius: 8px;
        background-color: var(--input-background, #fff);
        color: var(--text-primary, #333);
        box-sizing: border-box;
        text-transform: uppercase;
        letter-spacing: 1px;
    }

    .gift-card-input:focus {
        outline: none;
        border-color: var(--primary-color, #007bff);
        box-shadow: 0 0 0 3px rgba(0, 123, 255, 0.1);
    }

    .gift-card-input:disabled {
        background-color: var(--input-disabled-background, #f5f5f5);
        cursor: not-allowed;
    }

    .error-message {
        padding: 10px;
        background-color: var(--error-background, #fee);
        color: var(--error-text, #c33);
        border-radius: 6px;
        font-size: 14px;
    }

    .success-message {
        padding: 10px;
        background-color: var(--success-background, #efe);
        color: var(--success-text, #3c3);
        border-radius: 6px;
        font-size: 14px;
    }

    .button-container {
        display: flex;
        gap: 10px;
        margin-top: 10px;
    }

    .cancel-button,
    .redeem-button {
        flex: 1;
        padding: 12px 24px;
        font-size: 16px;
        font-weight: 500;
        border: none;
        border-radius: 8px;
        cursor: pointer;
        transition: all 0.2s ease;
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

