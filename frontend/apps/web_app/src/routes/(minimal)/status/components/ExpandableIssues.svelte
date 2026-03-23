<!--
    ExpandableIssues — Shows first N current issues with "Show all (total)" expand button.
    Displays unhealthy services and failed tests.
    Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import type { ServiceIssue, TestIssue } from './types';
	import { sc } from './utils';

	let {
		services = [],
		servicesTotal = 0,
		failedTests = [],
		failedTestsTotal = 0,
		isAdmin = false
	}: {
		services: ServiceIssue[];
		servicesTotal: number;
		failedTests: TestIssue[];
		failedTestsTotal: number;
		isAdmin?: boolean;
	} = $props();

	let showAllServices = $state(false);
	let showAllTests = $state(false);

	const hasIssues = $derived(servicesTotal > 0 || failedTestsTotal > 0);
	const displayedServices = $derived(showAllServices ? services : services);
	const displayedTests = $derived(showAllTests ? failedTests : failedTests);
</script>

{#if hasIssues}
	<div class="issues-card" data-testid="status-current-issues">
		<!-- Service issues -->
		{#if servicesTotal > 0}
			<div class="issue-section">
				<h3>Service Issues <span class="cnt">{servicesTotal}</span></h3>
				{#each displayedServices as issue (issue.service_id)}
					<div class="issue-row">
						<span class="dot" style="background:{sc(issue.status)}"></span>
						<span class="issue-name">{issue.name}</span>
						<span class="issue-group">{issue.group}</span>
						<span class="issue-status" style="color:{sc(issue.status)}">{issue.status}</span>
					</div>
					{#if isAdmin && issue.error_message}
						<div class="issue-err">{issue.error_message}</div>
					{/if}
				{/each}
				{#if servicesTotal > services.length && !showAllServices}
					<button class="show-all" onclick={() => (showAllServices = true)}>
						Show all ({servicesTotal})
					</button>
				{/if}
			</div>
		{/if}

		<!-- Failed tests -->
		{#if failedTestsTotal > 0}
			<div class="issue-section">
				<h3>Failed Tests <span class="cnt">{failedTestsTotal}</span></h3>
				{#each displayedTests as test (test.name)}
					<div class="issue-row">
						<span class="dot" style="background:#ef4444"></span>
						<span class="issue-name">{test.name}</span>
						<span class="issue-group">{test.suite}</span>
					</div>
					{#if isAdmin && test.error}
						<div class="issue-err">{test.error}</div>
					{/if}
				{/each}
				{#if failedTestsTotal > failedTests.length && !showAllTests}
					<button class="show-all" onclick={() => (showAllTests = true)}>
						Show all ({failedTestsTotal})
					</button>
				{/if}
			</div>
		{/if}
	</div>
{/if}

<style>
	.issues-card {
		margin-top: 1rem;
		background: var(--color-grey-0);
		border: 1px solid var(--color-grey-25);
		border-left: 3px solid #ef4444;
		border-radius: 10px;
		padding: 0.75rem 1rem;
	}
	.issue-section {
		margin-bottom: 0.5rem;
	}
	.issue-section:last-child {
		margin-bottom: 0;
	}
	.issue-section h3 {
		font-size: 0.82rem;
		font-weight: 600;
		margin: 0 0 0.4rem;
		color: var(--color-font-primary);
		display: flex;
		align-items: center;
		gap: 0.4rem;
	}
	.cnt {
		font-size: 0.72rem;
		padding: 0.05rem 0.35rem;
		border-radius: 999px;
		background: rgba(239, 68, 68, 0.1);
		color: #ef4444;
		font-variant-numeric: tabular-nums;
	}
	.issue-row {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		font-size: 0.8rem;
		padding: 0.15rem 0;
	}
	.dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		flex-shrink: 0;
	}
	.issue-name {
		flex: 1;
		color: var(--color-font-primary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.issue-group {
		font-size: 0.7rem;
		color: var(--color-font-secondary);
		flex-shrink: 0;
	}
	.issue-status {
		font-size: 0.72rem;
		text-transform: capitalize;
		flex-shrink: 0;
	}
	.issue-err {
		font-size: 0.68rem;
		color: var(--color-font-secondary);
		background: var(--color-grey-10);
		padding: 0.2rem 0.4rem;
		border-radius: 4px;
		margin: 0.1rem 0 0.2rem 1rem;
		white-space: pre-wrap;
		word-break: break-all;
		max-height: 3rem;
		overflow: auto;
	}
	.show-all {
		display: block;
		margin: 0.3rem 0 0;
		background: none;
		border: 1px solid var(--color-grey-30);
		border-radius: 4px;
		padding: 0.2rem 0.6rem;
		font-size: 0.72rem;
		color: var(--color-font-secondary);
		cursor: pointer;
		font-family: inherit;
	}
	.show-all:hover {
		background: var(--color-grey-10);
	}
</style>
