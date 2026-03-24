<!--
    Status Page — /status (v2)
    Three sections: Services (infrastructure), Apps (expandable), Functionalities (test-based).
    Detail data loads lazily on expand. Auto-refreshes every 60 seconds.
    Architecture: docs/architecture/infrastructure/status-page.md
    Tests: frontend/apps/web_app/tests/status-page.spec.ts
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';
	import type { StatusSummary, SelectedTimeline } from './components/types';
	import { fetchSummary } from './components/api';
	import StatusHeader from './components/StatusHeader.svelte';
	import TimelineBar from './components/TimelineBar.svelte';
	import ExpandableIssues from './components/ExpandableIssues.svelte';
	import InfraServices from './components/InfraServices.svelte';
	import AppGroup from './components/AppGroup.svelte';
	import FunctionalityGroup from './components/FunctionalityGroup.svelte';

	let loading = $state(true);
	let error = $state('');
	let data: StatusSummary | null = $state(null);
	let selected: SelectedTimeline | null = $state(null);

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
		<StatusHeader overallStatus={data.overall_status} lastUpdated={data.last_updated} overallTimeline={data.overall_timeline_30d} />
	{/if}

	{#if loading}
		<p class="msg">Loading...</p>
	{:else if error}
		<p class="msg err">{error}</p>
	{:else if data}
		<!-- Current Issues (first 5 with expand) -->
		{#if data.current_issues}
			<ExpandableIssues
				services={data.current_issues.services}
				servicesTotal={data.current_issues.services_total}
				failedTests={data.current_issues.failed_tests}
				failedTestsTotal={data.current_issues.failed_tests_total}
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

		<!-- Services (flat infrastructure) -->
		{#if data.services?.length}
			<section class="card">
				<h2>Services</h2>
				<InfraServices services={data.services} bind:selected />
			</section>
		{/if}

		<!-- Apps (expandable with lazy detail) -->
		{#if data.apps?.length}
			<section class="card">
				<h2>Apps</h2>
				{#each data.apps as app (app.id)}
					<AppGroup {app} isAdmin={data.is_admin} bind:selected />
				{/each}
			</section>
		{/if}

		<!-- Functionalities (expandable with lazy detail) -->
		<section class="card">
			<h2>Functionalities</h2>
			{#if data.functionalities?.length}
				{#each data.functionalities as func (func.name)}
					<FunctionalityGroup functionality={func} isAdmin={data.is_admin} bind:selected />
				{/each}
			{:else}
				<p class="empty-note">No E2E test data available yet. Functionalities populate after the daily test run.</p>
			{/if}
		</section>

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
	.empty-note {
		font-size: 0.78rem;
		color: var(--color-font-secondary);
		padding: 0.25rem 0;
		margin: 0;
	}
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
	.item-head {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		width: 100%;
		font-size: 0.85rem;
		color: var(--color-font-primary);
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
