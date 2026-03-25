<!--
	Service group section (v3).
	Renders a group header and list of service rows.
	Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import type { ServiceGroupData } from './types';
	import ServiceRow from './ServiceRow.svelte';

	interface Props {
		group: ServiceGroupData;
	}

	let { group }: Props = $props();
</script>

<section class="group">
	<h2 class="group-header">{group.name}</h2>
	{#each group.services as service (service.id)}
		<ServiceRow {service} />
	{/each}
</section>

<style>
	.group {
		margin-bottom: 0.75rem;
	}
	.group-header {
		font-size: 0.7rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-font-secondary);
		margin: 0 0 0.4rem;
		padding-bottom: 0.25rem;
		border-bottom: 1px solid var(--color-grey-15, #e5e7eb);
	}
</style>
