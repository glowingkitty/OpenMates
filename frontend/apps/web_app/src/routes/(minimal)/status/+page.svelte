<!--
    Status Page — /status
    Public page showing service health and test results.
    Dark mode supported via CSS variables from theme.css.
    No admin probe (CORS conflict) — admin features deferred.
    Architecture: See docs/architecture/status-page.md
    Tests: frontend/packages/ui/src/components/status/__tests__/statusPage.test.ts
-->
<script lang="ts">
    import { onMount } from 'svelte';
    import { browser } from '$app/environment';
    import { getApiEndpoint } from '@repo/ui';

    // --- Types ---
    type GroupSummary = {
        group_name: string;
        display_name: string;
        status: string;
        service_count: number;
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

    type TrendPoint = { date: string; total: number; passed: number; failed: number };
    type TimelineBucket = { start: string; end: string; status: string };

    type CategoryData = {
        total: number;
        passed: number;
        failed: number;
        skipped: number;
        pass_rate: number;
        history: { date: string; pass_rate: number; total: number; passed: number; failed: number }[];
    };

    type StatusResponse = {
        overall_status: string;
        last_updated: string;
        is_admin: boolean;
        health?: { groups: GroupSummary[] };
        timeline?: { period_days: number; buckets: TimelineBucket[] };
        tests?: {
            overall_status: string;
            latest_run: { run_id: string; timestamp: string; summary: Record<string, number> } | null;
            suites: SuiteSummary[];
            trend: TrendPoint[];
            categories: Record<string, CategoryData>;
        };
        incidents?: { total_last_30d: number };
    };

    // --- State ---
    let loading = $state(true);
    let error = $state('');
    let statusData: StatusResponse | null = $state(null);
    let expandedSections: Record<string, boolean> = $state({});

    // --- Helpers ---
    async function fetchJson(path: string): Promise<any> {
        const url = getApiEndpoint(path);
        const res = await fetch(url);
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        return res.json();
    }

    async function loadSummary() {
        try {
            statusData = await fetchJson('/v1/status');
            error = '';
        } catch (e) {
            console.error('[STATUS] Failed to load:', e);
            error = 'Could not load status data.';
        } finally {
            loading = false;
        }
    }

    function toggleSection(key: string) {
        expandedSections[key] = !expandedSections[key];
    }

    /** Interpolate between green (#22c55e) and red (#ef4444) based on pass rate 0-100 */
    function passRateColor(rate: number): string {
        const r = Math.round(0x22 + (0xef - 0x22) * (1 - rate / 100));
        const g = Math.round(0xc5 + (0x44 - 0xc5) * (1 - rate / 100));
        const b = Math.round(0x5e + (0x44 - 0x5e) * (1 - rate / 100));
        return `rgb(${r}, ${g}, ${b})`;
    }

    function statusColor(status: string): string {
        if (status === 'operational') return '#22c55e';
        if (status === 'degraded') return '#f59e0b';
        if (status === 'down') return '#ef4444';
        return 'var(--color-grey-40, #999)';
    }

    function formatTime(iso: string): string {
        try { return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); } catch { return iso; }
    }

    function formatDate(iso: string): string {
        try { return new Date(iso).toLocaleDateString([], { month: 'short', day: 'numeric' }); } catch { return iso; }
    }

    const suiteDisplayNames: Record<string, string> = {
        playwright: 'End to End Tests',
        vitest: 'Unit Tests (Frontend)',
        pytest_unit: 'Unit Tests (Backend)',
    };

    const statusLabels: Record<string, string> = {
        operational: 'All Systems Operational',
        degraded: 'Partial Degradation',
        down: 'Major Outage',
        unknown: 'Status Unknown',
    };

    // --- Lifecycle ---
    onMount(() => {
        if (!browser) return;
        loadSummary();
        const timer = setInterval(loadSummary, 60_000);
        return () => clearInterval(timer);
    });
</script>

<svelte:head>
    <title>OpenMates Status</title>
</svelte:head>

<main class="sp">
    <!-- Header -->
    <header class="sp-header">
        <h1>OpenMates Status</h1>
        {#if statusData}
            <div class="badge" data-status={statusData.overall_status}>
                <span class="badge-dot"></span>
                {statusLabels[statusData.overall_status] ?? statusLabels.unknown}
            </div>
            <p class="updated">Updated {formatTime(statusData.last_updated)}</p>
        {/if}
    </header>

    {#if loading}
        <p class="msg">Loading...</p>
    {:else if error}
        <p class="msg err">{error}</p>
    {:else if statusData}
        <!-- 30-Day Health Timeline -->
        {#if statusData.timeline?.buckets?.length}
            <section class="sec">
                <h2 class="sec-title">30-Day Health Overview</h2>
                <div class="timeline" role="img" aria-label="30-day health timeline">
                    {#each statusData.timeline.buckets as bucket, i}
                        <div
                            class="tl-seg"
                            style="background:{statusColor(bucket.status)}"
                            title="{formatDate(bucket.start)}: {bucket.status}"
                        ></div>
                    {/each}
                </div>
                <div class="tl-range"><span>30d ago</span><span>Now</span></div>
            </section>
        {/if}

        <!-- Service Groups -->
        {#if statusData.health?.groups?.length}
            <section class="sec">
                <h2 class="sec-title">Services</h2>
                {#each statusData.health.groups as group (group.group_name)}
                    <div class="row">
                        <span class="dot" style="background:{statusColor(group.status)}"></span>
                        <span class="row-name">{group.display_name}</span>
                        <span class="row-count">{group.service_count}</span>
                        <span class="row-status" style="color:{statusColor(group.status)}">{group.status}</span>
                    </div>
                {/each}
            </section>
        {/if}

        <!-- Test Suites -->
        {#if statusData.tests}
            <section class="sec">
                <div class="sec-head">
                    <h2 class="sec-title">Tests</h2>
                    {#if statusData.tests.latest_run}
                        <span class="meta">
                            {statusData.tests.latest_run.summary.passed ?? 0}/{statusData.tests.latest_run.summary.total ?? 0} passed
                        </span>
                    {/if}
                </div>

                <!-- Suite summary rows -->
                {#each statusData.tests.suites as suite (suite.name)}
                    <div class="row">
                        <span class="dot" style="background:{suite.failed > 0 ? '#ef4444' : '#22c55e'}"></span>
                        <span class="row-name">{suiteDisplayNames[suite.name] ?? suite.name}</span>
                        <span class="row-count">{suite.passed}/{suite.total}</span>
                        {#if suite.failed > 0}
                            <span class="row-fail">{suite.failed} failed</span>
                        {/if}
                    </div>
                {/each}

                <!-- Test categories with 30-day colored history -->
                {#if statusData.tests.categories && Object.keys(statusData.tests.categories).length > 0}
                    <h3 class="sub-title">Test Categories (30-day history)</h3>
                    {#each Object.entries(statusData.tests.categories).sort((a, b) => a[0].localeCompare(b[0])) as [catName, cat]}
                        <button class="cat-row" onclick={() => toggleSection(`cat-${catName}`)}>
                            <div class="cat-left">
                                <span class="dot" style="background:{passRateColor(cat.pass_rate)}"></span>
                                <span class="cat-name">{catName}</span>
                                <span class="cat-counts">{cat.passed}/{cat.total}</span>
                                {#if cat.failed > 0}
                                    <span class="cat-fail">{cat.failed} failed</span>
                                {/if}
                            </div>
                            <div class="cat-right">
                                <!-- 30-day mini timeline -->
                                {#if cat.history?.length > 0}
                                    <div class="mini-tl">
                                        {#each cat.history as day}
                                            <div
                                                class="mini-seg"
                                                style="background:{passRateColor(day.pass_rate)}"
                                                title="{day.date}: {day.pass_rate}% ({day.passed}/{day.total})"
                                            ></div>
                                        {/each}
                                    </div>
                                {/if}
                                <span class="cat-rate" style="color:{passRateColor(cat.pass_rate)}">{cat.pass_rate}%</span>
                                <span class="chevron" class:open={expandedSections[`cat-${catName}`]}>&#9662;</span>
                            </div>
                        </button>

                        {#if expandedSections[`cat-${catName}`] && cat.tests?.length}
                            <div class="cat-detail">
                                {#each cat.tests as test}
                                    <div class="test-row">
                                        <span class="dot sm" style="background:{test.status === 'passed' ? '#22c55e' : test.status === 'failed' ? '#ef4444' : '#999'}"></span>
                                        <span class="test-name">{test.name}</span>
                                        <span class="test-status">{test.status}</span>
                                        <!-- Per-test 30-day history -->
                                        {#if test.history_30d?.length > 0}
                                            <div class="mini-tl sm-tl">
                                                {#each test.history_30d as day}
                                                    <div
                                                        class="mini-seg"
                                                        style="background:{day.status === 'passed' ? '#22c55e' : day.status === 'failed' ? '#ef4444' : '#999'}"
                                                        title="{day.date}: {day.status}"
                                                    ></div>
                                                {/each}
                                            </div>
                                        {/if}
                                        {#if test.last_run}
                                            <span class="test-time">{formatDate(test.last_run)}</span>
                                        {/if}
                                        {#if test.error}
                                            <div class="test-err">{test.error}</div>
                                        {/if}
                                    </div>
                                {/each}
                            </div>
                        {/if}
                    {/each}
                {/if}

                <!-- 30-day trend sparkline -->
                {#if statusData.tests.trend?.length >= 2}
                    <h3 class="sub-title">Daily Pass Rate (30 days)</h3>
                    <div class="trend-bar">
                        {#each statusData.tests.trend as day}
                            {@const rate = day.total > 0 ? Math.round(day.passed / day.total * 100) : 0}
                            <div
                                class="trend-seg"
                                style="background:{passRateColor(rate)}"
                                title="{day.date}: {rate}% ({day.passed}/{day.total})"
                            ></div>
                        {/each}
                    </div>
                    <div class="tl-range"><span>30d ago</span><span>Today</span></div>
                {/if}
            </section>
        {/if}

        <!-- Incidents -->
        {#if statusData.incidents}
            <section class="sec">
                <div class="row">
                    <span class="row-name">Incidents (30d)</span>
                    <span class="incident-count" class:has={statusData.incidents.total_last_30d > 0}>
                        {statusData.incidents.total_last_30d}
                    </span>
                </div>
            </section>
        {/if}
    {/if}

    <footer class="sp-footer">
        OpenMates &middot; <a href="/">Go to app</a>
    </footer>
</main>

<style>
    /* ─── Dark mode compatible styles ─── */
    .sp {
        max-width: 800px;
        margin: 0 auto;
        padding: 0 1rem 2rem;
        color: var(--color-font-primary, #222);
    }

    .sp-header {
        text-align: center;
        padding: 2rem 0 1rem;
    }

    .sp-header h1 {
        margin: 0 0 0.5rem;
        font-size: var(--font-size-h2, 1.5rem);
        font-weight: 700;
    }

    .badge {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.3rem 0.75rem;
        border-radius: 999px;
        font-size: 0.85rem;
        font-weight: 500;
        border: 1px solid var(--color-grey-25, #ddd);
        background: var(--color-grey-10, #f5f5f5);
    }
    .badge-dot { width: 0.45rem; height: 0.45rem; border-radius: 50%; }
    [data-status='operational'] .badge-dot { background: #22c55e; }
    [data-status='operational'] { color: #22c55e; }
    [data-status='degraded'] .badge-dot { background: #f59e0b; }
    [data-status='degraded'] { color: #f59e0b; }
    [data-status='down'] .badge-dot { background: #ef4444; }
    [data-status='down'] { color: #ef4444; }
    [data-status='unknown'] .badge-dot { background: var(--color-grey-40, #999); }

    .updated {
        margin: 0.4rem 0 0;
        font-size: 0.75rem;
        color: var(--color-font-secondary, #888);
    }

    .msg { text-align: center; padding: 2rem; color: var(--color-font-secondary, #888); }
    .err { color: var(--color-error, #e74c3c); }

    /* Sections */
    .sec {
        margin-top: 1.5rem;
        background: var(--color-grey-0, #fff);
        border: 1px solid var(--color-grey-25, #ddd);
        border-radius: 10px;
        padding: 0.75rem 1rem;
    }

    .sec-title {
        margin: 0 0 0.5rem;
        font-size: 0.95rem;
        font-weight: 600;
        color: var(--color-font-primary, #222);
    }

    .sec-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 0.5rem;
    }
    .sec-head .sec-title { margin-bottom: 0; }

    .sub-title {
        margin: 0.75rem 0 0.4rem;
        font-size: 0.82rem;
        font-weight: 600;
        color: var(--color-font-secondary, #888);
    }

    .meta {
        font-size: 0.78rem;
        color: var(--color-font-secondary, #888);
    }

    /* Rows */
    .row {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.4rem 0;
        font-size: 0.85rem;
    }
    .row + .row { border-top: 1px solid var(--color-grey-15, #eee); }
    .dot { width: 0.45rem; height: 0.45rem; border-radius: 50%; flex-shrink: 0; }
    .dot.sm { width: 0.35rem; height: 0.35rem; }
    .row-name { flex: 1; font-weight: 500; }
    .row-count { font-size: 0.78rem; color: var(--color-font-secondary, #888); font-variant-numeric: tabular-nums; }
    .row-status { font-size: 0.75rem; text-transform: capitalize; }
    .row-fail { font-size: 0.75rem; color: #ef4444; font-weight: 600; }

    /* Category rows */
    .cat-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        width: 100%;
        padding: 0.45rem 0;
        background: none;
        border: none;
        border-top: 1px solid var(--color-grey-15, #eee);
        cursor: pointer;
        font-family: inherit;
        font-size: 0.82rem;
        color: var(--color-font-primary, #222);
        text-align: left;
    }
    .cat-row:hover { background: var(--color-grey-5, #fafafa); }

    .cat-left { display: flex; align-items: center; gap: 0.4rem; }
    .cat-right { display: flex; align-items: center; gap: 0.5rem; }

    .cat-name { font-weight: 500; }
    .cat-counts { font-size: 0.75rem; color: var(--color-font-secondary, #888); font-variant-numeric: tabular-nums; }
    .cat-fail { font-size: 0.72rem; color: #ef4444; font-weight: 600; }
    .cat-rate { font-size: 0.75rem; font-weight: 600; font-variant-numeric: tabular-nums; }

    .chevron {
        font-size: 0.65rem;
        color: var(--color-font-secondary, #888);
        transition: transform 0.15s;
    }
    .chevron.open { transform: rotate(180deg); }

    /* Mini timeline (30-day colored bar) */
    .mini-tl {
        display: flex;
        gap: 1px;
        height: 0.65rem;
        border-radius: 3px;
        overflow: hidden;
        width: 90px;
    }
    .mini-tl.sm-tl { width: 60px; height: 0.5rem; }
    .mini-seg { flex: 1; min-width: 2px; }

    /* Full-width timeline */
    .timeline {
        display: flex;
        height: 1.5rem;
        border-radius: 6px;
        overflow: hidden;
        gap: 1px;
        background: var(--color-grey-20, #eee);
    }
    .tl-seg { flex: 1; min-width: 2px; cursor: default; }
    .tl-range {
        display: flex;
        justify-content: space-between;
        font-size: 0.7rem;
        color: var(--color-font-secondary, #888);
        margin-top: 0.2rem;
    }

    /* Trend bar */
    .trend-bar {
        display: flex;
        height: 1.2rem;
        border-radius: 5px;
        overflow: hidden;
        gap: 1px;
        background: var(--color-grey-20, #eee);
    }
    .trend-seg { flex: 1; min-width: 3px; cursor: default; }

    /* Expanded category detail (admin) */
    .cat-detail {
        padding: 0 0 0.5rem 1.2rem;
        border-left: 2px solid var(--color-grey-20, #eee);
        margin-left: 0.2rem;
    }

    .test-row {
        display: flex;
        align-items: center;
        gap: 0.4rem;
        padding: 0.25rem 0;
        font-size: 0.75rem;
        flex-wrap: wrap;
    }
    .test-row + .test-row { border-top: 1px solid var(--color-grey-10, #f5f5f5); }
    .test-name { flex: 1; word-break: break-word; color: var(--color-font-primary, #222); }
    .test-status { font-size: 0.7rem; color: var(--color-font-secondary, #888); text-transform: capitalize; }
    .test-time { font-size: 0.68rem; color: var(--color-font-secondary, #888); }
    .test-err {
        width: 100%;
        font-size: 0.7rem;
        color: var(--color-error, #e74c3c);
        background: rgba(239, 68, 68, 0.06);
        padding: 0.25rem 0.4rem;
        border-radius: 4px;
        margin-top: 0.1rem;
        white-space: pre-wrap;
        word-break: break-word;
        max-height: 60px;
        overflow-y: auto;
    }

    /* Incidents */
    .incident-count {
        font-size: 0.78rem;
        padding: 0.1rem 0.4rem;
        border-radius: 999px;
        background: var(--color-grey-10, #f5f5f5);
        color: var(--color-font-secondary, #888);
        font-variant-numeric: tabular-nums;
    }
    .incident-count.has {
        background: rgba(239, 68, 68, 0.1);
        color: #ef4444;
    }

    /* Footer */
    .sp-footer {
        text-align: center;
        padding: 1.5rem 0;
        font-size: 0.75rem;
        color: var(--color-font-secondary, #888);
    }
    .sp-footer a { color: var(--color-font-secondary, #888); text-decoration: underline; }
</style>
