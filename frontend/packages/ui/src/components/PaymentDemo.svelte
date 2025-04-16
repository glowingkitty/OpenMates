<script lang="ts">
  import { onMount, tick } from 'svelte';
  import RevolutCheckout from '@revolut/checkout';
  import { apiEndpoints, getApiEndpoint } from '../config/api';
  import { userProfile, updateProfile } from '../stores/userProfile'; // Import userProfile and updateProfile

  // --- Component State ---
  let revolutPublicKey: string | null = null;
  let orderToken: string | null = null;
  let cardFieldInstance: any = null; // To hold the Revolut CardField instance
  let cardFieldTarget: HTMLElement; // Bound element for CardField
  let isLoading = false;
  let errorMessage: string | null = null;
  let successMessage: string | null = null;
  let validationErrors: string | null = null;
  let showCheckoutForm = false;
  let pollTimeoutId: number | null = null; // Declare timeout ID at component level
  let isPollingStopped = false; // Flag to ensure polling stops reliably
 
  // --- Form Data ---
  let name = '';
  let email = '';

  // --- Credits Purchase Data ---
  const creditsToPurchase = 21000; // Default credits amount as requested
  // Currency is now read from the userProfile store

  // --- Types and Helper Functions ---
  // Define the allowed Revolut locale types based on the TS error
  type RevolutLocale = "en" | "en-US" | "nl" | "fr" | "de" | "cs" | "it" | "lt" | "pl" | "pt" | "es" | "hu" | "sk" | "ja" | "sv" | "bg" | "ro" | "ru" | "el" | "hr" | "auto";
  const supportedRevolutLocales: Set<string> = new Set<RevolutLocale>([
    "en", "en-US", "nl", "fr", "de", "cs", "it", "lt", "pl", "pt", "es", "hu", "sk", "ja", "sv", "bg", "ro", "ru", "el", "hr", "auto"
  ]);

  // Helper to get a valid Revolut locale from the user profile language
  function getValidRevolutLocale(profileLanguage: string | null | undefined): RevolutLocale {
    const defaultLocale: RevolutLocale = 'en';
    if (!profileLanguage) {
      return defaultLocale;
    }
    // Simple mapping (e.g., if profile stores 'en-GB', map it to 'en' if 'en-GB' isn't directly supported)
    // For now, we assume the profile language directly matches a supported locale or we default.
    const lowerCaseLang = profileLanguage.toLowerCase();

    // Direct match check (case-insensitive comparison with the Set's values)
    for (const supportedLocale of supportedRevolutLocales) {
        if (supportedLocale.toLowerCase() === lowerCaseLang) {
            return supportedLocale as RevolutLocale; // Cast is safe due to check
        }
    }

    // Fallback for base language codes (e.g., 'fr-FR' -> 'fr')
    const baseLang = lowerCaseLang.split('-')[0];
     if (supportedRevolutLocales.has(baseLang)) {
        return baseLang as RevolutLocale;
     }


    console.warn(`Profile language '${profileLanguage}' is not a supported Revolut locale. Defaulting to '${defaultLocale}'.`);
    return defaultLocale;
  }


  // --- Fetch Revolut Config ---
  async function fetchConfig() {
    isLoading = true;
    errorMessage = null;
    try {
      const response = await fetch(getApiEndpoint(apiEndpoints.payments.config), {
        credentials: 'include' // Send cookies with the request
      });
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const config = await response.json();

      if (!config.revolut_public_key) {
        throw new Error('Revolut Public Key not found in config response.');
      }
      revolutPublicKey = config.revolut_public_key;
      console.log('Revolut Public Key fetched successfully.');
    } catch (error) {
      console.error('Failed to fetch Revolut config:', error);
      errorMessage = `Failed to load payment configuration. ${error instanceof Error ? error.message : String(error)}`;
    } finally {
      isLoading = false;
      // If config fetch was successful, immediately try to create the order
      if (revolutPublicKey) {
        console.log('Config fetched, automatically creating order...');
        createOrder(); // Automatically trigger order creation
      }
    }
  }

  // --- Create Payment Order ---
  async function createOrder() {
    if (!revolutPublicKey) {
      errorMessage = 'Cannot create order: Revolut Public Key is missing.';
      return;
    }

    isLoading = true;
    errorMessage = null;
    successMessage = null;
    orderToken = null; // Reset previous order ID

    try {
      const response = await fetch(getApiEndpoint(apiEndpoints.payments.createOrder), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include', // Send cookies with the request
        body: JSON.stringify({
          credits_amount: creditsToPurchase,
          currency: $userProfile?.currency || 'EUR' // Use currency from profile store, fallback to 'EUR'
          // Backend determines amount based on credits and currency
        })
      });

      console.log('Create Order response:', response);

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({})); // Try to parse error details
        throw new Error(`Failed to create order: ${response.status} ${response.statusText}. ${errorData.detail || ''}`);
      }

      const order = await response.json();
      if (!order.order_token) {
        throw new Error('Order created, but order_id is missing in the response.');
      }
      orderToken = order.order_token;
      lastOrderId = order.order_id; // Store order_id for polling after payment
      console.log('Revolut Order created:', orderToken, 'Order ID:', lastOrderId);
      showCheckoutForm = true; // Show the form now
      // Wait for Svelte to update the DOM so cardFieldTarget is bound
      await tick();
      // Initialize Card Field after order is created and element is visible
      await initializeCardField();

    } catch (error) {
      console.error('Failed to create payment order:', error);
      errorMessage = `Failed to create payment order. ${error instanceof Error ? error.message : String(error)}`;
      showCheckoutForm = false; // Hide form on error
    } finally {
      isLoading = false;
    }
  }

  // --- Initialize Revolut Card Field ---
  async function initializeCardField() {
    if (!orderToken || !cardFieldTarget || !revolutPublicKey) {
      errorMessage = 'Cannot initialize payment field: Missing Order ID, target element, or Public Key.';
      console.error('Initialization prerequisites not met:', { orderToken, cardFieldTarget, revolutPublicKey });
      return;
    }

    // Ensure previous instance is destroyed if re-initializing
    if (cardFieldInstance) {
      try {
        cardFieldInstance.destroy();
        console.log('Previous CardField instance destroyed.');
      } catch (error) {
        console.error('Error destroying previous CardField instance:', error);
      }
      cardFieldInstance = null;
    }

    // Clear previous validation errors
    validationErrors = null;

    try {
      // Always use 'sandbox' environment for RevolutCheckout
      const environment = 'sandbox';

      console.log(`Initializing RevolutCheckout for order ${orderToken} in ${environment} mode.`);

      // Destructure createCardField from RevolutCheckout as per official docs
      const { createCardField } = await RevolutCheckout(orderToken, environment);
      if (!createCardField || typeof createCardField !== 'function') {
        throw new Error('RevolutCheckout did not return createCardField function.');
      }
      console.log('RevolutCheckout loaded, createCardField available.');

      cardFieldInstance = createCardField({
        target: cardFieldTarget,
        locale: getValidRevolutLocale($userProfile?.language), // Use validated language from profile store
        // Optional: Customize styles and classes
        // styles: {},
        // classes: {},
        onSuccess() {
          console.log('Payment successful! Waiting for backend confirmation...');
          errorMessage = null;
          validationErrors = null;
          // Do not show successMessage yet
          // Optionally reset form or navigate away
          showCheckoutForm = false;
          // Start polling backend for order status
          pollOrderStatus();
        },
        onError(error) {
          console.error('Payment error:', error);
          // Revolut often returns error like { code: 'payment_declined', message: '...' }
          const message = typeof error === 'object' && error !== null && 'message' in error ? String(error.message) : 'An unknown payment error occurred.';
          errorMessage = `Payment failed: ${message}`;
          successMessage = null;
          validationErrors = null;
        },
        onValidation(errors) {
          console.warn('Validation errors:', errors);
          // Concatenate the error messages into a single string
          const concatenatedErrors = errors
            ?.map((err: { message: string }) => err.message)
            .join('; ');

          if (concatenatedErrors?.length) {
            validationErrors = concatenatedErrors;
            errorMessage = null; // Clear general error message if validation errors occur
          } else {
            validationErrors = null; // Clear validation errors if none are present
          }
        }
      });
      console.log('Card Field instance created:', cardFieldInstance, 'typeof:', typeof cardFieldInstance);

    } catch (error) {
      console.error('Failed to initialize Revolut Card Field:', error);
      errorMessage = `Failed to initialize payment field. ${error instanceof Error ? error.message : String(error)}`;
      cardFieldInstance = null; // Ensure instance is null on error
    }
  }

  // --- Poll Backend for Order Status ---
  async function pollOrderStatus() {
    if (!orderToken) {
      errorMessage = 'Order token missing. Cannot verify payment status.';
      return;
    }
    let attempts = 0;
    const maxAttempts = 20; // e.g., poll for up to 20 times (~40s)
    const pollInterval = 2000; // 2 seconds
    // Reset polling stop flag at the beginning of a new polling sequence
    isPollingStopped = false;
 
    // We need to get the order_id associated with the orderToken.
    // Since the backend returns both order_token and order_id, we should store order_id when creating the order.
    // We'll add a variable to store it.
    let orderId = lastOrderId;
    if (!orderId) {
      errorMessage = 'Order ID missing. Cannot verify payment status.';
      return;
    }

    async function poll() {
      // Check flag before doing anything
      if (isPollingStopped) {
        console.log('Polling stopped flag is true, exiting poll function.');
        return;
      }

      attempts++;
      try {
        const response = await fetch(getApiEndpoint(apiEndpoints.payments.orderStatus), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ order_id: orderId })
        });
        if (!response.ok) {
          throw new Error(`Failed to fetch order status: ${response.status} ${response.statusText}`);
        }
        const data = await response.json();
        const state = data.state;
        console.log('Order status polled:', state);
        if (typeof state === 'string' && state.toLowerCase() === 'completed') {
          successMessage = 'Payment successful! Your order is complete.';
          errorMessage = null;
          validationErrors = null;
          orderToken = null;
          lastOrderId = null;
          isPollingStopped = true; // Set flag
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
          errorMessage = 'Payment failed or was cancelled. Please try again.';
          successMessage = null;
          validationErrors = null;
          orderToken = null;
          lastOrderId = null;
          isPollingStopped = true; // Set flag
          if (pollTimeoutId) clearTimeout(pollTimeoutId);
          pollTimeoutId = null;
          return;
        } else {
          // Still pending, poll again ONLY if not stopped
          if (attempts < maxAttempts && !isPollingStopped) {
            pollTimeoutId = setTimeout(poll, pollInterval); // Store timeout ID
          } else if (!isPollingStopped) { // Only set timeout message if not already stopped for other reasons
            errorMessage = 'Payment processing timed out. Please check your order status later.';
            successMessage = null;
            validationErrors = null;
            orderToken = null;
            lastOrderId = null;
            isPollingStopped = true; // Set flag
            if (pollTimeoutId) clearTimeout(pollTimeoutId);
            pollTimeoutId = null;
          }
        }
      } catch (err) {
        errorMessage = `Error checking payment status: ${err instanceof Error ? err.message : String(err)}`;
        successMessage = null;
        validationErrors = null;
        orderToken = null;
        lastOrderId = null;
        isPollingStopped = true; // Set flag
        if (pollTimeoutId) clearTimeout(pollTimeoutId);
        pollTimeoutId = null;
      }
    }

    // Clear any existing timeout AND reset stop flag before starting a new poll sequence
    if (pollTimeoutId) clearTimeout(pollTimeoutId);
    pollTimeoutId = null; // Ensure ID is null before starting
    isPollingStopped = false; // Reset flag
    // Start the first poll after an initial delay
    pollTimeoutId = setTimeout(poll, 1500);
  }

  // Store the last order ID for polling after payment
  let lastOrderId: string | null = null;

  // --- Handle Form Submission ---
  function handleSubmit() {
    if (!cardFieldInstance) {
      errorMessage = 'Payment field is not ready.';
      return;
    }
    if (!name || !email) {
      validationErrors = 'Please enter your full name and email address.';
      return;
    }

    console.log('Submitting Card Field with:', { name, email });
    errorMessage = null;
    successMessage = null;
    validationErrors = null; // Clear previous validation errors before submit

    // Submit card details along with billing info (meta object)
    cardFieldInstance.submit({
      name: name,
      email: email
      // Add other billing details if needed (address, phone, etc.)
      // billingAddress: { ... }
    });
  }

  // --- Lifecycle ---
  onMount(() => {
    // Fetch config when component mounts
    fetchConfig();

    // Cleanup on destroy
    return () => {
      if (cardFieldInstance) {
        try {
          cardFieldInstance.destroy();
          console.log('CardField instance destroyed on component unmount.');
        } catch (error) {
          console.error('Error destroying CardField instance on unmount:', error);
        }
      }
      // Also clear timeout and set stop flag on component destroy
      isPollingStopped = true; // Ensure any pending poll stops
      if (pollTimeoutId) {
        clearTimeout(pollTimeoutId);
      }
    };
  });
</script>

<div class="payment-demo-container">
  {#if isLoading}
    <p>Loading payment details...</p>
  {/if}

  {#if errorMessage}
    <p class="error-message">Error: {errorMessage}</p>
  {/if}

  {#if successMessage}
    <p class="success-message">{successMessage}</p>
  {/if}

  <!-- Checkout Form (now shown directly after order creation attempt) -->
  {#if showCheckoutForm && orderToken}
    <form on:submit|preventDefault={handleSubmit} class="checkout-form">
      <h3>Enter Payment Details</h3>

      <div class="form-group">
        <label for="name">Full Name</label>
        <input type="text" id="name" bind:value={name} placeholder="Enter your full name" required />
      </div>

      <div class="form-group">
        <label for="email">Email</label>
        <input type="email" id="email" bind:value={email} placeholder="Enter your email address" required />
      </div>

      <!-- Revolut Card Field Container -->
      <p>Card Details:</p>
      <div bind:this={cardFieldTarget} id="card-field-container" class="card-field-wrapper">
        <!-- Revolut Card Field will be mounted here -->
      </div>

      {#if validationErrors}
        <p class="error-message validation-errors">{validationErrors}</p>
      {/if}

      <button type="submit" disabled={isLoading || !cardFieldInstance}>
        {#if isLoading}Processing...{:else}Complete Purchase{/if} <!-- Updated button text -->
      </button>
    </form>
  {/if}
</div>

<style>
  .payment-demo-container {
    padding: 20px;
    border: 1px solid #ccc;
    border-radius: 8px;
    max-width: 500px;
    margin: 20px auto;
    font-family: sans-serif;
  }

  .product-display {
    text-align: center;
    margin-bottom: 20px;
  }

  .checkout-form {
    display: flex;
    flex-direction: column;
    gap: 15px;
  }

  .form-group {
    display: flex;
    flex-direction: column;
  }

  label {
    margin-bottom: 5px;
    font-weight: bold;
  }

  input[type='text'],
  input[type='email'] {
    padding: 10px;
    border: 1px solid #ccc;
    border-radius: 4px;
  }

  /* Style the container where Revolut Card Field will be injected */
  .card-field-wrapper {
    border: 1px solid #ccc; /* Example border */
    padding: 10px;          /* Example padding */
    border-radius: 4px;
    min-height: 50px; /* Ensure it has some height */
  }

  button {
    padding: 12px 20px;
    background-color: #007bff;
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 16px;
    transition: background-color 0.2s ease;
  }

  button:disabled {
    background-color: #ccc;
    cursor: not-allowed;
  }

  button:not(:disabled):hover {
    background-color: #0056b3;
  }

  .error-message {
    color: #dc3545; /* Red */
    background-color: #f8d7da;
    border: 1px solid #f5c6cb;
    padding: 10px;
    border-radius: 4px;
    margin-top: 10px;
  }

  .validation-errors {
    margin-top: 0; /* Adjust spacing specifically for validation errors */
  }

  .success-message {
    color: #28a745; /* Green */
    background-color: #d4edda;
    border: 1px solid #c3e6cb;
    padding: 10px;
    border-radius: 4px;
    margin-top: 10px;
  }
</style>