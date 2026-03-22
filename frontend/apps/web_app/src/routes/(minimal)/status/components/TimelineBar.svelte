<!--
    TimelineBar — Reusable 30-day timeline bar with interactive segment selection.
    Replaces ~10 duplicated timeline rendering blocks across the status page.
    Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import type { TimelineEntry, SelectedTimeline } from './types';
	import { timelineColor, timelineTitle } from './utils';

	let {
		entries,
		timelineKey,
		testid = '',
		selected = $bindable<SelectedTimeline | null>(null),
		showLabels = false
	}: {
		entries: TimelineEntry[];
		timelineKey: string;
		testid?: string;
		selected?: SelectedTimeline | null;
		showLabels?: boolean;
	} = $props();

	function select(entry: TimelineEntry) {
		selected = {
			key: timelineKey,
			date: entry.date,
			text: timelineTitle(entry)
		};
	}

	function isSelected(entry: TimelineEntry): boolean {
		return selected?.key === timelineKey && selected?.date === entry.date;
	}
</script>

{#if entries?.length}
	<div class="tl" data-testid={testid || `status-timeline-${timelineKey}`}>
		{#each entries as d}
			<button
				type="button"
				class="seg"
				class:selected={isSelected(d)}
				style="background:{timelineColor(d)}"
				title={timelineTitle(d)}
				aria-label={timelineTitle(d)}
				onclick={() => select(d)}
				onfocus={() => select(d)}
			></button>
		{/each}
	</div>
	{#if selected?.key === timelineKey}
		<div class="tl-detail" data-testid="status-timeline-detail">{selected.text}</div>
	{/if}
	{#if showLabels}
		<div class="tl-lab"><span>30d ago</span><span>Today</span></div>
	{/if}
{/if}

<style>
	.tl {
		display: flex;
		gap: 1px;
		height: 1.1rem;
		border-radius: 4px;
		overflow: hidden;
		background: var(--color-grey-20);
		width: 100%;
	}
	.seg {
		flex: 1;
		min-width: 2px;
		border: none;
		padding: 0;
		margin: 0;
		cursor: pointer;
	}
	.seg.selected {
		outline: 2px solid var(--color-font-primary);
		outline-offset: -2px;
	}
	.tl-detail {
		margin-top: 0.35rem;
		font-size: 0.72rem;
		color: var(--color-font-secondary);
		font-variant-numeric: tabular-nums;
	}
	.tl-lab {
		display: flex;
		justify-content: space-between;
		font-size: 0.68rem;
		color: var(--color-font-secondary);
		margin-top: 0.15rem;
	}
</style>
