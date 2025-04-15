<script lang="ts">
  import { onMount, tick } from "svelte"; // Import tick
  import { createEventDispatcher } from "svelte";
  import { apiEndpoints, getApiEndpoint } from "../config/api";

  export let credits_amount: number = 21000;
  export let currency: string = "EUR";
  export let userEmail: string = "";

  let revolutConfig: { revolut_public_key: string; environment: string } | null = null;
  let orderToken: string | null = null;
  let orderId: string | null = null;
  let paymentState: "idle" | "loading" | "initializing_card" | "ready" | "success" | "error" = "idle";
  let errorMessage: string = "";
  let successMessage: string = "";

  let cardFieldDiv: HTMLDivElement | null = null;
  let cardFieldInstance: any | null = null; // To store the Revolut card field instance

  const dispatch = createEventDispatcher();

  // Fetch Revolut config on mount
  onMount(async () => {
    paymentState = "loading";
    try {
      const res = await fetch(getApiEndpoint(apiEndpoints.payments.config), {
        credentials: "include"
      });
      if (!res.ok) throw new Error("Failed to fetch payment config");
      revolutConfig = await res.json();
      paymentState = "idle";
    } catch (err) {
      errorMessage = "Could not load payment configuration.";
      paymentState = "error";
    }
  });

  // Create order and initialize Revolut card field
  async function startPayment() {
    paymentState = "loading";
    errorMessage = "";
    successMessage = "";
    orderToken = null;
    orderId = null;

    // Clear previous card field immediately if it exists
    if (cardFieldDiv) cardFieldDiv.innerHTML = "";

    try {
      // Create order
      const res = await fetch(getApiEndpoint(apiEndpoints.payments.createOrder), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          credits_amount,
          currency
        })
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to create payment order");
      }
      const data = await res.json();
      orderToken = data.order_token;
      orderId = data.order_id;

      // Set state to trigger card field initialization via reactive statement
      paymentState = "initializing_card";
    } catch (err: any) {
      console.error("Error creating order:", err); // Log order creation errors
      errorMessage = err.message || "Unexpected error during payment setup.";
      paymentState = "error";
    }
  }

  // Function to initialize Revolut Card Field
  async function initializeRevolutCardField() {
    if (!orderToken || !revolutConfig || !cardFieldDiv) {
      console.error("Missing prerequisites for Revolut initialization", { orderToken, revolutConfig, cardFieldDiv });
      errorMessage = "Failed to initialize payment field.";
      paymentState = "error";
      return;
    }

    // Clear previous content just in case
    cardFieldDiv.innerHTML = "";
    console.log(`[Revolut Init] Cleared content of cardFieldDiv:`, cardFieldDiv);

    try {
      console.log(`[Revolut Init] Attempting to initialize with token: ${orderToken}, env: ${revolutConfig.environment}, target:`, cardFieldDiv);
      console.log("[Revolut Init] Importing RevolutCheckout SDK...");
      // Load Revolut SDK
      // @ts-ignore
      const RevolutCheckout = (await import("https://unpkg.com/@revolut/checkout/esm")).default;
      console.log("[Revolut Init] RevolutCheckout SDK imported:", RevolutCheckout);

      console.log(`[Revolut Init] Calling RevolutCheckout('${orderToken}', '${revolutConfig.environment}')...`);
      // Initialize card field factory
      const revolutInstance = await RevolutCheckout(orderToken, revolutConfig.environment);
      console.log("[Revolut Init] RevolutCheckout instance created:", revolutInstance);
      const { createCardField } = revolutInstance;
      console.log("[Revolut Init] createCardField function obtained.");

      console.log("[Revolut Init] Calling createCardField with target:", cardFieldDiv);
      // Call createCardField and store the returned instance
      const createdField = createCardField({
        target: cardFieldDiv,
        onSuccess() {
          console.log("[Revolut Callback] onSuccess triggered. Order ID:", orderId);
          paymentState = "success";
          successMessage = "Payment successful! Your credits will be added soon.";
          dispatch("payment", { orderId, status: "success" });
        },
        onError(error) {
          console.error("[Revolut Callback] onError triggered:", error); // Log Revolut errors
          paymentState = "error";
          errorMessage = "Payment failed. Please try again.";
          dispatch("payment", { orderId, status: "error", error });
        },
        onValidation(errors) {
          console.warn("[Revolut Callback] onValidation triggered:", errors); // Log validation issues
          if (errors && errors.length) {
            errorMessage = errors.map((e) => e.message).join(" - ");
            console.log("[Revolut Validation] Errors found:", errorMessage);
          } else {
            errorMessage = ""; // Clear previous validation errors if current validation passes
            console.log("[Revolut Validation] Validation passed (or no errors reported).");
          }
        }
      });
      console.log("[Revolut Init] createCardField call completed.");
      cardFieldInstance = createdField; // Store the returned instance
      console.log("[Revolut Init] Stored cardFieldInstance:", cardFieldInstance);

      console.log("[Revolut Init] Setting paymentState to 'ready'.");
      paymentState = "ready"; // Card field is ready for input
    } catch (err: any) {
      console.error("[Revolut Init] Error during initialization process:", err); // Log initialization errors
      errorMessage = `Could not initialize payment field: ${err.message || "Unknown error"}`;
      paymentState = "error";
    }
  }

  // Reactive statement to initialize card field when conditions are met
  $: if (paymentState === 'initializing_card' && orderToken && revolutConfig && cardFieldDiv) {
    initializeRevolutCardField();
  }

  function reset() {
    paymentState = "idle";
    errorMessage = "";
    successMessage = "";
    orderToken = null;
    orderId = null;
    if (cardFieldDiv) cardFieldDiv.innerHTML = "";
    cardFieldInstance = null; // Reset instance
  }

  // Function to handle explicit submission
  function submitPayment() {
    if (cardFieldInstance) {
      console.log("[Revolut Submit] Calling cardFieldInstance.submit()...");
      // We don't have extra form data like name/email here, but submit is needed.
      // Note: The Revolut SDK might have changed; check if submit() is directly on the instance
      // or if it was returned differently. Assuming it's on the stored instance for now.
      try {
         // Assuming the stored instance has the submit method
         const submitResult = cardFieldInstance.submit();
         console.log("[Revolut Submit] submit() called.", submitResult);
         // Optionally set a submitting state here if needed
         // paymentState = 'submitting'; // Requires adding 'submitting' to the state type
      } catch (err) {
         console.error("[Revolut Submit] Error calling submit():", err);
         errorMessage = "Failed to submit payment.";
         paymentState = "error";
      }
    } else {
      console.error("[Revolut Submit] cardFieldInstance is null, cannot submit.");
      errorMessage = "Cannot submit payment. Field not initialized correctly.";
      paymentState = "error";
    }
  }
</script>

<div class="payment-demo">
  {#if paymentState === "loading"}
    <div class="loading">Creating payment order...</div>
  {:else if paymentState === "initializing_card"}
    <div class="loading">Initializing payment form...</div>
    <!-- Render the card field div, hidden initially -->
    <div bind:this={cardFieldDiv} class="card-field" style="display: none;"></div>
  {:else if paymentState === "success"}
    <div class="success">{successMessage}</div>
    <button on:click={reset}>Make another payment</button>
  {:else if paymentState === 'ready'}
     <!-- Show card field and submit button when ready -->
     <div bind:this={cardFieldDiv} class="card-field"></div>
     {#if errorMessage}
       <div class="error">{errorMessage}</div>
     {/if}
     <button class="submit-btn" on:click={submitPayment}>Submit Payment</button>
     <button class="cancel-btn" on:click={reset}>Cancel</button>
  {:else} <!-- Initial state (idle) or error before ready -->
    <div>
      <button class="pay-btn" on:click={startPayment} disabled={paymentState !== 'idle'}>
         {#if paymentState === 'error'}
           Retry Payment for {credits_amount} credits ({currency})
         {:else}
           Pay for {credits_amount} credits ({currency})
         {/if}
      </button>
      {#if errorMessage && paymentState === 'error'}
         <div class="error">{errorMessage}</div>
      {/if}
      <!-- Redundant card-field div removed from here -->
    </div>
  {/if}
</div>

<style>
.payment-demo {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
}

.loading {
  color: #888;
  margin: 1em 0;
}
.success {
  color: green;
  font-weight: bold;
  margin: 1em 0;
}
.error {
  color: red;
  margin: 1em 0;
}
.pay-btn {
  margin-bottom: 1em;
  padding: 0.7em 2em;
  font-size: 1.1em;
  background: #2626e6;
  color: #fff;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition: background-color 0.2s ease;
}
.pay-btn:hover:not(:disabled) {
  background-color: #1a1aa3;
}
.pay-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.submit-btn, .cancel-btn {
  margin-top: 1em;
  padding: 0.7em 2em;
  font-size: 1.1em;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition: background-color 0.2s ease, color 0.2s ease;
}
.submit-btn {
  background: #28a745; /* Green */
  color: #fff;
  margin-right: 0.5em;
}
.submit-btn:hover {
  background-color: #218838;
}
.cancel-btn {
  background: #dc3545; /* Red */
  color: #fff;
}
.cancel-btn:hover {
  background-color: #c82333;
}
.card-field {
  margin-top: 1em;
  min-height: 60px; /* Ensure it has some height */
  width: 100%;
  max-width: 400px;
  border: 1px solid #ccc; /* Add border for visibility */
  padding: 5px; /* Add padding */
}
/* Removed .card-field-placeholder as it's no longer used */
</style>