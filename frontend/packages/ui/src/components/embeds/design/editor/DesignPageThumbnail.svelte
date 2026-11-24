<!-- figma-visual-proof: not-required. Original OpenMates preview with browser proof. -->
<script lang="ts">
  import type { DesignPage } from './designDocument';
  import { decodeImages, drawDesignPage } from './designRenderer';

  let { page }: { page: DesignPage } = $props();
  let canvas: HTMLCanvasElement;
  const scale = $derived(Math.min(112 / page.width, 112 / page.height));
  $effect(() => {
    const designPage = page;
    const zoom = scale;
    let current = true;
    void decodeImages(designPage.layers).then((images) => {
      if (!current) return;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      ctx.setTransform(zoom, 0, 0, zoom, 0, 0);
      drawDesignPage(ctx, designPage, images);
    });
    return () => { current = false; };
  });
</script>

<canvas bind:this={canvas} width={Math.ceil(page.width * scale)} height={Math.ceil(page.height * scale)} aria-hidden="true"></canvas>

<style>
  canvas { height: 64px; max-width: 72px; object-fit: contain; }
</style>
