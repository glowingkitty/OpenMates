<!--
    FunctionalityGroup — Expandable functionality item with lazy-loaded sub-categories and tests.
    Root shows functionality name, pass rate, and 30-day timeline.
    On expand: fetches sub-category timelines, then individual tests on further expand.
    Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import type { FunctionalitySummary, FunctionalityDetail, FunctionalitySubCategory, SelectedTimeline } from './types';
	import { sc, rc } from './utils';
	import { fetchFunctionalityDetail } from './api';
	import TimelineBar from './TimelineBar.svelte';

	let {
		functionality,
		isAdmin = false,
		selected = $bindable<SelectedTimeline | null>(null)
	}: {
		functionality: FunctionalitySummary;
		isAdmin?: boolean;
		selected?: SelectedTimeline | null;
	} = $props();

	let expanded = $state(false);
	let detail: FunctionalityDetail | null = $state(null);
	let loading = $state(false);
	let loadError = $state('');
	let expandedSubCat: string | null = $state(null);

	const passColor = $derived(rc(functionality.pass_rate));
	const statusColor = $derived(sc(functionality.status));

	async function toggle() {
		expanded = !expanded;
		if (expanded && !detail) {
			loading = true;
			loadError = '';
			try {
				detail = await fetchFunctionalityDetail(functionality.name);
			} catch (e) {
				console.error('[STATUS] Failed to load functionality detail', e);
				loadError = 'Failed to load details.';
			} finally {
				loading = false;
			}
		}
	}

	function toggleSubCat(name: string) {
		expandedSubCat = expandedSubCat === name ? null : name;
	}

	function testsForSubCat(subCat: FunctionalitySubCategory): typeof detail extends null ? never : NonNullable<FunctionalityDetail>['tests'] {
		if (!detail) return [];
		return detail.tests.filter((t) => t.sub_category === subCat.name);
	}
</script>

<div class="func-item" data-testid="status-func-{functionality.name.toLowerCase().replace(/\s+/g, '-')}">
	<button type="button" class="func-head" onclick={toggle}>
		<span class="dot" style="background:{statusColor}"></span>
		<span class="func-name">{functionality.name}</span>
		<span class="func-stats">
			<span class="func-rate" style="color:{passColor}">{functionality.pass_rate}%</span>
			<span class="func-count">{functionality.passed}/{functionality.total}</span>
		</span>
		<span class="chevron" class:open={expanded}>▸</span>
	</button>

	{#if functionality.timeline_30d?.length}
		<TimelineBar
			entries={functionality.timeline_30d}
			timelineKey="func-{functionality.name}"
			bind:selected
			enableIntraDay
			intraDaySource="functionality"
			intraDayId={functionality.name}
		/>
	{/if}

	{#if expanded}
		<div class="func-detail">
			{#if loading}
				<p class="loading">Loading...</p>
			{:else if loadError}
				<p class="err">{loadError}</p>
			{:else if detail}
				<!-- Sub-categories with timelines -->
				{#if detail.sub_categories?.length}
					{#each detail.sub_categories as subCat (subCat.name)}
						{@const subPassColor = rc(subCat.pass_rate)}
						<div class="sub-cat">
							<button type="button" class="sub-cat-head" onclick={() => toggleSubCat(subCat.name)}>
								<span class="dot sm" style="background:{sc(subCat.status)}"></span>
								<span class="sub-cat-name">{subCat.name}</span>
								<span class="sub-cat-rate" style="color:{subPassColor}">{subCat.pass_rate}%</span>
								<span class="sub-cat-count">{subCat.passed}/{subCat.total}</span>
								<span class="chevron sm" class:open={expandedSubCat === subCat.name}>▸</span>
							</button>
							{#if subCat.timeline_30d?.length}
								<div class="sub-cat-tl">
									<TimelineBar
										entries={subCat.timeline_30d}
										timelineKey="subcat-{functionality.name}-{subCat.name}"
										height="0.7rem"
										bind:selected
									/>
								</div>
							{/if}
							{#if expandedSubCat === subCat.name}
								<div class="test-list">
									{#each testsForSubCat(subCat) as test (test.file)}
										<div class="test-row">
											<span class="dot xs" style="background:{test.status === 'passed' ? '#22c55e' : test.status === 'failed' ? '#ef4444' : 'var(--color-grey-40)'}"></span>
											<span class="test-name">{test.name}</span>
											<span class="test-status" class:failed={test.status === 'failed'}>{test.status}</span>
										</div>
										{#if isAdmin && test.error}
											<div class="test-error">{test.error}</div>
										{/if}
									{/each}
								</div>
							{/if}
						</div>
					{/each}
				{:else}
					<!-- No sub-categories — show tests directly -->
					<div class="test-list">
						{#each detail.tests as test (test.file)}
							<div class="test-row">
								<span class="dot xs" style="background:{test.status === 'passed' ? '#22c55e' : test.status === 'failed' ? '#ef4444' : 'var(--color-grey-40)'}"></span>
								<span class="test-name">{test.name}</span>
								<span class="test-status" class:failed={test.status === 'failed'}>{test.status}</span>
							</div>
							{#if isAdmin && test.error}
								<div class="test-error">{test.error}</div>
							{/if}
						{/each}
					</div>
				{/if}
			{/if}
		</div>
	{/if}
</div>

<style>
	.func-item {
		border-top: 1px solid var(--color-grey-15);
		padding: 0.5rem 0 0.4rem;
	}
	.func-item:first-child {
		border-top: none;
	}
	.func-head {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		width: 100%;
		font-size: 0.85rem;
		color: var(--color-font-primary);
		background: none;
		border: none;
		padding: 0;
		cursor: pointer;
		margin-bottom: 0.3rem;
		font-family: inherit;
		text-align: left;
	}
	.dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
	}
	.dot.sm {
		width: 6px;
		height: 6px;
	}
	.dot.xs {
		width: 5px;
		height: 5px;
	}
	.func-name {
		flex: 1;
		font-weight: 500;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.func-stats {
		display: flex;
		align-items: center;
		gap: 0.3rem;
		flex-shrink: 0;
	}
	.func-rate {
		font-size: 0.8rem;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
	.func-count {
		font-size: 0.72rem;
		color: var(--color-font-secondary);
		font-variant-numeric: tabular-nums;
	}
	.chevron {
		font-size: 0.7rem;
		color: var(--color-font-secondary);
		transition: transform 0.15s;
		flex-shrink: 0;
	}
	.chevron.sm {
		font-size: 0.6rem;
	}
	.chevron.open {
		transform: rotate(90deg);
	}
	.func-detail {
		padding: 0.3rem 0 0 1rem;
	}
	.loading, .err {
		font-size: 0.78rem;
		color: var(--color-font-secondary);
		padding: 0.25rem 0;
	}
	.err {
		color: var(--color-error);
	}

	/* Sub-categories */
	.sub-cat {
		margin-bottom: 0.3rem;
	}
	.sub-cat-head {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		width: 100%;
		font-size: 0.8rem;
		color: var(--color-font-primary);
		background: none;
		border: none;
		padding: 0.15rem 0;
		cursor: pointer;
		font-family: inherit;
		text-align: left;
	}
	.sub-cat-name {
		flex: 1;
		font-weight: 500;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.sub-cat-rate {
		font-size: 0.75rem;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
	.sub-cat-count {
		font-size: 0.68rem;
		color: var(--color-font-secondary);
		font-variant-numeric: tabular-nums;
	}
	.sub-cat-tl {
		padding: 0.1rem 0 0.15rem 0.6rem;
	}

	/* Tests */
	.test-list {
		padding: 0.15rem 0 0.15rem 0.6rem;
	}
	.test-row {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		font-size: 0.75rem;
		padding: 0.12rem 0;
	}
	.test-name {
		flex: 1;
		color: var(--color-font-primary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.test-status {
		font-size: 0.68rem;
		color: var(--color-font-secondary);
		text-transform: capitalize;
		flex-shrink: 0;
	}
	.test-status.failed {
		color: #ef4444;
		font-weight: 600;
	}
	.test-error {
		font-size: 0.68rem;
		color: var(--color-font-secondary);
		background: var(--color-grey-10);
		padding: 0.2rem 0.4rem;
		border-radius: 4px;
		margin: 0.1rem 0 0.2rem 1.1rem;
		white-space: pre-wrap;
		word-break: break-all;
		max-height: 4rem;
		overflow: auto;
	}
</style>
