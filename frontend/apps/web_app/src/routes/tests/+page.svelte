<!--
  Latest Playwright recording gallery.
  Shows one card per spec with a reused test screenshot thumbnail and links to
  the detail page where video, screenshots, and timestamped steps are shown.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import {
		fetchTestRecordings,
		formatDuration,
		type TestRecordingsIndex
	} from './testRecordings';

	let data: TestRecordingsIndex | null = $state(null);
	let errorMessage = $state('');
	let isLoading = $state(true);

	onMount(async () => {
		try {
			data = await fetchTestRecordings();
		} catch (error) {
			errorMessage = error instanceof Error ? error.message : 'Failed to load test recordings.';
		} finally {
			isLoading = false;
		}
	});
</script>

<svelte:head>
	<title>Playwright Test Recordings | OpenMates</title>
	<meta name="robots" content="noindex,nofollow" />
</svelte:head>

<main class="tests-page">
	<header class="hero">
		<div>
			<p class="eyebrow">Dev tools</p>
			<h1>Playwright test recordings</h1>
			<p class="subtitle">Latest video, screenshots, and step metadata for each E2E spec.</p>
		</div>
		{#if data?.run_id}
			<div class="run-card">
				<span>Latest run</span>
				<strong>{data.run_id}</strong>
				{#if data.git_sha}
					<small>{data.git_sha.slice(0, 9)} &middot; {data.git_branch}</small>
				{/if}
			</div>
		{/if}
	</header>

	{#if isLoading}
		<div class="state-card">Loading test recordings...</div>
	{:else if errorMessage}
		<div class="state-card error">{errorMessage}</div>
	{:else if !data?.tests?.length}
		<div class="state-card">No test recordings have been published yet.</div>
	{:else}
		<section class="grid" aria-label="Test recordings">
			{#each data.tests as test (test.slug)}
				<a class="test-card" class:failed={test.status !== 'passed'} href={`/tests/${test.slug}`}>
					<div class="thumb-wrap">
						{#if test.assets?.thumbnail_url}
							<img src={test.assets.thumbnail_url} alt={`Thumbnail for ${test.title}`} loading="lazy" />
						{:else}
							<div class="thumb-placeholder">No thumbnail</div>
						{/if}
						<span class="status">{test.status}</span>
					</div>
					<div class="card-body">
						<h2>{test.title}</h2>
						<p>{formatDuration(test.duration_seconds)}</p>
						{#if test.error}
							<small>{test.error}</small>
						{/if}
					</div>
				</a>
			{/each}
		</section>
	{/if}
</main>

<style>
	.tests-page {
		min-height: 100vh;
		padding: clamp(24px, 4vw, 56px);
		font-family: var(--font-primary, 'Lexend Deca Variable'), sans-serif;
		color: var(--color-font-primary);
		background:
			radial-gradient(circle at top left, color-mix(in srgb, var(--color-button-primary) 16%, transparent), transparent 34rem),
			var(--color-grey-0);
	}

	.hero {
		display: flex;
		justify-content: space-between;
		gap: 24px;
		align-items: flex-end;
		margin: 0 auto 32px;
		max-width: 1300px;
	}

	.eyebrow {
		margin: 0 0 8px;
		font-size: 13px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--color-font-secondary);
	}

	h1 {
		margin: 0;
		font-size: clamp(34px, 6vw, 68px);
		line-height: 0.95;
		letter-spacing: -0.05em;
	}

	.subtitle {
		max-width: 680px;
		margin: 14px 0 0;
		font-size: 17px;
		color: var(--color-font-secondary);
	}

	.run-card,
	.state-card {
		border: 1px solid var(--color-grey-20);
		border-radius: 24px;
		background: color-mix(in srgb, var(--color-grey-0) 84%, transparent);
		box-shadow: 0 18px 40px rgba(0, 0, 0, 0.08);
	}

	.run-card {
		display: grid;
		gap: 5px;
		min-width: 240px;
		padding: 18px;
	}

	.run-card span,
	.run-card small,
	.card-body p,
	.card-body small {
		color: var(--color-font-secondary);
	}

	.run-card strong {
		font-size: 15px;
		word-break: break-word;
	}

	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: 22px;
		max-width: 1300px;
		margin: 0 auto;
	}

	.test-card {
		overflow: hidden;
		border: 1px solid var(--color-grey-20);
		border-radius: 28px;
		background: var(--color-grey-0);
		box-shadow: 0 18px 42px rgba(0, 0, 0, 0.1);
		text-decoration: none;
		color: inherit;
		transition:
			transform 0.18s ease,
			box-shadow 0.18s ease;
	}

	.test-card:hover {
		transform: translateY(-3px);
		box-shadow: 0 24px 54px rgba(0, 0, 0, 0.14);
	}

	.thumb-wrap {
		position: relative;
		aspect-ratio: 16 / 10;
		background: var(--color-grey-10);
	}

	.thumb-wrap img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}

	.thumb-placeholder {
		display: grid;
		place-items: center;
		height: 100%;
		color: var(--color-font-secondary);
	}

	.status {
		position: absolute;
		top: 12px;
		right: 12px;
		padding: 6px 10px;
		border-radius: 999px;
		background: #148a4d;
		color: white;
		font-size: 12px;
		font-weight: 700;
		text-transform: uppercase;
	}

	.failed .status {
		background: #c13333;
	}

	.card-body {
		display: grid;
		gap: 8px;
		padding: 18px;
	}

	.card-body h2 {
		margin: 0;
		font-size: 19px;
		line-height: 1.18;
	}

	.card-body p,
	.card-body small {
		margin: 0;
	}

	.card-body small {
		display: -webkit-box;
		overflow: hidden;
		-webkit-line-clamp: 3;
		-webkit-box-orient: vertical;
		font-size: 12px;
	}

	.state-card {
		max-width: 800px;
		margin: 0 auto;
		padding: 28px;
		text-align: center;
	}

	.state-card.error {
		color: #c13333;
	}

	@media (max-width: 760px) {
		.hero {
			align-items: stretch;
			flex-direction: column;
		}
	}
</style>
