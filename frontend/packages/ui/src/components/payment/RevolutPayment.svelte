<script lang="ts">
    import { onMount, createEventDispatcher, tick } from 'svelte';
    import RevolutCheckout from '@revolut/checkout';
    import { apiEndpoints, getApiEndpoint } from '../../config/api';
    import { userProfile, updateProfile } from '../../stores/userProfile';

    const dispatch = createEventDispatcher();

    export let purchasePrice: number = 20;
    export let currency: string = 'EUR';
    export let credits_amount: number = 21000;
    export let paymentFormComponent: any;

    let revolutPublicKey: string | null = null;
    let revolutEnvironment: 'production' | 'sandbox' = 'sandbox';
    let orderToken: string | null = null;
    let lastOrderId: string | null = null;
    let cardFieldInstance: any = null;
    let cardFieldLoaded: boolean = false;
    let paymentRequestInstance: any = null;
    let paymentRequestTargetElement: HTMLElement | null = null;
    let showPaymentRequestButton = false;
    let isLoading = false;
    let errorMessage: string | null = null;
    let validationErrors: string | null = null;
    let pollTimeoutId: any = null;
    let isPollingStopped = false;
    let cardSubmitTimeoutId: any = null;
    let cardFieldTarget: HTMLElement;
    
    const allowedRevolutLocales = [
        "en", "en-US", "nl", "fr", "de", "cs", "it", "lt", "pl", "pt", "es", "hu", "sk", "ja", "sv", "bg", "ro", "ru", "el", "hr", "auto"
    ];

    function mapLocale(lang: string | null | undefined): typeof allowedRevolutLocales[number] {
        if (!lang) return "en";
        if (allowedRevolutLocales.includes(lang)) return lang as typeof allowedRevolutLocales[number];
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

    function getRevolutCardFieldClass() {
        return darkmode ? 'revolut-card-field-dark' : 'revolut-card-field-light';
    }

    async function fetchConfig() {
        isLoading = true;
        errorMessage = null;
        try {
            const response = await fetch(getApiEndpoint(apiEndpoints.payments.config), {
                credentials: 'include'
            });
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const config = await response.json();
            if (config.provider !== 'revolut') throw new Error('Incorrect payment provider configured.');
            if (!config.public_key) throw new Error('Revolut Public Key not found in config response.');
            revolutPublicKey = config.public_key;
            revolutEnvironment = config.environment === 'production' ? 'production' : 'sandbox';
        } catch (error) {
            errorMessage = `Failed to load payment configuration. ${error instanceof Error ? error.message : String(error)}`;
            revolutPublicKey = null;
            revolutEnvironment = 'sandbox';
        } finally {
            isLoading = false;
        }
    }

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
            orderToken = order.order_token;
            lastOrderId = order.order_id;
            return { success: true, publicId: order.order_token };
        } catch (error) {
            errorMessage = `Failed to create payment order. ${error instanceof Error ? error.message : String(error)}`;
            return false;
        } finally {
            isLoading = false;
        }
    }

    async function initializeCardField() {
        if (!orderToken || !cardFieldTarget || !revolutPublicKey) {
            errorMessage = 'Cannot initialize payment field: Missing Order ID, target element, or Public Key.';
            cardFieldLoaded = false;
            return;
        }

        if (cardFieldInstance) {
            try { cardFieldInstance.destroy(); } catch (e) { console.warn('Error destroying previous instance', e); }
            cardFieldInstance = null;
        }

        validationErrors = null;
        try {
            const revolutMode = revolutEnvironment === 'production' ? 'prod' : 'sandbox';
            const { createCardField } = await RevolutCheckout(orderToken, revolutMode);
            cardFieldInstance = createCardField({
                target: cardFieldTarget,
                theme: darkmode ? 'dark' : 'light',
                locale: locale as "en" | "en-US" | "nl" | "fr" | "de" | "cs" | "it" | "lt" | "pl" | "pt" | "es" | "hu" | "sk" | "ja" | "sv" | "bg" | "ro" | "ru" | "el" | "hr" | "auto",
                classes: {
                    default: getRevolutCardFieldClass(),
                    invalid: 'revolut-card-field--invalid'
                },
                onSuccess() {
                    if (cardSubmitTimeoutId) {
                        clearTimeout(cardSubmitTimeoutId);
                        cardSubmitTimeoutId = null;
                    }
                    errorMessage = null;
                    validationErrors = null;
                    dispatch('paymentSuccess');
                },
                onError(error) {
                    if (cardSubmitTimeoutId) {
                        clearTimeout(cardSubmitTimeoutId);
                        cardSubmitTimeoutId = null;
                    }
                    errorMessage = error?.message ? error.message.replace(/\. /g, '.<br>') : 'Unknown error';
                    validationErrors = null;
                    isLoading = false;
                    if (paymentFormComponent) {
                        paymentFormComponent.setPaymentFailed(errorMessage);
                    }
                },
                onValidation(errors) {
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
        } catch (error) {
            errorMessage = `Failed to initialize payment field. ${error instanceof Error ? error.message : String(error)}`;
            cardFieldInstance = null;
            cardFieldLoaded = false;
        }
    }
    
    onMount(async () => {
        await fetchConfig();
        await createOrder();
        await tick();
        initializeCardField();
    });

</script>

<div id="revolut-payment-form">
    <!-- Revolut-specific form elements will be mounted here -->
</div>
