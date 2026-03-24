<!--
    InfraServices — Flat list of infrastructure services with status + 30-day timeline.
    No expand needed — just 4 items (Vercel, API Server, Sightengine, Brevo).
    Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import type { InfraService, SelectedTimeline } from './types';
	import { sc, uptimePct, fmtUptime } from './utils';
	import TimelineBar from './TimelineBar.svelte';

	let {
		services,
		selected = $bindable<SelectedTimeline | null>(null)
	}: {
		services: InfraService[];
		selected?: SelectedTimeline | null;
	} = $props();
</script>

{#each services as svc (svc.id)}
	<div class="svc-row" data-testid="status-service-{svc.id}">
		<div class="svc-head">
			<span class="dot" style="background:{sc(svc.status)}"></span>
			<span class="svc-name">{svc.display_name}</span>
			{@const pct = uptimePct(svc.timeline_30d ?? [])}
			{#if pct !== null}
				<span class="svc-uptime">{fmtUptime(pct)}</span>
			{/if}
			<span class="svc-status" style="color:{sc(svc.status)}">{svc.status}</span>
		</div>
		{#if svc.timeline_30d?.length}
			<TimelineBar
				entries={svc.timeline_30d}
				timelineKey="service-{svc.id}"
				bind:selected
				enableIntraDay
				intraDaySource="service"
				intraDayId={svc.id}
			/>
		{/if}
	</div>
{/each}

<style>
	.svc-row {
		border-top: 1px solid var(--color-grey-15);
		padding: 0.5rem 0 0.4rem;
	}
	.svc-row:first-child {
		border-top: none;
	}
	.svc-head {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		font-size: 0.85rem;
		margin-bottom: 0.3rem;
	}
	.dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
	}
	.svc-name {
		flex: 1;
		font-weight: 500;
		color: var(--color-font-primary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.svc-uptime {
		font-size: 0.75rem;
		color: var(--color-font-secondary);
		flex-shrink: 0;
	}
	.svc-status {
		font-size: 0.78rem;
		text-transform: capitalize;
		flex-shrink: 0;
	}
</style>
