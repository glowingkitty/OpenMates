<!--
  Revolut Business OAuth Callback Page.

  Purpose: give users a non-broken landing page after Revolut Business consent.
  Architecture: app-domain callback UI for Finance connected-account setup.
  Security: displays only the short-lived authorization code returned by Revolut;
  account connection setup continues in the initiating OpenMates client.
  Spec: docs/specs/finance-check-accounts-v1/spec.yml
-->
<script lang="ts">
  import { page } from '$app/state';

  let copied = $state(false);
  let code = $derived(page.url.searchParams.get('code') ?? '');
  let error = $derived(page.url.searchParams.get('error') ?? '');
  let errorDescription = $derived(page.url.searchParams.get('error_description') ?? '');

  async function copyCode() {
    if (!code) return;
    await navigator.clipboard.writeText(code);
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
        Copy this code, return to OpenMates, and paste it into the connection flow.
      </p>

      <div class="code-box" data-testid="revolut-authorization-code">
        <code>{code}</code>
      </div>
      <button class="primary" type="button" onclick={copyCode} data-testid="copy-revolut-code">
        {copied ? 'Copied' : 'Copy code'}
      </button>
      <p class="hint">
        This code expires quickly. If it expires, restart the Revolut Business connection flow in OpenMates.
      </p>
    {:else}
      <h1>Missing Revolut authorization code</h1>
      <p class="lead">
        This callback page did not receive a Revolut code. Start the Revolut Business setup again from OpenMates.
      </p>
      <div class="code-box"><code>openmates connect-account revolut-business</code></div>
    {/if}
  </section>
</main>

<style>
  :global(body) {
    margin: 0;
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    font-family: var(--font-primary, 'Lexend Deca', system-ui, sans-serif);
  }

  .callback-shell {
    min-height: 100vh;
    display: grid;
    place-items: center;
    padding: 1.25rem;
    background:
      radial-gradient(circle at 10% 0%, color-mix(in srgb, var(--color-primary-start, #4867cd) 24%, transparent) 0, transparent 38rem),
      radial-gradient(circle at 88% 12%, color-mix(in srgb, var(--color-button-primary, #ff553b) 16%, transparent) 0, transparent 34rem),
      var(--color-grey-0);
  }

  .card {
    width: min(100%, 680px);
    padding: clamp(1.5rem, 4vw, 2.75rem);
    border: 1px solid var(--color-grey-30);
    border-radius: 28px;
    background: color-mix(in srgb, var(--color-grey-0) 88%, transparent);
    box-shadow: 0 24px 90px color-mix(in srgb, var(--color-grey-100, #000) 18%, transparent);
    backdrop-filter: blur(22px);
  }

  .eyebrow {
    margin: 0 0 0.75rem;
    color: var(--color-primary-start, #4867cd);
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
    color: var(--color-font-secondary);
    font-size: 1.05rem;
    line-height: 1.6;
  }

  .code-box {
    margin: 1rem 0;
    padding: 1rem;
    border-radius: 16px;
    background: var(--color-grey-10);
    border: 1px solid var(--color-grey-30);
    overflow-x: auto;
  }

  code {
    color: var(--color-font-primary);
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
    background: var(--color-button-primary);
    color: var(--color-font-button);
    font: inherit;
    font-weight: 800;
    text-decoration: none;
    cursor: pointer;
  }

  .hint {
    margin: 1rem 0 0;
    color: var(--color-font-secondary);
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
    background: var(--color-error-light);
    color: var(--color-error);
  }

</style>
