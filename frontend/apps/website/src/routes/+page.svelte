<script lang="ts">
  import LandingPage from '@repo/public-site/components/landing/LandingPage.svelte';
  import type { PageData } from './$types';
  let { data }: { data: PageData } = $props();
  const pageTitle = 'OpenMates — Your privacy first AI team mates';
</script>
<svelte:head>
  <title>{pageTitle}</title>
  <meta name="description" content="Your privacy first AI team mates for everyday work, research, and creation." />
  <meta name="robots" content={data.isDevHost ? 'noindex, nofollow' : 'index, follow'} />
  <link rel="canonical" href={data.canonicalUrl} />
  <meta property="og:title" content={pageTitle} />
  <meta name="twitter:title" content={pageTitle} />
  <meta property="og:image" content={`${data.websiteBaseUrl}/images/og-image.jpg`} />
</svelte:head>
<LandingPage appBaseUrl={data.appBaseUrl} websiteBaseUrl={data.websiteBaseUrl} apiBaseUrl={data.apiBaseUrl} serverStatusUrl="/api/server-status" events={data.events} news={data.news} posts={data.posts} />
