<!--
    Settings Server Statistics Component

    Displays global server statistics for admins using a modern dashboard layout.
    Shows key metrics in cards and time-series data in interactive charts.
    Replaces table-based layout with visual charts for better UX.
-->
<script lang="ts">
    import { onMount } from 'svelte';
    import { getApiEndpoint, text } from '@repo/ui';
    import { fade } from 'svelte/transition';
    import SettingsItem from '../../SettingsItem.svelte';

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

    // ============================================================================
    // STATE
    // ============================================================================
    
    let isLoading = $state(true);
    let error = $state<string | null>(null);
    let dailyHistory = $state<StatsRecord[]>([]);
    let monthlyHistory = $state<StatsRecord[]>([]);
    let currentStats = $state<Partial<StatsRecord>>({});
    let newsletterSubscribersCount = $state(0);
    
    // Active chart metric for daily view
    let activeMetric = $state<'messages' | 'credits_used' | 'users' | 'income'>('messages');
    // Active chart metric for monthly view
    let activeMonthlyMetric = $state<'messages' | 'credits_used' | 'users' | 'income'>('income');
    
    // Hover state for charts
    let hoveredPoint = $state<ChartDataPoint | null>(null);
    let hoveredMonthlyPoint = $state<ChartDataPoint | null>(null);
    let tooltipX = $state(0);
    let tooltipY = $state(0);
    let monthlyTooltipX = $state(0);
    let monthlyTooltipY = $state(0);

    // ============================================================================
    // DATA LOADING
    // ============================================================================

    /**
     * Load server statistics from server
     */
    async function loadStats() {
        try {
            isLoading = true;
            error = null;

            const response = await fetch(getApiEndpoint('/v1/admin/server-stats'), {
                credentials: 'include'
            });

            if (!response.ok) {
                if (response.status === 403) {
                    error = 'Admin privileges required to view server statistics.';
                } else {
                    error = 'Failed to load server statistics.';
                }
                return;
            }

            const data = await response.json();
            currentStats = data.current || {};
            newsletterSubscribersCount = data.newsletter_subscribers_count || 0;
            
            // Filter out invalid dates (before 2020) from history
            const minYear = 2020;
            dailyHistory = (data.daily_history || []).filter((record: StatsRecord) => {
                const date = record.date || '';
                const year = parseInt(date.substring(0, 4));
                return !isNaN(year) && year >= minYear;
            });
            
            monthlyHistory = (data.monthly_history || []).filter((record: StatsRecord) => {
                const yearMonth = record.year_month || '';
                const year = parseInt(yearMonth.substring(0, 4));
                return !isNaN(year) && year >= minYear;
            });

        } catch (err) {
            console.error('Error loading stats:', err);
            error = 'Failed to connect to server.';
        } finally {
            isLoading = false;
        }
    }

    // ============================================================================
    // FORMATTING UTILITIES
    // ============================================================================

    /**
     * Format currency (cents to EUR)
     */
    function formatCurrency(cents: number = 0): string {
        return (cents / 100).toLocaleString('en-US', {
            style: 'currency',
            currency: 'EUR'
        });
    }

    /**
     * Convert credits to EUR for liability display
     * Based on pricing tiers: approximately 1000 credits = 1 EUR
     */
    function formatLiabilityInEur(credits: number = 0): string {
        const eur = credits / 1000;
        return eur.toLocaleString('en-US', {
            style: 'currency',
            currency: 'EUR',
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
    }

    /**
     * Format number with thousands separator
     */
    function formatNumber(num: number = 0): string {
        return num.toLocaleString('en-US');
    }

    /**
     * Format date for display (short form for charts)
     */
    function formatDateShort(dateStr: string): string {
        if (!dateStr) return '';
        try {
            const date = new Date(dateStr);
            return date.toLocaleDateString('en-US', {
                month: 'short',
                day: 'numeric'
            });
        } catch {
            return dateStr;
        }
    }

    /**
     * Format date for tooltip (full form)
     */
    function formatDateFull(dateStr: string): string {
        if (!dateStr) return '';
        try {
            const date = new Date(dateStr);
            return date.toLocaleDateString('en-US', {
                year: 'numeric',
                month: 'short',
                day: 'numeric'
            });
        } catch {
            return dateStr;
        }
    }

    /**
     * Format month for display
     */
    function formatMonth(monthStr: string): string {
        if (!monthStr) return '';
        try {
            const [year, month] = monthStr.split('-');
            const date = new Date(parseInt(year), parseInt(month) - 1);
            return date.toLocaleDateString('en-US', {
                year: 'numeric',
                month: 'short'
            });
        } catch {
            return monthStr;
        }
    }

    /**
     * Format month short for chart labels
     */
    function formatMonthShort(monthStr: string): string {
        if (!monthStr) return '';
        try {
            const [year, month] = monthStr.split('-');
            const date = new Date(parseInt(year), parseInt(month) - 1);
            return date.toLocaleDateString('en-US', { month: 'short' });
        } catch {
            return monthStr;
        }
    }

    // ============================================================================
    // CHART DATA DERIVATIONS
    // ============================================================================

    /**
     * Get chart data for the selected daily metric
     */
    function getDailyChartData(metric: typeof activeMetric): ChartDataPoint[] {
        // Sort by date ascending
        const sorted = [...dailyHistory].sort((a, b) => 
            (a.date || '').localeCompare(b.date || '')
        );
        
        return sorted.map(day => {
            let value: number;
            let label: string;
            
            switch (metric) {
                case 'messages':
                    value = day.messages_sent || 0;
                    label = `${formatNumber(value)} messages`;
                    break;
                case 'credits_used':
                    value = day.credits_used || 0;
                    label = `${formatNumber(value)} credits`;
                    break;
                case 'users':
                    value = day.new_users_registered || 0;
                    label = `${formatNumber(value)} new users`;
                    break;
                case 'income':
                    value = day.income_eur_cents || 0;
                    label = formatCurrency(value);
                    break;
                default:
                    value = 0;
                    label = '';
            }
            
            return {
                date: day.date || '',
                value,
                label
            };
        });
    }

    /**
     * Get chart data for the selected monthly metric
     */
    function getMonthlyChartData(metric: typeof activeMonthlyMetric): ChartDataPoint[] {
        // Sort by year_month ascending
        const sorted = [...monthlyHistory].sort((a, b) => 
            (a.year_month || '').localeCompare(b.year_month || '')
        );
        
        return sorted.map(month => {
            let value: number;
            let label: string;
            
            switch (metric) {
                case 'messages':
                    value = month.messages_sent || 0;
                    label = `${formatNumber(value)} messages`;
                    break;
                case 'credits_used':
                    value = month.credits_used || 0;
                    label = `${formatNumber(value)} credits`;
                    break;
                case 'users':
                    value = month.new_users_registered || 0;
                    label = `${formatNumber(value)} new users`;
                    break;
                case 'income':
                    value = month.income_eur_cents || 0;
                    label = formatCurrency(value);
                    break;
                default:
                    value = 0;
                    label = '';
            }
            
            return {
                date: month.year_month || '',
                value,
                label
            };
        });
    }

    /**
     * Calculate max value for chart scaling
     */
    function getMaxValue(data: ChartDataPoint[]): number {
        if (data.length === 0) return 100;
        const max = Math.max(...data.map(d => d.value));
        // Add 10% padding and ensure minimum
        return Math.max(max * 1.1, 10);
    }

    /**
     * Generate SVG path for area chart
     */
    function generateAreaPath(data: ChartDataPoint[], width: number, height: number): string {
        if (data.length === 0) return '';
        
        const maxValue = getMaxValue(data);
        const padding = 40;
        const chartWidth = width - padding * 2;
        const chartHeight = height - padding * 2;
        
        const points = data.map((d, i) => {
            const x = padding + (i / Math.max(data.length - 1, 1)) * chartWidth;
            const y = padding + chartHeight - (d.value / maxValue) * chartHeight;
            return { x, y };
        });
        
        // Line path
        let linePath = `M ${points[0].x} ${points[0].y}`;
        for (let i = 1; i < points.length; i++) {
            linePath += ` L ${points[i].x} ${points[i].y}`;
        }
        
        // Area path (fill down to bottom)
        let areaPath = linePath;
        areaPath += ` L ${points[points.length - 1].x} ${padding + chartHeight}`;
        areaPath += ` L ${points[0].x} ${padding + chartHeight}`;
        areaPath += ' Z';
        
        return areaPath;
    }

    /**
     * Generate SVG path for line chart (stroke only)
     */
    function generateLinePath(data: ChartDataPoint[], width: number, height: number): string {
        if (data.length === 0) return '';
        
        const maxValue = getMaxValue(data);
        const padding = 40;
        const chartWidth = width - padding * 2;
        const chartHeight = height - padding * 2;
        
        const points = data.map((d, i) => {
            const x = padding + (i / Math.max(data.length - 1, 1)) * chartWidth;
            const y = padding + chartHeight - (d.value / maxValue) * chartHeight;
            return { x, y };
        });
        
        let path = `M ${points[0].x} ${points[0].y}`;
        for (let i = 1; i < points.length; i++) {
            path += ` L ${points[i].x} ${points[i].y}`;
        }
        
        return path;
    }

    /**
     * Get data point positions for hover detection
     */
    function getDataPoints(data: ChartDataPoint[], width: number, height: number): Array<{ x: number; y: number; point: ChartDataPoint }> {
        if (data.length === 0) return [];
        
        const maxValue = getMaxValue(data);
        const padding = 40;
        const chartWidth = width - padding * 2;
        const chartHeight = height - padding * 2;
        
        return data.map((d, i) => ({
            x: padding + (i / Math.max(data.length - 1, 1)) * chartWidth,
            y: padding + chartHeight - (d.value / maxValue) * chartHeight,
            point: d
        }));
    }

    /**
     * Handle mouse move over chart for tooltip
     */
    function handleChartMouseMove(event: MouseEvent, data: ChartDataPoint[], isMonthly: boolean = false) {
        const target = event.currentTarget as SVGElement;
        const rect = target.getBoundingClientRect();
        const mouseX = event.clientX - rect.left;
        
        const points = getDataPoints(data, rect.width, rect.height);
        
        // Find closest point
        let closest: typeof points[0] | null = null;
        let minDist = Infinity;
        
        for (const p of points) {
            const dist = Math.abs(p.x - mouseX);
            if (dist < minDist) {
                minDist = dist;
                closest = p;
            }
        }
        
        if (closest && minDist < 30) {
            if (isMonthly) {
                hoveredMonthlyPoint = closest.point;
                monthlyTooltipX = closest.x;
                monthlyTooltipY = closest.y;
            } else {
                hoveredPoint = closest.point;
                tooltipX = closest.x;
                tooltipY = closest.y;
            }
        } else {
            if (isMonthly) {
                hoveredMonthlyPoint = null;
            } else {
                hoveredPoint = null;
            }
        }
    }

    function handleChartMouseLeave(isMonthly: boolean = false) {
        if (isMonthly) {
            hoveredMonthlyPoint = null;
        } else {
            hoveredPoint = null;
        }
    }

    // ============================================================================
    // DERIVED VALUES
    // ============================================================================

    const dailyChartData = $derived(getDailyChartData(activeMetric));
    const monthlyChartData = $derived(getMonthlyChartData(activeMonthlyMetric));

    // ============================================================================
    // LIFECYCLE
    // ============================================================================

    onMount(() => {
        loadStats();
    });
</script>

<div class="server-stats" in:fade={{ duration: 300 }}>
    <!-- Header - simplified, removed redundant heading -->
    <SettingsItem 
        type="heading"
        icon="usage"
        subtitleTop={$text('settings.server_stats.description.text')}
        title={$text('settings.server_stats.title.text')}
    />

    {#if isLoading}
        <div class="loading">
            <div class="spinner"></div>
            <p>{$text('settings.server_stats.loading.text')}</p>
        </div>
    {:else if error}
        <div class="error">
            <div class="error-icon">⚠️</div>
            <p>{error}</p>
            <button onclick={loadStats} class="btn btn-primary">{$text('settings.server_stats.try_again.text')}</button>
        </div>
    {:else}
        <!-- Key Metrics Cards Row -->
        <div class="metrics-row">
            <div class="metric-card">
                <span class="metric-label">{$text('settings.server_stats.total_users.text')}</span>
                <span class="metric-value">{formatNumber(currentStats.total_regular_users || 0)}</span>
            </div>
            <div class="metric-card">
                <span class="metric-label">{$text('settings.server_stats.active_subscriptions.text')}</span>
                <span class="metric-value">{formatNumber(currentStats.active_subscriptions || 0)}</span>
            </div>
            <div class="metric-card">
                <span class="metric-label">{$text('settings.server_stats.total_liability.text')}</span>
                <span class="metric-value">{formatLiabilityInEur(currentStats.liability_total || 0)}</span>
            </div>
            <div class="metric-card">
                <span class="metric-label">{$text('settings.server_stats.newsletter_subscribers.text')}</span>
                <span class="metric-value">{formatNumber(newsletterSubscribersCount)}</span>
            </div>
        </div>

        <!-- Today's Activity Summary -->
        <div class="today-summary">
            <h3>{$text('settings.server_stats.latest_activity.text', { date: currentStats.date ? formatDateFull(currentStats.date) : 'Today' })}</h3>
            <div class="summary-grid">
                <div class="summary-item">
                    <span class="value">{formatNumber(currentStats.new_users_registered || 0)}</span>
                    <span class="label">{$text('settings.server_stats.new_registrations.text')}</span>
                </div>
                <div class="summary-item">
                    <span class="value">{formatNumber(currentStats.new_users_finished_signup || 0)}</span>
                    <span class="label">{$text('settings.server_stats.finished_signup.text')}</span>
                </div>
                <div class="summary-item">
                    <span class="value">{formatCurrency(currentStats.income_eur_cents)}</span>
                    <span class="label">{$text('settings.server_stats.income.text')}</span>
                </div>
                <div class="summary-item">
                    <span class="value">{formatNumber(currentStats.credits_sold || 0)}</span>
                    <span class="label">{$text('settings.server_stats.credits_sold.text')}</span>
                </div>
                <div class="summary-item">
                    <span class="value">{formatNumber(currentStats.credits_used || 0)}</span>
                    <span class="label">{$text('settings.server_stats.credits_used.text')}</span>
                </div>
                <div class="summary-item">
                    <span class="value">{formatNumber(currentStats.messages_sent || 0)}</span>
                    <span class="label">{$text('settings.server_stats.messages_sent.text')}</span>
                </div>
            </div>
        </div>

        <!-- Daily Chart Section -->
        <div class="chart-section">
            <div class="chart-header">
                <h3>{$text('settings.server_stats.daily_history.text')}</h3>
                <div class="metric-tabs">
                    <button 
                        class="tab" 
                        class:active={activeMetric === 'messages'}
                        onclick={() => activeMetric = 'messages'}
                    >
                        {$text('settings.server_stats.messages.text')}
                    </button>
                    <button 
                        class="tab" 
                        class:active={activeMetric === 'credits_used'}
                        onclick={() => activeMetric = 'credits_used'}
                    >
                        {$text('settings.server_stats.credits_used.text')}
                    </button>
                    <button 
                        class="tab" 
                        class:active={activeMetric === 'users'}
                        onclick={() => activeMetric = 'users'}
                    >
                        {$text('settings.server_stats.new_users.text')}
                    </button>
                    <button 
                        class="tab" 
                        class:active={activeMetric === 'income'}
                        onclick={() => activeMetric = 'income'}
                    >
                        {$text('settings.server_stats.income.text')}
                    </button>
                </div>
            </div>
            
            <div class="chart-container">
                <!-- svelte-ignore a11y_no_static_element_interactions -->
                <svg 
                    class="chart" 
                    viewBox="0 0 700 220"
                    onmousemove={(e) => handleChartMouseMove(e, dailyChartData)}
                    onmouseleave={() => handleChartMouseLeave()}
                >
                    <!-- Grid lines -->
                    <g class="grid-lines">
                        {#each [0.25, 0.5, 0.75, 1] as ratio}
                            <line 
                                x1="40" 
                                y1={40 + 140 * (1 - ratio)} 
                                x2="660" 
                                y2={40 + 140 * (1 - ratio)} 
                                stroke="var(--color-border)" 
                                stroke-dasharray="4 4"
                                opacity="0.5"
                            />
                        {/each}
                    </g>
                    
                    <!-- Area fill -->
                    <path 
                        d={generateAreaPath(dailyChartData, 700, 220)}
                        fill="url(#areaGradient)"
                        opacity="0.3"
                    />
                    
                    <!-- Line -->
                    <path 
                        d={generateLinePath(dailyChartData, 700, 220)}
                        fill="none"
                        stroke="var(--color-primary)"
                        stroke-width="2"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                    />
                    
                    <!-- Data points -->
                    {#each getDataPoints(dailyChartData, 700, 220) as { x, y, point }}
                        <circle 
                            cx={x} 
                            cy={y} 
                            r={hoveredPoint?.date === point.date ? 6 : 3}
                            fill="var(--color-primary)"
                            class="data-point"
                        />
                    {/each}
                    
                    <!-- X-axis labels (show every 5th) -->
                    <!-- svelte-ignore component_name_lowercase -->
                    {#each dailyChartData as point, i}
                        {#if i % 5 === 0 || i === dailyChartData.length - 1}
                            <text 
                                x={40 + (i / Math.max(dailyChartData.length - 1, 1)) * 620} 
                                y="200" 
                                text-anchor="middle" 
                                fill="var(--color-text-tertiary)"
                                font-size="10"
                            >
                                {formatDateShort(point.date)}
                            </text>
                        {/if}
                    {/each}
                    
                    <!-- Gradient definition -->
                    <defs>
                        <linearGradient id="areaGradient" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" stop-color="var(--color-primary)" stop-opacity="0.4"/>
                            <stop offset="100%" stop-color="var(--color-primary)" stop-opacity="0"/>
                        </linearGradient>
                    </defs>
                </svg>
                
                <!-- Tooltip -->
                {#if hoveredPoint}
                    <div 
                        class="chart-tooltip"
                        style="left: {tooltipX}px; top: {tooltipY - 50}px;"
                        in:fade={{ duration: 100 }}
                    >
                        <div class="tooltip-date">{formatDateFull(hoveredPoint.date)}</div>
                        <div class="tooltip-value">{hoveredPoint.label}</div>
                    </div>
                {/if}
            </div>
        </div>

        <!-- Monthly Chart Section -->
        <div class="chart-section">
            <div class="chart-header">
                <h3>{$text('settings.server_stats.monthly_history.text')}</h3>
                <div class="metric-tabs">
                    <button 
                        class="tab" 
                        class:active={activeMonthlyMetric === 'income'}
                        onclick={() => activeMonthlyMetric = 'income'}
                    >
                        {$text('settings.server_stats.income.text')}
                    </button>
                    <button 
                        class="tab" 
                        class:active={activeMonthlyMetric === 'credits_used'}
                        onclick={() => activeMonthlyMetric = 'credits_used'}
                    >
                        {$text('settings.server_stats.credits_used.text')}
                    </button>
                    <button 
                        class="tab" 
                        class:active={activeMonthlyMetric === 'messages'}
                        onclick={() => activeMonthlyMetric = 'messages'}
                    >
                        {$text('settings.server_stats.messages.text')}
                    </button>
                    <button 
                        class="tab" 
                        class:active={activeMonthlyMetric === 'users'}
                        onclick={() => activeMonthlyMetric = 'users'}
                    >
                        {$text('settings.server_stats.new_users.text')}
                    </button>
                </div>
            </div>
            
            <!-- Bar chart for monthly data -->
            <div class="chart-container bar-chart-container">
                <!-- svelte-ignore a11y_no_static_element_interactions -->
                <svg 
                    class="chart bar-chart" 
                    viewBox="0 0 700 220"
                    onmousemove={(e) => handleChartMouseMove(e, monthlyChartData, true)}
                    onmouseleave={() => handleChartMouseLeave(true)}
                >
                    <!-- Grid lines -->
                    <g class="grid-lines">
                        {#each [0.25, 0.5, 0.75, 1] as ratio}
                            <line 
                                x1="40" 
                                y1={40 + 140 * (1 - ratio)} 
                                x2="660" 
                                y2={40 + 140 * (1 - ratio)} 
                                stroke="var(--color-border)" 
                                stroke-dasharray="4 4"
                                opacity="0.5"
                            />
                        {/each}
                    </g>
                    
                    <!-- Bars -->
                    {#each monthlyChartData as point, i}
                        {@const maxValue = getMaxValue(monthlyChartData)}
                        {@const barWidth = Math.max(620 / monthlyChartData.length - 8, 20)}
                        {@const barHeight = Math.max((point.value / maxValue) * 140, 2)}
                        {@const x = 40 + (i / Math.max(monthlyChartData.length - 1, 1)) * 620 - barWidth / 2}
                        {@const y = 180 - barHeight}
                        <rect 
                            x={monthlyChartData.length === 1 ? 350 - barWidth / 2 : x}
                            {y}
                            width={barWidth}
                            height={barHeight}
                            fill={hoveredMonthlyPoint?.date === point.date ? 'var(--color-primary)' : 'var(--color-primary-muted, rgba(99, 102, 241, 0.7))'}
                            rx="4"
                            class="bar"
                        />
                        
                        <!-- X-axis label -->
                        <!-- svelte-ignore component_name_lowercase -->
                        <text 
                            x={monthlyChartData.length === 1 ? 350 : 40 + (i / Math.max(monthlyChartData.length - 1, 1)) * 620} 
                            y="200" 
                            text-anchor="middle" 
                            fill="var(--color-text-tertiary)"
                            font-size="10"
                        >
                            {formatMonthShort(point.date)}
                        </text>
                    {/each}
                </svg>
                
                <!-- Tooltip -->
                {#if hoveredMonthlyPoint}
                    <div 
                        class="chart-tooltip"
                        style="left: {monthlyTooltipX}px; top: {monthlyTooltipY - 50}px;"
                        in:fade={{ duration: 100 }}
                    >
                        <div class="tooltip-date">{formatMonth(hoveredMonthlyPoint.date)}</div>
                        <div class="tooltip-value">{hoveredMonthlyPoint.label}</div>
                    </div>
                {/if}
            </div>
        </div>
    {/if}
</div>

<style>
    /* ============================================================================
       CONTAINER & LAYOUT
       ============================================================================ */
    
    .server-stats {
        padding: 1rem;
        max-width: 900px;
        margin: 0 auto;
    }

    /* ============================================================================
       KEY METRICS ROW
       ============================================================================ */

    .metrics-row {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 1rem;
        margin-bottom: 1.5rem;
    }

    .metric-card {
        background: var(--color-background-secondary);
        border: 1px solid var(--color-border);
        border-radius: 12px;
        padding: 1rem;
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
    }

    .metric-label {
        font-size: 0.75rem;
        color: var(--color-text-tertiary);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 0.25rem;
    }

    .metric-value {
        font-size: 1.5rem;
        font-weight: 700;
        color: var(--color-primary);
    }

    /* ============================================================================
       TODAY'S SUMMARY
       ============================================================================ */

    .today-summary {
        background: var(--color-background-tertiary);
        border: 1px solid var(--color-border);
        border-radius: 12px;
        padding: 1rem;
        margin-bottom: 1.5rem;
    }

    .today-summary h3 {
        margin: 0 0 1rem;
        font-size: 0.9rem;
        color: var(--color-text-secondary);
        font-weight: 600;
    }

    .summary-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
        gap: 1rem;
    }

    .summary-item {
        display: flex;
        flex-direction: column;
        gap: 0.125rem;
    }

    .summary-item .value {
        font-size: 1.1rem;
        font-weight: 600;
        color: var(--color-text-primary);
    }

    .summary-item .label {
        font-size: 0.75rem;
        color: var(--color-text-tertiary);
    }

    /* ============================================================================
       CHART SECTIONS
       ============================================================================ */

    .chart-section {
        background: var(--color-background-secondary);
        border: 1px solid var(--color-border);
        border-radius: 12px;
        padding: 1rem;
        margin-bottom: 1.5rem;
    }

    .chart-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 0.75rem;
        margin-bottom: 1rem;
    }

    .chart-header h3 {
        margin: 0;
        font-size: 0.9rem;
        color: var(--color-text-primary);
        font-weight: 600;
    }

    .metric-tabs {
        display: flex;
        gap: 0.25rem;
        background: var(--color-background-tertiary);
        padding: 0.25rem;
        border-radius: 8px;
    }

    .tab {
        background: none;
        border: none;
        padding: 0.35rem 0.75rem;
        font-size: 0.75rem;
        font-weight: 500;
        color: var(--color-text-secondary);
        cursor: pointer;
        border-radius: 6px;
        transition: all 0.15s ease;
    }

    .tab:hover {
        color: var(--color-text-primary);
    }

    .tab.active {
        background: var(--color-primary);
        color: white;
    }

    .chart-container {
        position: relative;
        width: 100%;
        aspect-ratio: 700 / 220;
    }

    .chart {
        width: 100%;
        height: 100%;
    }

    .data-point {
        transition: r 0.15s ease;
    }

    .bar {
        transition: fill 0.15s ease;
    }

    /* ============================================================================
       TOOLTIPS
       ============================================================================ */

    .chart-tooltip {
        position: absolute;
        transform: translateX(-50%);
        background: var(--color-background-primary);
        border: 1px solid var(--color-border);
        border-radius: 8px;
        padding: 0.5rem 0.75rem;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        pointer-events: none;
        z-index: 10;
        white-space: nowrap;
    }

    .tooltip-date {
        font-size: 0.7rem;
        color: var(--color-text-tertiary);
        margin-bottom: 0.125rem;
    }

    .tooltip-value {
        font-size: 0.85rem;
        font-weight: 600;
        color: var(--color-text-primary);
    }

    /* ============================================================================
       LOADING & ERROR STATES
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
        border-radius: 8px;
        font-weight: 600;
        cursor: pointer;
        border: none;
        transition: all 0.2s ease;
        margin-top: 1rem;
    }

    .btn-primary {
        background: var(--color-primary);
        color: white;
    }

    .btn-primary:hover {
        filter: brightness(1.1);
    }

    /* ============================================================================
       RESPONSIVE
       ============================================================================ */

    @media (max-width: 640px) {
        .server-stats {
            padding: 0.75rem;
        }
        
        .metrics-row {
            grid-template-columns: 1fr;
            gap: 0.75rem;
        }
        
        .metric-card {
            flex-direction: row;
            justify-content: space-between;
            padding: 0.75rem 1rem;
        }
        
        .metric-label {
            margin-bottom: 0;
        }
        
        .summary-grid {
            grid-template-columns: repeat(2, 1fr);
        }
        
        .chart-header {
            flex-direction: column;
            align-items: flex-start;
        }
        
        .metric-tabs {
            width: 100%;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
        }
        
        .tab {
            flex-shrink: 0;
        }
    }
</style>
