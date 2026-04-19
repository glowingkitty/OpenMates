<!--
	frontend/apps/web_app/src/routes/(seo)/intro/[slug]/+page.svelte

	SEO page for intro chats at /intro/{slug}.

	WHY (seo) ROUTE GROUP:
	  The root +layout.svelte wraps everything in {#if loaded} where loaded is only set
	  inside onMount (browser-only). During SSR, onMount never runs, so loaded=false and
	  {#render children()} is never called — the entire page body is suppressed in SSR output.
	  By placing this page in the (seo) route group (which has its own minimal +layout.svelte
	  that simply renders children), the root layout's loading guard is bypassed and the full
	  server-rendered HTML is emitted for crawlers/Google to index.

	ARCHITECTURE — How this works:
	  1. Server renders this page to HTML (via +page.server.ts).
	     The full intro chat content (title, message, follow-ups) is in the HTML — Google indexes it.
	  2. When a human browser loads the page, the onMount redirect fires immediately
	     and navigates to the main SPA at /#chat-id={chatId}.
	  3. The SPA picks up the deep link, loads the intro chat from its in-memory bundle,
	     and displays it in the full interactive UI — seamlessly.
	  4. The user never sees this page render — the redirect is instant.

	SEO meta tags, OG tags, canonical URL, and JSON-LD are injected via <svelte:head>.
	The chat content in the <main> element is what Google reads and indexes.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import type { PageData } from './$types';

	// Props injected from +page.server.ts
	let { data }: { data: PageData } = $props();

	/**
	 * Redirect human browsers to the SPA immediately on mount.
	 * Crawlers don't execute JavaScript, so they see the full server-rendered content.
	 * Human users are redirected before the page visually renders — invisible transition.
	 *
	 * We use window.location.replace (not href assignment or goto) so the SEO page
	 * does not appear in the browser's back history — the user hits Back and goes
	 * wherever they came from, not back to this static page.
	 */
	onMount(() => {
		if (data.spaUrl) {
			// Use a relative redirect so prerendered pages (built with sveltekit-prerender
			// hostname → origin always resolves to openmates.org) don't forward dev/staging
			// visitors to the production domain.
			const { pathname, search, hash } = new URL(data.spaUrl);
			window.location.replace(pathname + search + hash);
		}
	});
</script>

<!--
	SEO meta tags injected server-side into <head>.
	These are the tags Google and other crawlers read.
-->
<svelte:head>
	<title>{data.title} — OpenMates</title>
	<meta name="description" content={data.description} />
	<link rel="canonical" href={data.canonicalUrl} />
	<!--
		noindex on dev/staging hostnames — prevents preview deployments from being indexed.
		Production deployments (openmates.org) get index,follow.
		Matches the same hostname logic in robots.txt/+server.ts.
	-->
	<meta name="robots" content={data.isDevHost ? 'noindex, nofollow' : 'index, follow'} />

	<!-- Open Graph -->
	<meta property="og:type" content="website" />
	<meta property="og:url" content={data.canonicalUrl} />
	<meta property="og:title" content="{data.title} — OpenMates" />
	<meta property="og:description" content={data.description} />
	<meta property="og:image" content="https://openmates.org/images/og-image.jpg" />
	<meta property="og:site_name" content="OpenMates" />

	<!-- Twitter Card -->
	<meta name="twitter:card" content="summary_large_image" />
	<meta name="twitter:url" content={data.canonicalUrl} />
	<meta name="twitter:title" content="{data.title} — OpenMates" />
	<meta name="twitter:description" content={data.description} />
	<meta name="twitter:image" content="https://openmates.org/images/og-image.jpg" />

	<!-- JSON-LD structured data (WebApplication schema) -->
	<!-- Split closing tag so the HTML parser doesn't confuse this template literal with a script block close -->
	<!-- eslint-disable-next-line svelte/no-at-html-tags -->
	{@html `<script type="application/ld+json">${data.jsonLd}<` + `/script>`}
</svelte:head>

<!--
	Semantic HTML content for search engine crawlers.
	Humans never see this — they're redirected to the SPA by onMount.
	The structure mirrors the intro chat conversation semantically.
-->
<main aria-label="{data.title} — OpenMates intro">
	<article>
		<header>
			<h1>{data.title}</h1>
			<p class="description">{data.description}</p>
		</header>

		<!-- Intro chat message content — this is the primary content Google indexes -->
		<section class="message" aria-label="Introduction">
			<p>{data.message}</p>
		</section>

		{#if data.followUpSuggestions && data.followUpSuggestions.length > 0}
			<section class="follow-up-suggestions" aria-label="Follow-up questions">
				<h2>Continue the conversation</h2>
				<ul>
					{#each data.followUpSuggestions as suggestion}
						<li>{suggestion}</li>
					{/each}
				</ul>
			</section>
		{/if}

		<footer>
			<!--
				Minimal fallback link for the rare case where JS is disabled (no redirect fires).
				Points to the SPA root, which loads the intro chat via the deep link.
			-->
			<a href={data.spaUrl}>Open this conversation in OpenMates</a>
		</footer>
	</article>
</main>

<style>
	/*
	 * Minimal styles — this page is only ever seen by crawlers.
	 * Human users are redirected before the page renders visually.
	 * Keep styles simple so the page renders fast on SSR.
	 *
	 * Note: raw color literals are intentional here — this is a crawler-only
	 * page outside the SPA theme system and has no dark-mode requirement.
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

	.message {
		background: #f5f5f5; /* intentional: no theme vars — crawler-only page */
		border-radius: 12px;
		padding: 16px 20px;
		margin-bottom: 32px;
		line-height: 1.6;
		font-size: 15px;
		white-space: pre-wrap;
	}

	.message p {
		margin: 0;
		white-space: pre-wrap;
	}

	.follow-up-suggestions h2 {
		font-size: 18px;
		font-weight: 600;
		margin: 0 0 12px;
	}

	.follow-up-suggestions ul {
		padding-left: 20px;
		margin: 0;
	}

	.follow-up-suggestions li {
		margin-bottom: 8px;
		font-size: 15px;
		color: #333; /* intentional: no theme vars — crawler-only page */
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
