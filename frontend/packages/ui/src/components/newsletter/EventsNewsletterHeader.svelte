<!--
  frontend/packages/ui/src/components/newsletter/EventsNewsletterHeader.svelte

  Localized visual source for the OpenMates Events newsletter header image.
  scripts/generate_events_newsletter_header_assets.mjs renders this component in
  a temporary Vite page and exports PNGs for email clients that need image-only
  hero artwork. Keep text copy here so localized exports stay reproducible.
-->

<script lang="ts">
  type HeaderLanguage = 'en' | 'de';
  type HeaderVariant = 'desktop' | 'mobile';

  interface HeaderCopy {
    eyebrow: string;
    title: string;
    ariaLabel: string;
  }

  const copy: Record<HeaderLanguage, HeaderCopy> = {
    en: {
      eyebrow: 'Newsletter',
      title: 'Join our new\nOpenMates events!',
      ariaLabel: 'OpenMates Events newsletter header',
    },
    de: {
      eyebrow: 'Newsletter',
      title: 'Sei bei unseren neuen\nOpenMates Events dabei!',
      ariaLabel: 'OpenMates Events Newsletter Header',
    },
  };

  let { language = 'en', variant = 'desktop' }: { language?: HeaderLanguage | string; variant?: HeaderVariant | string } = $props();

  let normalizedLanguage = $derived(language === 'de' ? 'de' : 'en');
  let normalizedVariant = $derived(variant === 'mobile' ? 'mobile' : 'desktop');
  let labels = $derived(copy[normalizedLanguage]);
</script>

<section class="events-newsletter-header" class:mobile={normalizedVariant === 'mobile'} aria-label={labels.ariaLabel} data-testid="events-newsletter-header">
  <div class="eyebrow-row">
    <div class="app-icon" aria-hidden="true">
      <img src="/favicon.svg" alt="" />
    </div>
    <div class="eyebrow">{labels.eyebrow}</div>
  </div>

  <h1>{labels.title}</h1>

  <span class="event-mask decorative decorative-left" aria-hidden="true"></span>
  <span class="event-mask decorative decorative-right" aria-hidden="true"></span>
</section>

<style>
  .events-newsletter-header {
    position: relative;
    width: 1155px;
    height: 322px;
    overflow: hidden;
    border-radius: calc(var(--radius-6, 0.875rem) + var(--radius-1, 0.25rem) / 2);
    background: linear-gradient(135deg, #a20000 9.04%, #e61b3e 90.06%);
    color: var(--color-grey-0, #ffffff);
    font-family: 'Lexend Deca Variable', 'Lexend Deca', Arial, Helvetica, sans-serif;
  }

  .events-newsletter-header.mobile {
    width: 780px;
    height: 258px;
  }

  .eyebrow-row {
    position: absolute;
    top: 25px;
    left: 250px;
    display: flex;
    align-items: center;
    gap: 14px;
  }

  .app-icon {
    width: 38px;
    height: 38px;
  }

  .app-icon img {
    display: block;
    width: 38px;
    height: 38px;
    border-radius: var(--radius-3, 0.5rem);
  }

  .event-mask {
    display: block;
    background: linear-gradient(135deg, #a20000 9.04%, #e61b3e 90.06%);
    mask: url('/icons/event.svg') center / contain no-repeat;
    -webkit-mask: url('/icons/event.svg') center / contain no-repeat;
  }

  .eyebrow {
    color: color-mix(in srgb, var(--color-grey-0, #ffffff) 62%, transparent);
    font-size: var(--font-size-h3, 1.25rem);
    font-weight: 800;
    line-height: 1.25;
  }

  h1 {
    position: absolute;
    top: 136px;
    left: 250px;
    width: 650px;
    margin: 0;
    color: var(--color-grey-0, #ffffff);
    font-size: calc(var(--font-size-h1, 3.75rem) * 2 / 3);
    font-weight: 800;
    line-height: 1.25;
    white-space: pre-line;
  }

  .decorative {
    position: absolute;
    width: 73px;
    height: 73px;
    background: rgba(255, 255, 255, 0.5);
  }

  .decorative-left {
    top: 222px;
    left: 113px;
    transform: rotate(-13deg);
  }

  .decorative-right {
    top: 217px;
    right: 60px;
    width: 82px;
    height: 82px;
    transform: rotate(13deg);
  }

  .mobile .eyebrow-row {
    top: 24px;
    left: 167px;
  }

  .mobile h1 {
    top: 94px;
    left: 167px;
    width: 485px;
    font-size: calc(var(--font-size-h1, 3.75rem) * 2 / 3);
  }

  .mobile .decorative-left {
    top: 165px;
    left: 70px;
  }

  .mobile .decorative-right {
    top: 160px;
    right: 58px;
  }
</style>
