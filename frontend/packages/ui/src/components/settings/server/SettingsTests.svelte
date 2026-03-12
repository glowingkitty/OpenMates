<!--
    Settings Tests Component — Admin-only

    Displays the latest automated test run results, scheduling info, and
    provides a button to trigger out-of-schedule test runs. Reads data from
    GET /v1/admin/test-results which serves the on-disk JSON results.

    Architecture: No database model — reads existing JSON files via the API.
    See scripts/run-tests.sh for the test result format.
-->
<script lang="ts">
    import { onMount } from 'svelte';
    import { getApiEndpoint, text } from '@repo/ui';
    import { fade } from 'svelte/transition';
    import SettingsItem from '../../SettingsItem.svelte';

    // ============================================================================
    // TYPE DEFINITIONS
    // ============================================================================

    interface TestEntry {
        file?: string;
        name?: string;
        status: string;
        duration_seconds?: number;
        error?: string;
        stdout?: string;
        slot?: number;
    }

    interface SuiteResult {
        status: string;
        duration_seconds?: number;
        tests?: TestEntry[];
        workers?: number;
        reason?: string;
    }

    interface TestRunData {
        run_id: string;
        git_sha: string;
        git_branch: string;
        duration_seconds: number;
        summary: {
            total: number;
            passed: number;
            failed: number;
            skipped: number;
            not_started?: number;
        };
        suites: {
            vitest?: SuiteResult;
            pytest_unit?: SuiteResult;
            pytest_integration?: SuiteResult;
            playwright?: SuiteResult;
        };
    }

    interface TestResultsResponse {
        has_results: boolean;
        last_run: TestRunData | null;
        last_run_timestamp: string | null;
        next_scheduled_run_utc: string;
        hours_until_next_run: number;
        is_running: boolean;
        run_started_at: string | null;
    }

    // ============================================================================
    // STATE
    // ============================================================================

    let isLoading = $state(true);
    let error = $state<string | null>(null);
    let data = $state<TestResultsResponse | null>(null);
    let isTriggering = $state(false);
    let triggerMessage = $state<string | null>(null);
    let expandedSuites = $state<Record<string, boolean>>({});
    let expandedErrors = $state<Record<string, boolean>>({});

    // Optimistic "running" state — set immediately on trigger to prevent
    // double-clicks, cleared when the next poll confirms actual state.
    let optimisticRunning = $state(false);
    let optimisticRunStartedAt = $state<string | null>(null);

    // Auto-refresh interval ID
    let refreshIntervalId: ReturnType<typeof setInterval> | undefined;

    // Auto-refresh interval in ms (30 seconds while running, 5 minutes otherwise)
    const REFRESH_INTERVAL_RUNNING_MS = 30_000;
    const REFRESH_INTERVAL_IDLE_MS = 300_000;

    // ============================================================================
    // COMPUTED
    // ============================================================================

    let lastRun = $derived(data?.last_run ?? null);
    let summary = $derived(lastRun?.summary ?? null);
    let isRunning = $derived(optimisticRunning || (data?.is_running ?? false));

    let lastRunTimeAgo = $derived.by(() => {
        if (!data?.last_run_timestamp) return null;
        return formatTimeAgo(data.last_run_timestamp);
    });

    let lastRunDate = $derived.by(() => {
        if (!data?.last_run_timestamp) return null;
        return formatDate(data.last_run_timestamp);
    });

    let nextRunDisplay = $derived.by(() => {
        if (!data) return null;
        const hours = data.hours_until_next_run;
        if (hours < 1) {
            const minutes = Math.round(hours * 60);
            return `${minutes}m`;
        }
        return `${Math.floor(hours)}h ${Math.round((hours % 1) * 60)}m`;
    });

    let durationDisplay = $derived.by(() => {
        if (!lastRun) return null;
        return formatDuration(lastRun.duration_seconds);
    });

    let suiteEntries = $derived.by(() => {
        if (!lastRun?.suites) return [];
        const order: Array<[string, string]> = [
            ['vitest', 'Vitest (Unit)'],
            ['pytest_unit', 'Pytest (Unit)'],
            ['pytest_integration', 'Pytest (Integration)'],
            ['playwright', 'Playwright (E2E)'],
        ];
        return order
            .filter(([key]) => lastRun!.suites[key as keyof typeof lastRun.suites] !== undefined)
            .map(([key, label]) => ({
                key,
                label,
                suite: lastRun!.suites[key as keyof typeof lastRun.suites] as SuiteResult,
            }));
    });

    // ============================================================================
    // FORMATTING HELPERS
    // ============================================================================

    function formatTimeAgo(isoTimestamp: string): string {
        const now = new Date();
        const then = new Date(isoTimestamp);
        const diffMs = now.getTime() - then.getTime();
        const diffMinutes = Math.floor(diffMs / 60_000);
        const diffHours = Math.floor(diffMs / 3_600_000);
        const diffDays = Math.floor(diffMs / 86_400_000);

        if (diffMinutes < 1) return 'just now';
        if (diffMinutes < 60) return `${diffMinutes}m ago`;
        if (diffHours < 24) return `${diffHours}h ${diffMinutes % 60}m ago`;
        return `${diffDays}d ago`;
    }

    function formatDate(isoTimestamp: string): string {
        const d = new Date(isoTimestamp);
        return d.toLocaleString(undefined, {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            timeZoneName: 'short',
        });
    }

    function formatDuration(seconds: number): string {
        if (seconds < 60) return `${seconds}s`;
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        if (mins < 60) return `${mins}m ${secs}s`;
        const hours = Math.floor(mins / 60);
        return `${hours}h ${mins % 60}m`;
    }

    function statusIcon(status: string): string {
        switch (status) {
            case 'passed': return '\u2705';
            case 'failed': return '\u274C';
            case 'skipped': return '\u23ED\uFE0F';
            case 'not_started': return '\u23F8\uFE0F';
            case 'error': return '\u26A0\uFE0F';
            default: return '\u2753';
        }
    }

    // ============================================================================
    // API CALLS
    // ============================================================================

    async function fetchTestResults() {
        try {
            error = null;
            const response = await fetch(getApiEndpoint('/v1/admin/test-results'), {
                credentials: 'include',
            });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            data = await response.json();
        } catch (e) {
            const errMsg = e instanceof Error ? e.message : String(e);
            error = `Failed to load test results: ${errMsg}`;
            console.error('[SettingsTests] Failed to fetch test results:', e);
        } finally {
            isLoading = false;

            // Clear optimistic running state once the server confirms
            // the run has finished (or was never started).
            if (optimisticRunning && data && !data.is_running) {
                optimisticRunning = false;
                optimisticRunStartedAt = null;
            }
        }
    }

    async function triggerTestRun() {
        if (isTriggering || isRunning) return;

        isTriggering = true;
        triggerMessage = null;

        try {
            const response = await fetch(getApiEndpoint('/v1/admin/tests/run'), {
                method: 'POST',
                credentials: 'include',
            });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            const result = await response.json();
            triggerMessage = result.message;

            if (result.success) {
                // Set optimistic running state immediately — prevents double-clicks
                // and shows "Running" feedback before the next poll confirms it.
                optimisticRunning = true;
                optimisticRunStartedAt = new Date().toISOString();

                // Refresh to get authoritative state from server
                await fetchTestResults();
                // Switch to faster polling while running
                setupAutoRefresh();
            }
        } catch (e) {
            const errMsg = e instanceof Error ? e.message : String(e);
            triggerMessage = `Failed to start tests: ${errMsg}`;
            console.error('[SettingsTests] Failed to trigger test run:', e);
            // Clear optimistic state on error so the button re-enables
            optimisticRunning = false;
            optimisticRunStartedAt = null;
        } finally {
            isTriggering = false;
        }
    }

    // ============================================================================
    // AUTO-REFRESH
    // ============================================================================

    function setupAutoRefresh() {
        if (refreshIntervalId) clearInterval(refreshIntervalId);
        const interval = isRunning ? REFRESH_INTERVAL_RUNNING_MS : REFRESH_INTERVAL_IDLE_MS;
        refreshIntervalId = setInterval(async () => {
            await fetchTestResults();
            // Adjust refresh rate if running state changed
            const newInterval = isRunning ? REFRESH_INTERVAL_RUNNING_MS : REFRESH_INTERVAL_IDLE_MS;
            if (newInterval !== interval) {
                setupAutoRefresh();
            }
        }, interval);
    }

    // ============================================================================
    // TOGGLE HELPERS
    // ============================================================================

    function toggleSuite(key: string) {
        expandedSuites = { ...expandedSuites, [key]: !expandedSuites[key] };
    }

    function toggleError(testId: string) {
        expandedErrors = { ...expandedErrors, [testId]: !expandedErrors[testId] };
    }

    // ============================================================================
    // LIFECYCLE
    // ============================================================================

    onMount(() => {
        fetchTestResults().then(() => setupAutoRefresh());
        return () => {
            if (refreshIntervalId) clearInterval(refreshIntervalId);
        };
    });
</script>

<div class="settings-tests" in:fade={{ duration: 300 }}>
    <SettingsItem
        type="heading"
        icon="check"
        subtitleTop={$text('settings.server.tests.description')}
        title={$text('settings.server.tests')}
    />

    {#if isLoading}
        <div class="loading">
            <div class="spinner"></div>
            <p>Loading test results...</p>
        </div>
    {:else if error}
        <div class="error-banner">
            <p>{error}</p>
            <button class="retry-btn" onclick={() => { isLoading = true; fetchTestResults(); }}>
                Retry
            </button>
        </div>
    {:else if data}
        <!-- Running indicator -->
        {#if isRunning}
            <div class="running-banner" in:fade={{ duration: 200 }}>
                <div class="running-indicator">
                    <div class="spinner small"></div>
                    <span>Test run in progress...</span>
                </div>
                {#if data.run_started_at || optimisticRunStartedAt}
                    <span class="running-since">Started {formatTimeAgo(data.run_started_at ?? optimisticRunStartedAt ?? '')}</span>
                {/if}
            </div>
        {/if}

        <!-- Schedule Info -->
        <div class="schedule-row">
            <div class="schedule-item">
                <span class="schedule-label">{$text('settings.server.tests.last_run')}</span>
                <span class="schedule-value" title={lastRunDate ?? ''}>
                    {lastRunTimeAgo ?? $text('settings.server.tests.never')}
                </span>
            </div>
            <div class="schedule-item">
                <span class="schedule-label">{$text('settings.server.tests.next_run')}</span>
                <span class="schedule-value">{nextRunDisplay}</span>
            </div>
            {#if lastRun}
                <div class="schedule-item">
                    <span class="schedule-label">{$text('settings.server.tests.duration')}</span>
                    <span class="schedule-value">{durationDisplay}</span>
                </div>
            {/if}
        </div>

        <!-- Start Tests Button -->
        <div class="action-row">
            <button
                class="start-tests-btn"
                onclick={triggerTestRun}
                disabled={isTriggering || isRunning}
            >
                {#if isTriggering}
                    <div class="spinner small"></div>
                    <span>{$text('settings.server.tests.starting')}</span>
                {:else if isRunning}
                    <span>{$text('settings.server.tests.running')}</span>
                {:else}
                    <span>{$text('settings.server.tests.start_tests')}</span>
                {/if}
            </button>
            {#if triggerMessage}
                <p class="trigger-message" in:fade={{ duration: 200 }}>{triggerMessage}</p>
            {/if}
        </div>

        <!-- Summary Cards -->
        {#if summary}
            <div class="summary-cards">
                <div class="summary-card total">
                    <span class="card-value">{summary.total}</span>
                    <span class="card-label">{$text('settings.server.tests.total')}</span>
                </div>
                <div class="summary-card passed">
                    <span class="card-value">{summary.passed}</span>
                    <span class="card-label">{$text('settings.server.tests.passed')}</span>
                </div>
                <div class="summary-card failed" class:highlight={summary.failed > 0}>
                    <span class="card-value">{summary.failed}</span>
                    <span class="card-label">{$text('settings.server.tests.failed')}</span>
                </div>
                <div class="summary-card skipped">
                    <span class="card-value">{summary.skipped}</span>
                    <span class="card-label">{$text('settings.server.tests.skipped')}</span>
                </div>
                {#if summary.not_started !== undefined && summary.not_started > 0}
                    <div class="summary-card not-started">
                        <span class="card-value">{summary.not_started}</span>
                        <span class="card-label">{$text('settings.server.tests.not_started')}</span>
                    </div>
                {/if}
            </div>

            <!-- Git info -->
            {#if lastRun}
                <div class="git-info">
                    <span class="git-badge">{lastRun.git_branch}</span>
                    <span class="git-sha">{lastRun.git_sha}</span>
                </div>
            {/if}
        {/if}

        <!-- Suite Breakdown -->
        {#if suiteEntries.length > 0}
            <div class="suites-section">
                <h3 class="section-title">{$text('settings.server.tests.suite_breakdown')}</h3>
                {#each suiteEntries as { key, label, suite }}
                    <div class="suite-block">
                        <button
                            class="suite-header"
                            onclick={() => toggleSuite(key)}
                        >
                            <span class="suite-status-dot {suite.status}"></span>
                            <span class="suite-name">{label}</span>
                            {#if suite.tests}
                                <span class="suite-count">
                                    {suite.tests.filter(t => t.status === 'passed').length}/{suite.tests.length}
                                </span>
                            {/if}
                            {#if suite.duration_seconds !== undefined}
                                <span class="suite-duration">{formatDuration(suite.duration_seconds)}</span>
                            {/if}
                            <span class="chevron" class:expanded={expandedSuites[key]}></span>
                        </button>

                        {#if expandedSuites[key] && suite.tests}
                            <div class="suite-tests" in:fade={{ duration: 150 }}>
                                {#each suite.tests as test, idx}
                                    {@const testId = `${key}-${idx}`}
                                    <div class="test-row {test.status}">
                                        <span class="test-status">{statusIcon(test.status)}</span>
                                        <span class="test-name">{test.file || test.name || `Test ${idx + 1}`}</span>
                                        {#if test.duration_seconds !== undefined}
                                            <span class="test-duration">{formatDuration(Math.round(test.duration_seconds))}</span>
                                        {/if}
                                        {#if test.error}
                                            <button
                                                class="error-toggle"
                                                onclick={() => toggleError(testId)}
                                            >
                                                {expandedErrors[testId] ? 'Hide' : 'Show'} error
                                            </button>
                                        {/if}
                                    </div>
                                    {#if test.error && expandedErrors[testId]}
                                        <div class="error-detail" in:fade={{ duration: 100 }}>
                                            <pre>{test.error}</pre>
                                        </div>
                                    {/if}
                                {/each}
                            </div>
                        {:else if expandedSuites[key] && suite.reason}
                            <div class="suite-reason" in:fade={{ duration: 150 }}>
                                <p>{suite.reason}</p>
                            </div>
                        {/if}
                    </div>
                {/each}
            </div>
        {:else if !data.has_results}
            <div class="no-results">
                <p>{$text('settings.server.tests.no_results')}</p>
            </div>
        {/if}
    {/if}
</div>

<style>
    .settings-tests {
        padding: 0 0 2rem 0;
    }

    /* Loading & Error */
    .loading {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 1rem;
        padding: 3rem 1rem;
        color: var(--color-grey-60);
    }

    .spinner {
        width: 32px;
        height: 32px;
        border: 3px solid var(--color-grey-30);
        border-top-color: var(--color-primary);
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
    }

    .spinner.small {
        width: 16px;
        height: 16px;
        border-width: 2px;
    }

    @keyframes spin {
        to { transform: rotate(360deg); }
    }

    .error-banner {
        margin: 1rem;
        padding: 1rem;
        background: var(--color-red-10, #fef2f2);
        border: 1px solid var(--color-red-30, #fca5a5);
        border-radius: 8px;
        text-align: center;
    }

    .error-banner p {
        color: var(--color-red-60, #dc2626);
        margin: 0 0 0.5rem 0;
        font-size: 0.875rem;
    }

    .retry-btn {
        background: var(--color-red-50, #ef4444);
        color: white;
        border: none;
        border-radius: 6px;
        padding: 0.4rem 1rem;
        cursor: pointer;
        font-size: 0.8rem;
    }

    .retry-btn:hover {
        opacity: 0.9;
    }

    /* Running Banner */
    .running-banner {
        margin: 0.75rem 1rem;
        padding: 0.75rem 1rem;
        background: var(--color-blue-10, #eff6ff);
        border: 1px solid var(--color-blue-30, #93c5fd);
        border-radius: 8px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.5rem;
        flex-wrap: wrap;
    }

    .running-indicator {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        color: var(--color-blue-60, #2563eb);
        font-weight: 500;
        font-size: 0.875rem;
    }

    .running-since {
        color: var(--color-blue-50, #3b82f6);
        font-size: 0.8rem;
    }

    /* Schedule Row */
    .schedule-row {
        display: flex;
        gap: 1rem;
        padding: 0.75rem 1rem;
        margin: 0.5rem 1rem;
        background: var(--color-grey-10, #f9fafb);
        border-radius: 8px;
        flex-wrap: wrap;
    }

    .schedule-item {
        display: flex;
        flex-direction: column;
        gap: 0.2rem;
        min-width: 80px;
        flex: 1;
    }

    .schedule-label {
        font-size: 0.7rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: var(--color-grey-50);
        font-weight: 500;
    }

    .schedule-value {
        font-size: 0.9rem;
        font-weight: 600;
        color: var(--color-grey-80, #1f2937);
    }

    /* Action Row */
    .action-row {
        padding: 0.75rem 1rem;
        display: flex;
        align-items: center;
        gap: 1rem;
        flex-wrap: wrap;
    }

    .start-tests-btn {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.6rem 1.25rem;
        background: var(--color-primary, #6366f1);
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 0.875rem;
        font-weight: 500;
        cursor: pointer;
        transition: opacity 0.2s, background 0.2s;
    }

    .start-tests-btn:hover:not(:disabled) {
        opacity: 0.9;
    }

    .start-tests-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .trigger-message {
        font-size: 0.8rem;
        color: var(--color-grey-60);
        margin: 0;
    }

    /* Summary Cards */
    .summary-cards {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(90px, 1fr));
        gap: 0.5rem;
        padding: 0.5rem 1rem;
        margin: 0.5rem 0;
    }

    .summary-card {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 0.25rem;
        padding: 0.75rem 0.5rem;
        border-radius: 8px;
        background: var(--color-grey-10, #f9fafb);
        border: 1px solid var(--color-grey-20, #e5e7eb);
    }

    .summary-card.passed {
        background: var(--color-green-10, #f0fdf4);
        border-color: var(--color-green-30, #86efac);
    }

    .summary-card.failed {
        background: var(--color-grey-10, #f9fafb);
        border-color: var(--color-grey-20, #e5e7eb);
    }

    .summary-card.failed.highlight {
        background: var(--color-red-10, #fef2f2);
        border-color: var(--color-red-30, #fca5a5);
    }

    .summary-card.skipped, .summary-card.not-started {
        background: var(--color-yellow-10, #fefce8);
        border-color: var(--color-yellow-30, #fde68a);
    }

    .card-value {
        font-size: 1.5rem;
        font-weight: 700;
        color: var(--color-grey-80, #1f2937);
    }

    .card-label {
        font-size: 0.7rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: var(--color-grey-50);
        font-weight: 500;
    }

    /* Git Info */
    .git-info {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.25rem 1rem;
        margin-bottom: 0.5rem;
    }

    .git-badge {
        display: inline-block;
        padding: 0.15rem 0.5rem;
        background: var(--color-grey-20, #e5e7eb);
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 500;
        color: var(--color-grey-70, #374151);
        font-family: monospace;
    }

    .git-sha {
        font-size: 0.75rem;
        color: var(--color-grey-50);
        font-family: monospace;
    }

    /* Suite Section */
    .suites-section {
        padding: 0 1rem;
    }

    .section-title {
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: var(--color-grey-50);
        font-weight: 600;
        margin: 1rem 0 0.5rem 0;
    }

    .suite-block {
        margin-bottom: 0.25rem;
        border-radius: 8px;
        overflow: hidden;
        border: 1px solid var(--color-grey-20, #e5e7eb);
    }

    .suite-header {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        width: 100%;
        padding: 0.65rem 0.75rem;
        background: var(--color-grey-10, #f9fafb);
        border: none;
        cursor: pointer;
        font-size: 0.85rem;
        color: var(--color-grey-80, #1f2937);
        text-align: left;
        transition: background 0.15s;
    }

    .suite-header:hover {
        background: var(--color-grey-15, #f3f4f6);
    }

    .suite-status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        flex-shrink: 0;
    }

    .suite-status-dot.passed {
        background: var(--color-green-50, #22c55e);
    }

    .suite-status-dot.failed {
        background: var(--color-red-50, #ef4444);
    }

    .suite-status-dot.skipped {
        background: var(--color-yellow-50, #eab308);
    }

    .suite-name {
        font-weight: 500;
        flex: 1;
    }

    .suite-count {
        font-size: 0.75rem;
        color: var(--color-grey-50);
    }

    .suite-duration {
        font-size: 0.75rem;
        color: var(--color-grey-50);
        font-family: monospace;
    }

    .chevron {
        width: 0;
        height: 0;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid var(--color-grey-40);
        transition: transform 0.2s;
        flex-shrink: 0;
    }

    .chevron.expanded {
        transform: rotate(180deg);
    }

    /* Test Rows */
    .suite-tests {
        border-top: 1px solid var(--color-grey-20, #e5e7eb);
    }

    .test-row {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.45rem 0.75rem 0.45rem 1.5rem;
        font-size: 0.8rem;
        border-bottom: 1px solid var(--color-grey-15, #f3f4f6);
    }

    .test-row:last-child {
        border-bottom: none;
    }

    .test-row.failed {
        background: var(--color-red-5, #fff5f5);
    }

    .test-status {
        flex-shrink: 0;
        font-size: 0.75rem;
    }

    .test-name {
        flex: 1;
        word-break: break-all;
        color: var(--color-grey-70, #374151);
    }

    .test-duration {
        font-size: 0.7rem;
        color: var(--color-grey-50);
        font-family: monospace;
        flex-shrink: 0;
    }

    .error-toggle {
        font-size: 0.7rem;
        color: var(--color-red-50, #ef4444);
        background: none;
        border: 1px solid var(--color-red-30, #fca5a5);
        border-radius: 4px;
        padding: 0.15rem 0.4rem;
        cursor: pointer;
        flex-shrink: 0;
    }

    .error-toggle:hover {
        background: var(--color-red-10, #fef2f2);
    }

    .error-detail {
        padding: 0.5rem 0.75rem 0.5rem 1.5rem;
        background: var(--color-grey-5, #fafafa);
        border-bottom: 1px solid var(--color-grey-15, #f3f4f6);
    }

    .error-detail pre {
        font-size: 0.7rem;
        line-height: 1.4;
        color: var(--color-red-60, #dc2626);
        white-space: pre-wrap;
        word-break: break-word;
        margin: 0;
        max-height: 300px;
        overflow-y: auto;
    }

    .suite-reason {
        padding: 0.5rem 0.75rem 0.5rem 1.5rem;
        border-top: 1px solid var(--color-grey-20, #e5e7eb);
    }

    .suite-reason p {
        font-size: 0.8rem;
        color: var(--color-grey-50);
        margin: 0;
    }

    /* No Results */
    .no-results {
        padding: 2rem 1rem;
        text-align: center;
        color: var(--color-grey-50);
        font-size: 0.875rem;
    }

    /* Dark mode adjustments */
    :global(.dark) .schedule-row,
    :global(.dark) .suite-header {
        background: var(--color-grey-15, #1f2937);
    }

    :global(.dark) .suite-header:hover {
        background: var(--color-grey-20, #374151);
    }

    :global(.dark) .summary-card {
        background: var(--color-grey-15, #1f2937);
        border-color: var(--color-grey-25, #374151);
    }

    :global(.dark) .card-value,
    :global(.dark) .schedule-value,
    :global(.dark) .suite-name,
    :global(.dark) .test-name {
        color: var(--color-grey-90, #f9fafb);
    }

    :global(.dark) .git-badge {
        background: var(--color-grey-25, #374151);
        color: var(--color-grey-80, #d1d5db);
    }

    :global(.dark) .running-banner {
        background: var(--color-blue-90, #1e3a5f);
        border-color: var(--color-blue-60, #2563eb);
    }

    :global(.dark) .running-indicator {
        color: var(--color-blue-30, #93c5fd);
    }
</style>
