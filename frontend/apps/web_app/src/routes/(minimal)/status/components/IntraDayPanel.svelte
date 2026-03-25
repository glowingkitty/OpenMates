<!--
	Intra-day drill-down panel (v3).
	Shows individual health checks or test runs for a specific day.
	Shared between service rows and test rows.
	Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import type { IntraDayCheck, IntraDayTestRun } from './types';
	import { statusColor } from './utils';

	interface Props {
		title: string;
		date: string;
		checks?: IntraDayCheck[];
		runs?: IntraDayTestRun[];
		loading?: boolean;
	}

	let { title, date, checks, runs, loading = false }: Props = $props();

	function statusIcon(status: string): string {
		if (status === 'operational' || status === 'passed') return '●';
		if (status === 'degraded') return '▲';
		return '✕';
	}
</script>

<div class="panel">
	<div class="panel-header">{title} — {date}</div>
	{#if loading}
		<div class="loading">Loading...</div>
	{:else if checks?.length}
		<div class="timeline-visual">
			{#each checks as check}
				<span class="dot" style:color={statusColor(check.status)} title="{check.time}: {check.status}">
					{statusIcon(check.status)}
				</span>
			{/each}
		</div>
		<div class="entries">
			{#each checks as check}
				<div class="entry">
					<span class="time">{check.time}</span>
					<span class="icon" style:color={statusColor(check.status)}>{statusIcon(check.status)}</span>
					<span class="status">{check.status}</span>
					{#if check.response_time_ms !== null}
						<span class="rt">({check.response_time_ms}ms)</span>
					{/if}
					{#if check.error}
						<span class="error">— {check.error}</span>
					{/if}
				</div>
			{/each}
		</div>
	{:else if runs?.length}
		<div class="entries">
			{#each runs as run}
				<div class="entry">
					<span class="time">{run.time}</span>
					<span class="icon" style:color={statusColor(run.status === 'passed' ? 'operational' : 'down')}>
						{run.status === 'passed' ? '✓' : '✗'}
					</span>
					<span class="status" class:failed={run.status === 'failed'}>
						{run.status === 'passed' ? 'PASSED' : 'FAILED'}
					</span>
					{#if run.duration_s}
						<span class="rt">({run.duration_s}s)</span>
					{/if}
					{#if run.error}
						<div class="error-detail">{run.error}</div>
					{/if}
				</div>
			{/each}
		</div>
	{:else}
		<div class="empty">No data for this day.</div>
	{/if}
</div>

<style>
	.panel {
		background: var(--color-grey-5, #f9fafb);
		border: 1px solid var(--color-grey-20);
		border-radius: 8px;
		padding: 0.75rem;
		margin-top: 0.5rem;
		font-size: 0.78rem;
	}
	.panel-header {
		font-weight: 600;
		margin-bottom: 0.5rem;
		color: var(--color-font-primary);
	}
	.loading, .empty {
		color: var(--color-font-secondary);
		font-style: italic;
	}
	.timeline-visual {
		display: flex;
		gap: 0.5rem;
		margin-bottom: 0.5rem;
		font-size: 0.9rem;
	}
	.entries {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}
	.entry {
		display: flex;
		align-items: baseline;
		gap: 0.4rem;
		flex-wrap: wrap;
	}
	.time {
		font-family: monospace;
		color: var(--color-font-secondary);
		min-width: 3.5rem;
	}
	.icon {
		font-size: 0.85rem;
	}
	.status {
		color: var(--color-font-primary);
	}
	.status.failed {
		color: var(--color-error, #ef4444);
		font-weight: 600;
	}
	.rt {
		color: var(--color-font-secondary);
		font-size: 0.72rem;
	}
	.error {
		color: var(--color-font-secondary);
		font-size: 0.72rem;
	}
	.error-detail {
		width: 100%;
		padding-left: 4.5rem;
		color: var(--color-error, #ef4444);
		font-size: 0.72rem;
		margin-top: 0.1rem;
	}
</style>
