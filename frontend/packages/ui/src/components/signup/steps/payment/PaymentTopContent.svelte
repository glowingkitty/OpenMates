<!--
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml
step_10_top_content_svelte:
    credits_amount_header:
        type: 'text'
        text:
            - $text('signup.amount_currency.text') with amount and currency icon
            - $text('signup.for_chatting_and_apps.text')
        purpose:
            - 'Display the amount of credits the user will receive'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - 'credits'
    payment_component:
        type: 'component'
        component: 'Payment.svelte'
        purpose:
            - 'Display payment form with refund consent'
            - 'Process payment information'
        bigger_context:
            - 'Signup'
        tags:
            - 'signup'
            - 'payment'
            - 'credits'
-->

<script lang="ts">
    import { text } from '@repo/ui';
    import { createEventDispatcher, onMount } from 'svelte';
    import Payment from '../../../../components/Payment.svelte';
    import AutoTopUp from '../../../../components/payment/AutoTopUp.svelte';
    import { apiEndpoints, getApiUrl } from '../../../../config/api';
    
    const dispatch = createEventDispatcher();
    
    // Accept credits amount, price and currency as props using Svelte 5 runes
    let { 
        credits_amount = 21000,
        price = 20,
        currency = 'EUR',
        isGift = false,
        isGiftCardRedemption = false, // Flag to indicate this is a gift card redemption
        showSuccess = false, // When true, shows success message instead of payment form
        // Auto top-up props (used when showSuccess is true)
        purchasedCredits = null,
        purchasedPrice = null,
        paymentMethodSaved = true,
        paymentMethodSaveError = null,
        oncomplete,
        'onactivate-subscription': onactivateSubscription
    }: {
        credits_amount?: number,
        price?: number,
        currency?: string,
        isGift?: boolean,
        isGiftCardRedemption?: boolean,
        showSuccess?: boolean,
        purchasedCredits?: number | null,
        purchasedPrice?: number | null,
        paymentMethodSaved?: boolean,
        paymentMethodSaveError?: string | null,
        oncomplete?: (event: CustomEvent) => void,
        'onactivate-subscription'?: (event: CustomEvent) => void
    } = $props();
    
    // Track if payment form is visible
    let isPaymentFormVisible = false;
    
    // Local state for payment method status (used as fallback if prop is not set correctly)
    let localPaymentMethodSaved = $state(paymentMethodSaved);
    let localPaymentMethodSaveError = $state<string | null>(paymentMethodSaveError);
    
    // Update local state when props change
    $effect(() => {
        localPaymentMethodSaved = paymentMethodSaved;
        localPaymentMethodSaveError = paymentMethodSaveError;
    });
    
    
    // Check payment method on mount if showSuccess is true and paymentMethodSaved is false
    // This is a fallback check in case the parent component didn't check on reload
    onMount(async () => {
        if (showSuccess && !paymentMethodSaved) {
            console.debug('[PaymentTopContent] showSuccess=true but paymentMethodSaved=false, checking backend...');
            try {
                const response = await fetch(getApiUrl() + apiEndpoints.payments.hasPaymentMethod, {
                    method: 'GET',
                    credentials: 'include'
                });
                
                if (response.ok) {
                    const data = await response.json();
                    const hasPaymentMethod = data.has_payment_method === true;
                    console.debug(`[PaymentTopContent] Payment method status from backend: ${hasPaymentMethod}`);
                    
                    if (hasPaymentMethod) {
                        // Update local state and dispatch event to parent
                        localPaymentMethodSaved = true;
                        localPaymentMethodSaveError = null;
                        // Dispatch event to parent to update its state
                        dispatch('paymentMethodStatusUpdate', { 
                            saved: true, 
                            error: null 
                        });
                    } else {
                        localPaymentMethodSaved = false;
                        localPaymentMethodSaveError = 'No payment method found. Please complete payment first.';
                        dispatch('paymentMethodStatusUpdate', { 
                            saved: false, 
                            error: localPaymentMethodSaveError 
                        });
                    }
                } else {
                    console.warn('[PaymentTopContent] Failed to check payment method status:', response.status);
                    localPaymentMethodSaved = false;
                    localPaymentMethodSaveError = 'Failed to check payment method status';
                    dispatch('paymentMethodStatusUpdate', { 
                        saved: false, 
                        error: localPaymentMethodSaveError 
                    });
                }
            } catch (error) {
                console.error('[PaymentTopContent] Error checking payment method status:', error);
                localPaymentMethodSaved = false;
                localPaymentMethodSaveError = error instanceof Error ? error.message : 'Unknown error checking payment method';
                dispatch('paymentMethodStatusUpdate', { 
                    saved: false, 
                    error: localPaymentMethodSaveError 
                });
            }
        }
    });
    
    // Format number with thousand separators
    function formatNumber(num: number): string {
        return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    }

    function handleConsent(event) {
        // Forward consent event to parent component
        dispatch('consentGiven', event.detail);
        
        // When consent is given, after a short delay, payment form will show
        if (event.detail.consented) {
            setTimeout(() => {
                isPaymentFormVisible = true;
                dispatch('paymentFormVisibility', { visible: true });
            }, 500);
        }
    }
    
    function handleOpenRefundInfo() {
        // Forward the refund info request to parent
        dispatch('openRefundInfo');
    }
    
    function handlePaymentStateChange(event) {
        // Forward payment state changes to parent component
        dispatch('paymentStateChange', event.detail);
    }
</script>

<div class="container">
    {#if showSuccess}
        {#if isGiftCardRedemption}
            <!-- Gift card redemption: Show credits amount in top, success message in bottom -->
            <div class="top-container">
                <div class="header-content">
                    <div class="primary-text">
                        {@html $text('signup.amount_currency.text')
                            .replace('{currency}', '<span class="coin-icon-inline"></span>')
                            .replace('{amount}', formatNumber(credits_amount))}
                    </div>
                </div>
            </div>
            
            <div class="bottom-container">
                <div class="main-content">
                    <div class="separated-block gift-card-success">
                        <div class="success-message-container">
                            <div class="success-icon-large"></div>
                            <div class="success-text">
                                {@html $text('signup.gift_card_redeemed_success.text')}
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        {:else}
            <!-- Regular payment success: Show success message in top, auto top-up in bottom -->
            <div class="top-container success-container">
                <div class="header-content">
                    <div class="success-icon"></div>
                    <div class="primary-text">
                        {@html $text('signup.purchase_successful.text')}
                    </div>
                </div>
            </div>
            
            <!-- Auto top-up content below success message -->
            <div class="bottom-container">
                <div class="main-content">
                    <div class="separated-block">
                        <AutoTopUp
                            purchasedCredits={purchasedCredits || 0}
                            purchasedPrice={purchasedPrice || 0}
                            currency={currency.toLowerCase()}
                            paymentMethodSaved={localPaymentMethodSaved}
                            paymentMethodSaveError={localPaymentMethodSaveError}
                            {oncomplete}
                            onactivate-subscription={onactivateSubscription}
                        />
                    </div>
                </div>
            </div>
        {/if}
    {:else}
        <!-- Payment form for payment step -->
        <div class="top-container">
            <div class="header-content">
                <div class="primary-text">
                    {@html $text('signup.amount_currency.text')
                        .replace('{currency}', '<span class="coin-icon-inline"></span>')
                        .replace('{amount}', formatNumber(credits_amount))}
                </div>
            </div>
        </div>

        <div class="bottom-container">
            <div class="main-content">
                <div class="separated-block">
                    <Payment 
                        {credits_amount} 
                        purchasePrice={currency.toUpperCase() === 'JPY' ? price : price * 100} 
                        {currency}
                        initialState={isGift ? 'success' : 'idle'}
                        {isGift}
                        on:consentGiven={handleConsent}
                        on:openRefundInfo={handleOpenRefundInfo}
                        on:paymentStateChange={handlePaymentStateChange}
                    />
                </div>
            </div>
        </div>
    {/if}
</div>

<style>
    .container {
        position: relative;
        width: 100%;
        height: 100%;
        min-height: 400px; /* Ensure minimum height for payment form visibility */
    }
    
    .top-container {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 130px;
        padding: 0 24px;
        display: flex;
        align-items: flex-end;
        justify-content: center;
        z-index: 2;
    }
    
    /* Success container with purple background */
    .success-container {
        background: var(--color-primary);
        border-radius: 16px 16px 0 0;
        height: 100px;
        align-items: flex-end;
        padding-bottom: 0;
    }
    
    .header-content {
        display: flex;
        flex-direction: column;
        text-align: center;
        padding-bottom: 20px;
        align-items: center;
        gap: 6px;
    }
    
    /* For success container, display icon and text horizontally */
    .success-container .header-content {
        flex-direction: row;
        gap: 12px;
    }
    
    .success-icon {
        width: 36px;
        height: 36px;
        background-color: #58BC00;
        mask-image: url('@openmates/ui/static/icons/check.svg');
        mask-size: contain;
        mask-repeat: no-repeat;
        mask-position: center;
        animation: scaleIn 0.3s ease-out;
    }
    
    @keyframes scaleIn {
        from {
            transform: scale(0);
        }
        to {
            transform: scale(1);
        }
    }
    
    .primary-text {
        white-space: nowrap;
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-size: 18px;
        font-weight: 500;
    }

    .bottom-container {
        position: absolute;
        top: 160px;
        left: 0;
        right: 0;
        bottom: 0;
        padding: 0 24px;
        overflow-y: auto; /* Allow scrolling if content exceeds container */
        overflow-x: hidden;
    }

    @media (max-width: 600px) {
        .top-container {
            height: 60px;
        }
        .success-container {
            height: 60px;
        }
        .bottom-container {
            top: 80px;
            padding: 0 5px;
        }
    }
    
    .main-content {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: flex-start;
        width: 100%;
        height: 100%; /* Fill available space */
        gap: 0; /* Remove gap to allow full height usage */
    }

    .separated-block {
        position: relative;
        width: 95%;
        max-width: 400px;
        /* Fill full height of container - payment form is expanded step with full height */
        height: 100%;
        background-color: var(--color-grey-20);
        border-radius: 16px;
        padding: 16px;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1);
        display: flex;
        flex-direction: column;
        overflow: hidden; /* Prevent content overflow */
        box-sizing: border-box; /* Include padding in height calculation */
    }
    
    /* Target the bottom containers of our payment components */
    .separated-block :global(.bottom-container) {
        position: absolute;
        bottom: 20px;
        left: 0;
        width: 100%;
        padding-bottom: 0;
    }

    @media (max-width: 600px) {
        .separated-block :global(.bottom-container) {
            position: relative;
            bottom: unset;
        }
    }
    
    /* Adjust bottom-container position for success view */
    .success-container ~ .bottom-container {
        top: 120px;
    }
    
    @media (max-width: 600px) {
        .success-container ~ .bottom-container {
            top: 75px;
        }
    }
    
    /* Gift card success message styling */
    .gift-card-success {
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 200px;
    }
    
    .success-message-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 20px;
        text-align: center;
    }
    
    .success-icon-large {
        width: 64px;
        height: 64px;
        background-color: #58BC00;
        mask-image: url('@openmates/ui/static/icons/check.svg');
        mask-size: contain;
        mask-repeat: no-repeat;
        mask-position: center;
        animation: scaleIn 0.3s ease-out;
    }
    
    .success-text {
        font-size: 24px;
        font-weight: 600;
        color: var(--color-grey-100);
    }
</style>