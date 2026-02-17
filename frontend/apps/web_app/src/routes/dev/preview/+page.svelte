<!--
  Component Preview Index Page.
  Auto-discovers all .svelte components from @openmates/ui/src/components/
  using Vite's import.meta.glob() and displays them in a navigable tree.
  
  This is a dev-only tool for:
  - Browsing all UI components
  - Navigating to individual component previews
  - Quick search/filter across the component library
-->
<script lang="ts">
	/**
	 * Auto-discover all Svelte components in the UI package.
	 * import.meta.glob returns a record of module paths at build time.
	 * We only need the keys (paths), not the actual module loaders — hence { eager: false }.
	 */
	const componentModules = import.meta.glob(
		'/../../packages/ui/src/components/**/*.svelte',
		{ eager: false }
	);

	/**
	 * Strip the base path prefix to get clean relative component paths.
	 * e.g. "/../../packages/ui/src/components/embeds/web/WebSearchEmbedPreview.svelte"
	 *   -> "embeds/web/WebSearchEmbedPreview.svelte"
	 *
	 * Uses a regex to find the "components/" segment, since the exact prefix
	 * can vary between local dev and production builds (Vercel).
	 */
	function stripBasePath(fullPath: string): string {
		const marker = '/components/';
		const idx = fullPath.indexOf(marker);
		if (idx !== -1) {
			return fullPath.substring(idx + marker.length);
		}
		// Fallback: try the literal prefix
		const BASE_PATH = '/../../packages/ui/src/components/';
		if (fullPath.startsWith(BASE_PATH)) {
			return fullPath.substring(BASE_PATH.length);
		}
		return fullPath;
	}

	const componentPaths = Object.keys(componentModules)
		.map(stripBasePath)
		.sort();

	/**
	 * Build a tree structure from flat component paths for the sidebar navigation.
	 * Each node is either a directory (has children) or a file (leaf node).
	 */
	interface TreeNode {
		name: string;
		path: string;
		children: TreeNode[];
		isFile: boolean;
	}

	function buildTree(paths: string[]): TreeNode[] {
		const root: TreeNode[] = [];

		for (const filePath of paths) {
			const parts = filePath.split('/');
			let current = root;

			for (let i = 0; i < parts.length; i++) {
				const part = parts[i];
				const isFile = i === parts.length - 1;
				const currentPath = parts.slice(0, i + 1).join('/');

				let existing = current.find((n) => n.name === part);
				if (!existing) {
					existing = {
						name: part,
						path: currentPath,
						children: [],
						isFile
					};
					current.push(existing);
				}
				current = existing.children;
			}
		}

		return root;
	}

	/** Search/filter state */
	let searchQuery = $state('');

	/** Filtered paths based on search query (case-insensitive match on filename) */
	let filteredPaths = $derived(
		searchQuery.trim()
			? componentPaths.filter((p) =>
					p.toLowerCase().includes(searchQuery.toLowerCase())
				)
			: componentPaths
	);

	/** Filtered tree built from filtered paths */
	let filteredTree = $derived(buildTree(filteredPaths));

	/** Track which directories are expanded */
	let expandedDirs = $state<Set<string>>(new Set());

	/** Toggle a directory's expanded state */
	function toggleDir(path: string) {
		const next = new Set(expandedDirs);
		if (next.has(path)) {
			next.delete(path);
		} else {
			next.add(path);
		}
		expandedDirs = next;
	}

	/** Expand all directories (useful after search) */
	function expandAll() {
		const allDirs = new Set<string>();
		for (const p of filteredPaths) {
			const parts = p.split('/');
			for (let i = 1; i < parts.length; i++) {
				allDirs.add(parts.slice(0, i).join('/'));
			}
		}
		expandedDirs = allDirs;
	}

	/** Collapse all directories */
	function collapseAll() {
		expandedDirs = new Set();
	}

	/**
	 * When search query changes, auto-expand all directories
	 * to show matching results immediately.
	 */
	$effect(() => {
		if (searchQuery.trim()) {
			expandAll();
		}
	});

	/**
	 * Build the preview URL for a component.
	 * Strips the .svelte extension since SvelteKit handles routing.
	 */
	function getPreviewUrl(filePath: string): string {
		return `/dev/preview/${filePath.replace('.svelte', '')}`;
	}
</script>

<div class="preview-index">
	<header class="preview-header">
		<h1>Component Preview</h1>
		<p class="component-count">{componentPaths.length} components</p>
	</header>

	<div class="search-bar">
		<input
			type="text"
			placeholder="Search components..."
			bind:value={searchQuery}
		/>
		<div class="search-actions">
			<button onclick={expandAll}>Expand all</button>
			<button onclick={collapseAll}>Collapse all</button>
		</div>
	</div>

	<nav class="component-tree">
		{#snippet renderTree(nodes: TreeNode[], depth: number)}
			{#each nodes as node}
				{#if node.isFile}
					<a
						class="tree-file"
						href={getPreviewUrl(node.path)}
						style="padding-left: {depth * 16 + 12}px"
					>
						<span class="file-icon">◆</span>
						<span class="file-name">{node.name.replace('.svelte', '')}</span>
					</a>
				{:else}
					<button
						class="tree-dir"
						class:expanded={expandedDirs.has(node.path)}
						onclick={() => toggleDir(node.path)}
						style="padding-left: {depth * 16 + 12}px"
					>
						<span class="dir-arrow">{expandedDirs.has(node.path) ? '▼' : '▶'}</span>
						<span class="dir-name">{node.name}</span>
						<span class="dir-count">{node.children.length}</span>
					</button>
					{#if expandedDirs.has(node.path)}
						{@render renderTree(node.children, depth + 1)}
					{/if}
				{/if}
			{/each}
		{/snippet}

		{#if filteredTree.length > 0}
			{@render renderTree(filteredTree, 0)}
		{:else}
			<p class="no-results">No components match "{searchQuery}"</p>
		{/if}
	</nav>
</div>

<style>
	.preview-index {
		max-width: 800px;
		margin: 0 auto;
		padding: 32px 24px;
		font-family: 'Lexend Deca', sans-serif;
		color: var(--color-font-primary);
	}

	.preview-header {
		margin-bottom: 24px;
	}

	.preview-header h1 {
		font-size: 28px;
		font-weight: 600;
		margin: 0 0 4px;
	}

	.component-count {
		font-size: 14px;
		color: var(--color-font-tertiary);
		margin: 0;
	}

	.search-bar {
		margin-bottom: 16px;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.search-bar input {
		width: 100%;
		padding: 10px 14px;
		border: 1px solid var(--color-grey-30);
		border-radius: 8px;
		background: var(--color-grey-10);
		color: var(--color-font-primary);
		font-size: 14px;
		font-family: 'Lexend Deca', sans-serif;
		outline: none;
		box-sizing: border-box;
	}

	.search-bar input:focus {
		border-color: var(--color-primary-start);
	}

	.search-bar input::placeholder {
		color: var(--color-font-field-placeholder);
	}

	.search-actions {
		display: flex;
		gap: 8px;
	}

	.search-actions button {
		padding: 4px 10px;
		border: 1px solid var(--color-grey-30);
		border-radius: 6px;
		background: var(--color-grey-10);
		color: var(--color-font-tertiary);
		font-size: 12px;
		cursor: pointer;
		font-family: 'Lexend Deca', sans-serif;
	}

	.search-actions button:hover {
		background: var(--color-grey-20);
		color: var(--color-font-primary);
	}

	.component-tree {
		display: flex;
		flex-direction: column;
	}

	.tree-file {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 6px 12px;
		border-radius: 6px;
		text-decoration: none;
		color: var(--color-font-primary);
		font-size: 13px;
		cursor: pointer;
		transition: background-color 0.15s;
	}

	.tree-file:hover {
		background: var(--color-grey-20);
	}

	.file-icon {
		font-size: 8px;
		color: var(--color-primary-start);
	}

	.file-name {
		font-family: 'Courier New', monospace;
		font-size: 13px;
	}

	.tree-dir {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 6px 12px;
		border: none;
		border-radius: 6px;
		background: none;
		color: var(--color-font-primary);
		font-size: 13px;
		cursor: pointer;
		width: 100%;
		text-align: left;
		font-family: 'Lexend Deca', sans-serif;
		transition: background-color 0.15s;
	}

	.tree-dir:hover {
		background: var(--color-grey-20);
	}

	.dir-arrow {
		font-size: 10px;
		width: 12px;
		text-align: center;
		color: var(--color-font-tertiary);
	}

	.dir-name {
		font-weight: 500;
	}

	.dir-count {
		font-size: 11px;
		color: var(--color-font-tertiary);
		margin-left: auto;
	}

	.no-results {
		font-size: 14px;
		color: var(--color-font-tertiary);
		text-align: center;
		padding: 24px 0;
	}
</style>
