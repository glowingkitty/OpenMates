<!--
    ServiceGroupCard — Expandable card showing a service group's health.
    Shows group name + status color. Click expands to show individual services.
    Admin view shows error messages + response times; non-admin shows status dots only.
    Architecture: See docs/architecture/status-page.md
    Tests: N/A
-->
<script lang="ts">
    type ServiceDetail = {
        id: string;
        name: string;
        status: string;
        error_message?: string | null;
        response_time_ms?: Record<string, number> | null;
        last_check?: string | null;
    };

    type GroupSummary = {
        group_name: string;
        display_name: string;
        status: string;
        service_count: number;
        services?: ServiceDetail[];
    };

    let {
        group,
        isAdmin = false,
        onExpand,
    }: {
        group: GroupSummary;
        isAdmin?: boolean;
        onExpand?: (groupName: string) => void;
    } = $props();

    let expanded = $state(false);
    let detail: ServiceDetail[] | null = $state(null);
    let loading = $state(false);

    const statusColors: Record<string, string> = {
        operational: '#22c55e',
        degraded: '#f59e0b',
        down: '#ef4444',
        unknown: '#d4d4d4',
    };

    function toggle() {
        expanded = !expanded;
        if (expanded && !detail && onExpand) {
            loading = true;
            onExpand(group.group_name);
        }
    }

    // Allow parent to inject detail data after fetch
    export function setDetail(services: ServiceDetail[]) {
        detail = services;
        loading = false;
    }
</script>

<div class="group-card" data-status={group.status}>
    <button class="group-header" onclick={toggle} aria-expanded={expanded}>
        <div class="header-left">
            <span class="status-dot" style="background: {statusColors[group.status] ?? statusColors.unknown}"></span>
            <span class="group-name">{group.display_name}</span>
            <span class="service-count">({group.service_count})</span>
        </div>
        <span class="chevron" class:rotated={expanded}>&#9662;</span>
    </button>

    {#if expanded}
        <div class="group-body">
            {#if loading}
                <p class="loading-text">Loading...</p>
            {:else if detail && detail.length > 0}
                <ul class="service-list">
                    {#each detail as service}
                        <li class="service-row">
                            <span class="service-dot" style="background: {statusColors[service.status] ?? statusColors.unknown}"></span>
                            <span class="service-name">{service.name}</span>
                            <span class="service-status">{service.status}</span>
                            {#if isAdmin && service.error_message}
                                <span class="error-msg">{service.error_message}</span>
                            {/if}
                        </li>
                    {/each}
                </ul>
            {:else if group.services && group.services.length > 0}
                <!-- Inline services from summary (non-expanded detail fetch) -->
                <ul class="service-list">
                    {#each group.services as service}
                        <li class="service-row">
                            <span class="service-dot" style="background: {statusColors[service.status] ?? statusColors.unknown}"></span>
                            <span class="service-name">{service.name}</span>
                            <span class="service-status">{service.status}</span>
                        </li>
                    {/each}
                </ul>
            {:else}
                <p class="loading-text">No service data available</p>
            {/if}
        </div>
    {/if}
</div>

<style>
    .group-card {
        background: var(--color-grey-0, #fff);
        border: 1px solid var(--color-grey-25, #e0e0e0);
        border-radius: 10px;
        overflow: hidden;
    }

    .group-header {
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

    .group-header:hover {
        background: var(--color-grey-5, #fafafa);
    }

    .header-left {
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }

    .status-dot {
        width: 0.5rem;
        height: 0.5rem;
        border-radius: 50%;
        flex-shrink: 0;
    }

    .group-name {
        font-weight: 600;
    }

    .service-count {
        color: var(--color-font-secondary, #999);
        font-size: 0.8rem;
    }

    .chevron {
        font-size: 0.75rem;
        color: var(--color-font-secondary, #999);
        transition: transform 0.2s ease;
    }

    .chevron.rotated {
        transform: rotate(180deg);
    }

    .group-body {
        padding: 0 1rem 0.75rem;
        border-top: 1px solid var(--color-grey-15, #eee);
    }

    .service-list {
        list-style: none;
        margin: 0;
        padding: 0;
    }

    .service-row {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.4rem 0;
        font-size: 0.82rem;
    }

    .service-row + .service-row {
        border-top: 1px solid var(--color-grey-10, #f5f5f5);
    }

    .service-dot {
        width: 0.4rem;
        height: 0.4rem;
        border-radius: 50%;
        flex-shrink: 0;
    }

    .service-name {
        flex: 1;
        color: var(--color-font-primary, #222);
    }

    .service-status {
        font-size: 0.75rem;
        color: var(--color-font-secondary, #999);
        text-transform: capitalize;
    }

    .error-msg {
        font-size: 0.72rem;
        color: var(--color-error, #e74c3c);
        max-width: 300px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .loading-text {
        font-size: 0.82rem;
        color: var(--color-font-secondary, #999);
        padding: 0.5rem 0;
        margin: 0;
    }
</style>
