<script lang="ts">
    import { text } from '@repo/ui';
    import { onMount, createEventDispatcher, tick } from 'svelte';
    import { fade } from 'svelte/transition';
    import { getWebsiteUrl, routes } from '../config/links';
    import RevolutCheckout from '@revolut/checkout';
    import { apiEndpoints, getApiEndpoint } from '../config/api';
    import { userProfile, updateProfile } from '../stores/userProfile'; // Import updateProfile
    import { get } from 'svelte/store';

    // Import our new component modules
    import LimitedRefundConsent from './payment/LimitedRefundConsent.svelte';
    import PaymentForm from './payment/PaymentForm.svelte';
    import ProcessingPayment from './payment/ProcessingPayment.svelte';

    const dispatch = createEventDispatcher();

    // Accept props
    export let purchasePrice: number = 20;
    export let currency: string = 'EUR';
    export let credits_amount: number = 21000;
    export let requireConsent: boolean = true;
    export let compact: boolean = false;
    export let initialState: 'idle' | 'processing' | 'success' = 'idle';
    export let isGift: boolean = false;

    // Consent state
    let hasConsentedToLimitedRefund = false;

    // Payment state
    let paymentState: 'idle' | 'processing' | 'success' = initialState;

    // Payment form state
    /* showPaymentForm is no longer needed; payment form is always rendered and initialized regardless of consent */

    // References to child components
    let paymentFormComponent;

    // Revolut/Payment state
    let revolutPublicKey: string | null = null;
    let revolutEnvironment: 'production' | 'sandbox' = 'sandbox'; // Added state for environment
    let orderToken: string | null = null;
    let lastOrderId: string | null = null;
    let cardFieldInstance: any = null;
    let cardFieldLoaded: boolean = false;
    let paymentRequestInstance: any = null; // Added for Payment Request Button
    let paymentRequestTargetElement: HTMLElement | null = null; // Added for Payment Request Button target
    let showPaymentRequestButton = false; // Added for Payment Request Button visibility
    let isLoading = false;
    let isButtonCooldown = false;
    let errorMessage: string | null = null;
    let validationErrors: string | null = null;
    let pollTimeoutId: any = null; // Changed type from number | null to any
    let isPollingStopped = false;
    let userEmail: string | null = null;
    let isInitializing = false; // Reintroduce the flag

    // Timeout for card payment submission (UI-level)
    let cardSubmitTimeoutId: any = null; // Changed type from number | null to any

    // CardField target from PaymentForm
    let cardFieldTarget: HTMLElement;
    
    // Subscribe to userProfile store
    // Allowed locales for Revolut card field
    const allowedRevolutLocales = [
        "en", "en-US", "nl", "fr", "de", "cs", "it", "lt", "pl", "pt", "es", "hu", "sk", "ja", "sv", "bg", "ro", "ru", "el", "hr", "auto"
    ];

    // Helper to map user profile language to allowed locale
    function mapLocale(lang: string | null | undefined): typeof allowedRevolutLocales[number] {
        if (!lang) return "en";
        // Try exact match
        if (allowedRevolutLocales.includes(lang)) return lang as typeof allowedRevolutLocales[number];
        // Try language only (e.g., "en" from "en-GB")
        const base = lang.split('-')[0];
        if (allowedRevolutLocales.includes(base)) return base as typeof allowedRevolutLocales[number];
        return "en";
    }

    let darkmode = false;
    let locale: typeof allowedRevolutLocales[number] = "en";

    let userProfileUnsubscribe = userProfile.subscribe(profile => {
        darkmode = !!profile.darkmode;
        locale = mapLocale(profile.language);
    });

    // Helper to get Revolut card field class based on dark mode
    function getRevolutCardFieldClass() {
        return darkmode ? 'revolut-card-field-dark' : 'revolut-card-field-light';
    }

    // --- Fetch user email ---
    async function fetchUserEmail() {
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.settings.user.getEmail), {
                credentials: 'include'
            });
            if (!response.ok) throw new Error('Failed to fetch user email');
            const data = await response.json();
            userEmail = data.email || null;
        } catch (err) {
            userEmail = null;
        }
    }

    // --- Fetch Revolut Config ---
    async function fetchConfig() {
        isLoading = true;
        errorMessage = null;
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.config), {
                credentials: 'include'
            });
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const config = await response.json();
            if (!config.revolut_public_key) throw new Error('Revolut Public Key not found in config response.');
            revolutPublicKey = config.revolut_public_key;
            revolutEnvironment = config.environment === 'production' ? 'production' : 'sandbox'; // Store environment
            console.debug(`[fetchConfig] Loaded config: Environment=${revolutEnvironment}`);
        } catch (error) {
            errorMessage = `Failed to load payment configuration. ${error instanceof Error ? error.message : String(error)}`;
            revolutPublicKey = null; // Ensure key is null on error
            revolutEnvironment = 'sandbox'; // Default to sandbox on error
        } finally {
            isLoading = false;
        }
    }

    // --- Create Payment Order ---
    async function createOrder() {
        if (!revolutPublicKey) {
            errorMessage = 'Cannot create order: Revolut Public Key is missing.';
            return false;
        }
        isLoading = true;
        errorMessage = null;
        orderToken = null;
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.createOrder), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({
                    credits_amount: credits_amount,
                    currency: currency
                })
            });
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(`Failed to create order: ${response.status} ${response.statusText}. ${errorData.detail || ''}`);
            }
            const order = await response.json();
            if (!order.order_token) throw new Error('Order created, but order_token is missing in the response.');
            orderToken = order.order_token; // Keep this for CardField
            lastOrderId = order.order_id;
            // Return structure needed for paymentRequest's createOrder
            return { success: true, publicId: order.order_token };
        } catch (error) {
            errorMessage = `Failed to create payment order. ${error instanceof Error ? error.message : String(error)}`;
            return false;
        } finally {
            isLoading = false;
        }
    }

    // --- Initialize CardField ---
    async function initializeCardField() {
        console.debug('[initializeCardField] called', {
            orderToken,
            cardFieldTarget,
            revolutPublicKey
        });

        if (!orderToken || !cardFieldTarget || !revolutPublicKey) {
            console.warn('[initializeCardField] Missing prerequisites:', {
                orderToken,
                cardFieldTarget,
                revolutPublicKey
            });
            errorMessage = 'Cannot initialize payment field: Missing Order ID, target element, or Public Key.';
            cardFieldLoaded = false;
            return;
        }

        // Destroy previous instance
        if (cardFieldInstance) {
            console.debug('[initializeCardField] Destroying previous cardFieldInstance');
            try { cardFieldInstance.destroy(); } catch (e) { console.warn('[initializeCardField] Error destroying previous instance', e); }
            cardFieldInstance = null;
        }

        validationErrors = null;
        try {
            // Determine the correct mode string ('prod' or 'sandbox') based on the fetched environment
            const revolutMode = revolutEnvironment === 'production' ? 'prod' : 'sandbox';
            console.debug(`[initializeCardField] Creating card field instance with mode: ${revolutMode}...`);
            // Explicitly provide the correct mode ('prod' or 'sandbox') along with the orderToken
            const { createCardField } = await RevolutCheckout(orderToken, revolutMode);
            cardFieldInstance = createCardField({
                target: cardFieldTarget,
                theme: darkmode ? 'dark' : 'light',
                locale: locale as
                    | "en" | "en-US" | "nl" | "fr" | "de" | "cs" | "it" | "lt" | "pl" | "pt" | "es" | "hu" | "sk" | "ja" | "sv" | "bg" | "ro" | "ru" | "el" | "hr" | "auto",
                classes: {
                    default: getRevolutCardFieldClass(),
                    invalid: 'revolut-card-field--invalid'
                },
                onSuccess() {
                    console.debug('[initializeCardField] onSuccess called');
                    // Clear card submit timeout if it exists
                    if (cardSubmitTimeoutId) {
                        clearTimeout(cardSubmitTimeoutId);
                        cardSubmitTimeoutId = null;
                    }
                    errorMessage = null;
                    validationErrors = null;
                    paymentState = 'processing';
                    dispatch('paymentStateChange', { state: paymentState }); // Dispatch state change
                    pollOrderStatus();
                },
                onError(error) {
                    console.debug('[initializeCardField] onError called', error);
                    // Clear card submit timeout if it exists
                    if (cardSubmitTimeoutId) {
                        clearTimeout(cardSubmitTimeoutId);
                        cardSubmitTimeoutId = null;
                    }
                    errorMessage = error?.message ? error.message.replace(/\. /g, '.<br>') : 'Unknown error';
                    validationErrors = null;
                    paymentState = 'idle';
                    dispatch('paymentStateChange', { state: paymentState }); // Dispatch state change
                    isLoading = false;
                    isButtonCooldown = true;
                    setTimeout(() => {
                        isButtonCooldown = false;
                    }, 2000);
                    if (paymentFormComponent) {
                        paymentFormComponent.setPaymentFailed(errorMessage);
                    }
                },
                onValidation(errors) {
                    console.debug('[initializeCardField] onValidation called', errors);
                    // Only show the 'message' field from each error object
                    const concatenatedErrors = errors?.map(e => e?.message || String(e)).join('; ');
                    if (concatenatedErrors?.length) {
                        validationErrors = concatenatedErrors;
                        errorMessage = null;
                    } else {
                        validationErrors = null;
                    }
                }
            });
            cardFieldLoaded = true;
            console.debug('[initializeCardField] Card field initialized successfully');
        } catch (error) {
            console.error('[initializeCardField] Error initializing card field', error);
            errorMessage = `Failed to initialize payment field. ${error instanceof Error ? error.message : String(error)}`;
            cardFieldInstance = null;
            cardFieldLoaded = false;
        }
        console.debug('[initializeCardField] function end', { cardFieldLoaded, cardFieldInstance });
    }

    // --- Initialize Payment Request Button (Apple Pay / Google Pay) ---
    async function initializePaymentRequest() {
        console.debug('[initializePaymentRequest] called', {
            revolutPublicKey,
            paymentRequestTargetElement,
            purchasePrice,
            currency
        });

        if (!revolutPublicKey || !paymentRequestTargetElement || !purchasePrice || !currency) {
            console.warn('[initializePaymentRequest] Missing prerequisites:', {
                revolutPublicKey,
                paymentRequestTargetElement,
                purchasePrice,
                currency
            });
            // Don't show error message here, just prevent initialization
            showPaymentRequestButton = false;
            return;
        }

        // Destroy previous instance if exists
        if (paymentRequestInstance) {
            console.debug('[initializePaymentRequest] Destroying previous paymentRequestInstance');
            try { paymentRequestInstance.destroy(); } catch (e) { console.warn('[initializePaymentRequest] Error destroying previous instance', e); }
            paymentRequestInstance = null;
        }

        try {
            console.debug('[initializePaymentRequest] Initializing RevolutCheckout.payments...');
            // Note: We only need the 'payments' object once, could optimize later
            const { paymentRequest } = await RevolutCheckout.payments({
                locale: locale as "en" | "en-US" | "nl" | "fr" | "de" | "cs" | "it" | "lt" | "pl" | "pt" | "es" | "hu" | "sk" | "ja" | "sv" | "bg" | "ro" | "ru" | "el" | "hr" | "auto", // Explicit type assertion
                publicToken: revolutPublicKey
            });

            console.debug('[initializePaymentRequest] Creating payment request instance...');
            paymentRequestInstance = paymentRequest(paymentRequestTargetElement, {
                currency: currency,
                amount: Math.round(purchasePrice * 100), // Amount in lowest denomination (cents/pence)
                createOrder: async () => {
                    console.debug('[paymentRequest.createOrder] called');
                    // Reuse the existing createOrder logic, but ensure it returns the publicId
                    const orderResult = await createOrder();
                    if (orderResult && orderResult.success && orderResult.publicId) {
                        console.debug('[paymentRequest.createOrder] Order created successfully:', orderResult.publicId);
                        return { publicId: orderResult.publicId };
                    } else {
                        console.error('[paymentRequest.createOrder] Failed to create order for payment request.');
                        throw new Error('Failed to create payment order.');
                    }
                },
                onSuccess() {
                    console.debug('[paymentRequest.onSuccess] called');
                    // Similar to CardField success: clear errors, set processing, start polling
                    errorMessage = null;
                    validationErrors = null;
                    paymentState = 'processing';
                    dispatch('paymentStateChange', { state: paymentState }); // Dispatch state change
                    // Ensure we have the lastOrderId from the createOrder call within paymentRequest
                    // If createOrder was successful, lastOrderId should be set.
                    if (lastOrderId) {
                        pollOrderStatus();
                    } else {
                        console.error('[paymentRequest.onSuccess] lastOrderId is missing after successful payment request. Cannot poll status.');
                        errorMessage = 'Payment successful, but status verification failed. Please check your account.';
                        paymentState = 'idle'; // Revert state if polling can't start
                        dispatch('paymentStateChange', { state: paymentState }); // Dispatch state change
                        }
                    },
                onError(error) {
                    console.debug('[paymentRequest.onError] called', error);
                    // Similar to CardField error handling
                    errorMessage = error?.message ? error.message.replace(/\. /g, '.<br>') : 'Payment failed via Apple Pay/Google Pay.';
                    validationErrors = null; // Clear card validation errors
                    paymentState = 'idle';
                    dispatch('paymentStateChange', { state: paymentState }); // Dispatch state change
                    isLoading = false; // Ensure loading state is reset
                    isButtonCooldown = true; // Apply cooldown if needed
                    setTimeout(() => { isButtonCooldown = false; }, 2000);
                    if (paymentFormComponent) {
                        paymentFormComponent.setPaymentFailed(errorMessage);
                    }
                    // Destroy the instance on error? Maybe not, user might retry.
                    // Consider re-creating the order if necessary before retry.
                    orderToken = null; // Reset order token as it might be invalid
                    lastOrderId = null;
                },
                // Add other options like buttonStyle if needed
                buttonStyle: {
                    radius: "small",
                    size: "large", // Match card payment button height?
                    variant: darkmode ? "dark" : "light",
                    action: "buy"
                }
            });

            console.debug('[initializePaymentRequest] Checking if payment can be made...');
            const method = await paymentRequestInstance.canMakePayment();
            console.debug('[initializePaymentRequest] canMakePayment result:', method);
            if (method) { // 'applePay' or 'googlePay'
                paymentRequestInstance.render();
                showPaymentRequestButton = true;
                console.debug('[initializePaymentRequest] Payment request button rendered.');
            } else {
                showPaymentRequestButton = false;
                paymentRequestInstance.destroy(); // Clean up if no method available
                paymentRequestInstance = null;
                console.debug('[initializePaymentRequest] No payment method available, instance destroyed.');
            }

        } catch (error) {
            console.error('[initializePaymentRequest] Error initializing payment request', error);
            errorMessage = `Failed to initialize Apple Pay/Google Pay. ${error instanceof Error ? error.message : String(error)}`;
            paymentRequestInstance = null;
            showPaymentRequestButton = false;
        }
        console.debug('[initializePaymentRequest] function end', { showPaymentRequestButton, paymentRequestInstance });
    }


    // --- Poll Backend for Order Status ---
    async function pollOrderStatus() {
        if (!orderToken) {
            errorMessage = 'Order token missing. Cannot verify payment status.';
            return;
        }
        let attempts = 0;
        const maxAttempts = 5; // Reduced from 20 for a ~10 second timeout
        const pollInterval = 2000;
        isPollingStopped = false;
        let orderId = lastOrderId;
        if (!orderId) {
            errorMessage = 'Order ID missing. Cannot verify payment status.';
            return;
        }
        async function poll() {
            if (isPollingStopped) return;
            attempts++;
            try {
                const response = await fetch(getApiEndpoint(apiEndpoints.payments.orderStatus), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify({ order_id: orderId })
                });
                if (!response.ok) throw new Error(`Failed to fetch order status: ${response.status} ${response.statusText}`);
                const data = await response.json();
                const state = data.state;
                if (typeof state === 'string' && state.toLowerCase() === 'completed') {
                    paymentState = 'success';
                    dispatch('paymentStateChange', { state: paymentState }); // Dispatch state change
                    errorMessage = null;
                    validationErrors = null;
                    orderToken = null;
                    lastOrderId = null;
                    isPollingStopped = true;
                    if (pollTimeoutId) clearTimeout(pollTimeoutId);
                    pollTimeoutId = null;

                    // Update user profile store with new credits from response
                    if (typeof data.current_credits === 'number') {
                        console.log(`Updating profile credits to: ${data.current_credits}`);
                        updateProfile({ credits: data.current_credits });
                    } else {
                        console.warn('Order completed, but current_credits not found in response. Credits may be stale.');
                    }
                    return;
                } else if (typeof state === 'string' && (state.toLowerCase() === 'failed' || state.toLowerCase() === 'cancelled')) {
                    paymentState = 'idle';
                    dispatch('paymentStateChange', { state: paymentState }); // Dispatch state change
                    errorMessage = 'Payment failed or was cancelled. Please try again.';
                    validationErrors = null;
                    orderToken = null;
                    lastOrderId = null;
                    isPollingStopped = true;
                    if (pollTimeoutId) clearTimeout(pollTimeoutId);
                    pollTimeoutId = null;
                    if (paymentFormComponent) {
                        paymentFormComponent.setPaymentFailed();
                    }
                    return;
                } else {
                    if (attempts < maxAttempts && !isPollingStopped) {
                        pollTimeoutId = setTimeout(poll, pollInterval);
                    } else if (!isPollingStopped) {
                        errorMessage = 'Payment processing timed out. Please check your order status later.';
                        paymentState = 'idle';
                        dispatch('paymentStateChange', { state: paymentState }); // Dispatch state change
                        validationErrors = null;
                        orderToken = null;
                        lastOrderId = null;
                        isPollingStopped = true;
                        if (pollTimeoutId) clearTimeout(pollTimeoutId);
                        pollTimeoutId = null;
                        if (paymentFormComponent) {
                            paymentFormComponent.setPaymentFailed();
                        }
                    }
                }
            } catch (err) {
                errorMessage = `Error checking payment status: ${err instanceof Error ? err.message : String(err)}`;
                paymentState = 'idle';
                dispatch('paymentStateChange', { state: paymentState }); // Dispatch state change
                validationErrors = null;
                orderToken = null;
                lastOrderId = null;
                isPollingStopped = true;
                if (pollTimeoutId) clearTimeout(pollTimeoutId);
                pollTimeoutId = null;
                if (paymentFormComponent) {
                    paymentFormComponent.setPaymentFailed();
                }
            }
        }
        if (pollTimeoutId) clearTimeout(pollTimeoutId);
        pollTimeoutId = null;
        isPollingStopped = false;
        pollTimeoutId = setTimeout(poll, 1500);
    }

    // --- Consent handler ---
    function handleConsentChanged(event) {
        hasConsentedToLimitedRefund = event.detail.consented;
        if (hasConsentedToLimitedRefund) {
            dispatch('consentGiven', { consented: true });
        }
        // No longer need to toggle showPaymentForm; overlay will fade out on consent
        // Optionally, can dispatch an event if parent needs to know
        if (requireConsent && hasConsentedToLimitedRefund) {
            setTimeout(() => {
                dispatch('paymentFormVisibility', { visible: true });
            }, 300);
        }
    }

    // Notify parent when payment form visibility changes
    /* showPaymentForm is removed; no need to track its state for parent notification */

    // Watch payment state and return to form on failure
    // Removed: auto-reset of paymentState from 'failure' to 'idle' (no longer needed, as we set to 'idle' on error directly)

    // --- Automatically load and initialize payment methods ---

    // Single reactive trigger for initialization
    // Reactive trigger for initialization
    // Runs when:
    // - Payment is idle
    // - Not currently initializing
    // - No general error message is displayed (prevents retry loops on persistent errors)
    // - At least one payment method target element is available
    // Reactive trigger for initialization
    // Runs when:
    // - Payment is idle
    // - Not currently initializing
    // - No general error message is displayed
    // - AND at least one payment method needs initialization:
    //   - Card field target exists but instance doesn't, OR
    //   - Payment request target exists, instance doesn't, and env is production
    $: needsCardInit = cardFieldTarget && !cardFieldInstance;
    $: needsPaymentRequestInit = revolutEnvironment === 'production' && paymentRequestTargetElement && !paymentRequestInstance;

    $: if (
        paymentState === 'idle' &&
        !isInitializing &&
        !errorMessage &&
        (needsCardInit || needsPaymentRequestInit) // <-- Check if actual init is needed
       ) {
        console.debug('[Reactive Trigger] Conditions met for initialization. Setting flag and scheduling.', { needsCardInit, needsPaymentRequestInit });
        isInitializing = true; // Set flag BEFORE starting async work
        tick().then(async () => {
            try {
                // Clear previous errors before attempting initialization
                errorMessage = null;
                validationErrors = null;
                await initializePaymentMethods(); // Call the main async logic function
            } catch (error) {
                 console.error('[Reactive Trigger] Error during initializePaymentMethods:', error);
                 // Set error message state if initialization fails
                 errorMessage = `Initialization failed: ${error instanceof Error ? error.message : String(error)}`;
                 // Ensure state is idle on failure
                 paymentState = 'idle';
                 dispatch('paymentStateChange', { state: paymentState }); // Dispatch state change
            } finally {
                console.debug('[Reactive Trigger] Clearing isInitializing flag.');
                isInitializing = false; // Clear flag AFTER async work (or error)
            }
        });
    }

    // Main async initialization logic
    async function initializePaymentMethods() {
        console.debug('[initializePaymentMethods] Starting...');

        // Double check state just in case (should be prevented by reactive trigger guard)
        if (paymentState !== 'idle') {
             console.warn('[initializePaymentMethods] Called but paymentState is not idle. Aborting.');
             return;
        }

        // 1. Fetch Config (if needed)
        if (!revolutPublicKey) {
            console.debug('[initializePaymentMethods] Fetching config...');
            await fetchConfig();
            if (!revolutPublicKey) {
                console.error('[initializePaymentMethods] Config fetch failed. Aborting.');
                // fetchConfig should set errorMessage
                return; // Stop initialization if config fails
            }
        } else {
             console.debug('[initializePaymentMethods] Config already available.');
        }

        // 2. Create Order (if needed) - CRITICAL: Check token *before* calling createOrder
        if (!orderToken) {
            console.debug('[initializePaymentMethods] Order token missing. Creating order...');
            const orderResult = await createOrder(); // Sets global orderToken on success
            if (!orderResult || !orderResult.success) {
                console.error('[initializePaymentMethods] Order creation failed. Aborting.');
                // createOrder should set errorMessage
                return; // Stop initialization if order creation fails
            }
             console.debug('[initializePaymentMethods] Order created successfully.');
        } else {
             console.debug('[initializePaymentMethods] Order token already exists.');
        }

        // Ensure order token is definitely available now before proceeding
        if (!orderToken) {
             console.error('[initializePaymentMethods] Order token still missing after creation check. Aborting.');
             errorMessage = 'Failed to obtain payment session token.'; // Set a generic error
             return;
        }

        // Wait for potential DOM updates after config/order steps
        await tick();

        // 3. Initialize Card Field (if target ready and instance not created)
        // Check instance existence again inside async flow
        if (cardFieldTarget && !cardFieldInstance) {
            console.debug('[initializePaymentMethods] Initializing Card Field...');
            await initializeCardField(); // Uses global orderToken
        } else {
             console.debug('[initializePaymentMethods] Skipping Card Field init.', { hasTarget: !!cardFieldTarget, hasInstance: !!cardFieldInstance });
        }

        // 4. Initialize Payment Request Button (if conditions met)
        // Check instance existence again inside async flow
        if (revolutEnvironment === 'production' && paymentRequestTargetElement && !paymentRequestInstance) {
            console.debug('[initializePaymentMethods] Initializing Payment Request Button...');
            await initializePaymentRequest(); // Uses global publicKey etc.
        } else {
             console.debug('[initializePaymentMethods] Skipping Payment Request init.', { isProd: revolutEnvironment === 'production', hasTarget: !!paymentRequestTargetElement, hasInstance: !!paymentRequestInstance });
             if (revolutEnvironment !== 'production') {
                 showPaymentRequestButton = false; // Ensure button hidden if skipped
             }
        }
        console.debug('[initializePaymentMethods] Finished.');
    }

    // --- Cleanup on destroy ---
    onMount(() => {
        fetchUserEmail();
        // Initial call in case component mounts in idle state with targets ready
        // The reactive trigger ($:) will handle the initial call automatically when targets become available.
        // No explicit call needed here anymore.
        // tick().then(() => initializePaymentMethods()); // REMOVED
        return () => {
            console.debug('[Payment.svelte] onDestroy cleanup');
            if (cardFieldInstance) {
                console.debug('Destroying cardFieldInstance');
                try { cardFieldInstance.destroy(); } catch (e) { console.warn('Error destroying cardFieldInstance', e); }
                cardFieldInstance = null;
            }
            if (paymentRequestInstance) {
                console.debug('Destroying paymentRequestInstance');
                try { paymentRequestInstance.destroy(); } catch (e) { console.warn('Error destroying paymentRequestInstance', e); }
                paymentRequestInstance = null;
            }
            isPollingStopped = true;
            if (pollTimeoutId) {
                console.debug('Clearing poll timeout');
                clearTimeout(pollTimeoutId);
                pollTimeoutId = null;
            }
             if (cardSubmitTimeoutId) {
                console.debug('Clearing card submit timeout');
                clearTimeout(cardSubmitTimeoutId);
                cardSubmitTimeoutId = null;
            }
            if (userProfileUnsubscribe) {
                console.debug('Unsubscribing from userProfile');
                userProfileUnsubscribe();
            }
        };
    });
    // Handle PaymentForm submit event to set loading state immediately
    function handleFormSubmit() {
        isLoading = true;
        // Clear any previous card submit timeout
        if (cardSubmitTimeoutId) {
            clearTimeout(cardSubmitTimeoutId);
            cardSubmitTimeoutId = null;
        }
        // Start a timeout for card payment UI response (e.g., 12 seconds)
        cardSubmitTimeoutId = setTimeout(() => {
            errorMessage = 'Payment could not be processed in time. Please try again.';
            paymentState = 'idle';
            dispatch('paymentStateChange', { state: paymentState }); // Dispatch state change
            isLoading = false;
            // Clean up card field instance and order state
            if (cardFieldInstance) {
                try { cardFieldInstance.destroy(); } catch {}
                cardFieldInstance = null;
            }
            cardFieldLoaded = false;
            orderToken = null;
            lastOrderId = null;
            if (paymentFormComponent && typeof paymentFormComponent.setPaymentFailed === 'function') {
                paymentFormComponent.setPaymentFailed(errorMessage);
            }
            cardSubmitTimeoutId = null;
        }, 12000); // 12 seconds
    }
</script>

<div class="payment-component {compact ? 'compact' : ''}">
    {#if paymentState === 'processing' || paymentState === 'success'}
        <ProcessingPayment
            state={paymentState}
            {isGift}
        />
    {:else}
        <div class="payment-form-overlay-wrapper">
            <PaymentForm
                bind:this={paymentFormComponent}
                purchasePrice={purchasePrice}
                currency={currency}
                cardFieldInstance={cardFieldInstance}
                userEmail={userEmail}
                bind:cardFieldTarget={cardFieldTarget}
                bind:paymentRequestTargetElement={paymentRequestTargetElement}
                cardFieldLoaded={cardFieldLoaded}
                showPaymentRequestButton={showPaymentRequestButton}
                hasConsentedToLimitedRefund={hasConsentedToLimitedRefund}
                validationErrors={validationErrors}
                paymentError={errorMessage}
                isLoading={isLoading}
                isButtonCooldown={isButtonCooldown}
                on:submitPayment={handleFormSubmit}
            />
            {#if requireConsent && !hasConsentedToLimitedRefund}
                <div class="consent-overlay" transition:fade>
                    <LimitedRefundConsent
                        bind:hasConsentedToLimitedRefund={hasConsentedToLimitedRefund}
                        on:consentChanged={handleConsentChanged}
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
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: var(--color-grey-20);
        z-index: 10;
        display: flex;
        align-items: center;
        justify-content: center;
        pointer-events: all;
        /* Optional: add a slight box-shadow for separation */
        box-shadow: 0 0 8px 0 rgba(0,0,0,0.04);
        /* Prevent interaction with underlying payment form */
    }

    .consent-overlay :global(*) {
        pointer-events: auto;
    }

    .compact {
        max-width: 500px;
        margin: 0 auto;
    }
</style>
