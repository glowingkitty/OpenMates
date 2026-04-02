<!--
  SettingsShareDebugLogs.svelte

  Allows any authenticated user to activate a temporary debug log sharing
  session. While active, browser console logs are forwarded to OpenObserve
  tagged with a short debugging_id. The user shares this ID with support.

  Placed under Settings > Privacy as a sub-section of the Debug Logging section.

  Architecture context: See docs/architecture/admin-console-log-forwarding.md
-->

<script lang="ts">
  import { onMount } from "svelte";
  import { getApiEndpoint, apiEndpoints } from "../../config/api";
  import { clientLogForwarder } from "../../services/clientLogForwarder";

  // ------- State -------
  let isActive = $state(false);
  let debuggingId = $state("");
  let expiresAt = $state<string | null>(null);
  let selectedDuration = $state("5m");
  let isLoading = $state(false);
  let isCopied = $state(false);
  let error = $state("");

  const durationOptions = [
    { value: "5m", label: "5 minutes" },
    { value: "1h", label: "1 hour" },
    { value: "3d", label: "3 days" },
    { value: "7d", label: "7 days" },
    { value: "none", label: "No time limit" },
  ];

  // ------- Lifecycle -------

  onMount(async () => {
    await checkExistingSession();
  });

  // ------- API helpers -------

  async function checkExistingSession(): Promise<void> {
    try {
      const response = await fetch(
        getApiEndpoint(apiEndpoints.settings.debugSession),
        { method: "GET", credentials: "include" },
      );
      if (!response.ok) return;
      const data = await response.json();
      if (data.active) {
        isActive = true;
        debuggingId = data.debugging_id ?? "";
        expiresAt = data.expires_at ?? null;
        selectedDuration = data.duration ?? "5m";

        // Also check localStorage for previously stored session
        // and resume the log forwarder if it was running
        if (debuggingId && !clientLogForwarder.isRunning) {
          clientLogForwarder.startDebugSession(debuggingId);
        }
      }
    } catch {
      // Non-critical — user just won't see an existing session
    }
  }

  async function activate(): Promise<void> {
    isLoading = true;
    error = "";

    try {
      const response = await fetch(
        getApiEndpoint(apiEndpoints.settings.debugSession),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ duration: selectedDuration }),
          credentials: "include",
        },
      );

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        error = data.detail ?? "Failed to activate debug logging";
        return;
      }

      const data = await response.json();
      isActive = true;
      debuggingId = data.debugging_id ?? "";
      expiresAt = data.expires_at ?? null;

      // Store in localStorage so the log forwarder survives page reloads
      localStorage.setItem(
        "debug_session",
        JSON.stringify({
          debugging_id: debuggingId,
          expires_at: expiresAt,
        }),
      );

      // Start the log forwarder in debug session mode
      clientLogForwarder.startDebugSession(debuggingId);

      // Start OTel tracing so browser traces also reach OpenObserve
      import("../../config/api").then(({ getApiUrl, isDevEnvironment }) => {
        if (!isDevEnvironment()) {
          import("../../services/tracing/setup").then(({ initTracing }) => {
            initTracing(getApiUrl());
          });
        }
      }).catch(() => {});
    } catch (_e) {
      error = "Network error — please try again";
    } finally {
      isLoading = false;
    }
  }

  async function deactivate(): Promise<void> {
    isLoading = true;
    error = "";

    try {
      await fetch(getApiEndpoint(apiEndpoints.settings.debugSession), {
        method: "DELETE",
        credentials: "include",
      });
    } catch {
      // Best-effort — clean up locally even if server call fails
    }

    // Stop the log forwarder and OTel tracing
    await clientLogForwarder.stop();
    import("../../services/tracing/setup").then(({ stopTracing }) => {
      void stopTracing();
    }).catch(() => {});
    localStorage.removeItem("debug_session");

    isActive = false;
    debuggingId = "";
    expiresAt = null;
    isLoading = false;
  }

  function copyId(): void {
    if (!debuggingId) return;
    navigator.clipboard.writeText(debuggingId).then(() => {
      isCopied = true;
      setTimeout(() => {
        isCopied = false;
      }, 2000);
    });
  }

  function formatExpiry(iso: string | null): string {
    if (!iso) return "No expiry";
    try {
      const date = new Date(iso);
      const now = new Date();
      const diffMs = date.getTime() - now.getTime();
      if (diffMs <= 0) return "Expired";
      const diffMin = Math.floor(diffMs / 60000);
      if (diffMin < 60) return `${diffMin}m remaining`;
      const diffHours = Math.floor(diffMin / 60);
      if (diffHours < 24) return `${diffHours}h remaining`;
      const diffDays = Math.floor(diffHours / 24);
      return `${diffDays}d remaining`;
    } catch {
      return "";
    }
  }
</script>

<div class="debug-logs-section">
  <h3>Share Debug Logs</h3>
  <p class="description">
    Temporarily share your browser console logs with the support team to help
    diagnose issues. Logs are automatically sanitized to remove passwords and
    API keys. No message content is shared.
  </p>

  {#if isActive}
    <!-- Active session view -->
    <div class="active-session">
      <div class="debug-id-display">
        <span class="field-label">Your Debug ID</span>
        <div class="id-row">
          <code class="debug-id">{debuggingId}</code>
          <button class="copy-button" onclick={copyId} aria-label="Copy debug ID">
            {isCopied ? "Copied" : "Copy"}
          </button>
        </div>
        <p class="hint">Share this ID with the support team so they can view your logs.</p>
      </div>

      {#if expiresAt}
        <p class="expiry">{formatExpiry(expiresAt)}</p>
      {:else}
        <p class="expiry">Active until manually stopped</p>
      {/if}

      <button
        class="deactivate-button"
        onclick={deactivate}
        disabled={isLoading}
      >
        {isLoading ? "Stopping..." : "Stop Sharing"}
      </button>
    </div>
  {:else}
    <!-- Activation view -->
    <div class="activate-section">
      <div class="input-group">
        <label for="debug-duration">Duration</label>
        <select
          id="debug-duration"
          bind:value={selectedDuration}
          disabled={isLoading}
        >
          {#each durationOptions as opt}
            <option value={opt.value}>{opt.label}</option>
          {/each}
        </select>
      </div>

      <button
        class="activate-button"
        onclick={activate}
        disabled={isLoading}
      >
        {isLoading ? "Activating..." : "Start Sharing Debug Logs"}
      </button>
    </div>
  {/if}

  {#if error}
    <p class="error-message">{error}</p>
  {/if}
</div>

<style>
  .debug-logs-section {
    margin-top: 1.5rem;
    padding-top: 1.5rem;
    border-top: 1px solid var(--color-grey-25);
  }

  h3 {
    font-size: var(--font-size-h4);
    font-weight: 600;
    margin-bottom: 0.5rem;
  }

  .description {
    color: var(--color-font-secondary);
    font-size: 0.875rem;
    line-height: 1.5;
    margin-bottom: 1rem;
  }

  .active-session {
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .debug-id-display .field-label {
    display: block;
    font-size: 0.8125rem;
    font-weight: 500;
    color: var(--color-font-secondary);
    margin-bottom: 0.25rem;
  }

  .id-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .debug-id {
    font-size: 1.125rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    padding: 0.5rem 0.75rem;
    background: var(--color-grey-10);
    border: 1px solid var(--color-grey-25);
    border-radius: 0.375rem;
    user-select: all;
  }

  .copy-button {
    padding: 0.5rem 0.75rem;
    font-size: 0.8125rem;
    background: var(--color-grey-10);
    border: 1px solid var(--color-grey-25);
    border-radius: 0.375rem;
    cursor: pointer;
    transition: background-color 0.15s;
  }

  .copy-button:hover {
    background: var(--color-grey-20);
  }

  .hint {
    font-size: 0.8125rem;
    color: var(--color-font-tertiary);
    margin-top: 0.25rem;
  }

  .expiry {
    font-size: 0.8125rem;
    color: var(--color-font-secondary);
  }

  .input-group {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    margin-bottom: 0.75rem;
  }

  .input-group label {
    font-size: 0.8125rem;
    font-weight: 500;
    color: var(--color-font-secondary);
  }

  select {
    padding: 0.5rem 0.75rem;
    font-size: 0.875rem;
    border: 1px solid var(--color-grey-25);
    border-radius: 0.375rem;
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    cursor: pointer;
  }

  .activate-button,
  .deactivate-button {
    width: 100%;
    padding: 0.625rem 1rem;
    font-size: 0.875rem;
    font-weight: 500;
    border: none;
    border-radius: 0.375rem;
    cursor: pointer;
    transition: background-color 0.15s;
  }

  .activate-button {
    background: var(--color-primary);
    color: var(--color-grey-0);
  }

  .activate-button:hover:not(:disabled) {
    opacity: 0.9;
  }

  .deactivate-button {
    background: var(--color-grey-10);
    border: 1px solid var(--color-grey-25);
    color: var(--color-font-primary);
  }

  .deactivate-button:hover:not(:disabled) {
    background: var(--color-grey-20);
  }

  .activate-button:disabled,
  .deactivate-button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .error-message {
    color: var(--color-error);
    font-size: 0.8125rem;
    margin-top: 0.5rem;
  }
</style>
