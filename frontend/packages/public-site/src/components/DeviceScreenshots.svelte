<script lang="ts">
  import DeviceFrame from './DeviceFrame.svelte';

  interface Props {
    baseKey: string;
    href?: string;
    linkLabel?: string;
    desktopAlt: string;
    mobileAlt: string;
    desktopSrc?: string;
    mobileSrc?: string;
    watchSrc?: string;
    watchAlt?: string;
    eager?: boolean;
    hero?: boolean;
  }

  let { baseKey, href, linkLabel, desktopAlt, mobileAlt, desktopSrc, mobileSrc, watchSrc, watchAlt = 'OpenMates on Apple Watch', eager = false, hero = false }: Props = $props();
</script>

<svelte:element this={href ? 'a' : 'div'} class="device-screenshots" class:hero class:with-watch={Boolean(watchSrc)} {href} target={href ? '_blank' : undefined} rel={href ? 'noopener noreferrer' : undefined} aria-label={href ? linkLabel : undefined} data-testid="device-screenshots">
  <div class="laptop-wrap">
    <DeviceFrame kind="laptop" src={desktopSrc ?? `/landing/screenshots/${baseKey}-desktop.webp`} alt={desktopAlt} loading={eager ? 'eager' : 'lazy'} />
  </div>
  <div class="phone-wrap">
    <DeviceFrame kind="phone" src={mobileSrc ?? `/landing/screenshots/${baseKey}-mobile.webp`} alt={mobileAlt} loading={eager ? 'eager' : 'lazy'} />
  </div>
  {#if watchSrc}
    <div class="watch-wrap">
      <DeviceFrame kind="watch" src={watchSrc} alt={watchAlt} loading={eager ? 'eager' : 'lazy'} />
    </div>
  {/if}
</svelte:element>

<style>
  .device-screenshots { display: block; color: inherit; text-decoration: none; position: relative; width: 100%; margin-inline: auto; padding: 1.5% 0 3.5% 12%; box-sizing: border-box; }
  .device-screenshots:focus-visible { outline: 3px solid var(--color-primary-start); outline-offset: 8px; border-radius: 12px; }
  .watch-wrap { position: absolute; z-index: 2; width: 16%; left: -5%; bottom: -1%; }
  .laptop-wrap { width: 100%; }
  .phone-wrap { position: absolute; z-index: 1; width: 26%; left: 0; bottom: 0; }
  @media (max-width: 760px) {
    .device-screenshots { width: min(66vw, 300px); max-width: 100%; padding: 0; }
    .device-screenshots.hero { width: 100%; }
    .laptop-wrap { display: none; }
    .with-watch { padding-left: 12%; }
    .watch-wrap { width: 43%; left: 0; bottom: -2%; }
    .phone-wrap { position: relative; width: 100%; left: auto; bottom: auto; }
  }
</style>
