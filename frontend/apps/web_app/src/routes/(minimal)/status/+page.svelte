<!--
    Status Page — /status
    Hierarchical 30-day timelines for services and tests.
    Every expandable row has a FULL-WIDTH 30-day bar below the label.
    All data visible to all users. Admin-exclusive: error messages only.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';
	import { getApiEndpoint } from '@repo/ui';

	type TimelineStatus =
		| 'operational'
		| 'degraded'
		| 'down'
		| 'unknown'
		| 'passed'
		| 'failed'
		| 'not_run';
	type TimelineEntry = {
		date: string;
		status?: TimelineStatus;
		pass_rate?: number;
		tone?: number | null;
		passed?: number;
		failed?: number;
		total?: number;
		not_run?: number;
		has_run?: boolean;
		run_at?: string | null;
	};
	type SelectedTimeline = {
		key: string;
		date: string;
		text: string;
	};

	let loading = $state(true);
	let error = $state('');
	let data: any = $state(null);
	let exp: Record<string, boolean> = $state({});
	let selectedTimeline: SelectedTimeline | null = $state(null);

	function toggle(k: string) {
		exp[k] = !exp[k];
	}

	function tid(value: string): string {
		return value
			.toLowerCase()
			.replace(/[^a-z0-9]+/g, '-')
			.replace(/^-|-$/g, '');
	}

	function sc(s: string): string {
		return s === 'operational'
			? '#22c55e'
			: s === 'degraded'
				? '#f59e0b'
				: s === 'down'
					? '#ef4444'
					: 'var(--color-grey-50)';
	}

	function rc(rate: number): string {
		const r = Math.round(34 + (239 - 34) * (1 - rate / 100));
		const g = Math.round(197 + (68 - 197) * (1 - rate / 100));
		const b = Math.round(94 + (68 - 94) * (1 - rate / 100));
		return `rgb(${r},${g},${b})`;
	}

	function fd(iso: string): string {
		try {
			return new Date(iso + 'T00:00:00').toLocaleDateString(undefined, {
				month: 'short',
				day: 'numeric'
			});
		} catch {
			return iso;
		}
	}

	function ft(iso: string): string {
		try {
			return new Date(iso).toLocaleTimeString([], {
				hour: '2-digit',
				minute: '2-digit',
				hour12: false
			});
		} catch {
			return iso;
		}
	}

	function fdt(iso: string): string {
		try {
			return new Date(iso).toLocaleString(undefined, {
				month: 'short',
				day: 'numeric',
				year: 'numeric',
				hour: '2-digit',
				minute: '2-digit',
				hour12: false
			});
		} catch {
			return iso;
		}
	}

	function timelineColor(entry: TimelineEntry): string {
		if (entry.status) {
			return entry.status === 'passed'
				? '#22c55e'
				: entry.status === 'failed'
					? '#ef4444'
					: entry.status === 'not_run'
						? 'var(--color-grey-40)'
						: sc(entry.status);
		}
		if (entry.has_run === false) {
			return 'var(--color-grey-40)';
		}
		return rc(entry.tone ?? entry.pass_rate ?? 0);
	}

	function timelineTitle(entry: TimelineEntry): string {
		if (entry.status) {
			if (entry.status === 'not_run') {
				return `${fd(entry.date)}: No run`;
			}
			return entry.run_at
				? `${fdt(entry.run_at)}: ${entry.status}`
				: `${fd(entry.date)}: ${entry.status}`;
		}
		if (entry.has_run === false) {
			return `${fd(entry.date)}: No run`;
		}

		const parts = [`${fd(entry.date)}`];
		if (entry.run_at) {
			parts.push(fdt(entry.run_at));
		}
		if (
			typeof entry.passed === 'number' ||
			typeof entry.failed === 'number' ||
			typeof entry.not_run === 'number'
		) {
			parts.push(`${entry.passed ?? 0} passed`);
			parts.push(`${entry.failed ?? 0} failed`);
			if ((entry.not_run ?? 0) > 0) {
				parts.push(`${entry.not_run ?? 0} not run`);
			}
		} else if (typeof entry.pass_rate === 'number') {
			parts.push(`${entry.pass_rate}%`);
		}
		return parts.join(' · ');
	}

	function selectTimeline(key: string, entry: TimelineEntry): void {
		selectedTimeline = {
			key,
			date: entry.date,
			text: timelineTitle(entry)
		};
	}

	function isSelectedTimeline(key: string, entry: TimelineEntry): boolean {
		return selectedTimeline?.key === key && selectedTimeline?.date === entry.date;
	}

	const slab: Record<string, string> = {
		operational: 'All Systems Operational',
		degraded: 'Partial Degradation',
		down: 'Major Outage',
		unknown: 'Status Unknown'
	};
	const snames: Record<string, string> = {
		playwright: 'End to End Tests',
		vitest: 'Unit Tests (Frontend)',
		pytest_unit: 'Unit Tests (Backend)'
	};

	async function load() {
		try {
			const res = await fetch(getApiEndpoint('/v1/status'));
			if (!res.ok) throw new Error(`${res.status}`);
			data = await res.json();
			error = '';
		} catch (e) {
			console.error('[STATUS]', e);
			error = 'Could not load status data.';
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		if (!browser) return;
		load();
		const t = setInterval(load, 60_000);
		return () => clearInterval(t);
	});
</script>

<svelte:head><title>OpenMates Status</title></svelte:head>

<main>
	<header>
		<h1>OpenMates Status</h1>
		{#if data}
			<div class="badge" data-s={data.overall_status}>
				<span class="bdot"></span>{slab[data.overall_status] ?? slab.unknown}
			</div>
			<p class="upd">Updated {ft(data.last_updated)}</p>
		{/if}
	</header>

	{#if loading}
		<p class="msg">Loading...</p>
	{:else if error}
		<p class="msg err">{error}</p>
	{:else if data}
		<!-- ═══ 30-Day Overview ═══ -->
		{#if data.overall_timeline_30d?.length}
			<section class="card">
				<h2>30-Day Health Overview</h2>
				<div class="tl" data-testid="status-timeline-overall-health">
					{#each data.overall_timeline_30d as d}
						<button
							type="button"
							class="seg"
							class:selected={isSelectedTimeline('overall-health', d)}
							style="background:{timelineColor(d)}"
							title={timelineTitle(d)}
							aria-label={timelineTitle(d)}
							onclick={() => selectTimeline('overall-health', d)}
							onfocus={() => selectTimeline('overall-health', d)}
						></button>
					{/each}
				</div>
				{#if selectedTimeline?.key === 'overall-health'}
					<div class="tl-detail" data-testid="status-timeline-detail">{selectedTimeline.text}</div>
				{/if}
				<div class="tl-lab"><span>30d ago</span><span>Today</span></div>
			</section>
		{/if}

		<!-- ═══ Services ═══ -->
		{#if data.health?.groups?.length}
			<section class="card">
				<h2>Services</h2>
				{#each data.health.groups as g (g.group_name)}
					{@const groupTimelineKey = `group-${g.group_name}`}
					<div class="item">
						<button class="item-head" onclick={() => toggle(`g-${g.group_name}`)}>
							<span class="dot" style="background:{sc(g.status)}"></span>
							<span class="label">{g.display_name}</span>
							<span class="cnt">({g.service_count})</span>
							<span class="slbl" style="color:{sc(g.status)}">{g.status}</span>
							<span class="chev" class:open={exp[`g-${g.group_name}`]}>&#9662;</span>
						</button>
						<div class="tl" data-testid={`status-timeline-${groupTimelineKey}`}>
							{#each g.timeline_30d as d}
								<button
									type="button"
									class="seg"
									class:selected={isSelectedTimeline(groupTimelineKey, d)}
									style="background:{timelineColor(d)}"
									title={timelineTitle(d)}
									aria-label={timelineTitle(d)}
									onclick={() => selectTimeline(groupTimelineKey, d)}
									onfocus={() => selectTimeline(groupTimelineKey, d)}
								></button>
							{/each}
						</div>
						{#if selectedTimeline?.key === groupTimelineKey}
							<div class="tl-detail" data-testid="status-timeline-detail">
								{selectedTimeline.text}
							</div>
						{/if}

						{#if exp[`g-${g.group_name}`] && g.services}
							<div class="sub">
								{#each g.services as svc}
									{@const serviceTimelineKey = `service-${g.group_name}-${svc.id}`}
									<div class="item nested">
										<div class="item-head static">
											<span class="dot sm" style="background:{sc(svc.status)}"></span>
											<span class="label">{svc.name}</span>
											<span class="slbl" style="color:{sc(svc.status)}">{svc.status}</span>
										</div>
										<div class="tl" data-testid={`status-timeline-${serviceTimelineKey}`}>
											{#each svc.timeline_30d as d}
												<button
													type="button"
													class="seg"
													class:selected={isSelectedTimeline(serviceTimelineKey, d)}
													style="background:{timelineColor(d)}"
													title={timelineTitle(d)}
													aria-label={timelineTitle(d)}
													onclick={() => selectTimeline(serviceTimelineKey, d)}
													onfocus={() => selectTimeline(serviceTimelineKey, d)}
												></button>
											{/each}
										</div>
										{#if selectedTimeline?.key === serviceTimelineKey}
											<div class="tl-detail" data-testid="status-timeline-detail">
												{selectedTimeline.text}
											</div>
										{/if}
										{#if data.is_admin && svc.error_message}
											<div class="errd">{svc.error_message}</div>
										{/if}
									</div>
								{/each}
							</div>
						{/if}
					</div>
				{/each}
			</section>
		{/if}

		<!-- ═══ Tests ═══ -->
		{#if data.tests}
			<section class="card">
				<div class="card-hdr">
					<h2>Tests</h2>
					{#if data.tests.latest_run}
						<span class="meta"
							>{data.tests.latest_run.summary.passed ?? 0}/{data.tests.latest_run.summary.total ??
								0} passed</span
						>
					{/if}
				</div>

				{#each data.tests.suites as suite (suite.name)}
					{@const hasCats =
						suite.name === 'playwright' &&
						suite.categories &&
						Object.keys(suite.categories).length > 0}
					{@const suiteTimelineKey = `suite-${suite.name}`}
					<div class="item">
						<button
							class="item-head"
							data-testid={`status-suite-${suite.name}`}
							onclick={() => toggle(`s-${suite.name}`)}
						>
							<span class="dot" style="background:{suite.failed > 0 ? '#ef4444' : '#22c55e'}"
							></span>
							<span class="label">{snames[suite.name] ?? suite.name}</span>
							<span class="cnt">{suite.passed}/{suite.total}</span>
							{#if suite.failed > 0}<span class="fail">{suite.failed} failed</span>{/if}
							<span class="chev" class:open={exp[`s-${suite.name}`]}>&#9662;</span>
						</button>
						{#if suite.timeline_30d?.length}
							<div class="tl" data-testid={`status-timeline-${suiteTimelineKey}`}>
								{#each suite.timeline_30d as d}
									<button
										type="button"
										class="seg"
										class:selected={isSelectedTimeline(suiteTimelineKey, d)}
										style="background:{timelineColor(d)}"
										title={timelineTitle(d)}
										aria-label={timelineTitle(d)}
										onclick={() => selectTimeline(suiteTimelineKey, d)}
										onfocus={() => selectTimeline(suiteTimelineKey, d)}
									></button>
								{/each}
							</div>
							{#if selectedTimeline?.key === suiteTimelineKey}
								<div class="tl-detail" data-testid="status-timeline-detail">
									{selectedTimeline.text}
								</div>
							{/if}
						{/if}

						{#if exp[`s-${suite.name}`]}
							<div class="sub">
								{#if hasCats}
									{#each Object.entries(suite.categories as Record<string, any>).sort( (a, b) => a[0].localeCompare(b[0]) ) as [catName, cat]}
										{@const categoryTimelineKey = `category-${tid(catName)}`}
										<div class="item nested">
											<button
												class="item-head"
												data-testid={`status-category-${tid(catName)}`}
												onclick={() => toggle(`c-${catName}`)}
											>
												<span class="dot sm" style="background:{rc(cat.pass_rate)}"></span>
												<span class="label">{catName}</span>
												<span class="cnt">{cat.passed}/{cat.total}</span>
												<span class="rate" style="color:{rc(cat.pass_rate)}">{cat.pass_rate}%</span>
												<span class="chev" class:open={exp[`c-${catName}`]}>&#9662;</span>
											</button>
											{#if cat.history?.length}
												<div class="tl" data-testid={`status-timeline-${categoryTimelineKey}`}>
													{#each cat.history as d}
														<button
															type="button"
															class="seg"
															class:selected={isSelectedTimeline(categoryTimelineKey, d)}
															style="background:{timelineColor(d)}"
															title={timelineTitle(d)}
															aria-label={timelineTitle(d)}
															onclick={() => selectTimeline(categoryTimelineKey, d)}
															onfocus={() => selectTimeline(categoryTimelineKey, d)}
														></button>
													{/each}
												</div>
												{#if selectedTimeline?.key === categoryTimelineKey}
													<div class="tl-detail" data-testid="status-timeline-detail">
														{selectedTimeline.text}
													</div>
												{/if}
											{/if}

											{#if exp[`c-${catName}`] && cat.tests?.length}
												<div class="sub">
													{#each cat.tests as test}
														{@const testTimelineKey = `test-${tid(test.file ?? test.name)}`}
														<div class="item nested">
															<div class="item-head static">
																<span
																	class="dot xs"
																	style="background:{test.status === 'passed'
																		? '#22c55e'
																		: test.status === 'failed'
																			? '#ef4444'
																			: '#666'}"
																></span>
																<span class="label mono">{test.name}</span>
																<span
																	class="slbl"
																	style="color:{test.status === 'passed'
																		? '#22c55e'
																		: test.status === 'failed'
																			? '#ef4444'
																			: '#666'}">{test.status}</span
																>
																{#if test.last_run}<span class="tdate"
																		>{fd(test.last_run.slice(0, 10))}</span
																	>{/if}
															</div>
															{#if test.history_30d?.length}
																<div class="tl" data-testid={`status-timeline-${testTimelineKey}`}>
																	{#each test.history_30d as d}
																		<button
																			type="button"
																			class="seg"
																			class:selected={isSelectedTimeline(testTimelineKey, d)}
																			style="background:{timelineColor(d)}"
																			title={timelineTitle(d)}
																			aria-label={timelineTitle(d)}
																			onclick={() => selectTimeline(testTimelineKey, d)}
																			onfocus={() => selectTimeline(testTimelineKey, d)}
																		></button>
																	{/each}
																</div>
																{#if selectedTimeline?.key === testTimelineKey}
																	<div class="tl-detail" data-testid="status-timeline-detail">
																		{selectedTimeline.text}
																	</div>
																{/if}
															{/if}
															{#if data.is_admin && test.error}
																<div class="errd">{test.error}</div>
															{/if}
														</div>
													{/each}
												</div>
											{/if}
										</div>
									{/each}
								{:else if suite.tests?.length}
									{#each suite.tests as test}
										{@const testTimelineKey = `test-${suite.name}-${tid(test.file ?? test.name)}`}
										<div class="item nested">
											<div class="item-head static">
												<span
													class="dot xs"
													style="background:{test.status === 'passed'
														? '#22c55e'
														: test.status === 'failed'
															? '#ef4444'
															: 'var(--color-grey-50)'}"
												></span>
												<span class="label mono">{test.name || test.file}</span>
												<span
													class="slbl"
													style="color:{test.status === 'passed'
														? '#22c55e'
														: test.status === 'failed'
															? '#ef4444'
															: 'var(--color-grey-50)'}">{test.status}</span
												>
												{#if test.last_run}<span class="tdate"
														>{fd(test.last_run.slice(0, 10))}</span
													>{/if}
											</div>
											{#if test.history_30d?.length}
												<div class="tl" data-testid={`status-timeline-${testTimelineKey}`}>
													{#each test.history_30d as d}
														<button
															type="button"
															class="seg"
															class:selected={isSelectedTimeline(testTimelineKey, d)}
															style="background:{timelineColor(d)}"
															title={timelineTitle(d)}
															aria-label={timelineTitle(d)}
															onclick={() => selectTimeline(testTimelineKey, d)}
															onfocus={() => selectTimeline(testTimelineKey, d)}
														></button>
													{/each}
												</div>
												{#if selectedTimeline?.key === testTimelineKey}
													<div class="tl-detail" data-testid="status-timeline-detail">
														{selectedTimeline.text}
													</div>
												{/if}
											{/if}
											{#if data.is_admin && test.error}
												<div class="errd">{test.error}</div>
											{/if}
										</div>
									{/each}
								{:else}
									<p class="meta" style="padding:0.5rem 0">No test details available.</p>
								{/if}
							</div>
						{/if}
					</div>
				{/each}

				<!-- Overall trend -->
				{#if data.tests.trend?.length >= 2}
					{@const trendTimelineKey = 'tests-trend'}
					<div class="item">
						<div class="item-head static">
							<span class="label">Daily Pass Rate (All Suites, 30d)</span>
						</div>
						<div class="tl" data-testid={`status-timeline-${trendTimelineKey}`}>
							{#each data.tests.trend as d}
								{@const trendEntry = {
									...d,
									pass_rate: d.total > 0 ? Math.round((d.passed / d.total) * 100) : 0
								}}
								<button
									type="button"
									class="seg"
									class:selected={isSelectedTimeline(trendTimelineKey, trendEntry)}
									style="background:{timelineColor(trendEntry)}"
									title={timelineTitle(trendEntry)}
									aria-label={timelineTitle(trendEntry)}
									onclick={() => selectTimeline(trendTimelineKey, trendEntry)}
									onfocus={() => selectTimeline(trendTimelineKey, trendEntry)}
								></button>
							{/each}
						</div>
						{#if selectedTimeline?.key === trendTimelineKey}
							<div class="tl-detail" data-testid="status-timeline-detail">
								{selectedTimeline.text}
							</div>
						{/if}
						<div class="tl-lab"><span>30d ago</span><span>Today</span></div>
					</div>
				{/if}
			</section>
		{/if}

		<!-- ═══ Incidents ═══ -->
		{#if data.incidents}
			<section class="card">
				<div class="item-head static">
					<span class="label">Incidents (30d)</span>
					<span class="ibadge" class:has={data.incidents.total_last_30d > 0}
						>{data.incidents.total_last_30d}</span
					>
				</div>
			</section>
		{/if}
	{/if}

	<footer>OpenMates · <a href="/">Go to app</a></footer>
</main>

<style>
	/* ─── Layout ─── */
	main {
		max-width: 860px;
		margin: 0 auto;
		padding: 0 1rem 2rem;
		color: var(--color-font-primary);
	}
	header {
		text-align: center;
		padding: 2rem 0 0.5rem;
	}
	header h1 {
		margin: 0 0 0.5rem;
		font-size: var(--font-size-h2, 1.5rem);
		font-weight: 700;
	}
	footer {
		text-align: center;
		padding: 1.5rem 0;
		font-size: 0.75rem;
		color: var(--color-font-secondary);
	}
	footer a {
		color: var(--color-font-secondary);
		text-decoration: underline;
	}

	/* Badge */
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
	[data-s='operational'] .bdot {
		background: #22c55e;
	}
	[data-s='operational'] {
		color: #22c55e;
	}
	[data-s='degraded'] .bdot {
		background: #f59e0b;
	}
	[data-s='degraded'] {
		color: #f59e0b;
	}
	[data-s='down'] .bdot {
		background: #ef4444;
	}
	[data-s='down'] {
		color: #ef4444;
	}
	.upd {
		margin: 0.4rem 0 0;
		font-size: 0.75rem;
		color: var(--color-font-secondary);
	}
	.msg {
		text-align: center;
		padding: 2rem;
		color: var(--color-font-secondary);
	}
	.err {
		color: var(--color-error);
	}

	/* Cards */
	.card {
		margin-top: 1rem;
		background: var(--color-grey-0);
		border: 1px solid var(--color-grey-25);
		border-radius: 10px;
		padding: 0.75rem 1rem;
	}
	.card h2 {
		margin: 0 0 0.6rem;
		font-size: 0.95rem;
		font-weight: 600;
	}
	.card-hdr {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 0.6rem;
	}
	.card-hdr h2 {
		margin-bottom: 0;
	}
	.meta {
		font-size: 0.78rem;
		color: var(--color-font-secondary);
	}

	/* ─── Item: the core repeating unit ─── */
	/* Each item = header row + full-width timeline below it */
	.item {
		border-top: 1px solid var(--color-grey-15);
		padding: 0.5rem 0 0.4rem;
	}
	.item:first-child {
		border-top: none;
	}
	.item.nested {
		padding: 0.35rem 0;
	}

	.item-head {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		width: 100%;
		font-size: 0.85rem;
		color: var(--color-font-primary);
		margin-bottom: 0.3rem;
	}

	button.item-head {
		background: none;
		border: none;
		cursor: pointer;
		font-family: inherit;
		text-align: left;
		padding: 0;
	}
	button.item-head:hover {
		opacity: 0.8;
	}

	.dot {
		width: 0.45rem;
		height: 0.45rem;
		border-radius: 50%;
		flex-shrink: 0;
	}
	.dot.sm {
		width: 0.38rem;
		height: 0.38rem;
	}
	.dot.xs {
		width: 0.3rem;
		height: 0.3rem;
	}
	.label {
		flex: 1;
		font-weight: 500;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.label.mono {
		font-family: monospace;
		font-size: 0.75rem;
		font-weight: 400;
	}
	.cnt {
		font-size: 0.75rem;
		color: var(--color-font-secondary);
		font-variant-numeric: tabular-nums;
		flex-shrink: 0;
	}
	.slbl {
		font-size: 0.72rem;
		text-transform: capitalize;
		flex-shrink: 0;
	}
	.fail {
		font-size: 0.72rem;
		color: #ef4444;
		font-weight: 600;
		flex-shrink: 0;
	}
	.rate {
		font-size: 0.72rem;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		flex-shrink: 0;
	}
	.tdate {
		font-size: 0.68rem;
		color: var(--color-font-secondary);
		flex-shrink: 0;
	}
	.chev {
		font-size: 0.65rem;
		color: var(--color-font-secondary);
		transition: transform 0.15s;
		flex-shrink: 0;
	}
	.chev.open {
		transform: rotate(180deg);
	}

	/* ─── Timeline bars — ALWAYS FULL WIDTH ─── */
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

	/* Nested sub-items */
	.sub {
		padding-left: 1rem;
		border-left: 2px solid var(--color-grey-20);
		margin-left: 0.2rem;
		margin-top: 0.3rem;
	}

	/* Error detail (admin only) */
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

	/* Incidents */
	.ibadge {
		font-size: 0.78rem;
		padding: 0.1rem 0.4rem;
		border-radius: 999px;
		background: var(--color-grey-10);
		color: var(--color-font-secondary);
		font-variant-numeric: tabular-nums;
	}
	.ibadge.has {
		background: rgba(239, 68, 68, 0.1);
		color: #ef4444;
	}
</style>
