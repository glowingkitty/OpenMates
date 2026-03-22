<!--
    Status Page — /status
    Orchestrator component. Fetches summary data and delegates rendering to child components.
    Detail data (per-service timelines, per-test histories) loads lazily on expand.
    Architecture: docs/architecture/infrastructure/status-page.md
    Tests: frontend/apps/web_app/tests/status-page.spec.ts
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';
	import type { StatusSummary, SelectedTimeline } from './components/types';
	import { fetchSummary } from './components/api';
	import { timelineColor, timelineTitle } from './components/utils';
	import StatusHeader from './components/StatusHeader.svelte';
	import TimelineBar from './components/TimelineBar.svelte';
	import CurrentIssues from './components/CurrentIssues.svelte';
	import ServiceGroup from './components/ServiceGroup.svelte';
	import TestSuite from './components/TestSuite.svelte';

	let loading = $state(true);
	let error = $state('');
	let data: StatusSummary | null = $state(null);
	let selected: SelectedTimeline | null = $state(null);

	const trendEntries = $derived(
		(data?.tests?.trend ?? []).map((d) => ({
			...d,
			pass_rate: (d.total ?? 0) > 0 ? Math.round(((d.passed ?? 0) / (d.total ?? 1)) * 100) : 0
		}))
	);

	async function load() {
		try {
			data = await fetchSummary();
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
	{#if data}
		<StatusHeader overallStatus={data.overall_status} lastUpdated={data.last_updated} />
	{/if}

	{#if loading}
		<p class="msg">Loading...</p>
	{:else if error}
		<p class="msg err">{error}</p>
	{:else if data}
		<!-- Current Issues overview (unhealthy services + failed tests with admin errors) -->
		{#if data.current_issues}
			<CurrentIssues
				services={data.current_issues.services}
				failedTests={data.current_issues.failed_tests}
				isAdmin={data.is_admin}
			/>
		{/if}

		<!-- 30-Day Health Overview -->
		{#if data.overall_timeline_30d?.length}
			<section class="card">
				<h2>30-Day Health Overview</h2>
				<TimelineBar
					entries={data.overall_timeline_30d}
					timelineKey="overall-health"
					testid="status-timeline-overall-health"
					bind:selected
					showLabels
				/>
			</section>
		{/if}

		<!-- Services -->
		{#if data.health?.groups?.length}
			<section class="card">
				<h2>Services</h2>
				{#each data.health.groups as group (group.group_name)}
					<ServiceGroup {group} isAdmin={data.is_admin} bind:selected />
				{/each}
			</section>
		{/if}

		<!-- Tests -->
		{#if data.tests}
			<section class="card">
				<div class="card-hdr">
					<h2>Tests</h2>
					{#if data.tests.latest_run}
						<span class="meta">
							{data.tests.latest_run.summary.passed ?? 0}/{data.tests.latest_run.summary.total ?? 0} passed
						</span>
					{/if}
				</div>

				{#each data.tests.suites as suite (suite.name)}
					<TestSuite {suite} isAdmin={data.is_admin} bind:selected />
				{/each}

				<!-- Overall trend -->
				{#if trendEntries.length >= 2}
					<div class="item">
						<div class="item-head static">
							<span class="label">Daily Pass Rate (All Suites, 30d)</span>
						</div>
						<TimelineBar
							entries={trendEntries}
							timelineKey="tests-trend"
							bind:selected
							showLabels
							enableIntraDay
						/>
					</div>
				{/if}
			</section>
		{/if}

		<!-- Incidents -->
		{#if data.incidents}
			<section class="card">
				<div class="item-head static">
					<span class="label">Incidents (30d)</span>
					<span class="ibadge" class:has={data.incidents.total_last_30d > 0}>
						{data.incidents.total_last_30d}
					</span>
				</div>
			</section>
		{/if}
	{/if}

	<footer>OpenMates · <a href="/">Go to app</a></footer>
</main>

<style>
	main {
		max-width: 860px;
		margin: 0 auto;
		padding: 0 1rem 2rem;
		color: var(--color-font-primary);
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
	.msg {
		text-align: center;
		padding: 2rem;
		color: var(--color-font-secondary);
	}
	.err { color: var(--color-error); }
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
	.card-hdr h2 { margin-bottom: 0; }
	.meta {
		font-size: 0.78rem;
		color: var(--color-font-secondary);
	}
	.item {
		border-top: 1px solid var(--color-grey-15);
		padding: 0.5rem 0 0.4rem;
	}
	.item:first-child { border-top: none; }
	.item-head {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		width: 100%;
		font-size: 0.85rem;
		color: var(--color-font-primary);
		margin-bottom: 0.3rem;
	}
	.label {
		flex: 1;
		font-weight: 500;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
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
