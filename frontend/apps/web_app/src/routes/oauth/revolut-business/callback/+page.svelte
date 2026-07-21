<!--
  Revolut Business OAuth Callback Page.

  Purpose: give users a non-broken landing page after Revolut Business consent.
  Architecture: app-domain callback UI for Finance connected-account setup.
  Security: displays the short-lived authorization code only on the user's device;
  the private key stays in CLI/client storage and the backend is not called here.
  Spec: docs/specs/finance-check-accounts-v1/spec.yml
-->
<script lang="ts">
  import { page } from '$app/state';

  const DEFAULT_CLIENT_ID = '';

  let copied = $state(false);
  let code = $derived(page.url.searchParams.get('code') ?? '');
  let error = $derived(page.url.searchParams.get('error') ?? '');
  let errorDescription = $derived(page.url.searchParams.get('error_description') ?? '');
  let clientId = $state(DEFAULT_CLIENT_ID);
  let exchangeCommand = $derived(
    clientId.trim()
      ? `openmates connect-account revolut-business exchange-code --client-id "${clientId.trim()}" --code "${page.url.href}"`
      : 'openmates connect-account revolut-business exchange-code --client-id "<ClientID>" --code "' + page.url.href + '"'
  );

  async function copyCommand() {
    await navigator.clipboard.writeText(exchangeCommand);
    copied = true;
    setTimeout(() => {
      copied = false;
    }, 2200);
  }
</script>

<svelte:head>
  <title>Revolut Business Connected | OpenMates</title>
  <meta name="robots" content="noindex,nofollow" />
</svelte:head>

<main class="callback-shell">
  <section class="card" data-testid="revolut-oauth-callback-card">
    <p class="eyebrow">OpenMates Finance</p>
    {#if error}
      <h1>Revolut access was not approved</h1>
      <p class="lead">
        Revolut returned an error instead of an authorization code.
      </p>
      <div class="notice error" data-testid="revolut-oauth-error">
        <strong>{error}</strong>
        {#if errorDescription}<span>{errorDescription}</span>{/if}
      </div>
      <a class="primary" href="/">Return to OpenMates</a>
    {:else if code}
      <h1>Revolut Business access approved</h1>
      <p class="lead">
        Your authorization code is ready. Finish setup from the same machine that generated your OpenMates private key.
      </p>

      <label for="client-id">ClientID from Revolut</label>
      <input
        id="client-id"
        bind:value={clientId}
        placeholder="Paste ClientID"
        autocomplete="off"
        spellcheck="false"
        data-testid="revolut-client-id-input"
      />

      <div class="command" data-testid="revolut-exchange-command">
        <code>{exchangeCommand}</code>
      </div>
      <button class="primary" type="button" onclick={copyCommand} data-testid="copy-revolut-command">
        {copied ? 'Copied' : 'Copy command'}
      </button>
      <p class="hint">
        This code expires quickly. If it expires, reopen the Revolut consent link from the CLI and approve access again.
      </p>
    {:else}
      <h1>Missing Revolut authorization code</h1>
      <p class="lead">
        This callback page did not receive a Revolut code. Start the Revolut Business setup again from the OpenMates CLI.
      </p>
      <div class="command"><code>openmates connect-account revolut-business</code></div>
    {/if}
  </section>
</main>

<style>
  :global(body) {
    margin: 0;
    background: radial-gradient(circle at top left, #1f3d5a 0, #071018 42%, #03070a 100%);
    color: #f7fbff;
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  }

  .callback-shell {
    min-height: 100vh;
    display: grid;
    place-items: center;
    padding: 1.25rem;
  }

  .card {
    width: min(100%, 680px);
    padding: clamp(1.5rem, 4vw, 2.75rem);
    border: 1px solid rgb(255 255 255 / 14%);
    border-radius: 28px;
    background: rgb(10 21 30 / 86%);
    box-shadow: 0 24px 90px rgb(0 0 0 / 48%);
  }

  .eyebrow {
    margin: 0 0 0.75rem;
    color: #83b7ff;
    font-size: 0.8rem;
    font-weight: 700;
    letter-spacing: 0.13em;
    text-transform: uppercase;
  }

  h1 {
    margin: 0;
    font-size: clamp(2rem, 6vw, 4rem);
    line-height: 0.95;
    letter-spacing: -0.05em;
  }

  .lead {
    max-width: 54ch;
    margin: 1rem 0 1.5rem;
    color: rgb(247 251 255 / 76%);
    font-size: 1.05rem;
    line-height: 1.6;
  }

  label {
    display: block;
    margin: 0 0 0.4rem;
    color: rgb(247 251 255 / 72%);
    font-size: 0.85rem;
    font-weight: 700;
  }

  input {
    width: 100%;
    box-sizing: border-box;
    border: 1px solid rgb(255 255 255 / 14%);
    border-radius: 14px;
    padding: 0.9rem 1rem;
    background: rgb(255 255 255 / 8%);
    color: #fff;
    font: inherit;
  }

  .command {
    margin: 1rem 0;
    padding: 1rem;
    border-radius: 16px;
    background: #05090d;
    border: 1px solid rgb(255 255 255 / 10%);
    overflow-x: auto;
  }

  code {
    color: #b8f7d4;
    font-family: 'SFMono-Regular', Consolas, monospace;
    font-size: 0.85rem;
    white-space: pre-wrap;
    word-break: break-all;
  }

  .primary {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 3rem;
    border: 0;
    border-radius: 999px;
    padding: 0 1.35rem;
    background: #fff;
    color: #06101a;
    font: inherit;
    font-weight: 800;
    text-decoration: none;
    cursor: pointer;
  }

  .hint {
    margin: 1rem 0 0;
    color: rgb(247 251 255 / 62%);
    font-size: 0.9rem;
  }

  .notice {
    display: grid;
    gap: 0.35rem;
    margin: 1rem 0 1.5rem;
    padding: 1rem;
    border-radius: 16px;
  }

  .notice.error {
    background: rgb(255 80 80 / 14%);
    color: #ffd8d8;
  }
</style>
