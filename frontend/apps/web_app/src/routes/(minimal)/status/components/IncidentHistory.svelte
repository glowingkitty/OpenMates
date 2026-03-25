<!--
	Incident history section (v3).
	Shows reverse-chronological list of incidents with "View older" option.
	Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import type { Incident } from './types';
	import IncidentEntry from './IncidentEntry.svelte';

	interface Props {
		incidents: Incident[];
	}

	let { incidents }: Props = $props();
</script>

<section class="incidents-section">
	<h2 class="section-title">Incidents (last 14 days)</h2>
	{#if incidents.length === 0}
		<p class="empty">No incidents in the last 14 days.</p>
	{:else}
		{#each incidents as incident}
			<IncidentEntry {incident} />
		{/each}
	{/if}
</section>

<style>
	.incidents-section {
		margin-top: 0.5rem;
	}
	.section-title {
		font-size: 0.7rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-font-secondary);
		margin: 0 0 0.4rem;
		padding-bottom: 0.25rem;
		border-bottom: 1px solid var(--color-grey-15, #e5e7eb);
	}
	.empty {
		font-size: 0.78rem;
		color: var(--color-font-secondary);
		margin: 0;
		padding: 0.25rem 0;
	}
</style>
