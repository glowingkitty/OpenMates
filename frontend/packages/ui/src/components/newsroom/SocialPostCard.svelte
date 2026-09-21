<script lang="ts">
  import NewsroomMedia from "./NewsroomMedia.svelte";
  import type { NewsroomItem } from "./types";

  interface Props {
    item: NewsroomItem;
    onOpen: (item: NewsroomItem) => void;
  }

  let { item, onOpen }: Props = $props();
</script>

<button
  type="button"
  class="social-card"
  data-testid={`newsroom-card-${item.id}`}
  onclick={() => onOpen(item)}
>
  <NewsroomMedia
    label={`${item.title} social media preview`}
    source={item.media}
    shape="portrait"
    showPlay={false}
  />
  <span class="social-overlay">
    <span class="author-row"
      ><span class="avatar" aria-hidden="true">OM</span><strong
        >{item.author ?? item.eyebrow}</strong
      ></span
    >
    <span class="post-title">{item.title}</span>
    <span class="post-date">{item.publishedLabel}</span>
  </span>
</button>

<style>
  .social-card {
    all: unset;
    position: relative;
    box-sizing: border-box;
    display: block;
    flex: 0 0 var(--publication-social-card-width, 15rem);
    width: var(--publication-social-card-width, 15rem);
    aspect-ratio: var(--publication-social-card-ratio, 3 / 4.7);
    overflow: hidden;
    border: 1px solid var(--color-grey-25);
    border-radius: var(--radius-8);
    background: var(--color-grey-0);
    box-shadow: var(--shadow-md);
    cursor: pointer;
    scroll-snap-align: start;
  }

  .social-card :global(.newsroom-media) {
    position: absolute;
    inset: 0;
    height: 100%;
    aspect-ratio: auto;
    border-radius: 0;
  }

  .social-card:focus-visible {
    outline: 0.125rem solid var(--color-primary-start);
    outline-offset: 0.1875rem;
  }

  .social-overlay {
    position: absolute;
    inset: auto 0 0;
    display: grid;
    gap: var(--spacing-4);
    padding: var(--spacing-8);
    background: linear-gradient(
      to top,
      color-mix(in srgb, var(--color-grey-0) 96%, transparent) 25%,
      color-mix(in srgb, var(--color-grey-0) 84%, transparent) 70%,
      transparent
    );
    color: var(--color-font-primary);
    text-align: left;
  }

  .author-row {
    display: flex;
    align-items: center;
    gap: var(--spacing-4);
    font-size: var(--font-size-small);
  }

  .avatar {
    display: grid;
    width: 2.25rem;
    aspect-ratio: 1;
    place-items: center;
    border-radius: 50%;
    background: var(--color-primary);
    color: #fff;
    font-size: 0.65rem;
    font-weight: 800;
  }

  .post-title {
    display: -webkit-box;
    overflow: hidden;
    font-size: var(--font-size-small);
    font-weight: 700;
    line-height: 1.3;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 3;
  }

  .post-date {
    color: var(--color-font-secondary);
    font-size: var(--font-size-tiny);
    font-weight: 650;
  }
</style>
