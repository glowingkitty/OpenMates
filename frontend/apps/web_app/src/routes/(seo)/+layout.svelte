<!--
	frontend/apps/web_app/src/routes/(seo)/+layout.svelte

	Minimal layout for the (seo) route group.

	WHY THIS EXISTS:
	  The root +layout.svelte wraps all children in {#if loaded} where `loaded` is only
	  set inside onMount (browser-only). During SSR, onMount never runs — so `loaded=false`
	  and the entire page body is suppressed from the server-rendered HTML.

	  Routes under (seo)/ need their full HTML rendered on the server so that search
	  engine crawlers (Googlebot, etc.) can index the page content. By placing them in
	  this route group with its own layout, these routes inherit this minimal layout
	  instead of the root layout — preserving full SSR output.

	  This layout simply renders children without any loading guards, CSS imports,
	  or client-side-only initialisation. The SEO pages provide their own styles
	  inline and do not depend on the SPA's theme/i18n/store infrastructure.
-->
<script lang="ts">
	let { children } = $props();
</script>

{@render children()}
