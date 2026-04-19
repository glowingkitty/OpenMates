<!--
	SEO page for a single tip newsletter issue at /tips/{slug}.
	Crawlers see a fully-rendered article; human browsers are redirected to the
	interactive SPA chat via onMount.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import MarkdownIt from 'markdown-it';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	const md = new MarkdownIt({ html: false, linkify: true, breaks: false });
	const bodyHtml = $derived(data.messageBody ? md.render(data.messageBody) : '');

	onMount(() => {
		if (data.spaUrl) {
			const { pathname, search, hash } = new URL(data.spaUrl);
			window.location.replace(pathname + search + hash);
		}
	});
</script>

<svelte:head>
	<title>{data.title} — OpenMates</title>
	<meta name="description" content={data.summary || data.title} />
	<meta name="keywords" content={data.keywords.join(', ')} />
	<link rel="canonical" href={data.canonicalUrl} />
	<meta name="robots" content={data.isDevHost ? 'noindex, nofollow' : 'index, follow'} />

	<meta property="og:type" content="article" />
	<meta property="og:url" content={data.canonicalUrl} />
	<meta property="og:title" content="{data.title} — OpenMates" />
	<meta property="og:description" content={data.summary || data.title} />
	<meta property="og:site_name" content="OpenMates" />
	{#if data.video.thumbnail_url}
		<meta property="og:image" content={data.video.thumbnail_url} />
	{/if}

	<meta name="twitter:card" content="summary_large_image" />
	<meta name="twitter:url" content={data.canonicalUrl} />
	<meta name="twitter:title" content="{data.title} — OpenMates" />
	<meta name="twitter:description" content={data.summary || data.title} />
	{#if data.video.thumbnail_url}
		<meta name="twitter:image" content={data.video.thumbnail_url} />
	{/if}

	<!-- eslint-disable-next-line svelte/no-at-html-tags -->
	{@html `<script type="application/ld+json">${data.jsonLd}<` + `/script>`}
</svelte:head>

<main aria-label="{data.title} — OpenMates tip">
	<article>
		<header>
			<h1>{data.title}</h1>
			{#if data.summary}
				<p class="summary">{data.summary}</p>
			{/if}
		</header>

		{#if data.video.mp4_url}
			<div class="video-wrapper">
				<video
					controls
					preload="metadata"
					playsinline
					poster={data.video.thumbnail_url ?? undefined}
				>
					<source src={data.video.mp4_url} type="video/mp4" />
				</video>
			</div>
		{/if}

		<!-- eslint-disable-next-line svelte/no-at-html-tags -->
		<section class="body">{@html bodyHtml}</section>

		<footer>
			<a href={data.spaUrl}>Open this in OpenMates</a>
		</footer>
	</article>
</main>

<style>
	main {
		max-width: 820px;
		margin: 0 auto;
		padding: 24px;
		font-family:
			-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
		color: #1a1a1a;
		background: #fff;
	}
	h1 { font-size: 28px; font-weight: 700; margin: 0 0 12px; color: #000; }
	.summary { font-size: 16px; color: #555; margin: 0 0 24px; line-height: 1.6; }
	.video-wrapper {
		width: 100%;
		aspect-ratio: 16 / 9;
		background: #000;
		border-radius: 12px;
		overflow: hidden;
		margin: 0 0 24px 0;
	}
	.video-wrapper video { width: 100%; height: 100%; display: block; object-fit: contain; }
	.body :global(h2) { font-size: 22px; font-weight: 600; margin: 24px 0 8px; }
	.body :global(h3) { font-size: 18px; font-weight: 600; margin: 20px 0 6px; }
	.body :global(p) { margin: 0 0 16px; line-height: 1.6; }
	.body :global(ul), .body :global(ol) { margin: 0 0 16px 20px; line-height: 1.6; }
	.body :global(a) { color: #4867cd; text-decoration: none; }
	.body :global(a:hover) { text-decoration: underline; }
	footer { margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee; }
	footer a { color: #4867cd; text-decoration: none; font-size: 15px; }
	footer a:hover { text-decoration: underline; }
</style>
