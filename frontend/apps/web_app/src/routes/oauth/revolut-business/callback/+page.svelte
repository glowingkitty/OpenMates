<!--
  Revolut Business OAuth Callback Page.

  Purpose: give users a non-broken landing page after Revolut Business consent.
  Architecture: app-domain callback UI for Finance connected-account setup.
  Security: displays only setup metadata and the short-lived authorization code;
  account reads are performed by the OpenMates server after setup completes.
  Spec: docs/specs/finance-check-accounts-v1/spec.yml
-->
<script lang="ts">
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import { getApiEndpoint } from '@repo/ui';

  const DEFAULT_CLIENT_ID = '';
  const DEFAULT_PRIVATE_KEY_PATH = '~/.openmates/revolut-business/sandbox/privatecert.pem';
  const SERVER_EGRESS_IP_PATH = '/v1/connected-accounts/setup/revolut-business/server-egress-ip';

  let copied = $state(false);
  let copiedIp = $state(false);
  let code = $derived(page.url.searchParams.get('code') ?? '');
  let error = $derived(page.url.searchParams.get('error') ?? '');
  let errorDescription = $derived(page.url.searchParams.get('error_description') ?? '');
  let clientId = $state(DEFAULT_CLIENT_ID);
  let privateKeyPath = $state(DEFAULT_PRIVATE_KEY_PATH);
  let serverIps = $state<string[]>([]);
  let serverIpError = $state('');
  let exchangeCommand = $derived(
    clientId.trim()
      ? `openmates connect-account revolut-business exchange-code --client-id "${clientId.trim()}" --private-key "${privateKeyPath.trim() || DEFAULT_PRIVATE_KEY_PATH}" --code "${page.url.href}"`
      : 'openmates connect-account revolut-business exchange-code --client-id "<ClientID>" --private-key "' + (privateKeyPath.trim() || DEFAULT_PRIVATE_KEY_PATH) + '" --code "' + page.url.href + '"'
  );
  let serverIpText = $derived(serverIps.length > 0 ? serverIps.join(', ') : 'Loading server IP...');

  onMount(async () => {
    try {
      const response = await fetch(getApiEndpoint(SERVER_EGRESS_IP_PATH), {
        headers: { Accept: 'application/json' }
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      serverIps = Array.isArray(payload.ip_addresses)
        ? payload.ip_addresses.filter((value: unknown): value is string => typeof value === 'string' && value.length > 0)
        : [];
      if (serverIps.length === 0) serverIpError = 'OpenMates could not detect the server IP automatically.';
    } catch {
      serverIpError = 'OpenMates could not detect the server IP automatically.';
    }
  });

  async function copyCommand() {
    await navigator.clipboard.writeText(exchangeCommand);
    copied = true;
    setTimeout(() => {
      copied = false;
    }, 2200);
  }

  async function copyServerIps() {
    if (serverIps.length === 0) return;
    await navigator.clipboard.writeText(serverIps.join(', '));
    copiedIp = true;
    setTimeout(() => {
      copiedIp = false;
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
        Your authorization code is ready. Finish setup in OpenMates after the OpenMates server IP is whitelisted in Revolut.
      </p>

      <div class="setup-step" data-testid="revolut-server-ip-step">
        <div>
          <span class="step-label">Required in Revolut</span>
          <strong>Production IP whitelist</strong>
        </div>
        <div class="ip-row">
          <code>{serverIpText}</code>
          <button class="secondary" type="button" onclick={copyServerIps} disabled={serverIps.length === 0} data-testid="copy-revolut-server-ip">
            {copiedIp ? 'Copied' : 'Copy IP'}
          </button>
        </div>
        <p class="hint">
          Revolut rejects account reads with HTTP 403 until this OpenMates server IP is added to the certificate whitelist.
        </p>
        {#if serverIpError}<p class="warning">{serverIpError}</p>{/if}
      </div>

      <label for="client-id">ClientID from Revolut</label>
      <input
        id="client-id"
        bind:value={clientId}
        placeholder="Paste ClientID"
        autocomplete="off"
        spellcheck="false"
        data-testid="revolut-client-id-input"
      />

      <label for="private-key-path">Private key path from the OpenMates CLI</label>
      <input
        id="private-key-path"
        bind:value={privateKeyPath}
        placeholder={DEFAULT_PRIVATE_KEY_PATH}
        autocomplete="off"
        spellcheck="false"
        data-testid="revolut-private-key-path-input"
      />
      <p class="hint compact">
        Use the path printed by the certificate generation command. If you did not pass <code>--output</code>, the default path above is correct.
      </p>

      <div class="command" data-testid="revolut-exchange-command">
        <code>{exchangeCommand}</code>
      </div>
      <button class="primary" type="button" onclick={copyCommand} data-testid="copy-revolut-command">
        {copied ? 'Copied' : 'Copy command'}
      </button>
      <p class="hint">
        This code expires quickly. If it expires, reopen the Revolut consent link from OpenMates and approve access again.
      </p>
    {:else}
      <h1>Missing Revolut authorization code</h1>
      <p class="lead">
        This callback page did not receive a Revolut code. Start the Revolut Business setup again from OpenMates.
      </p>
      <div class="command"><code>openmates connect-account revolut-business</code></div>
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

  .setup-step {
    display: grid;
    gap: 0.8rem;
    margin: 1.5rem 0;
    padding: 1rem;
    border: 1px solid var(--color-grey-30);
    border-radius: 20px;
    background: var(--color-grey-10);
  }

  .setup-step strong {
    display: block;
    margin-top: 0.15rem;
    font-size: 1.1rem;
  }

  .step-label {
    color: var(--color-font-secondary);
    font-size: 0.8rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .ip-row {
    display: flex;
    gap: 0.75rem;
    align-items: center;
    justify-content: space-between;
    padding: 0.85rem;
    border: 1px solid var(--color-grey-30);
    border-radius: 16px;
    background: var(--color-grey-0);
  }

  label {
    display: block;
    margin: 0 0 0.4rem;
    color: var(--color-font-secondary);
    font-size: 0.85rem;
    font-weight: 700;
  }

  input {
    width: 100%;
    box-sizing: border-box;
    border: 1px solid var(--color-grey-30);
    border-radius: 14px;
    padding: 0.9rem 1rem;
    background: var(--color-grey-10);
    color: var(--color-font-primary);
    font: inherit;
  }

  .command {
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

  .secondary {
    min-height: 2.4rem;
    border: 1px solid var(--color-grey-30);
    border-radius: 999px;
    padding: 0 1rem;
    background: var(--color-grey-20);
    color: var(--color-font-primary);
    font: inherit;
    font-weight: 800;
    cursor: pointer;
    white-space: nowrap;
  }

  .secondary:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }

  .hint {
    margin: 1rem 0 0;
    color: var(--color-font-secondary);
    font-size: 0.9rem;
  }

  .setup-step .hint {
    margin: 0;
  }

  .warning {
    margin: 0;
    color: var(--color-warning, #b87500);
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

  @media (max-width: 640px) {
    .ip-row {
      align-items: stretch;
      flex-direction: column;
    }
  }
</style>
