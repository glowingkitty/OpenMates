<!--
  Dynamic Component Preview Page.
  Renders any Svelte component from @openmates/ui based on the URL path.
  
  URL pattern: /dev/preview/<component-path-without-.svelte>
  Example: /dev/preview/embeds/web/WebSearchEmbedPreview
    -> renders frontend/packages/ui/src/components/embeds/web/WebSearchEmbedPreview.svelte
  
  Features:
  - Auto-loads the component from the URL path
  - Loads .preview.ts companion file for mock props (if it exists)
  - Theme toggle (light/dark)
  - Viewport resize controls for responsive testing
  - Background options (transparent, white, grey, dark) for visual inspection
  - Prop editor for overriding mock props
-->
<script lang="ts">
	import { page } from '$app/state';
	import { theme } from '@repo/ui';

	/**
	 * Vite glob imports for all Svelte components and their preview files.
	 * These are lazy-loaded (eager: false) so we only load what's needed.
	 */
	const componentModules = import.meta.glob<{ default: unknown }>(
		'/../../packages/ui/src/components/**/*.svelte',
		{ eager: false }
	);

	/**
	 * Preview files provide mock props for components.
	 * Convention: ComponentName.preview.ts next to ComponentName.svelte
	 * Each preview file should export:
	 *   - default: Record<string, unknown> (default props)
	 *   - variants?: Record<string, Record<string, unknown>> (named prop sets)
	 */
	const previewModules = import.meta.glob<{
		default: Record<string, unknown>;
		variants?: Record<string, Record<string, unknown>>;
	}>('/../../packages/ui/src/components/**/*.preview.ts', { eager: false });

	/**
	 * Build lookup maps from glob keys to clean component paths.
	 * The glob keys can vary between dev and production builds, so we
	 * extract the path relative to the "components/" directory marker.
	 */
	function extractCleanPath(fullPath: string): string {
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

	/** Map clean path (without extension) -> glob key for components */
	const componentKeyMap = new Map<string, string>();
	for (const key of Object.keys(componentModules)) {
		const clean = extractCleanPath(key).replace('.svelte', '');
		componentKeyMap.set(clean, key);
	}

	/** Map clean path (without extension) -> glob key for preview files */
	const previewKeyMap = new Map<string, string>();
	for (const key of Object.keys(previewModules)) {
		const clean = extractCleanPath(key).replace('.preview.ts', '');
		previewKeyMap.set(clean, key);
	}

	/** The component path from the URL (without .svelte extension) */
	let componentPath = $derived(page.params.path || '');

	/** Look up glob keys using the clean path */
	let moduleKey = $derived(componentKeyMap.get(componentPath) || '');
	let previewKey = $derived(previewKeyMap.get(componentPath) || '');

	/** Component loading state */
	let loadedComponent = $state<unknown>(null);
	let loadError = $state<string | null>(null);
	let isLoading = $state(true);

	/** Mock props from the preview file */
	let mockProps = $state<Record<string, unknown>>({});
	let variants = $state<Record<string, Record<string, unknown>>>({});
	let activeVariant = $state<string>('default');
	let hasPreviewFile = $state(false);

	/** UI state for the preview controls */
	let viewportWidth = $state<number | null>(null);
	let background = $state<'transparent' | 'white' | 'grey' | 'dark'>('white');
	let showPropsEditor = $state(false);
	let propsError = $state<string | null>(null);

	/**
	 * Manual prop overrides from the JSON editor.
	 * Starts empty — only applied when the user explicitly edits props.
	 * This prevents the JSON editor from silently overriding variant selections.
	 */
	let manualOverrides = $state<Record<string, unknown>>({});
	let hasManualEdits = $state(false);

	/**
	 * Computed props: merges mock props, variant overrides, and manual edits.
	 * Priority: default props < variant overrides < manual JSON edits
	 */
	let effectiveProps = $derived.by(() => {
		const base = { ...mockProps };

		// Apply active variant overrides (replaces matching keys from defaults)
		if (activeVariant !== 'default' && variants[activeVariant]) {
			Object.assign(base, variants[activeVariant]);
		}

		// Apply manual JSON editor overrides only if user has made edits
		if (hasManualEdits) {
			Object.assign(base, manualOverrides);
		}

		return base;
	});

	/**
	 * Editable JSON string for the props editor textarea.
	 * Synced to effectiveProps when variant changes, but independently
	 * editable by the user. User edits are parsed into manualOverrides.
	 */
	let propsJson = $state('{}');

	/** Sync the editor contents when effectiveProps changes due to variant switch */
	$effect(() => {
		if (!hasManualEdits) {
			propsJson = JSON.stringify(effectiveProps, null, 2);
		}
	});

	/**
	 * Load the component and its preview file whenever the path changes.
	 */
	$effect(() => {
		loadComponent(moduleKey, previewKey);
	});

	async function loadComponent(modKey: string, prevKey: string) {
		isLoading = true;
		loadError = null;
		loadedComponent = null;
		hasPreviewFile = false;
		mockProps = {};
		variants = {};
		activeVariant = 'default';
		manualOverrides = {};
		hasManualEdits = false;
		propsError = null;

		try {
			// Check if the component exists in the glob map
			if (!modKey || !componentModules[modKey]) {
				loadError = `Component not found: ${componentPath}.svelte`;
				isLoading = false;
				return;
			}

			// Load the component module
			const mod = await componentModules[modKey]();
			loadedComponent = mod.default;

			// Try to load preview props if a companion .preview.ts exists
			if (prevKey && previewModules[prevKey]) {
				try {
					const preview = await previewModules[prevKey]();
					mockProps = preview.default || {};
					variants = preview.variants || {};
					hasPreviewFile = true;
				} catch (err) {
					console.warn(`[Preview] Failed to load preview file for ${componentPath}:`, err);
				}
			}
		} catch (err) {
			loadError = `Failed to load component: ${err instanceof Error ? err.message : String(err)}`;
		} finally {
			isLoading = false;
		}
	}

	/** Toggle between light and dark theme */
	function toggleTheme() {
		theme.set($theme === 'light' ? 'dark' : 'light');
	}

	/** Parse the component name from the full path (for display) */
	let componentName = $derived(componentPath.split('/').pop() || 'Unknown');

	/** Parse the directory path (for breadcrumb) */
	let directoryPath = $derived(componentPath.split('/').slice(0, -1).join('/'));

	/** Viewport preset options */
	const viewportPresets = [
		{ label: 'Auto', value: null },
		{ label: 'Mobile', value: 375 },
		{ label: 'Tablet', value: 768 },
		{ label: 'Desktop', value: 1440 }
	];

	/** Background options */
	const backgroundOptions: { label: string; value: typeof background }[] = [
		{ label: 'White', value: 'white' },
		{ label: 'Grey', value: 'grey' },
		{ label: 'Dark', value: 'dark' },
		{ label: 'Grid', value: 'transparent' }
	];

	/** Background CSS for the preview container */
	let backgroundStyle = $derived.by(() => {
		switch (background) {
			case 'white':
				return 'background: #ffffff;';
			case 'grey':
				return 'background: var(--color-grey-20);';
			case 'dark':
				return 'background: #1a1a1a;';
			case 'transparent':
				return `background-image: linear-gradient(45deg, #e0e0e0 25%, transparent 25%),
					linear-gradient(-45deg, #e0e0e0 25%, transparent 25%),
					linear-gradient(45deg, transparent 75%, #e0e0e0 75%),
					linear-gradient(-45deg, transparent 75%, #e0e0e0 75%);
					background-size: 20px 20px;
					background-position: 0 0, 0 10px, 10px -10px, -10px 0px;`;
			default:
				return 'background: #ffffff;';
		}
	});

	/**
	 * Handle manual props JSON input.
	 * Parses the JSON and sets manual overrides. Validates inline.
	 */
	function handlePropsInput(event: Event) {
		const target = event.target as HTMLTextAreaElement;
		propsJson = target.value;
		hasManualEdits = true;
		try {
			const parsed = JSON.parse(propsJson);
			if (typeof parsed === 'object' && parsed !== null) {
				manualOverrides = parsed;
				propsError = null;
			}
		} catch (err) {
			propsError = err instanceof Error ? err.message : 'Invalid JSON';
		}
	}

	/** Reset manual overrides (called when user wants to revert edits) */
	function resetManualOverrides() {
		manualOverrides = {};
		hasManualEdits = false;
		propsError = null;
	}
</script>

<div class="preview-page">
	<!-- Top toolbar -->
	<header class="toolbar">
		<div class="toolbar-left">
			<a href="/dev/preview" class="back-link">← Components</a>
			<span class="breadcrumb">
				{#if directoryPath}
					<span class="breadcrumb-dir">{directoryPath}/</span>
				{/if}
				<span class="breadcrumb-name">{componentName}</span>
			</span>
		</div>

		<div class="toolbar-right">
			<!-- Viewport presets -->
			<div class="control-group">
				{#each viewportPresets as preset}
					<button
						class="control-btn"
						class:active={viewportWidth === preset.value}
						onclick={() => (viewportWidth = preset.value)}
					>
						{preset.label}
						{#if preset.value}
							<span class="control-detail">{preset.value}px</span>
						{/if}
					</button>
				{/each}
			</div>

			<!-- Background options -->
			<div class="control-group">
				{#each backgroundOptions as bg}
					<button
						class="control-btn"
						class:active={background === bg.value}
						onclick={() => (background = bg.value)}
					>
						{bg.label}
					</button>
				{/each}
			</div>

			<!-- Theme toggle -->
			<button class="control-btn" onclick={toggleTheme}>
				{$theme === 'light' ? '🌙' : '☀️'}
			</button>

			<!-- Props editor toggle -->
			<button
				class="control-btn"
				class:active={showPropsEditor}
				onclick={() => (showPropsEditor = !showPropsEditor)}
			>
				Props
			</button>
		</div>
	</header>

	<!-- Variant selector (only shown when preview file has variants) -->
	{#if Object.keys(variants).length > 0}
		<div class="variant-bar">
			<span class="variant-label">Variants:</span>
			<button
				class="variant-btn"
				class:active={activeVariant === 'default'}
				onclick={() => (activeVariant = 'default')}
			>
				Default
			</button>
			{#each Object.keys(variants) as variantName}
				<button
					class="variant-btn"
					class:active={activeVariant === variantName}
					onclick={() => (activeVariant = variantName)}
				>
					{variantName}
				</button>
			{/each}
		</div>
	{/if}

	<div class="preview-layout">
		<!-- Props editor panel (side panel) -->
		{#if showPropsEditor}
			<aside class="props-panel">
				<div class="props-header">
					<h3>Props</h3>
					{#if hasManualEdits}
						<button class="props-reset" onclick={resetManualOverrides}>
							Reset
						</button>
					{/if}
				</div>
				{#if !hasPreviewFile}
					<p class="props-hint">
						No <code>.preview.ts</code> file found.<br />
						Create <code>{componentName}.preview.ts</code> next to the component
						to define mock props and variants.
					</p>
				{/if}
				<textarea
					class="props-editor"
					value={propsJson}
					oninput={handlePropsInput}
					spellcheck="false"
				></textarea>
				{#if propsError}
					<p class="props-error">{propsError}</p>
				{/if}
			</aside>
		{/if}

		<!-- Component render area -->
		<div class="preview-container" style={backgroundStyle}>
			<div
				class="preview-viewport"
				style={viewportWidth ? `max-width: ${viewportWidth}px; margin: 0 auto;` : ''}
			>
				{#if isLoading}
					<div class="preview-state">
						<p>Loading component...</p>
					</div>
				{:else if loadError}
					<div class="preview-state error">
						<h2>Error</h2>
						<p>{loadError}</p>
						<p class="hint">
							Make sure the component path is correct. Browse
							<a href="/dev/preview">all components</a>.
						</p>
					</div>
				{:else if loadedComponent}
					<!-- 
						Render the dynamically loaded component with effective props.
						Wrapped in an error boundary div — Svelte doesn't have native error boundaries,
						but this at least contains the component.
					-->
					<div class="component-mount">
						{#key componentPath + activeVariant}
							{@const Component = loadedComponent}
							<Component {...effectiveProps} />
						{/key}
					</div>
				{/if}
			</div>
		</div>
	</div>

	<!-- Status bar -->
	<footer class="status-bar">
		<span class="status-item">
			{componentPath}.svelte
		</span>
		{#if hasPreviewFile}
			<span class="status-item status-preview">preview.ts loaded</span>
		{:else}
			<span class="status-item status-no-preview">no preview.ts</span>
		{/if}
		{#if viewportWidth}
			<span class="status-item">{viewportWidth}px</span>
		{/if}
		<span class="status-item">{$theme} theme</span>
	</footer>
</div>

<style>
	.preview-page {
		display: flex;
		flex-direction: column;
		height: 100vh;
		overflow: hidden;
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
		color: var(--color-font-primary);
	}

	/* --- Toolbar --- */
	.toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 8px 16px;
		background: var(--color-grey-10);
		border-bottom: 1px solid var(--color-grey-25);
		flex-shrink: 0;
		gap: 12px;
		flex-wrap: wrap;
	}

	.toolbar-left {
		display: flex;
		align-items: center;
		gap: 12px;
		min-width: 0;
	}

	.toolbar-right {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}

	.back-link {
		font-size: 13px;
		color: var(--color-primary-start);
		text-decoration: none;
		white-space: nowrap;
	}

	.back-link:hover {
		text-decoration: underline;
	}

	.breadcrumb {
		font-size: 13px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.breadcrumb-dir {
		color: var(--color-font-tertiary);
	}

	.breadcrumb-name {
		font-weight: 600;
	}

	.control-group {
		display: flex;
		border: 1px solid var(--color-grey-30);
		border-radius: 6px;
		overflow: hidden;
	}

	.control-btn {
		padding: 4px 10px;
		border: none;
		background: var(--color-grey-10);
		color: var(--color-font-primary);
		font-size: 12px;
		cursor: pointer;
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
		white-space: nowrap;
		transition: background-color 0.15s;
	}

	.control-group .control-btn {
		border-right: 1px solid var(--color-grey-30);
	}

	.control-group .control-btn:last-child {
		border-right: none;
	}

	.control-btn:hover {
		background: var(--color-grey-20);
	}

	.control-btn.active {
		background: var(--color-primary-start);
		color: #fff;
	}

	.control-detail {
		font-size: 10px;
		opacity: 0.7;
		margin-left: 2px;
	}

	/* --- Variant bar --- */
	.variant-bar {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 6px 16px;
		background: var(--color-grey-10);
		border-bottom: 1px solid var(--color-grey-25);
		flex-shrink: 0;
	}

	.variant-label {
		font-size: 12px;
		color: var(--color-font-tertiary);
	}

	.variant-btn {
		padding: 3px 10px;
		border: 1px solid var(--color-grey-30);
		border-radius: 4px;
		background: var(--color-grey-10);
		color: var(--color-font-primary);
		font-size: 12px;
		cursor: pointer;
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
	}

	.variant-btn.active {
		background: var(--color-primary-start);
		color: #fff;
		border-color: var(--color-primary-start);
	}

	.variant-btn:hover:not(.active) {
		background: var(--color-grey-20);
	}

	/* --- Main preview area --- */
	.preview-layout {
		display: flex;
		flex: 1;
		overflow: hidden;
	}

	.props-panel {
		width: 320px;
		flex-shrink: 0;
		padding: 16px;
		background: var(--color-grey-10);
		border-right: 1px solid var(--color-grey-25);
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.props-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.props-panel h3 {
		font-size: 14px;
		font-weight: 600;
		margin: 0;
	}

	.props-reset {
		padding: 2px 8px;
		border: 1px solid var(--color-grey-30);
		border-radius: 4px;
		background: var(--color-grey-10);
		color: var(--color-font-tertiary);
		font-size: 11px;
		cursor: pointer;
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
	}

	.props-reset:hover {
		background: var(--color-grey-20);
		color: var(--color-font-primary);
	}

	.props-hint {
		font-size: 12px;
		color: var(--color-font-tertiary);
		line-height: 1.5;
		margin: 0;
	}

	.props-hint code {
		background: var(--color-grey-20);
		padding: 1px 4px;
		border-radius: 3px;
		font-size: 11px;
	}

	.props-editor {
		width: 100%;
		min-height: 200px;
		flex: 1;
		padding: 10px;
		border: 1px solid var(--color-grey-30);
		border-radius: 6px;
		background: var(--color-grey-0);
		color: var(--color-font-primary);
		font-family: 'Courier New', monospace;
		font-size: 12px;
		line-height: 1.5;
		resize: none;
		outline: none;
		box-sizing: border-box;
	}

	.props-editor:focus {
		border-color: var(--color-primary-start);
	}

	.props-error {
		font-size: 11px;
		color: #e53935;
		margin: 0;
	}

	.preview-container {
		flex: 1;
		overflow: auto;
		padding: 24px;
	}

	.preview-viewport {
		width: 100%;
	}

	.component-mount {
		min-height: 50px;
	}

	.preview-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 48px 24px;
		text-align: center;
		color: var(--color-font-tertiary);
	}

	.preview-state.error {
		color: #e53935;
	}

	.preview-state h2 {
		font-size: 18px;
		margin: 0 0 8px;
	}

	.preview-state p {
		font-size: 14px;
		margin: 0 0 4px;
	}

	.preview-state .hint {
		font-size: 12px;
		color: var(--color-font-tertiary);
	}

	.preview-state .hint a {
		color: var(--color-primary-start);
	}

	/* --- Status bar --- */
	.status-bar {
		display: flex;
		align-items: center;
		gap: 16px;
		padding: 4px 16px;
		background: var(--color-grey-10);
		border-top: 1px solid var(--color-grey-25);
		flex-shrink: 0;
		font-size: 11px;
		color: var(--color-font-tertiary);
	}

	.status-item {
		font-family: 'Courier New', monospace;
	}

	.status-preview {
		color: #43a047;
	}

	.status-no-preview {
		color: var(--color-font-secondary);
	}
</style>
