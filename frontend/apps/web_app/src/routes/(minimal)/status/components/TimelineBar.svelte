<!--
    TimelineBar — Reusable 30-day timeline bar with interactive segment selection.
    When a day has multiple checks/runs, clicking it shows an hourly sub-timeline.
    Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import type { TimelineEntry, SelectedTimeline, IntraDayHour } from './types';
	import { timelineColor, timelineTitle, fd, ft, rc } from './utils';
	import { fetchIntraDayData } from './api';

	let {
		entries,
		timelineKey,
		testid = '',
		height = '',
		selected = $bindable<SelectedTimeline | null>(null),
		showLabels = false,
		enableIntraDay = false,
		intraDaySource = undefined as string | undefined,
		intraDayId = undefined as string | undefined
	}: {
		entries: TimelineEntry[];
		timelineKey: string;
		testid?: string;
		height?: string;
		selected?: SelectedTimeline | null;
		showLabels?: boolean;
		enableIntraDay?: boolean;
		intraDaySource?: string;
		intraDayId?: string;
	} = $props();

	let intraDayHours: IntraDayHour[] | null = $state(null);
	let intraDayDate: string | null = $state(null);
	let intraDayLoading = $state(false);
	let selectedHour: number | null = $state(null);

	function select(entry: TimelineEntry) {
		selected = {
			key: timelineKey,
			date: entry.date,
			text: timelineTitle(entry)
		};
		if (intraDayDate !== entry.date) {
			intraDayHours = null;
			intraDayDate = null;
			selectedHour = null;
		}
	}

	function isSelected(entry: TimelineEntry): boolean {
		return selected?.key === timelineKey && selected?.date === entry.date;
	}

	async function loadIntraDay(date: string) {
		if (intraDayDate === date && intraDayHours !== null) {
			intraDayHours = null;
			intraDayDate = null;
			selectedHour = null;
			return;
		}
		intraDayLoading = true;
		intraDayDate = date;
		try {
			const res = await fetchIntraDayData(date, intraDaySource, intraDayId);
			intraDayHours = res.hours;
		} catch (e) {
			console.error('[STATUS] Failed to load intra-day data', e);
			intraDayHours = [];
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

	function hourColor(hour: IntraDayHour): string {
		if (hour.summary.total === 0) return 'var(--color-grey-40)';
		const rate = Math.round((hour.summary.passed / hour.summary.total) * 100);
		return rc(rate);
	}
</script>

{#if entries?.length}
	<div class="tl" style={height ? `height:${height}` : ''} data-testid={testid || `status-timeline-${timelineKey}`}>
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
			{#if enableIntraDay && selected.date && !intraDayHours && !intraDayLoading}
				<button class="expand-btn" onclick={() => loadIntraDay(selected?.date ?? '')}>
					Show all runs
				</button>
			{/if}
		</div>
	{/if}

	<!-- Intra-day hourly sub-timeline -->
	{#if intraDayLoading}
		<div class="intra-day">
			<span class="intra-label">Loading...</span>
		</div>
	{:else if intraDayHours !== null && intraDayDate}
		{@const totalRuns = intraDayHours.reduce((s, h) => s + h.run_count, 0)}
		{#if totalRuns <= 1}
			<div class="intra-day">
				<span class="intra-label">{fd(intraDayDate)}: 1 run</span>
			</div>
		{:else}
			<div class="intra-day">
				<span class="intra-label">{fd(intraDayDate)}: {totalRuns} runs across {intraDayHours.length} hours</span>
				<div class="intra-tl">
					{#each Array(24) as _, h}
						{@const hourData = intraDayHours.find((hr) => hr.hour === h)}
						{#if hourData}
							{@const rate = hourData.summary.total > 0 ? Math.round((hourData.summary.passed / hourData.summary.total) * 100) : 0}
							<button
								type="button"
								class="intra-seg"
								class:selected={selectedHour === h}
								style="background:{hourColor(hourData)}"
								title="{String(h).padStart(2, '0')}:00 — {hourData.run_count} run(s), {hourData.summary.passed}/{hourData.summary.total} passed ({rate}%)"
								aria-label="{String(h).padStart(2, '0')}:00: {hourData.summary.passed}/{hourData.summary.total} passed"
								onclick={() => (selectedHour = selectedHour === h ? null : h)}
							></button>
						{:else}
							<div class="intra-seg empty" title="{String(h).padStart(2, '0')}:00 — no runs"></div>
						{/if}
					{/each}
				</div>
				{#if selectedHour !== null}
					{@const hourData = intraDayHours.find((hr) => hr.hour === selectedHour)}
					{#if hourData}
						{@const rate = hourData.summary.total > 0 ? Math.round((hourData.summary.passed / hourData.summary.total) * 100) : 0}
						<div class="intra-detail">
							<span class="intra-time">{String(selectedHour).padStart(2, '0')}:00</span>
							<span class="intra-counts">
								{hourData.run_count} run(s) · {hourData.summary.passed}/{hourData.summary.total} passed
								{#if hourData.summary.failed > 0}
									<span class="intra-fail">{hourData.summary.failed} failed</span>
								{/if}
							</span>
							<span class="intra-rate" style="color:{rc(rate)}">{rate}%</span>
						</div>
						<!-- Individual runs within this hour -->
						{#if hourData.runs.length > 1}
							<div class="intra-runs">
								{#each hourData.runs as run}
									{@const runRate = run.summary.total > 0 ? Math.round((run.summary.passed / run.summary.total) * 100) : 0}
									<div class="intra-run-row">
										<span class="intra-time">{ft(run.timestamp)}</span>
										<span class="intra-counts">{run.summary.passed}/{run.summary.total}</span>
										<span class="intra-rate" style="color:{rc(runRate)}">{runRate}%</span>
										{#if run.git_sha}
											<span class="intra-sha">{run.git_sha.slice(0, 7)}</span>
										{/if}
										{#if run.duration_seconds}
											<span class="intra-dur">{Math.round(run.duration_seconds)}s</span>
										{/if}
									</div>
								{/each}
							</div>
						{/if}
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
		/* height set via inline style prop (default 1.1rem) */
		min-height: 0.8rem;
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
		min-height: 0.8rem;
		border-radius: 4px;
		overflow: hidden;
		background: var(--color-grey-20);
	}
	.intra-seg {
		flex: 1;
		min-width: 4px;
		border: none;
		padding: 0;
		margin: 0;
		cursor: pointer;
		border-radius: 2px;
	}
	.intra-seg.empty {
		background: var(--color-grey-15);
		cursor: default;
	}
	.intra-seg.selected {
		outline: 2px solid var(--color-font-primary);
		outline-offset: -2px;
	}
	.intra-runs {
		margin-top: 0.25rem;
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
	}
	.intra-run-row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		font-size: 0.68rem;
		color: var(--color-font-secondary);
		font-variant-numeric: tabular-nums;
		padding: 0.1rem 0;
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
