<script lang="ts">
  type Props = {
    kind: 'phone' | 'laptop';
    src: string;
    alt: string;
    loading?: 'eager' | 'lazy';
  };

  let { kind, src, alt, loading = 'lazy' }: Props = $props();
</script>

<div class:phone={kind === 'phone'} class:laptop={kind === 'laptop'} class="device-frame">
  <img class="device-screen" {src} {alt} {loading} fetchpriority={loading === 'eager' ? 'high' : 'auto'} decoding="async" />
  <img class="device-shell" src={kind === 'phone' ? '/landing/devices/iphone-17-pro-overlay.svg' : '/landing/devices/macbook-pro-14-overlay.svg'} alt="" aria-hidden="true" loading="lazy" decoding="async" />
</div>

<style>
  .device-frame { position: relative; isolation: isolate; width: 100%; filter: drop-shadow(0 22px 22px rgba(18, 21, 38, .16)); }
  .device-frame.phone { aspect-ratio: 1280 / 2642; }
  .device-frame.laptop { aspect-ratio: 1216 / 735; }
  .device-shell { position: absolute; inset: 0; width: 100%; height: 100%; display: block; z-index: 1; pointer-events: none; }
  .device-screen { position: absolute; display: block; object-fit: cover; object-position: center top; z-index: 0; }
  .phone .device-screen { left: 4.318%; top: 2.093%; width: 91.364%; height: 96.256%; border-radius: 5.7% / 2.7%; }
  .laptop .device-screen { left: 9.061%; top: .269%; width: 82.04%; height: 88.151%; border-radius: .7% .7% 0 0; }
  .phone::after { content: ''; position: absolute; z-index: 2; left: 35.5%; top: 3.6%; width: 29%; height: 4.1%; border-radius: 999px; background: #050506; }
  .laptop::after { content: ''; position: absolute; z-index: 2; top: .25%; left: 45.1%; width: 9.8%; height: 4.9%; border-radius: 0 0 8px 8px; background: #050506; }
</style>
