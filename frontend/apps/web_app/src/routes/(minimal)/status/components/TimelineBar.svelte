<!--
    TimelineBar — Reusable 30-day timeline bar with interactive segment selection.
    When a day has multiple test runs, clicking it shows an intra-day sub-timeline.
    Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import type { TimelineEntry, SelectedTimeline, IntraDayRun } from './types';
	import { timelineColor, timelineTitle, fd, ft, rc } from './utils';
	import { fetchIntraDayRuns } from './api';

	let {
		entries,
		timelineKey,
		testid = '',
		selected = $bindable<SelectedTimeline | null>(null),
		showLabels = false,
		enableIntraDay = false
	}: {
		entries: TimelineEntry[];
		timelineKey: string;
		testid?: string;
		selected?: SelectedTimeline | null;
		showLabels?: boolean;
		enableIntraDay?: boolean;
	} = $props();

	let intraDayRuns: IntraDayRun[] | null = $state(null);
	let intraDayDate: string | null = $state(null);
	let intraDayLoading = $state(false);
	let selectedRunId: string | null = $state(null);

	function select(entry: TimelineEntry) {
		selected = {
			key: timelineKey,
			date: entry.date,
			text: timelineTitle(entry)
		};
		// Reset intra-day when selecting a different date or different timeline
		if (intraDayDate !== entry.date) {
			intraDayRuns = null;
			intraDayDate = null;
			selectedRunId = null;
		}
	}

	function isSelected(entry: TimelineEntry): boolean {
		return selected?.key === timelineKey && selected?.date === entry.date;
	}

	async function loadIntraDay(date: string) {
		if (intraDayDate === date && intraDayRuns !== null) {
			// Toggle off
			intraDayRuns = null;
			intraDayDate = null;
			selectedRunId = null;
			return;
		}
		intraDayLoading = true;
		intraDayDate = date;
		try {
			const res = await fetchIntraDayRuns(date);
			intraDayRuns = res.runs;
		} catch (e) {
			console.error('[STATUS] Failed to load intra-day runs', e);
			intraDayRuns = [];
		} finally {
			intraDayLoading = false;
		}
	}

	function handleSegmentClick(entry: TimelineEntry) {
		select(entry);
		if (enableIntraDay && entry.has_run !== false) {
			loadIntraDay(entry.date);
		}
	}

	function runColor(run: IntraDayRun): string {
		if (run.summary.total === 0) return 'var(--color-grey-40)';
		const rate = Math.round((run.summary.passed / run.summary.total) * 100);
		return rc(rate);
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
				onclick={() => handleSegmentClick(d)}
				onfocus={() => select(d)}
			></button>
		{/each}
	</div>
	{#if selected?.key === timelineKey}
		<div class="tl-detail" data-testid="status-timeline-detail">
			{selected.text}
			{#if enableIntraDay && selected.date && !intraDayRuns && !intraDayLoading}
				<button class="expand-btn" onclick={() => loadIntraDay(selected?.date ?? '')}>
					Show all runs
				</button>
			{/if}
		</div>
	{/if}

	<!-- Intra-day sub-timeline -->
	{#if intraDayLoading}
		<div class="intra-day">
			<span class="intra-label">Loading runs...</span>
		</div>
	{:else if intraDayRuns !== null && intraDayDate}
		{#if intraDayRuns.length <= 1}
			<div class="intra-day">
				<span class="intra-label">{fd(intraDayDate)}: 1 run</span>
			</div>
		{:else}
			<div class="intra-day">
				<span class="intra-label">{fd(intraDayDate)}: {intraDayRuns.length} runs</span>
				<div class="intra-tl">
					{#each intraDayRuns as run}
						{@const rate = run.summary.total > 0 ? Math.round((run.summary.passed / run.summary.total) * 100) : 0}
						<button
							type="button"
							class="intra-seg"
							class:selected={selectedRunId === run.run_id}
							style="background:{runColor(run)}"
							title="{ft(run.timestamp)}: {run.summary.passed}/{run.summary.total} passed ({rate}%)"
							aria-label="{ft(run.timestamp)}: {run.summary.passed}/{run.summary.total} passed"
							onclick={() => (selectedRunId = selectedRunId === run.run_id ? null : run.run_id)}
						></button>
					{/each}
				</div>
				{#if selectedRunId}
					{@const run = intraDayRuns.find((r) => r.run_id === selectedRunId)}
					{#if run}
						{@const rate = run.summary.total > 0 ? Math.round((run.summary.passed / run.summary.total) * 100) : 0}
						<div class="intra-detail">
							<span class="intra-time">{ft(run.timestamp)}</span>
							<span class="intra-counts">
								{run.summary.passed}/{run.summary.total} passed
								{#if run.summary.failed > 0}
									<span class="intra-fail">{run.summary.failed} failed</span>
								{/if}
							</span>
							<span class="intra-rate" style="color:{rc(rate)}">{rate}%</span>
							{#if run.git_sha}
								<span class="intra-sha">{run.git_sha.slice(0, 7)}</span>
							{/if}
							{#if run.duration_seconds}
								<span class="intra-dur">{Math.round(run.duration_seconds)}s</span>
							{/if}
						</div>
					{/if}
				{/if}
			</div>
		{/if}
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
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
	.tl-lab {
		display: flex;
		justify-content: space-between;
		font-size: 0.68rem;
		color: var(--color-font-secondary);
		margin-top: 0.15rem;
	}
	.expand-btn {
		background: none;
		border: 1px solid var(--color-grey-30);
		border-radius: 4px;
		padding: 0.1rem 0.4rem;
		font-size: 0.68rem;
		color: var(--color-font-secondary);
		cursor: pointer;
		font-family: inherit;
	}
	.expand-btn:hover {
		background: var(--color-grey-10);
	}

	/* Intra-day sub-timeline */
	.intra-day {
		margin-top: 0.35rem;
		padding: 0.35rem 0.5rem;
		background: var(--color-grey-10);
		border-radius: 6px;
		border: 1px solid var(--color-grey-20);
	}
	.intra-label {
		font-size: 0.7rem;
		color: var(--color-font-secondary);
		font-weight: 500;
		display: block;
		margin-bottom: 0.25rem;
	}
	.intra-tl {
		display: flex;
		gap: 2px;
		height: 1.3rem;
		border-radius: 4px;
		overflow: hidden;
		background: var(--color-grey-20);
	}
	.intra-seg {
		flex: 1;
		min-width: 8px;
		border: none;
		padding: 0;
		margin: 0;
		cursor: pointer;
		border-radius: 2px;
	}
	.intra-seg.selected {
		outline: 2px solid var(--color-font-primary);
		outline-offset: -2px;
	}
	.intra-detail {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-top: 0.3rem;
		font-size: 0.72rem;
		color: var(--color-font-secondary);
		font-variant-numeric: tabular-nums;
	}
	.intra-time {
		font-weight: 600;
		color: var(--color-font-primary);
	}
	.intra-counts {
		flex: 1;
	}
	.intra-fail {
		color: #ef4444;
		font-weight: 600;
		margin-left: 0.3rem;
	}
	.intra-rate {
		font-weight: 600;
		flex-shrink: 0;
	}
	.intra-sha {
		font-family: monospace;
		font-size: 0.68rem;
		color: var(--color-font-secondary);
		flex-shrink: 0;
	}
	.intra-dur {
		font-size: 0.68rem;
		color: var(--color-font-secondary);
		flex-shrink: 0;
	}
</style>
