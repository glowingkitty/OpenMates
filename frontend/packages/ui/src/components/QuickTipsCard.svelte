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

  let {
    chatId,
    slugs = [],
  }: {
    chatId: string | null | undefined;
    slugs?: string[];
  } = $props();

  const dispatch = createEventDispatcher<{
    action: QuickTipDefinition;
  }>();

  let dismissedSlugs = $state<Set<string>>(new Set());

  function storageKey(slug: string): string | null {
    return chatId ? `openmates:quick-tip-dismissed:${chatId}:${slug}` : null;
  }

  function isDismissed(slug: string): boolean {
    const key = storageKey(slug);
    if (!key || typeof localStorage === 'undefined') return dismissedSlugs.has(slug);
    return dismissedSlugs.has(slug) || localStorage.getItem(key) === '1';
  }

  function dismiss(slug: string): void {
    dismissedSlugs = new Set([...dismissedSlugs, slug]);
    const key = storageKey(slug);
    if (key && typeof localStorage !== 'undefined') {
      localStorage.setItem(key, '1');
    }
  }

  let activeTip = $derived.by(() => {
    for (const slug of slugs) {
      const tip = getQuickTip(slug);
      if (tip && !isDismissed(slug)) return tip;
    }
    return null;
  });

  function handleAction(tip: QuickTipDefinition): void {
    dismiss(tip.slug);
    dispatch('action', tip);
  }
</script>

{#if activeTip}
  <section class="quick-tip-card" data-testid="quick-tip-card" transition:fade={{ duration: 200 }}>
    <div class="quick-tip-content">
      <p class="quick-tip-eyebrow">{$text('chat.quick_tips.eyebrow')}</p>
      <h3>{$text(activeTip.titleKey)}</h3>
      <p class="quick-tip-body">{$text(activeTip.bodyKey)}</p>
      {#if activeTip.ctaLabelKey && activeTip.ctaAction}
        <button class="quick-tip-cta" type="button" data-testid="quick-tip-cta" onclick={() => handleAction(activeTip)}>
          {$text(activeTip.ctaLabelKey)}
        </button>
      {/if}
    </div>
    <button
      class="quick-tip-dismiss"
      type="button"
      data-testid="quick-tip-dismiss"
      aria-label={$text('common.close')}
      onclick={() => dismiss(activeTip.slug)}
    >
      x
    </button>
  </section>
{/if}

<style>
  .quick-tip-card {
    position: relative;
    width: min(100%, 780px);
    align-self: flex-end;
    overflow: hidden;
    border-radius: var(--radius-6);
    padding: 1px;
    background: linear-gradient(135deg, var(--color-primary), var(--color-secondary));
    box-shadow: 0 0.75rem 2rem rgba(0, 0, 0, 0.16);
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
    border-radius: calc(var(--radius-6) - 1px);
    padding: 1rem 3rem 1rem 1rem;
    color: var(--color-grey-0);
  }

  .quick-tip-eyebrow {
    margin: 0 0 0.35rem;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    opacity: 0.82;
  }

  h3 {
    margin: 0;
    font-size: clamp(1rem, 0.96rem + 0.25vw, 1.15rem);
    line-height: 1.2;
    font-weight: 800;
  }

  .quick-tip-body {
    margin: 0.45rem 0 0;
    max-width: 44rem;
    font-size: 0.92rem;
    line-height: 1.45;
    opacity: 0.94;
  }

  .quick-tip-cta {
    all: unset;
    box-sizing: border-box;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    margin-top: 0.8rem;
    min-height: 2rem;
    padding: 0.35rem 0.75rem;
    border-radius: var(--radius-full);
    cursor: pointer;
    background: rgba(255, 255, 255, 0.92);
    color: var(--color-grey-100);
    font-size: 0.84rem;
    font-weight: 700;
    box-shadow: 0 0.25rem 0.8rem rgba(0, 0, 0, 0.16);
  }

  .quick-tip-cta:focus-visible,
  .quick-tip-dismiss:focus-visible {
    outline: 2px solid rgba(255, 255, 255, 0.9);
    outline-offset: 2px;
  }

  .quick-tip-dismiss {
    all: unset;
    position: absolute;
    top: 0.65rem;
    right: 0.65rem;
    z-index: 1;
    display: grid;
    place-items: center;
    width: 1.75rem;
    height: 1.75rem;
    border-radius: 999px;
    cursor: pointer;
    color: var(--color-grey-0);
    background: rgba(255, 255, 255, 0.16);
    font-size: 1.25rem;
    line-height: 1;
  }

  @media (max-width: 500px) {
    .quick-tip-card {
      width: 100%;
    }
  }
</style>
