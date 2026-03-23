<!--
    AppGroup — Expandable app item with lazy-loaded providers and skills.
    Root shows app name, status, and 30-day timeline.
    On expand: fetches providers (with timelines) and skills (overall status).
    Architecture: docs/architecture/infrastructure/status-page.md
-->
<script lang="ts">
	import type { AppSummary, AppDetail, SelectedTimeline } from './types';
	import { sc } from './utils';
	import { fetchAppDetail } from './api';
	import TimelineBar from './TimelineBar.svelte';

	let {
		app,
		isAdmin = false,
		selected = $bindable<SelectedTimeline | null>(null)
	}: {
		app: AppSummary;
		isAdmin?: boolean;
		selected?: SelectedTimeline | null;
	} = $props();

	let expanded = $state(false);
	let detail: AppDetail | null = $state(null);
	let loading = $state(false);
	let loadError = $state('');

	async function toggle() {
		expanded = !expanded;
		if (expanded && !detail) {
			loading = true;
			loadError = '';
			try {
				detail = await fetchAppDetail(app.id);
			} catch (e) {
				console.error('[STATUS] Failed to load app detail', e);
				loadError = 'Failed to load details.';
			} finally {
				loading = false;
			}
		}
	}
</script>

<div class="app-item" data-testid="status-app-{app.id}">
	<button type="button" class="app-head" onclick={toggle}>
		<span class="dot" style="background:{sc(app.status)}"></span>
		<span class="app-name">{app.display_name}</span>
		<span class="app-meta">
			{app.provider_count} providers · {app.skill_count} skills
		</span>
		<span class="chevron" class:open={expanded}>▸</span>
	</button>

	{#if app.timeline_30d?.length}
		<TimelineBar
			entries={app.timeline_30d}
			timelineKey="app-{app.id}"
			bind:selected
		/>
	{/if}

	{#if expanded}
		<div class="app-detail">
			{#if loading}
				<p class="loading">Loading...</p>
			{:else if loadError}
				<p class="err">{loadError}</p>
			{:else if detail}
				<!-- Providers -->
				{#if detail.providers.length}
					<div class="sub-section">
						<h4>Providers ({detail.providers.length})</h4>
						{#each detail.providers as provider (provider.id)}
							<div class="sub-row">
								<span class="dot sm" style="background:{sc(provider.status)}"></span>
								<span class="sub-name">{provider.name}</span>
								<span class="sub-status" style="color:{sc(provider.status)}">{provider.status}</span>
							</div>
							{#if provider.timeline_30d?.length}
								<div class="sub-tl">
									<TimelineBar
										entries={provider.timeline_30d}
										timelineKey="provider-{provider.id}"
										height="0.7rem"
										bind:selected
									/>
								</div>
							{/if}
						{/each}
					</div>
				{/if}

				<!-- Skills -->
				{#if detail.skills.length}
					<div class="sub-section">
						<h4>Skills ({detail.skills.length})</h4>
						{#each detail.skills as skill (skill.id)}
							<div class="sub-row">
								<span class="dot sm" style="background:{sc(skill.status)}"></span>
								<span class="sub-name">{skill.id}</span>
								<span class="sub-status" style="color:{sc(skill.status)}">{skill.status}</span>
							</div>
							{#if skill.providers.length}
								<div class="skill-providers">
									{#each skill.providers as sp}
										<span class="sp-dot" style="background:{sc(sp.status)}" title="{sp.name}: {sp.status}"></span>
										<span class="sp-name">{sp.name}</span>
									{/each}
								</div>
							{/if}
						{/each}
					</div>
				{/if}

				<!-- Admin details -->
				{#if isAdmin && detail.last_check}
					<div class="admin-info">
						Last check: {new Date(Number(detail.last_check) * 1000).toLocaleString()}
					</div>
				{/if}
			{/if}
		</div>
	{/if}
</div>

<style>
	.app-item {
		border-top: 1px solid var(--color-grey-15);
		padding: 0.5rem 0 0.4rem;
	}
	.app-item:first-child {
		border-top: none;
	}
	.app-head {
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
	.app-name {
		flex: 1;
		font-weight: 500;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.app-meta {
		font-size: 0.72rem;
		color: var(--color-font-secondary);
		flex-shrink: 0;
	}
	.chevron {
		font-size: 0.7rem;
		color: var(--color-font-secondary);
		transition: transform 0.15s;
		flex-shrink: 0;
	}
	.chevron.open {
		transform: rotate(90deg);
	}
	.app-detail {
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
	.sub-section {
		margin-bottom: 0.5rem;
	}
	.sub-section h4 {
		font-size: 0.75rem;
		font-weight: 600;
		color: var(--color-font-secondary);
		margin: 0.3rem 0 0.2rem;
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}
	.sub-row {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		font-size: 0.8rem;
		padding: 0.15rem 0;
	}
	.sub-name {
		flex: 1;
		color: var(--color-font-primary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.sub-status {
		font-size: 0.72rem;
		text-transform: capitalize;
		flex-shrink: 0;
	}
	.sub-tl {
		padding: 0.1rem 0 0.2rem 0.6rem;
	}
	.skill-providers {
		display: flex;
		align-items: center;
		gap: 0.3rem;
		padding: 0.1rem 0 0.15rem 0.6rem;
		flex-wrap: wrap;
	}
	.sp-dot {
		width: 5px;
		height: 5px;
		border-radius: 50%;
	}
	.sp-name {
		font-size: 0.68rem;
		color: var(--color-font-secondary);
		margin-right: 0.3rem;
	}
	.admin-info {
		font-size: 0.68rem;
		color: var(--color-font-secondary);
		margin-top: 0.3rem;
		padding: 0.2rem 0.4rem;
		background: var(--color-grey-10);
		border-radius: 4px;
	}
</style>
