<!--
  ChatMessageStatic — lightweight chat message renderer for media generation.

  Renders a chat message bubble (user or assistant) using markdown-it for
  HTML conversion. Zero store dependencies, zero TipTap, zero IndexedDB.
  Visually matches the real ChatMessage component from @repo/ui.

  Props:
    role        - 'user' | 'assistant'
    content     - Markdown string
    category    - Mate category (e.g. 'general_knowledge') for profile image
    mateName    - Display name for the mate (defaults to category label)
    containerWidth - Container width for mobile layout switching

  Architecture: docs/media-generation.md
-->
<script lang="ts">
	import { onMount } from 'svelte';

	let {
		role = 'user',
		content = '',
		category = 'general_knowledge',
		mateName = '',
		containerWidth = 400
	}: {
		role?: 'user' | 'assistant';
		content?: string;
		category?: string;
		mateName?: string;
		containerWidth?: number;
	} = $props();

	let renderedHtml = $state('');
	let isMobileStacked = $derived(containerWidth <= 500);

	// Category to display name mapping
	const CATEGORY_NAMES: Record<string, string> = {
		general_knowledge: 'George',
		software_development: 'Dev',
		cooking_food: 'Chef',
		science: 'Sci',
		design: 'Design',
		finance: 'Fin',
		legal_law: 'Legal',
		medical_health: 'Med',
		life_coach_psychology: 'Coach',
		history: 'History',
		marketing_sales: 'Marketing',
		business_development: 'Biz',
		movies_tv: 'Movies',
		maker_prototyping: 'Maker',
		activism: 'Activist',
		electrical_engineering: 'EE',
		onboarding_support: 'Support'
	};

	let displayName = $derived(mateName || CATEGORY_NAMES[category] || 'George');

	onMount(async () => {
		const MarkdownIt = (await import('markdown-it')).default;
		const md = new MarkdownIt({ html: true, linkify: true, typographer: true, breaks: false });
		renderedHtml = md.render(content);
	});
</script>

<div
	class="static-message {role}"
	class:mobile-stacked={role === 'assistant' && isMobileStacked}
>
	{#if role === 'assistant'}
		<div class="static-mate-profile {category}"></div>
	{/if}

	<div class="static-message-content {role === 'user' ? 'static-user-content' : 'static-mate-content'}">
		{#if role === 'assistant'}
			<div class="static-mate-name">{displayName}</div>
		{/if}
		<div class="static-message-text">
			{#if renderedHtml}
				{@html renderedHtml}
			{:else}
				<p>{content}</p>
			{/if}
		</div>
	</div>
</div>

<style>
	.static-message {
		display: flex;
		align-items: flex-start;
		gap: 6px;
		width: 100%;
		margin-bottom: 4px;
	}

	.static-message.user {
		justify-content: flex-end;
	}

	.static-message.assistant {
		justify-content: flex-start;
	}

	.static-message.assistant.mobile-stacked {
		flex-direction: column;
		align-items: flex-start;
	}

	/* ── Mate profile ─────────────────────────────────────────── */
	.static-mate-profile {
		width: 40px;
		height: 40px;
		margin: 4px;
		border-radius: 50%;
		background-position: center;
		background-size: cover;
		background-repeat: no-repeat;
		box-shadow: 0 4px 4px rgba(0, 0, 0, 0.25);
		flex-shrink: 0;
	}

	/* Mate category images — uses the same static assets as the real component */
	.static-mate-profile.general_knowledge {
		background-image: url('@openmates/ui/static/images/mates/general_knowledge.jpeg');
	}
	.static-mate-profile.software_development {
		background-image: url('@openmates/ui/static/images/mates/software_development.jpeg');
	}
	.static-mate-profile.cooking_food {
		background-image: url('@openmates/ui/static/images/mates/cooking_food.jpeg');
	}
	.static-mate-profile.science {
		background-image: url('@openmates/ui/static/images/mates/science.jpeg');
	}
	.static-mate-profile.design {
		background-image: url('@openmates/ui/static/images/mates/design.jpeg');
	}
	.static-mate-profile.finance {
		background-image: url('@openmates/ui/static/images/mates/finance.jpeg');
	}
	.static-mate-profile.legal_law {
		background-image: url('@openmates/ui/static/images/mates/legal_law.jpeg');
	}
	.static-mate-profile.medical_health {
		background-image: url('@openmates/ui/static/images/mates/medical_health.jpeg');
	}
	.static-mate-profile.life_coach_psychology {
		background-image: url('@openmates/ui/static/images/mates/life_coach_psychology.jpeg');
	}
	.static-mate-profile.history {
		background-image: url('@openmates/ui/static/images/mates/history.jpeg');
	}
	.static-mate-profile.marketing_sales {
		background-image: url('@openmates/ui/static/images/mates/marketing_sales.jpeg');
	}
	.static-mate-profile.business_development {
		background-image: url('@openmates/ui/static/images/mates/business_development.jpeg');
	}
	.static-mate-profile.movies_tv {
		background-image: url('@openmates/ui/static/images/mates/movies_tv.jpeg');
	}
	.static-mate-profile.maker_prototyping {
		background-image: url('@openmates/ui/static/images/mates/maker_prototyping.jpeg');
	}
	.static-mate-profile.activism {
		background-image: url('@openmates/ui/static/images/mates/activism.jpeg');
	}
	.static-mate-profile.electrical_engineering {
		background-image: url('@openmates/ui/static/images/mates/electrical_engineering.jpeg');
	}
	.static-mate-profile.onboarding_support {
		background-image: url('@openmates/ui/static/images/mates/onboarding_support.jpeg');
	}

	/* ── Message bubbles ──────────────────────────────────────── */
	.static-user-content {
		background-color: var(--color-grey-blue, #2d2f35);
		color: var(--color-grey-100, #fff);
		padding: 12px;
		border-radius: 13px;
		max-width: calc(100% - 70px);
		margin-left: auto;
		filter: drop-shadow(0 4px 4px rgba(0, 0, 0, 0.25));
	}

	.static-mate-content {
		background-color: var(--color-grey-0, #171717);
		color: var(--color-font-primary, #e6e6e6);
		padding: 12px;
		border-radius: 13px;
		max-width: calc(100% - 70px);
		filter: drop-shadow(0 4px 4px rgba(0, 0, 0, 0.25));
	}

	.static-mate-name {
		font-size: 0.8125rem;
		font-weight: 600;
		color: var(--color-font-secondary, #cfcfcf);
		margin-bottom: 4px;
	}

	/* ── Markdown content styling ─────────────────────────────── */
	.static-message-text {
		font-size: 0.9375rem;
		line-height: 1.5;
	}

	.static-message-text :global(p) {
		margin: 0 0 8px;
	}

	.static-message-text :global(p:last-child) {
		margin-bottom: 0;
	}

	.static-message-text :global(strong) {
		font-weight: 700;
		color: var(--color-bold-text, #c9bbff);
	}

	.static-message-text :global(em) {
		font-style: italic;
	}

	.static-message-text :global(ul),
	.static-message-text :global(ol) {
		margin: 4px 0;
		padding-left: 20px;
	}

	.static-message-text :global(li) {
		margin-bottom: 2px;
	}

	.static-message-text :global(li p) {
		margin: 0;
	}

	.static-message-text :global(code) {
		background: rgba(255, 255, 255, 0.08);
		padding: 1px 4px;
		border-radius: 3px;
		font-size: 0.875em;
		font-family: 'JetBrains Mono Variable', monospace;
	}

	.static-message-text :global(pre) {
		background: rgba(0, 0, 0, 0.3);
		padding: 12px;
		border-radius: 8px;
		overflow-x: auto;
		margin: 8px 0;
	}

	.static-message-text :global(pre code) {
		background: none;
		padding: 0;
	}

	.static-message-text :global(a) {
		color: #7a9bf0;
		text-decoration: none;
	}

	.static-message-text :global(blockquote) {
		border-left: 3px solid var(--color-grey-40, #404040);
		margin: 8px 0;
		padding-left: 12px;
		color: var(--color-font-secondary, #cfcfcf);
	}
</style>
