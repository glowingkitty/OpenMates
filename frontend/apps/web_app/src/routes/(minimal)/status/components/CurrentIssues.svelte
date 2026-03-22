<!--
    CurrentIssues — Overview of current failed tests and unhealthy services at the top.
    Admin users see exact error messages.
    Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import { sc } from './utils';

	type ServiceIssue = {
		service_type: string;
		service_id: string;
		name: string;
		group: string;
		status: string;
		error_message?: string;
		last_check?: string;
	};

	type TestIssue = {
		suite: string;
		name: string;
		file: string;
		error?: string;
	};

	let {
		services = [],
		failedTests = [],
		isAdmin = false
	}: {
		services?: ServiceIssue[];
		failedTests?: TestIssue[];
		isAdmin?: boolean;
	} = $props();

	const hasIssues = $derived(services.length > 0 || failedTests.length > 0);
</script>

{#if hasIssues}
	<section class="card issues">
		<h2>Current Issues</h2>

		{#if services.length > 0}
			<div class="issue-group">
				<h3>Unhealthy Services</h3>
				{#each services as svc}
					<div class="issue-row">
						<span class="dot" style="background:{sc(svc.status)}"></span>
						<span class="issue-label">{svc.name}</span>
						<span class="issue-group-name">{svc.group}</span>
						<span class="issue-status" style="color:{sc(svc.status)}">{svc.status}</span>
					</div>
					{#if isAdmin && svc.error_message}
						<div class="errd">{svc.error_message}</div>
					{/if}
				{/each}
			</div>
		{/if}

		{#if failedTests.length > 0}
			<div class="issue-group">
				<h3>Failed Tests ({failedTests.length})</h3>
				{#each failedTests as test}
					<div class="issue-row">
						<span class="dot" style="background:#ef4444"></span>
						<span class="issue-label mono">{test.name || test.file}</span>
						<span class="issue-suite">{test.suite}</span>
					</div>
					{#if isAdmin && test.error}
						<div class="errd">{test.error}</div>
					{/if}
				{/each}
			</div>
		{/if}
	</section>
{/if}

<style>
	.card.issues {
		margin-top: 1rem;
		background: var(--color-grey-0);
		border: 1px solid var(--color-grey-25);
		border-radius: 10px;
		padding: 0.75rem 1rem;
		border-left: 3px solid #ef4444;
	}
	.card.issues h2 {
		margin: 0 0 0.5rem;
		font-size: 0.95rem;
		font-weight: 600;
		color: #ef4444;
	}
	.issue-group {
		margin-bottom: 0.5rem;
	}
	.issue-group:last-child {
		margin-bottom: 0;
	}
	.issue-group h3 {
		margin: 0 0 0.3rem;
		font-size: 0.78rem;
		font-weight: 600;
		color: var(--color-font-secondary);
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}
	.issue-row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.25rem 0;
		font-size: 0.82rem;
	}
	.dot {
		width: 0.4rem;
		height: 0.4rem;
		border-radius: 50%;
		flex-shrink: 0;
	}
	.issue-label {
		flex: 1;
		font-weight: 500;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.issue-label.mono {
		font-family: monospace;
		font-size: 0.75rem;
		font-weight: 400;
	}
	.issue-group-name {
		font-size: 0.7rem;
		color: var(--color-font-secondary);
		flex-shrink: 0;
	}
	.issue-status {
		font-size: 0.72rem;
		text-transform: capitalize;
		font-weight: 600;
		flex-shrink: 0;
	}
	.issue-suite {
		font-size: 0.7rem;
		color: var(--color-font-secondary);
		flex-shrink: 0;
	}
	.errd {
		font-size: 0.7rem;
		color: var(--color-error);
		background: rgba(239, 68, 68, 0.06);
		padding: 0.2rem 0.5rem;
		border-radius: 4px;
		margin: 0.1rem 0 0.3rem 0.9rem;
		white-space: pre-wrap;
		word-break: break-word;
		max-height: 60px;
		overflow-y: auto;
	}
</style>
