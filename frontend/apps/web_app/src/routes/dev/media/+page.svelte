<!--
  Media Generation Gallery — index page listing all available templates.

  Browse templates, preview them inline, and copy Playwright capture commands.
  Accessible at /dev/media (dev environments only).

  Architecture: docs/media-generation.md
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { browser } from '$app/environment';
	import { listTemplates, listScenarios } from './data/loader';
	import { FORMAT_DIMENSIONS } from './data/types';

	interface TemplateInfo {
		id: string;
		path: string;
		dimensions: string;
	}

	let templates = $state<TemplateInfo[]>([]);
	let scenarios = $state<string[]>([]);
	let ready = $state(false);

	const TEMPLATE_DESCRIPTIONS: Record<string, string> = {
		'og-github': 'GitHub repo / Open Graph — 1200x630',
		'og-social': 'Social sharing (Twitter, LinkedIn) — 1200x630',
		'instagram-single': 'Instagram single post — 1080x1080',
		'instagram-carousel': 'Instagram carousel (multi-slide) — 1080x1080',
		'instagram-story': 'Instagram / TikTok story — 1080x1920'
	};

	onMount(() => {
		if (!browser) return;

		try {
			const templateIds = listTemplates();
			templates = templateIds.map((id) => ({
				id,
				path: `/dev/media/templates/${id}`,
				dimensions: TEMPLATE_DESCRIPTIONS[id] || id
			}));

			scenarios = listScenarios();
		} catch (e) {
			console.error('Failed to load media index:', e);
		}

		ready = true;
	});
</script>

<div class="media-gallery">
	<h1 class="gallery-title">Media Generation</h1>
	<p class="gallery-subtitle">
		Templates for OG images, social media graphics, and marketing materials.
		Edit YAML scenario files to change content. Capture with Playwright.
	</p>

	{#if ready}
		<section class="gallery-section">
			<h2>Templates</h2>
			<div class="template-grid">
				{#each templates as tmpl}
					<a href={tmpl.path} class="template-card">
						<div class="template-preview">
							<iframe src={tmpl.path} title={tmpl.id} loading="lazy"></iframe>
						</div>
						<div class="template-info">
							<h3>{tmpl.id}</h3>
							<p>{tmpl.dimensions}</p>
						</div>
					</a>
				{/each}
			</div>
		</section>

		<section class="gallery-section">
			<h2>Scenarios</h2>
			<p class="section-desc">Chat scenarios loaded from YAML files. Use ?scenario=name to override.</p>
			<div class="scenario-list">
				{#each scenarios as scenario}
					<span class="scenario-tag">{scenario}</span>
				{/each}
			</div>
		</section>

		<section class="gallery-section">
			<h2>Quick Capture</h2>
			<pre class="capture-cmd">npx playwright test frontend/apps/web_app/src/routes/dev/media/scripts/capture.spec.ts</pre>
			<p class="section-desc">
				Or capture a single template:
			</p>
			<pre class="capture-cmd">npx playwright test --grep "og-github" frontend/apps/web_app/src/routes/dev/media/scripts/capture.spec.ts</pre>
		</section>
	{/if}
</div>

<style>
	:global(body) {
		margin: 0;
		padding: 0;
		background: #111;
		font-family: var(--font-primary, 'Lexend Deca Variable'), system-ui, sans-serif;
		color: #e0e0e0;
	}

	.media-gallery {
		max-width: 1200px;
		margin: 0 auto;
		padding: 40px 24px;
	}

	.gallery-title {
		font-size: 2rem;
		font-weight: 800;
		color: #f0f0f0;
		margin: 0 0 8px;
	}

	.gallery-subtitle {
		color: #888;
		margin: 0 0 40px;
		line-height: 1.5;
	}

	.gallery-section {
		margin-bottom: 48px;
	}

	.gallery-section h2 {
		font-size: 1.25rem;
		font-weight: 700;
		color: #ccc;
		margin: 0 0 16px;
		border-bottom: 1px solid #333;
		padding-bottom: 8px;
	}

	.section-desc {
		color: #888;
		margin: 0 0 12px;
		font-size: 0.875rem;
	}

	.template-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
		gap: 24px;
	}

	.template-card {
		background: #1a1a1a;
		border: 1px solid #333;
		border-radius: 12px;
		overflow: hidden;
		text-decoration: none;
		color: inherit;
		transition: border-color 0.2s;
	}

	.template-card:hover {
		border-color: #7a9bf0;
	}

	.template-preview {
		width: 100%;
		height: 200px;
		overflow: hidden;
		position: relative;
		background: #111;
	}

	.template-preview iframe {
		width: 1200px;
		height: 630px;
		border: none;
		transform: scale(0.3);
		transform-origin: top left;
		pointer-events: none;
	}

	.template-info {
		padding: 12px 16px;
	}

	.template-info h3 {
		font-size: 1rem;
		font-weight: 600;
		margin: 0 0 4px;
		color: #f0f0f0;
	}

	.template-info p {
		font-size: 0.8125rem;
		color: #888;
		margin: 0;
	}

	.scenario-list {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}

	.scenario-tag {
		background: #252525;
		color: #ccc;
		padding: 4px 12px;
		border-radius: 6px;
		font-size: 0.8125rem;
		font-family: monospace;
	}

	.capture-cmd {
		background: #1a1a1a;
		border: 1px solid #333;
		border-radius: 8px;
		padding: 12px 16px;
		font-family: monospace;
		font-size: 0.8125rem;
		color: #7a9bf0;
		overflow-x: auto;
		margin: 0 0 8px;
	}
</style>
