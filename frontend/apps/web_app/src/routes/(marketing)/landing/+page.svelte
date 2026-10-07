<script lang="ts">
	import LandingPage from '@repo/ui/components/landing/LandingPage.svelte';
	import type { PageData } from './$types';
	let { data }: { data: PageData } = $props();
</script>

<svelte:head>
	<title>OpenMates — Your privacy first AI team mates</title>
	<meta name="description" content="AI team mates for actionable chats and everyday workflow automation. Explore OpenMates, with privacy and safety by design." />
	<link rel="canonical" href={data.canonicalUrl} />
	<meta property="og:title" content="OpenMates — Your privacy first AI team mates" />
	<meta property="og:description" content="Get things done with actionable chats, workflow automation, and privacy by design." />
	<meta property="og:url" content={data.canonicalUrl} />
	<meta property="og:type" content="website" />
	<meta property="og:image" content={`${data.websiteBaseUrl}/images/og-image.jpg`} />
	{#if data.isDevHost}<meta name="robots" content="noindex, nofollow" />{/if}
</svelte:head>

<LandingPage appBaseUrl={data.appBaseUrl} websiteBaseUrl={data.websiteBaseUrl} news={data.news} posts={data.posts} events={data.events} />
