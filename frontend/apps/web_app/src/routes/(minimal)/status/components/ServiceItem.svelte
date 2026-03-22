<!--
    ServiceItem — Single service with status dot, name, and per-service timeline.
    Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import type { Service, SelectedTimeline } from './types';
	import { sc } from './utils';
	import TimelineBar from './TimelineBar.svelte';

	let {
		service,
		groupName,
		isAdmin = false,
		selected = $bindable<SelectedTimeline | null>(null)
	}: {
		service: Service;
		groupName: string;
		isAdmin?: boolean;
		selected?: SelectedTimeline | null;
	} = $props();
</script>

<div class="item nested">
	<div class="item-head static">
		<span class="dot sm" style="background:{sc(service.status)}"></span>
		<span class="label">{service.name}</span>
		<span class="slbl" style="color:{sc(service.status)}">{service.status}</span>
	</div>
	<TimelineBar
		entries={service.timeline_30d}
		timelineKey={`service-${groupName}-${service.id}`}
		bind:selected
	/>
	{#if isAdmin && service.error_message}
		<div class="errd">{service.error_message}</div>
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
	}
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
	.slbl {
		font-size: 0.72rem;
		text-transform: capitalize;
		flex-shrink: 0;
	}
	.errd {
		font-size: 0.7rem;
		color: var(--color-error);
		background: rgba(239, 68, 68, 0.06);
		padding: 0.2rem 0.5rem;
		border-radius: 4px;
		margin-top: 0.15rem;
		white-space: pre-wrap;
		word-break: break-word;
		max-height: 60px;
		overflow-y: auto;
	}
</style>
