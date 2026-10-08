<script lang="ts">
  import NewsroomMedia from "./NewsroomMedia.svelte";
  import type { NewsroomHero } from "./types";

  interface Props {
    hero: NewsroomHero;
    detail?: boolean;
    showNavigation?: boolean;
    onOpen: () => void;
    onClose?: () => void;
  }

  let { hero, detail = false, showNavigation = false, onOpen, onClose }: Props = $props();
</script>

<section
  class:detail
  class="publication-hero"
  aria-labelledby="newsroom-hero-title"
>
  {#if !detail}
    <button
      type="button"
      class="hero-link"
      aria-label={hero.actionLabel}
      onclick={onOpen}
    ></button>
  {/if}
  {#if showNavigation}
    <button
      type="button"
      class="hero-arrow previous"
      aria-label="Previous featured publication">‹</button
    >
  {/if}
  <div class="hero-content">
    <div class="hero-copy">
      {#if hero.kicker}<span class="kicker">{hero.kicker}</span>{/if}
      <span class="eyebrow">{hero.eyebrow}</span>
      <h1 id="newsroom-hero-title">{hero.title}</h1>
      <time>{hero.meta}</time>
      {#if !detail}
        <span class="hero-action">{hero.actionLabel}</span>
      {/if}
    </div>
    <div class="hero-media">
      <NewsroomMedia
        label={`${hero.title} featured media`}
        source={hero.media}
        showPlay={hero.media?.type === "video"}
      />
    </div>
  </div>
  {#if showNavigation}
    <button
      type="button"
      class="hero-arrow next"
      aria-label="Next featured publication">›</button
    >
  {/if}
  {#if detail && onClose}
    <button
      type="button"
      class="hero-close"
      aria-label="Close article"
      onclick={onClose}
    >
      <span class="clickable-icon icon_close" aria-hidden="true"></span>
    </button>
  {/if}
</section>

<style>
  .publication-hero {
    position: relative;
    box-sizing: border-box;
    display: grid;
    min-height: var(--publication-hero-block-size, 21rem);
    align-items: center;
    overflow: hidden;
    padding: var(--spacing-16) var(--spacing-20);
    border-radius: var(--radius-8);
    background: var(--gradient-primary);
    color: #fff;
    box-shadow: var(--shadow-xl);
    isolation: isolate;
  }

  .hero-content {
    position: relative;
    z-index: 1;
    display: grid;
    grid-template-columns: minmax(0, 14rem) minmax(0, 1fr);
    align-items: center;
    gap: var(--spacing-16);
    width: min(100%, var(--publication-content-max-width, 44.5rem));
    margin: 0 auto;
  }

  .hero-copy {
    display: grid;
    min-width: 0;
    gap: var(--spacing-5);
    justify-items: start;
  }

  .kicker,
  .eyebrow {
    font-size: var(--font-size-small);
    font-weight: 750;
    opacity: 0.72;
  }

  .kicker {
    padding: var(--spacing-2) var(--spacing-5);
    border: 1px solid rgba(255, 255, 255, 0.3);
    border-radius: var(--radius-full);
  }

  h1 {
    max-width: 15ch;
    margin: 0;
    color: inherit;
    font-size: var(--font-size-h2-mobile);
    line-height: 1.1;
    text-wrap: balance;
  }

  time {
    font-size: var(--font-size-small);
    font-weight: 650;
    opacity: 0.68;
  }

  .hero-action {
    display: inline-flex;
    align-items: center;
    margin-top: var(--spacing-5);
    font-size: var(--font-size-small);
    font-weight: 750;
  }

  .hero-link {
    all: unset;
    position: absolute;
    z-index: 2;
    inset: 0;
    cursor: pointer;
  }

  .hero-link:focus-visible {
    border-radius: inherit;
    outline: 0.1875rem solid rgba(255, 255, 255, 0.9);
    outline-offset: -0.375rem;
  }

  .hero-media {
    min-width: 0;
    width: 100%;
    justify-self: end;
  }

  .hero-media :global(.newsroom-media) {
    border: 1px solid rgba(255, 255, 255, 0.28);
    border-radius: var(--radius-8);
    box-shadow: var(--shadow-lg);
  }

  .hero-arrow,
  .hero-close {
    all: unset;
    position: absolute;
    display: grid;
    place-items: center;
    cursor: pointer;
    z-index: 3;
  }

  .hero-arrow {
    top: 50%;
    width: 2.5rem;
    aspect-ratio: 1;
    color: rgba(255, 255, 255, 0.55);
    font-size: 2.5rem;
    transform: translateY(-50%);
  }

  .hero-arrow.previous {
    left: var(--spacing-3);
  }
  .hero-arrow.next {
    right: var(--spacing-3);
  }

  .hero-close {
    top: var(--spacing-5);
    right: var(--spacing-5);
    width: 2.75rem;
    aspect-ratio: 1;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.9);
    box-shadow: var(--shadow-md);
  }

  .hero-close :global(.clickable-icon) {
    width: 1.5rem;
    height: 1.5rem;
    background-color: var(--color-primary-start);
  }

  @media (max-width: 730px) {
    .publication-hero {
      min-height: 0;
      padding: var(--spacing-12);
    }

    .hero-content {
      grid-template-columns: 1fr;
      gap: var(--spacing-12);
    }

    .hero-copy {
      order: 2;
    }

    .hero-media {
      order: 1;
    }

    h1 {
      font-size: var(--font-size-h2);
    }

    .hero-arrow {
      display: none;
    }
  }
</style>
