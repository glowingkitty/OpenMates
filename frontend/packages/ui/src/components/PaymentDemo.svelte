<script lang="ts">
  import { onMount } from "svelte";
  import { createEventDispatcher } from "svelte";
  import { apiEndpoints, getApiEndpoint } from "../config/api";

  export let credits_amount: number = 21000;
  export let currency: string = "EUR";
  export let userEmail: string = "";

  let revolutConfig: { revolut_public_key: string; environment: string } | null = null;
  let orderToken: string | null = null;
  let orderId: string | null = null;
  let paymentState: string = "idle";
  let errorMessage: string = "";
  let successMessage: string = "";

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

      // Load Revolut SDK
      // @ts-ignore
      const RevolutCheckout = (await import("https://unpkg.com/@revolut/checkout/esm")).default;
      // Initialize card field
      const { createCardField } = await RevolutCheckout(orderToken, revolutConfig?.environment || "sandbox");

      // Remove any previous card field
      const cardFieldDiv = document.getElementById("card-field");
      if (cardFieldDiv) cardFieldDiv.innerHTML = "";

      createCardField({
        target: cardFieldDiv,
        onSuccess() {
          paymentState = "success";
          successMessage = "Payment successful! Your credits will be added soon.";
          dispatch("payment", { orderId, status: "success" });
        },
        onError(error) {
          paymentState = "error";
          errorMessage = "Payment failed. Please try again.";
          dispatch("payment", { orderId, status: "error", error });
        },
        onValidation(errors) {
          if (errors && errors.length) {
            errorMessage = errors.map((e) => e.message).join(" - ");
          }
        }
      });

      paymentState = "ready";
    } catch (err: any) {
      errorMessage = err.message || "Unexpected error during payment.";
      paymentState = "error";
    }
  }

  function reset() {
    paymentState = "idle";
    errorMessage = "";
    successMessage = "";
    orderToken = null;
    orderId = null;
    const cardFieldDiv = document.getElementById("card-field");
    if (cardFieldDiv) cardFieldDiv.innerHTML = "";
  }
</script>

<div class="payment-demo">
  {#if paymentState === "loading"}
    <div class="loading">Loading payment form...</div>
  {:else if paymentState === "success"}
    <div class="success">{successMessage}</div>
    <button on:click={reset}>Make another payment</button>
  {:else}
    <div>
      <button class="pay-btn" on:click={startPayment} disabled={paymentState === "loading"}>
        Pay for {credits_amount} credits ({currency})
      </button>
      {#if errorMessage}
        <div class="error">{errorMessage}</div>
      {/if}
      <div id="card-field" class="card-field"></div>
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
  min-height: 60px;
  width: 100%;
  max-width: 400px;
}
</style>