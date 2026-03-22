<!--
    Status Page — /status
    Public page showing service health and test results.
    Loads summary-level data on mount, fetches details on section expand.
    Admin users (detected via session cookie) see error messages and failure reasons.
    Architecture: See docs/architecture/status-page.md
    Tests: N/A
-->
<script lang="ts">
    import { onMount } from 'svelte';
    import { browser } from '$app/environment';
    import { getApiEndpoint } from '@repo/ui';
    import StatusBadge from '@repo/ui/components/status/StatusBadge.svelte';
    import HealthTimeline from '@repo/ui/components/status/HealthTimeline.svelte';
    import ServiceGroupCard from '@repo/ui/components/status/ServiceGroupCard.svelte';
    import TestSuiteCard from '@repo/ui/components/status/TestSuiteCard.svelte';
    import TestTrendChart from '@repo/ui/components/status/TestTrendChart.svelte';
    import IncidentList from '@repo/ui/components/status/IncidentList.svelte';

    // --- Types ---
    type GroupSummary = {
        group_name: string;
        display_name: string;
        status: string;
        service_count: number;
        services?: any[];
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

    type TrendPoint = {
        date: string;
        total: number;
        passed: number;
        failed: number;
    };

    type TimelineBucket = {
        start: string;
        end: string;
        status: string;
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
        };
        incidents?: { total_last_30d: number };
    };

    // --- State ---
    let loading = $state(true);
    let error = $state('');
    let statusData: StatusResponse | null = $state(null);
    let isAdmin = $state(false);
    let adminChecked = false;

    // Component refs for injecting detail data
    let groupCardRefs: Record<string, ServiceGroupCard> = {};
    let suiteCardRefs: Record<string, TestSuiteCard> = {};
    let incidentListRef: IncidentList | null = $state(null);

    // --- API helpers ---
    async function fetchJson(path: string, withCredentials = false): Promise<any> {
        const url = getApiEndpoint(path);
        const opts: RequestInit = withCredentials ? { credentials: 'include' } : {};
        const res = await fetch(url, opts);
        if (!res.ok) {
            if (res.status === 403) return null;
            throw new Error(`${res.status} ${res.statusText}`);
        }
        return res.json();
    }

    async function loadSummary() {
        try {
            // Summary fetch: no credentials (public endpoint, wildcard CORS)
            const data = await fetchJson('/v1/status');
            if (data) {
                statusData = data;
                // Detect admin by trying a credentialed probe (only once)
                if (!adminChecked) {
                    adminChecked = true;
                    try {
                        const probe = await fetchJson('/v1/status?section=health&detail=full', true);
                        isAdmin = probe?.is_admin ?? false;
                    } catch {
                        isAdmin = false;
                    }
                }
            }
            error = '';
        } catch (e) {
            console.error('[STATUS] Failed to load:', e);
            error = 'Could not load status data.';
        } finally {
            loading = false;
        }
    }

    // --- Detail fetch handlers ---
    // Detail requests use credentials only when admin (so CORS works via FastAPI, not wildcard)
    async function handleGroupExpand(groupName: string) {
        try {
            const detail = isAdmin ? 'full' : 'summary';
            const data = await fetchJson(
                `/v1/status/health?group=${encodeURIComponent(groupName)}&detail=${detail}`,
                isAdmin,
            );
            if (data?.services && groupCardRefs[groupName]) {
                groupCardRefs[groupName].setDetail(data.services);
            }
        } catch (e) {
            console.error(`[STATUS] Failed to load group ${groupName}:`, e);
        }
    }

    async function handleSuiteExpand(suiteName: string) {
        try {
            const detail = isAdmin ? 'full' : 'summary';
            const data = await fetchJson(
                `/v1/status/tests?suite=${encodeURIComponent(suiteName)}&detail=${detail}`,
                isAdmin,
            );
            if (data?.suites?.[suiteName]?.tests && suiteCardRefs[suiteName]) {
                suiteCardRefs[suiteName].setDetail(data.suites[suiteName].tests);
            }
        } catch (e) {
            console.error(`[STATUS] Failed to load suite ${suiteName}:`, e);
        }
    }

    async function handleIncidentsExpand() {
        try {
            const detail = isAdmin ? 'full' : 'summary';
            const data = await fetchJson(`/v1/status/incidents?detail=${detail}`, isAdmin);
            if (data?.events && incidentListRef) {
                incidentListRef.setEvents(data.events);
            }
        } catch (e) {
            console.error('[STATUS] Failed to load incidents:', e);
        }
    }

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

<main class="status-page">
    <!-- Header -->
    <header class="status-header">
        <div class="header-content">
            <h1>OpenMates Status</h1>
            {#if statusData}
                <StatusBadge status={statusData.overall_status} />
            {/if}
            {#if statusData?.last_updated}
                <p class="last-updated">
                    Last updated: {new Date(statusData.last_updated).toLocaleTimeString()}
                </p>
            {/if}
        </div>
    </header>

    <div class="content">
        {#if loading}
            <p class="state-msg">Loading status data...</p>
        {:else if error}
            <p class="state-msg error-msg">{error}</p>
        {:else if statusData}
            <!-- Timeline -->
            {#if statusData.timeline}
                <section class="section">
                    <HealthTimeline
                        buckets={statusData.timeline.buckets}
                        periodDays={statusData.timeline.period_days}
                    />
                </section>
            {/if}

            <!-- Service Groups -->
            {#if statusData.health?.groups}
                <section class="section">
                    <h2 class="section-title">Services</h2>
                    <div class="card-grid">
                        {#each statusData.health.groups as group (group.group_name)}
                            <ServiceGroupCard
                                bind:this={groupCardRefs[group.group_name]}
                                {group}
                                {isAdmin}
                                onExpand={handleGroupExpand}
                            />
                        {/each}
                    </div>
                </section>
            {/if}

            <!-- Test Suites -->
            {#if statusData.tests}
                <section class="section">
                    <div class="section-header">
                        <h2 class="section-title">Tests</h2>
                        {#if statusData.tests.trend?.length >= 2}
                            <TestTrendChart trend={statusData.tests.trend} />
                        {/if}
                    </div>
                    {#if statusData.tests.latest_run}
                        <p class="test-summary">
                            Last run: {statusData.tests.latest_run.summary.passed ?? 0} passed,
                            {statusData.tests.latest_run.summary.failed ?? 0} failed
                            of {statusData.tests.latest_run.summary.total ?? 0} tests
                        </p>
                    {/if}
                    <div class="card-grid">
                        {#each statusData.tests.suites as suite (suite.name)}
                            <TestSuiteCard
                                bind:this={suiteCardRefs[suite.name]}
                                {suite}
                                {isAdmin}
                                onExpand={handleSuiteExpand}
                            />
                        {/each}
                    </div>
                </section>
            {/if}

            <!-- Incidents -->
            {#if statusData.incidents}
                <section class="section">
                    <IncidentList
                        bind:this={incidentListRef}
                        totalIncidents={statusData.incidents.total_last_30d}
                        {isAdmin}
                        onExpand={handleIncidentsExpand}
                    />
                </section>
            {/if}
        {/if}
    </div>

    <!-- Footer -->
    <footer class="status-footer">
        <p>OpenMates &middot; <a href="/">Go to app</a></p>
    </footer>
</main>

<style>
    .status-page {
        max-width: 800px;
        margin: 0 auto;
        padding: 0 1rem;
    }

    .status-header {
        padding: 2rem 0 1rem;
    }

    .header-content {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 0.6rem;
        text-align: center;
    }

    h1 {
        margin: 0;
        font-size: var(--font-size-h2, 1.5rem);
        font-weight: 700;
        color: var(--color-font-primary, #222);
    }

    .last-updated {
        margin: 0;
        font-size: 0.75rem;
        color: var(--color-font-secondary, #999);
    }

    .content {
        padding-bottom: 2rem;
    }

    .section {
        margin-top: 1.5rem;
    }

    .section-title {
        margin: 0 0 0.6rem;
        font-size: 1rem;
        font-weight: 600;
        color: var(--color-font-primary, #222);
    }

    .section-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 0.6rem;
    }

    .section-header .section-title {
        margin-bottom: 0;
    }

    .card-grid {
        display: grid;
        gap: 0.6rem;
    }

    .test-summary {
        margin: 0 0 0.6rem;
        font-size: 0.82rem;
        color: var(--color-font-secondary, #999);
    }

    .state-msg {
        text-align: center;
        padding: 2rem;
        font-size: 0.9rem;
        color: var(--color-font-secondary, #999);
    }

    .error-msg {
        color: var(--color-error, #e74c3c);
    }

    .status-footer {
        text-align: center;
        padding: 2rem 0;
        font-size: 0.78rem;
        color: var(--color-font-secondary, #999);
        border-top: 1px solid var(--color-grey-20, #eee);
    }

    .status-footer a {
        color: var(--color-font-secondary, #999);
        text-decoration: underline;
    }
</style>
