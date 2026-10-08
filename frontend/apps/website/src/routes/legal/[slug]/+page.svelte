<script lang="ts">
  import type { PageData } from './$types';
  let { data }: { data: PageData } = $props();
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
<header class="site-header"><a href="/">OpenMates</a><nav><a href="/news">News</a><a href="/blog">Blog</a></nav></header>
<main class="legal-document">
  <article>
    <!-- The server renders canonical legal Markdown with raw HTML disabled. -->
    <!-- eslint-disable-next-line svelte/no-at-html-tags -->
    {@html data.bodyHtml}
  </article>
</main>
<footer class="site-footer"><a href="/legal/privacy">Privacy</a><a href="/legal/terms">Terms</a><a href="/legal/imprint">Imprint</a></footer>
<style>
  .site-header,.site-footer { display:flex; justify-content:space-between; gap:1.5rem; padding:1.5rem max(1.5rem, calc((100vw - 900px)/2)); }
  nav,.site-footer { display:flex; gap:1.25rem; }
  .legal-document { max-width:900px; margin:auto; padding:2rem 1.5rem 5rem; line-height:1.7; }
  .legal-document :global(h1) { font-size:clamp(2rem,4vw,3rem); }
  .legal-document :global(h2) { margin-top:2.5rem; }
  .legal-document :global(a) { color:var(--color-primary); overflow-wrap:anywhere; }
</style>
