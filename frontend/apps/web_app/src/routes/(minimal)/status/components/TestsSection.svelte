<!--
	E2E tests section with categories (v3).
	Shows summary header and collapsible test categories.
	Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import type { TestsData } from './types';
	import TestCategory from './TestCategory.svelte';
	import { timeAgo } from './utils';

	interface Props {
		tests: TestsData;
	}

	let { tests }: Props = $props();
</script>

<section class="tests-section">
	<div class="tests-header">
		<h2 class="section-title">E2E Tests</h2>
		<span class="tests-summary" class:has-failures={tests.failed > 0}>
			{tests.passed}/{tests.total} passing
		</span>
	</div>
	{#if tests.last_run}
		<div class="last-run">Last run: {timeAgo(tests.last_run)}</div>
	{/if}

	<div class="categories">
		{#each tests.categories as category (category.name)}
			<TestCategory {category} />
		{/each}
	</div>
</section>

<style>
	.tests-section {
		margin-top: 0.5rem;
	}
	.tests-header {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-bottom: 0.25rem;
	}
	.section-title {
		font-size: 0.7rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-font-secondary);
		margin: 0;
		flex: 1;
		padding-bottom: 0.25rem;
		border-bottom: 1px solid var(--color-grey-15, #e5e7eb);
	}
	.tests-summary {
		font-size: 0.82rem;
		font-weight: 600;
		color: var(--color-success, #22c55e);
	}
	.tests-summary.has-failures {
		color: var(--color-error, #ef4444);
	}
	.last-run {
		font-size: 0.72rem;
		color: var(--color-font-secondary);
		margin-bottom: 0.5rem;
	}
	.categories {
		display: flex;
		flex-direction: column;
	}
</style>
