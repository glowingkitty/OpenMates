<!--
    TestCategory — Expandable test category with pass rate, timeline, and lazy test list.
    Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import type { TestCategory as TCat, SelectedTimeline } from './types';
	import { tid, rc } from './utils';
	import TimelineBar from './TimelineBar.svelte';
	import TestItem from './TestItem.svelte';

	let {
		name,
		category,
		isAdmin = false,
		selected = $bindable<SelectedTimeline | null>(null)
	}: {
		name: string;
		category: TCat;
		isAdmin?: boolean;
		selected?: SelectedTimeline | null;
	} = $props();

	let expanded = $state(false);
</script>

<div class="item nested">
	<button
		class="item-head"
		data-testid={`status-category-${tid(name)}`}
		onclick={() => (expanded = !expanded)}
	>
		<span class="dot sm" style="background:{rc(category.pass_rate)}"></span>
		<span class="label">{name}</span>
		<span class="cnt">{category.passed}/{category.total}</span>
		<span class="rate" style="color:{rc(category.pass_rate)}">{category.pass_rate}%</span>
		<span class="chev" class:open={expanded}>&#9662;</span>
	</button>
	{#if category.history?.length}
		<TimelineBar
			entries={category.history}
			timelineKey={`category-${tid(name)}`}
			bind:selected
		/>
	{/if}

	{#if expanded && category.tests?.length}
		<div class="sub">
			{#each category.tests as test}
				<TestItem {test} timelinePrefix={`test`} {isAdmin} bind:selected />
			{/each}
		</div>
	{/if}
</div>

<style>
	.item.nested { padding: 0.35rem 0; }
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
	.dot.sm {
		width: 0.38rem;
		height: 0.38rem;
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
	.rate {
		font-size: 0.72rem;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
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
</style>
