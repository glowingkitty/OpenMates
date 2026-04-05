<!--
    Settings Server Statistics Component

    Displays global server statistics for admins using a modern dashboard layout.
    Shows key metrics in cards and time-series data in interactive charts.

    Layout principles:
    - 2×2 metric cards grid (no overflow on any screen width)
    - Single unified chart for daily/monthly/web traffic (tabs switch metric + source)
    - Full-width ranked lists (countries, devices, browsers, session duration, referrers)
    - Analytics sections always visible with empty-state placeholder when no data yet
    - Today's summary as compact label: value rows (no grid overflow)
-->
<script lang="ts">
    import { onMount } from 'svelte';
    import { getApiEndpoint, text } from '@repo/ui';
    import { fade } from 'svelte/transition';
    import { SettingsSectionHeading } from '../../settings/elements';

    // ============================================================================
    // TYPE DEFINITIONS
    // ============================================================================

    interface StatsRecord {
        id: string;
        date?: string;
        year_month?: string;
        new_users_registered: number;
        new_users_finished_signup: number;
        income_eur_cents: number;
        credits_sold: number;
        credits_used: number;
        messages_sent: number;
        chats_created: number;
        embeds_created?: number;
        liability_total: number;
        active_subscriptions: number;
        total_regular_users: number;
        created_at: string;
        updated_at: string;
    }

    interface ChartDataPoint {
        date: string;
        value: number;
        label: string;
    }

    interface WebAnalyticsDailyRecord {
        id: string;
        date: string;
        page_loads: number;
        unique_visits_approx: number;
        countries?: Record<string, number>;
        devices?: Record<string, number>;
        browsers?: Record<string, number>;
        os_families?: Record<string, number>;
        referrer_domains?: Record<string, number>;
        screen_classes?: Record<string, number>;
        session_duration_buckets?: Record<string, number>;
    }

    interface SignupFunnelDailyRecord {
        id: string;
        date: string;
        started_basics: number;
        email_confirmed: number;
        auth_password_setup: number;
        auth_passkey_setup: number;
        recovery_key_saved: number;
        reached_payment: number;
        payment_completed: number;
        payment_completed_eu: number;
        payment_completed_non_eu: number;
        auto_topup_setup: number;
    }

    interface AppAnalyticsDailyRecord {
        id: string;
        date: string;
        app_id?: string;
        skill_id?: string;
        model_used?: string;
        focus_mode_id?: string;
        settings_memory_type?: string;
        count: number;
    }

    interface RankedItem {
        key: string;
        value: number;
    }

    // ============================================================================
    // STATE
    // ============================================================================

    let isLoading = $state(true);
    let error = $state<string | null>(null);
    let dailyHistory = $state<StatsRecord[]>([]);
    let monthlyHistory = $state<StatsRecord[]>([]);
    let currentStats = $state<Partial<StatsRecord>>({});
    let newsletterSubscribersCount = $state(0);

    let webAnalyticsDaily = $state<WebAnalyticsDailyRecord[]>([]);
    let signupFunnelDaily = $state<SignupFunnelDailyRecord[]>([]);
    let appAnalyticsDaily = $state<AppAnalyticsDailyRecord[]>([]);

    // Unified chart: which metric/source is active
    // daily-* sources → dailyHistory line chart
    // monthly-* sources → monthlyHistory bar chart
    // traffic-* sources → webAnalyticsDaily line chart
    type ChartTab =
        | 'daily-messages' | 'daily-credits' | 'daily-income' | 'daily-users'
        | 'monthly-income' | 'monthly-credits' | 'monthly-messages'
        | 'traffic-loads' | 'traffic-uniques';
    let activeTab = $state<ChartTab>('daily-messages');

    // Hover state for unified chart
    let hoveredPoint = $state<ChartDataPoint | null>(null);
    let tooltipX = $state(0);
    let tooltipY = $state(0);

    // ============================================================================
    // DATA LOADING
    // ============================================================================

    async function loadStats() {
        try {
            isLoading = true;
            error = null;

            const response = await fetch(getApiEndpoint('/v1/admin/server-stats'), {
                credentials: 'include'
            });

            if (!response.ok) {
                error = response.status === 403
                    ? 'Admin privileges required to view server statistics.'
                    : 'Failed to load server statistics.';
                return;
            }

            const data = await response.json();
            currentStats = data.current || {};
            newsletterSubscribersCount = data.newsletter_subscribers_count || 0;

            const minYear = 2020;
            dailyHistory = (data.daily_history || []).filter((r: StatsRecord) => {
                const y = parseInt((r.date || '').substring(0, 4));
                return !isNaN(y) && y >= minYear;
            });
            monthlyHistory = (data.monthly_history || []).filter((r: StatsRecord) => {
                const y = parseInt((r.year_month || '').substring(0, 4));
                return !isNaN(y) && y >= minYear;
            });
            webAnalyticsDaily = (data.web_analytics_daily || []).filter((r: WebAnalyticsDailyRecord) => {
                const y = parseInt((r.date || '').substring(0, 4));
                return !isNaN(y) && y >= minYear;
            });
            signupFunnelDaily = (data.signup_funnel_daily || []).filter((r: SignupFunnelDailyRecord) => {
                const y = parseInt((r.date || '').substring(0, 4));
                return !isNaN(y) && y >= minYear;
            });
            appAnalyticsDaily = (data.app_analytics_daily || []).filter((r: AppAnalyticsDailyRecord) => {
                const y = parseInt((r.date || '').substring(0, 4));
                return !isNaN(y) && y >= minYear;
            });

        } catch (err) {
            console.error('Error loading stats:', err);
            error = 'Failed to connect to server.';
        } finally {
            isLoading = false;
        }
    }

    // ============================================================================
    // FORMATTING
    // ============================================================================

    function formatCurrency(cents: number = 0): string {
        return (cents / 100).toLocaleString('en-US', { style: 'currency', currency: 'EUR' });
    }

    function formatLiabilityInEur(credits: number = 0): string {
        return (credits / 1000).toLocaleString('en-US', {
            style: 'currency', currency: 'EUR',
            minimumFractionDigits: 2, maximumFractionDigits: 2
        });
    }

    function formatNumber(num: number = 0): string {
        return num.toLocaleString('en-US');
    }

    function formatDateShort(dateStr: string): string {
        if (!dateStr) return '';
        try {
            return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        } catch { return dateStr; }
    }

    function formatDateFull(dateStr: string): string {
        if (!dateStr) return '';
        try {
            return new Date(dateStr).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
        } catch { return dateStr; }
    }

    function formatMonth(monthStr: string): string {
        if (!monthStr) return '';
        try {
            const [year, month] = monthStr.split('-');
            return new Date(parseInt(year), parseInt(month) - 1).toLocaleDateString('en-US', { year: 'numeric', month: 'short' });
        } catch { return monthStr; }
    }

    function formatMonthShort(monthStr: string): string {
        if (!monthStr) return '';
        try {
            const [year, month] = monthStr.split('-');
            return new Date(parseInt(year), parseInt(month) - 1).toLocaleDateString('en-US', { month: 'short' });
        } catch { return monthStr; }
    }

    // ============================================================================
    // UNIFIED CHART DATA
    // ============================================================================

    /**
     * Build chart data for the currently active tab.
     * Returns { points, isBar, formatX } so the template can render either
     * a line chart (daily/traffic) or a bar chart (monthly).
     */
    function getActiveChartData(): ChartDataPoint[] {
        switch (activeTab) {
            case 'daily-messages': {
                const s = [...dailyHistory].sort((a, b) => (a.date||'').localeCompare(b.date||''));
                return s.map(d => ({ date: d.date||'', value: d.messages_sent||0, label: `${formatNumber(d.messages_sent||0)} messages` }));
            }
            case 'daily-credits': {
                const s = [...dailyHistory].sort((a, b) => (a.date||'').localeCompare(b.date||''));
                return s.map(d => ({ date: d.date||'', value: d.credits_used||0, label: `${formatNumber(d.credits_used||0)} credits` }));
            }
            case 'daily-income': {
                const s = [...dailyHistory].sort((a, b) => (a.date||'').localeCompare(b.date||''));
                return s.map(d => ({ date: d.date||'', value: d.income_eur_cents||0, label: formatCurrency(d.income_eur_cents||0) }));
            }
            case 'daily-users': {
                const s = [...dailyHistory].sort((a, b) => (a.date||'').localeCompare(b.date||''));
                return s.map(d => ({ date: d.date||'', value: d.new_users_registered||0, label: `${formatNumber(d.new_users_registered||0)} new users` }));
            }
            case 'monthly-income': {
                const s = [...monthlyHistory].sort((a, b) => (a.year_month||'').localeCompare(b.year_month||''));
                return s.map(d => ({ date: d.year_month||'', value: d.income_eur_cents||0, label: formatCurrency(d.income_eur_cents||0) }));
            }
            case 'monthly-credits': {
                const s = [...monthlyHistory].sort((a, b) => (a.year_month||'').localeCompare(b.year_month||''));
                return s.map(d => ({ date: d.year_month||'', value: d.credits_used||0, label: `${formatNumber(d.credits_used||0)} credits` }));
            }
            case 'monthly-messages': {
                const s = [...monthlyHistory].sort((a, b) => (a.year_month||'').localeCompare(b.year_month||''));
                return s.map(d => ({ date: d.year_month||'', value: d.messages_sent||0, label: `${formatNumber(d.messages_sent||0)} messages` }));
            }
            case 'traffic-loads': {
                const s = [...webAnalyticsDaily].sort((a, b) => (a.date||'').localeCompare(b.date||''));
                return s.map(d => ({ date: d.date||'', value: d.page_loads||0, label: `${formatNumber(d.page_loads||0)} page loads` }));
            }
            case 'traffic-uniques': {
                const s = [...webAnalyticsDaily].sort((a, b) => (a.date||'').localeCompare(b.date||''));
                return s.map(d => ({ date: d.date||'', value: d.unique_visits_approx||0, label: `~${formatNumber(d.unique_visits_approx||0)} unique visits` }));
            }
        }
    }

    /** Whether the active tab should render bars (monthly) vs line (daily/traffic) */
    const isBarChart = $derived(activeTab.startsWith('monthly-'));

    /** X-axis label formatter depending on tab source */
    function formatXLabel(dateStr: string): string {
        return activeTab.startsWith('monthly-') ? formatMonthShort(dateStr) : formatDateShort(dateStr);
    }

    /** Full date label for tooltip */
    function formatXFull(dateStr: string): string {
        return activeTab.startsWith('monthly-') ? formatMonth(dateStr) : formatDateFull(dateStr);
    }

    const chartData = $derived(getActiveChartData());

    function getMaxValue(data: ChartDataPoint[]): number {
        if (data.length === 0) return 100;
        return Math.max(Math.max(...data.map(d => d.value)) * 1.1, 10);
    }

    function generateAreaPath(data: ChartDataPoint[], w: number, h: number): string {
        if (data.length === 0) return '';
        const max = getMaxValue(data);
        const px = 40, chartW = w - px * 2, chartH = h - px * 2;
        const pts = data.map((d, i) => ({
            x: px + (i / Math.max(data.length - 1, 1)) * chartW,
            y: px + chartH - (d.value / max) * chartH
        }));
        let line = `M ${pts[0].x} ${pts[0].y}`;
        for (let i = 1; i < pts.length; i++) line += ` L ${pts[i].x} ${pts[i].y}`;
        return `${line} L ${pts[pts.length - 1].x} ${px + chartH} L ${pts[0].x} ${px + chartH} Z`;
    }

    function generateLinePath(data: ChartDataPoint[], w: number, h: number): string {
        if (data.length === 0) return '';
        const max = getMaxValue(data);
        const px = 40, chartW = w - px * 2, chartH = h - px * 2;
        const pts = data.map((d, i) => ({
            x: px + (i / Math.max(data.length - 1, 1)) * chartW,
            y: px + chartH - (d.value / max) * chartH
        }));
        let path = `M ${pts[0].x} ${pts[0].y}`;
        for (let i = 1; i < pts.length; i++) path += ` L ${pts[i].x} ${pts[i].y}`;
        return path;
    }

    function getDataPoints(data: ChartDataPoint[], w: number, h: number) {
        if (data.length === 0) return [];
        const max = getMaxValue(data);
        const px = 40, chartW = w - px * 2, chartH = h - px * 2;
        return data.map((d, i) => ({
            x: px + (i / Math.max(data.length - 1, 1)) * chartW,
            y: px + chartH - (d.value / max) * chartH,
            point: d
        }));
    }

    function handleChartMouseMove(event: MouseEvent) {
        const target = event.currentTarget as SVGElement;
        const rect = target.getBoundingClientRect();
        const mouseX = event.clientX - rect.left;
        const pts = getDataPoints(chartData, rect.width, rect.height);
        let closest: typeof pts[0] | null = null;
        let minDist = Infinity;
        for (const p of pts) {
            const d = Math.abs(p.x - mouseX);
            if (d < minDist) { minDist = d; closest = p; }
        }
        if (closest && minDist < 30) {
            hoveredPoint = closest.point;
            tooltipX = closest.x;
            tooltipY = closest.y;
        } else {
            hoveredPoint = null;
        }
    }

    // ============================================================================
    // ANALYTICS HELPERS
    // ============================================================================

    function aggregateDistribution(field: keyof WebAnalyticsDailyRecord, topN = 8): RankedItem[] {
        const totals: Record<string, number> = {};
        for (const day of webAnalyticsDaily) {
            const dist = day[field] as Record<string, number> | undefined;
            if (!dist) continue;
            for (const [k, v] of Object.entries(dist)) totals[k] = (totals[k] || 0) + v;
        }
        return Object.entries(totals)
            .map(([key, value]) => ({ key, value }))
            .sort((a, b) => b.value - a.value)
            .slice(0, topN);
    }

    function getSessionDurationData(): RankedItem[] {
        const ORDER = ['<30s', '30s-2m', '2m-5m', '5m-15m', '15m-30m', '30m-1h', '1h+'];
        const totals: Record<string, number> = {};
        for (const day of webAnalyticsDaily) {
            if (!day.session_duration_buckets) continue;
            for (const [k, v] of Object.entries(day.session_duration_buckets))
                totals[k] = (totals[k] || 0) + v;
        }
        return ORDER.map(k => ({ key: k, value: totals[k] || 0 })).filter(i => i.value > 0);
    }

    function getSignupFunnelData(): Array<{ key: string; label: string; value: number }> {
        const steps = [
            { key: 'started_basics',     label: $text('settings.server_stats.funnel_started') },
            { key: 'email_confirmed',    label: $text('settings.server_stats.funnel_email_confirmed') },
            { key: 'auth_password_setup',label: $text('settings.server_stats.funnel_password_setup') },
            { key: 'auth_passkey_setup', label: $text('settings.server_stats.funnel_passkey_setup') },
            { key: 'recovery_key_saved', label: $text('settings.server_stats.funnel_recovery_saved') },
            { key: 'reached_payment',    label: $text('settings.server_stats.funnel_reached_payment') },
            { key: 'payment_completed',  label: $text('settings.server_stats.funnel_payment_completed') },
            { key: 'auto_topup_setup',   label: $text('settings.server_stats.funnel_auto_topup') },
        ] as const;
        const totals: Record<string, number> = {};
        for (const day of signupFunnelDaily)
            for (const s of steps)
                totals[s.key] = (totals[s.key] || 0) + ((day as unknown as Record<string, number>)[s.key] || 0);
        return steps.map(s => ({ key: s.key, label: s.label, value: totals[s.key] || 0 }));
    }

    function getAppUsageData(): RankedItem[] {
        const totals: Record<string, number> = {};
        for (const row of appAnalyticsDaily) {
            const k = row.app_id || 'unknown';
            totals[k] = (totals[k] || 0) + (row.count || 0);
        }
        return Object.entries(totals)
            .map(([key, value]) => ({ key, value }))
            .sort((a, b) => b.value - a.value)
            .slice(0, 10);
    }

    // ============================================================================
    // DERIVED
    // ============================================================================

    const topCountries = $derived(aggregateDistribution('countries', 8));
    const topBrowsers = $derived(aggregateDistribution('browsers', 8));
    const topReferrers = $derived(aggregateDistribution('referrer_domains', 8));
    const deviceData = $derived(aggregateDistribution('devices', 5));
    const sessionDurationData = $derived(getSessionDurationData());
    const signupFunnelData = $derived(getSignupFunnelData());
    const appUsageData = $derived(getAppUsageData());

    // ============================================================================
    // LIFECYCLE
    // ============================================================================

    onMount(() => { loadStats(); });
</script>

<div class="server-stats" in:fade={{ duration: 300 }}>
    <SettingsSectionHeading
        title={$text('settings.server_stats.title')}
        icon="usage"
    />

    {#if isLoading}
        <div class="loading">
            <div class="spinner"></div>
            <p>{$text('settings.server_stats.loading')}</p>
        </div>
    {:else if error}
        <div class="error">
            <div class="error-icon">⚠️</div>
            <p>{error}</p>
            <button onclick={loadStats} class="btn btn-primary">{$text('settings.server_stats.try_again')}</button>
        </div>
    {:else}

        <!-- ================================================================
             KEY METRICS — 2×2 grid, never overflows
             ================================================================ -->
        <div class="metrics-grid">
            <div class="metric-card">
                <span class="metric-label">{$text('settings.server_stats.total_users')}</span>
                <span class="metric-value">{formatNumber(currentStats.total_regular_users || 0)}</span>
            </div>
            <div class="metric-card">
                <span class="metric-label">{$text('settings.server_stats.active_subscriptions')}</span>
                <span class="metric-value">{formatNumber(currentStats.active_subscriptions || 0)}</span>
            </div>
            <div class="metric-card">
                <span class="metric-label">{$text('settings.server_stats.total_liability')}</span>
                <span class="metric-value">{formatLiabilityInEur(currentStats.liability_total || 0)}</span>
            </div>
            <div class="metric-card">
                <span class="metric-label">{$text('settings.server_stats.newsletter_subscribers')}</span>
                <span class="metric-value">{formatNumber(newsletterSubscribersCount)}</span>
            </div>
        </div>

        <!-- ================================================================
             TODAY'S SUMMARY — compact label: value rows
             ================================================================ -->
        <div class="today-summary">
            <h3>
                {#if currentStats.date}
                    {$text('settings.server_stats.latest_activity', { date: formatDateFull(currentStats.date) })}
                {:else}
                    {$text('settings.server_stats.latest_activity', { date: 'Today' })}
                {/if}
            </h3>
            <div class="summary-rows">
                <div class="summary-row">
                    <span class="summary-label">{$text('settings.server_stats.new_registrations')}</span>
                    <span class="summary-value">{formatNumber(currentStats.new_users_registered || 0)}</span>
                </div>
                <div class="summary-row">
                    <span class="summary-label">{$text('settings.server_stats.finished_signup')}</span>
                    <span class="summary-value">{formatNumber(currentStats.new_users_finished_signup || 0)}</span>
                </div>
                <div class="summary-row">
                    <span class="summary-label">{$text('settings.server_stats.income')}</span>
                    <span class="summary-value">{formatCurrency(currentStats.income_eur_cents)}</span>
                </div>
                <div class="summary-row">
                    <span class="summary-label">{$text('settings.server_stats.credits_sold')}</span>
                    <span class="summary-value">{formatNumber(currentStats.credits_sold || 0)}</span>
                </div>
                <div class="summary-row">
                    <span class="summary-label">{$text('settings.server_stats.credits_used')}</span>
                    <span class="summary-value">{formatNumber(currentStats.credits_used || 0)}</span>
                </div>
                <div class="summary-row">
                    <span class="summary-label">{$text('settings.server_stats.messages_sent')}</span>
                    <span class="summary-value">{formatNumber(currentStats.messages_sent || 0)}</span>
                </div>
            </div>
        </div>

        <!-- ================================================================
             UNIFIED CHART — tabs switch between daily / monthly / traffic
             ================================================================ -->
        <div class="chart-section">
            <div class="chart-header">
                <h3>{$text('settings.server_stats.daily_history')}</h3>
            </div>

            <!-- Tab groups: Daily | Monthly | Traffic -->
            <div class="tab-groups">
                <div class="tab-group">
                    <span class="tab-group-label">Daily</span>
                    <div class="tabs">
                        <button class="tab" class:active={activeTab === 'daily-messages'} onclick={() => activeTab = 'daily-messages'}>
                            {$text('settings.server_stats.messages')}
                        </button>
                        <button class="tab" class:active={activeTab === 'daily-credits'} onclick={() => activeTab = 'daily-credits'}>
                            {$text('settings.server_stats.credits_used')}
                        </button>
                        <button class="tab" class:active={activeTab === 'daily-income'} onclick={() => activeTab = 'daily-income'}>
                            {$text('settings.server_stats.income')}
                        </button>
                        <button class="tab" class:active={activeTab === 'daily-users'} onclick={() => activeTab = 'daily-users'}>
                            {$text('settings.server_stats.new_users')}
                        </button>
                    </div>
                </div>
                <div class="tab-group">
                    <span class="tab-group-label">Monthly</span>
                    <div class="tabs">
                        <button class="tab" class:active={activeTab === 'monthly-income'} onclick={() => activeTab = 'monthly-income'}>
                            {$text('settings.server_stats.income')}
                        </button>
                        <button class="tab" class:active={activeTab === 'monthly-credits'} onclick={() => activeTab = 'monthly-credits'}>
                            {$text('settings.server_stats.credits_used')}
                        </button>
                        <button class="tab" class:active={activeTab === 'monthly-messages'} onclick={() => activeTab = 'monthly-messages'}>
                            {$text('settings.server_stats.messages')}
                        </button>
                    </div>
                </div>
                <div class="tab-group">
                    <span class="tab-group-label">{$text('settings.server_stats.web_traffic')}</span>
                    <div class="tabs">
                        <button class="tab" class:active={activeTab === 'traffic-loads'} onclick={() => activeTab = 'traffic-loads'}>
                            {$text('settings.server_stats.page_loads')}
                        </button>
                        <button class="tab" class:active={activeTab === 'traffic-uniques'} onclick={() => activeTab = 'traffic-uniques'}>
                            {$text('settings.server_stats.unique_visits')}
                        </button>
                    </div>
                </div>
            </div>

            {#if chartData.length === 0}
                <p class="no-data-chart">{$text('settings.server_stats.no_data')}</p>
            {:else}
                <div class="chart-container">
                    <svg
                        class="chart"
                        viewBox="0 0 700 200"
                        role="img"
                        onmousemove={handleChartMouseMove}
                        onmouseleave={() => { hoveredPoint = null; }}
                    >
                        <defs>
                            <linearGradient id="chartGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                                <stop offset="0%" stop-color="var(--color-primary)" stop-opacity="0.35"/>
                                <stop offset="100%" stop-color="var(--color-primary)" stop-opacity="0"/>
                            </linearGradient>
                        </defs>

                        <!-- Grid lines -->
                        {#each [0.25, 0.5, 0.75, 1] as ratio}
                            <line
                                x1="40" y1={40 + 120 * (1 - ratio)}
                                x2="660" y2={40 + 120 * (1 - ratio)}
                                stroke="var(--color-border)" stroke-dasharray="4 4" opacity="0.5"
                            />
                        {/each}

                        {#if isBarChart}
                            <!-- Bar chart for monthly data -->
                            {#each chartData as point, i}
                                {@const maxVal = getMaxValue(chartData)}
                                {@const bw = Math.max(620 / chartData.length - 6, 16)}
                                {@const bh = Math.max((point.value / maxVal) * 120, 2)}
                                {@const bx = chartData.length === 1
                                    ? 350 - bw / 2
                                    : 40 + (i / Math.max(chartData.length - 1, 1)) * 620 - bw / 2}
                                {@const by = 160 - bh}
                                <rect
                                    x={bx} y={by} width={bw} height={bh}
                                    fill={hoveredPoint?.date === point.date
                                        ? 'var(--color-primary)'
                                        : 'var(--color-primary-muted, rgba(99,102,241,0.65))'}
                                    rx="3" class="bar"
                                />
                                <!-- svelte-ignore component_name_lowercase -->
                                <text
                                    x={chartData.length === 1 ? 350 : 40 + (i / Math.max(chartData.length - 1, 1)) * 620}
                                    y="182" text-anchor="middle"
                                    fill="var(--color-text-tertiary)" font-size="10"
                                >
                                    {formatXLabel(point.date)}
                                </text>
                            {/each}
                        {:else}
                            <!-- Line / area chart for daily and traffic data -->
                            <path d={generateAreaPath(chartData, 700, 200)} fill="url(#chartGradient)" opacity="1" />
                            <path
                                d={generateLinePath(chartData, 700, 200)}
                                fill="none" stroke="var(--color-primary)" stroke-width="2"
                                stroke-linecap="round" stroke-linejoin="round"
                            />
                            {#each getDataPoints(chartData, 700, 200) as { x, y, point }}
                                <circle
                                    cx={x} cy={y}
                                    r={hoveredPoint?.date === point.date ? 5 : 3}
                                    fill="var(--color-primary)" class="data-point"
                                />
                            {/each}
                            <!-- X-axis labels: every 5th + last -->
                            <!-- svelte-ignore component_name_lowercase -->
                            {#each chartData as point, i}
                                {#if i % 5 === 0 || i === chartData.length - 1}
                                    <text
                                        x={40 + (i / Math.max(chartData.length - 1, 1)) * 620}
                                        y="193" text-anchor="middle"
                                        fill="var(--color-text-tertiary)" font-size="10"
                                    >
                                        {formatXLabel(point.date)}
                                    </text>
                                {/if}
                            {/each}
                        {/if}
                    </svg>

                    {#if hoveredPoint}
                        <div
                            class="chart-tooltip"
                            style="left: {tooltipX}px; top: {Math.max(tooltipY - 52, 4)}px;"
                            in:fade={{ duration: 80 }}
                        >
                            <div class="tooltip-date">{formatXFull(hoveredPoint.date)}</div>
                            <div class="tooltip-value">{hoveredPoint.label}</div>
                        </div>
                    {/if}
                </div>
            {/if}
        </div>

        <!-- ================================================================
             WEB ANALYTICS RANKED LISTS — always visible, full-width
             ================================================================ -->

        <!-- Top Countries -->
        <div class="chart-section">
            <div class="chart-header">
                <h3>{$text('settings.server_stats.top_countries')}</h3>
            </div>
            {#if topCountries.length === 0}
                <p class="no-data">{$text('settings.server_stats.no_data')}</p>
            {:else}
                <div class="ranked-list">
                    {#each topCountries as item}
                        {@const total = topCountries.reduce((s, i) => s + i.value, 0)}
                        {@const pct = total > 0 ? Math.round((item.value / total) * 100) : 0}
                        <div class="ranked-item">
                            <span class="ranked-key">{item.key}</span>
                            <div class="ranked-bar-wrap">
                                <div class="ranked-bar" style="width: {pct}%"></div>
                            </div>
                            <span class="ranked-pct">{pct}%</span>
                            <span class="ranked-value">{formatNumber(item.value)}</span>
                        </div>
                    {/each}
                </div>
            {/if}
        </div>

        <!-- Devices -->
        <div class="chart-section">
            <div class="chart-header">
                <h3>{$text('common.devices')}</h3>
            </div>
            {#if deviceData.length === 0}
                <p class="no-data">{$text('settings.server_stats.no_data')}</p>
            {:else}
                <div class="ranked-list">
                    {#each deviceData as item}
                        {@const total = deviceData.reduce((s, i) => s + i.value, 0)}
                        {@const pct = total > 0 ? Math.round((item.value / total) * 100) : 0}
                        <div class="ranked-item">
                            <span class="ranked-key">{item.key}</span>
                            <div class="ranked-bar-wrap">
                                <div class="ranked-bar" style="width: {pct}%"></div>
                            </div>
                            <span class="ranked-pct">{pct}%</span>
                            <span class="ranked-value">{formatNumber(item.value)}</span>
                        </div>
                    {/each}
                </div>
            {/if}
        </div>

        <!-- Top Browsers -->
        <div class="chart-section">
            <div class="chart-header">
                <h3>{$text('settings.server_stats.top_browsers')}</h3>
            </div>
            {#if topBrowsers.length === 0}
                <p class="no-data">{$text('settings.server_stats.no_data')}</p>
            {:else}
                <div class="ranked-list">
                    {#each topBrowsers as item}
                        {@const total = topBrowsers.reduce((s, i) => s + i.value, 0)}
                        {@const pct = total > 0 ? Math.round((item.value / total) * 100) : 0}
                        <div class="ranked-item">
                            <span class="ranked-key">{item.key}</span>
                            <div class="ranked-bar-wrap">
                                <div class="ranked-bar" style="width: {pct}%"></div>
                            </div>
                            <span class="ranked-pct">{pct}%</span>
                            <span class="ranked-value">{formatNumber(item.value)}</span>
                        </div>
                    {/each}
                </div>
            {/if}
        </div>

        <!-- Session Duration -->
        <div class="chart-section">
            <div class="chart-header">
                <h3>{$text('settings.server_stats.session_duration')}</h3>
            </div>
            {#if sessionDurationData.length === 0}
                <p class="no-data">{$text('settings.server_stats.no_data')}</p>
            {:else}
                <div class="ranked-list">
                    {#each sessionDurationData as item}
                        {@const total = sessionDurationData.reduce((s, i) => s + i.value, 0)}
                        {@const pct = total > 0 ? Math.round((item.value / total) * 100) : 0}
                        <div class="ranked-item">
                            <span class="ranked-key">{item.key}</span>
                            <div class="ranked-bar-wrap">
                                <div class="ranked-bar" style="width: {pct}%"></div>
                            </div>
                            <span class="ranked-pct">{pct}%</span>
                            <span class="ranked-value">{formatNumber(item.value)}</span>
                        </div>
                    {/each}
                </div>
            {/if}
        </div>

        <!-- Top Referrers -->
        <div class="chart-section">
            <div class="chart-header">
                <h3>{$text('settings.server_stats.top_referrers')}</h3>
            </div>
            {#if topReferrers.length === 0}
                <p class="no-data">{$text('settings.server_stats.no_data')}</p>
            {:else}
                <div class="ranked-list">
                    {#each topReferrers as item}
                        {@const total = topReferrers.reduce((s, i) => s + i.value, 0)}
                        {@const pct = total > 0 ? Math.round((item.value / total) * 100) : 0}
                        <div class="ranked-item">
                            <span class="ranked-key">{item.key}</span>
                            <div class="ranked-bar-wrap">
                                <div class="ranked-bar" style="width: {pct}%"></div>
                            </div>
                            <span class="ranked-pct">{pct}%</span>
                            <span class="ranked-value">{formatNumber(item.value)}</span>
                        </div>
                    {/each}
                </div>
            {/if}
        </div>

        <!-- ================================================================
             SIGNUP FUNNEL — always visible
             ================================================================ -->
        <div class="chart-section">
            <div class="chart-header">
                <h3>{$text('settings.server_stats.signup_funnel')}</h3>
            </div>
            {#if signupFunnelData.every(s => s.value === 0)}
                <p class="no-data">{$text('settings.server_stats.no_data')}</p>
            {:else}
                <div class="ranked-list">
                    {#each signupFunnelData as step}
                        {@const maxStep = Math.max(...signupFunnelData.map(s => s.value), 1)}
                        {@const pct = Math.round((step.value / maxStep) * 100)}
                        <div class="ranked-item">
                            <span class="ranked-key">{step.label}</span>
                            <div class="ranked-bar-wrap">
                                <div class="ranked-bar" style="width: {pct}%"></div>
                            </div>
                            <span class="ranked-pct">{pct}%</span>
                            <span class="ranked-value">{formatNumber(step.value)}</span>
                        </div>
                    {/each}
                </div>
            {/if}
        </div>

        <!-- ================================================================
             APP USAGE — always visible
             ================================================================ -->
        <div class="chart-section">
            <div class="chart-header">
                <h3>{$text('settings.server_stats.app_usage')}</h3>
            </div>
            {#if appUsageData.length === 0}
                <p class="no-data">{$text('settings.server_stats.no_data')}</p>
            {:else}
                <div class="ranked-list">
                    {#each appUsageData as item}
                        {@const total = appUsageData.reduce((s, i) => s + i.value, 0)}
                        {@const pct = total > 0 ? Math.round((item.value / total) * 100) : 0}
                        <div class="ranked-item">
                            <span class="ranked-key">{item.key}</span>
                            <div class="ranked-bar-wrap">
                                <div class="ranked-bar" style="width: {pct}%"></div>
                            </div>
                            <span class="ranked-pct">{pct}%</span>
                            <span class="ranked-value">{formatNumber(item.value)}</span>
                        </div>
                    {/each}
                </div>
            {/if}
        </div>

    {/if}
</div>

<style>
    /* ============================================================================
       CONTAINER
       ============================================================================ */

    .server-stats {
        padding: 1rem;
        max-width: 900px;
        margin: 0 auto;
    }

    /* ============================================================================
       KEY METRICS — 2×2 grid
       ============================================================================ */

    .metrics-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 0.75rem;
        margin-bottom: 1rem;
    }

    .metric-card {
        background: var(--color-background-secondary);
        border: 1px solid var(--color-border);
        border-radius: var(--radius-5);
        padding: 0.875rem 1rem;
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
    }

    .metric-label {
        font-size: 0.72rem;
        color: var(--color-text-tertiary);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        line-height: 1.2;
    }

    .metric-value {
        font-size: 1.4rem;
        font-weight: 700;
        color: var(--color-primary);
        line-height: 1;
    }

    /* ============================================================================
       TODAY'S SUMMARY — label: value rows
       ============================================================================ */

    .today-summary {
        background: var(--color-background-secondary);
        border: 1px solid var(--color-border);
        border-radius: var(--radius-5);
        padding: 1rem;
        margin-bottom: 1rem;
    }

    .today-summary h3 {
        margin: 0 0 0.75rem;
        font-size: 0.85rem;
        color: var(--color-text-secondary);
        font-weight: 600;
    }

    .summary-rows {
        display: flex;
        flex-direction: column;
    }

    .summary-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0.45rem 0;
        border-bottom: 1px solid var(--color-border);
    }

    .summary-row:last-child {
        border-bottom: none;
    }

    .summary-label {
        font-size: 0.82rem;
        color: var(--color-text-secondary);
    }

    .summary-value {
        font-size: 0.9rem;
        font-weight: 600;
        color: var(--color-text-primary);
    }

    /* ============================================================================
       CHART SECTIONS
       ============================================================================ */

    .chart-section {
        background: var(--color-background-secondary);
        border: 1px solid var(--color-border);
        border-radius: var(--radius-5);
        padding: 1rem;
        margin-bottom: 1rem;
    }

    .chart-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 0.5rem;
        margin-bottom: 0.75rem;
    }

    .chart-header h3 {
        margin: 0;
        font-size: 0.9rem;
        color: var(--color-text-primary);
        font-weight: 600;
    }

    /* ============================================================================
       UNIFIED CHART TABS — grouped by Daily / Monthly / Traffic
       ============================================================================ */

    .tab-groups {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
        margin-bottom: 1rem;
    }

    .tab-group {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        flex-wrap: wrap;
    }

    .tab-group-label {
        font-size: 0.7rem;
        color: var(--color-text-tertiary);
        text-transform: uppercase;
        letter-spacing: 0.06em;
        min-width: 52px;
        flex-shrink: 0;
    }

    .tabs {
        display: flex;
        gap: 0.25rem;
        background: var(--color-background-tertiary);
        padding: 0.2rem;
        border-radius: var(--radius-3);
        flex-wrap: wrap;
    }

    .tab {
        background: none;
        border: none;
        padding: 0.3rem 0.65rem;
        font-size: 0.75rem;
        font-weight: 500;
        color: var(--color-text-secondary);
        cursor: pointer;
        border-radius: var(--radius-2);
        transition: all var(--duration-fast) var(--easing-default);
        white-space: nowrap;
    }

    .tab:hover {
        color: var(--color-text-primary);
    }

    .tab.active {
        background: var(--color-primary);
        color: white;
    }

    /* ============================================================================
       CHART CANVAS
       ============================================================================ */

    .chart-container {
        position: relative;
        width: 100%;
        aspect-ratio: 700 / 200;
    }

    .chart {
        width: 100%;
        height: 100%;
    }

    .data-point {
        transition: r 0.1s ease;
    }

    .bar {
        transition: fill var(--duration-fast) var(--easing-default);
    }

    .no-data-chart {
        text-align: center;
        font-size: 0.82rem;
        color: var(--color-text-tertiary);
        padding: 2rem 0 1rem;
        margin: 0;
    }

    /* ============================================================================
       TOOLTIP
       ============================================================================ */

    .chart-tooltip {
        position: absolute;
        transform: translateX(-50%);
        background: var(--color-background-primary);
        border: 1px solid var(--color-border);
        border-radius: var(--radius-3);
        padding: 0.4rem 0.65rem;
        box-shadow: var(--shadow-md);
        pointer-events: none;
        z-index: 10;
        white-space: nowrap;
    }

    .tooltip-date {
        font-size: 0.68rem;
        color: var(--color-text-tertiary);
        margin-bottom: 0.1rem;
    }

    .tooltip-value {
        font-size: 0.82rem;
        font-weight: 600;
        color: var(--color-text-primary);
    }

    /* ============================================================================
       RANKED LISTS — full-width, 4-col grid: key | bar | % | count
       ============================================================================ */

    .ranked-list {
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }

    .ranked-item {
        display: grid;
        grid-template-columns: minmax(80px, 130px) 1fr 36px 52px;
        align-items: center;
        gap: 0.5rem;
    }

    .ranked-key {
        font-size: 0.8rem;
        color: var(--color-text-secondary);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .ranked-bar-wrap {
        background: var(--color-background-tertiary);
        border-radius: var(--radius-1);
        height: 8px;
        overflow: hidden;
    }

    .ranked-bar {
        height: 100%;
        background: var(--color-primary);
        border-radius: var(--radius-1);
        transition: width var(--duration-slow) var(--easing-default);
        min-width: 2px;
    }

    .ranked-pct {
        font-size: 0.75rem;
        color: var(--color-text-tertiary);
        text-align: right;
        font-variant-numeric: tabular-nums;
    }

    .ranked-value {
        font-size: 0.78rem;
        font-weight: 600;
        color: var(--color-text-primary);
        text-align: right;
        font-variant-numeric: tabular-nums;
    }

    .no-data {
        font-size: 0.8rem;
        color: var(--color-text-tertiary);
        margin: 0;
        padding: 0.25rem 0;
    }

    /* ============================================================================
       LOADING & ERROR
       ============================================================================ */

    .loading, .error {
        text-align: center;
        padding: 3rem;
    }

    .spinner {
        width: 2.5rem;
        height: 2.5rem;
        border: 3px solid var(--color-border);
        border-top: 3px solid var(--color-primary);
        border-radius: 50%;
        animation: spin 1s linear infinite;
        margin: 0 auto 1rem;
    }

    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }

    .error-icon {
        font-size: 2rem;
        margin-bottom: 0.5rem;
    }

    .btn {
        padding: 0.5rem 1rem;
        border-radius: var(--radius-3);
        font-weight: 600;
        cursor: pointer;
        border: none;
        transition: all var(--duration-normal) var(--easing-default);
        margin-top: 1rem;
    }

    .btn-primary {
        background: var(--color-primary);
        color: white;
    }

    .btn-primary:hover {
        filter: brightness(1.1);
    }
</style>
