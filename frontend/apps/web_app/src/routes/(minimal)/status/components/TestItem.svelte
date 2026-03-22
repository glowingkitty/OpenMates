<!--
    TestItem — Single test with status dot, name, status label, and per-test timeline.
    Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import type { TestData, SelectedTimeline } from './types';
	import { tid, fd } from './utils';
	import TimelineBar from './TimelineBar.svelte';

	let {
		test,
		timelinePrefix = 'test',
		isAdmin = false,
		selected = $bindable<SelectedTimeline | null>(null)
	}: {
		test: TestData;
		timelinePrefix?: string;
		isAdmin?: boolean;
		selected?: SelectedTimeline | null;
	} = $props();

	const statusColor = $derived(
		test.status === 'passed' ? '#22c55e' : test.status === 'failed' ? '#ef4444' : 'var(--color-grey-50)'
	);
</script>

<div class="item nested">
	<div class="item-head static">
		<span class="dot xs" style="background:{statusColor}"></span>
		<span class="label mono">{test.name || test.file}</span>
		<span class="slbl" style="color:{statusColor}">{test.status}</span>
		{#if test.last_run}
			<span class="tdate">{fd(test.last_run.slice(0, 10))}</span>
		{/if}
	</div>
	{#if test.history_30d?.length}
		<TimelineBar
			entries={test.history_30d}
			timelineKey={`${timelinePrefix}-${tid(test.file ?? test.name)}`}
			bind:selected
		/>
	{/if}
	{#if isAdmin && test.error}
		<div class="errd">{test.error}</div>
	{/if}
</div>

<style>
	.item.nested { padding: 0.35rem 0; }
	.item-head {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		width: 100%;
		font-size: 0.85rem;
		color: var(--color-font-primary);
		margin-bottom: 0.3rem;
	}
	.dot.xs {
		width: 0.3rem;
		height: 0.3rem;
		border-radius: 50%;
		flex-shrink: 0;
	}
	.label.mono {
		flex: 1;
		font-family: monospace;
		font-size: 0.75rem;
		font-weight: 400;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.slbl {
		font-size: 0.72rem;
		text-transform: capitalize;
		flex-shrink: 0;
	}
	.tdate {
		font-size: 0.68rem;
		color: var(--color-font-secondary);
		flex-shrink: 0;
	}
	.errd {
		font-size: 0.7rem;
		color: var(--color-error);
		background: rgba(239, 68, 68, 0.06);
		padding: 0.2rem 0.5rem;
		border-radius: 4px;
		margin-top: 0.15rem;
		white-space: pre-wrap;
		word-break: break-word;
		max-height: 60px;
		overflow-y: auto;
	}
</style>
