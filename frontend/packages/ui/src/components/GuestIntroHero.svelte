<!--
  GuestIntroHero.svelte — logged-out OpenMates intro media hero.

  Renders the same intro video assets used by the for-everyone intro chat, but
  as a focused welcome-screen hero above the guest interest selector. Kept
  separate from ActiveChat.svelte so guest marketing media does not add more
  branching to the core chat shell.
-->
<script lang="ts">
  import { tick } from 'svelte';
  import { text } from '@repo/ui';
  import { locale } from 'svelte-i18n';
  import { getVideoForLocale } from '../demo_chats/data/videos';
  import { proxyImage, MAX_WIDTH_VIDEO_FULLSCREEN } from '../utils/imageProxy';

  let isPlayingFullVideo = $state(false);
  let videoEl = $state<HTMLVideoElement | null>(null);

  let introVideo = $derived(getVideoForLocale('intro', $locale ?? 'en'));
  let posterUrl = $derived(
    introVideo?.teaser_webp_url ?? proxyImage(introVideo?.thumbnail_url, MAX_WIDTH_VIDEO_FULLSCREEN),
  );

  async function playFullIntro() {
    if (!introVideo?.mp4_url) return;
    isPlayingFullVideo = true;
    await tick();
    try {
      await videoEl?.play();
    } catch (error) {
      // Native controls remain visible if autoplay with sound is blocked.
      console.debug('[GuestIntroHero] Full intro video autoplay was blocked', error);
    }
  }
</script>

<section class="guest-intro-hero" data-testid="guest-intro-hero" aria-label={$text('demo_chats.for_everyone.title')}>
  <div class="guest-intro-orbs" aria-hidden="true">
    <div class="guest-intro-orb guest-intro-orb-1"></div>
    <div class="guest-intro-orb guest-intro-orb-2"></div>
    <div class="guest-intro-orb guest-intro-orb-3"></div>
  </div>

  <div class="guest-intro-copy" data-testid="guest-intro-copy">
    <span>{$text('demo_chats.for_everyone.teaser_line1')}</span>
    <span>{$text('demo_chats.for_everyone.teaser_line2')}</span>
    <span>{$text('demo_chats.for_everyone.teaser_line3')}</span>
  </div>

  {#if introVideo}
    <button
      type="button"
      class="guest-intro-video-shell"
      data-testid="guest-intro-video-shell"
      aria-label={$text('daily_inspiration.watch_video')}
      onclick={playFullIntro}
    >
      {#if isPlayingFullVideo}
        <video
          bind:this={videoEl}
          class="guest-intro-video"
          data-testid="guest-intro-video"
          src={introVideo.mp4_url}
          controls
          playsinline
          preload="auto"
        >
          <track kind="captions" />
        </video>
      {:else if introVideo.teaser_url || introVideo.teaser_mp4_url}
        <video
          class="guest-intro-video"
          data-testid="guest-intro-video"
          poster={posterUrl}
          autoplay
          muted
          loop
          playsinline
          preload="metadata"
        >
          {#if introVideo.teaser_url}
            <source src={introVideo.teaser_url} type="video/webm" />
          {/if}
          {#if introVideo.teaser_mp4_url}
            <source src={introVideo.teaser_mp4_url} type="video/mp4" />
          {/if}
        </video>
      {:else}
        <img
          class="guest-intro-video"
          data-testid="guest-intro-video"
          src={posterUrl}
          alt=""
          loading="eager"
          decoding="async"
        />
      {/if}

      {#if !isPlayingFullVideo}
        <span class="guest-intro-play" aria-hidden="true">
          <span></span>
        </span>
      {/if}
    </button>
  {/if}
</section>

<style>
  .guest-intro-hero {
    position: relative;
    z-index: var(--z-index-raised);
    display: flex;
    align-items: center;
    justify-content: center;
    gap: clamp(18px, 4vw, 42px);
    width: 100%;
    min-height: clamp(235px, 34vh, 390px);
    padding: clamp(18px, 3.6vh, 36px) clamp(18px, 5vw, 68px);
    box-sizing: border-box;
    overflow: hidden;
    background: var(--color-primary);
  }

  .guest-intro-orbs {
    position: absolute;
    inset: 0;
    overflow: hidden;
    pointer-events: none;
  }

  .guest-intro-orb {
    position: absolute;
    border-radius: 999px;
    filter: blur(32px);
    opacity: 0.54;
    background: radial-gradient(circle, rgba(160, 190, 255, 0.95), transparent 70%);
  }

  .guest-intro-orb-1 {
    width: 420px;
    height: 330px;
    left: -110px;
    top: -120px;
  }

  .guest-intro-orb-2 {
    width: 440px;
    height: 360px;
    right: -120px;
    bottom: -150px;
    background: radial-gradient(circle, rgba(255, 193, 116, 0.72), transparent 72%);
  }

  .guest-intro-orb-3 {
    width: 360px;
    height: 290px;
    left: 42%;
    top: -80px;
    opacity: 0.36;
  }

  .guest-intro-copy {
    position: relative;
    z-index: var(--z-index-raised);
    display: flex;
    flex-direction: column;
    flex: 1 1 360px;
    max-width: 520px;
    min-width: 260px;
    color: white;
    font-size: clamp(1.8rem, 3.4vw, 3.9rem);
    font-weight: 700;
    line-height: 0.98;
    letter-spacing: -0.04em;
    text-align: left;
    text-shadow: 0 2px 18px rgba(0, 0, 0, 0.2);
  }

  .guest-intro-video-shell {
    position: relative;
    z-index: var(--z-index-raised);
    display: block;
    flex: 1 1 430px;
    width: min(46vw, 620px);
    min-width: 320px;
    aspect-ratio: 16 / 9;
    padding: 0;
    border: 1px solid rgba(255, 255, 255, 0.22);
    border-radius: clamp(18px, 2vw, 28px);
    overflow: hidden;
    background: rgba(0, 0, 0, 0.22);
    box-shadow: 0 22px 54px rgba(0, 0, 0, 0.32), 0 6px 16px rgba(0, 0, 0, 0.18);
    cursor: pointer;
  }

  .guest-intro-video {
    display: block;
    width: 100%;
    height: 100%;
    object-fit: cover;
    background: rgba(0, 0, 0, 0.2);
  }

  .guest-intro-play {
    position: absolute;
    inset: auto 18px 18px auto;
    display: grid;
    place-items: center;
    width: 52px;
    height: 52px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.92);
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.28);
  }

  .guest-intro-play span {
    display: block;
    width: 0;
    height: 0;
    margin-left: 4px;
    border-top: 11px solid transparent;
    border-bottom: 11px solid transparent;
    border-left: 17px solid var(--color-button-primary, #4867cd);
  }

  @media (max-width: 730px) {
    .guest-intro-hero {
      flex-direction: column;
      align-items: stretch;
      min-height: 330px;
      padding: 18px 16px 20px;
      gap: 16px;
    }

    .guest-intro-copy {
      flex: 0 0 auto;
      min-width: 0;
      max-width: none;
      font-size: clamp(1.75rem, 9vw, 2.6rem);
      text-align: left;
    }

    .guest-intro-video-shell {
      flex: 0 0 auto;
      width: 100%;
      min-width: 0;
      border-radius: 20px;
    }
  }
</style>
