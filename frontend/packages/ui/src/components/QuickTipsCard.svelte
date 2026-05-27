<!--
  QuickTipsCard.svelte

  Colorful post-response product tip card for chat.
  Receives encrypted metadata after client decryption as stable slugs only.
  UI copy is loaded from i18n through the quick tips registry.
-->
<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { fade } from 'svelte/transition';
  import { text } from '@repo/ui';
  import { getQuickTip, type QuickTipDefinition } from '../data/quickTips';
  import { getCategoryGradientColors } from '../utils/categoryUtils';

  let {
    slugs = [],
    category = null,
  }: {
    slugs?: string[];
    category?: string | null;
  } = $props();

  const dispatch = createEventDispatcher<{
    action: QuickTipDefinition;
  }>();

  let activeTip = $derived.by(() => {
    for (const slug of slugs) {
      const tip = getQuickTip(slug);
      if (tip) return tip;
    }
    return null;
  });

  let gradientStyle = $derived.by(() => {
    const colors = category ? getCategoryGradientColors(category) : null;
    return colors
      ? `background: linear-gradient(135deg, ${colors.start}, ${colors.end});`
      : 'background: var(--color-primary);';
  });

  function handleAction(tip: QuickTipDefinition): void {
    dispatch('action', tip);
  }

  function handleCardAction(tip: QuickTipDefinition): void {
    if (!tip.ctaLabelKey || !tip.ctaAction) return;
    handleAction(tip);
  }

  function handleCardKeydown(event: KeyboardEvent, tip: QuickTipDefinition): void {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    handleCardAction(tip);
  }
</script>

{#if activeTip}
  <section
    class="quick-tip-card"
    data-testid="quick-tip-card"
    data-quick-tip-slug={activeTip.slug}
    role="button"
    tabindex="0"
    style={gradientStyle}
    onclick={() => handleCardAction(activeTip)}
    onkeydown={(event) => handleCardKeydown(event, activeTip)}
    transition:fade={{ duration: 200 }}
  >
    <div class="quick-tip-content">
      <p class="quick-tip-eyebrow">{$text('chat.quick_tips.eyebrow')}</p>
      <h3>{$text(activeTip.titleKey)}</h3>
      <p class="quick-tip-body">{$text(activeTip.bodyKey)}</p>
      {#if activeTip.ctaLabelKey && activeTip.ctaAction}
        <button
          class="quick-tip-cta"
          type="button"
          data-testid="quick-tip-cta"
          onclick={(event) => {
            event.stopPropagation();
            handleAction(activeTip);
          }}
        >
          {$text(activeTip.ctaLabelKey)}
        </button>
      {/if}
    </div>
  </section>
{/if}

<style>
  .quick-tip-card {
    position: relative;
    width: 100%;
    height: 170px;
    display: flex;
    align-items: center;
    justify-content: center;
    box-sizing: border-box;
    overflow: hidden;
    border-radius: var(--radius-6);
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18);
    user-select: none;
  }

  .quick-tip-card[role='button'] {
    cursor: pointer;
  }

  .quick-tip-card[role='button']:focus-visible {
    outline: 2px solid rgba(255, 255, 255, 0.9);
    outline-offset: 2px;
  }

  .quick-tip-card::before {
    content: '';
    position: absolute;
    inset: 0;
    background:
      radial-gradient(circle at 15% 20%, rgba(255, 255, 255, 0.45), transparent 24%),
      radial-gradient(circle at 86% 82%, rgba(255, 255, 255, 0.22), transparent 32%);
    pointer-events: none;
  }

  .quick-tip-content {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    max-width: 700px;
    padding: 1rem 3rem;
    color: #fff;
    text-align: center;
  }

  .quick-tip-eyebrow {
    margin: 0 0 0.35rem;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    opacity: 0.82;
    color: #fff;
  }

  h3 {
    margin: 0;
    font-size: clamp(1rem, 0.96rem + 0.25vw, 1.15rem);
    line-height: 1.2;
    font-weight: 800;
    color: #fff;
  }

  .quick-tip-body {
    margin: 0.45rem 0 0;
    font-size: 0.92rem;
    line-height: 1.45;
    opacity: 0.94;
    color: #fff;
  }

  .quick-tip-cta {
    margin-top: 0.8rem;
    margin-right: 0;
    min-width: 0;
    min-height: 2rem;
    height: auto;
    padding: 0.35rem 0.8rem;
    border-radius: var(--radius-full);
    background-color: rgba(255, 255, 255, 0.2);
    color: #fff;
    font-size: 0.84rem;
    font-weight: 700;
    filter: none;
  }

  .quick-tip-cta:hover {
    background-color: rgba(255, 255, 255, 0.5);
    color: #fff;
  }

  .quick-tip-cta:active {
    background-color: rgba(255, 255, 255, 0.5);
    color: #fff;
    filter: none;
  }

  .quick-tip-cta:focus-visible {
    outline: 2px solid rgba(255, 255, 255, 0.9);
    outline-offset: 2px;
  }

  @media (max-width: 500px) {
    .quick-tip-card {
      height: auto;
      min-height: 170px;
    }

    .quick-tip-content {
      padding: 1rem;
    }
  }
</style>
