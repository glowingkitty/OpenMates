<!--
  frontend/packages/ui/src/components/embeds/shared/EmbedIconButton.svelte

  One round icon action of an embed fullscreen, for controls that live inside the
  content (editors, strips, popovers) rather than in EmbedTopBar. Same design as
  the top bar's pill wrapper + circular icon (EmbedTopBar / HeaderActionMenu):
  grey-10 circle, 8px padding around a 25px gradient icon mask, shadow, hover
  scale 1.08, press scale 0.95, and the shared `tooltip` action that shows the
  aria-label on hover and focus. The button itself is the circle, so the whole
  visible area is clickable and it never picks up the global buttons.css sizing.

  Icons are names of `static/icons/*.svg` (the generated `--icon-url-*` custom
  properties). `content` replaces the icon for glyph or swatch buttons.
-->
<script lang="ts">
  import type { Snippet } from 'svelte';
  import { tooltip } from '../../../actions/tooltip';

  interface Props {
    /** Accessible name and tooltip text (translated). */
    label: string;
    /** Icon file name in static/icons without `.svg`; omit when `content` is given. */
    icon?: string;
    /** Mirror the icon horizontally (redo from undo, right from left). */
    flip?: boolean;
    testId?: string;
    disabled?: boolean;
    /** Toggle state (aria-pressed); a pressed button is filled with the primary colour. */
    pressed?: boolean;
    /** Disclosure state (aria-expanded) of a button that opens a popover or panel. */
    expanded?: boolean;
    /** Id of the popover or panel this button controls. */
    controls?: string;
    /** The one prominent action of a surface (filled primary, white icon). */
    primary?: boolean;
    /** Small dot on the button, e.g. "this slide has notes". */
    badge?: boolean;
    badgeTestId?: string;
    /** Custom inner content instead of the icon (glyph, colour swatch). */
    content?: Snippet;
    onclick: (event: MouseEvent) => void;
    element?: HTMLButtonElement | null;
  }

  let {
    label,
    icon,
    flip = false,
    testId,
    disabled = false,
    pressed,
    expanded,
    controls,
    primary = false,
    badge = false,
    badgeTestId,
    content,
    onclick,
    element = $bindable(null)
  }: Props = $props();
</script>

<button
  bind:this={element}
  type="button"
  class="embed-icon-button"
  class:pressed={pressed === true}
  class:primary
  use:tooltip
  aria-label={label}
  aria-pressed={pressed}
  aria-expanded={expanded}
  aria-controls={controls}
  data-testid={testId}
  {disabled}
  {onclick}
>
  {#if content}
    {@render content()}
  {:else if icon}
    <span
      class="clickable-icon top-button embed-icon-button-icon"
      class:flip
      style:--embed-icon-url="var(--icon-url-{icon})"
      aria-hidden="true"
    ></span>
  {/if}
  {#if badge}<span class="embed-icon-button-badge" data-testid={badgeTestId} aria-hidden="true"></span>{/if}
</button>

<style>
  /* EmbedTopBar .button-wrapper + HeaderActionMenu .header-action, as one element. */
  .embed-icon-button {
    all: unset;
    position: relative;
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    justify-content: center;
    box-sizing: border-box;
    width: calc(25px + 2 * var(--spacing-4));
    height: calc(25px + 2 * var(--spacing-4));
    padding: var(--spacing-4);
    border-radius: 40px;
    background-color: var(--color-grey-10);
    box-shadow: var(--shadow-md);
    color: var(--color-font-primary);
    font-weight: 600;
    cursor: pointer;
    transition:
      background-color var(--duration-normal),
      transform var(--duration-normal),
      box-shadow var(--duration-normal),
      opacity var(--duration-normal);
    -webkit-tap-highlight-color: transparent;
  }

  .embed-icon-button:hover:not(:disabled) {
    transform: scale(1.08);
    box-shadow: var(--shadow-lg);
  }

  .embed-icon-button:active:not(:disabled) {
    transform: scale(0.95);
    box-shadow: var(--shadow-xs);
  }

  .embed-icon-button:focus-visible {
    outline: 2px solid var(--color-primary-start);
    outline-offset: 4px;
  }

  .embed-icon-button:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .embed-icon-button-icon {
    flex-shrink: 0;
    display: block;
    width: 25px;
    height: 25px;
    margin: 0;
    -webkit-mask-image: var(--embed-icon-url);
    mask-image: var(--embed-icon-url);
  }

  .embed-icon-button:disabled .embed-icon-button-icon {
    cursor: default;
  }

  .embed-icon-button-icon.flip {
    transform: scaleX(-1);
  }

  /* Pressed toggle / primary action: filled primary circle with a white icon (EmbedTopBar edit-active). */
  .embed-icon-button.pressed,
  .embed-icon-button.primary {
    background-color: var(--color-primary-start);
    color: var(--color-font-button);
  }

  .embed-icon-button.pressed .embed-icon-button-icon,
  .embed-icon-button.primary .embed-icon-button-icon {
    background: var(--color-font-button);
  }

  .embed-icon-button-badge {
    position: absolute;
    top: 3px;
    right: 3px;
    width: 10px;
    height: 10px;
    border-radius: var(--radius-full);
    background: var(--color-button-primary);
    box-shadow: 0 0 0 2px var(--color-grey-10);
  }

  @media (prefers-reduced-motion: reduce) {
    .embed-icon-button {
      transition: none;
    }
  }
</style>
