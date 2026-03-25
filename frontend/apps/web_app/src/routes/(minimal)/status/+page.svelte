<!--
	Status Page — /status (v3)
	Compact layout: service groups with uptime bars, E2E tests by category,
	response time graphs, intra-day drill-down, incidents.
	Architecture: docs/architecture/infrastructure/status-page.md
	Tests: frontend/apps/web_app/tests/status-page.spec.ts
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';
	import type { StatusResponse } from './components/types';
	import { fetchStatus } from './components/api';
	import StatusBanner from './components/StatusBanner.svelte';
	import ServiceGroup from './components/ServiceGroup.svelte';
	import TestsSection from './components/TestsSection.svelte';
	import IncidentHistory from './components/IncidentHistory.svelte';

	let loading = $state(true);
	let error = $state('');
	let data: StatusResponse | null = $state(null);

	async function load() {
		try {
			data = await fetchStatus();
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
	{#if loading}
		<p class="msg">Loading...</p>
	{:else if error}
		<p class="msg err">{error}</p>
	{:else if data}
		<StatusBanner status={data.status} uptimePct={data.uptime_pct} lastUpdated={data.last_updated} />

		<div class="card">
			{#each data.groups as group (group.name)}
				<ServiceGroup {group} />
			{/each}
		</div>

		<div class="card">
			<TestsSection tests={data.tests} />
		</div>

		<div class="card">
			<IncidentHistory incidents={data.incidents} />
		</div>
	{/if}

	<footer>OpenMates · <a href="/">Go to app</a></footer>
</main>

<style>
	main {
		max-width: 860px;
		margin: 0 auto;
		padding: 1rem 1rem 2rem;
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
		margin-bottom: 0.75rem;
		background: var(--color-grey-0);
		border: 1px solid var(--color-grey-25);
		border-radius: 10px;
		padding: 0.75rem 1rem;
	}
</style>
