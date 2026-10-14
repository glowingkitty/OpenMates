<script lang="ts">
  import PublicLandingPage from '@repo/public-site/components/landing/LandingPage.svelte';
  import type { LandingPublication } from '@repo/public-site/components/landing/landingPageContent';

  let {
    appBaseUrl,
    websiteBaseUrl,
    apiBaseUrl,
    serverStatusUrl,
    events = [],
    news = [],
    posts = []
  }: {
    appBaseUrl: string;
    websiteBaseUrl: string;
    apiBaseUrl?: string;
    serverStatusUrl?: string;
    events?: LandingPublication[];
    news?: LandingPublication[];
    posts?: LandingPublication[];
  } = $props();

  const fallbackApiUrl = $derived(apiBaseUrl ?? (
    appBaseUrl.includes('localhost') || appBaseUrl.includes('127.0.0.1')
      ? 'http://localhost:8000'
      : appBaseUrl.includes('.dev.') ? 'https://api.dev.openmates.org' : 'https://api.openmates.org'
  ));
</script>

<PublicLandingPage {appBaseUrl} {websiteBaseUrl} apiBaseUrl={fallbackApiUrl} {serverStatusUrl} {events} {news} {posts} />
