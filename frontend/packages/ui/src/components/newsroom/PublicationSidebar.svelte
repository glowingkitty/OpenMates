<script lang="ts">
  import { tick } from "svelte";
  import type { NewsroomItem } from "./types";

  interface Props {
    label: string;
    latestLabel: string;
    items: NewsroomItem[];
    onOpen: (item: NewsroomItem) => void;
    onClose: () => void;
  }

  let { label, latestLabel, items, onOpen, onClose }: Props = $props();
  let searchOpen = $state(false);
  let searchTerm = $state("");
  let searchInput = $state<HTMLInputElement>();
  const filteredItems = $derived.by(() => {
    const query = searchTerm.trim().toLocaleLowerCase();
    if (!query) return items;
    return items.filter((item) =>
      `${item.title} ${item.excerpt} ${item.eyebrow}`
        .toLocaleLowerCase()
        .includes(query),
    );
  });

  async function toggleSearch() {
    searchOpen = !searchOpen;
    if (!searchOpen) {
      searchTerm = "";
      return;
    }
    await tick();
    searchInput?.focus();
  }
</script>

<aside class="publication-sidebar" aria-label={`${label} archive`}>
  <header>
    <button
      type="button"
      class="sidebar-search"
      aria-label={`Search ${label}`}
      data-testid="sidebar-search"
      aria-expanded={searchOpen}
      onclick={toggleSearch}
    >
      <span class={`clickable-icon icon_${searchOpen ? "close" : "search"}`} aria-hidden="true"></span>
    </button>
    <button
      type="button"
      class="sidebar-close"
      aria-label={`Close ${label} navigation`}
      onclick={onClose}
    >
      <span class="clickable-icon icon_close" aria-hidden="true"></span>
    </button>
  </header>

  <div class="sidebar-title">
    <strong>{label}</strong><span>{latestLabel}</span>
  </div>
  {#if searchOpen}
    <input
      class="sidebar-search-input"
      data-testid="sidebar-search-input"
      type="search"
      placeholder={`Search ${label}`}
      aria-label={`Search ${label}`}
      bind:this={searchInput}
      bind:value={searchTerm}
    />
  {/if}
  <nav>
    <span class="date-label">Today</span>
    {#each filteredItems.slice(0, 3) as item, index (item.id)}
      <button
        class:active={index === 0}
        type="button"
        onclick={() => onOpen(item)}
      >
        <span class="item-icon" aria-hidden="true"
          >{item.kind === "blog"
            ? "✎"
            : item.kind === "release"
              ? "↗"
              : "•"}</span
        >
        <span class="item-copy"
          ><strong>{item.title}</strong><small>{item.publishedLabel}</small
          ></span
        >
      </button>
    {/each}
    <span class="date-label">Earlier</span>
    {#each filteredItems.slice(3) as item (item.id)}
      <button type="button" onclick={() => onOpen(item)}>
        <span class="item-icon" aria-hidden="true"
          >{item.kind === "blog"
            ? "✎"
            : item.kind === "release"
              ? "↗"
              : "•"}</span
        >
        <span class="item-copy"
          ><strong>{item.title}</strong><small>{item.publishedLabel}</small
          ></span
        >
      </button>
    {/each}
  </nav>
</aside>

<style>
  .publication-sidebar {
    display: flex;
    box-sizing: border-box;
    width: 100%;
    height: 100%;
    flex-direction: column;
    overflow: hidden;
    background: var(--color-grey-20);
    box-shadow: inset -0.375rem 0 0.75rem -0.25rem rgba(0, 0, 0, 0.18);
  }

  header {
    display: flex;
    min-height: 4.5rem;
    align-items: center;
    justify-content: space-between;
    padding: 0 var(--spacing-10);
  }

  header button {
    all: unset;
    display: grid;
    width: 2.75rem;
    aspect-ratio: 1;
    place-items: center;
    cursor: pointer;
  }

  header :global(.clickable-icon) {
    width: 1.65rem;
    height: 1.65rem;
    background-color: var(--color-primary-start);
  }

  .sidebar-title {
    display: grid;
    gap: var(--spacing-2);
    padding: var(--spacing-8) var(--spacing-10) var(--spacing-6);
  }

  .sidebar-title strong {
    font-size: var(--font-size-h3);
  }
  .sidebar-title span {
    color: var(--color-font-secondary);
    font-size: var(--font-size-tiny);
  }

  .sidebar-search-input {
    box-sizing: border-box;
    width: calc(100% - 2 * var(--spacing-10));
    min-height: 2.5rem;
    margin: 0 var(--spacing-10) var(--spacing-4);
    padding: 0 var(--spacing-5);
    border: 1px solid var(--color-grey-30);
    border-radius: var(--radius-full);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    font: inherit;
  }

  .sidebar-search-input:focus-visible {
    outline: 0.125rem solid var(--color-primary-start);
    outline-offset: 0.125rem;
  }

  nav {
    display: grid;
    min-height: 0;
    overflow-y: auto;
    padding: 0 var(--spacing-5) var(--spacing-10);
  }

  .date-label {
    padding: var(--spacing-8) var(--spacing-5) var(--spacing-3);
    color: var(--color-font-secondary);
    font-size: var(--font-size-tiny);
    font-weight: 700;
  }

  nav button {
    all: unset;
    display: grid;
    grid-template-columns: 2rem minmax(0, 1fr);
    align-items: start;
    gap: var(--spacing-4);
    padding: var(--spacing-5);
    border-radius: var(--radius-4);
    cursor: pointer;
  }

  nav button:hover,
  nav button.active {
    background: var(--color-grey-25);
  }

  .item-icon {
    display: grid;
    width: 1.75rem;
    aspect-ratio: 1;
    place-items: center;
    border-radius: 50%;
    background: var(--color-primary);
    color: #fff;
    font-weight: 800;
  }

  .item-copy {
    display: grid;
    min-width: 0;
    gap: var(--spacing-2);
  }

  .item-copy strong {
    display: -webkit-box;
    overflow: hidden;
    font-size: var(--font-size-small);
    line-height: 1.25;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
  }

  .item-copy small {
    color: var(--color-font-secondary);
    font-size: var(--font-size-tiny);
  }

</style>
