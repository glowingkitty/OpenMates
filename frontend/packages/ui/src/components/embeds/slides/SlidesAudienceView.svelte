<!--
  frontend/packages/ui/src/components/embeds/slides/SlidesAudienceView.svelte

  The audience view of a presentation: only the current slide, scaled to the
  largest size that fits the window at the deck aspect ratio, on a black
  surround. Uses the Fullscreen API when available. Keyboard (arrows, space,
  PageUp/PageDown, Home/End, Esc) and click/tap drive the position through the
  callbacks; the position itself is owned by the parent. Speaker notes are never
  rendered here: this component only renders SlideCanvas, which has no notes.
-->
<script lang="ts">
  import SlideCanvas from './SlideCanvas.svelte';
  import { actionForKey, isTypingTarget, type PresentAction, type PresentPosition } from './slidesPresentation';
  import type { Deck } from './slidesMarkup';
  import { text } from '@repo/ui';

  interface Props {
    deck: Deck;
    position: PresentPosition;
    onAction: (action: Exclude<PresentAction, 'exit'>) => void;
    onExit: () => void;
    /** Ask for the Fullscreen API on mount (a presenting window should fill the screen). */
    fullscreen?: boolean;
    /** One-time message (e.g. popup blocked), shown briefly over the slide. */
    notice?: string;
  }

  let { deck, position, onAction, onExit, fullscreen = true, notice = '' }: Props = $props();

  const CHROME_VISIBLE_MS = 2500;
  const NOTICE_VISIBLE_MS = 6000;

  let root = $state<HTMLElement | null>(null);
  let areaWidth = $state(0);
  let areaHeight = $state(0);
  let chromeVisible = $state(false);
  let chromeTimer: ReturnType<typeof setTimeout> | undefined;
  let enteredFullscreen = false;
  let noticeVisible = $state(true);

  $effect(() => {
    if (!notice) return;
    noticeVisible = true;
    const timer = setTimeout(() => (noticeVisible = false), NOTICE_VISIBLE_MS);
    return () => clearTimeout(timer);
  });

  let slide = $derived(deck.slides[Math.min(position.index, deck.slides.length - 1)]);
  let ratio = $derived(deck.width / deck.height);
  /** Largest slide that fits the window at the deck aspect ratio. */
  let slideWidth = $derived(Math.floor(Math.min(areaWidth, areaHeight * ratio)));

  function requestFullscreen() {
    if (!root || document.fullscreenElement || !document.fullscreenEnabled) return;
    // Denied without a user gesture (e.g. a popup); the window still presents, just not full screen.
    root.requestFullscreen().then(() => (enteredFullscreen = true), () => {});
  }

  $effect(() => {
    if (!root || !fullscreen) return;
    requestFullscreen();
    const onChange = () => {
      if (enteredFullscreen && !document.fullscreenElement) {
        enteredFullscreen = false;
        onExit();
      }
    };
    document.addEventListener('fullscreenchange', onChange);
    return () => {
      document.removeEventListener('fullscreenchange', onChange);
      enteredFullscreen = false;
      if (document.fullscreenElement === root) void document.exitFullscreen();
    };
  });

  function onKeydown(event: KeyboardEvent) {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || isTypingTarget(event.target)) return;
    const action = actionForKey(event.key);
    if (!action) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (action === 'exit') onExit();
    else onAction(action);
  }

  $effect(() => {
    window.addEventListener('keydown', onKeydown, true);
    return () => window.removeEventListener('keydown', onKeydown, true);
  });

  function showChrome() {
    chromeVisible = true;
    clearTimeout(chromeTimer);
    chromeTimer = setTimeout(() => (chromeVisible = false), CHROME_VISIBLE_MS);
  }

  $effect(() => () => clearTimeout(chromeTimer));

  function onClick(event: MouseEvent) {
    if ((event.target as HTMLElement).closest('a, button')) return;
    requestFullscreen();
    onAction('next');
  }
</script>

<div
  class="audience"
  bind:this={root}
  bind:clientWidth={areaWidth}
  bind:clientHeight={areaHeight}
  role="presentation"
  data-testid="slides-audience"
  data-slide-index={position.index}
  data-step={position.step}
  onclick={onClick}
  onpointermove={showChrome}
  onpointerdown={showChrome}
>
  {#if slide && slideWidth > 0}
    <div class="audience-slide" style:width="{slideWidth}px" data-testid="slides-audience-slide">
      {#key slide.id}
        <SlideCanvas
          {slide}
          width={deck.width}
          height={deck.height}
          template={deck.template}
          step={position.step}
          interactive={true}
          animated={true}
        />
      {/key}
    </div>
  {/if}
  {#if notice && noticeVisible}
    <p class="notice" role="status" data-testid="slides-audience-notice">{notice}</p>
  {/if}
  <button
    type="button"
    class="exit"
    class:visible={chromeVisible}
    data-testid="slides-audience-exit"
    aria-label={$text('embeds.slides_exit_presentation')}
    onclick={onExit}
  >✕</button>
</div>

<style>
  .audience {
    position: fixed;
    inset: 0;
    z-index: 10000;
    display: flex;
    align-items: center;
    justify-content: center;
    /* The surround is black on every theme: it is projected onto a screen. */
    background: black;
    cursor: pointer;
    overflow: hidden;
  }

  /* Not ".slide": a global rule with that name pins the element to the top left. */
  .audience-slide {
    flex: none;
  }

  .notice {
    position: absolute;
    bottom: var(--spacing-8);
    left: 50%;
    transform: translateX(-50%);
    max-width: 90%;
    margin: 0;
    padding: var(--spacing-4) var(--spacing-8);
    border-radius: var(--radius-5);
    background: color-mix(in srgb, black 70%, transparent);
    color: white;
    font-size: var(--font-size-small);
    text-align: center;
  }

  .exit {
    position: absolute;
    top: var(--spacing-6);
    right: var(--spacing-6);
    display: grid;
    place-items: center;
    width: 44px;
    height: 44px;
    min-width: 0;
    min-height: 0;
    margin: 0;
    padding: 0;
    border: 0;
    border-radius: 50%;
    background: color-mix(in srgb, white 18%, transparent);
    color: white;
    font-size: var(--font-size-p);
    cursor: pointer;
    opacity: 0;
    transition: opacity 0.2s ease;
  }

  .exit.visible,
  .exit:focus-visible {
    opacity: 1;
  }
</style>
