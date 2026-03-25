<!--
	Single incident entry with timeline (v3).
	Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import type { Incident } from './types';
	import { statusColor, formatDuration } from './utils';

	interface Props {
		incident: Incident;
	}

	let { incident }: Props = $props();

	function formatDate(iso: string): string {
		const d = new Date(iso);
		return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
	}

	function formatTime(iso: string): string {
		const d = new Date(iso);
		return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
	}
</script>

<div class="incident">
	<div class="incident-header">
		<span class="date">{formatDate(incident.started_at)}</span>
		<span class="sep">·</span>
		<span class="component">{incident.component}</span>
		<span class="sep">—</span>
		<span class="severity" style:color={statusColor(incident.severity)}>
			{incident.severity === 'down' ? 'Down' : 'Degraded'}
		</span>
		<span class="sep">·</span>
		<span class="duration">{formatDuration(incident.duration_minutes)}</span>
	</div>
	<div class="updates">
		{#each incident.updates as update}
			<div class="update">
				<span class="update-time">{formatTime(update.timestamp)}</span>
				<span class="update-sep">—</span>
				<span class="update-status">
					{update.status === 'operational' ? 'Resolved' : `Status changed to ${update.status}`}
				</span>
			</div>
		{/each}
	</div>
</div>

<style>
	.incident {
		padding: 0.4rem 0;
		border-bottom: 1px solid var(--color-grey-10);
	}
	.incident:last-child {
		border-bottom: none;
	}
	.incident-header {
		display: flex;
		align-items: center;
		gap: 0.3rem;
		font-size: 0.82rem;
		flex-wrap: wrap;
	}
	.date {
		font-weight: 600;
		color: var(--color-font-primary);
	}
	.component {
		font-weight: 500;
	}
	.sep {
		color: var(--color-font-secondary);
	}
	.duration {
		color: var(--color-font-secondary);
		font-size: 0.75rem;
	}
	.updates {
		padding-left: 1rem;
		margin-top: 0.2rem;
	}
	.update {
		font-size: 0.75rem;
		color: var(--color-font-secondary);
		display: flex;
		gap: 0.3rem;
	}
	.update-time {
		font-family: monospace;
		min-width: 3rem;
	}
</style>
