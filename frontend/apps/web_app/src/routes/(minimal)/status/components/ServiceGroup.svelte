<!--
    ServiceGroup — Single expandable service group with lazy-loaded services.
    Fetches per-service detail data (with timelines) on first expand.
    Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import type { HealthGroup, HealthGroupDetail, SelectedTimeline, Service } from './types';
	import { sc } from './utils';
	import { fetchGroupDetail } from './api';
	import TimelineBar from './TimelineBar.svelte';
	import ServiceItem from './ServiceItem.svelte';

	let {
		group,
		isAdmin = false,
		selected = $bindable<SelectedTimeline | null>(null)
	}: {
		group: HealthGroup;
		isAdmin?: boolean;
		selected?: SelectedTimeline | null;
	} = $props();

	let expanded = $state(false);
	let detail: HealthGroupDetail | null = $state(null);
	let detailLoadedAt = $state(0);
	let loading = $state(false);

	async function toggle() {
		expanded = !expanded;
		if (expanded && (!detail || Date.now() - detailLoadedAt > 60_000)) {
			loading = true;
			try {
				detail = await fetchGroupDetail(group.group_name);
				detailLoadedAt = Date.now();
			} catch (e) {
				console.error('[STATUS] Failed to load group detail', e);
			} finally {
				loading = false;
			}
		}
	}
</script>

<div class="item">
	<button class="item-head" onclick={toggle}>
		<span class="dot" style="background:{sc(group.status)}"></span>
		<span class="label">{group.display_name}</span>
		<span class="cnt">({group.service_count})</span>
		<span class="slbl" style="color:{sc(group.status)}">{group.status}</span>
		<span class="chev" class:open={expanded}>&#9662;</span>
	</button>
	<TimelineBar
		entries={group.timeline_30d}
		timelineKey={`group-${group.group_name}`}
		bind:selected
	/>

	{#if expanded}
		<div class="sub">
			{#if loading}
				<p class="meta">Loading services...</p>
			{:else if detail?.services}
				{#each detail.services as svc}
					<ServiceItem service={svc} groupName={group.group_name} {isAdmin} bind:selected />
				{/each}
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
	.slbl {
		font-size: 0.72rem;
		text-transform: capitalize;
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
