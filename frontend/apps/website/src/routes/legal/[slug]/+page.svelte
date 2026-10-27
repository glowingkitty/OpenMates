<script lang="ts">
  import PublicSiteHeader from '@repo/public-site/components/landing/PublicSiteHeader.svelte';
  import { saveBrowserPreference } from '@repo/public-site/languagePreference';
  import { landingCopy } from '@repo/public-site/components/landing/landingLocale';
  import type { PageData } from './$types';
  let { data }: { data: PageData } = $props();
  let copy = $derived(landingCopy[data.locale]);
  function selectLanguage(code: string): void {
    saveBrowserPreference(code === 'auto' ? { mode: 'auto' } : { mode: 'manual', language: code });
    window.location.href = `${data.canonicalUrl}${code === 'auto' ? '' : `?lang=${code}`}`;
  }
</script>
<svelte:head>
  <title>{data.title} — OpenMates</title>
  <meta name="description" content={data.description} />
  <meta name="robots" content={data.isDevHost ? 'noindex, nofollow' : 'index, follow'} />
  <link rel="canonical" href={data.canonicalUrl} />
  <meta property="og:type" content="website" />
  <meta property="og:title" content={`${data.title} — OpenMates`} />
  <meta property="og:description" content={data.description} />
  <meta property="og:image" content="https://openmates.org/images/og-image.jpg" />
  <!-- JSON-LD is serialized from repository-owned legal metadata and a validated origin. -->
  <!-- eslint-disable-next-line svelte/no-at-html-tags -->
  {@html `<script type="application/ld+json">${data.jsonLd}<` + `/script>`}
</svelte:head>
<PublicSiteHeader appBaseUrl={data.appBaseUrl} websiteBaseUrl={data.websiteBaseUrl} language={data.locale} languageMode={data.languageMode} availableLanguages={['en', 'de']} onLanguageChange={selectLanguage} />
<main class="legal-document">
  <article>
    <!-- The server renders canonical legal Markdown with raw HTML disabled. -->
    <!-- eslint-disable-next-line svelte/no-at-html-tags -->
    {@html data.bodyHtml}
  </article>
</main>
<footer class="site-footer"><a href={`/legal/privacy?lang=${data.locale}`}>{copy.privacy}</a><a href={`/legal/terms?lang=${data.locale}`}>{copy.terms}</a><a href={`/legal/imprint?lang=${data.locale}`}>{copy.imprint}</a></footer>
<style>
  .site-footer { display:flex; flex-wrap:wrap; justify-content:space-between; gap:1.5rem; padding:1.5rem max(1.5rem, calc((100vw - 900px)/2)); }
  .legal-document { max-width:900px; margin:auto; padding:2rem 1.5rem 5rem; line-height:1.7; overflow-wrap:anywhere; }
  .legal-document :global(h1) { font-size:clamp(1.75rem,4vw,3rem); hyphens:auto; }
  .legal-document :global(h2) { margin-top:2.5rem; }
  .legal-document :global(a) { color:var(--color-primary); overflow-wrap:anywhere; }
  @media (max-width:730px) {
    .legal-document :global(table) { width:100%; table-layout:fixed; border-collapse:collapse; font-size:var(--font-size-small); line-height:1.5; hyphens:auto; }
    .legal-document :global(th) { font-size:var(--font-size-xs); overflow-wrap:normal; hyphens:none; }
    .legal-document :global(th:first-child), .legal-document :global(th:last-child) { width:24%; }
    .legal-document :global(th:nth-child(2)) { width:25%; }
    .legal-document :global(th:nth-child(3)) { width:27%; }
    .legal-document :global(td:last-child) { overflow-wrap:normal; word-break:normal; hyphens:none; }
  }
</style>
