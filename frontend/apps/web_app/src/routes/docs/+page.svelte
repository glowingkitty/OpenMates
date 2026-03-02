<script lang="ts">
	/**
	 * Docs Index Page
	 *
	 * Landing page for documentation at /docs
	 * Displays:
	 * - Welcome message
	 * - Quick links to main documentation sections
	 * - Search prompt
	 */
	import docsData from '$lib/generated/docs-data.json';
	import type { DocFolder } from '$lib/types/docs';

	// Get the documentation structure
	const { structure } = docsData;

	// Extract main sections (top-level folders)
	const mainSections = structure.folders.map((folder) => ({
		title: folder.title,
		path: `/docs/${folder.path}`,
		description: getFirstFileDescription(folder as DocFolder),
		fileCount: countAllFiles(folder as DocFolder)
	}));

	/**
	 * Get a short description from the first file in a folder
	 */
	function getFirstFileDescription(folder: DocFolder): string {
		if (folder.files.length > 0) {
			// Extract first paragraph from plain text
			const text = folder.files[0].plainText || '';
			const firstParagraph = text.split('\n')[0] || '';
			return firstParagraph.substring(0, 150) + (firstParagraph.length > 150 ? '...' : '');
		}
		return 'Documentation section';
	}

	/**
	 * Count all files in a folder recursively
	 */
	function countAllFiles(folder: DocFolder): number {
		let count = folder.files.length;
		for (const subfolder of folder.folders) {
			count += countAllFiles(subfolder);
		}
		return count;
	}
</script>

<svelte:head>
	<title>Documentation | OpenMates</title>
	<meta
		name="description"
		content="OpenMates documentation - guides, architecture, and API reference"
	/>
</svelte:head>

<div class="docs-index">
	<header class="docs-hero">
		<h1>OpenMates Documentation</h1>
		<p class="hero-description">
			Guides, architecture documentation, and API reference for OpenMates.
		</p>
	</header>

	<section class="quick-links">
		<h2>Browse Documentation</h2>
		<div class="section-grid">
			{#each mainSections as section}
				<a href={section.path} class="section-card">
					<h3>{section.title}</h3>
					<p>{section.description}</p>
					<span class="file-count">{section.fileCount} documents</span>
				</a>
			{/each}
		</div>
	</section>

	<section class="getting-started">
		<h2>Quick Links</h2>
		<div class="start-links">
			<a href="/docs/getting-started" class="start-link api-highlight">
				<span class="icon">&#x1F680;</span>
				<div>
					<h4>Getting Started</h4>
					<p>What is OpenMates and how it works</p>
				</div>
			</a>
			<a href="/docs/user-guide" class="start-link">
				<span class="icon">&#x1F4D6;</span>
				<div>
					<h4>User Guide</h4>
					<p>Learn how to use all features</p>
				</div>
			</a>
			<a href="/docs/apps" class="start-link">
				<span class="icon">&#x1F4E6;</span>
				<div>
					<h4>Apps</h4>
					<p>Explore built-in apps and skills</p>
				</div>
			</a>
			<a href="/docs/self-hosting" class="start-link">
				<span class="icon">&#x1F5A5;</span>
				<div>
					<h4>Self-Hosting</h4>
					<p>Run your own OpenMates instance</p>
				</div>
			</a>
			<a href="/docs/architecture" class="start-link">
				<span class="icon">&#x1F3D7;</span>
				<div>
					<h4>Architecture</h4>
					<p>Technical deep dives for developers</p>
				</div>
			</a>
			<a href="/docs/api" class="start-link">
				<span class="icon">&#x1F50C;</span>
				<div>
					<h4>API Reference</h4>
					<p>Interactive REST API documentation</p>
				</div>
			</a>
			<a href="/docs/design-guide" class="start-link">
				<span class="icon">&#x1F3A8;</span>
				<div>
					<h4>Design Guide</h4>
					<p>UI/UX principles and patterns</p>
				</div>
			</a>
			<a href="/docs/contributing" class="start-link">
				<span class="icon">&#x1F91D;</span>
				<div>
					<h4>Contributing</h4>
					<p>Help improve OpenMates</p>
				</div>
			</a>
		</div>
	</section>
</div>

<style>
	.docs-index {
		max-width: 1000px;
		margin: 0 auto;
	}

	.docs-hero {
		text-align: center;
		padding: 3rem 1rem;
		margin-bottom: 2rem;
	}

	.docs-hero h1 {
		font-size: 2.5rem;
		font-weight: 700;
		color: var(--color-grey-900, #111827);
		margin-bottom: 1rem;
	}

	.hero-description {
		font-size: 1.25rem;
		color: var(--color-grey-600, #4b5563);
		max-width: 600px;
		margin: 0 auto;
	}

	.quick-links {
		margin-bottom: 3rem;
	}

	.quick-links h2,
	.getting-started h2 {
		font-size: 1.5rem;
		font-weight: 600;
		color: var(--color-grey-900, #111827);
		margin-bottom: 1.5rem;
	}

	.section-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: 1.5rem;
	}

	.section-card {
		display: block;
		padding: 1.5rem;
		background-color: var(--color-grey-50, #ffffff);
		border: 1px solid var(--color-grey-200, #e5e5e5);
		border-radius: 0.75rem;
		text-decoration: none;
		transition: all 0.2s ease;
	}

	.section-card:hover {
		border-color: var(--color-primary, #3b82f6);
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
		transform: translateY(-2px);
	}

	.section-card h3 {
		font-size: 1.125rem;
		font-weight: 600;
		color: var(--color-grey-900, #111827);
		margin-bottom: 0.5rem;
	}

	.section-card p {
		font-size: 0.875rem;
		color: var(--color-grey-600, #4b5563);
		margin-bottom: 1rem;
		line-height: 1.5;
	}

	.file-count {
		font-size: 0.75rem;
		color: var(--color-grey-500, #6b7280);
	}

	.start-links {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	.start-link {
		display: flex;
		align-items: center;
		gap: 1rem;
		padding: 1rem 1.5rem;
		background-color: var(--color-grey-50, #ffffff);
		border: 1px solid var(--color-grey-200, #e5e5e5);
		border-radius: 0.75rem;
		text-decoration: none;
		transition: all 0.2s ease;
	}

	.start-link:hover {
		border-color: var(--color-primary, #3b82f6);
		background-color: var(--color-primary-50, #eff6ff);
	}

	.start-link .icon {
		font-size: 2rem;
	}

	.start-link h4 {
		font-size: 1rem;
		font-weight: 600;
		color: var(--color-grey-900, #111827);
		margin-bottom: 0.25rem;
	}

	.start-link p {
		font-size: 0.875rem;
		color: var(--color-grey-600, #4b5563);
	}

	.start-link.api-highlight {
		background-color: var(--color-primary-50, #eff6ff);
		border-color: var(--color-primary-200, #bfdbfe);
	}

	.start-link.api-highlight:hover {
		background-color: var(--color-primary-100, #dbeafe);
		border-color: var(--color-primary, #3b82f6);
	}

	@media (max-width: 767px) {
		.docs-hero h1 {
			font-size: 1.75rem;
		}

		.hero-description {
			font-size: 1rem;
		}
	}
</style>
