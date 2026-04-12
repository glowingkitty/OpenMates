<!--
	frontend/apps/web_app/src/routes/(seo)/example/[slug]/+page.svelte

	SEO page for individual example chats at /example/{slug}.

	ARCHITECTURE:
	  1. Server renders full chat content to HTML for Google/crawlers to index.
	  2. Human browsers are redirected to the SPA via onMount.
	  3. SEO meta tags, OG tags, JSON-LD, and keyword meta are all server-rendered.

	URL examples:
	  /example/gigantic-airplanes-transporting-rocket-parts
	  /example/comparing-ai-tools-2025
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
	<meta name="description" content={data.summary || data.title} />
	<meta name="keywords" content={data.keywords.join(', ')} />
	<link rel="canonical" href={data.canonicalUrl} />
	<meta name="robots" content={data.isDevHost ? 'noindex, nofollow' : 'index, follow'} />

	<!-- Open Graph -->
	<meta property="og:type" content="article" />
	<meta property="og:url" content={data.canonicalUrl} />
	<meta property="og:title" content="{data.title} — OpenMates" />
	<meta property="og:description" content={data.summary || data.title} />
	<meta property="og:image" content="https://openmates.org/images/og-image.jpg" />
	<meta property="og:site_name" content="OpenMates" />

	<!-- Twitter Card -->
	<meta name="twitter:card" content="summary_large_image" />
	<meta name="twitter:url" content={data.canonicalUrl} />
	<meta name="twitter:title" content="{data.title} — OpenMates" />
	<meta name="twitter:description" content={data.summary || data.title} />
	<meta name="twitter:image" content="https://openmates.org/images/og-image.jpg" />

	<!-- JSON-LD structured data -->
	<!-- eslint-disable-next-line svelte/no-at-html-tags -->
	{@html `<script type="application/ld+json">${data.jsonLd}<` + `/script>`}
</svelte:head>

<main aria-label="{data.title} — OpenMates example chat">
	<article>
		<header>
			<h1>{data.title}</h1>
			{#if data.summary}
				<p class="summary">{data.summary}</p>
			{/if}
			{#if data.keywords.length > 0}
				<p class="keywords">{data.keywords.join(' · ')}</p>
			{/if}
		</header>

		<!-- Chat conversation content — primary indexed content -->
		<section class="conversation" aria-label="Chat conversation">
			{#each data.messages as message}
				{#if message.role === 'user'}
					<div class="message user-message">
						<strong>User:</strong>
						<p>{message.content}</p>
					</div>
				{:else if message.role === 'assistant'}
					<div class="message assistant-message">
						<strong>OpenMates:</strong>
						<p>{message.content}</p>
					</div>
				{/if}
			{/each}
		</section>

		{#if data.followUpSuggestions && data.followUpSuggestions.length > 0}
			<section class="follow-up" aria-label="Related questions">
				<h2>Related questions you can ask</h2>
				<ul>
					{#each data.followUpSuggestions as suggestion}
						<li>{suggestion}</li>
					{/each}
				</ul>
			</section>
		{/if}

		<footer>
			<a href={data.spaUrl}>Open this conversation in OpenMates</a>
			<span class="separator">·</span>
			<a href="/example">View all example chats</a>
		</footer>
	</article>
</main>

<style>
	main {
		max-width: 800px;
		margin: 0 auto;
		padding: 24px;
		font-family:
			-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
		color: #1a1a1a;
		background: #fff;
	}

	h1 {
		font-size: 28px;
		font-weight: 700;
		margin: 0 0 12px;
		color: #000;
	}

	.summary {
		font-size: 16px;
		color: #555;
		margin: 0 0 8px;
		line-height: 1.6;
	}

	.keywords {
		font-size: 13px;
		color: #999;
		margin: 0 0 32px;
	}

	.conversation {
		display: flex;
		flex-direction: column;
		gap: 16px;
		margin-bottom: 32px;
	}

	.message {
		padding: 12px 16px;
		border-radius: 12px;
		line-height: 1.6;
		font-size: 15px;
	}

	.message strong {
		display: block;
		font-size: 12px;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		color: #888;
		margin-bottom: 4px;
	}

	.user-message {
		background: #e8eaf6;
		align-self: flex-end;
		max-width: 80%;
	}

	.assistant-message {
		background: #f5f5f5;
		align-self: flex-start;
		max-width: 90%;
	}

	.message p {
		margin: 0;
		white-space: pre-wrap;
	}

	.follow-up h2 {
		font-size: 18px;
		font-weight: 600;
		margin: 0 0 12px;
	}

	.follow-up ul {
		padding-left: 20px;
		margin: 0;
	}

	.follow-up li {
		margin-bottom: 8px;
		font-size: 15px;
		color: #333;
	}

	footer {
		margin-top: 40px;
		padding-top: 20px;
		border-top: 1px solid #eee;
		display: flex;
		gap: 8px;
		align-items: center;
	}

	footer a {
		color: #4867cd;
		text-decoration: none;
		font-size: 15px;
	}

	footer a:hover {
		text-decoration: underline;
	}

	.separator {
		color: #ccc;
	}
</style>
