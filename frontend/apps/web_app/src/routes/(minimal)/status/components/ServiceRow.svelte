<!--
	Individual service row with status, uptime bar, and expandable response time chart (v3).
	Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import type { Service, IntraDayCheck } from './types';
	import { statusColor, statusLabel } from './utils';
	import { fetchIntraDay } from './api';
	import UptimeBar from './UptimeBar.svelte';
	import ResponseTimeChart from './ResponseTimeChart.svelte';
	import IntraDayPanel from './IntraDayPanel.svelte';

	interface Props {
		service: Service;
	}

	let { service }: Props = $props();
	let expanded = $state(false);
	let intraDayDate: string | null = $state(null);
	let intraDayChecks: IntraDayCheck[] = $state([]);
	let intraDayLoading = $state(false);

	async function handleDayClick(date: string) {
		if (intraDayDate === date) {
			intraDayDate = null;
			return;
		}
		intraDayDate = date;
		intraDayLoading = true;
		try {
			const result = await fetchIntraDay('service', service.id, date);
			intraDayChecks = result.checks || [];
		} catch {
			intraDayChecks = [];
		} finally {
			intraDayLoading = false;
		}
	}
</script>

<div class="row-wrapper">
	<button class="row" onclick={() => { if (service.response_times_7d) expanded = !expanded; }}>
		<span class="dot" style:background={statusColor(service.status)}></span>
		<span class="name" data-testid="service-name">{service.name}</span>
		<span class="status-text" style:color={statusColor(service.status)}>{statusLabel(service.status)}</span>
		<UptimeBar entries={service.uptime_90d} onDayClick={handleDayClick} />
		<span class="pct">{service.uptime_pct}%</span>
		{#if service.response_times_7d}
			<span class="expand-icon">{expanded ? '▾' : '▸'}</span>
		{/if}
	</button>

	{#if expanded && service.response_times_7d}
		<ResponseTimeChart data={service.response_times_7d} serviceName={service.name} />
	{/if}

	{#if intraDayDate}
		<IntraDayPanel
			title={service.name}
			date={intraDayDate}
			checks={intraDayChecks}
			loading={intraDayLoading}
		/>
	{/if}
</div>

<style>
	.row-wrapper {
		margin-bottom: 0.15rem;
	}
	.row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		width: 100%;
		padding: 0.3rem 0;
		background: none;
		border: none;
		cursor: pointer;
		font-size: 0.82rem;
		color: var(--color-font-primary);
		text-align: left;
	}
	.row:hover {
		background: var(--color-grey-5, #f9fafb);
		border-radius: 4px;
	}
	.dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
	}
	.name {
		min-width: 8rem;
		font-weight: 500;
		white-space: nowrap;
	}
	.status-text {
		min-width: 6rem;
		font-size: 0.75rem;
		white-space: nowrap;
	}
	.pct {
		min-width: 3.5rem;
		text-align: right;
		font-size: 0.75rem;
		color: var(--color-font-secondary);
		font-variant-numeric: tabular-nums;
	}
	.expand-icon {
		font-size: 0.7rem;
		color: var(--color-font-secondary);
		width: 1rem;
		text-align: center;
	}
</style>
