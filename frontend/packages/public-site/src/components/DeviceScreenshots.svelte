<script lang="ts">
  import DeviceFrame from './DeviceFrame.svelte';

  type Props = {
    baseKey: string;
    desktopAlt: string;
    mobileAlt: string;
    desktopSrc?: string;
    mobileSrc?: string;
    eager?: boolean;
  };

  let { baseKey, desktopAlt, mobileAlt, desktopSrc, mobileSrc, eager = false }: Props = $props();
</script>

<div class="device-screenshots" data-testid="device-screenshots">
  <div class="laptop-wrap">
    <DeviceFrame kind="laptop" src={desktopSrc ?? `/landing/screenshots/${baseKey}-desktop.webp`} alt={desktopAlt} loading={eager ? 'eager' : 'lazy'} />
  </div>
  <div class="phone-wrap">
    <DeviceFrame kind="phone" src={mobileSrc ?? `/landing/screenshots/${baseKey}-mobile.webp`} alt={mobileAlt} loading={eager ? 'eager' : 'lazy'} />
  </div>
</div>

<style>
  .device-screenshots { position: relative; width: min(100%, 1030px); margin-inline: auto; padding: 1.5% 0 3.5% 12%; box-sizing: border-box; }
  .laptop-wrap { width: 100%; }
  .phone-wrap { position: absolute; z-index: 1; width: 23%; left: 1%; bottom: 0; }
  @media (max-width: 680px) {
    .device-screenshots { width: 100%; padding: 2% 0 5% 13%; }
    .phone-wrap { width: 31%; left: 0; }
  }
</style>
