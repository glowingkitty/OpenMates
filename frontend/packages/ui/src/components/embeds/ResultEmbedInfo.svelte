<script lang="ts">
  import { onMount, tick, type Snippet } from "svelte";
  import { getLucideIcon } from "../../utils/categoryUtils";

  interface Props {
    icon: string;
    label: string;
    value?: string;
    caption?: string;
    state?: "yes" | "no" | "unknown";
    testId?: string;
    children?: Snippet;
  }
  let {
    icon,
    label,
    value,
    caption,
    state: infoState,
    testId,
    children,
  }: Props = $props();
  const uid = $props.id();
  const Symbol = $derived(getLucideIcon(icon));
  let trigger = $state<HTMLButtonElement>();
  let panel = $state<HTMLDivElement>();
  let shown = $state(false);
  let pinned = $state(false);
  let left = $state(0);
  let top = $state(0);

  async function reveal() {
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const width = Math.min(320, window.innerWidth - 24);
    left = Math.max(
      12,
      Math.min(
        rect.left + rect.width / 2 - width / 2,
        window.innerWidth - width - 12,
      ),
    );
    top = rect.bottom + 8;
    shown = true;
    await tick();
    if (panel && top + panel.offsetHeight > window.innerHeight - 12)
      top = Math.max(12, rect.top - panel.offsetHeight - 8);
  }
  function dismiss() {
    shown = false;
    pinned = false;
  }
  // Fullscreen transforms establish a containing block; the panel must escape
  // it so viewport coordinates and clipping remain correct in side-by-side mode.
  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => node.remove() };
  }
  onMount(() => {
    const reposition = () => { if (shown) void reveal(); };
    window.addEventListener("scroll", reposition, true);
    // Preview cards stop bubbling pointer events; outside dismissal must run first.
    window.addEventListener("pointerdown", outside, true);
    return () => {
      window.removeEventListener("scroll", reposition, true);
      window.removeEventListener("pointerdown", outside, true);
    };
  });
  function outside(event: PointerEvent) {
    if (
      !trigger?.contains(event.target as Node) &&
      !panel?.contains(event.target as Node)
    )
      dismiss();
  }
</script>

<svelte:window onresize={dismiss} />

<div class="result-info">
  <button
    bind:this={trigger}
    type="button"
    class="info-trigger"
    class:circle={value === undefined}
    data-testid={testId}
    data-state={infoState}
    data-pinned={pinned}
    aria-label={label}
    aria-describedby={shown ? uid : undefined}
    aria-expanded={shown}
    onmouseenter={reveal}
    onmouseleave={() => {
      if (!pinned) shown = false;
    }}
    onfocus={reveal}
    onblur={() => {
      if (!pinned) shown = false;
    }}
    onkeydown={(event) => {
      if (event.key === "Escape" && shown) {
        event.preventDefault();
        event.stopPropagation();
        dismiss();
      }
    }}
    onclick={(event) => {
      event.stopPropagation();
      if (pinned) dismiss();
      else {
        pinned = true;
        void reveal();
      }
    }}
  >
    <Symbol
      size={value === undefined ? 23 : 18}
      strokeWidth={2}
      aria-hidden="true"
    />
    {#if value !== undefined}<span class="fact-text"
        ><strong>{value}</strong>{#if caption}<small>{caption}</small
          >{/if}</span
      >{/if}
    {#if infoState}<span
        class="state"
        class:yes={infoState === "yes"}
        class:no={infoState === "no"}
        aria-hidden="true"
        >{infoState === "yes" ? "✓" : infoState === "no" ? "×" : "?"}</span
      >{/if}
  </button>
  {#if shown}
    <div
      bind:this={panel}
      use:portal
      id={uid}
      role="tooltip"
      class="info-panel"
      style:left={`${left}px`}
      style:top={`${top}px`}
    >
      <strong>{label}</strong>
      {#if children}<div class="info-body">{@render children()}</div>{/if}
    </div>
  {/if}
</div>

<style>
  .result-info {
    display: inline-flex;
    min-width: 0;
    max-width: 100%;
  }
  .info-trigger {
    all: unset;
    box-sizing: border-box;
    max-width: 100%;
    overflow-wrap: anywhere;
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-3);
    border: 0;
    background: transparent;
    color: var(--color-font-secondary);
    font: inherit;
    cursor: pointer;
    padding: var(--spacing-3);
    border-radius: var(--radius-4);
    min-height: 44px;
    min-width: 44px;
  }
  .info-trigger:hover,
  .info-trigger[aria-expanded="true"] {
    background: var(--color-grey-25);
    color: var(--color-font-primary);
  }
  .info-trigger:focus-visible {
    outline: 2px solid var(--color-button-primary);
    outline-offset: 3px;
  }
  .info-trigger.circle {
    width: 44px;
    height: 44px;
    border-radius: 50%;
    background: var(--color-grey-25);
  }
  .fact-text {
    min-width: 0;
    overflow-wrap: anywhere;
    display: flex;
    flex-direction: column;
    text-align: left;
    line-height: 1.15;
  }
  strong {
    font-size: 0.875rem;
    font-weight: 650;
  }
  small {
    font-size: 0.625rem;
    margin-top: var(--spacing-1);
  }
  .state {
    position: absolute;
    right: -2px;
    bottom: -2px;
    width: 18px;
    height: 18px;
    display: grid;
    place-items: center;
    border-radius: 50%;
    border: 2px solid var(--color-grey-20);
    background: var(--color-grey-60);
    color: var(--color-font-button);
    font-size: 0.75rem;
    font-weight: 700;
  }
  .state.yes {
    background: var(--color-semantic-success);
  }
  .state.no {
    background: var(--color-semantic-error);
  }
  .info-panel {
    position: fixed;
    z-index: var(--z-index-tooltip);
    width: min(320px, calc(100vw - 24px));
    max-height: min(60vh, 32rem);
    overflow: auto;
    box-sizing: border-box;
    border-radius: var(--radius-5);
    padding: var(--spacing-8);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    box-shadow: var(--shadow-lg);
    font-size: 0.8125rem;
    line-height: 1.5;
    text-align: left;
  }
  .info-body {
    margin-top: var(--spacing-4);
  }
  .info-body :global(p),
  .info-body :global(h4),
  .info-body :global(h5) {
    margin: 0 0 var(--spacing-3);
    font-size: inherit;
  }
  .info-body :global(dl) {
    display: grid;
    gap: var(--spacing-3);
    margin: 0;
  }
  .info-body :global(dl > div) {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1.3fr);
    gap: var(--spacing-4);
  }
  .info-body :global(dd) {
    margin: 0;
    overflow-wrap: anywhere;
  }
  .info-body :global(dt) {
    color: var(--color-font-tertiary);
  }
</style>
