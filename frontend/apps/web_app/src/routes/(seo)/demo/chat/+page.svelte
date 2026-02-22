<!--
	frontend/apps/web_app/src/routes/(seo)/demo/chat/+page.svelte

	Listing/index page for all demo chats at /demo/chat/.

	ARCHITECTURE:
	  - Crawlers see the full listing with links to individual demo chat SEO pages.
	  - Human browsers are redirected to the SPA home (/#demo) on mount.
	  - The page groups demo chats by category and provides internal links to /demo/chat/{slug}
	    so Google can discover and index each individual demo chat page.

	WHY (seo) ROUTE GROUP:
	  The root +layout.svelte wraps everything in {#if loaded} where loaded is only set
	  inside onMount (browser-only). During SSR, onMount never runs, so loaded=false and
	  {#render children()} is never called — the entire page body is suppressed in SSR output.
	  By placing this page in the (seo) route group (which has its own minimal +layout.svelte
	  that simply renders children), the root layout's loading guard is bypassed and the full
	  server-rendered HTML is emitted for crawlers/Google to index.

	This is an SSR page — all content is server-rendered for SEO.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	/**
	 * Redirect human browsers to the SPA on mount.
	 * Crawlers don't run JavaScript, so they see the full listing.
	 * Human users land on the main SPA instead of this minimal HTML page.
	 */
	onMount(() => {
		window.location.replace('/');
	});
</script>

<svelte:head>
	<title>Demo Chats — OpenMates</title>
	<meta
		name="description"
		content="Explore example AI conversations covering travel, coding, news, learning, and more. Try OpenMates with real demo chats."
	/>
	<link rel="canonical" href={data.canonicalUrl} />
	<meta name="robots" content="index, follow" />

	<!-- Open Graph -->
	<meta property="og:type" content="website" />
	<meta property="og:url" content={data.canonicalUrl} />
	<meta property="og:title" content="Demo Chats — OpenMates" />
	<meta
		property="og:description"
		content="Explore example AI conversations covering travel, coding, news, learning, and more."
	/>
	<meta property="og:image" content="https://openmates.org/images/og-image.jpg" />
	<meta property="og:site_name" content="OpenMates" />

	<!-- Twitter Card -->
	<meta name="twitter:card" content="summary_large_image" />
	<meta name="twitter:title" content="Demo Chats — OpenMates" />
	<meta
		name="twitter:description"
		content="Explore example AI conversations covering travel, coding, news, learning, and more."
	/>
	<meta name="twitter:image" content="https://openmates.org/images/og-image.jpg" />
</svelte:head>

<main>
	<header>
		<h1>Demo Chats</h1>
		<p class="intro">Explore example AI conversations. Click any chat to try it in OpenMates.</p>
	</header>

	{#if data.groups.length === 0}
		<p class="empty">No demo chats available yet.</p>
	{:else}
		{#each data.groups as group}
			<section class="category-group" aria-labelledby="cat-{group.category}">
				<h2 id="cat-{group.category}">{group.label}</h2>
				<ul class="chat-list">
					{#each group.chats as chat}
						<li class="chat-item">
							<a href="/demo/chat/{chat.slug || chat.demo_id}" class="chat-link">
								{#if chat.icon}
									<span class="chat-icon" aria-hidden="true">{chat.icon}</span>
								{/if}
								<span class="chat-info">
									<span class="chat-title">{chat.title}</span>
									{#if chat.summary}
										<span class="chat-summary">{chat.summary}</span>
									{/if}
								</span>
							</a>
						</li>
					{/each}
				</ul>
			</section>
		{/each}
	{/if}

	<footer>
		<a href="/">Open OpenMates</a>
	</footer>
</main>

<style>
	/*
	 * Minimal styles — only crawlers see this page.
	 * Human users are redirected to the SPA by onMount.
	 */
	main {
		max-width: 860px;
		margin: 0 auto;
		padding: 32px 24px;
		font-family:
			-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
		color: #1a1a1a;
		background: #fff;
	}

	h1 {
		font-size: 32px;
		font-weight: 700;
		margin: 0 0 12px;
		color: #000;
	}

	.intro {
		font-size: 17px;
		color: #555;
		margin: 0 0 40px;
		line-height: 1.5;
	}

	.empty {
		color: #888;
		font-size: 16px;
	}

	.category-group {
		margin-bottom: 40px;
	}

	h2 {
		font-size: 20px;
		font-weight: 600;
		color: #222;
		margin: 0 0 16px;
		padding-bottom: 8px;
		border-bottom: 1px solid #eee;
	}

	.chat-list {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.chat-item {
		border-radius: 10px;
		border: 1px solid #e8e8e8;
		transition: border-color 0.15s;
	}

	.chat-item:hover {
		border-color: #aaa;
	}

	.chat-link {
		display: flex;
		align-items: flex-start;
		gap: 12px;
		padding: 14px 16px;
		text-decoration: none;
		color: inherit;
	}

	.chat-icon {
		font-size: 22px;
		line-height: 1;
		flex-shrink: 0;
		padding-top: 2px;
	}

	.chat-info {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.chat-title {
		font-size: 15px;
		font-weight: 600;
		color: #111;
	}

	.chat-summary {
		font-size: 13px;
		color: #666;
		line-height: 1.4;
	}

	footer {
		margin-top: 48px;
		padding-top: 20px;
		border-top: 1px solid #eee;
	}

	footer a {
		color: #4867cd;
		text-decoration: none;
		font-size: 15px;
	}

	footer a:hover {
		text-decoration: underline;
	}
</style>
