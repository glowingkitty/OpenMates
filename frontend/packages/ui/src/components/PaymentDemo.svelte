<script lang="ts">
	import { onMount, tick } from 'svelte';
	import RevolutCheckout from '@revolut/checkout';
	import { apiEndpoints, getApiEndpoint } from '../config/api';

	// --- Component State ---
	let revolutPublicKey: string | null = null;
	let revolutPublicOrderId: string | null = null;
	let cardFieldInstance: any = null; // To hold the Revolut CardField instance
	let cardFieldTarget: HTMLElement; // Bound element for CardField
	let isLoading = false;
	let errorMessage: string | null = null;
	let successMessage: string | null = null;
	let validationErrors: string | null = null;
	let showCheckoutForm = false;

	// --- Form Data ---
	let name = '';
	let email = '';

	// --- Credits Purchase Data ---
	const creditsToPurchase = 21000; // Default credits amount as requested
	const purchaseCurrency = 'USD'; // Assuming USD, adjust if needed

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
		revolutPublicOrderId = null; // Reset previous order ID

		try {
			const response = await fetch(getApiEndpoint(apiEndpoints.payments.createOrder), {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				credentials: 'include', // Send cookies with the request
				body: JSON.stringify({
					credits_amount: creditsToPurchase,
					currency: purchaseCurrency
					// Backend determines amount based on credits and currency
				})
			});

			console.log('Create Order response:', response);

			if (!response.ok) {
				const errorData = await response.json().catch(() => ({})); // Try to parse error details
				throw new Error(`Failed to create order: ${response.status} ${response.statusText}. ${errorData.detail || ''}`);
			}

			const order = await response.json();
			if (!order.order_id) {
				throw new Error('Order created, but order_id is missing in the response.');
			}
			revolutPublicOrderId = order.order_id;
			console.log('Revolut Order created:', revolutPublicOrderId);
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
		if (!revolutPublicOrderId || !cardFieldTarget || !revolutPublicKey) {
			errorMessage = 'Cannot initialize payment field: Missing Order ID, target element, or Public Key.';
			console.error('Initialization prerequisites not met:', { revolutPublicOrderId, cardFieldTarget, revolutPublicKey });
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
   // Use 'prod' or 'sandbox' based on your environment needs
   // @ts-ignore - Vite specific env variable
   const environment = import.meta.env.MODE === 'production' ? 'prod' : 'sandbox';
			console.log(`Initializing RevolutCheckout for order ${revolutPublicOrderId} in ${environment} mode.`);

			const RC = await RevolutCheckout(revolutPublicOrderId, environment);
            if (!RC || typeof RC.createCardField !== 'function') {
                throw new Error('RevolutCheckout initialization failed or did not return expected object.');
            }
			console.log('RevolutCheckout loaded.');

			cardFieldInstance = RC.createCardField({
				target: cardFieldTarget,
				locale: 'en', // Optional: set language
				// Optional: Customize styles and classes
				// styles: {},
				// classes: {},
				onSuccess() {
					console.log('Payment successful!');
					successMessage = 'Payment successful! Your order is complete.';
					errorMessage = null;
					validationErrors = null;
					// Optionally reset form or navigate away
					showCheckoutForm = false;
					revolutPublicOrderId = null;
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
			console.log('Card Field instance created.');
            // Mount the instance
            cardFieldInstance.mount();
            console.log('Card Field instance mounted.');

		} catch (error) {
			console.error('Failed to initialize Revolut Card Field:', error);
			errorMessage = `Failed to initialize payment field. ${error instanceof Error ? error.message : String(error)}`;
            cardFieldInstance = null; // Ensure instance is null on error
		}
	}

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

		// Submit card details along with billing info
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
        };
	});

</script>

<div class="payment-demo-container">
	<h2>Revolut Card Field Demo</h2>

	{#if isLoading}
		<p>Loading payment details...</p>
	{/if}

	{#if errorMessage}
		<p class="error-message">Error: {errorMessage}</p>
	{/if}

	{#if successMessage}
		<p class="success-message">{successMessage}</p>
	{/if}

	<!-- Step 1: Show Product and Checkout Button -->
	{#if !showCheckoutForm && !successMessage}
		<div class="product-display">
			<h3>Purchase OpenMates Credits</h3>
			<p>Get {creditsToPurchase.toLocaleString()} credits</p> <!-- Display credits instead of price -->
			<button on:click={createOrder} disabled={isLoading || !revolutPublicKey}>
				{#if isLoading}Creating Order...{:else}Checkout Now{/if}
			</button>
			{#if !revolutPublicKey && !isLoading}
				<p class="error-message">Payment system not available.</p>
			{/if}
		</div>
	{/if}

	<!-- Step 2: Show Checkout Form after Order is Created -->
	{#if showCheckoutForm && revolutPublicOrderId}
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