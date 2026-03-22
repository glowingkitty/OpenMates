<!--
    TestSuiteCard — Shows test suite results with expandable details.
    Shows suite name + pass/fail counts + status color.
    Click expands to show individual tests.
    Admin view shows error messages for failed tests.
    Architecture: See docs/architecture/status-page.md
    Tests: N/A
-->
<script lang="ts">
    type TestResult = {
        name: string;
        file: string;
        status: string;
        duration_seconds: number;
        error?: string | null;
    };

    type SuiteSummary = {
        name: string;
        status: string;
        total: number;
        passed: number;
        failed: number;
        skipped: number;
        flaky: number;
    };

    let {
        suite,
        isAdmin = false,
        onExpand,
    }: {
        suite: SuiteSummary;
        isAdmin?: boolean;
        onExpand?: (suiteName: string) => void;
    } = $props();

    let expanded = $state(false);
    let detail: TestResult[] | null = $state(null);
    let loading = $state(false);

    const statusColors: Record<string, string> = {
        passing: '#22c55e',
        failing: '#ef4444',
        passed: '#22c55e',
        failed: '#ef4444',
        skipped: '#d4d4d4',
        not_started: '#d4d4d4',
        flaky: '#f59e0b',
    };

    function toggle() {
        expanded = !expanded;
        if (expanded && !detail && onExpand) {
            loading = true;
            onExpand(suite.name);
        }
    }

    export function setDetail(tests: TestResult[]) {
        detail = tests;
        loading = false;
    }

    const suiteDisplayNames: Record<string, string> = {
        playwright: 'Playwright E2E',
        vitest: 'Vitest Unit',
        pytest_unit: 'Pytest Unit',
    };
</script>

<div class="suite-card" data-status={suite.status}>
    <button class="suite-header" onclick={toggle} aria-expanded={expanded}>
        <div class="header-left">
            <span class="status-dot" style="background: {statusColors[suite.status] ?? '#d4d4d4'}"></span>
            <span class="suite-name">{suiteDisplayNames[suite.name] ?? suite.name}</span>
        </div>
        <div class="header-right">
            <span class="count passed">{suite.passed}</span>
            <span class="separator">/</span>
            <span class="count total">{suite.total}</span>
            {#if suite.failed > 0}
                <span class="count failed">{suite.failed} failed</span>
            {/if}
            {#if suite.flaky > 0}
                <span class="count flaky">{suite.flaky} flaky</span>
            {/if}
            <span class="chevron" class:rotated={expanded}>&#9662;</span>
        </div>
    </button>

    {#if expanded}
        <div class="suite-body">
            {#if loading}
                <p class="loading-text">Loading test details...</p>
            {:else if detail && detail.length > 0}
                <ul class="test-list">
                    {#each detail as test}
                        <li class="test-row" data-test-status={test.status}>
                            <span class="test-dot" style="background: {statusColors[test.status] ?? '#d4d4d4'}"></span>
                            <span class="test-name" title={test.file}>{test.name}</span>
                            <span class="test-status">{test.status}</span>
                            {#if isAdmin && test.error}
                                <div class="test-error">{test.error}</div>
                            {/if}
                        </li>
                    {/each}
                </ul>
            {:else}
                <p class="loading-text">No test details available</p>
            {/if}
        </div>
    {/if}
</div>

<style>
    .suite-card {
        background: var(--color-grey-0, #fff);
        border: 1px solid var(--color-grey-25, #e0e0e0);
        border-radius: 10px;
        overflow: hidden;
    }

    .suite-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        width: 100%;
        padding: 0.75rem 1rem;
        background: none;
        border: none;
        cursor: pointer;
        font-family: inherit;
        font-size: var(--font-size-p, 0.875rem);
        color: var(--color-font-primary, #222);
        text-align: left;
    }

    .suite-header:hover {
        background: var(--color-grey-5, #fafafa);
    }

    .header-left {
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }

    .header-right {
        display: flex;
        align-items: center;
        gap: 0.35rem;
        font-size: 0.8rem;
    }

    .status-dot {
        width: 0.5rem;
        height: 0.5rem;
        border-radius: 50%;
        flex-shrink: 0;
    }

    .suite-name {
        font-weight: 600;
    }

    .count {
        font-variant-numeric: tabular-nums;
    }

    .count.passed {
        color: #15803d;
    }

    .count.total {
        color: var(--color-font-secondary, #999);
    }

    .count.failed {
        color: #ef4444;
        font-weight: 600;
        margin-left: 0.35rem;
    }

    .count.flaky {
        color: #f59e0b;
        font-size: 0.75rem;
        margin-left: 0.25rem;
    }

    .separator {
        color: var(--color-grey-40, #bbb);
    }

    .chevron {
        font-size: 0.75rem;
        color: var(--color-font-secondary, #999);
        transition: transform 0.2s ease;
        margin-left: 0.5rem;
    }

    .chevron.rotated {
        transform: rotate(180deg);
    }

    .suite-body {
        padding: 0 1rem 0.75rem;
        border-top: 1px solid var(--color-grey-15, #eee);
        max-height: 400px;
        overflow-y: auto;
    }

    .test-list {
        list-style: none;
        margin: 0;
        padding: 0;
    }

    .test-row {
        display: flex;
        align-items: flex-start;
        gap: 0.5rem;
        padding: 0.35rem 0;
        font-size: 0.78rem;
        flex-wrap: wrap;
    }

    .test-row + .test-row {
        border-top: 1px solid var(--color-grey-10, #f5f5f5);
    }

    .test-dot {
        width: 0.35rem;
        height: 0.35rem;
        border-radius: 50%;
        flex-shrink: 0;
        margin-top: 0.35rem;
    }

    .test-name {
        flex: 1;
        color: var(--color-font-primary, #222);
        word-break: break-word;
    }

    .test-status {
        font-size: 0.72rem;
        color: var(--color-font-secondary, #999);
        text-transform: capitalize;
    }

    .test-error {
        width: 100%;
        font-size: 0.72rem;
        color: var(--color-error, #e74c3c);
        background: rgba(239, 68, 68, 0.05);
        padding: 0.3rem 0.5rem;
        border-radius: 4px;
        margin-top: 0.15rem;
        white-space: pre-wrap;
        word-break: break-word;
        max-height: 80px;
        overflow-y: auto;
    }

    .loading-text {
        font-size: 0.82rem;
        color: var(--color-font-secondary, #999);
        padding: 0.5rem 0;
        margin: 0;
    }
</style>
