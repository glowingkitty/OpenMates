<!--
  MockAppScreen — high-fidelity static replica of the OpenMates app UI for media generation.

  Renders a full app layout (header, optional sidebar, content area, input bar)
  that visually matches the real app. Zero store dependencies — all data is
  hardcoded or passed via props.

  Modes:
    'new-chat'  — Header + suggestion cards + input bar (phone layout)
    'chat'      — Header + optional sidebar + chat banner + messages + input bar (desktop layout)

  Usage:
    <MockAppScreen mode="new-chat" scale={0.52} containerWidth={220} />
    <MockAppScreen mode="chat" messages={msgs} showSidebar scale={0.58} containerWidth={560} />

  Architecture: docs/media-generation.md
-->
<script lang="ts">
	import ChatMessageStatic from './ChatMessageStatic.svelte';
	import ThemeScope from './ThemeScope.svelte';
	import type { MediaMessage } from '../data/types';

	let {
		mode = 'new-chat',
		messages = [],
		scale = 0.52,
		containerWidth = 220,
		containerHeight = 430,
		showSidebar = false,
		chatTitle = 'Cuttlefish Colors',
		chatCategory = 'general_knowledge',
		theme = 'dark'
	}: {
		mode?: 'new-chat' | 'chat';
		messages?: MediaMessage[];
		scale?: number;
		containerWidth?: number;
		containerHeight?: number;
		showSidebar?: boolean;
		chatTitle?: string;
		chatCategory?: string;
		theme?: 'dark' | 'light';
	} = $props();

	let virtualWidth = $derived(containerWidth / scale);
	let virtualHeight = $derived(containerHeight / scale);

	/* ── Mock sidebar chat list ────────────────────────────────── */
	const SIDEBAR_CHATS = [
		{ title: 'Cuttlefish Colors', category: 'general_knowledge', preview: 'Chromatophores allow rapid...', active: true },
		{ title: 'React Hooks Guide', category: 'software_development', preview: 'Let me explain useEffect...' },
		{ title: 'Pasta Carbonara', category: 'cooking_food', preview: 'The traditional recipe uses...' },
		{ title: 'Morning Routine', category: 'life_coach_psychology', preview: 'A balanced morning starts...' },
		{ title: 'Market Analysis', category: 'finance', preview: 'Based on recent trends...' },
		{ title: 'Movie Recommendations', category: 'movies_tv', preview: 'Here are some great films...' },
		{ title: 'Logo Redesign', category: 'design', preview: 'For a modern look, I suggest...' },
		{ title: 'Circuit Design', category: 'electrical_engineering', preview: 'The voltage divider circuit...' },
	];

	/* ── Mock suggestion cards ─────────────────────────────────── */
	const SUGGESTION_CARDS = [
		{ text: 'Find the latest tech news', gradient: 'linear-gradient(135deg, #155D91 9%, #42ABF4 90%)' },
		{ text: 'What is quantum computing?', gradient: 'linear-gradient(135deg, #b85a3a 9%, #e8956e 90%)' },
		{ text: 'Generate a sunset landscape', gradient: 'linear-gradient(135deg, #7b2d8e 9%, #c850c0 90%)' },
		{ text: 'Check healthy breakfast ideas', gradient: 'linear-gradient(135deg, #fd50a0 9%, #f42c2d 90%)' },
		{ text: 'Plan a weekly budget', gradient: 'linear-gradient(135deg, #0a6e04 9%, #2cb81e 90%)' },
		{ text: 'Help me debug my Python code', gradient: 'linear-gradient(135deg, #155D91 9%, #42ABF4 90%)' },
		{ text: 'Write a short bedtime story', gradient: 'linear-gradient(135deg, #b85a3a 9%, #e8956e 90%)' },
		{ text: "Explain how black holes form", gradient: 'linear-gradient(135deg, #CE5B06 9%, #8F220E 90%)' },
		{ text: 'Best practices for React hooks', gradient: 'linear-gradient(135deg, #155D91 9%, #42ABF4 90%)' },
		{ text: 'Easy 15-min workout routine', gradient: 'linear-gradient(135deg, #8a0048 9%, #d63084 90%)' },
	];

	/* ── Category gradient map (matches categoryUtils.ts) ──────── */
	const CATEGORY_GRADIENTS: Record<string, string> = {
		general_knowledge: 'linear-gradient(135deg, #DE1E66 9%, #FF763B 90%)',
		software_development: 'linear-gradient(135deg, #155D91 9%, #42ABF4 90%)',
		cooking_food: 'linear-gradient(135deg, #FD8450 9%, #F42C2D 90%)',
		life_coach_psychology: 'linear-gradient(135deg, #FDB250 9%, #F42C2D 90%)',
		finance: 'linear-gradient(135deg, #119106 9%, #15780D 90%)',
		movies_tv: 'linear-gradient(135deg, #00C2C5 9%, #3170DC 90%)',
		design: 'linear-gradient(135deg, #101010 9%, #2E2E2E 90%)',
		electrical_engineering: 'linear-gradient(135deg, #233888 9%, #2E4EC8 90%)',
		medical_health: 'linear-gradient(135deg, #FD50A0 9%, #F42C2D 90%)',
		science: 'linear-gradient(135deg, #CE5B06 9%, #8F220E 90%)',
		history: 'linear-gradient(135deg, #4989F2 9%, #2F44BF 90%)',
		activism: 'linear-gradient(135deg, #F53D00 9%, #F56200 90%)',
		maker_prototyping: 'linear-gradient(135deg, #EA7600 9%, #FBAB59 90%)',
		marketing_sales: 'linear-gradient(135deg, #FF8C00 9%, #F4B400 90%)',
		business_development: 'linear-gradient(135deg, #004040 9%, #008080 90%)',
		onboarding_support: 'linear-gradient(135deg, #6364FF 9%, #9B6DFF 90%)',
	};

	function getCategoryGradient(category: string): string {
		return CATEGORY_GRADIENTS[category] || CATEGORY_GRADIENTS.general_knowledge;
	}
</script>

<ThemeScope {theme}>
	<div
		class="mock-app-screen"
		style="transform: scale({scale}); transform-origin: top left; width: {virtualWidth}px; height: {virtualHeight}px;"
	>
		<!-- ── Header ──────────────────────────────────────────── -->
		<div class="mock-header">
			<div class="mock-header-left">
				<div class="mock-hamburger">
					<span></span><span></span><span></span>
				</div>
				<div class="mock-logo">
					<span class="mock-logo-open">Open</span><span class="mock-logo-mates">Mates</span>
				</div>
			</div>
			<div class="mock-header-right">
				<div class="mock-user-avatar"></div>
			</div>
		</div>

		<!-- ── Body ────────────────────────────────────────────── -->
		<div class="mock-body">
			{#if showSidebar && mode === 'chat'}
				<!-- Sidebar -->
				<div class="mock-sidebar">
					<div class="mock-sidebar-header">
						<span class="mock-sidebar-title">Chats</span>
					</div>
					<div class="mock-chat-list">
						{#each SIDEBAR_CHATS as chat}
							<div class="mock-chat-item" class:active={chat.title === chatTitle}>
								<div
									class="mock-chat-circle"
									style="background: {getCategoryGradient(chat.category)};"
								></div>
								<div class="mock-chat-item-text">
									<div class="mock-chat-item-title">{chat.title}</div>
									<div class="mock-chat-item-preview">{chat.preview}</div>
								</div>
							</div>
						{/each}
					</div>
				</div>
			{/if}

			<!-- Main content -->
			<div class="mock-main">
				{#if mode === 'new-chat'}
					<!-- New chat: suggestion cards -->
					<div class="mock-new-chat">
						<div class="mock-greeting">
							<div class="mock-greeting-text">How can I help you today?</div>
						</div>
						<div class="mock-suggestions">
							{#each SUGGESTION_CARDS as card}
								<div class="mock-suggestion-card" style="background: {card.gradient};">
									<span class="mock-suggestion-text">{card.text}</span>
								</div>
							{/each}
						</div>
					</div>
				{:else}
					<!-- Existing chat: banner + messages -->
					<div class="mock-chat-content">
						<!-- Chat header banner -->
						<div
							class="mock-chat-banner"
							style="background: {getCategoryGradient(chatCategory)};"
						>
							<div
								class="mock-banner-icon"
								style="background-image: url('@openmates/ui/static/images/mates/{chatCategory}.jpeg');"
							></div>
							<div class="mock-banner-title">{chatTitle}</div>
						</div>

						<!-- Messages -->
						<div class="mock-messages">
							{#each messages as msg}
								<ChatMessageStatic
									role={msg.role}
									content={msg.content}
									category={msg.category}
									mateName={msg.mate_name}
									containerWidth={showSidebar ? virtualWidth - 250 : virtualWidth}
								/>
							{/each}
						</div>
					</div>
				{/if}

				<!-- Input bar -->
				<div class="mock-input-bar">
					<div class="mock-input-field">
						<span class="mock-input-placeholder">
							{mode === 'new-chat' ? 'Ask me anything...' : 'Reply...'}
						</span>
					</div>
					<div class="mock-send-button">
						<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
							<line x1="22" y1="2" x2="11" y2="13"></line>
							<polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
						</svg>
					</div>
				</div>
			</div>
		</div>
	</div>
</ThemeScope>

<style>
	/* ── Screen container ─────────────────────────────────────── */
	.mock-app-screen {
		display: flex;
		flex-direction: column;
		background: var(--color-grey-0, #171717);
		overflow: hidden;
		font-family: var(--font-primary, 'Lexend Deca Variable'), system-ui, sans-serif;
	}

	/* ── Header ───────────────────────────────────────────────── */
	.mock-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 14px 16px 8px;
		flex-shrink: 0;
	}

	.mock-header-left {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.mock-hamburger {
		display: flex;
		flex-direction: column;
		gap: 3px;
		cursor: pointer;
		padding: 4px;
	}

	.mock-hamburger span {
		display: block;
		width: 16px;
		height: 1.5px;
		/* Intentional hardcoded: static media asset */
		background: var(--color-grey-70, #a0a0a0);
		border-radius: 1px;
	}

	.mock-logo {
		font-size: 1.125rem;
		font-weight: 700;
		letter-spacing: -0.01em;
	}

	.mock-logo-open {
		/* Intentional hardcoded: brand color for "Open" in media assets */
		background: #4867cd;
		color: var(--color-grey-20, #212121);
		padding: 0 3px;
		border-radius: 2px;
	}

	.mock-logo-mates {
		color: var(--color-grey-100, #fff);
	}

	.mock-header-right {
		display: flex;
		align-items: center;
	}

	.mock-user-avatar {
		width: 28px;
		height: 28px;
		border-radius: 50%;
		/* Intentional hardcoded: generic avatar placeholder */
		background: linear-gradient(135deg, #4867cd 9%, #5a85eb 90%);
		opacity: 0.7;
	}

	/* ── Body ─────────────────────────────────────────────────── */
	.mock-body {
		display: flex;
		flex: 1;
		overflow: hidden;
	}

	/* ── Sidebar ──────────────────────────────────────────────── */
	.mock-sidebar {
		width: 230px;
		flex-shrink: 0;
		background: var(--color-grey-10, #1c1c1c);
		border-right: 1px solid var(--color-grey-25, #252525);
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.mock-sidebar-header {
		padding: 12px 14px 8px;
		flex-shrink: 0;
	}

	.mock-sidebar-title {
		font-size: 0.8125rem;
		font-weight: 600;
		color: var(--color-font-secondary, #cfcfcf);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.mock-chat-list {
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.mock-chat-item {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 8px 14px;
		cursor: pointer;
	}

	.mock-chat-item.active {
		background: var(--color-grey-20, #212121);
	}

	.mock-chat-circle {
		width: 32px;
		height: 32px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	.mock-chat-item-text {
		flex: 1;
		min-width: 0;
		overflow: hidden;
	}

	.mock-chat-item-title {
		font-size: 0.8125rem;
		font-weight: 600;
		color: var(--color-font-primary, #e6e6e6);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.mock-chat-item-preview {
		font-size: 0.6875rem;
		color: var(--color-font-secondary, #cfcfcf);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		margin-top: 1px;
	}

	/* ── Main content ─────────────────────────────────────────── */
	.mock-main {
		flex: 1;
		display: flex;
		flex-direction: column;
		overflow: hidden;
		min-width: 0;
	}

	/* ── New chat mode ────────────────────────────────────────── */
	.mock-new-chat {
		flex: 1;
		display: flex;
		flex-direction: column;
		justify-content: center;
		align-items: center;
		padding: 16px;
		overflow: hidden;
	}

	.mock-greeting {
		margin-bottom: 20px;
		text-align: center;
	}

	.mock-greeting-text {
		font-size: 1.375rem;
		font-weight: 700;
		color: var(--color-font-primary, #e6e6e6);
		opacity: 0.7;
	}

	.mock-suggestions {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		justify-content: center;
		max-width: 100%;
		padding: 0 4px;
	}

	.mock-suggestion-card {
		display: flex;
		align-items: center;
		padding: 10px 14px;
		border-radius: 12px;
		min-width: 0;
		max-width: 280px;
		/* Intentional hardcoded: shadow for media assets */
		box-shadow: 0 4px 8px rgba(0, 0, 0, 0.3);
	}

	.mock-suggestion-text {
		font-size: 0.8125rem;
		font-weight: 600;
		color: #fff;
		line-height: 1.3;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	/* ── Chat mode ────────────────────────────────────────────── */
	.mock-chat-content {
		flex: 1;
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}

	.mock-chat-banner {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 6px;
		padding: 20px 16px;
		min-height: 120px;
		border-radius: 0 0 14px 14px;
		flex-shrink: 0;
		position: relative;
		overflow: hidden;
	}

	.mock-banner-icon {
		width: 36px;
		height: 36px;
		border-radius: 50%;
		background-size: cover;
		background-position: center;
		/* Intentional hardcoded: shadow for media assets */
		box-shadow: 0 4px 4px rgba(0, 0, 0, 0.25);
		flex-shrink: 0;
	}

	.mock-banner-title {
		font-size: 1.125rem;
		font-weight: 700;
		color: #fff;
		text-align: center;
		text-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
	}

	.mock-messages {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 0;
		padding: 8px 8px;
		overflow: hidden;
	}

	/* ── Input bar ────────────────────────────────────────────── */
	.mock-input-bar {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 12px 12px;
		flex-shrink: 0;
	}

	.mock-input-field {
		flex: 1;
		background: var(--color-grey-20, #212121);
		border: 1px solid var(--color-grey-30, #2c2c2c);
		border-radius: 20px;
		padding: 10px 16px;
		display: flex;
		align-items: center;
	}

	.mock-input-placeholder {
		font-size: 0.875rem;
		color: var(--color-grey-50, #606060);
	}

	.mock-send-button {
		width: 34px;
		height: 34px;
		border-radius: 50%;
		/* Intentional hardcoded: send button color for media assets */
		background: #ff553b;
		display: flex;
		align-items: center;
		justify-content: center;
		color: #fff;
		flex-shrink: 0;
	}
</style>
