<!--
    HealthTimeline — Horizontal bar chart showing health status over time.
    Left = oldest, right = now. Color-coded by status per time bucket.
    Architecture: See docs/architecture/status-page.md
    Tests: N/A
-->
<script lang="ts">
    type Bucket = {
        start: string;
        end: string;
        status: string;
    };

    let { buckets = [], periodDays = 90 }: { buckets: Bucket[]; periodDays?: number } = $props();

    const statusColors: Record<string, string> = {
        operational: '#22c55e',
        degraded: '#f59e0b',
        down: '#ef4444',
        unknown: '#d4d4d4',
    };

    let hoveredIndex: number | null = $state(null);
    let tooltipText = $derived.by(() => {
        if (hoveredIndex === null || !buckets[hoveredIndex]) return '';
        const b = buckets[hoveredIndex];
        const start = new Date(b.start).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        const end = new Date(b.end).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        const label = b.status.charAt(0).toUpperCase() + b.status.slice(1);
        return `${start} – ${end}: ${label}`;
    });
</script>

<div class="timeline-container">
    <div class="timeline-header">
        <span class="timeline-label">{periodDays}-day overview</span>
        {#if tooltipText}
            <span class="tooltip">{tooltipText}</span>
        {/if}
    </div>
    <div class="timeline-bar" role="img" aria-label="Health timeline showing {periodDays} days of status history">
        {#each buckets as bucket, i}
            <div
                class="bucket"
                style="flex: 1; background: {statusColors[bucket.status] ?? statusColors.unknown}"
                role="presentation"
                onmouseenter={() => hoveredIndex = i}
                onmouseleave={() => hoveredIndex = null}
            ></div>
        {/each}
    </div>
    <div class="timeline-range">
        <span>{periodDays}d ago</span>
        <span>Now</span>
    </div>
</div>

<style>
    .timeline-container {
        margin-bottom: 1rem;
    }

    .timeline-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 0.35rem;
        min-height: 1.5rem;
    }

    .timeline-label {
        font-size: 0.8rem;
        color: var(--color-font-secondary, #6b6b6b);
        font-weight: 500;
    }

    .tooltip {
        font-size: 0.75rem;
        color: var(--color-font-primary, #222);
        background: var(--color-grey-10, #f5f5f5);
        padding: 0.15rem 0.5rem;
        border-radius: 4px;
        border: 1px solid var(--color-grey-25, #e0e0e0);
    }

    .timeline-bar {
        display: flex;
        height: 2rem;
        border-radius: 6px;
        overflow: hidden;
        gap: 1px;
        background: var(--color-grey-20, #eee);
    }

    .bucket {
        transition: opacity 0.15s ease;
        cursor: pointer;
        min-width: 2px;
    }

    .bucket:hover {
        opacity: 0.7;
    }

    .timeline-range {
        display: flex;
        justify-content: space-between;
        margin-top: 0.25rem;
        font-size: 0.7rem;
        color: var(--color-font-secondary, #999);
    }
</style>
