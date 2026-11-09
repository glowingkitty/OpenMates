<!--
  frontend/packages/ui/src/components/embeds/code/SvgEmbedImage.svelte

  Visual rendering of an SVG code embed. The source is shown through an <img>
  with a data: URL, so scripts and external resources can never run or load.
  While streaming, partial source is repaired (progressiveSvg.ts) and
  re-rendered at most every ~200 ms; the last good frame stays visible when a
  partial cannot be rendered. Finished source is rendered unmodified.
-->

<script lang="ts">
  import { text } from '@repo/ui';
  import { buildProgressiveSvg, svgAspect, svgToDataUrl } from './progressiveSvg';
  import { createThrottle, PROGRESSIVE_RENDER_INTERVAL_MS } from './progressiveRender';

  interface Props {
    /** SVG source (possibly partial while streaming) */
    code: string;
    /** Accessible description of the image */
    title: string;
    /** True while the assistant is still producing the source */
    streaming: boolean;
  }

  let { code, title, streaming }: Props = $props();

  let src = $state<string | null>(null);
  let aspect = $state<{ width: number; height: number } | null>(null);
  const throttle = createThrottle(PROGRESSIVE_RENDER_INTERVAL_MS);

  $effect(() => {
    const source = code;
    if (!streaming) {
      throttle.cancel();
      src = source.trim() ? svgToDataUrl(source) : null;
      aspect = svgAspect(source) ?? aspect;
      return;
    }
    throttle.schedule(() => {
      const doc = buildProgressiveSvg(source);
      if (doc === null) return; // keep the last good frame
      src = svgToDataUrl(doc);
      aspect = svgAspect(doc) ?? aspect;
    });
  });

  $effect(() => () => throttle.cancel());
</script>

<div
  class="svg-embed-image"
  data-testid="svg-embed-visual"
  data-streaming={streaming ? 'true' : 'false'}
>
  {#if src}
    <img
      {src}
      alt={title}
      draggable="false"
      style:aspect-ratio={aspect ? `${aspect.width} / ${aspect.height}` : undefined}
      data-testid="svg-embed-image"
    />
  {:else if streaming}
    <div class="svg-embed-pending" data-testid="svg-embed-pending">
      <span class="svg-embed-dot"></span>
      <span>{$text('common.processing')}</span>
    </div>
  {/if}
</div>

<style>
  .svg-embed-image {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
    overflow: hidden;
    padding: var(--spacing-4);
    box-sizing: border-box;
    background-color: var(--color-grey-0);
  }

  img {
    display: block;
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
    user-select: none;
  }

  .svg-embed-pending {
    display: flex;
    align-items: center;
    gap: var(--spacing-3);
    color: var(--color-font-secondary);
  }

  .svg-embed-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background-color: var(--color-font-secondary);
    animation: svg-embed-pulse 1s infinite alternate;
  }

  @keyframes svg-embed-pulse {
    from { opacity: 0.3; }
    to { opacity: 1; }
  }
</style>
