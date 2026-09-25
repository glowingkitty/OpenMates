<script lang="ts">
  import { tooltip } from '../actions/tooltip';

  export type IconTabItem = {
    id: string;
    label: string;
    iconClass: 'chat-icon' | 'project-icon' | 'plan-icon' | 'task-icon' | 'workflow-icon';
    testId?: string;
    href?: string;
    disabled?: boolean;
    controls?: string;
  };

  let {
    items,
    activeId,
    ariaLabel,
    testId = undefined,
    mode = 'tabs',
    onChange = undefined,
    onIntent = undefined,
    onNavigate = undefined,
  }: {
    items: IconTabItem[];
    activeId: string;
    ariaLabel: string;
    testId?: string;
    mode?: 'navigation' | 'tabs';
    onChange?: (id: string) => void;
    onIntent?: (item: IconTabItem, index: number) => void;
    onNavigate?: (event: MouseEvent, item: IconTabItem) => void;
  } = $props();

  let hoveredIndex = $state<number | null>(null);
  const activeIndex = $derived(Math.max(0, items.findIndex((item) => item.id === activeId)));

  function beginIntent(item: IconTabItem, index: number): void {
    hoveredIndex = item.id === activeId ? null : index;
    onIntent?.(item, index);
  }

  function endIntent(): void {
    hoveredIndex = null;
  }
</script>

<div
  class="icon-tab-bar"
  role={mode === 'tabs' ? 'tablist' : undefined}
  aria-label={ariaLabel}
  data-testid={testId}
  style={`--active-index:${activeIndex};--hover-index:${hoveredIndex ?? activeIndex};`}
>
  <div class="icon-tab-hover-pill" class:visible={hoveredIndex !== null} aria-hidden="true"></div>
  <div class="icon-tab-active-pill" data-testid={testId ? `${testId}-pill` : undefined} aria-hidden="true"></div>
  {#each items as item, index (item.id)}
    {#if mode === 'navigation' && item.href && !item.disabled}
      <a
        href={item.href}
        class="icon-tab"
        class:active={item.id === activeId}
        data-testid={item.testId}
        aria-label={item.label}
        aria-current={item.id === activeId ? 'page' : undefined}
        onclick={(event) => onNavigate?.(event, item)}
        onmouseenter={() => beginIntent(item, index)}
        onmouseleave={endIntent}
        onfocus={() => beginIntent(item, index)}
        onblur={endIntent}
        use:tooltip
      ><span class={`icon-tab-icon ${item.iconClass}`} aria-hidden="true"></span></a>
    {:else}
      <button
        type="button"
        class="icon-tab"
        class:active={item.id === activeId}
        data-testid={item.testId}
        role={mode === 'tabs' ? 'tab' : undefined}
        aria-selected={mode === 'tabs' ? item.id === activeId : undefined}
        aria-current={mode === 'navigation' && item.id === activeId ? 'page' : undefined}
        aria-controls={mode === 'tabs' ? item.controls : undefined}
        aria-label={item.label}
        aria-disabled={item.disabled ? 'true' : undefined}
        disabled={item.disabled}
        onclick={() => !item.disabled && onChange?.(item.id)}
        onmouseenter={() => beginIntent(item, index)}
        onmouseleave={endIntent}
        onfocus={() => beginIntent(item, index)}
        onblur={endIntent}
        use:tooltip
      ><span class={`icon-tab-icon ${item.iconClass}`} aria-hidden="true"></span></button>
    {/if}
  {/each}
</div>

<style>
  .icon-tab-bar {
    --icon-tab-width: 4.5rem;
    --icon-tab-height: 2.8rem;
    --icon-tab-radius: 3.25rem;
    display: flex;
    align-items: center;
    width: max-content;
    height: var(--icon-tab-height);
    background: var(--color-grey-10);
    border-radius: var(--icon-tab-radius);
    filter: drop-shadow(0 0.25rem 0.25rem rgba(0, 0, 0, 0.14));
    overflow: hidden;
    position: relative;
  }

  .icon-tab-active-pill,
  .icon-tab-hover-pill {
    position: absolute;
    inset-block: 0;
    inset-inline-start: calc(var(--icon-tab-width) * var(--active-index, 0));
    width: var(--icon-tab-width);
    border-radius: var(--icon-tab-radius);
    background: linear-gradient(135deg, var(--color-primary-start), var(--color-primary-end));
    transition: inset-inline-start 0.3s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.25s ease;
    z-index: var(--z-index-base);
  }

  .icon-tab-hover-pill {
    inset-inline-start: calc(var(--icon-tab-width) * var(--hover-index, 0));
    opacity: 0;
    background: linear-gradient(
      135deg,
      color-mix(in srgb, var(--color-primary-start) 50%, transparent),
      color-mix(in srgb, var(--color-primary-end) 50%, transparent)
    );
  }

  .icon-tab-hover-pill.visible { opacity: 1; }

  .icon-tab {
    all: unset;
    box-sizing: border-box;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: var(--icon-tab-width);
    height: var(--icon-tab-height);
    min-width: var(--icon-tab-width);
    min-height: var(--icon-tab-height);
    flex: 0 0 var(--icon-tab-width);
    padding: 0;
    background: transparent;
    cursor: pointer;
    font: inherit;
    margin: 0;
    position: relative;
    z-index: var(--z-index-raised);
  }

  .icon-tab[aria-disabled='true'] { cursor: default; opacity: 0.7; }
  .icon-tab:focus-visible { outline: 0.125rem solid var(--color-primary-start); outline-offset: 0.125rem; }

  .icon-tab-icon {
    width: 20px;
    height: 20px;
    background: var(--color-grey-70);
    -webkit-mask-size: contain;
    mask-size: contain;
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    transition: background-color 0.25s ease;
  }

  .icon-tab:hover .icon-tab-icon,
  .icon-tab:focus-visible .icon-tab-icon,
  .icon-tab.active .icon-tab-icon { background: #fff; }

  .chat-icon { -webkit-mask-image: url('@openmates/ui/static/icons/chat.svg'); mask-image: url('@openmates/ui/static/icons/chat.svg'); }
  .project-icon { -webkit-mask-image: url('@openmates/ui/static/icons/project.svg'); mask-image: url('@openmates/ui/static/icons/project.svg'); }
  .plan-icon { -webkit-mask-image: var(--icon-url-planning); mask-image: var(--icon-url-planning); }
  .workflow-icon { -webkit-mask-image: url('@openmates/ui/static/icons/workflow.svg'); mask-image: url('@openmates/ui/static/icons/workflow.svg'); }
  .task-icon { -webkit-mask-image: url('@openmates/ui/static/icons/projectmanagement.svg'); mask-image: url('@openmates/ui/static/icons/projectmanagement.svg'); }

  @media (prefers-reduced-motion: reduce) {
    .icon-tab-active-pill,
    .icon-tab-hover-pill,
    .icon-tab-icon { transition: none; }
  }
</style>
