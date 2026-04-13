<!--
	frontend/apps/web_app/src/routes/(seo)/example/+page.svelte

	Listing page for all example chats at /example/.
	Crawlers see the full listing with links to /example/{slug}.
	Human browsers are redirected to the SPA on mount.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	onMount(() => {
		window.location.replace('/');
	});
</script>

<svelte:head>
	<title>Example Chats — OpenMates</title>
	<meta
		name="description"
		content="Explore real AI conversations about aviation, travel, science, and more. See how OpenMates handles complex questions with web search, image search, and knowledge retrieval."
	/>
	<link rel="canonical" href={data.canonicalUrl} />
	<meta name="robots" content={data.isDevHost ? 'noindex, nofollow' : 'index, follow'} />

	<!-- Open Graph -->
	<meta property="og:type" content="website" />
	<meta property="og:url" content={data.canonicalUrl} />
	<meta property="og:title" content="Example Chats — OpenMates" />
	<meta
		property="og:description"
		content="Explore real AI conversations about aviation, travel, science, and more."
	/>
	<meta property="og:image" content="https://openmates.org/images/og-image.jpg" />
	<meta property="og:site_name" content="OpenMates" />

	<!-- Twitter Card -->
	<meta name="twitter:card" content="summary_large_image" />
	<meta name="twitter:title" content="Example Chats — OpenMates" />
	<meta
		name="twitter:description"
		content="Explore real AI conversations about aviation, travel, science, and more."
	/>
	<meta name="twitter:image" content="https://openmates.org/images/og-image.jpg" />
</svelte:head>

<main>
	<header>
		<h1>Example Chats</h1>
		<p class="intro">
			Real AI conversations showcasing how OpenMates handles complex questions
			with web search, image search, and knowledge retrieval.
		</p>
	</header>

	{#if data.chats.length === 0}
		<p class="empty">No example chats available yet.</p>
	{:else}
		<ul class="chat-list">
			{#each data.chats as chat}
				<li class="chat-item">
					<a href="/example/{chat.slug}" class="chat-link">
						<span class="chat-info">
							<span class="chat-title">{chat.title}</span>
							{#if chat.summary}
								<span class="chat-summary">{chat.summary}</span>
							{/if}
							{#if chat.keywords.length > 0}
								<span class="chat-keywords">
									{chat.keywords.slice(0, 5).join(' · ')}
								</span>
							{/if}
						</span>
					</a>
				</li>
			{/each}
		</ul>
	{/if}

	<footer>
		<a href="/">Try OpenMates</a>
	</footer>
</main>

<style>
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

	.chat-keywords {
		font-size: 12px;
		color: #999;
		margin-top: 2px;
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
