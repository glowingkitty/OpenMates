<!--
	Reusable uptime bar component (v3).
	Renders a horizontal bar of day segments with hover tooltips and click drill-down.
	Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import type { DayStatus } from './types';
	import { statusColor } from './utils';

	interface Props {
		entries: DayStatus[];
		onDayClick?: (date: string) => void;
	}

	let { entries, onDayClick }: Props = $props();
	let hoveredIndex: number | null = $state(null);
</script>

<div class="bar-container">
	<div class="bar" role="img" aria-label="Uptime history">
		{#each entries as entry, i}
			<button
				class="segment"
				style:background={statusColor(entry.status)}
				onmouseenter={() => hoveredIndex = i}
				onmouseleave={() => hoveredIndex = null}
				onclick={() => onDayClick?.(entry.date)}
				title="{entry.date} — {entry.status}"
				aria-label="{entry.date}: {entry.status}"
			></button>
		{/each}
	</div>
	{#if hoveredIndex !== null && entries[hoveredIndex]}
		<div class="tooltip">
			{entries[hoveredIndex].date} — {entries[hoveredIndex].status}
		</div>
	{/if}
</div>

<style>
	.bar-container {
		position: relative;
		flex: 1;
		min-width: 0;
	}
	.bar {
		display: flex;
		gap: 1px;
		height: 1.1rem;
		border-radius: 3px;
		overflow: hidden;
	}
	.segment {
		flex: 1;
		min-width: 0;
		border: none;
		padding: 0;
		cursor: pointer;
		opacity: 0.85;
		transition: opacity 0.15s;
	}
	.segment:hover {
		opacity: 1;
	}
	.tooltip {
		position: absolute;
		top: -1.8rem;
		left: 50%;
		transform: translateX(-50%);
		background: var(--color-grey-90, #1f2937);
		color: #fff;
		font-size: 0.7rem;
		padding: 0.15rem 0.4rem;
		border-radius: 4px;
		white-space: nowrap;
		pointer-events: none;
		z-index: 10;
	}
</style>
