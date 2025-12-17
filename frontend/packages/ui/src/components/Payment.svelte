<script lang="ts">
    import { onMount, onDestroy, createEventDispatcher } from 'svelte';
    import { fade } from 'svelte/transition';
    import { getWebsiteUrl, routes } from '../config/links';
    import { apiEndpoints, getApiEndpoint } from '../config/api';
    import { userProfile, updateProfile } from '../stores/userProfile';
    import { get } from 'svelte/store';
    import { loadStripe } from '@stripe/stripe-js';
    import * as cryptoService from '../services/cryptoService'; // Import cryptoService for email decryption
    import { webSocketService } from '../services/websocketService'; // Import WebSocket service for payment completion notifications
    import { notificationStore } from '../stores/notificationStore'; // Import notification store

    import LimitedRefundConsent from './payment/LimitedRefundConsent.svelte';
    import PaymentForm from './payment/PaymentForm.svelte';
    import ProcessingPayment from './payment/ProcessingPayment.svelte';

    const dispatch = createEventDispatcher();

    // Props using Svelte 5 runes
    let { 
        purchasePrice = 20,
        currency = 'EUR',
        credits_amount = 21000,
        requireConsent = true,
        compact = false,
        initialState = 'idle',
        isGift = false,
        isGiftCard = false,
        disableWebSocketHandlers = false // When true, don't register WebSocket handlers (e.g., when used in Settings)
    }: {
        purchasePrice?: number;
        currency?: string;
        credits_amount?: number;
        requireConsent?: boolean;
        compact?: boolean;
        initialState?: 'idle' | 'processing' | 'success';
        isGift?: boolean;
        isGiftCard?: boolean;
        disableWebSocketHandlers?: boolean;
    } = $props();

    let hasConsentedToLimitedRefund = $state(false);
    let paymentState: 'idle' | 'processing' | 'success' = $state(initialState);
    let paymentFormComponent = $state();

    let stripe: any = $state(null);
    let elements: any = $state(null);
    let paymentElement: any = $state(null);
    let clientSecret: string | null = $state(null);
    let lastOrderId: string | null = $state(null);
    let paymentIntentId: string | null = $state(null); // Store actual payment_intent_id for delayed payments
    let isLoading = $state(false);
    let isButtonCooldown = $state(false);
    let errorMessage: string | null = $state(null);
    let validationErrors: string | null = $state(null);
    let pollTimeoutId: any = $state(null);
    let isPollingStopped = $state(false);
    let userEmail: string | null = $state(null);
    let isInitializing = $state(false);
    let paymentConfirmationTimeoutId: any = $state(null);
    let isWaitingForConfirmation = $state(false);
    let showDelayedMessage = $state(false);

    // State for Payment Element completeness
    let isPaymentElementComplete: boolean = $state(false);
    
    let darkmode = $state(false);
    let userProfileUnsubscribe = userProfile.subscribe(profile => {
        darkmode = !!profile.darkmode;
    });

    async function getUserEmail() {
        try {
            // Get email from encrypted storage (always decrypt on demand)
            const email: string | null = await cryptoService.getEmailDecryptedWithMasterKey();
            userEmail = email || null;
        } catch (err) {
            console.error('Error getting decrypted email:', err);
            userEmail = null;
        }
    }

    async function fetchConfigAndInitialize() {
        if (isInitializing) return;
        isInitializing = true;
        isLoading = true;
        errorMessage = null;
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.config), {
                credentials: 'include'
            });
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const config = await response.json();

            if (config.provider === 'stripe') {
                if (!config.public_key) throw new Error('Stripe Public Key not found in config response.');
                stripe = await loadStripe(config.public_key);
                await createOrder();
            } else {
                // Handle other providers like Revolut if needed
                errorMessage = 'Unsupported payment provider.';
            }
        } catch (error) {
            errorMessage = `Failed to load payment configuration. ${error instanceof Error ? error.message : String(error)}`;
        } finally {
            isLoading = false;
            isInitializing = false;
        }
    }

    async function createOrder() {
        isLoading = true;
        errorMessage = null;
        try {
            // Get email encryption key for server to decrypt email
            const emailEncryptionKey = cryptoService.getEmailEncryptionKeyForApi();
            
            // Use buy-gift-card endpoint for gift card purchases, create-order for regular purchases
            const endpoint = isGiftCard 
                ? apiEndpoints.payments.buyGiftCard 
                : apiEndpoints.payments.createOrder;
            
            const response = await fetch(getApiEndpoint(endpoint), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    credits_amount: credits_amount,
                    currency: currency,
                    email_encryption_key: emailEncryptionKey
                })
            });
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                // Extract the detail message from the API response if available
                // This provides user-friendly error messages (e.g., tier limit exceeded)
                const errorDetail = errorData.detail || '';
                if (errorDetail) {
                    throw new Error(errorDetail);
                } else {
                    throw new Error(`Failed to create order: ${response.status} ${response.statusText}`);
                }
            }
            const order = await response.json();
            if (order.provider === 'stripe') {
                if (!order.client_secret) throw new Error('Order created, but client_secret is missing.');
                clientSecret = order.client_secret;
                initializePaymentElement();
            }
            lastOrderId = order.order_id;
        } catch (error) {
            errorMessage = `Failed to create payment order. ${error instanceof Error ? error.message : String(error)}`;
        } finally {
            isLoading = false;
        }
    }

    function initializePaymentElement() {
        if (!stripe || !clientSecret) return;
        
        // Destroy existing payment element if it exists to prevent re-mounting issues
        if (paymentElement) {
            paymentElement.destroy();
            paymentElement = null;
        }

        const appearance = {
            theme: darkmode ? 'night' : 'stripe',
            variables: {
                colorPrimary: '#635BFF', // A shade of purple/blue
                colorBackground: darkmode ? '#1a1a1a' : '#ffffff',
                colorText: darkmode ? '#ffffff' : '#333333',
                colorDanger: '#df1b41',
                fontFamily: 'Lexend Deca, system-ui, sans-serif',
                spacingUnit: '2px',
                borderRadius: '12px', // More rounded corners
                // Custom colors for input fields
                colorTextPlaceholder: darkmode ? '#888888' : '#aaaaaa',
                colorIcon: darkmode ? '#ffffff' : '#635BFF', // Icon color
            },
            rules: {
                '.Input': {
                    padding: '12px 16px',
                    border: '1px solid var(--color-grey-40)',
                },
                '.Input:focus': {
                    border: '1px solid var(--color-grey-40)',
                },
                '.Error': {
                    color: 'var(--colorDanger)',
                },
                '.Label': {
                    opacity: '0',
                    marginBottom: '-10px',
                }
            }
        };

        elements = stripe.elements({ appearance, clientSecret });
        paymentElement = elements.create('payment', {
            fields: {
                billingDetails: {
                    name: 'auto',
                    email: 'never', // We collect email separately
                }
            },
            layout: 'tabs',
        });
        
        paymentElement.mount('#payment-element');

        // Log available payment methods for debugging Apple Pay
        paymentElement.on('ready', (event: any) => {
            console.log('[Payment] Payment Element ready. Available payment methods:', event);
            // Check if Apple Pay is available
            if (event && event.availablePaymentMethods) {
                const applePayAvailable = event.availablePaymentMethods.some(
                    (method: any) => method.type === 'apple_pay' || method.type === 'pay'
                );
                console.log('[Payment] Apple Pay available:', applePayAvailable);
                if (!applePayAvailable) {
                    console.warn('[Payment] Apple Pay is not available. This could be due to:');
                    console.warn('  - Domain not verified in Stripe Dashboard');
                    console.warn('  - Apple Pay not enabled in Stripe Dashboard');
                    console.warn('  - Browser/device not supporting Apple Pay');
                    console.warn('  - Not using HTTPS');
                }
            }
        });

        paymentElement.on('change', (event: any) => {
            isPaymentElementComplete = event.complete; // Track overall completeness
            if (event.error) {
                validationErrors = event.error.message;
            } else {
                validationErrors = null;
            }
            // Log payment method changes for debugging
            if (event.value && event.value.type) {
                console.log('[Payment] Payment method changed:', event.value.type);
            }
        });
    }

    /**
     * Save payment method to backend after successful payment.
     * This ensures the payment method is attached to the Stripe customer
     * and available for future purchases and subscriptions.
     * 
     * @param intentId - The payment intent ID from the successful payment
     */
    async function savePaymentMethod(intentId: string) {
        // Only save payment methods for regular credit purchases (not gift cards)
        // Gift cards may have different requirements
        if (isGiftCard) {
            console.log('[Payment] Skipping payment method save for gift card purchase');
            return;
        }

        try {
            console.log(`[Payment] Saving payment method with payment_intent_id: ${intentId}`);
            
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.savePaymentMethod), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify({
                    payment_intent_id: intentId
                })
            });
            
            if (response.ok) {
                const result = await response.json();
                console.log('[Payment] Payment method saved successfully:', result);
            } else {
                const errorText = await response.text();
                console.warn('[Payment] Failed to save payment method (non-critical):', errorText);
                // Don't throw error - payment was successful, saving payment method is a convenience feature
            }
        } catch (error) {
            console.warn('[Payment] Error saving payment method (non-critical):', error);
            // Don't throw error - payment was successful, saving payment method is a convenience feature
        }
    }

    async function handleSubmit() {
        if (!stripe || !elements || !paymentElement) {
            return;
        }

        // CRITICAL: Ensure email is available before submitting payment
        // Since we set email: 'never' in the payment element, we MUST provide it in confirmPayment
        if (!userEmail) {
            // Try to get email if not already loaded
            await getUserEmail();
            if (!userEmail) {
                errorMessage = 'Email is required for payment. Please ensure your email is set in your account.';
                isLoading = false;
                return;
            }
        }

        isLoading = true;
        errorMessage = null;
        validationErrors = null;

        const { error, paymentIntent } = await stripe.confirmPayment({
            elements,
            confirmParams: {
                // return_url is removed to prevent redirection
                payment_method_data: {
                    billing_details: {
                        email: userEmail // Always provide email since we disabled it in the element
                    }
                }
            },
            redirect: 'if_required'
        });

        if (error) {
            if (error.type === 'card_error' || error.type === 'validation_error') {
                validationErrors = error.message;
            } else {
                errorMessage = error.message;
            }
            isLoading = false;
        } else if (paymentIntent && paymentIntent.status === 'succeeded') {
            // Store payment_intent_id for later use (e.g., when webhook completes)
            paymentIntentId = paymentIntent.id;
            
            // Save payment method for future use (non-blocking)
            // This ensures the payment method is available for future purchases
            await savePaymentMethod(paymentIntentId);
            
            // For gift cards, keep in processing state until we receive gift_card_created event
            // For regular purchases, immediately show success
            if (isGiftCard) {
                paymentState = 'processing';
                isWaitingForConfirmation = true;
                dispatch('paymentStateChange', { state: paymentState }); // Dispatch processing state
                
                // Start 20-second timeout for gift card creation from server
                // If no gift card received, show delayed message and proceed as if successful
                paymentConfirmationTimeoutId = setTimeout(() => {
                    if (isWaitingForConfirmation) {
                        console.log('[Payment] Gift card creation timeout after 20 seconds - showing delayed message and proceeding');
                        showDelayedMessage = true;
                        
                        // Show delayed message briefly, then proceed as if payment was successful
                        // This allows user to continue while gift card processes in background
                        setTimeout(() => {
                            if (isWaitingForConfirmation) {
                                console.log('[Payment] Proceeding to success state after gift card timeout');
                                paymentState = 'success';
                                isWaitingForConfirmation = false; // Keep listening for websocket event
                                dispatch('paymentStateChange', { 
                                    state: paymentState,
                                    payment_intent_id: paymentIntentId, // Use stored payment_intent_id
                                    isDelayed: true // Flag to indicate this was a delayed confirmation
                                });
                            }
                        }, 2000); // Show delayed message for 2 seconds before proceeding
                    }
                }, 20000); // 20 seconds
            } else {
                paymentState = 'success';
                // Dispatch state change with payment_intent_id for subscription setup
                dispatch('paymentStateChange', { 
                    state: paymentState, 
                    payment_intent_id: paymentIntentId // Use stored payment_intent_id
                });
            }
        } else if (paymentIntent && paymentIntent.status === 'processing') {
            // Store payment_intent_id for later use (e.g., when webhook completes)
            paymentIntentId = paymentIntent.id;
            
            paymentState = 'processing';
            isWaitingForConfirmation = true;
            dispatch('paymentStateChange', { state: paymentState }); // Dispatch state change
            
            // Start 20-second timeout for payment confirmation from server
            // If no confirmation received, show delayed message and proceed as if successful
            paymentConfirmationTimeoutId = setTimeout(() => {
                if (isWaitingForConfirmation) {
                    console.log('[Payment] Payment confirmation timeout after 20 seconds - showing delayed message and proceeding');
                    showDelayedMessage = true;
                    
                    // Show delayed message briefly, then proceed as if payment was successful
                    // This allows user to continue while payment processes in background
                    setTimeout(() => {
                        if (isWaitingForConfirmation) {
                            console.log('[Payment] Proceeding to success state after timeout');
                            paymentState = 'success';
                            isWaitingForConfirmation = false; // Keep listening for websocket event
                            
                            // Save payment method when payment is confirmed after timeout
                            if (paymentIntentId) {
                                savePaymentMethod(paymentIntentId);
                            }
                            
                            dispatch('paymentStateChange', { 
                                state: paymentState,
                                payment_intent_id: paymentIntentId, // Use stored payment_intent_id
                                isDelayed: true // Flag to indicate this was a delayed confirmation
                            });
                        }
                    }, 2000); // Show delayed message for 2 seconds before proceeding
                }
            }, 20000); // 20 seconds (same as regular credit purchases)
        } else {
            errorMessage = 'An unexpected error occurred. Please try again.';
            isLoading = false;
        }
    }

    // Handle payment completion notification from server
    // This is called when the webhook processes the payment and invoice is sent
    function handlePaymentCompleted(payload: { order_id: string, credits_purchased: number, current_credits: number }) {
        console.log('[Payment] Received payment_completed notification from server:', payload);
        
        // Clear the timeout since we received confirmation
        if (paymentConfirmationTimeoutId) {
            clearTimeout(paymentConfirmationTimeoutId);
            paymentConfirmationTimeoutId = null;
        }
        
        // ALWAYS update credits when current_credits is provided, regardless of payment state
        // This ensures credits are updated even if WebSocket wasn't connected during signup
        // or if user_credits_updated event was missed
        if (payload.current_credits !== undefined) {
            console.log(`[Payment] Updating credits to ${payload.current_credits} from payment_completed event`);
            updateProfile({ credits: payload.current_credits });
        }
        
        // If we were waiting for confirmation (delayed payment), show notification
        // For fast payments, this won't be called as payment already succeeded
        if (isWaitingForConfirmation || showDelayedMessage) {
            isWaitingForConfirmation = false;
            showDelayedMessage = false;
            
            // Show success notification popup (using Notification.svelte component)
            notificationStore.success(
                `Payment completed! ${payload.credits_purchased.toLocaleString()} credits have been added to your account.`,
                5000
            );
            
            // If payment state is still processing, update to success
            // (This handles the case where timeout occurred and we're waiting for webhook)
            if (paymentState === 'processing') {
                paymentState = 'success';
                // Use stored payment_intent_id if available, otherwise fall back to lastOrderId
                // For Stripe, order_id is the payment_intent_id, so lastOrderId should work
                // But prefer paymentIntentId if we have it (from immediate success case)
                const intentId = paymentIntentId || lastOrderId || payload.order_id;
                
                // Save payment method when payment is confirmed via webhook
                if (intentId) {
                    savePaymentMethod(intentId);
                }
                
                dispatch('paymentStateChange', { 
                    state: paymentState,
                    payment_intent_id: intentId
                });
            }
        } else {
            // Fast payment case - credits already updated above, just log
            console.log('[Payment] Payment already completed, credits updated from payment_completed event');
        }
    }

    // Handle gift card created notification from server
    // This is called when the webhook creates a gift card after payment
    function handleGiftCardCreated(payload: { order_id: string, gift_card_code: string, credits_value: number }) {
        console.log('[Payment] Received gift_card_created notification from server:', payload);
        
        // Clear the timeout since we received confirmation
        if (paymentConfirmationTimeoutId) {
            clearTimeout(paymentConfirmationTimeoutId);
            paymentConfirmationTimeoutId = null;
        }
        
        // If we were waiting for confirmation (delayed payment), proceed to success
        if (isWaitingForConfirmation || showDelayedMessage) {
            isWaitingForConfirmation = false;
            showDelayedMessage = false;
            
            // Update payment state to success
            if (paymentState === 'processing') {
                paymentState = 'success';
                // Use stored payment_intent_id if available, otherwise fall back to lastOrderId
                const intentId = paymentIntentId || lastOrderId;
                dispatch('paymentStateChange', { 
                    state: paymentState,
                    payment_intent_id: intentId,
                    gift_card_code: payload.gift_card_code,
                    credits_value: payload.credits_value
                });
            }
        } else {
            // Fast payment case - update state if still processing
            if (paymentState === 'processing') {
                paymentState = 'success';
                // Use stored payment_intent_id if available, otherwise fall back to lastOrderId
                const intentId = paymentIntentId || lastOrderId;
                dispatch('paymentStateChange', { 
                    state: paymentState,
                    payment_intent_id: intentId,
                    gift_card_code: payload.gift_card_code,
                    credits_value: payload.credits_value
                });
            } else if (paymentState === 'success') {
                // Already in success state, but dispatch again with gift card info
                // Use stored payment_intent_id if available, otherwise fall back to lastOrderId
                const intentId = paymentIntentId || lastOrderId;
                dispatch('paymentStateChange', { 
                    state: paymentState,
                    payment_intent_id: intentId,
                    gift_card_code: payload.gift_card_code,
                    credits_value: payload.credits_value
                });
            }
        }
    }

    // Handle payment failure notification from server
    // This is called when the webhook receives a payment failure (can happen minutes after payment attempt)
    function handlePaymentFailed(payload: { order_id: string, message: string }) {
        console.log('[Payment] Received payment_failed notification from server:', payload);
        
        // Clear the timeout since we received failure notification
        if (paymentConfirmationTimeoutId) {
            clearTimeout(paymentConfirmationTimeoutId);
            paymentConfirmationTimeoutId = null;
        }
        
        // Reset waiting state
        isWaitingForConfirmation = false;
        showDelayedMessage = false;
        
        // Show error notification popup (using Notification.svelte component)
        // This notification will appear even if user has already moved on to other parts of the app
        notificationStore.error(
            payload.message || 'Payment failed. Please try again or use a different payment method.',
            10000 // Show for 10 seconds since this is important
        );
        
        // Update payment state to failure
        paymentState = 'idle'; // Reset to idle so user can try again
        errorMessage = payload.message || 'Payment failed. Please try again.';
        isLoading = false;
        
        // Dispatch state change to parent component
        dispatch('paymentStateChange', { 
            state: 'failure',
            error: payload.message
        });
    }

    onMount(() => {
        getUserEmail();
        if (initialState === 'idle') {
            fetchConfigAndInitialize();
        }
        
        // Only register WebSocket handlers if not disabled (e.g., when used in Settings, Settings.svelte already handles these)
        // This prevents duplicate handler registrations that cause warnings
        if (!disableWebSocketHandlers) {
            // Listen for payment_completed websocket event
            // This is sent after webhook processes payment and invoice is sent
            webSocketService.on('payment_completed', handlePaymentCompleted);
            
            // Listen for gift_card_created websocket event (for gift card purchases)
            // This is sent after webhook creates a gift card after payment
            if (isGiftCard) {
                webSocketService.on('gift_card_created', handleGiftCardCreated);
            }
            
            // Listen for payment_failed websocket event
            // This is sent when webhook receives payment failure (can happen minutes after payment attempt)
            webSocketService.on('payment_failed', handlePaymentFailed);
        }
        
        return () => {
            if (userProfileUnsubscribe) {
                userProfileUnsubscribe();
            }
            // Clean up Stripe elements on component destroy
            if (paymentElement) paymentElement.destroy();
            // Clean up timeout
            if (paymentConfirmationTimeoutId) {
                clearTimeout(paymentConfirmationTimeoutId);
            }
            // Remove websocket listeners only if they were registered
            if (!disableWebSocketHandlers) {
                webSocketService.off('payment_completed', handlePaymentCompleted);
                if (isGiftCard) {
                    webSocketService.off('gift_card_created', handleGiftCardCreated);
                }
                webSocketService.off('payment_failed', handlePaymentFailed);
            }
        };
    });

</script>

<div class="payment-component {compact ? 'compact' : ''}">
    {#if paymentState === 'processing' || paymentState === 'success'}
        <ProcessingPayment
            state={paymentState}
            {isGift}
            isGiftCard={isGiftCard}
            {showDelayedMessage}
        />
    {:else}
        <div class="payment-form-overlay-wrapper">
            <div id="payment-element"></div>
            <PaymentForm
                bind:this={paymentFormComponent}
                purchasePrice={purchasePrice}
                currency={currency}
                userEmail={userEmail}
                bind:isPaymentElementComplete={isPaymentElementComplete}
                hasConsentedToLimitedRefund={hasConsentedToLimitedRefund}
                validationErrors={validationErrors}
                paymentError={errorMessage}
                isLoading={isLoading}
                isButtonCooldown={isButtonCooldown}
                on:submitPayment={handleSubmit}
                stripe={stripe}
                elements={elements}
                clientSecret={clientSecret}
                darkmode={darkmode}
            />
            {#if requireConsent && !hasConsentedToLimitedRefund}
                <div class="consent-overlay" transition:fade>
                    <LimitedRefundConsent
                        bind:hasConsentedToLimitedRefund={hasConsentedToLimitedRefund}
                        on:consentChanged={(event) => {
                            hasConsentedToLimitedRefund = event.detail.consented;
                            // Dispatch consent event to parent component
                            dispatch('consentGiven', event.detail);
                        }}
                    />
                </div>
            {/if}
        </div>
    {/if}
</div>

<style>
    .payment-component {
        width: 100%;
        height: 100%;
        position: relative;
    }

    .payment-form-overlay-wrapper {
        position: relative;
        width: 100%;
        height: 100%;
    }

    .consent-overlay {
        position: absolute;
        top: -10px;
        left: -10px;
        right: -10px;
        width: 100%;
        height: 100%;
        background: var(--color-grey-20);
        z-index: 10;
        display: flex;
        align-items: center;
        justify-content: center;
        pointer-events: all;
        box-shadow: 0 0 8px 0 rgba(0,0,0,0.04);
        padding: 10px;
    }

    .consent-overlay :global(*) {
        pointer-events: auto;
    }

    .compact {
        max-width: 500px;
        margin: 0 auto;
    }
</style>
