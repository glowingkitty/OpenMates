<script lang="ts">
	import { goto } from '$app/navigation';
	import NewsroomSurface from '@repo/ui/components/newsroom/NewsroomSurface.svelte';
	import type { NewsroomAction } from '@repo/ui/components/newsroom/types';
	import type { PublicPublicationPageData } from '$lib/publications/types';

	interface Props {
		data: PublicPublicationPageData;
	}

	let { data }: Props = $props();

	function openLink(href: string) {
		if (/^https?:\/\//.test(href)) {
			window.open(href, '_blank', 'noopener,noreferrer');
			return;
		}
		void goto(href);
	}

	function handleAction(action: NewsroomAction) {
		if (action.type === 'open-item') {
			if (!action.itemId) {
				void goto(data.indexUrl);
				return;
			}
			const href = data.linksById[action.itemId];
			if (href) openLink(href);
			return;
		}
		if (action.type === 'press-inquiry') {
			window.location.href = 'mailto:press@openmates.org';
			return;
		}
		if (action.type === 'press-kit') {
			window.location.href = 'mailto:press@openmates.org?subject=OpenMates%20press%20kit';
			return;
		}
		if (action.type === 'subscribe-news') {
			window.location.href = '/#settings/newsletter';
			return;
		}
		window.location.href = '/';
	}
</script>

<svelte:head>
	<title>{data.pageTitle} — OpenMates</title>
	<meta name="description" content={data.pageDescription} />
	<meta name="robots" content={data.isDevHost ? 'noindex, nofollow' : 'index, follow'} />
	<link rel="canonical" href={data.canonicalUrl} />
	<link rel="alternate" hreflang={data.locale} href={data.canonicalUrl} />
	<link rel="alternate" hreflang={data.alternateLocale} href={data.alternateUrl} />
	<link rel="alternate" hreflang="x-default" href={data.locale === 'en' ? data.canonicalUrl : data.alternateUrl} />

	<meta property="og:type" content={data.selectedSlug ? 'article' : 'website'} />
	<meta property="og:url" content={data.canonicalUrl} />
	<meta property="og:title" content={`${data.pageTitle} — OpenMates`} />
	<meta property="og:description" content={data.pageDescription} />
	<meta property="og:site_name" content="OpenMates" />
	<meta property="og:locale" content={data.locale === 'de' ? 'de_DE' : 'en_US'} />
	{#if data.ogImage}<meta property="og:image" content={data.ogImage} />{/if}

	<meta name="twitter:card" content={data.ogImage ? 'summary_large_image' : 'summary'} />
	<meta name="twitter:title" content={`${data.pageTitle} — OpenMates`} />
	<meta name="twitter:description" content={data.pageDescription} />
	{#if data.ogImage}<meta name="twitter:image" content={data.ogImage} />{/if}

	<!-- eslint-disable-next-line svelte/no-at-html-tags -->
	{@html `<script type="application/ld+json">${data.jsonLd}<` + `/script>`}
</svelte:head>

<NewsroomSurface view={data.view} locale={data.locale} data={data.surface} onAction={handleAction} />
