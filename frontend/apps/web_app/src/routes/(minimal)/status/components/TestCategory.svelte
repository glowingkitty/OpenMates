<!--
	Collapsible test category with pass/fail summary (v3).
	Auto-expands if there are failures.
	Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import type { TestCategory as TCType } from './types';
	import TestRow from './TestRow.svelte';

	interface Props {
		category: TCType;
		defaultExpanded?: boolean;
	}

	let { category, defaultExpanded = false }: Props = $props();
	let expanded = $state(defaultExpanded || category.failed > 0);
	let showAll = $state(false);

	const INITIAL_SHOW = 5;
	let visibleSpecs = $derived(
		showAll || category.specs.length <= INITIAL_SHOW
			? category.specs
			: category.specs.slice(0, INITIAL_SHOW)
	);
</script>

<div class="category">
	<button class="cat-header" onclick={() => expanded = !expanded}>
		<span class="expand-icon">{expanded ? '▾' : '▸'}</span>
		<span class="cat-name" data-testid="cat-name">{category.name}</span>
		<span class="cat-count">({category.total} tests)</span>
		<span class="cat-summary" class:has-failures={category.failed > 0}>
			{category.passed}/{category.total} passing
		</span>
	</button>

	{#if expanded}
		<div class="cat-body">
			{#each visibleSpecs as spec (spec.name)}
				<TestRow {spec} />
			{/each}
			{#if !showAll && category.specs.length > INITIAL_SHOW}
				<button class="show-more" onclick={() => showAll = true}>
					+{category.specs.length - INITIAL_SHOW} more
				</button>
			{/if}
		</div>
	{/if}
</div>

<style>
	.category {
		margin-bottom: 0.3rem;
	}
	.cat-header {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		width: 100%;
		padding: 0.3rem 0;
		background: none;
		border: none;
		cursor: pointer;
		font-size: 0.82rem;
		color: var(--color-font-primary);
		text-align: left;
	}
	.cat-header:hover {
		background: var(--color-grey-5, #f9fafb);
		border-radius: 4px;
	}
	.expand-icon {
		font-size: 0.7rem;
		color: var(--color-font-secondary);
		width: 1rem;
	}
	.cat-name {
		font-weight: 600;
	}
	.cat-count {
		color: var(--color-font-secondary);
		font-size: 0.75rem;
	}
	.cat-summary {
		margin-left: auto;
		font-size: 0.75rem;
		color: var(--color-font-secondary);
	}
	.cat-summary.has-failures {
		color: var(--color-error, #ef4444);
		font-weight: 600;
	}
	.cat-body {
		padding-left: 0.25rem;
	}
	.show-more {
		background: none;
		border: none;
		color: var(--color-primary, #3b82f6);
		font-size: 0.75rem;
		cursor: pointer;
		padding: 0.2rem 0.5rem;
		margin-top: 0.15rem;
	}
	.show-more:hover {
		text-decoration: underline;
	}
</style>
