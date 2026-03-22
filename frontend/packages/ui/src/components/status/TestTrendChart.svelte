<!--
    TestTrendChart — SVG sparkline showing pass rate over last 14 days.
    No chart library dependency — pure SVG.
    Architecture: See docs/architecture/status-page.md
    Tests: N/A
-->
<script lang="ts">
    type TrendPoint = {
        date: string;
        total: number;
        passed: number;
        failed: number;
    };

    let { trend = [] }: { trend: TrendPoint[] } = $props();

    const width = 200;
    const height = 40;
    const padding = 2;

    let points = $derived.by(() => {
        if (trend.length < 2) return '';
        const maxTotal = Math.max(...trend.map((t) => t.total), 1);
        const step = (width - padding * 2) / (trend.length - 1);

        return trend
            .map((t, i) => {
                const passRate = t.total > 0 ? t.passed / t.total : 0;
                const x = padding + i * step;
                const y = height - padding - passRate * (height - padding * 2);
                return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
            })
            .join(' ');
    });

    let lastPassRate = $derived.by(() => {
        if (trend.length === 0) return null;
        const last = trend[trend.length - 1];
        return last.total > 0 ? Math.round((last.passed / last.total) * 100) : 0;
    });
</script>

{#if trend.length >= 2}
    <div class="trend-container">
        <svg viewBox="0 0 {width} {height}" class="sparkline" aria-label="Test pass rate trend">
            <path d={points} fill="none" stroke={lastPassRate !== null && lastPassRate >= 80 ? '#22c55e' : '#ef4444'} stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round" />
        </svg>
        {#if lastPassRate !== null}
            <span class="rate" class:good={lastPassRate >= 80} class:bad={lastPassRate < 80}>{lastPassRate}%</span>
        {/if}
    </div>
{/if}

<style>
    .trend-container {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
    }

    .sparkline {
        width: 100px;
        height: 24px;
    }

    .rate {
        font-size: 0.75rem;
        font-weight: 600;
        font-variant-numeric: tabular-nums;
    }

    .rate.good {
        color: #15803d;
    }

    .rate.bad {
        color: #ef4444;
    }
</style>
