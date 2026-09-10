<!--
  Shared responsive chat and fullscreen-embed action layout.
  Measures its own available width, including side-by-side panes.
  Existing action snippets retain their permissions, handlers and identifiers.
  Secondary actions appear as individually labeled pills beneath More.
  Header overlap colors remain owned by headerOverlayControls and icons.css.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import { tooltip } from '../actions/tooltip';
  import type { Snippet } from 'svelte';
  import { tick, onMount } from 'svelte';
  import { fly } from 'svelte/transition';

  let {
    report,
    share,
    actions,
    restoreChat,
    close,
    resetKey,
  }: {
    report: Snippet;
    share: Snippet;
    actions: Snippet;
    restoreChat?: Snippet;
    close: Snippet;
    resetKey?: string;
  } = $props();
  const SHARE_MIN_WIDTH = 460;
  const REPORT_LABEL_MIN_WIDTH = 640;
  const MENU_GAP = 12;
  const MENU_DURATION = 180;
  const MENU_HOVER_SCALE = 1.08;
  const MENU_SHADOW_CLEARANCE = 8;
  let width = $state(0);
  let containerWidth = $state(0);
  let open = $state(false);
  let root: HTMLDivElement;
  let trigger: HTMLButtonElement;
  let anchor: HTMLDivElement;
  let menuWidth = $state(240);
  const menuId = $props.id();

  onMount(() => {
    const container = root.closest<HTMLElement>('.chat-side, .fullscreen-container') ?? root;
    const updateWidth = () => { containerWidth = container.clientWidth; };
    const observer = new ResizeObserver(updateWidth);
    observer.observe(container);
    updateWidth();
    return () => observer.disconnect();
  });

  $effect(() => {
    void resetKey;
    open = false;
  });
  $effect(() => {
    void width;
    if (open && root && anchor) {
      menuWidth = Math.max(
        0,
        (root.getBoundingClientRect().right -
          anchor.getBoundingClientRect().left -
          MENU_SHADOW_CLEARANCE) /
          MENU_HOVER_SCALE,
      );
    }
  });

  function outside(event: PointerEvent) {
    if (open && event.target instanceof Node && !root.contains(event.target))
      open = false;
  }
  function actionClicked(event: MouseEvent) {
    const action =
      event.target instanceof Element
        ? event.target.closest('button, a')
        : null;
    if (action && action !== trigger && !action.matches(':disabled')) {
      open = false;
    }
  }

  async function keydown(event: KeyboardEvent) {
    if (event.key === 'Escape' && open) {
      event.preventDefault();
      event.stopPropagation();
      open = false;
      trigger.focus();
    } else if (event.key === 'ArrowDown' && event.target === trigger) {
      event.preventDefault();
      open = true;
      await tick();
      root
        .querySelector<HTMLElement>('.more-actions button, .more-actions a')
        ?.focus();
    }
  }
</script>

<svelte:window onpointerdown={outside} />
<div
  class="header-action-menu"
  bind:this={root}
  bind:clientWidth={width}
  onkeydown={keydown}
  onclick={actionClicked}
  role="toolbar"
  tabindex="-1"
  aria-label={$text('common.more_actions')}
>
  <div class="primary-actions">
    <div
      class="report-action"
      class:show-label={containerWidth >= REPORT_LABEL_MIN_WIDTH}
    >
      {@render report()}
    </div>
    {#if containerWidth >= SHARE_MIN_WIDTH}<div class="share-action">
        {@render share()}
      </div>{/if}
    {@render restoreChat?.()}
    <div class="more-anchor" bind:this={anchor}>
      <div class="button-wrapper more-wrapper" class:is-open={open}>
        <button
          bind:this={trigger}
          use:tooltip
          class="header-action more-trigger"
          aria-label={$text('common.more_actions')}
          aria-expanded={open}
          aria-controls={menuId}
          onclick={() => (open = !open)}
        >
          <span class="clickable-icon icon_more top-button" aria-hidden="true"
          ></span>
        </button>
      </div>
      {#if open}
        <div
          id={menuId}
          class="more-actions"
          data-header-overlay-disabled
          data-tooltip-disabled
          style:max-width={`${menuWidth}px`}
          style:--menu-hover-scale={MENU_HOVER_SCALE}
          style:top={`calc(100% + ${MENU_GAP}px)`}
          transition:fly={{
            y: -8,
            duration: window.matchMedia('(prefers-reduced-motion: reduce)')
              .matches
              ? 0
              : MENU_DURATION,
          }}
        >
          {#if containerWidth < SHARE_MIN_WIDTH}{@render share()}{/if}
          {@render actions()}
        </div>
      {/if}
    </div>
  </div>
  <div class="close-action">{@render close()}</div>
</div>

<style>
  .header-action-menu {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    width: 100%;
    min-width: 0;
    gap: var(--spacing-4);
    pointer-events: none;
  }
  .primary-actions {
    display: flex;
    align-items: center;
    gap: var(--spacing-4);
    min-width: 0;
  }
  .more-anchor {
    position: relative;
  }
  .more-wrapper {
    border-radius: 40px;
    padding: var(--spacing-4);
    background-color: var(--color-grey-10);
    box-shadow: var(--shadow-md);
    pointer-events: auto;
    transition:
      opacity var(--duration-normal),
      background-color var(--duration-normal);
  }
  .more-wrapper.is-open {
    opacity: 0.5;
  }
  .more-actions {
    position: absolute;
    left: 0;
    width: max-content;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--spacing-4);
    z-index: 2;
    /* Allow pill hover transforms and shadows to extend beyond the menu bounds. */
    overflow: visible;
    pointer-events: auto;
  }
  .header-action-menu :global(.header-action) {
    all: unset;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-4);
    box-sizing: border-box;
    cursor: pointer;
    pointer-events: auto;
    color: var(--color-font-primary);
    font-weight: 600;
    min-width: 25px;
    min-height: 25px;
  }
  .header-action-menu :global(.header-action:focus-visible) {
    outline: 2px solid var(--color-primary);
    outline-offset: 4px;
    border-radius: 24px;
  }
  .header-action-menu :global(.header-action:disabled) {
    opacity: 0.5;
    cursor: default;
  }
  .header-action-menu :global(.clickable-icon) {
    flex-shrink: 0;
    display: block;
    width: 25px;
    height: 25px;
    margin: 0;
  }
  .header-action-menu :global(.action-label) {
    display: none;
    transition: color var(--duration-normal);
  }
  .report-action.show-label :global(.action-label),
  .more-actions :global(.action-label) {
    display: block;
    padding-inline-end: var(--spacing-4);
  }
  .more-actions :global(.action-label) {
    overflow-wrap: anywhere;
  }
  .more-actions :global(.button-wrapper),
  .more-actions :global(.new-chat-button-wrapper) {
    max-width: 100%;
    box-sizing: border-box;
    transform-origin: left center;
  }
  .more-actions :global(.button-wrapper:hover),
  .more-actions :global(.new-chat-button-wrapper:hover) {
    transform: scale(var(--menu-hover-scale));
  }
  .header-action-menu :global([data-header-overlay] .action-label) {
    color: #fff;
  }
  .header-action-menu :global(.icon_more) {
    mask-image: url('@openmates/ui/static/icons/more.svg');
    -webkit-mask-image: url('@openmates/ui/static/icons/more.svg');
  }
  @media (prefers-reduced-motion: reduce) {
    .more-wrapper,
    .header-action-menu :global(.action-label) {
      transition: none;
    }
  }
</style>
