<!--
    Status Page — /status
    Hierarchical 30-day timelines for services and tests.
    All data visible to all users. Admin-exclusive: error messages only.
    Dark mode via CSS variables (theme.css + app.html anti-flicker).
    Architecture: See docs/architecture/status-page.md
-->
<script lang="ts">
    import { onMount } from 'svelte';
    import { browser } from '$app/environment';
    import { getApiEndpoint } from '@repo/ui';

    // --- State ---
    let loading = $state(true);
    let error = $state('');
    let data: any = $state(null);
    let exp: Record<string, boolean> = $state({});

    // --- Helpers ---
    function toggle(key: string) { exp[key] = !exp[key]; }

    function statusColor(s: string): string {
        if (s === 'operational') return '#22c55e';
        if (s === 'degraded') return '#f59e0b';
        if (s === 'down') return '#ef4444';
        return '#888';
    }

    function rateColor(rate: number): string {
        const r = Math.round(0x22 + (0xef - 0x22) * (1 - rate / 100));
        const g = Math.round(0xc5 + (0x44 - 0xc5) * (1 - rate / 100));
        const b = Math.round(0x5e + (0x44 - 0x5e) * (1 - rate / 100));
        return `rgb(${r},${g},${b})`;
    }

    function fmtDate(iso: string): string {
        try {
            const d = new Date(iso + 'T00:00:00');
            return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
        } catch { return iso; }
    }

    function fmtTime(iso: string): string {
        try { return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
        catch { return iso; }
    }

    const statusLabel: Record<string, string> = {
        operational: 'All Systems Operational',
        degraded: 'Partial Degradation',
        down: 'Major Outage',
        unknown: 'Status Unknown',
    };

    const suiteNames: Record<string, string> = {
        playwright: 'End to End Tests',
        vitest: 'Unit Tests (Frontend)',
        pytest_unit: 'Unit Tests (Backend)',
    };

    async function load() {
        try {
            const url = getApiEndpoint('/v1/status');
            const res = await fetch(url);
            if (!res.ok) throw new Error(`${res.status}`);
            data = await res.json();
            error = '';
        } catch (e) {
            console.error('[STATUS]', e);
            error = 'Could not load status data.';
        } finally {
            loading = false;
        }
    }

    onMount(() => {
        if (!browser) return;
        load();
        const t = setInterval(load, 60_000);
        return () => clearInterval(t);
    });
</script>

<svelte:head><title>OpenMates Status</title></svelte:head>

<main class="sp">
    <header class="hdr">
        <h1>OpenMates Status</h1>
        {#if data}
            <div class="badge" data-s={data.overall_status}>
                <span class="bdot"></span>
                {statusLabel[data.overall_status] ?? statusLabel.unknown}
            </div>
            <p class="upd">Updated {fmtTime(data.last_updated)}</p>
        {/if}
    </header>

    {#if loading}
        <p class="msg">Loading...</p>
    {:else if error}
        <p class="msg err">{error}</p>
    {:else if data}

        <!-- ═══ 30-Day Health Overview ═══ -->
        {#if data.overall_timeline_30d?.length}
            <section class="card">
                <h2 class="card-title">30-Day Health Overview</h2>
                <div class="tl full">
                    {#each data.overall_timeline_30d as day}
                        <div class="seg" style="background:{statusColor(day.status)}" title="{fmtDate(day.date)}: {day.status}"></div>
                    {/each}
                </div>
                <div class="tl-labels"><span>30d ago</span><span>Today</span></div>
            </section>
        {/if}

        <!-- ═══ Services ═══ -->
        {#if data.health?.groups?.length}
            <section class="card">
                <h2 class="card-title">Services</h2>
                {#each data.health.groups as g (g.group_name)}
                    <!-- Group row -->
                    <button class="row expandable" onclick={() => toggle(`g-${g.group_name}`)} aria-expanded={!!exp[`g-${g.group_name}`]}>
                        <span class="dot" style="background:{statusColor(g.status)}"></span>
                        <span class="name">{g.display_name}</span>
                        <div class="tl inline">
                            {#each g.timeline_30d as day}
                                <div class="seg" style="background:{statusColor(day.status)}" title="{fmtDate(day.date)}: {day.status}"></div>
                            {/each}
                        </div>
                        <span class="count">({g.service_count})</span>
                        <span class="status-lbl" style="color:{statusColor(g.status)}">{g.status}</span>
                        <span class="chev" class:open={exp[`g-${g.group_name}`]}>&#9662;</span>
                    </button>

                    <!-- Expanded services -->
                    {#if exp[`g-${g.group_name}`] && g.services}
                        <div class="children">
                            {#each g.services as svc}
                                <div class="row child">
                                    <span class="dot sm" style="background:{statusColor(svc.status)}"></span>
                                    <span class="name">{svc.name}</span>
                                    <div class="tl inline">
                                        {#each svc.timeline_30d as day}
                                            <div class="seg" style="background:{statusColor(day.status)}" title="{fmtDate(day.date)}: {day.status}"></div>
                                        {/each}
                                    </div>
                                    <span class="status-lbl" style="color:{statusColor(svc.status)}">{svc.status}</span>
                                </div>
                                {#if data.is_admin && svc.error_message}
                                    <div class="err-detail">{svc.error_message}</div>
                                {/if}
                            {/each}
                        </div>
                    {/if}
                {/each}
            </section>
        {/if}

        <!-- ═══ Tests ═══ -->
        {#if data.tests}
            <section class="card">
                <div class="card-head">
                    <h2 class="card-title">Tests</h2>
                    {#if data.tests.latest_run}
                        <span class="meta">{data.tests.latest_run.summary.passed ?? 0}/{data.tests.latest_run.summary.total ?? 0} passed</span>
                    {/if}
                </div>

                <!-- Suite rows -->
                {#each data.tests.suites as suite (suite.name)}
                    {@const hasCats = suite.name === 'playwright' && data.tests.categories && Object.keys(data.tests.categories).length > 0}
                    <button class="row expandable" onclick={() => toggle(`s-${suite.name}`)} aria-expanded={!!exp[`s-${suite.name}`]}>
                        <span class="dot" style="background:{suite.failed > 0 ? '#ef4444' : '#22c55e'}"></span>
                        <span class="name">{suiteNames[suite.name] ?? suite.name}</span>
                        {#if suite.timeline_30d?.length}
                            <div class="tl inline">
                                {#each suite.timeline_30d as day}
                                    {@const c = rateColor(day.pass_rate)}
                                    <div class="seg" style="background:{c}" title="{fmtDate(day.date)}: {day.pass_rate}% ({day.passed}/{day.total})"></div>
                                {/each}
                            </div>
                        {/if}
                        <span class="count">{suite.passed}/{suite.total}</span>
                        {#if suite.failed > 0}<span class="fail">{suite.failed} failed</span>{/if}
                        <span class="chev" class:open={exp[`s-${suite.name}`]}>&#9662;</span>
                    </button>

                    <!-- Expanded: show categories for playwright, flat list for others -->
                    {#if exp[`s-${suite.name}`]}
                        <div class="children">
                            {#if hasCats}
                                {#each Object.entries(data.tests.categories).sort((a, b) => a[0].localeCompare(b[0])) as [catName, cat]}
                                    <button class="row expandable child" onclick={() => toggle(`c-${catName}`)} aria-expanded={!!exp[`c-${catName}`]}>
                                        <span class="dot sm" style="background:{rateColor(cat.pass_rate)}"></span>
                                        <span class="name">{catName}</span>
                                        {#if cat.history?.length}
                                            <div class="tl inline sm">
                                                {#each cat.history as day}
                                                    <div class="seg" style="background:{rateColor(day.pass_rate)}" title="{fmtDate(day.date)}: {day.pass_rate}% ({day.passed}/{day.total})"></div>
                                                {/each}
                                            </div>
                                        {/if}
                                        <span class="count">{cat.passed}/{cat.total}</span>
                                        <span class="rate" style="color:{rateColor(cat.pass_rate)}">{cat.pass_rate}%</span>
                                        <span class="chev" class:open={exp[`c-${catName}`]}>&#9662;</span>
                                    </button>

                                    {#if exp[`c-${catName}`] && cat.tests?.length}
                                        <div class="children depth2">
                                            {#each cat.tests as test}
                                                <div class="row child leaf">
                                                    <span class="dot xs" style="background:{test.status === 'passed' ? '#22c55e' : test.status === 'failed' ? '#ef4444' : '#888'}"></span>
                                                    <span class="name mono">{test.name}</span>
                                                    {#if test.history_30d?.length}
                                                        <div class="tl inline xs">
                                                            {#each test.history_30d as day}
                                                                <div class="seg" style="background:{day.status === 'passed' ? '#22c55e' : day.status === 'failed' ? '#ef4444' : '#888'}" title="{fmtDate(day.date)}: {day.status}"></div>
                                                            {/each}
                                                        </div>
                                                    {/if}
                                                    <span class="test-status" style="color:{test.status === 'passed' ? '#22c55e' : test.status === 'failed' ? '#ef4444' : '#888'}">{test.status}</span>
                                                    {#if test.last_run}
                                                        <span class="test-date">{fmtDate(test.last_run.slice(0, 10))}</span>
                                                    {/if}
                                                </div>
                                                {#if data.is_admin && test.error}
                                                    <div class="err-detail">{test.error}</div>
                                                {/if}
                                            {/each}
                                        </div>
                                    {/if}
                                {/each}
                            {:else}
                                <p class="meta" style="padding:0.4rem 0">No detailed breakdown available for this suite.</p>
                            {/if}
                        </div>
                    {/if}
                {/each}

                <!-- Daily trend bar -->
                {#if data.tests.trend?.length >= 2}
                    <h3 class="sub-title">Daily Pass Rate (30 days)</h3>
                    <div class="tl full short">
                        {#each data.tests.trend as day}
                            {@const rate = day.total > 0 ? Math.round(day.passed / day.total * 100) : 0}
                            <div class="seg" style="background:{rateColor(rate)}" title="{fmtDate(day.date)}: {rate}% ({day.passed}/{day.total})"></div>
                        {/each}
                    </div>
                    <div class="tl-labels"><span>30d ago</span><span>Today</span></div>
                {/if}
            </section>
        {/if}

        <!-- ═══ Incidents ═══ -->
        {#if data.incidents}
            <section class="card">
                <div class="row">
                    <span class="name">Incidents (30d)</span>
                    <span class="incident-badge" class:has={data.incidents.total_last_30d > 0}>{data.incidents.total_last_30d}</span>
                </div>
            </section>
        {/if}
    {/if}

    <footer class="ftr">OpenMates &middot; <a href="/">Go to app</a></footer>
</main>

<style>
    .sp { max-width: 860px; margin: 0 auto; padding: 0 1rem 2rem; color: var(--color-font-primary); }

    /* Header */
    .hdr { text-align: center; padding: 2rem 0 0.5rem; }
    .hdr h1 { margin: 0 0 0.5rem; font-size: var(--font-size-h2, 1.5rem); font-weight: 700; }
    .badge { display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.3rem 0.75rem; border-radius: 999px; font-size: 0.85rem; font-weight: 500; border: 1px solid var(--color-grey-25); background: var(--color-grey-10); }
    .bdot { width: 0.45rem; height: 0.45rem; border-radius: 50%; }
    [data-s='operational'] .bdot { background: #22c55e; } [data-s='operational'] { color: #22c55e; }
    [data-s='degraded'] .bdot { background: #f59e0b; } [data-s='degraded'] { color: #f59e0b; }
    [data-s='down'] .bdot { background: #ef4444; } [data-s='down'] { color: #ef4444; }
    [data-s='unknown'] .bdot { background: #888; }
    .upd { margin: 0.4rem 0 0; font-size: 0.75rem; color: var(--color-font-secondary); }
    .msg { text-align: center; padding: 2rem; color: var(--color-font-secondary); }
    .err { color: var(--color-error); }

    /* Cards */
    .card { margin-top: 1rem; background: var(--color-grey-0); border: 1px solid var(--color-grey-25); border-radius: 10px; padding: 0.75rem 1rem; }
    .card-title { margin: 0 0 0.5rem; font-size: 0.95rem; font-weight: 600; }
    .card-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.5rem; }
    .card-head .card-title { margin-bottom: 0; }
    .sub-title { margin: 0.75rem 0 0.4rem; font-size: 0.82rem; font-weight: 600; color: var(--color-font-secondary); }
    .meta { font-size: 0.78rem; color: var(--color-font-secondary); }

    /* Rows */
    .row { display: flex; align-items: center; gap: 0.5rem; padding: 0.4rem 0; font-size: 0.85rem; width: 100%; }
    .row + .row { border-top: 1px solid var(--color-grey-15); }
    .row.expandable { background: none; border: none; border-top: 1px solid var(--color-grey-15); cursor: pointer; font-family: inherit; color: var(--color-font-primary); text-align: left; }
    .row.expandable:first-child { border-top: none; }
    .row.expandable:hover { background: var(--color-grey-5); }
    .row.child { padding-left: 1rem; font-size: 0.82rem; }
    .row.leaf { padding-left: 0.5rem; font-size: 0.78rem; }

    .dot { width: 0.45rem; height: 0.45rem; border-radius: 50%; flex-shrink: 0; }
    .dot.sm { width: 0.38rem; height: 0.38rem; }
    .dot.xs { width: 0.3rem; height: 0.3rem; }
    .name { flex: 1; font-weight: 500; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .name.mono { font-family: monospace; font-size: 0.75rem; font-weight: 400; }
    .count { font-size: 0.75rem; color: var(--color-font-secondary); font-variant-numeric: tabular-nums; flex-shrink: 0; }
    .status-lbl { font-size: 0.72rem; text-transform: capitalize; flex-shrink: 0; }
    .fail { font-size: 0.72rem; color: #ef4444; font-weight: 600; flex-shrink: 0; }
    .rate { font-size: 0.72rem; font-weight: 600; font-variant-numeric: tabular-nums; flex-shrink: 0; }
    .test-status { font-size: 0.7rem; text-transform: capitalize; flex-shrink: 0; }
    .test-date { font-size: 0.68rem; color: var(--color-font-secondary); flex-shrink: 0; }

    .chev { font-size: 0.65rem; color: var(--color-font-secondary); transition: transform 0.15s; flex-shrink: 0; }
    .chev.open { transform: rotate(180deg); }

    /* Children (expanded) */
    .children { padding-left: 0.75rem; border-left: 2px solid var(--color-grey-20); margin-left: 0.2rem; }
    .children .row:first-child { border-top: none; }
    .depth2 { padding-left: 0.5rem; }

    /* Timeline bars */
    .tl { display: flex; gap: 1px; border-radius: 4px; overflow: hidden; background: var(--color-grey-20); }
    .tl.full { height: 1.5rem; }
    .tl.full.short { height: 1rem; }
    .tl.inline { height: 0.6rem; width: 120px; flex-shrink: 0; }
    .tl.inline.sm { width: 80px; height: 0.5rem; }
    .tl.inline.xs { width: 50px; height: 0.4rem; }
    .seg { flex: 1; min-width: 2px; }
    .tl-labels { display: flex; justify-content: space-between; font-size: 0.68rem; color: var(--color-font-secondary); margin-top: 0.15rem; }

    /* Error detail (admin only) */
    .err-detail { font-size: 0.7rem; color: var(--color-error); background: rgba(239, 68, 68, 0.06); padding: 0.2rem 0.5rem; border-radius: 4px; margin: 0.1rem 0 0.2rem 1.5rem; white-space: pre-wrap; word-break: break-word; max-height: 60px; overflow-y: auto; }

    /* Incidents */
    .incident-badge { font-size: 0.78rem; padding: 0.1rem 0.4rem; border-radius: 999px; background: var(--color-grey-10); color: var(--color-font-secondary); font-variant-numeric: tabular-nums; }
    .incident-badge.has { background: rgba(239, 68, 68, 0.1); color: #ef4444; }

    /* Footer */
    .ftr { text-align: center; padding: 1.5rem 0; font-size: 0.75rem; color: var(--color-font-secondary); }
    .ftr a { color: var(--color-font-secondary); text-decoration: underline; }
</style>
