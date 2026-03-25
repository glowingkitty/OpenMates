<!--
	Status page overall status banner (v3).
	Shows overall status, uptime %, and last updated time.
	Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import type { ServiceStatus } from './types';
	import { statusColor, overallStatusLabel, timeAgo } from './utils';

	interface Props {
		status: ServiceStatus;
		uptimePct: number;
		lastUpdated: string;
	}

	let { status, uptimePct, lastUpdated }: Props = $props();
</script>

<div class="banner" style:--banner-color={statusColor(status)}>
	<div class="banner-dot" style:background={statusColor(status)}></div>
	<div class="banner-text">
		<span class="banner-label">{overallStatusLabel(status)}</span>
		<span class="banner-meta">{uptimePct}% uptime (90d) · Updated {timeAgo(lastUpdated)}</span>
	</div>
</div>

<style>
	.banner {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 1rem 1.25rem;
		border-radius: 10px;
		background: var(--color-grey-0);
		border: 1px solid var(--color-grey-25);
		margin-bottom: 1rem;
	}
	.banner-dot {
		width: 12px;
		height: 12px;
		border-radius: 50%;
		flex-shrink: 0;
	}
	.banner-text {
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
	}
	.banner-label {
		font-size: 1rem;
		font-weight: 600;
		color: var(--color-font-primary);
	}
	.banner-meta {
		font-size: 0.75rem;
		color: var(--color-font-secondary);
	}
</style>
