<script lang="ts">
  import NewsroomMedia from "./NewsroomMedia.svelte";
  import type { NewsroomItem } from "./types";

  interface Props {
    item: NewsroomItem;
    variant?: "featured" | "standard" | "compact";
    onOpen: (item: NewsroomItem) => void;
  }

  let { item, variant = "standard", onOpen }: Props = $props();
</script>

<button
  type="button"
  class="publication-card {variant}"
  data-testid={`newsroom-card-${item.id}`}
  onclick={() => onOpen(item)}
>
  {#if item.mediaShape !== "none"}
    <span class="card-media">
      <NewsroomMedia
        label={`${item.title} media preview`}
        showPlay={item.kind !== "blog"}
        compact={variant !== "featured"}
      />
      {#if item.language}<span class="language-pill">{item.language}</span>{/if}
    </span>
  {/if}
  <span class="card-copy">
    <span class="eyebrow">{item.eyebrow}</span>
    <strong>{item.title}</strong>
    <span class="meta"
      ><span>{item.publishedLabel}</span>{#if item.readTime}<span
          >{item.readTime}</span
        >{/if}</span
    >
  </span>
</button>

<style>
  .publication-card {
    all: unset;
    box-sizing: border-box;
    display: grid;
    min-width: 0;
    overflow: hidden;
    border: 1px solid var(--color-grey-25);
    border-radius: var(--radius-8);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    box-shadow: var(--shadow-md);
    cursor: pointer;
    transition:
      transform var(--duration-fast) var(--easing-default),
      box-shadow var(--duration-fast) var(--easing-default);
  }

  .publication-card:hover {
    box-shadow: var(--shadow-lg);
    transform: translateY(-0.125rem);
  }

  .publication-card:focus-visible {
    outline: 0.125rem solid var(--color-primary-start);
    outline-offset: 0.1875rem;
  }

  .publication-card.featured {
    grid-column: 1 / -1;
    grid-template-columns: minmax(0, 1.15fr) minmax(16rem, 0.85fr);
    min-height: var(--publication-featured-card-min-height, 14rem);
  }

  .publication-card.standard,
  .publication-card.compact {
    grid-template-rows: auto minmax(
        var(--publication-card-body-min-height, 10rem),
        auto
      );
  }

  .card-media {
    position: relative;
    display: block;
    min-width: 0;
  }

  .featured .card-media :global(.newsroom-media) {
    height: 100%;
    min-height: var(--publication-featured-card-min-height, 14rem);
    aspect-ratio: auto;
    border-radius: 0;
  }

  .standard .card-media :global(.newsroom-media),
  .compact .card-media :global(.newsroom-media) {
    border-radius: 0;
  }

  .card-copy {
    display: grid;
    box-sizing: border-box;
    min-width: 0;
    grid-template-rows: auto 1fr auto;
    gap: var(--spacing-5);
    padding: var(--spacing-8);
  }

  .featured .card-copy {
    grid-template-rows: auto 1fr auto;
    padding: var(--spacing-10);
  }

  .eyebrow {
    color: var(--color-font-secondary);
    font-size: var(--font-size-tiny);
    font-weight: 700;
  }

  strong {
    align-self: center;
    font-size: var(--font-size-h3-mobile);
    line-height: 1.24;
  }

  .featured strong {
    font-size: var(--font-size-h2-mobile);
  }

  .meta {
    display: flex;
    align-self: end;
    justify-content: space-between;
    gap: var(--spacing-5);
    margin-top: auto;
    color: var(--color-font-secondary);
    font-size: var(--font-size-tiny);
    font-weight: 650;
  }

  .language-pill {
    position: absolute;
    top: var(--spacing-4);
    left: var(--spacing-4);
    padding: var(--spacing-2) var(--spacing-4);
    border-radius: var(--radius-full);
    background: color-mix(in srgb, var(--color-grey-0) 88%, transparent);
    color: var(--color-font-secondary);
    font-size: var(--font-size-tiny);
    font-weight: 700;
  }

  @media (max-width: 730px) {
    .publication-card.featured {
      grid-template-columns: 1fr;
      grid-template-rows: auto minmax(
          var(--publication-card-body-min-height, 10rem),
          auto
        );
      min-height: 0;
    }

    .featured .card-media :global(.newsroom-media) {
      height: auto;
      min-height: 0;
      aspect-ratio: var(--publication-landscape-ratio, 16 / 9);
    }

    .featured .card-copy {
      align-content: start;
      padding: var(--spacing-8);
    }
  }
</style>
