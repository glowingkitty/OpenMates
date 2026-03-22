<!--
    ServiceItem — Single service with status dot, name, per-service timeline,
    and expandable skills list (for apps with per-skill health data).
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

	let expanded = $state(false);
	const hasSkills = $derived(service.skills && service.skills.length > 0);

	function skillStatusColor(status: string): string {
		return status === 'available' || status === 'healthy'
			? '#22c55e'
			: status === 'unavailable' || status === 'unhealthy'
				? '#ef4444'
				: 'var(--color-grey-50)';
	}
</script>

<div class="item nested">
	{#if hasSkills}
		<button class="item-head" onclick={() => (expanded = !expanded)}>
			<span class="dot sm" style="background:{sc(service.status)}"></span>
			<span class="label">{service.name}</span>
			<span class="cnt">({service.skills?.length} skills)</span>
			<span class="slbl" style="color:{sc(service.status)}">{service.status}</span>
			<span class="chev" class:open={expanded}>&#9662;</span>
		</button>
	{:else}
		<div class="item-head static">
			<span class="dot sm" style="background:{sc(service.status)}"></span>
			<span class="label">{service.name}</span>
			<span class="slbl" style="color:{sc(service.status)}">{service.status}</span>
		</div>
	{/if}
	<TimelineBar
		entries={service.timeline_30d}
		timelineKey={`service-${groupName}-${service.id}`}
		bind:selected
	/>
	{#if isAdmin && service.error_message}
		<div class="errd">{service.error_message}</div>
	{/if}

	{#if expanded && service.skills}
		<div class="sub">
			{#each service.skills as skill}
				<div class="skill-row">
					<span class="dot xs" style="background:{skillStatusColor(skill.status)}"></span>
					<span class="skill-name">{skill.id}</span>
					<span class="skill-status" style="color:{skillStatusColor(skill.status)}">{skill.status}</span>
					{#if skill.providers.length > 0}
						<span class="skill-providers">
							{#each skill.providers as prov, i}
								<span class="prov" style="color:{skillStatusColor(prov.status)}">{prov.name}</span>{#if i < skill.providers.length - 1}, {/if}
							{/each}
						</span>
					{/if}
				</div>
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
	}
	button.item-head {
		background: none;
		border: none;
		cursor: pointer;
		font-family: inherit;
		text-align: left;
		padding: 0;
	}
	button.item-head:hover { opacity: 0.8; }
	.dot.sm {
		width: 0.38rem;
		height: 0.38rem;
		border-radius: 50%;
		flex-shrink: 0;
	}
	.dot.xs {
		width: 0.3rem;
		height: 0.3rem;
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
		font-size: 0.72rem;
		color: var(--color-font-secondary);
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
	.sub {
		padding-left: 1rem;
		border-left: 2px solid var(--color-grey-20);
		margin-left: 0.2rem;
		margin-top: 0.3rem;
	}
	.skill-row {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		padding: 0.2rem 0;
		font-size: 0.78rem;
	}
	.skill-name {
		font-family: monospace;
		font-size: 0.72rem;
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.skill-status {
		font-size: 0.68rem;
		text-transform: capitalize;
		flex-shrink: 0;
	}
	.skill-providers {
		font-size: 0.68rem;
		color: var(--color-font-secondary);
		flex-shrink: 0;
	}
	.prov {
		font-size: 0.68rem;
	}
</style>
