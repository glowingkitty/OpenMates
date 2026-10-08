<script lang="ts">
  import type { NewsroomMediaSource } from "./types";

  interface Props {
    label: string;
    shape?: "landscape" | "portrait";
    showPlay?: boolean;
    compact?: boolean;
    source?: NewsroomMediaSource;
    controls?: boolean;
  }

  let {
    label,
    shape = "landscape",
    showPlay = true,
    compact = false,
    source,
    controls = false,
  }: Props = $props();
</script>

<div
  class:portrait={shape === "portrait"}
  class:compact
  class="newsroom-media"
  role={source ? undefined : "img"}
  aria-label={source ? undefined : label}
>
  {#if source?.type === "image"}
    <img src={source.posterUrl ?? source.url} alt={source.alt || label} loading="lazy" decoding="async" />
  {:else if source?.type === "video"}
    <video
      src={source.url}
      poster={source.posterUrl}
      aria-label={source.alt || label}
      {controls}
      muted={!controls}
      playsinline
      preload="metadata"
    ></video>
  {/if}
  {#if showPlay && source?.type === "video"}
    <span class="play-button" aria-hidden="true">
      <span></span>
    </span>
  {/if}
</div>

<style>
  .newsroom-media {
    position: relative;
    width: 100%;
    aspect-ratio: var(--publication-landscape-ratio, 16 / 9);
    overflow: hidden;
    border-radius: var(--radius-4);
    background-color: #f8f8f8;
    background-image:
      linear-gradient(45deg, #ececec 25%, transparent 25%),
      linear-gradient(-45deg, #ececec 25%, transparent 25%),
      linear-gradient(45deg, transparent 75%, #ececec 75%),
      linear-gradient(-45deg, transparent 75%, #ececec 75%);
    background-position:
      0 0,
      0 0.75rem,
      0.75rem -0.75rem,
      -0.75rem 0;
    background-size: 1.5rem 1.5rem;
  }

  .newsroom-media.portrait {
    aspect-ratio: var(--publication-social-media-ratio, 5 / 8);
  }

  img,
  video {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .play-button {
    position: absolute;
    inset: 50% auto auto 50%;
    display: grid;
    width: clamp(3rem, 6vw, 4.5rem);
    aspect-ratio: 1;
    place-items: center;
    border-radius: 50%;
    background: color-mix(in srgb, var(--color-grey-0) 92%, transparent);
    box-shadow: var(--shadow-md);
    transform: translate(-50%, -50%);
  }

  .compact .play-button {
    width: 3rem;
  }

  .play-button span {
    width: 0;
    height: 0;
    margin-inline-start: 0.25rem;
    border-block: 0.7rem solid transparent;
    border-inline-start: 1.05rem solid var(--color-primary-start);
  }
</style>
