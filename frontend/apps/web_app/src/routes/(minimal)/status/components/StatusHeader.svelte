<!--
    StatusHeader — Overall status badge and last-updated timestamp.
    Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import { ft } from './utils';
	import { STATUS_LABELS } from './utils';

	let {
		overallStatus,
		lastUpdated
	}: {
		overallStatus: string;
		lastUpdated: string;
	} = $props();
</script>

<header>
	<h1>OpenMates Status</h1>
	<div class="badge" data-s={overallStatus}>
		<span class="bdot"></span>{STATUS_LABELS[overallStatus] ?? STATUS_LABELS.unknown}
	</div>
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
	.upd {
		margin: 0.4rem 0 0;
		font-size: 0.75rem;
		color: var(--color-font-secondary);
	}
</style>
