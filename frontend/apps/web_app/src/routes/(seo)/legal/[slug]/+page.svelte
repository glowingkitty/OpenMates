<!--
	frontend/apps/web_app/src/routes/(seo)/legal/[slug]/+page.svelte

	SEO page for legal documents at /legal/{slug} (privacy, terms, imprint).

	WHY (seo) ROUTE GROUP:
	  The root +layout.svelte wraps everything in {#if loaded} (browser-only). During SSR,
	  loaded=false so the entire page body is suppressed. This (seo) group has its own
	  minimal +layout@.svelte that simply renders children, preserving full SSR output
	  for crawlers and link-preview bots.

	FLOW:
	  1. Crawler / link-preview bot hits /legal/privacy → SSR renders HTML + OG tags.
	  2. Human browser: onMount fires → redirects to SPA via /#chat-id=legal-privacy.
	  3. SPA calls setActiveChat('legal-privacy') → replaceState restores /legal/privacy.
	     The URL stays at /legal/privacy after the round-trip.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	onMount(() => {
		if (data.spaUrl) {
			window.location.replace(data.spaUrl);
		}
	});
</script>

<svelte:head>
	<title>{data.title} — OpenMates</title>
	<meta name="description" content={data.description} />
	<meta name="keywords" content={data.keywords.join(', ')} />
	<link rel="canonical" href={data.canonicalUrl} />
	<meta name="robots" content={data.isDevHost ? 'noindex, nofollow' : 'index, follow'} />

	<meta property="og:type" content="website" />
	<meta property="og:url" content={data.canonicalUrl} />
	<meta property="og:title" content="{data.title} — OpenMates" />
	<meta property="og:description" content={data.description} />
	<meta property="og:image" content="https://openmates.org/images/og-image.jpg" />
	<meta property="og:site_name" content="OpenMates" />

	<meta name="twitter:card" content="summary_large_image" />
	<meta name="twitter:url" content={data.canonicalUrl} />
	<meta name="twitter:title" content="{data.title} — OpenMates" />
	<meta name="twitter:description" content={data.description} />
	<meta name="twitter:image" content="https://openmates.org/images/og-image.jpg" />

	<!-- eslint-disable-next-line svelte/no-at-html-tags -->
	{@html `<script type="application/ld+json">${data.jsonLd}<` + `/script>`}
</svelte:head>

<main aria-label="{data.title} — OpenMates legal document">
	<article>
		<header>
			<h1>{data.title}</h1>
			{#if data.description}
				<p class="description">{data.description}</p>
			{/if}
		</header>

		<footer>
			<a href={data.spaUrl}>Open this document in OpenMates</a>
		</footer>
	</article>
</main>

<style>
	/*
	 * Minimal styles — this page is only ever seen by crawlers.
	 * Human users are redirected before the page renders visually.
	 *
	 * Note: raw color literals are intentional — this is a crawler-only
	 * page outside the SPA theme system with no dark-mode requirement.
	 */
	main {
		max-width: 800px;
		margin: 0 auto;
		padding: 24px;
		font-family:
			-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
		color: #1a1a1a; /* intentional: no theme vars — crawler-only page */
		background: #fff; /* intentional: no theme vars — crawler-only page */
	}

	h1 {
		font-size: 28px;
		font-weight: 700;
		margin: 0 0 12px;
		color: #000; /* intentional: no theme vars — crawler-only page */
	}

	.description {
		font-size: 16px;
		color: #555; /* intentional: no theme vars — crawler-only page */
		margin: 0 0 32px;
		line-height: 1.6;
	}

	footer {
		margin-top: 40px;
		padding-top: 20px;
		border-top: 1px solid #eee; /* intentional: no theme vars — crawler-only page */
	}

	footer a {
		color: #4867cd; /* intentional: no theme vars — crawler-only page */
		text-decoration: none;
		font-size: 15px;
	}

	footer a:hover {
		text-decoration: underline;
	}
</style>
