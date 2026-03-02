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
  - Background options (auto = follows theme, grid = checkered) for visual inspection
  - Prop editor for overriding mock props
-->
<script lang="ts">
	import { page } from '$app/state';
	import { mount, unmount } from 'svelte';
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

	/** Render error state — caught when component crashes during mount */
	let renderError = $state<string | null>(null);

	/** Target element for programmatic component mounting */
	let mountTarget = $state<HTMLElement | null>(null);

	/** Reference to the currently mounted component instance (for cleanup) */
	let mountedInstance: Record<string, unknown> | null = null;

	/** Mock props from the preview file */
	let mockProps = $state<Record<string, unknown>>({});
	let variants = $state<Record<string, Record<string, unknown>>>({});
	let activeVariant = $state<string>('default');
	let hasPreviewFile = $state(false);

	/** UI state for the preview controls */
	let viewportWidth = $state<number | null>(null);
	/**
	 * Background mode for the preview canvas.
	 * - 'auto': follows the current theme (white in light mode, dark in dark mode) — DEFAULT
	 * - 'grid': checkered grid pattern (useful for transparency inspection)
	 */
	let background = $state<'auto' | 'grid'>('auto');
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

	/**
	 * Programmatically mount the loaded component into the target div.
	 * Uses Svelte's mount() API inside a try/catch to gracefully handle
	 * components that crash during render (e.g. missing required snippet props).
	 *
	 * We also listen for unhandled errors (window 'error' event) because
	 * Svelte mount() can throw asynchronously during the render microtask,
	 * bypassing the synchronous try/catch.
	 */
	$effect(() => {
		// Read reactive deps to trigger re-runs on variant/prop changes.
		const component = loadedComponent;
		const props = effectiveProps;
		const target = mountTarget;
		const hasError = renderError;

		if (!component || !target) return;

		// Skip mounting if there's a render error — user must click Retry
		// to clear renderError, which will cause this effect to re-run
		// (because we read renderError above as a dependency).
		if (hasError) return;

		// Clean up previous mount
		cleanupMount(target);

		// Catch async render errors via window error handler
		let errorCaught = false;
		function handleError(event: ErrorEvent) {
			if (!errorCaught) {
				errorCaught = true;
				renderError = event.error?.message || event.message || 'Unknown render error';
				cleanupMount(target);
			}
			event.preventDefault();
		}
		window.addEventListener('error', handleError);

		try {
			// eslint-disable-next-line @typescript-eslint/no-explicit-any -- dynamic glob import yields unknown type
			mountedInstance = mount(component as any, { target, props });
		} catch (err) {
			errorCaught = true;
			renderError = err instanceof Error ? err.message : String(err);
			cleanupMount(target);
		}

		// If mount succeeded synchronously but might fail asynchronously,
		// keep the error listener for a brief period then remove it.
		const timerId = setTimeout(() => {
			window.removeEventListener('error', handleError);
		}, 500);

		return () => {
			clearTimeout(timerId);
			window.removeEventListener('error', handleError);
			cleanupMount(target);
		};
	});

	/** Safely unmount and clear the mount target */
	function cleanupMount(target: HTMLElement | null) {
		if (mountedInstance) {
			try {
				unmount(mountedInstance);
			} catch {
				// Ignore cleanup errors
			}
			mountedInstance = null;
		}
		if (target) {
			target.innerHTML = '';
		}
	}

	/** Retry rendering after a render error (e.g. after editing props) */
	function retryRender() {
		renderError = null;
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

	/**
	 * Background options for the preview canvas.
	 * 'auto' follows the selected theme automatically.
	 * 'grid' shows a checkered pattern for inspecting transparency.
	 */
	const backgroundOptions: { label: string; value: typeof background }[] = [
		{ label: 'Auto', value: 'auto' },
		{ label: 'Grid', value: 'grid' }
	];

	/**
	 * Background CSS for the preview container.
	 * 'auto' uses CSS variables so it reacts to the data-theme attribute —
	 * var(--color-grey-0) resolves to white in light mode and near-black in dark mode.
	 * 'grid' renders a checkered pattern; grid colors also adapt to the theme.
	 */
	let backgroundStyle = $derived.by(() => {
		switch (background) {
			case 'grid':
				// Use theme-aware colors for the grid squares so it looks right
				// in both light and dark mode.
				return `background-color: var(--color-grey-0);
					background-image: linear-gradient(45deg, var(--color-grey-20) 25%, transparent 25%),
					linear-gradient(-45deg, var(--color-grey-20) 25%, transparent 25%),
					linear-gradient(45deg, transparent 75%, var(--color-grey-20) 75%),
					linear-gradient(-45deg, transparent 75%, var(--color-grey-20) 75%);
					background-size: 20px 20px;
					background-position: 0 0, 0 10px, 10px -10px, -10px 0px;`;
			case 'auto':
			default:
				// Follows the theme: white in light mode, dark in dark mode.
				return 'background: var(--color-grey-0);';
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
			<!-- Label is pinned left; buttons scroll independently -->
			<span class="variant-label">Variants:</span>
			<div class="variant-scroll">
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
		</div>
	{/if}

	<div class="preview-layout">
		<!-- Props editor panel (side panel) -->
		{#if showPropsEditor}
			<aside class="props-panel">
				<div class="props-header">
					<h3>Props</h3>
					{#if hasManualEdits}
						<button class="props-reset" onclick={resetManualOverrides}> Reset </button>
					{/if}
				</div>
				{#if !hasPreviewFile}
					<p class="props-hint">
						No <code>.preview.ts</code> file found.<br />
						Create <code>{componentName}.preview.ts</code> next to the component to define mock props
						and variants.
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
			<!--
				Viewport wrapper: when a preset width is selected, this div constrains the
				content width and shows dashed cutoff lines at both sides so the developer
				can clearly see where the viewport edge falls relative to the component.
			-->
			<div
				class="preview-viewport"
				class:preview-viewport--constrained={viewportWidth !== null}
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
						Component is mounted programmatically via mount() in an $effect
						to catch render crashes from components with missing required props.
						
						IMPORTANT: The mount target div is ALWAYS present in the DOM to
						avoid timing issues with bind:this. When a render error occurs,
						we hide it with display:none and show the error panel instead.
						If we conditionally rendered the div ({#if}/{:else}), bind:this
						could be null when the $effect runs after a retry.
					-->
					{#if renderError}
						<div class="preview-state render-error">
							<h2>Render Error</h2>
							<p class="error-message">{renderError}</p>
							<p class="hint">
								This component likely requires props that aren't provided.
								{#if !hasPreviewFile}
									Create a <code>{componentName}.preview.ts</code> file next to the component to define
									mock props.
								{:else}
									Check the <strong>.preview.ts</strong> file — the mock props may be missing required
									fields.
								{/if}
							</p>
							<div class="error-actions">
								<button class="error-btn" onclick={retryRender}>Retry</button>
								<button class="error-btn" onclick={() => (showPropsEditor = true)}>
									Edit Props
								</button>
							</div>
						</div>
					{/if}
					<div
						class="component-mount"
						bind:this={mountTarget}
						style:display={renderError ? 'none' : 'block'}
					></div>
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
		/* Prevent the bar itself from wrapping or overflowing */
		min-width: 0;
		overflow: hidden;
	}

	.variant-label {
		font-size: 12px;
		color: var(--color-font-tertiary);
		/* Pin the label in place while the scroll container scrolls */
		flex-shrink: 0;
	}

	/* Scrollable inner container for variant buttons */
	.variant-scroll {
		display: flex;
		align-items: center;
		gap: 8px;
		overflow-x: auto;
		/* Hide the scrollbar visually but keep it functional */
		scrollbar-width: none;
		-ms-overflow-style: none;
		flex: 1;
		min-width: 0;
		padding-bottom: 2px; /* avoid clipping box-shadow on focused buttons */
	}

	.variant-scroll::-webkit-scrollbar {
		display: none;
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
		/* Prevent buttons from shrinking when there are many */
		flex-shrink: 0;
		white-space: nowrap;
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

	/**
	 * When a viewport preset is active, show dashed lines at both sides of the
	 * constrained content area. This makes it immediately clear where the
	 * viewport edge falls — useful for testing responsive behaviour.
	 *
	 * We use box-shadow (inset) so the indicator doesn't affect layout.
	 * A subtle left/right border with a dash pattern created via outline-offset
	 * won't work reliably, so instead we use a pseudo-element approach:
	 * left and right dashed borders rendered via the ::before/::after pseudo-elements
	 * positioned outside the content but still inside the scrollable container.
	 */
	.preview-viewport--constrained {
		position: relative;
	}

	.preview-viewport--constrained::before,
	.preview-viewport--constrained::after {
		content: '';
		position: absolute;
		top: 0;
		bottom: 0;
		width: 0;
		/* Dashed line rendered as a border on the pseudo-element */
		border-style: dashed;
		border-color: var(--color-primary-start);
		border-width: 0;
		opacity: 0.5;
		pointer-events: none;
	}

	/* Left cutoff line */
	.preview-viewport--constrained::before {
		left: 0;
		border-left-width: 1px;
	}

	/* Right cutoff line */
	.preview-viewport--constrained::after {
		right: 0;
		border-right-width: 1px;
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

	.preview-state .hint code {
		background: var(--color-grey-20);
		padding: 1px 4px;
		border-radius: 3px;
		font-size: 11px;
	}

	.preview-state.render-error {
		color: var(--color-font-primary);
		background: var(--color-grey-10);
		border: 1px solid #e5393550;
		border-radius: 12px;
		padding: 24px;
		max-width: 500px;
		margin: 24px auto;
	}

	.preview-state.render-error h2 {
		color: #e53935;
	}

	.error-message {
		font-family: 'Courier New', monospace;
		font-size: 12px;
		color: #e53935;
		background: var(--color-grey-20);
		padding: 8px 12px;
		border-radius: 6px;
		word-break: break-word;
		text-align: left;
	}

	.error-actions {
		display: flex;
		gap: 8px;
		margin-top: 12px;
		justify-content: center;
	}

	.error-btn {
		padding: 6px 16px;
		border: 1px solid var(--color-grey-30);
		border-radius: 6px;
		background: var(--color-grey-10);
		color: var(--color-font-primary);
		font-size: 13px;
		cursor: pointer;
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
	}

	.error-btn:hover {
		background: var(--color-grey-20);
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
