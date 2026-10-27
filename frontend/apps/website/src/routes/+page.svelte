<script lang="ts">
  import { onMount } from 'svelte';
  import LandingPage from '@repo/public-site/components/landing/LandingPage.svelte';
  import type { PageData } from './$types';
  let { data }: { data: PageData } = $props();
  let pageTitle = $derived(data.language === 'de' ? 'OpenMates — Deine KI-Teamkollegen mit Privatsphäre' : 'OpenMates — Your privacy first AI team mates');
  let description = $derived(data.language === 'de' ? 'Deine KI-Teamkollegen mit Privatsphäre für Alltag, Recherche und kreative Arbeit.' : 'Your privacy first AI team mates for everyday work, research, and creation.');
  onMount(() => {
    // Fragments never reach the server. Keep old private links entirely in-browser.
    if (/^#\/?(?:chat[-_]?id=|team-id=|embed[-_]id=|settings(?:\/|=)|signup\/|pair=|(?:new-)?message=|compose$|apps(?:\/|=)|404=)/.test(window.location.hash)) {
      window.location.replace(`${data.appBaseUrl}/${window.location.search}${window.location.hash}`);
    }
  });
</script>
<svelte:head>
  <title>{pageTitle}</title>
  <meta name="description" content={description} />
  <meta name="robots" content={data.isDevHost ? 'noindex, nofollow' : 'index, follow'} />
  <link rel="canonical" href={data.canonicalUrl} />
  <meta property="og:title" content={pageTitle} />
  <meta name="twitter:title" content={pageTitle} />
  <meta property="og:image" content={`${data.websiteBaseUrl}/images/og-image.jpg`} />
</svelte:head>
<LandingPage appBaseUrl={data.appBaseUrl} websiteBaseUrl={data.websiteBaseUrl} apiBaseUrl={data.apiBaseUrl} initialLanguage={data.language} initialLanguageMode={data.languageMode} navigateOnLanguageChange serverStatusUrl="/api/server-status" events={data.events} news={data.news} posts={data.posts} />
