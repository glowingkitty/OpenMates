<!--
    TestSuite — Expandable test suite with lazy-loaded categories and tests.
    Fetches per-test detail data on first expand.
    Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import type { TestSuiteData, TestSuiteDetail, SelectedTimeline } from './types';
	import { SUITE_NAMES } from './utils';
	import { fetchTestDetail } from './api';
	import TimelineBar from './TimelineBar.svelte';
	import TestCategory from './TestCategory.svelte';
	import TestItem from './TestItem.svelte';

	let {
		suite,
		isAdmin = false,
		selected = $bindable<SelectedTimeline | null>(null)
	}: {
		suite: TestSuiteData;
		isAdmin?: boolean;
		selected?: SelectedTimeline | null;
	} = $props();

	let expanded = $state(false);
	let detail: TestSuiteDetail | null = $state(null);
	let detailLoadedAt = $state(0);
	let loading = $state(false);

	const hasCats = $derived(
		detail?.categories && Object.keys(detail.categories).length > 0
	);

	const suiteTests = $derived(
		detail?.suites?.[suite.name]?.tests ?? []
	);

	async function toggle() {
		expanded = !expanded;
		if (expanded && (!detail || Date.now() - detailLoadedAt > 60_000)) {
			loading = true;
			try {
				detail = await fetchTestDetail(suite.name);
				detailLoadedAt = Date.now();
			} catch (e) {
				console.error('[STATUS] Failed to load test detail', e);
			} finally {
				loading = false;
			}
		}
	}
</script>

<div class="item">
	<button
		class="item-head"
		data-testid={`status-suite-${suite.name}`}
		onclick={toggle}
	>
		<span class="dot" style="background:{suite.failed > 0 ? '#ef4444' : '#22c55e'}"></span>
		<span class="label">{SUITE_NAMES[suite.name] ?? suite.name}</span>
		<span class="cnt">{suite.passed}/{suite.total}</span>
		{#if suite.failed > 0}<span class="fail">{suite.failed} failed</span>{/if}
		<span class="chev" class:open={expanded}>&#9662;</span>
	</button>
	<TimelineBar
		entries={suite.timeline_30d}
		timelineKey={`suite-${suite.name}`}
		bind:selected
	/>

	{#if expanded}
		<div class="sub">
			{#if loading}
				<p class="meta">Loading tests...</p>
			{:else if hasCats}
				{#each Object.entries(detail?.categories ?? {}).sort((a, b) => a[0].localeCompare(b[0])) as [catName, cat]}
					<TestCategory name={catName} category={cat} {isAdmin} bind:selected />
				{/each}
			{:else if suiteTests.length}
				{#each suiteTests as test}
					<TestItem {test} timelinePrefix={`test-${suite.name}`} {isAdmin} bind:selected />
				{/each}
			{:else}
				<p class="meta">No test details available.</p>
			{/if}
		</div>
	{/if}
</div>

<style>
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
		background: none;
		border: none;
		cursor: pointer;
		font-family: inherit;
		text-align: left;
		padding: 0;
	}
	.item-head:hover { opacity: 0.8; }
	.dot {
		width: 0.45rem;
		height: 0.45rem;
		border-radius: 50%;
		flex-shrink: 0;
	}
	.label {
		flex: 1;
		font-weight: 500;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.cnt {
		font-size: 0.75rem;
		color: var(--color-font-secondary);
		font-variant-numeric: tabular-nums;
		flex-shrink: 0;
	}
	.fail {
		font-size: 0.72rem;
		color: #ef4444;
		font-weight: 600;
		flex-shrink: 0;
	}
	.chev {
		font-size: 0.65rem;
		color: var(--color-font-secondary);
		transition: transform 0.15s;
		flex-shrink: 0;
	}
	.chev.open { transform: rotate(180deg); }
	.sub {
		padding-left: 1rem;
		border-left: 2px solid var(--color-grey-20);
		margin-left: 0.2rem;
		margin-top: 0.3rem;
	}
	.meta {
		font-size: 0.78rem;
		color: var(--color-font-secondary);
		padding: 0.5rem 0;
	}
</style>
