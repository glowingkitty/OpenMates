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
        isGift = false
    }: {
        purchasePrice?: number;
        currency?: string;
        credits_amount?: number;
        requireConsent?: boolean;
        compact?: boolean;
        initialState?: 'idle' | 'processing' | 'success';
        isGift?: boolean;
    } = $props();

    let hasConsentedToLimitedRefund = $state(false);
    let paymentState: 'idle' | 'processing' | 'success' = $state(initialState);
    let paymentFormComponent = $state();

    let stripe: any = $state(null);
    let elements: any = $state(null);
    let paymentElement: any = $state(null);
    let clientSecret: string | null = $state(null);
    let lastOrderId: string | null = $state(null);
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
            
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.createOrder), {
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
                throw new Error(`Failed to create order: ${response.status} ${response.statusText}. ${errorData.detail || ''}`);
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

    async function handleSubmit() {
        if (!stripe || !elements || !paymentElement) {
            return;
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
                        email: userEmail || undefined
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
            paymentState = 'success';
            // Dispatch state change with payment_intent_id for subscription setup
            dispatch('paymentStateChange', { 
                state: paymentState, 
                payment_intent_id: paymentIntent.id 
            });
        } else if (paymentIntent && paymentIntent.status === 'processing') {
            paymentState = 'processing';
            isWaitingForConfirmation = true;
            dispatch('paymentStateChange', { state: paymentState }); // Dispatch state change
            
            // Start 10-second timeout for payment confirmation from server
            // If no confirmation received, show delayed message and proceed as if successful
            paymentConfirmationTimeoutId = setTimeout(() => {
                if (isWaitingForConfirmation) {
                    console.log('[Payment] Payment confirmation timeout after 10 seconds - showing delayed message and proceeding');
                    showDelayedMessage = true;
                    
                    // Show delayed message briefly, then proceed as if payment was successful
                    // This allows user to continue while payment processes in background
                    setTimeout(() => {
                        if (isWaitingForConfirmation) {
                            console.log('[Payment] Proceeding to success state after timeout');
                            paymentState = 'success';
                            isWaitingForConfirmation = false; // Keep listening for websocket event
                            dispatch('paymentStateChange', { 
                                state: paymentState,
                                payment_intent_id: paymentIntent.id,
                                isDelayed: true // Flag to indicate this was a delayed confirmation
                            });
                        }
                    }, 2000); // Show delayed message for 2 seconds before proceeding
                }
            }, 10000); // 10 seconds
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
        
        // If we were waiting for confirmation (delayed payment), show notification
        // For fast payments, this won't be called as payment already succeeded
        if (isWaitingForConfirmation || showDelayedMessage) {
            isWaitingForConfirmation = false;
            showDelayedMessage = false;
            
            // Update credits in user profile
            if (payload.current_credits !== undefined) {
                updateProfile({ credits: payload.current_credits });
            }
            
            // Show success notification popup (using Notification.svelte component)
            notificationStore.success(
                `Payment completed! ${payload.credits_purchased.toLocaleString()} credits have been added to your account.`,
                5000
            );
            
            // If payment state is still processing, update to success
            // (This handles the case where timeout occurred and we're waiting for webhook)
            if (paymentState === 'processing') {
                paymentState = 'success';
                dispatch('paymentStateChange', { 
                    state: paymentState,
                    payment_intent_id: lastOrderId // Use order_id as payment_intent_id for compatibility
                });
            }
        } else {
            // Fast payment case - just update credits silently (no notification needed)
            // Credits were already updated via user_credits_updated event
            console.log('[Payment] Payment already completed, credits updated via user_credits_updated event');
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
        
        // Listen for payment_completed websocket event
        // This is sent after webhook processes payment and invoice is sent
        webSocketService.on('payment_completed', handlePaymentCompleted);
        
        // Listen for payment_failed websocket event
        // This is sent when webhook receives payment failure (can happen minutes after payment attempt)
        webSocketService.on('payment_failed', handlePaymentFailed);
        
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
            // Remove websocket listeners
            webSocketService.off('payment_completed', handlePaymentCompleted);
            webSocketService.off('payment_failed', handlePaymentFailed);
        };
    });

</script>

<div class="payment-component {compact ? 'compact' : ''}">
    {#if paymentState === 'processing' || paymentState === 'success'}
        <ProcessingPayment
            state={paymentState}
            {isGift}
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
