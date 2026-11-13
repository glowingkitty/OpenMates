<!--
	frontend/apps/web_app/src/routes/(minimal)/present/+page.svelte

	Audience window of a slide presentation (opened by presenter mode of the deck
	viewer). Same origin, no app shell: it only needs the theme, fonts and
	translations. It holds no deck data: the slides arrive from the presenter
	window through a BroadcastChannel keyed by the random `session` in the URL.
-->
<script lang="ts">
	import '@repo/ui/src/styles/theme.css';
	import '@repo/ui/src/styles/fonts.css';
	import { onMount } from 'svelte';
	import { setupI18n } from '@repo/ui/i18n/setup';
	import SlidesAudienceWindow from '@repo/ui/components/embeds/slides/SlidesAudienceWindow.svelte';

	let ready = $state(false);
	let sessionId = $state('');

	onMount(async () => {
		sessionId = new URLSearchParams(window.location.search).get('session') ?? '';
		await setupI18n();
		ready = true;
	});

	function ended() {
		window.close();
	}
</script>

{#if ready && sessionId}
	<SlidesAudienceWindow {sessionId} onEnded={ended} />
{/if}
