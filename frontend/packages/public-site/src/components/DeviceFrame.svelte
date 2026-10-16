<script lang="ts">
  interface Props {
    kind: 'phone' | 'laptop' | 'watch';
    src: string;
    alt: string;
    loading?: 'eager' | 'lazy';
  }

  let { kind, src, alt, loading = 'lazy' }: Props = $props();
</script>

<div class:phone={kind === 'phone'} class:laptop={kind === 'laptop'} class:watch={kind === 'watch'} class="device-frame">
  <div class="screen-aperture">
    <img class="device-screen" {src} {alt} {loading} fetchpriority={loading === 'eager' ? 'high' : 'auto'} decoding="async" />
  </div>
  {#if kind !== 'watch'}
    <img class="device-shell" src={kind === 'phone' ? '/landing/devices/iphone-17-pro-overlay.svg' : '/landing/devices/macbook-pro-14-overlay.svg'} alt="" aria-hidden="true" loading="lazy" decoding="async" />
  {/if}
</div>

<style>
  /* Hardware colors stay fixed to match the supplied device shells in every theme. */
  .device-frame { position: relative; isolation: isolate; width: 100%; filter: drop-shadow(0 22px 22px rgba(18, 21, 38, .16)); }
  .device-frame.phone { aspect-ratio: 1280 / 2642; }
  .device-frame.laptop { aspect-ratio: 1216 / 735; }
  .device-shell { position: absolute; inset: 0; width: 100%; height: 100%; display: block; z-index: 1; pointer-events: none; }
  .screen-aperture { position: absolute; overflow: hidden; z-index: 0; background: #050506; }
  .device-screen { display: block; width: 100%; height: 100%; object-fit: cover; object-position: center top; }
  /* Match each SVG screen-cutout rect, including its elliptical CSS radius. */
  .phone .screen-aperture { left: calc(100% * 55 / 1280); top: calc(100% * 55 / 2642); width: calc(100% * 1170 / 1280); height: calc(100% * 2532 / 2642); border-radius: calc(100% * 165 / 1170) / calc(100% * 165 / 2532); }
  .laptop .screen-aperture { left: calc(100% * 110 / 1216); top: calc(100% * 2 / 735); width: calc(100% * 998 / 1216); height: calc(100% * 648 / 735); border-radius: calc(100% * 26 / 998) / calc(100% * 26 / 648); }
  .phone::after { content: ''; position: absolute; z-index: 2; left: 35.5%; top: 3.6%; width: 29%; height: 4.1%; border-radius: 999px; background: #050506; }
  .laptop::after { content: ''; position: absolute; z-index: 2; top: .25%; left: 45.1%; width: 9.8%; height: 4.9%; border-radius: 0 0 8px 8px; background: #050506; }
  /* A simple decorative case surrounds genuine Watch captures supplied by the caller. */
  .device-frame.watch { aspect-ratio: 208 / 248; border-radius: 27% / 23%; background: #28292b; box-shadow: inset 0 0 0 2px #77797c, inset 0 0 0 5px #151618; }
  .watch .screen-aperture { inset: 5%; border-radius: 24% / 20%; }
  .watch::after { content: ''; position: absolute; z-index: -1; width: 5%; height: 15%; right: -3%; top: 25%; border-radius: 35%; background: #67696c; }
</style>
