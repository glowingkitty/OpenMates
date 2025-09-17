<script lang="ts">
    import { onMount, createEventDispatcher } from 'svelte';
    import { fade } from 'svelte/transition';
    import { getWebsiteUrl, routes } from '../config/links';
    import { apiEndpoints, getApiEndpoint } from '../config/api';
    import { userProfile, updateProfile } from '../stores/userProfile';
    import { get } from 'svelte/store';
    import { loadStripe } from '@stripe/stripe-js';
    import * as cryptoService from '../services/cryptoService'; // Import cryptoService for email decryption

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

    // State for Payment Element completeness
    let isPaymentElementComplete: boolean = $state(false);
    
    let darkmode = $state(false);
    let userProfileUnsubscribe = userProfile.subscribe(profile => {
        darkmode = !!profile.darkmode;
    });

    function getUserEmail() {
        try {
            // Get email from encrypted storage (always decrypt on demand)
            const email = cryptoService.getEmailDecryptedWithMasterKey();
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

        paymentElement.on('change', (event: any) => {
            isPaymentElementComplete = event.complete; // Track overall completeness
            if (event.error) {
                validationErrors = event.error.message;
            } else {
                validationErrors = null;
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
            dispatch('paymentStateChange', { state: paymentState }); // Dispatch state change
        } else if (paymentIntent && paymentIntent.status === 'processing') {
            paymentState = 'processing';
            dispatch('paymentStateChange', { state: paymentState }); // Dispatch state change
        } else {
            errorMessage = 'An unexpected error occurred. Please try again.';
            isLoading = false;
        }
    }

    onMount(() => {
        getUserEmail();
        if (initialState === 'idle') {
            fetchConfigAndInitialize();
        }
        
        return () => {
            if (userProfileUnsubscribe) {
                userProfileUnsubscribe();
            }
            // Clean up Stripe elements on component destroy
            if (paymentElement) paymentElement.destroy();
        };
    });

</script>

<div class="payment-component {compact ? 'compact' : ''}">
    {#if paymentState === 'processing' || paymentState === 'success'}
        <ProcessingPayment
            state={paymentState}
            {isGift}
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
                onsubmitPayment={handleSubmit}
                stripe={stripe}
                elements={elements}
                clientSecret={clientSecret}
                darkmode={darkmode}
            />
            {#if requireConsent && !hasConsentedToLimitedRefund}
                <div class="consent-overlay" transition:fade>
                    <LimitedRefundConsent
                        bind:hasConsentedToLimitedRefund={hasConsentedToLimitedRefund}
                        on:consentChanged={() => {}}
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
