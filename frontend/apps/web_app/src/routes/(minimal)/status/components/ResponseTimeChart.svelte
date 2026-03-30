<!--
	Response time line chart for providers (v3).
	Renders a simple SVG chart showing 7-day response time history.
	Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import type { ResponseTimePoint } from './types';

	interface Props {
		data: ResponseTimePoint[];
		serviceName: string;
	}

	let { data, serviceName }: Props = $props();

	const WIDTH = 500;
	const HEIGHT = 120;
	const PADDING = { top: 10, right: 10, bottom: 25, left: 40 };
	const chartW = WIDTH - PADDING.left - PADDING.right;
	const chartH = HEIGHT - PADDING.top - PADDING.bottom;

	let points = $derived.by(() => {
		if (!data.length) return { path: '', maxMs: 0, avgMs: 0, yLabels: [] as number[], xLabels: [] as { x: number; label: string }[] };

		const values = data.map(d => d.avg_ms);
		const maxMs = Math.max(...values, 1);
		const avgMs = Math.round(values.reduce((a, b) => a + b, 0) / values.length);

		const coords = data.map((d, i) => {
			const x = PADDING.left + (i / Math.max(data.length - 1, 1)) * chartW;
			const y = PADDING.top + chartH - (d.avg_ms / maxMs) * chartH;
			return { x, y };
		});

		const path = coords.map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x},${c.y}`).join(' ');

		// Y-axis labels
		const yLabels = [0, Math.round(maxMs / 2), Math.round(maxMs)];

		// X-axis labels (show a few date labels)
		const xLabels: { x: number; label: string }[] = [];
		const step = Math.max(1, Math.floor(data.length / 5));
		for (let i = 0; i < data.length; i += step) {
			const ts = data[i].timestamp;
			const dateStr = ts.slice(5, 10); // MM-DD
			xLabels.push({ x: coords[i].x, label: dateStr });
		}

		return { path, maxMs, avgMs, yLabels, xLabels };
	});
</script>

<div class="chart-container">
	<div class="chart-header">
		<span>{serviceName} — Response Time (7d)</span>
		<span class="avg">avg: {points.avgMs}ms</span>
	</div>
	{#if data.length > 1}
		<svg viewBox="0 0 {WIDTH} {HEIGHT}" class="chart" data-testid="response-time-chart">
			<!-- Y axis labels -->
			{#each points.yLabels as label, i}
				{@const y = PADDING.top + chartH - (i / (points.yLabels.length - 1)) * chartH}
				<text x={PADDING.left - 5} {y} class="axis-label" text-anchor="end" dominant-baseline="middle">
					{label}
				</text>
				<line x1={PADDING.left} x2={PADDING.left + chartW} y1={y} y2={y} class="grid-line" />
			{/each}

			<!-- Line -->
			<path d={points.path} fill="none" stroke="var(--color-primary, #3b82f6)" stroke-width="1.5" />

			<!-- X axis labels -->
			{#each points.xLabels as xl}
				<text x={xl.x} y={HEIGHT - 5} class="axis-label" text-anchor="middle">{xl.label}</text>
			{/each}
		</svg>
	{:else}
		<div class="no-data">Not enough data</div>
	{/if}
</div>

<style>
	.chart-container {
		padding: 0.5rem 0.75rem;
		background: var(--color-grey-5, #f9fafb);
		border: 1px solid var(--color-grey-20);
		border-radius: 8px;
		margin-top: 0.25rem;
	}
	.chart-header {
		display: flex;
		justify-content: space-between;
		font-size: 0.75rem;
		font-weight: 500;
		color: var(--color-font-primary);
		margin-bottom: 0.25rem;
	}
	.avg {
		color: var(--color-font-secondary);
	}
	.chart {
		width: 100%;
		height: auto;
	}
	.axis-label {
		font-size: 9px;
		fill: var(--color-font-secondary, #6b7280);
	}
	.grid-line {
		stroke: var(--color-grey-15, #e5e7eb);
		stroke-width: 0.5;
	}
	.no-data {
		color: var(--color-font-secondary);
		font-size: 0.75rem;
		font-style: italic;
		padding: 0.5rem 0;
	}
</style>
