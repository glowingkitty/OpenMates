<!--
  MockChatFeed — renders a list of ChatMessageStatic components at a given scale.

  Designed to be placed inside DevicePhone or DeviceLaptop screen slots.
  Uses CSS transform to scale the messages to fit the device screen.

  Usage:
    <MockChatFeed messages={CHAT_MESSAGES} scale={0.52} containerWidth={220} />

  Architecture: docs/media-generation.md
-->
<script lang="ts">
	import ChatMessageStatic from './ChatMessageStatic.svelte';
	import ThemeScope from './ThemeScope.svelte';
	import type { MediaMessage } from '../data/types';

	let {
		messages = [],
		scale = 0.52,
		containerWidth = 220,
		theme = 'dark'
	}: {
		messages?: MediaMessage[];
		scale?: number;
		containerWidth?: number;
		theme?: 'dark' | 'light';
	} = $props();

	let inverseScale = $derived(100 / (scale * 100) * 100);
</script>

<ThemeScope {theme}>
	<div
		class="mock-chat-feed"
		style="transform: scale({scale}); transform-origin: top left; width: {inverseScale}%;"
	>
		{#each messages as msg}
			<ChatMessageStatic
				role={msg.role}
				content={msg.content}
				category={msg.category}
				mateName={msg.mate_name}
				{containerWidth}
			/>
		{/each}
	</div>
</ThemeScope>

<style>
	.mock-chat-feed {
		display: flex;
		flex-direction: column;
		gap: 0;
		padding: 8px 4px;
		overflow: hidden;
		height: 100%;
		pointer-events: none;
	}
</style>
