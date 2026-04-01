<!--
	Individual test row with pass/fail status and 30-day timeline (v3).
	Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import type { TestSpec, IntraDayTestRun } from './types';
	import { fetchIntraDay } from './api';
	import UptimeBar from './UptimeBar.svelte';
	import IntraDayPanel from './IntraDayPanel.svelte';

	interface Props {
		spec: TestSpec;
	}

	let { spec }: Props = $props();
	let intraDayDate: string | null = $state(null);
	let intraDayRuns: IntraDayTestRun[] = $state([]);
	let intraDayLoading = $state(false);

	async function handleDayClick(date: string) {
		if (intraDayDate === date) {
			intraDayDate = null;
			return;
		}
		intraDayDate = date;
		intraDayLoading = true;
		try {
			const result = await fetchIntraDay('test', spec.name, date);
			intraDayRuns = result.runs || [];
		} catch {
			intraDayRuns = [];
		} finally {
			intraDayLoading = false;
		}
	}

	// Map test status to DayStatus format for the uptime bar
	let barEntries = $derived(
		spec.timeline_30d.map(d => ({
			date: d.date,
			status: d.status === 'passed' ? 'operational' as const : 'down' as const,
		}))
	);
</script>

<div class="test-row-wrapper">
	<div class="test-row" class:failed={spec.status === 'failed'}>
		<span class="icon">{spec.status === 'passed' ? '✓' : '✗'}</span>
		<span class="name">{spec.name}</span>
		{#if spec.timeline_30d.length}
			<UptimeBar entries={barEntries} onDayClick={handleDayClick} />
		{/if}
		<span class="label-30d">30d</span>
		{#if spec.status === 'failed'}
			<span class="badge-failed" data-testid="badge-failed">FAILED</span>
		{/if}
	</div>

	{#if intraDayDate}
		<IntraDayPanel
			title="{spec.name}.spec"
			date={intraDayDate}
			runs={intraDayRuns}
			loading={intraDayLoading}
		/>
	{/if}
</div>

<style>
	.test-row-wrapper {
		margin-bottom: 0.1rem;
	}
	.test-row {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		padding: 0.2rem 0 0.2rem 0.5rem;
		font-size: 0.78rem;
	}
	.icon {
		font-size: 0.8rem;
		width: 1rem;
		flex-shrink: 0;
	}
	.test-row:not(.failed) .icon {
		color: var(--color-success, #22c55e);
	}
	.test-row.failed .icon {
		color: var(--color-error, #ef4444);
	}
	.name {
		min-width: 10rem;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		color: var(--color-font-primary);
	}
	.label-30d {
		font-size: 0.65rem;
		color: var(--color-font-secondary);
		min-width: 1.5rem;
	}
	.badge-failed {
		font-size: 0.65rem;
		font-weight: 700;
		color: var(--color-error, #ef4444);
		background: rgba(239, 68, 68, 0.1);
		padding: 0.05rem 0.3rem;
		border-radius: 3px;
	}
</style>
