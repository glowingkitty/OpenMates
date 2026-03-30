<script lang="ts">
    import { onMount, createEventDispatcher } from 'svelte';
    import { fade } from 'svelte/transition';
    import { apiEndpoints, getApiEndpoint } from '../config/api';
    import { userProfile, updateProfile } from '../stores/userProfile';
    import { loadStripe } from '@stripe/stripe-js';
    import * as cryptoService from '../services/cryptoService'; // Import cryptoService for email decryption
    import { webSocketService } from '../services/websocketService'; // Import WebSocket service for payment completion notifications
    import { notificationStore } from '../stores/notificationStore'; // Import notification store
    import { text } from '@repo/ui'; // i18n text helper

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
        disableWebSocketHandlers = false, // When true, don't register WebSocket handlers (e.g., when used in Settings)
        supportContribution = false, // When true, this is a supporter contribution
        supportEmail = null, // Email for supporter contributions (non-authenticated users)
        isRecurring = false, // When true, this is a recurring monthly subscription
        initialProviderOverride = null // When set, forces a specific provider on first load (e.g. 'polar' when user clicked non-EU card)
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
        supportContribution?: boolean;
        supportEmail?: string | null;
        isRecurring?: boolean;
        initialProviderOverride?: 'stripe' | 'polar' | null;
    } = $props();

    let hasConsentedToLimitedRefund = $state(false);
    let paymentState: 'idle' | 'processing' | 'success' = $state(initialState);
    let paymentFormComponent = $state();

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let stripe: any = $state(null);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let elements: any = $state(null);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let paymentElement: any = $state(null);
    let clientSecret: string | null = $state(null);
    let lastOrderId: string | null = $state(null);
    let paymentIntentId: string | null = $state(null); // Store actual payment_intent_id for delayed payments
    let hostedInvoiceUrl: string | null = $state(null);
    let isLoading = $state(false);
    let isButtonCooldown = $state(false);
    let errorMessage: string | null = $state(null);
    let validationErrors: string | null = $state(null);
    let userEmail: string | null = $state(null);
    let isInitializing = $state(false);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let paymentConfirmationTimeoutId: any = $state(null);
    let isWaitingForConfirmation = $state(false);
    let showDelayedMessage = $state(false);

    // State for Payment Element completeness
    let isPaymentElementComplete: boolean = $state(false);
    
    // Dual-provider state
    // activeProvider is set after fetching /config — either 'stripe' or 'polar'
    let activeProvider: 'stripe' | 'polar' | null = $state(null);
    // providerOverride is set when the user explicitly switches providers via the switch button
    let providerOverride: 'stripe' | 'polar' | null = $state(null);
    // isPolarLoading is true while Polar create-order is in flight before showing inline iframe
    let isPolarLoading = $state(false);
    // polarCheckoutUrl: when set, renders the Polar checkout as an inline iframe inside the
    // payment panel instead of a full-screen overlay. The SDK's PolarEmbedCheckout.create()
    // always appends a fixed-position overlay to document.body — we bypass it entirely and
    // manage our own iframe + postMessage listener so the checkout fits inside the settings menu.
    let polarCheckoutUrl: string | null = $state(null);
    // polarMessageListener: reference kept so we can remove it on cleanup
    let polarMessageListener: ((e: MessageEvent) => void) | null = $state(null);
    
    let darkmode = $state(false);
    let userProfileUnsubscribe = userProfile.subscribe(profile => {
        darkmode = !!profile.darkmode;
    });

    $effect(() => {
        if (supportContribution && supportEmail) {
            userEmail = supportEmail.trim();
        }
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
            // Build config URL — append provider_override query param if the user has switched
            let configUrl = getApiEndpoint(apiEndpoints.payments.config);
            if (providerOverride) {
                configUrl += `?provider_override=${providerOverride}`;
            }

            const response = await fetch(configUrl, {
                credentials: 'include'
            });
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const config = await response.json();

            activeProvider = config.provider as 'stripe' | 'polar';

            if (config.provider === 'stripe') {
                if (!config.public_key) throw new Error('Stripe Public Key not found in config response.');
                stripe = await loadStripe(config.public_key);
                await createOrder();
            } else if (config.provider === 'polar') {
                // Polar: auto-trigger checkout immediately on provider detection.
                // No button click needed — the checkout iframe loads as soon as the
                // payment panel mounts with Polar as the active provider.
                isLoading = false;
                isInitializing = false;
                handlePolarCheckout();
                return;
            } else {
                // Handle other providers if needed
                errorMessage = 'Unsupported payment provider.';
            }
        } catch (error) {
            errorMessage = `Failed to load payment configuration. ${error instanceof Error ? error.message : String(error)}`;
        } finally {
            isLoading = false;
            isInitializing = false;
        }
    }

    /**
     * Switch to a different payment provider.
     * Resets all provider-specific state and re-fetches config for the new provider.
     */
    async function switchProvider(newProvider: 'stripe' | 'polar') {
        // Clean up any existing Stripe elements
        if (paymentElement) {
            paymentElement.destroy();
            paymentElement = null;
        }
        // Clean up any active Polar inline checkout
        teardownPolarInlineCheckout();
        // Reset provider-specific state
        stripe = null;
        elements = null;
        clientSecret = null;
        lastOrderId = null;
        paymentIntentId = null;
        hostedInvoiceUrl = null;
        errorMessage = null;
        validationErrors = null;
        isPaymentElementComplete = false;
        isInitializing = false;

        providerOverride = newProvider;
        await fetchConfigAndInitialize();
    }

    /**
     * Create a Polar checkout session and open the embedded checkout overlay.
     * Called when the user clicks the "Pay with Polar" button.
     */
    /**
     * Remove the Polar postMessage listener and reset inline iframe state.
     * Called when checkout is dismissed or completed.
     */
    function teardownPolarInlineCheckout() {
        if (polarMessageListener) {
            window.removeEventListener('message', polarMessageListener);
            polarMessageListener = null;
        }
        polarCheckoutUrl = null;
    }

    async function handlePolarCheckout() {
        if (supportContribution) {
            // Supporter contributions always use Stripe
            return;
        }
        isPolarLoading = true;
        errorMessage = null;
        try {
            const emailEncryptionKey = cryptoService.getEmailEncryptionKeyForApi();

            let endpoint: string;
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            let requestBody: Record<string, any>;

            if (isGiftCard) {
                endpoint = apiEndpoints.payments.buyGiftCard;
                requestBody = {
                    credits_amount: credits_amount,
                    currency: currency,
                    email_encryption_key: emailEncryptionKey,
                    provider: 'polar'
                };
            } else {
                endpoint = apiEndpoints.payments.createOrder;
                requestBody = {
                    credits_amount: credits_amount,
                    currency: currency,
                    email_encryption_key: emailEncryptionKey,
                    provider: 'polar'
                };
            }

            const response = await fetch(getApiEndpoint(endpoint), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify(requestBody)
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                const errorDetail = errorData.detail || '';
                throw new Error(errorDetail || `Failed to create Polar order: ${response.status}`);
            }

            const order = await response.json();
            lastOrderId = order.order_id;

            if (!order.checkout_url) {
                throw new Error('No checkout URL returned from Polar order.');
            }

            // Build the inline iframe URL: append embed=true + theme so Polar renders
            // in embed mode (no redirect, postMessage events enabled).
            // We do NOT use PolarEmbedCheckout.create() because it always appends a
            // fixed-position full-screen overlay to document.body — which is wrong for
            // the settings panel context. Instead we render our own <iframe> in the
            // template and wire up the postMessage protocol manually.
            const theme = darkmode ? 'dark' : 'light';
            const iframeUrl = new URL(order.checkout_url);
            iframeUrl.searchParams.set('embed', 'true');
            iframeUrl.searchParams.set('theme', theme);

            // Register postMessage listener BEFORE setting polarCheckoutUrl (before iframe mounts)
            const POLAR_ORIGINS = ['https://polar.sh', 'https://sandbox.polar.sh'];
            const listener = (ev: MessageEvent) => {
                if (!POLAR_ORIGINS.includes(ev.origin)) return;
                const data = ev.data;
                if (!data || data.type !== 'POLAR_CHECKOUT') return;

                const event = data.event as string;
                console.log('[Payment][Polar] postMessage event:', event);

                if (event === 'success') {
                    teardownPolarInlineCheckout();
                    // Transition to processing state — WebSocket will confirm completion
                    paymentState = 'processing';
                    isWaitingForConfirmation = true;
                    dispatch('paymentStateChange', { state: paymentState, provider: 'polar' });

                    // 30-second fallback timeout in case WebSocket confirmation is delayed
                    paymentConfirmationTimeoutId = setTimeout(() => {
                        if (isWaitingForConfirmation) {
                            console.log('[Payment][Polar] Confirmation timeout after 30s — showing delayed message');
                            showDelayedMessage = true;
                            setTimeout(() => {
                                if (isWaitingForConfirmation) {
                                    paymentState = 'success';
                                    isWaitingForConfirmation = false;
                                    dispatch('paymentStateChange', {
                                        state: paymentState,
                                        payment_intent_id: lastOrderId,
                                        provider: 'polar',
                                        isDelayed: true
                                    });
                                }
                            }, 2000);
                        }
                    }, 30000);
                } else if (event === 'close') {
                    // User closed the checkout without completing — go back to button
                    teardownPolarInlineCheckout();
                }
            };
            polarMessageListener = listener;
            window.addEventListener('message', listener);

            // Setting polarCheckoutUrl causes the template to replace the button with the iframe
            polarCheckoutUrl = iframeUrl.toString();
            console.log('[Payment][Polar] Inline iframe URL set:', polarCheckoutUrl);

        } catch (error) {
            errorMessage = `Failed to start Polar checkout. ${error instanceof Error ? error.message : String(error)}`;
            console.error('[Payment][Polar] Error starting checkout:', error);
        } finally {
            isPolarLoading = false;
        }
    }

    async function createOrder() {
        isLoading = true;
        errorMessage = null;
        hostedInvoiceUrl = null;
        try {
            // Get email encryption key for server to decrypt email
            const emailEncryptionKey = cryptoService.getEmailEncryptionKeyForApi();

            // Choose endpoint based on payment type
            let endpoint;
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            let requestBody: any;

            if (supportContribution) {
                // Ensure we have an email for supporter contributions (even for authenticated users).
                // Support payments are account-independent, so we submit plaintext support_email.
                if (!supportEmail) {
                    await getUserEmail();
                }
                const supportEmailToUse = (supportEmail || userEmail || '').trim();
                if (!supportEmailToUse) {
                    throw new Error('Email is required for supporter contributions.');
                }

                // For support contributions, use a dedicated endpoint
                endpoint = apiEndpoints.payments.createSupportOrder;
                requestBody = {
                    amount: purchasePrice, // Already in cents from parent component
                    currency: currency,
                    support_email: supportEmailToUse,
                    is_recurring: isRecurring
                };
            } else if (isGiftCard) {
                endpoint = apiEndpoints.payments.buyGiftCard;
                requestBody = {
                    credits_amount: credits_amount,
                    currency: currency,
                    email_encryption_key: emailEncryptionKey
                };
            } else {
                // Regular credit purchase
                endpoint = apiEndpoints.payments.createOrder;
                requestBody = {
                    credits_amount: credits_amount,
                    currency: currency,
                    email_encryption_key: emailEncryptionKey
                };
                // Include provider override if the user explicitly switched
                if (providerOverride) {
                    requestBody.provider = providerOverride;
                }
            }

            const response = await fetch(getApiEndpoint(endpoint), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify(requestBody)
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
                if (order.hosted_invoice_url) hostedInvoiceUrl = order.hosted_invoice_url;

                if (!order.client_secret) {
                    if (supportContribution && isRecurring && hostedInvoiceUrl) {
                        errorMessage =
                            'We could not initialize the embedded payment form. Continue on Stripe to complete your monthly support payment.';
                        // No Stripe Elements initialization without a client_secret.
                        lastOrderId = order.order_id;
                        return;
                    }
                    throw new Error('Order created, but client_secret is missing.');
                }
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
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        paymentElement.on('ready', (event: any) => {
            console.log('[Payment] Payment Element ready. Available payment methods:', event);
            // Check if Apple Pay is available
            if (event && event.availablePaymentMethods) {
                const applePayAvailable = event.availablePaymentMethods.some(
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
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

        // eslint-disable-next-line @typescript-eslint/no-explicit-any
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
        // Supporter contributions can be made without authentication, and we don't reuse the payment method.
        if (isGiftCard || supportContribution) {
            console.log('[Payment] Skipping payment method save (gift card or support contribution)');
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

    /**
     * Handle return from a redirect-based payment method (Revolut Pay, Wero, etc.).
     * When the user is redirected to the provider's site to authenticate, the browser navigates
     * away entirely. On return, this is a fresh page load with query params:
     *   ?payment_intent=pi_xxx&payment_intent_client_secret=pi_xxx_secret_xxx&redirect_status=succeeded
     * We retrieve the PaymentIntent status and trigger the same success/failure flow as if
     * confirmPayment() had returned inline (for card payments).
     * Returns true if a redirect return was detected and handled.
     */
    async function handlePaymentRedirectReturn(): Promise<boolean> {
        const urlParams = new URLSearchParams(window.location.search);
        const redirectPaymentIntent = urlParams.get('payment_intent');
        const redirectClientSecret = urlParams.get('payment_intent_client_secret');
        const redirectStatus = urlParams.get('redirect_status');

        if (!redirectPaymentIntent || !redirectClientSecret) {
            return false; // Not a redirect return
        }

        console.log(`[Payment] Detected redirect return: payment_intent=${redirectPaymentIntent}, redirect_status=${redirectStatus}`);

        // Clean redirect params from the URL immediately so refreshing the page
        // doesn't re-trigger this handler, and so the URL looks clean.
        const cleanUrl = new URL(window.location.href);
        cleanUrl.searchParams.delete('payment_intent');
        cleanUrl.searchParams.delete('payment_intent_client_secret');
        cleanUrl.searchParams.delete('redirect_status');
        cleanUrl.searchParams.delete('redirect_pm_type');
        window.history.replaceState({}, '', cleanUrl.toString());

        // Show processing state while we verify the payment
        paymentState = 'processing';
        isLoading = true;
        dispatch('paymentStateChange', { state: 'processing' });

        try {
            // Load Stripe if not already loaded (fresh page load after redirect)
            if (!stripe) {
                const configResponse = await fetch(getApiEndpoint(apiEndpoints.payments.config), {
                    credentials: 'include'
                });
                if (!configResponse.ok) throw new Error('Failed to load payment config');
                const config = await configResponse.json();
                if (!config.public_key) throw new Error('Stripe public key missing');
                stripe = await loadStripe(config.public_key);
                if (!stripe) throw new Error('Failed to load Stripe.js');
                activeProvider = 'stripe';
            }

            // Retrieve the PaymentIntent to check its actual status
            const { paymentIntent } = await stripe.retrievePaymentIntent(redirectClientSecret);

            if (!paymentIntent) {
                throw new Error('Could not retrieve payment status after redirect');
            }

            console.log(`[Payment] PaymentIntent status after redirect: ${paymentIntent.status}`);
            paymentIntentId = paymentIntent.id;

            if (paymentIntent.status === 'succeeded') {
                // Payment confirmed — trigger the same success flow as inline confirmation
                await savePaymentMethod(paymentIntentId);

                if (isGiftCard) {
                    // Gift cards: wait for WebSocket gift_card_created event
                    isWaitingForConfirmation = true;
                    paymentConfirmationTimeoutId = setTimeout(() => {
                        if (isWaitingForConfirmation) {
                            showDelayedMessage = true;
                            setTimeout(() => {
                                if (isWaitingForConfirmation) {
                                    paymentState = 'success';
                                    isWaitingForConfirmation = false;
                                    dispatch('paymentStateChange', {
                                        state: paymentState,
                                        payment_intent_id: paymentIntentId,
                                        provider: 'stripe',
                                        isDelayed: true
                                    });
                                }
                            }, 2000);
                        }
                    }, 20000);
                } else {
                    paymentState = 'success';
                    if (supportContribution) {
                        notificationStore.success('Support payment successful!', 6000);
                    }
                    dispatch('paymentStateChange', {
                        state: paymentState,
                        payment_intent_id: paymentIntentId,
                        provider: 'stripe'
                    });
                }
            } else if (paymentIntent.status === 'processing') {
                // Payment still processing (e.g., bank transfer in progress)
                isWaitingForConfirmation = true;
                paymentConfirmationTimeoutId = setTimeout(() => {
                    if (isWaitingForConfirmation) {
                        showDelayedMessage = true;
                        setTimeout(() => {
                            if (isWaitingForConfirmation) {
                                paymentState = 'success';
                                isWaitingForConfirmation = false;
                                if (paymentIntentId) savePaymentMethod(paymentIntentId);
                                dispatch('paymentStateChange', {
                                    state: paymentState,
                                    payment_intent_id: paymentIntentId,
                                    provider: 'stripe',
                                    isDelayed: true
                                });
                            }
                        }, 2000);
                    }
                }, 20000);
            } else if (paymentIntent.status === 'requires_payment_method') {
                // Payment failed or was declined — user needs to try again
                paymentState = 'idle';
                errorMessage = 'Payment was not completed. Please try again with a different payment method.';
                if (supportContribution) {
                    notificationStore.error(errorMessage, 10000);
                    dispatch('paymentStateChange', { state: 'failure', error: errorMessage });
                }
            } else {
                // Unexpected status
                paymentState = 'idle';
                errorMessage = `Payment returned with unexpected status: ${paymentIntent.status}. Please try again.`;
            }
        } catch (err) {
            console.error('[Payment] Error handling redirect return:', err);
            paymentState = 'idle';
            errorMessage = `Failed to verify payment after redirect. ${err instanceof Error ? err.message : String(err)}`;
            if (supportContribution) {
                notificationStore.error(errorMessage, 10000);
                dispatch('paymentStateChange', { state: 'failure', error: errorMessage });
            }
        } finally {
            isLoading = false;
        }

        return true;
    }

    async function handleSubmit() {
        if (!stripe || !elements || !paymentElement) {
            return;
        }

        // CRITICAL: Ensure email is available before submitting payment
        // Since we set email: 'never' in the payment element, we MUST provide it in confirmPayment
        if (!userEmail) {
            // Try to get email if not already loaded (authenticated users)
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

        // Build a return_url for redirect-based payment methods (Revolut Pay, Wero, etc.).
        // For card payments, redirect: 'if_required' means no redirect occurs and this URL is unused.
        // For redirect-based methods, the user is sent to the provider's site to authenticate,
        // then returned to this URL with ?payment_intent=...&redirect_status=... query params.
        // We use the current page URL (stripped of any prior redirect params) so the user
        // returns to the exact same view (settings billing or signup).
        const returnUrl = new URL(window.location.href);
        // Clean any stale redirect params from a previous return
        returnUrl.searchParams.delete('payment_intent');
        returnUrl.searchParams.delete('payment_intent_client_secret');
        returnUrl.searchParams.delete('redirect_status');
        returnUrl.searchParams.delete('redirect_pm_type');

        const { error, paymentIntent } = await stripe.confirmPayment({
            elements,
            confirmParams: {
                return_url: returnUrl.toString(),
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

            if (supportContribution) {
                notificationStore.error(error.message || 'Support payment failed. Please try again.', 10000);
                dispatch('paymentStateChange', { state: 'failure', error: error.message });
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
                                    provider: 'stripe',
                                    isDelayed: true // Flag to indicate this was a delayed confirmation
                                });
                            }
                        }, 2000); // Show delayed message for 2 seconds before proceeding
                    }
                }, 20000); // 20 seconds
            } else {
                paymentState = 'success';
                if (supportContribution) {
                    notificationStore.success('Support payment successful!', 6000);
                }
                // Dispatch state change with payment_intent_id for subscription setup
                dispatch('paymentStateChange', { 
                    state: paymentState, 
                    payment_intent_id: paymentIntentId, // Use stored payment_intent_id
                    provider: 'stripe'
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
                                provider: 'stripe',
                                isDelayed: true // Flag to indicate this was a delayed confirmation
                            });
                        }
                    }, 2000); // Show delayed message for 2 seconds before proceeding
                }
            }, 20000); // 20 seconds (same as regular credit purchases)
        } else {
            errorMessage = 'An unexpected error occurred. Please try again.';
            if (supportContribution) {
                notificationStore.error('Support payment failed. Please try again.', 10000);
                dispatch('paymentStateChange', { state: 'failure', error: errorMessage });
            }
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
                    payment_intent_id: intentId,
                    provider: activeProvider || 'stripe'
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
        if (!supportContribution || !supportEmail) {
            getUserEmail();
        }

        // Check if this is a return from a redirect-based payment method (Revolut Pay, Wero, etc.).
        // If so, handle it and skip the normal initialization (order already exists).
        // This is an async IIFE because onMount doesn't accept async directly for the cleanup return.
        const redirectReturnPromise = handlePaymentRedirectReturn();
        redirectReturnPromise.then((wasRedirectReturn) => {
            if (wasRedirectReturn) {
                console.log('[Payment] Handled redirect return — skipping normal init');
                return;
            }
            // Normal initialization (no redirect return detected)
            if (initialState === 'idle') {
                if (initialProviderOverride) {
                    providerOverride = initialProviderOverride;
                }
                fetchConfigAndInitialize();
            }
        });
        
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
            // Clean up Polar inline iframe postMessage listener if active
            teardownPolarInlineCheckout();
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
            provider={activeProvider || 'stripe'}
        />
    {:else if activeProvider === 'polar' && !supportContribution}
        <!-- Polar embedded checkout (inline iframe, no full-screen overlay).
             We bypass PolarEmbedCheckout.create() entirely because it always appends a
             fixed-position overlay to document.body. Instead we render our own <iframe>
             directly in the settings panel. The checkout is auto-triggered on mount —
             no button click required. States:
             1. isPolarLoading → loading spinner while create-order is in flight
             2. polarCheckoutUrl is set → inline iframe fills the panel
             3. errorMessage (URL null, not loading) → retry button shown -->
        <div class="polar-checkout-wrapper">
            {#if polarCheckoutUrl}
                <!-- Inline Polar checkout iframe — full width, no border, tall enough
                     to show all fields without internal scroll. Settings menu scrolls. -->
                <div class="polar-inline-checkout-container">
                    <iframe
                        class="polar-inline-checkout-iframe"
                        src={polarCheckoutUrl}
                        title="Polar Checkout"
                        allow="payment 'self' https://polar.sh https://sandbox.polar.sh; publickey-credentials-get 'self' https://polar.sh https://sandbox.polar.sh"
                    ></iframe>
                </div>
                <!-- Switch to EU / Stripe — always visible below the iframe so users
                     with an EU card can switch without losing the form. -->
                <div class="provider-switch-container">
                    <button
                        class="provider-switch-btn"
                        onclick={() => switchProvider('stripe')}
                    >
                        {$text('signup.switch_to_eu_card')}
                    </button>
                </div>
            {:else if isPolarLoading || isLoading}
                <!-- Loading state while create-order is in flight -->
                <div class="polar-loading-state">
                    <div class="polar-loading-spinner"></div>
                    <span>{$text('common.loading')}</span>
                </div>
            {:else}
                <!-- Error / retry state — shown if auto-trigger failed -->
                {#if errorMessage}
                    <div class="polar-error-message" role="alert">{errorMessage}</div>
                {/if}

                <button
                    class="buy-button polar-pay-button"
                    data-testid="polar-pay-button"
                    onclick={handlePolarCheckout}
                >
                    {$text('signup.buy_for')
                        .replace('{currency}', currency)
                        .replace('{amount}', (purchasePrice / 100).toString())}
                </button>

                <!-- Switch to EU / Stripe -->
                <div class="provider-switch-container">
                    <button
                        class="provider-switch-btn"
                        onclick={() => switchProvider('stripe')}
                    >
                        {$text('signup.switch_to_eu_card')}
                    </button>
                </div>
            {/if}
        </div>
    {:else}
        {#if hostedInvoiceUrl}
            <div class="payment-form-overlay-wrapper">
                <!-- Switch to Polar (non-EU card) — shown at top so it's visible on mobile without scrolling -->
                {#if !supportContribution}
                    <div class="provider-switch-container">
                        <button
                            class="provider-switch-btn"
                            onclick={() => switchProvider('polar')}
                            disabled={isLoading}
                        >
                            {$text('signup.switch_to_non_eu_card')}
                        </button>
                    </div>
                {/if}
                <PaymentForm
                    bind:this={paymentFormComponent}
                    purchasePrice={purchasePrice}
                    currency={currency}
                    userEmail={userEmail}
                    requireConsent={requireConsent}
                    isSupportContribution={supportContribution}
                    bind:isPaymentElementComplete={isPaymentElementComplete}
                    hasConsentedToLimitedRefund={hasConsentedToLimitedRefund}
                    validationErrors={validationErrors}
                    paymentError={errorMessage}
                    isLoading={isLoading}
                    isButtonCooldown={isButtonCooldown}
                    fallbackUrl={hostedInvoiceUrl}
                    fallbackButtonLabel={'Continue on Stripe'}
                    stripe={stripe}
                    elements={elements}
                    clientSecret={clientSecret}
                    darkmode={darkmode}
                />
            </div>
        {:else}
        <div class="payment-form-overlay-wrapper">
            <!-- Switch to Polar (non-EU card) — shown at top so it's visible on mobile without scrolling -->
            {#if !supportContribution}
                <div class="provider-switch-container">
                    <button
                        class="provider-switch-btn"
                        onclick={() => switchProvider('polar')}
                        disabled={isLoading}
                    >
                        {$text('signup.switch_to_non_eu_card')}
                    </button>
                </div>
            {/if}
            <div id="payment-element"></div>
            <PaymentForm
                bind:this={paymentFormComponent}
                purchasePrice={purchasePrice}
                currency={currency}
                userEmail={userEmail}
                requireConsent={requireConsent}
                isSupportContribution={supportContribution}
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

    /* Provider switch button — subtle text link below the payment form */
    .provider-switch-container {
        display: flex;
        justify-content: center;
        margin-top: 12px;
    }

    .provider-switch-btn {
        background: none;
        border: none;
        padding: 0;
        font-size: 13px;
        color: var(--color-grey-60);
        cursor: pointer;
        text-decoration: underline;
        transition: color 0.15s;
    }

    .provider-switch-btn:hover:not(:disabled) {
        color: var(--color-grey-80);
    }

    .provider-switch-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    /* Polar checkout wrapper — full width, no extra padding */
    .polar-checkout-wrapper {
        width: 100%;
    }

    /* Polar pay button — shown only as retry fallback when auto-trigger fails */
    .polar-pay-button {
        width: 100%;
        margin-top: 20px;
    }

    /* Polar loading state — centered spinner shown while create-order is in flight */
    .polar-loading-state {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 12px;
        padding: 40px 0;
        color: var(--color-grey-60);
        font-size: 14px;
    }

    .polar-loading-spinner {
        width: 24px;
        height: 24px;
        border-radius: 50%;
        border: 2px solid var(--color-grey-20);
        border-top-color: var(--color-primary);
        animation: polar-spin 0.8s linear infinite;
    }

    @keyframes polar-spin {
        to { transform: rotate(360deg); }
    }

    /* Inline Polar checkout iframe container — no border/radius, flush with panel.
       The settings menu scrolls; the iframe itself should not scroll internally.
        Height 1800px to fit all Polar form fields without internal scroll. */
    .polar-inline-checkout-container {
        width: 100%;
    }

    .polar-inline-checkout-iframe {
        width: 100%;
        /* 1800px to cover all Polar form fields (email, card type, card
           number, expiry, CVC, cardholder name, billing address, submit button)
           without internal scrollbar. Settings menu panel handles page scrolling. */
        height: 1800px;
        border: none;
        display: block;
        background: transparent;
    }

    /* Error message for Polar checkout failures */
    .polar-error-message {
        background-color: var(--color-error-bg, #fee);
        color: var(--color-error-text, #c00);
        padding: 12px 16px;
        border-radius: 8px;
        margin-bottom: 16px;
        font-size: 14px;
        line-height: 1.5;
        border: 1px solid var(--color-error-border, #fcc);
    }
</style>
