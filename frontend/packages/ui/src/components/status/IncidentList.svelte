<!--
    IncidentList — Shows incident count with expandable detail.
    Admin view shows error messages + durations.
    Non-admin shows timestamps + status transitions only.
    Architecture: See docs/architecture/status-page.md
    Tests: N/A
-->
<script lang="ts">
    type IncidentEvent = {
        service_type?: string;
        service_id?: string;
        previous_status?: string;
        new_status?: string;
        created_at?: string;
        error_message?: string;
        duration_seconds?: number;
    };

    let {
        totalIncidents = 0,
        isAdmin = false,
        onExpand,
    }: {
        totalIncidents: number;
        isAdmin?: boolean;
        onExpand?: () => void;
    } = $props();

    let expanded = $state(false);
    let events: IncidentEvent[] | null = $state(null);
    let loading = $state(false);

    function toggle() {
        expanded = !expanded;
        if (expanded && !events && onExpand) {
            loading = true;
            onExpand();
        }
    }

    export function setEvents(data: IncidentEvent[]) {
        events = data;
        loading = false;
    }

    function formatDate(iso: string | undefined): string {
        if (!iso) return '';
        try {
            return new Date(iso).toLocaleDateString('en-US', {
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
            });
        } catch {
            return iso;
        }
    }

    function formatDuration(seconds: number | undefined): string {
        if (!seconds) return '';
        if (seconds < 60) return `${seconds}s`;
        if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
        return `${(seconds / 3600).toFixed(1)}h`;
    }

    const statusColors: Record<string, string> = {
        operational: '#22c55e',
        degraded: '#f59e0b',
        down: '#ef4444',
        unknown: '#d4d4d4',
    };
</script>

<div class="incidents-card">
    <button class="incidents-header" onclick={toggle} aria-expanded={expanded}>
        <div class="header-left">
            <span class="incidents-label">Incidents (30d)</span>
            <span class="incidents-count" class:has-incidents={totalIncidents > 0}>{totalIncidents}</span>
        </div>
        <span class="chevron" class:rotated={expanded}>&#9662;</span>
    </button>

    {#if expanded}
        <div class="incidents-body">
            {#if loading}
                <p class="loading-text">Loading incident history...</p>
            {:else if events && events.length > 0}
                <ul class="event-list">
                    {#each events as event}
                        <li class="event-row">
                            <span class="event-dot" style="background: {statusColors[event.new_status ?? 'unknown'] ?? statusColors.unknown}"></span>
                            <span class="event-service">{event.service_id ?? 'unknown'}</span>
                            <span class="event-transition">{event.previous_status ?? '?'} → {event.new_status ?? '?'}</span>
                            <span class="event-time">{formatDate(event.created_at)}</span>
                            {#if isAdmin && event.duration_seconds}
                                <span class="event-duration">{formatDuration(event.duration_seconds)}</span>
                            {/if}
                            {#if isAdmin && event.error_message}
                                <div class="event-error">{event.error_message}</div>
                            {/if}
                        </li>
                    {/each}
                </ul>
            {:else}
                <p class="loading-text">No incidents in the last 30 days</p>
            {/if}
        </div>
    {/if}
</div>

<style>
    .incidents-card {
        background: var(--color-grey-0, #fff);
        border: 1px solid var(--color-grey-25, #e0e0e0);
        border-radius: 10px;
        overflow: hidden;
    }

    .incidents-header {
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

    .incidents-header:hover {
        background: var(--color-grey-5, #fafafa);
    }

    .header-left {
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }

    .incidents-label {
        font-weight: 600;
    }

    .incidents-count {
        font-size: 0.78rem;
        padding: 0.1rem 0.45rem;
        border-radius: 999px;
        background: var(--color-grey-10, #f5f5f5);
        color: var(--color-font-secondary, #999);
        font-variant-numeric: tabular-nums;
    }

    .incidents-count.has-incidents {
        background: rgba(239, 68, 68, 0.1);
        color: #ef4444;
    }

    .chevron {
        font-size: 0.75rem;
        color: var(--color-font-secondary, #999);
        transition: transform 0.2s ease;
    }

    .chevron.rotated {
        transform: rotate(180deg);
    }

    .incidents-body {
        padding: 0 1rem 0.75rem;
        border-top: 1px solid var(--color-grey-15, #eee);
        max-height: 400px;
        overflow-y: auto;
    }

    .event-list {
        list-style: none;
        margin: 0;
        padding: 0;
    }

    .event-row {
        display: flex;
        align-items: flex-start;
        gap: 0.5rem;
        padding: 0.4rem 0;
        font-size: 0.78rem;
        flex-wrap: wrap;
    }

    .event-row + .event-row {
        border-top: 1px solid var(--color-grey-10, #f5f5f5);
    }

    .event-dot {
        width: 0.35rem;
        height: 0.35rem;
        border-radius: 50%;
        flex-shrink: 0;
        margin-top: 0.35rem;
    }

    .event-service {
        font-weight: 500;
        color: var(--color-font-primary, #222);
    }

    .event-transition {
        color: var(--color-font-secondary, #999);
        font-size: 0.72rem;
    }

    .event-time {
        color: var(--color-font-secondary, #999);
        font-size: 0.72rem;
        margin-left: auto;
    }

    .event-duration {
        font-size: 0.7rem;
        color: #f59e0b;
    }

    .event-error {
        width: 100%;
        font-size: 0.72rem;
        color: var(--color-error, #e74c3c);
        background: rgba(239, 68, 68, 0.05);
        padding: 0.25rem 0.5rem;
        border-radius: 4px;
        margin-top: 0.1rem;
        word-break: break-word;
    }

    .loading-text {
        font-size: 0.82rem;
        color: var(--color-font-secondary, #999);
        padding: 0.5rem 0;
        margin: 0;
    }
</style>
