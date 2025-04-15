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

    try {
      console.log("Initializing Revolut Card Field with token:", orderToken, "on element:", cardFieldDiv);
      // Load Revolut SDK
      // @ts-ignore
      const RevolutCheckout = (await import("https://unpkg.com/@revolut/checkout/esm")).default;
      // Initialize card field
      const { createCardField } = await RevolutCheckout(orderToken, revolutConfig.environment);

      createCardField({
        target: cardFieldDiv,
        onSuccess() {
          paymentState = "success";
          successMessage = "Payment successful! Your credits will be added soon.";
          dispatch("payment", { orderId, status: "success" });
        },
        onError(error) {
          console.error("Revolut onError:", error); // Log Revolut errors
          paymentState = "error";
          errorMessage = "Payment failed. Please try again.";
          dispatch("payment", { orderId, status: "error", error });
        },
        onValidation(errors) {
          console.warn("Revolut onValidation:", errors); // Log validation issues
          if (errors && errors.length) {
            errorMessage = errors.map((e) => e.message).join(" - ");
          } else {
            errorMessage = ""; // Clear previous validation errors if current validation passes
          }
        }
      });

      paymentState = "ready"; // Card field is ready for input
    } catch (err: any) {
      console.error("Error initializing Revolut Card Field:", err); // Log initialization errors
      errorMessage = "Could not initialize payment field.";
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
  }
</script>

<div class="payment-demo">
  {#if paymentState === "loading"}
    <div class="loading">Creating payment order...</div>
  {:else if paymentState === "initializing_card"}
    <div class="loading">Initializing payment form...</div>
    <!-- Render the div here so it's available for binding -->
    <div bind:this={cardFieldDiv} class="card-field-placeholder"></div>
  {:else if paymentState === "success"}
    <div class="success">{successMessage}</div>
    <button on:click={reset}>Make another payment</button>
  {:else}
    <div>
      <!-- Disable button only when card field is ready to prevent restarting -->
      <button class="pay-btn" on:click={startPayment} disabled={paymentState === "ready"}>
        Pay for {credits_amount} credits ({currency})
      </button>
      {#if errorMessage}
        <div class="error">{errorMessage}</div>
      {/if}
      <!-- Card field will be mounted here when ready -->
      <div bind:this={cardFieldDiv} class="card-field" style:display={paymentState === 'ready' || paymentState === 'error' ? 'block' : 'none'}></div>
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
}
.pay-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.card-field {
  margin-top: 1em;
  min-height: 60px; /* Ensure it has some height */
  width: 100%;
  max-width: 400px;
  border: 1px solid #ccc; /* Add border for visibility */
  padding: 5px; /* Add padding */
}
.card-field-placeholder {
  min-height: 60px; /* Match height */
  width: 100%;
  max-width: 400px;
  margin-top: 1em;
  /* No border or content, just occupies space */
}
</style>