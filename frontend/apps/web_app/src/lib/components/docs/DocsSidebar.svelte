<script lang="ts">
	/**
	 * DocsSidebar Component
	 *
	 * Sidebar navigation for documentation, styled to match Chats.svelte.
	 * Features:
	 * - Integrated search bar at top (same UX as chat search)
	 * - Close button matching chat sidebar
	 * - Folder groups styled like chat time groups
	 * - Doc items styled like chat list items with category gradient circles
	 * - Table of contents for active doc page (h2/h3 headings)
	 * - Keyboard shortcut: Cmd+K for search focus
	 *
	 * Architecture: docs/architecture/docs-web-app.md
	 * Mirrors: components/chats/Chats.svelte layout pattern
	 */
	import { page } from '$app/state';
	import { untrack } from 'svelte';
	import { text, getCategoryGradientColors, getLucideIcon, SearchBar } from '@repo/ui';
	import docsData from '$lib/generated/docs-data.json';
	import type { DocFolder, DocFile, DocsData } from '$lib/types/docs';
	import { getDocCategoryInfo, DOCS_FOLDER_ICON } from '$lib/utils/docsCategoryMap';

	interface Props {
		onClose: () => void;
	}

	let { onClose }: Props = $props();

	const { structure, searchIndex } = docsData as unknown as DocsData;

	// Search state
	let searchQuery = $state('');
	let isSearchBarVisible = $state(false);

	// Track expanded folders
	let expandedFolders = $state<Set<string>>(new Set());

	let currentPath = $derived(page.url.pathname);

	// Auto-expand folder containing current page
	let lastProcessedPath = '';
	$effect(() => {
		const path = currentPath.replace('/docs/', '').replace('/docs', '');
		if (path && path !== lastProcessedPath) {
			lastProcessedPath = path;
			const parts = path.split('/');
			let parentPath = '';
			const foldersToExpand: string[] = [];
			for (const part of parts.slice(0, -1)) {
				parentPath = parentPath ? `${parentPath}/${part}` : part;
				foldersToExpand.push(parentPath);
			}
			untrack(() => {
				for (const folder of foldersToExpand) {
					expandedFolders.add(folder);
				}
				expandedFolders = new Set(expandedFolders);
			});
		}
	});

	// Search results
	let searchResults = $derived.by(() => {
		if (!searchQuery.trim()) return [];
		const query = searchQuery.toLowerCase().trim();
		const words = query.split(/\s+/);

		return searchIndex
			.filter((entry: { title: string; content: string; slug: string }) => {
				const titleLower = entry.title.toLowerCase();
				const contentLower = entry.content.toLowerCase();
				return words.every(
					(word: string) => titleLower.includes(word) || contentLower.includes(word)
				);
			})
			.sort((a: { title: string }, b: { title: string }) => {
				const aTitle = a.title.toLowerCase();
				const bTitle = b.title.toLowerCase();
				const aExact = aTitle.includes(query) ? 1 : 0;
				const bExact = bTitle.includes(query) ? 1 : 0;
				return bExact - aExact;
			})
			.slice(0, 20);
	});

	let isSearchActive = $derived(searchQuery.trim().length > 0);

	// TOC headings for the active doc page
	let tocHeadings = $state<Array<{ id: string; text: string; level: number }>>([]);
	let activeDocSlug = $derived(currentPath.replace('/docs/', '').replace('/docs', ''));

	// Extract TOC headings when the page changes
	$effect(() => {
		// Trigger on path change
		const _path = currentPath;
		// Use a microtask to wait for DOM render
		if (typeof window !== 'undefined') {
			setTimeout(() => {
				const container = document.querySelector('.active-docs-container');
				if (!container) {
					tocHeadings = [];
					return;
				}
				const headings = container.querySelectorAll('h2, h3');
				tocHeadings = Array.from(headings)
					.filter((h) => h.id)
					.map((h) => ({
						id: h.id,
						text: h.textContent || '',
						level: parseInt(h.tagName.charAt(1))
					}));
			}, 200);
		}
	});

	function isActive(slug: string): boolean {
		const docPath = `/docs/${slug}`;
		return currentPath === docPath || currentPath === `${docPath}/`;
	}

	function folderContainsActive(folder: DocFolder): boolean {
		for (const file of folder.files) {
			if (isActive(file.slug)) return true;
		}
		for (const subfolder of folder.folders) {
			if (folderContainsActive(subfolder)) return true;
		}
		return false;
	}

	function toggleFolder(path: string) {
		if (expandedFolders.has(path)) {
			expandedFolders.delete(path);
		} else {
			expandedFolders.add(path);
		}
		expandedFolders = new Set(expandedFolders);
	}

	function getSnippet(content: string, maxLen = 60): string {
		const clean = content.replace(/[#*_`\[\]()]/g, '').trim();
		return clean.length > maxLen ? clean.substring(0, maxLen) + '...' : clean;
	}

	function handleSearchQuery(query: string) {
		searchQuery = query;
	}

	function handleSearchClose() {
		searchQuery = '';
		isSearchBarVisible = false;
	}

	function openDocsSearch() {
		isSearchBarVisible = true;
	}

	function handleKeydown(event: KeyboardEvent) {
		if ((event.metaKey || event.ctrlKey) && event.key === 'k') {
			event.preventDefault();
			openDocsSearch();
		}
	}

	function scrollToHeading(id: string) {
		const element = document.getElementById(id);
		if (element) {
			element.scrollIntoView({ behavior: 'smooth', block: 'start' });
		}
	}
</script>

<svelte:window on:keydown={handleKeydown} />

<div class="sidebar-wrapper">
	<!-- Top buttons container — matches Chats.svelte .top-buttons-container -->
	<div class="top-buttons-container">
		{#if isSearchBarVisible}
			<SearchBar
				onSearch={handleSearchQuery}
				onClose={handleSearchClose}
				initialQuery={searchQuery}
			/>
		{:else}
			<div class="top-buttons">
				<button
					class="clickable-icon icon_search top-button"
					aria-label="Search"
					onclick={openDocsSearch}
				></button>
				<button
					class="clickable-icon icon_close top-button right"
					aria-label="Close sidebar"
					onclick={onClose}
				></button>
			</div>
		{/if}
	</div>

	<!-- Scrollable content -->
	<div class="nav-scroll">
		{#if isSearchActive}
			<!-- Search results -->
			<div class="search-results">
				{#if searchResults.length === 0}
					<div class="no-results">{$text('documentation.search.no_results')}</div>
				{:else}
					{#each searchResults as result (result.slug)}
						{@const catInfo = getDocCategoryInfo(result.slug)}
						{@const gradColors = getCategoryGradientColors(catInfo.category)}
						{@const DocIcon = getLucideIcon(catInfo.icon)}
						<a href="/docs/{result.slug}" class="doc-item" class:active={isActive(result.slug)}>
							<div
								class="doc-icon-circle"
								style="background: linear-gradient(135deg, {gradColors?.start ??
									'#6366f1'}, {gradColors?.end ?? '#4f46e5'});"
							>
								{#if DocIcon}<DocIcon size={14} color="white" strokeWidth={2} />{/if}
							</div>
							<div class="doc-content">
								<span class="doc-title">{result.title}</span>
								<span class="doc-preview">{getSnippet(result.content)}</span>
							</div>
						</a>
					{/each}
				{/if}
			</div>
		{:else}
			<!-- TOC for active doc page -->
			{#if tocHeadings.length > 0 && activeDocSlug && activeDocSlug !== '' && !activeDocSlug.startsWith('api')}
				<div class="toc-section">
					<h2 class="group-title">{$text('documentation.toc.title')}</h2>
					{#each tocHeadings as heading (heading.id)}
						<button
							class="toc-item"
							class:toc-h3={heading.level === 3}
							onclick={() => scrollToHeading(heading.id)}
						>
							{heading.text}
						</button>
					{/each}
				</div>
				<div class="nav-separator"></div>
			{/if}

			<!-- API Reference link — uses gradient circle like all other items -->
			{@const apiCatInfo = getDocCategoryInfo('api')}
			{@const apiGradColors = getCategoryGradientColors(apiCatInfo.category)}
			{@const ApiIcon = getLucideIcon(apiCatInfo.icon)}
			<a
				href="/docs/api"
				class="doc-item"
				class:active={currentPath === '/docs/api' || currentPath === '/docs/api/'}
			>
				<div
					class="doc-icon-circle"
					style="background: linear-gradient(135deg, {apiGradColors?.start ??
						'#6366f1'}, {apiGradColors?.end ?? '#4f46e5'});"
				>
					{#if ApiIcon}<ApiIcon size={14} color="white" strokeWidth={2} />{/if}
				</div>
				<div class="doc-content">
					<span class="doc-title">{$text('documentation.api_reference')}</span>
				</div>
			</a>

			<div class="nav-separator"></div>

			<!-- Top-level files -->
			{#each structure.files as file (file.slug)}
				{@const catInfo = getDocCategoryInfo(file.slug)}
				{@const gradColors = getCategoryGradientColors(catInfo.category)}
				{@const FileIcon = getLucideIcon(catInfo.icon)}
				<a href="/docs/{file.slug}" class="doc-item" class:active={isActive(file.slug)}>
					<div
						class="doc-icon-circle"
						style="background: linear-gradient(135deg, {gradColors?.start ??
							'#6366f1'}, {gradColors?.end ?? '#4f46e5'});"
					>
						{#if FileIcon}<FileIcon size={14} color="white" strokeWidth={2} />{/if}
					</div>
					<div class="doc-content">
						<span class="doc-title">{file.title}</span>
					</div>
				</a>
			{/each}

			<!-- Folder groups -->
			{#each structure.folders as folder (folder.path)}
				{@const isExpanded = expandedFolders.has(folder.path)}
				{@const containsActive = folderContainsActive(folder)}
				{@const folderIcon = DOCS_FOLDER_ICON[folder.path] || 'folder'}
				<div class="folder-group">
					<button
						class="group-header"
						class:contains-active={containsActive}
						onclick={() => toggleFolder(folder.path)}
						aria-expanded={isExpanded}
					>
						<svg
							class="chevron"
							class:expanded={isExpanded}
							width="12"
							height="12"
							viewBox="0 0 16 16"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
						>
							<path d="M6 4l4 4-4 4" />
						</svg>
						<h2 class="group-title">{folder.title}</h2>
					</button>

					{#if isExpanded}
						<div class="folder-items">
							{#each folder.files as file (file.slug)}
								{@const catInfo = getDocCategoryInfo(file.slug)}
								{@const gradColors = getCategoryGradientColors(catInfo.category)}
								{@const FolderFileIcon = getLucideIcon(catInfo.icon)}
								<a
									href="/docs/{file.slug}"
									class="doc-item nested"
									class:active={isActive(file.slug)}
								>
									<div
										class="doc-icon-circle"
										style="background: linear-gradient(135deg, {gradColors?.start ??
											'#6366f1'}, {gradColors?.end ?? '#4f46e5'});"
									>
										{#if FolderFileIcon}<FolderFileIcon
												size={14}
												color="white"
												strokeWidth={2}
											/>{/if}
									</div>
									<div class="doc-content">
										<span class="doc-title">{file.title}</span>
									</div>
								</a>
							{/each}

							{#each folder.folders as subfolder (subfolder.path)}
								{@const subIsExpanded = expandedFolders.has(subfolder.path)}
								{@const subContainsActive = folderContainsActive(subfolder)}

								<button
									class="sub-folder-header"
									class:contains-active={subContainsActive}
									onclick={() => toggleFolder(subfolder.path)}
									aria-expanded={subIsExpanded}
								>
									<svg
										class="chevron"
										class:expanded={subIsExpanded}
										width="10"
										height="10"
										viewBox="0 0 16 16"
										fill="none"
										stroke="currentColor"
										stroke-width="2"
									>
										<path d="M6 4l4 4-4 4" />
									</svg>
									<span class="sub-folder-title">{subfolder.title}</span>
								</button>

								{#if subIsExpanded}
									{#each subfolder.files as file (file.slug)}
										{@const catInfo = getDocCategoryInfo(file.slug)}
										{@const gradColors = getCategoryGradientColors(catInfo.category)}
										{@const SubFileIcon = getLucideIcon(catInfo.icon)}
										<a
											href="/docs/{file.slug}"
											class="doc-item nested-2"
											class:active={isActive(file.slug)}
										>
											<div
												class="doc-icon-circle"
												style="background: linear-gradient(135deg, {gradColors?.start ??
													'#6366f1'}, {gradColors?.end ?? '#4f46e5'});"
											>
												{#if SubFileIcon}<SubFileIcon
														size={14}
														color="white"
														strokeWidth={2}
													/>{/if}
											</div>
											<div class="doc-content">
												<span class="doc-title">{file.title}</span>
											</div>
										</a>
									{/each}
								{/if}
							{/each}
						</div>
					{/if}
				</div>
			{/each}
		{/if}
	</div>
</div>

<style>
	.sidebar-wrapper {
		display: flex;
		flex-direction: column;
		height: 100%;
		background-color: var(--color-grey-20);
	}

	/* Top buttons container — matches Chats.svelte .top-buttons-container */
	.top-buttons-container {
		flex-shrink: 0;
		z-index: 10;
		background-color: var(--color-grey-20);
		padding: 16px 20px;
		border-bottom: 1px solid var(--color-grey-30);
	}

	.top-buttons {
		position: relative;
		height: 32px;
		display: flex;
		justify-content: flex-end;
	}

	.top-button {
		display: flex;
		align-items: center;
	}

	.top-button.right {
		margin-inline-start: auto;
	}

	/* Scrollable nav area */
	.nav-scroll {
		flex: 1;
		overflow-y: auto;
		padding: 0.5rem;
	}

	.nav-scroll::-webkit-scrollbar {
		width: 6px;
	}

	.nav-scroll::-webkit-scrollbar-track {
		background: transparent;
	}

	.nav-scroll::-webkit-scrollbar-thumb {
		background-color: var(--color-grey-40);
		border-radius: 3px;
	}

	/* Search results */
	.search-results {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.no-results {
		padding: 2rem 1rem;
		text-align: center;
		color: var(--color-font-secondary);
		font-size: 0.875rem;
	}

	/* Doc items — matches Chat.svelte item style */
	.doc-item {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.625rem 0.75rem;
		border-radius: 10px;
		text-decoration: none;
		color: var(--color-font-primary);
		transition: background-color 0.15s ease;
		cursor: pointer;
	}

	.doc-item:hover {
		background-color: var(--color-grey-30);
	}

	.doc-item.active {
		background-color: var(--color-grey-30);
	}

	.doc-item.nested {
		padding-inline-start: 1.5rem;
	}

	.doc-item.nested-2 {
		padding-inline-start: 2.25rem;
	}

	/* Gradient circle with Lucide icon for doc items */
	.doc-icon-circle {
		flex-shrink: 0;
		width: 28px;
		height: 28px;
		border-radius: 50%;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.doc-content {
		display: flex;
		flex-direction: column;
		min-width: 0;
		flex: 1;
	}

	.doc-title {
		font-size: 0.875rem;
		font-weight: 500;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.doc-preview {
		font-size: 0.75rem;
		color: var(--color-font-secondary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	/* Folder groups — matches chat time groups */
	.folder-group {
		margin-bottom: 0.25rem;
	}

	.group-header {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		width: 100%;
		padding: 0.5rem 0.75rem;
		background: none;
		border: none;
		cursor: pointer;
		text-align: start;
		border-radius: 8px;
		transition: background-color 0.15s ease;
	}

	.group-header:hover {
		background-color: var(--color-grey-30);
	}

	.group-header.contains-active {
		color: var(--color-primary);
	}

	.group-title {
		font-size: 0.75rem;
		font-weight: 600;
		text-transform: uppercase;
		color: var(--color-font-secondary);
		letter-spacing: 0.05em;
		margin: 0;
	}

	.group-header.contains-active .group-title {
		color: var(--color-primary);
	}

	.chevron {
		flex-shrink: 0;
		color: var(--color-font-secondary);
		transition: transform 0.2s ease;
	}

	.chevron.expanded {
		transform: rotate(90deg);
	}

	.folder-items {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.sub-folder-header {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		width: 100%;
		padding: 0.375rem 0.75rem;
		padding-inline-start: 1.5rem;
		background: none;
		border: none;
		cursor: pointer;
		text-align: start;
		border-radius: 8px;
		transition: background-color 0.15s ease;
	}

	.sub-folder-header:hover {
		background-color: var(--color-grey-30);
	}

	.sub-folder-header.contains-active {
		color: var(--color-primary);
	}

	.sub-folder-title {
		font-size: 0.8125rem;
		font-weight: 500;
		color: var(--color-font-secondary);
	}

	.sub-folder-header.contains-active .sub-folder-title {
		color: var(--color-primary);
	}

	.nav-separator {
		height: 1px;
		background-color: var(--color-grey-30);
		margin: 0.5rem 0.75rem;
	}

	/* TOC section */
	.toc-section {
		padding: 0.5rem;
	}

	.toc-section .group-title {
		padding: 0.25rem 0.5rem;
		margin-bottom: 0.25rem;
	}

	.toc-item {
		display: block;
		width: 100%;
		padding: 0.375rem 0.75rem;
		background: none;
		border: none;
		cursor: pointer;
		text-align: start;
		font-size: 0.8125rem;
		color: var(--color-font-secondary);
		border-radius: 6px;
		transition: all 0.15s ease;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.toc-item:hover {
		background-color: var(--color-grey-30);
		color: var(--color-font-primary);
	}

	.toc-item.toc-h3 {
		padding-inline-start: 1.5rem;
		font-size: 0.75rem;
	}
</style>
