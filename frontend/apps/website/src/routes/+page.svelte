<script lang="ts">
  import LandingPage from '@repo/public-site/components/landing/LandingPage.svelte';
  import type { PageData } from './$types';
  let { data }: { data: PageData } = $props();
</script>
<svelte:head>
  <title>OpenMates — Your private AI workspace</title>
  <meta name="description" content="Private AI tools for everyday work, research, and creation." />
  <meta name="robots" content={data.isDevHost ? 'noindex, nofollow' : 'index, follow'} />
  <link rel="canonical" href={data.canonicalUrl} />
  <meta property="og:image" content={`${data.websiteBaseUrl}/images/og-image.jpg`} />
</svelte:head>
<LandingPage appBaseUrl={data.appBaseUrl} websiteBaseUrl={data.websiteBaseUrl} apiBaseUrl={data.apiBaseUrl} events={data.events} news={data.news} posts={data.posts} />
