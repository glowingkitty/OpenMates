<!--
    StatusBadge — Overall status indicator for the status page.
    Shows a colored pill with status text (Operational / Degraded / Down).
    Architecture: See docs/architecture/status-page.md
    Tests: N/A
-->
<script lang="ts">
    type StatusLevel = 'operational' | 'degraded' | 'down' | 'unknown';

    let { status = 'unknown' }: { status: StatusLevel } = $props();

    const labels: Record<StatusLevel, string> = {
        operational: 'All Systems Operational',
        degraded: 'Partial Degradation',
        down: 'Major Outage',
        unknown: 'Status Unknown',
    };
</script>

<div class="status-badge" data-status={status}>
    <span class="dot"></span>
    <span class="label">{labels[status] ?? labels.unknown}</span>
</div>

<style>
    .status-badge {
        display: inline-flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.4rem 0.85rem;
        border-radius: 999px;
        font-size: var(--font-size-p, 0.875rem);
        font-weight: 500;
        background: var(--color-grey-10, #f5f5f5);
        border: 1px solid var(--color-grey-25, #e0e0e0);
    }

    .dot {
        width: 0.5rem;
        height: 0.5rem;
        border-radius: 50%;
        flex-shrink: 0;
    }

    [data-status='operational'] .dot {
        background: #22c55e;
        box-shadow: 0 0 6px rgba(34, 197, 94, 0.4);
    }
    [data-status='operational'] {
        background: rgba(34, 197, 94, 0.08);
        border-color: rgba(34, 197, 94, 0.25);
        color: #15803d;
    }

    [data-status='degraded'] .dot {
        background: #f59e0b;
        box-shadow: 0 0 6px rgba(245, 158, 11, 0.4);
    }
    [data-status='degraded'] {
        background: rgba(245, 158, 11, 0.08);
        border-color: rgba(245, 158, 11, 0.25);
        color: #92400e;
    }

    [data-status='down'] .dot {
        background: #ef4444;
        box-shadow: 0 0 6px rgba(239, 68, 68, 0.4);
    }
    [data-status='down'] {
        background: rgba(239, 68, 68, 0.08);
        border-color: rgba(239, 68, 68, 0.25);
        color: #991b1b;
    }

    [data-status='unknown'] .dot {
        background: var(--color-grey-50, #9e9e9e);
    }
</style>
