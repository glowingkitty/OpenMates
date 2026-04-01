<script lang="ts">
	/**
	 * DocsBreadcrumb — Navigable breadcrumb trail for documentation pages.
	 *
	 * Renders a clickable path like: Docs > Architecture > AI > AI Model Selection
	 * Similar to the settings breadcrumb nav in AppDetailsHeader.svelte.
	 * Placed above the ChatHeader in the docs content area.
	 *
	 * Architecture: docs/architecture/frontend/docs-web-app.md
	 */
	import { text } from '@repo/ui';
	import docsData from '$lib/generated/docs-data.json';
	import type { DocFolder, DocStructure } from '$lib/types/docs';

	interface Props {
		/** Current page slug (e.g., "architecture/ai/ai-model-selection") */
		slug: string;
	}

	let { slug }: Props = $props();

	interface BreadcrumbItem {
		label: string;
		href: string;
	}

	let breadcrumbs = $derived.by(() => {
		const parts = slug.split('/').filter(Boolean);
		const items: BreadcrumbItem[] = [
			{ label: $text('documentation.title'), href: '/docs' }
		];

		let currentPath = '';
		let current: DocStructure | DocFolder = docsData.structure as DocStructure;

		for (let i = 0; i < parts.length; i++) {
			const part = parts[i];
			currentPath += (currentPath ? '/' : '') + part;
			const isLast = i === parts.length - 1;

			// Check if this part matches a folder
			const folder: DocFolder | undefined = current.folders.find((f: DocFolder) => f.name === part);
			if (folder) {
				items.push({
					label: folder.title,
					href: `/docs/${currentPath}`
				});
				if (!isLast) {
					current = folder;
				}
				continue;
			}

			// Check if this is a file at the last position
			if (isLast) {
				const file = current.files.find(
					(f: { slug: string; title: string; name: string }) =>
						f.slug === slug || f.name.replace('.md', '') === part
				);
				if (file) {
					items.push({
						label: file.title,
						href: `/docs/${slug}`
					});
				}
			}
		}

		return items;
	});
</script>

{#if breadcrumbs.length > 1}
	<nav class="docs-breadcrumb" data-testid="docs-breadcrumb" aria-label="Breadcrumb">
		{#each breadcrumbs as crumb, i (crumb.href)}
			{#if i > 0}
				<span class="separator">/</span>
			{/if}
			{#if i === breadcrumbs.length - 1}
				<span class="current">{crumb.label}</span>
			{:else}
				<a href={crumb.href} class="crumb-link">{crumb.label}</a>
			{/if}
		{/each}
	</nav>
{/if}

<style>
	.docs-breadcrumb {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.25rem;
		padding: 0.625rem 1rem;
		font-size: 0.8125rem;
		line-height: 1.4;
	}

	.crumb-link {
		color: var(--color-font-secondary);
		text-decoration: none;
		font-weight: 500;
		transition: color 0.15s ease;
		white-space: nowrap;
	}

	.crumb-link:hover {
		color: var(--color-primary);
		text-decoration: underline;
	}

	.separator {
		color: var(--color-font-tertiary);
		user-select: none;
		font-weight: 400;
	}

	.current {
		color: var(--color-font-primary);
		font-weight: 600;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		max-width: 300px;
	}

	@media (max-width: 600px) {
		.docs-breadcrumb {
			padding: 0.5rem 0.75rem;
			font-size: 0.75rem;
		}

		.current {
			max-width: 200px;
		}
	}
</style>
