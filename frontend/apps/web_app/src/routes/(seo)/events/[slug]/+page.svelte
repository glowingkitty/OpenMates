<!--
  frontend/apps/web_app/src/routes/(seo)/events/[slug]/+page.svelte

  Crawlable public event page for /events/{slug}. Search engines and link
  preview bots receive semantic event content, canonical tags, OG tags, and
  schema.org/Event JSON-LD. Human browsers forward into the SPA fullscreen
  event embed via the slug-based #embed-id value.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	const descriptionParagraphs = $derived(data.event.description.split('\n\n').filter(Boolean));
	const eventStart = $derived(new Date(data.event.date_start));
	const eventEnd = $derived(new Date(data.event.date_end));
	const dateLine = $derived(
		Number.isNaN(eventStart.getTime())
			? ''
			: eventStart.toLocaleDateString(undefined, {
				weekday: 'long',
				year: 'numeric',
				month: 'long',
				day: 'numeric'
			})
	);
	const timeLine = $derived(
		Number.isNaN(eventStart.getTime())
			? ''
			: `${eventStart.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })} to ${eventEnd.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}`
	);

	onMount(() => {
		if (data.spaUrl) {
			const { pathname, search, hash } = new URL(data.spaUrl);
			window.location.replace(pathname + search + hash);
		}
	});
</script>

<svelte:head>
	<title>{data.event.title} — OpenMates Events</title>
	<meta name="description" content={data.event.summary} />
	<meta name="keywords" content={data.event.keywords.join(', ')} />
	<link rel="canonical" href={data.canonicalUrl} />
	<meta name="robots" content={data.isDevHost ? 'noindex, nofollow' : 'index, follow'} />

	<meta property="og:type" content="event" />
	<meta property="og:url" content={data.canonicalUrl} />
	<meta property="og:title" content="{data.event.title} — OpenMates Events" />
	<meta property="og:description" content={data.event.summary} />
	<meta property="og:image" content={data.event.image_url} />
	<meta property="og:site_name" content="OpenMates" />

	<meta name="twitter:card" content="summary_large_image" />
	<meta name="twitter:url" content={data.canonicalUrl} />
	<meta name="twitter:title" content="{data.event.title} — OpenMates Events" />
	<meta name="twitter:description" content={data.event.summary} />
	<meta name="twitter:image" content={data.event.image_url} />

	<!-- eslint-disable-next-line svelte/no-at-html-tags -->
	{@html `<script type="application/ld+json">${data.jsonLd}<` + `/script>`}
</svelte:head>

<main aria-label="{data.event.title} — OpenMates event">
	<article>
		<header>
			<img src={data.event.image_url} alt="{data.event.title} event cover" loading="eager" decoding="async" />
			<p class="eyebrow">OpenMates Event</p>
			<h1>{data.event.title}</h1>
			<p class="summary">{data.event.summary}</p>
		</header>

		<section class="details" aria-label="Event details">
			<div>
				<strong>Date & Time</strong>
				<span>{dateLine}</span>
				<span>{timeLine}</span>
			</div>
			<div>
				<strong>Location</strong>
				<span>{data.location}</span>
			</div>
			<div>
				<strong>Organizer</strong>
				<span>{data.event.organizer.name}</span>
			</div>
		</section>

		<section aria-label="About this event">
			<h2>About this event</h2>
			{#each descriptionParagraphs as paragraph}
				<p>{paragraph}</p>
			{/each}
		</section>

		<footer>
			<a href={data.spaUrl}>Open event in OpenMates</a>
			<span class="separator">·</span>
			<a href={data.event.url} rel="noopener noreferrer">Register on Luma</a>
		</footer>
	</article>
</main>

<style>
	main {
		max-width: 860px;
		margin: 0 auto;
		padding: 28px;
		font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
		color: #171717;
		background: #fff;
	}

	article {
		display: flex;
		flex-direction: column;
		gap: 28px;
	}

	img {
		width: 100%;
		height: auto;
		display: block;
		border-radius: 18px;
	}

	.eyebrow {
		margin: 22px 0 8px;
		font-size: 13px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: #a20000;
	}

	h1 {
		font-size: clamp(32px, 6vw, 54px);
		line-height: 1.02;
		margin: 0;
		letter-spacing: -0.04em;
	}

	h2 {
		font-size: 24px;
		margin: 0 0 14px;
	}

	p {
		font-size: 17px;
		line-height: 1.65;
		margin: 0 0 16px;
	}

	.summary {
		max-width: 720px;
		margin-top: 16px;
		font-size: 20px;
		color: #4a4a4a;
	}

	.details {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
		gap: 14px;
	}

	.details div {
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 18px;
		border: 1px solid #e8e8e8;
		border-radius: 16px;
		background: #fafafa;
	}

	.details strong {
		font-size: 13px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: #666;
	}

	footer {
		padding-top: 20px;
		border-top: 1px solid #e8e8e8;
		font-size: 15px;
	}

	a {
		color: #a20000;
		font-weight: 700;
		text-decoration: none;
	}

	a:hover {
		text-decoration: underline;
	}

	.separator {
		margin: 0 8px;
		color: #999;
	}

	@media (max-width: 640px) {
		main {
			padding: 16px;
		}
	}
</style>
