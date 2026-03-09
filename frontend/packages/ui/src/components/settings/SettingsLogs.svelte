<!--
  Admin Logs Settings View

  Displays a live stream of client-side console logs for admin users directly
  in the Settings panel, so debugging does not require browser devtools.
  Uses logCollector's in-memory buffers and live listener API.
  Architecture reference: docs/architecture/admin-console-log-forwarding.md
  Test references: lint_changed.sh --ts --svelte --path frontend/packages/ui
-->

<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { userProfile } from '../../stores/userProfile';
  import { logCollector, type ConsoleLogEntry } from '../../services/logCollector';

  type LogFilter = 'all' | 'warn' | 'error';

  let filter = $state<LogFilter>('all');
  let logs = $state<ConsoleLogEntry[]>([]);
  let isAdminUser = $derived($userProfile.is_admin === true);
  let debugOutput = $state<string>('');
  let debugLoading = $state(false);

  const MAX_LOGS = 400;

  function applyFilter(entries: ConsoleLogEntry[]): ConsoleLogEntry[] {
    if (filter === 'warn') return entries.filter((entry) => entry.level === 'warn');
    if (filter === 'error') return entries.filter((entry) => entry.level === 'error');
    return entries;
  }

  let filteredLogs = $derived(applyFilter(logs));

  function formatTimestamp(ts: number): string {
    return new Date(ts).toISOString().replace('T', ' ').slice(0, 23);
  }

  function loadLogsSnapshot(): void {
    logs = logCollector.getLogs(MAX_LOGS);
  }

  async function loadWindowDebugOutput(): Promise<void> {
    if (!isAdminUser || typeof window === 'undefined') return;
    const debugFn = (window as unknown as { debug?: (() => unknown) }).debug;
    if (!debugFn) {
      debugOutput = 'window.debug() is not available in this runtime.';
      return;
    }

    debugLoading = true;
    try {
      const result = await Promise.resolve(debugFn());
      if (typeof result === 'string') {
        debugOutput = result;
      } else if (result === undefined) {
        debugOutput = 'window.debug() executed. Check logs below.';
      } else {
        debugOutput = JSON.stringify(result, null, 2);
      }
    } catch (error) {
      debugOutput = error instanceof Error
        ? `window.debug() failed: ${error.message}`
        : `window.debug() failed: ${String(error)}`;
    } finally {
      debugLoading = false;
    }
  }

  let detachListener: (() => void) | null = null;

  onMount(() => {
    if (!isAdminUser) return;

    void loadWindowDebugOutput();
    loadLogsSnapshot();

    const listener = (entry: ConsoleLogEntry) => {
      logs = [...logs, entry].slice(-MAX_LOGS);
    };
    logCollector.onNewLog(listener);
    detachListener = () => {
      logCollector.offNewLog(listener);
      detachListener = null;
    };
  });

  onDestroy(() => {
    detachListener?.();
  });
</script>

{#if !isAdminUser}
  <div class="logs-unavailable">Logs are available for admin users only.</div>
{:else}
  <div class="logs-debug-box selectable">
    <div class="logs-debug-header-row">
      <span class="logs-debug-title">window.debug()</span>
      <button class="logs-debug-refresh" onclick={loadWindowDebugOutput} disabled={debugLoading}>
        {debugLoading ? 'Loading...' : 'Refresh'}
      </button>
    </div>
    <pre class="logs-debug-pre selectable">{debugOutput || 'No debug output yet.'}</pre>
  </div>

  <div class="logs-toolbar">
    <button class="logs-filter" class:active={filter === 'all'} onclick={() => (filter = 'all')}>All</button>
    <button class="logs-filter" class:active={filter === 'warn'} onclick={() => (filter = 'warn')}>Warnings</button>
    <button class="logs-filter" class:active={filter === 'error'} onclick={() => (filter = 'error')}>Errors</button>
    <button class="logs-refresh" onclick={loadLogsSnapshot}>Refresh</button>
  </div>

  <div class="logs-container selectable">
    {#if filteredLogs.length === 0}
      <div class="logs-empty">No logs for this filter yet.</div>
    {:else}
      {#each filteredLogs as entry (entry.timestamp + ':' + entry.level + ':' + entry.message)}
        <div class="log-line {entry.level}">
          <span class="ts">[{formatTimestamp(entry.timestamp)}]</span>
          <span class="lvl">{entry.level.toUpperCase()}</span>
          <span class="msg selectable">{entry.message}</span>
        </div>
      {/each}
    {/if}
  </div>
{/if}

<style>
  .logs-toolbar {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 0.75rem;
    flex-wrap: wrap;
  }

  .logs-debug-box {
    margin: 0 0 0.75rem;
    padding: 0.75rem;
    border-radius: 0.75rem;
    border: 1px solid var(--color-grey-30);
    background: var(--color-grey-10);
  }

  .logs-debug-header-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.5rem;
  }

  .logs-debug-title {
    font-size: 0.82rem;
    font-weight: 600;
    color: var(--color-font-secondary);
  }

  .logs-debug-refresh {
    all: unset;
    cursor: pointer;
    font-size: 0.78rem;
    color: var(--color-primary);
  }

  .logs-debug-refresh:disabled {
    opacity: 0.6;
    cursor: default;
  }

  .logs-debug-pre {
    margin: 0;
    max-height: 12rem;
    overflow: auto;
    white-space: pre-wrap;
    word-break: break-word;
    font-family: monospace;
    font-size: 0.76rem;
    line-height: 1.4;
    color: var(--color-font-primary);
  }

  .logs-filter,
  .logs-refresh {
    all: unset;
    cursor: pointer;
    border-radius: 999px;
    padding: 0.4rem 0.7rem;
    font-size: 0.8rem;
    border: 1px solid var(--color-grey-30);
    color: var(--color-font-secondary);
    background: var(--color-grey-10);
  }

  .logs-filter.active {
    color: var(--color-primary);
    border-color: var(--color-primary);
  }

  .logs-container {
    border: 1px solid var(--color-grey-30);
    background: var(--color-grey-10);
    border-radius: 0.75rem;
    padding: 0.75rem;
    max-height: 24rem;
    overflow: auto;
  }

  .logs-empty,
  .logs-unavailable {
    color: var(--color-font-secondary);
    font-size: 0.85rem;
  }

  .log-line {
    display: grid;
    grid-template-columns: auto auto 1fr;
    gap: 0.5rem;
    font-family: monospace;
    font-size: 0.76rem;
    line-height: 1.45;
    color: var(--color-font-primary);
    margin-bottom: 0.25rem;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .log-line.warn .lvl {
    color: var(--color-warning);
  }

  .log-line.error .lvl {
    color: var(--color-error);
  }

  .ts {
    color: var(--color-font-tertiary);
  }

  .lvl {
    font-weight: 700;
  }

  .msg {
    user-select: text;
    -webkit-user-select: text;
    -moz-user-select: text;
    -ms-user-select: text;
  }
</style>
