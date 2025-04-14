<script lang="ts">
    import { text } from '@repo/ui'; // Revert to original path as requested
    import { createEventDispatcher, tick, onMount, onDestroy } from 'svelte'; // Added onDestroy
    import InputWarning from '../common/InputWarning.svelte';
    import { getWebsiteUrl, routes } from '../../config/links';
    import { fade } from 'svelte/transition';
    import RevolutCheckout from '@revolut/checkout';
    import type { RevolutCheckoutInstance, Mode } from '@revolut/checkout'; // Remove CardField type import, rely on inference
    import { getApiUrl, apiEndpoints } from '../../config/api'; // Import API config

    const dispatch = createEventDispatcher();

    // Props
    export let purchasePrice: number = 20;
    export let currency: string = 'EUR';
    export let credits_amount: number; // IMPORTANT: This must be passed from the parent
    // export let showSensitiveData: boolean = false; // No longer needed for Revolut element
    export let initialPaymentDetails = null; // Keep for name field if needed

    // --- Revolut State ---
    let revolutCheckout: RevolutCheckoutInstance | null = null;
    let cardFieldInstance: any | null = null; // Use 'any' or let TS infer type
    let orderToken: string | null = null;
    let isLoadingRevolut = true; // Track loading state
    let revolutError: string | null = null; // Store errors from Revolut init/payment
    let revolutPublicKey: string | null = null; // Store public key if needed later (e.g., for upsell)
    let revolutEnvironment: 'sandbox' | 'production' | null = null;

    // --- Form State ---
    let nameOnCard = ''; // Keep name field for now

    // Input element references
    let nameInput: HTMLInputElement;
    let cardFieldContainer: HTMLDivElement; // Target for Revolut element

    // Validation states
    let nameError = '';
    let showNameWarning = false;

    // Payment failure state - handled by Revolut's onError now, but keep for potential UI feedback
    let paymentFailed = false; // Can be set in onError

    // Track if form was submitted
    let attemptedSubmit = false;

    // Removed userProfile subscription and customerEmail variable

    // --- Initialization ---
    onMount(() => {
        // Pre-fill name if available from previous attempt
        if (initialPaymentDetails) {
            nameOnCard = initialPaymentDetails.nameOnCard || '';
            // If we had a general payment failure state passed in
            if (initialPaymentDetails.failed) {
                setPaymentFailed("Previous payment attempt failed."); // Pass a generic message
            }
        }

        if (credits_amount === undefined || credits_amount === null) {
             console.error("PaymentForm Error: credits_amount prop is missing or invalid.");
             revolutError = "Configuration error: Credits amount missing.";
             isLoadingRevolut = false;
        } else {
            // Fetch config and initialize Revolut
            initializeRevolut();
        }
    });

    onDestroy(() => {
        // Destroy card field instance if it exists
        cardFieldInstance?.destroy();
        console.debug("PaymentForm destroyed, Revolut card field instance destroyed.");
    });


    // Function to fetch order token and initialize Revolut Card Field
    async function initializeRevolut() {
        isLoadingRevolut = true;
        revolutError = null;
        orderToken = null;
        // Destroy previous instance if exists
        if (cardFieldInstance) {
            cardFieldInstance.destroy();
            cardFieldInstance = null;
            console.debug("Destroyed previous Revolut card field instance.");
        }

        // Removed check for customerEmail here, it's fetched later in handleBuyClick
        if (credits_amount === undefined || credits_amount === null || credits_amount <= 0) {
             revolutError = "Invalid credits amount specified.";
             isLoadingRevolut = false;
             console.error(`Revolut Init Error: Invalid credits_amount: ${credits_amount}`);
             dispatch('paymentFailure', { message: revolutError }); // Notify parent
             return;
        }


        try {
            // 1. Fetch Payment Config
            console.debug("Fetching payment config...");
            const configResponse = await fetch(getApiUrl() + apiEndpoints.payments.config, {
                 method: 'GET',
                 headers: { 'Accept': 'application/json' },
                 credentials: 'include'
            });
            if (!configResponse.ok) {
                throw new Error(`Failed to fetch payment config: ${configResponse.status} ${configResponse.statusText}`);
            }
            const configData = await configResponse.json();
            revolutPublicKey = configData.revolut_public_key;
            revolutEnvironment = configData.environment;
            console.debug(`Payment config received: Environment=${revolutEnvironment}`);

            // 2. Create Order to get Order Token
            const orderPayload = {
                amount: Math.round(purchasePrice * 100), // Convert to cents/smallest unit
                currency: currency,
                credits_amount: credits_amount // Use the prop value
            };
            console.debug("Creating payment order with payload:", orderPayload);
            const orderResponse = await fetch(getApiUrl() + apiEndpoints.payments.createOrder, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify(orderPayload)
            });

            if (!orderResponse.ok) {
                 const errorData = await orderResponse.json().catch(() => ({ detail: `${orderResponse.status} ${orderResponse.statusText}` }));
                 throw new Error(`Failed to create payment order: ${errorData.detail || orderResponse.statusText}`);
            }
            const orderData = await orderResponse.json();
            orderToken = orderData.order_token;
            console.debug(`Order token received: ${orderToken ? 'OK' : 'MISSING'}`);


            if (!orderToken) {
                throw new Error("Received empty order token from backend.");
            }

            // 3. Initialize Revolut Checkout Widget
            console.debug(`Initializing RevolutCheckout with token for ${revolutEnvironment} env.`);
            revolutCheckout = await RevolutCheckout(orderToken, revolutEnvironment as Mode); // Pass environment, cast type

            if (!revolutCheckout) {
                 throw new Error("Failed to initialize Revolut Checkout.");
            }

            // 4. Create and Mount Card Field
            console.debug("Creating Revolut card field instance...");
            cardFieldInstance = revolutCheckout.createCardField({
                target: cardFieldContainer, // Mount to our div
                // --- Event Handlers ---
                onSuccess() {
                    console.info("Revolut payment successful callback triggered.");
                    revolutError = null;
                    paymentFailed = false;
                    // Dispatch success event to parent (Payment.svelte)
                    dispatch('paymentSuccess', {
                        nameOnCard: nameOnCard,
                        amount: credits_amount, // Pass the credits amount
                        price: purchasePrice,
                        currency: currency
                        // Note: lastFourDigits not available here
                    });
                },
                onError(error) {
                    console.error("Revolut payment error callback triggered:", error);
                    const message = typeof error === 'string' ? error : (error?.message || "Unknown payment error");
                    revolutError = `Payment failed: ${message}`;
                    paymentFailed = true;
                     // Dispatch failure event to parent
                    dispatch('paymentFailure', { message: revolutError });
                },
                 onCancel() {
                    console.info("Revolut payment cancelled by user.");
                    revolutError = "Payment cancelled."; // Provide feedback
                    // Optionally dispatch a specific cancel event
                    dispatch('paymentCancel');
                },
                onValidation(errors) {
                    // Optional: Handle real-time validation errors if needed
                    // This provides an array of { field: string, message: string }
                    console.debug("Revolut validation event:", errors);
                    // You could potentially map these errors to UI elements if desired,
                    // but Revolut's element usually shows its own validation hints.
                },
                // --- Styling (Example - Adapt to your CSS) ---
                styles: {
                    default: { // Base styles
                        color: 'var(--color-text)', // Use your CSS variable
                        backgroundColor: 'var(--color-input-bg)',
                        padding: '14px 12px', // Match your input padding
                        borderRadius: 'var(--radius-input)',
                        border: '1px solid var(--color-input-border)',
                        fontFamily: 'inherit',
                        fontSize: '16px', // Match your input font size
                        // '::placeholder': { // Cannot style pseudo-elements directly here
                        //     color: 'var(--color-grey-60)'
                        // }
                    },
                    focused: { // Correct key is 'focused'
                        borderColor: 'var(--color-primary)',
                        boxShadow: '0 0 0 1px var(--color-primary)' // Adjusted focus style
                    },
                    invalid: { // Styles when the field has validation errors
                        borderColor: 'var(--color-error)',
                        color: 'var(--color-error)'
                    },
                },
                // --- Other Options ---
                locale: 'en', // Or dynamically set based on user preference
            });

            // Mount the instance
            console.debug("Mounting Revolut card field instance...");
            cardFieldInstance.mount();
            console.info("Revolut Card Field initialized and mounted.");

        } catch (error) {
            console.error("Error initializing Revolut:", error);
            revolutError = error instanceof Error ? error.message : String(error) || "Failed to initialize payment form.";
            dispatch('paymentFailure', { message: revolutError }); // Notify parent
        } finally {
            isLoadingRevolut = false;
        }
    }

    // Re-add function to handle the secure payment info click
    function handleSecurePaymentInfoClick() {
        window.open(getWebsiteUrl(routes.docs.userGuide_signup_10_2), '_blank');
    }


    // --- Keep Name Validation ---
    function validateName(name: string): boolean {
        if (name.trim().length < 3) {
            nameError = $text('signup.name_too_short.text');
            showNameWarning = name.trim().length > 0 || attemptedSubmit;
            return false;
        }
        nameError = '';
        showNameWarning = false;
        return true;
    }

    // --- Updated Buy Click Handler ---
    async function handleBuyClick() {
        console.debug("Buy button clicked.");
        attemptedSubmit = true;
        revolutError = null; // Clear previous errors

        // 1. Validate local fields (just Name for now)
        const isNameValid = validateName(nameOnCard);
        if (!isNameValid) {
            console.warn("Name validation failed.");
            nameInput?.focus(); // Focus the name input if invalid
            return;
        }

        // 2. Check if cardFieldInstance is ready
        if (!cardFieldInstance) {
            revolutError = "Payment form is not ready. Please wait or refresh.";
            console.error("handleBuyClick Error: cardFieldInstance not available.");
            dispatch('paymentFailure', { message: revolutError }); // Notify parent
            return;
        }

         // 3. Fetch user email from backend just-in-time
         let fetchedEmail: string | null = null;
         try {
             console.debug("Fetching user email for payment submission...");
             const emailResponse = await fetch(getApiUrl() + apiEndpoints.settings.user.getEmail, {
                 method: 'GET',
                 headers: { 'Accept': 'application/json' },
                 credentials: 'include'
             });
             if (!emailResponse.ok) {
                 const errorText = await emailResponse.text();
                 throw new Error(`Failed to fetch email: ${emailResponse.status} ${errorText}`);
             }
             const emailData = await emailResponse.json();
             fetchedEmail = emailData.email;
             if (!fetchedEmail) {
                 throw new Error("Email not found in backend response.");
             }
             console.debug("User email fetched successfully.");
         } catch (error) {
             console.error("Error fetching user email:", error);
             revolutError = "Could not retrieve user email for payment. Please try again.";
             dispatch('paymentFailure', { message: revolutError }); // Notify parent
             return; // Stop submission
         }
 
          // 4. Dispatch 'startPayment' to parent to indicate processing start
          console.info("Dispatching startPaymentProcessing event.");
          dispatch('startPaymentProcessing');
 
         // 5. Submit the Revolut Card Field with fetched email
         try {
             console.debug(`Submitting card field with fetched email and name: ${nameOnCard}`);
             await cardFieldInstance.submit({
                 email: fetchedEmail, // Use the fetched email
                 name: nameOnCard, // Pass the name from our input field
             });
             console.debug("cardField.submit() called successfully.");
             // Success/Error is handled by the onSuccess/onError callbacks defined in createCardField
         } catch (error) {
              // This catch might handle errors during the *initiation* of submit,
              // but payment success/failure is typically via the callbacks.
             console.error("Error calling cardField.submit():", error);
             const message = error instanceof Error ? error.message : String(error) || "Unknown submission error";
             revolutError = `Failed to initiate payment: ${message}`;
             paymentFailed = true;
             dispatch('paymentFailure', { message: revolutError }); // Notify parent
         }
    }

    // --- Keep Error Handling Functions ---
    export function resetErrors() {
        console.debug("Resetting errors.");
        nameError = '';
        showNameWarning = false;
        attemptedSubmit = false;
        paymentFailed = false;
        revolutError = null;
        // Revolut element handles its own visual state for errors
    }

    // Modified setPaymentFailed to accept a message
    export function setPaymentFailed(message: string = "Payment failed.") {
        console.warn(`Setting payment failed state: ${message}`);
        paymentFailed = true;
        revolutError = message; // Display a general error message
    }

</script>

<div class="payment-form" class:loading={isLoadingRevolut} in:fade={{ duration: 300 }}>
    {#if isLoadingRevolut}
        <div class="loading-indicator">Loading Payment Form...</div>
    {:else if revolutError}
         <div class="error-message color-error">
             <span class="clickable-icon icon_warning"></span>
             {revolutError}
             {#if revolutError.includes("initialize") || revolutError.includes("token")} <!-- Allow retry on init errors -->
                 <button class="text-button" on:click={initializeRevolut}>Retry</button>
             {/if}
         </div>
    {/if}

    <div class="color-grey-60 payment-title">
        {@html $text('signup.pay_with_card.text')}
    </div>

    <form on:submit|preventDefault={handleBuyClick}>
        <!-- Keep Name Input -->
        <div class="input-group">
            <div class="input-wrapper">
                <span class="clickable-icon icon_user"></span>
                <input
                    bind:this={nameInput}
                    type="text"
                    bind:value={nameOnCard}
                    placeholder={$text('signup.full_name_on_card.text')}
                    on:blur={() => validateName(nameOnCard)}
                    class:error={!!nameError}
                    required
                    autocomplete="name"
                    disabled={isLoadingRevolut || !!revolutError || !cardFieldInstance}
                />
                {#if showNameWarning && nameError}
                    <InputWarning
                        message={nameError}
                        target={nameInput}
                    />
                {/if}
            </div>
        </div>

        <!-- Revolut Card Field Container -->
        <div class="input-group revolut-card-field-wrapper">
             <div bind:this={cardFieldContainer} id="revolut-card-field">
                 <!-- Revolut Card Field will be mounted here -->
                 {#if isLoadingRevolut}<!-- Show text while loading element -->
                    <span class="color-grey-60">Loading card details...</span>
                 {/if}
             </div>
        </div>

        <button
            type="submit"
            class="buy-button"
            disabled={isLoadingRevolut || !!revolutError || !cardFieldInstance || !nameOnCard || !!nameError}
        >
            {$text('signup.buy_for.text').replace(
                '{currency}', currency
            ).replace(
                '{amount}', purchasePrice.toString()
            )}
        </button>

        <!-- Keep OR Divider and Apple/Google Pay (to be implemented separately) -->
        <div class="or-divider">
            <span class="color-grey-60">{@html $text('signup.or.text')}</span>
        </div>

        <button type="button" class="apple-pay-button" disabled> <!-- Disable for now -->
            <span class="apple-pay-text">Pay with Apple Pay</span>
        </button>
         <!-- TODO: Implement Apple Pay / Google Pay using Revolut -->

        <p class="vat-info color-grey-60">
            {@html $text('signup.vat_info.text')}
        </p>
    </form>

    <!-- Keep Bottom Container -->
    <div class="bottom-container">
         <button type="button" class="text-button" on:click={handleSecurePaymentInfoClick}>
             <span class="clickable-icon icon_lock inline-lock-icon"></span>
             {@html $text('signup.secured_and_powered_by.text').replace('{provider}', 'Revolut')}
         </button>
     </div>
</div>

<style>
    /* Add styles for loading and error states */
    .loading-indicator {
        text-align: center;
        padding: 40px 20px;
        color: var(--color-grey-60);
    }
    .error-message {
        background-color: var(--color-error-bg);
        color: var(--color-error);
        padding: 10px 15px;
        border-radius: var(--radius-input);
        margin-bottom: 15px;
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 14px; /* Slightly smaller error text */
    }
    .error-message .clickable-icon {
        position: static;
        transform: none;
        background-color: var(--color-error); /* Make icon match text */
        width: 18px; /* Smaller icon */
        height: 18px;
        flex-shrink: 0;
    }
     .error-message button {
         margin-left: auto;
         color: var(--color-error);
         text-decoration: underline;
         font-size: 14px;
         flex-shrink: 0;
     }

    /* Style the container for the Revolut element */
    .revolut-card-field-wrapper {
        min-height: 48px; /* Ensure it has height while loading */
        border: 1px solid var(--color-input-border); /* Match other inputs */
        border-radius: var(--radius-input); /* Match other inputs */
        background-color: var(--color-input-bg); /* Match other inputs */
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 0; /* Remove padding from wrapper, Revolut element has its own */
        transition: border-color 0.2s ease; /* Smooth transition for focus/error */
    }
    /* Add focus/error state to wrapper if needed, although Revolut element might handle it */
     .revolut-card-field-wrapper:has(#revolut-card-field.invalid) { /* Example if Revolut adds class */
         /* border-color: var(--color-error); */
     }
     .revolut-card-field-wrapper:has(#revolut-card-field:focus-within) { /* Example */
         /* border-color: var(--color-primary); */
         /* box-shadow: 0 0 0 1px var(--color-primary); */
     }


     #revolut-card-field {
         width: 100%; /* Ensure it takes full width */
     }
     #revolut-card-field span { /* Style internal loading text */
        font-size: 14px;
     }

     /* Ensure loading state doesn't allow interaction */
     .payment-form.loading form {
         opacity: 0.6;
         pointer-events: none;
     }

    /* --- Keep existing styles --- */
    .payment-form {
        width: 100%;
        position: relative;
        display: flex;
        flex-direction: column;
        padding-bottom: 60px; /* Make room for bottom container */
    }
    .payment-title {
        text-align: center;
        margin-bottom: 10px;
    }
    .input-group {
        margin-bottom: 12px; /* Consistent spacing */
        position: relative; /* For InputWarning positioning */
    }
    .input-wrapper {
        height: 48px; /* Consistent height */
        position: relative; /* For icon positioning */
        display: flex;
        align-items: center;
    }
     .input-wrapper .clickable-icon { /* Position icon inside */
        position: absolute;
        left: 12px;
        top: 50%;
        transform: translateY(-50%);
        width: 20px;
        height: 20px;
        background-color: var(--color-grey-60); /* Default icon color */
        pointer-events: none; /* Prevent icon interaction */
    }
     .input-wrapper input { /* Add padding for icon */
        padding-left: 40px;
        width: 100%;
        height: 100%;
        box-sizing: border-box; /* Include padding/border in width/height */
        /* Inherit styles from base input styles */
    }
     .input-wrapper input.error {
         border-color: var(--color-error);
         color: var(--color-error);
     }
      .input-wrapper input.error + .clickable-icon { /* Change icon color on error */
         /* background-color: var(--color-error); */ /* Optional */
     }


    .inline-lock-icon {
        position: unset;
        transform: none;
        display: inline-block;
        vertical-align: middle;
        margin-right: 5px;
        width: 16px; /* Smaller lock */
        height: 16px;
    }
    .buy-button {
        width: 100%;
        margin-top: 10px; /* Space above button */
    }
    .buy-button:disabled {
        opacity: 0.7;
        cursor: not-allowed;
    }
    .or-divider {
        display: flex;
        align-items: center;
        justify-content: center;
        margin: 16px 0; /* Adjusted margin */
        text-align: center;
    }
     .or-divider span {
         padding: 0 10px;
         font-size: 14px;
     }
     .or-divider::before,
     .or-divider::after {
         content: '';
         flex-grow: 1;
         height: 1px;
         background-color: var(--color-grey-20); /* Lighter divider line */
     }

    .apple-pay-button {
        width: 100%;
        height: 48px; /* Match input height */
        background-color: black;
        color: white;
        border: none;
        border-radius: var(--radius-input); /* Match input radius */
        font-size: 16px;
        font-weight: 500;
        /* margin-top: 12px; */ /* Removed, spacing handled by divider */
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 5px;
    }
     .apple-pay-button:disabled {
         opacity: 0.5;
         cursor: not-allowed;
     }

    .apple-pay-text {
        font-size: 16px;
    }
    .vat-info {
        font-size: 14px;
        text-align: center;
        margin: 16px 0 0; /* Margin top only */
    }
    .bottom-container {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        padding: 10px 0; /* Padding for the button */
        display: flex;
        justify-content: center;
    }
     .bottom-container .text-button {
         color: var(--color-grey-60);
         font-size: 14px;
     }

</style>
