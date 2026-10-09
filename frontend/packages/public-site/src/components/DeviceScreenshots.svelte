<script lang="ts">
  import DeviceFrame from './DeviceFrame.svelte';

  type Props = {
    baseKey: string;
    desktopAlt: string;
    mobileAlt: string;
    desktopSrc?: string;
    mobileSrc?: string;
    eager?: boolean;
    hero?: boolean;
  };

  let { baseKey, desktopAlt, mobileAlt, desktopSrc, mobileSrc, eager = false, hero = false }: Props = $props();
</script>

<div class="device-screenshots" class:hero data-testid="device-screenshots">
  <div class="laptop-wrap">
    <DeviceFrame kind="laptop" src={desktopSrc ?? `/landing/screenshots/${baseKey}-desktop.webp`} alt={desktopAlt} loading={eager ? 'eager' : 'lazy'} />
  </div>
  <div class="phone-wrap">
    <DeviceFrame kind="phone" src={mobileSrc ?? `/landing/screenshots/${baseKey}-mobile.webp`} alt={mobileAlt} loading={eager ? 'eager' : 'lazy'} />
  </div>
</div>

<style>
  .device-screenshots { position: relative; width: 100%; margin-inline: auto; padding: 1.5% 0 3.5% 12%; box-sizing: border-box; }
  .laptop-wrap { width: 100%; }
  .phone-wrap { position: absolute; z-index: 1; width: 26%; left: 0; bottom: 0; }
  @media (max-width: 760px) {
    .device-screenshots { width: min(66vw, 300px); max-width: 100%; padding: 0; }
    .device-screenshots.hero { width: 100%; }
    .laptop-wrap { display: none; }
    .phone-wrap { position: relative; width: 100%; left: auto; bottom: auto; }
  }
</style>
