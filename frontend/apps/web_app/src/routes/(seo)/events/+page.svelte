<!--
  frontend/apps/web_app/src/routes/(seo)/events/+page.svelte

  Crawlable public index for OpenMates events. This gives search engines a
  compact, stable /events destination with plain links to single-event pages,
  improving both event discovery and sitelink candidates.
-->
<script lang="ts">
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	function formatDate(value: string): string {
		const date = new Date(value);
		if (Number.isNaN(date.getTime())) return '';
		return date.toLocaleDateString(undefined, {
			weekday: 'short',
			month: 'short',
			day: 'numeric',
			year: 'numeric'
		});
	}
</script>

<svelte:head>
	<title>OpenMates Events</title>
	<meta
		name="description"
		content="Upcoming OpenMates community events, meetups, and sessions for people building privacy-first AI team mates."
	/>
	<link rel="canonical" href={data.canonicalUrl} />
	<meta name="robots" content={data.isDevHost ? 'noindex, nofollow' : 'index, follow'} />

	<meta property="og:type" content="website" />
	<meta property="og:url" content={data.canonicalUrl} />
	<meta property="og:title" content="OpenMates Events" />
	<meta
		property="og:description"
		content="Upcoming OpenMates community events, meetups, and sessions."
	/>
	<meta property="og:image" content="https://openmates.org/images/og-image.jpg" />
	<meta property="og:site_name" content="OpenMates" />

	<meta name="twitter:card" content="summary_large_image" />
	<meta name="twitter:title" content="OpenMates Events" />
	<meta name="twitter:description" content="Upcoming OpenMates community events and meetups." />
	<meta name="twitter:image" content="https://openmates.org/images/og-image.jpg" />

	<!-- eslint-disable-next-line svelte/no-at-html-tags -->
	{@html `<script type="application/ld+json">${data.jsonLd}<` + `/script>`}
</svelte:head>

<main aria-label="OpenMates events">
	<header>
		<p class="eyebrow">OpenMates Community</p>
		<h1>OpenMates Events</h1>
		<p class="intro">
			Meet people building and using privacy-first AI team mates. Join upcoming
			OpenMates meetups, talks, and community sessions.
		</p>
	</header>

	{#if data.events.length === 0}
		<p class="empty">No upcoming OpenMates events are listed yet.</p>
	{:else}
		<ol class="event-list">
			{#each data.events as event}
				<li>
					<a href="/events/{event.slug}">
						<img src={event.image_url} alt="" loading="lazy" decoding="async" />
						<span class="event-copy">
							<span class="event-title">{event.title}</span>
							<span class="event-summary">{event.summary}</span>
							<span class="event-meta">
								<time datetime={event.date_start}>{formatDate(event.date_start)}</time>
								<span>{event.venue.city}, {event.venue.country}</span>
							</span>
						</span>
					</a>
				</li>
			{/each}
		</ol>
	{/if}

	<footer>
		<a href="/">Try OpenMates</a>
	</footer>
</main>

<style>
	main {
		max-width: 920px;
		margin: 0 auto;
		padding: 32px 24px;
		font-family:
			-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
		color: #171717;
		background: #fff;
	}

	header {
		max-width: 720px;
		margin-bottom: 34px;
	}

	.eyebrow {
		margin: 0 0 10px;
		font-size: 13px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: #a20000;
	}

	h1 {
		margin: 0;
		font-size: clamp(36px, 7vw, 64px);
		line-height: 1;
		letter-spacing: -0.05em;
	}

	.intro {
		margin: 18px 0 0;
		font-size: 19px;
		line-height: 1.55;
		color: #4a4a4a;
	}

	.empty {
		color: #666;
	}

	.event-list {
		display: flex;
		flex-direction: column;
		gap: 16px;
		padding: 0;
		margin: 0;
		list-style: none;
	}

	li {
		border: 1px solid #e8e8e8;
		border-radius: 20px;
		overflow: hidden;
		background: #fafafa;
	}

	a {
		color: inherit;
		text-decoration: none;
	}

	.event-list a {
		display: grid;
		grid-template-columns: minmax(140px, 220px) 1fr;
		gap: 20px;
		align-items: stretch;
	}

	img {
		width: 100%;
		height: 100%;
		min-height: 150px;
		object-fit: cover;
	}

	.event-copy {
		display: flex;
		flex-direction: column;
		gap: 10px;
		padding: 22px 22px 22px 0;
	}

	.event-title {
		font-size: 24px;
		font-weight: 800;
		letter-spacing: -0.03em;
	}

	.event-summary {
		font-size: 15px;
		line-height: 1.5;
		color: #555;
	}

	.event-meta {
		display: flex;
		flex-wrap: wrap;
		gap: 8px 16px;
		font-size: 13px;
		font-weight: 700;
		color: #a20000;
	}

	footer {
		margin-top: 42px;
		padding-top: 20px;
		border-top: 1px solid #eee;
	}

	footer a {
		font-weight: 700;
		color: #a20000;
	}

	@media (max-width: 680px) {
		main {
			padding: 20px 16px;
		}

		.event-list a {
			grid-template-columns: 1fr;
			gap: 0;
		}

		.event-copy {
			padding: 18px;
		}
	}
</style>
