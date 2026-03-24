<!--
    StatusHeader — Overall status badge and last-updated timestamp.
    Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import type { TimelineEntry } from './types';
	import { ft, uptimePct, fmtUptime } from './utils';
	import { STATUS_LABELS } from './utils';

	let {
		overallStatus,
		lastUpdated,
		overallTimeline
	}: {
		overallStatus: string;
		lastUpdated: string;
		overallTimeline?: TimelineEntry[];
	} = $props();

	const uptime = $derived(uptimePct(overallTimeline ?? []));
</script>

<header>
	<h1>OpenMates Status</h1>
	<div class="badge" data-s={overallStatus}>
		<span class="bdot"></span>{STATUS_LABELS[overallStatus] ?? STATUS_LABELS.unknown}
	</div>
	{#if uptime !== null}
		<p class="uptime" data-testid="overall-uptime">{fmtUptime(uptime)} uptime <span class="uptime-period">last 30 days</span></p>
	{/if}
	<p class="upd">Updated {ft(lastUpdated)}</p>
</header>

<style>
	header {
		text-align: center;
		padding: 2rem 0 0.5rem;
	}
	header h1 {
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
		border: 1px solid var(--color-grey-25);
		background: var(--color-grey-10);
	}
	.bdot {
		width: 0.45rem;
		height: 0.45rem;
		border-radius: 50%;
	}
	[data-s='operational'] .bdot { background: #22c55e; }
	[data-s='operational'] { color: #22c55e; }
	[data-s='degraded'] .bdot { background: #f59e0b; }
	[data-s='degraded'] { color: #f59e0b; }
	[data-s='down'] .bdot { background: #ef4444; }
	[data-s='down'] { color: #ef4444; }
	.uptime {
		margin: 0.5rem 0 0;
		font-size: 1.1rem;
		font-weight: 600;
		color: var(--color-font-primary);
	}
	.uptime-period {
		font-weight: 400;
		font-size: 0.8rem;
		color: var(--color-font-secondary);
	}
	.upd {
		margin: 0.4rem 0 0;
		font-size: 0.75rem;
		color: var(--color-font-secondary);
	}
</style>
