<!-- frontend/packages/ui/src/components/settings/SearchSortBar.svelte
     
     Shared search-and-sort bar used across settings list views.
     
     Provides:
     - A search text input with a search icon
     - A sort dropdown with configurable options
     
     Usage:
       <SearchSortBar
           bind:searchQuery
           bind:sortBy
           searchPlaceholder="Search apps..."
           sortOptions={[
               { value: 'name_asc', label: 'Name (A–Z)' },
               { value: 'newest', label: 'Newest' },
           ]}
       />
     
     The parent component owns the filter/sort logic — this component only manages
     the input values and emits changes via bind:. All sort options are passed in
     as an array so the component is decoupled from any specific domain.
-->

<script lang="ts">
    import { text } from '@repo/ui';

    // --- Props ---
    interface SortOption {
        value: string;
        label: string;
    }

    interface Props {
        /** Current search query — use bind:searchQuery in parent */
        searchQuery?: string;
        /** Currently selected sort value — use bind:sortBy in parent */
        sortBy?: string;
        /** Placeholder text for the search input */
        searchPlaceholder?: string;
        /** Available sort options rendered in the dropdown */
        sortOptions?: SortOption[];
    }

    let {
        searchQuery = $bindable(''),
        sortBy = $bindable(''),
        searchPlaceholder = '',
        sortOptions = [],
    }: Props = $props();

    // --- Local dropdown state ---
    let showSortDropdown = $state(false);

    // --- Derived label for the current sort selection ---
    let currentSortLabel = $derived(
        sortOptions.find(opt => opt.value === sortBy)?.label ??
        (sortOptions[0]?.label ?? $text('common.sort'))
    );

    // --- Handlers ---
    function toggleSortDropdown() {
        showSortDropdown = !showSortDropdown;
    }

    function closeSortDropdown() {
        showSortDropdown = false;
    }

    function handleSortChange(value: string) {
        sortBy = value;
        showSortDropdown = false;
    }
</script>

<div class="search-sort-bar">
    <!-- Search input -->
    <div class="search-container">
        <span class="icon icon_search search-icon"></span>
        <input
            type="text"
            class="search-input"
            placeholder={searchPlaceholder}
            bind:value={searchQuery}
            aria-label={searchPlaceholder}
        />
    </div>

    <!-- Sort dropdown (only render when options are provided) -->
    {#if sortOptions.length > 0}
        <div class="sort-container">
            <button
                class="sort-button"
                onclick={toggleSortDropdown}
                aria-expanded={showSortDropdown}
                aria-haspopup="menu"
            >
                <span class="icon icon_sort sort-icon"></span>
                <span class="sort-label">{currentSortLabel}</span>
            </button>

            {#if showSortDropdown}
                <div class="sort-dropdown" role="menu">
                    {#each sortOptions as option (option.value)}
                        <button
                            class="sort-option"
                            class:active={sortBy === option.value}
                            onclick={() => handleSortChange(option.value)}
                            role="menuitem"
                        >
                            {option.label}
                        </button>
                    {/each}
                </div>
                <!-- Invisible backdrop to close dropdown when clicking outside -->
                <button
                    class="sort-backdrop"
                    onclick={closeSortDropdown}
                    aria-label={$text('common.close')}
                ></button>
            {/if}
        </div>
    {/if}
</div>

<style>
    .search-sort-bar {
        display: flex;
        gap: 0.75rem;
        align-items: center;
    }

    /* ── Search ─────────────────────────────────────────────────── */
    .search-container {
        flex: 1;
        position: relative;
        display: flex;
        align-items: center;
    }

    .search-icon {
        position: absolute;
        left: 12px;
        width: 18px;
        height: 18px;
        color: var(--color-grey-50);
        pointer-events: none;
    }

    .search-input {
        width: 100%;
        padding: 0.625rem 0.75rem 0.625rem 40px;
        font-size: 0.875rem;
        border: 1px solid var(--color-grey-20);
        border-radius: 8px;
        background: var(--color-grey-10);
        color: var(--color-grey-100);
        transition: border-color 0.2s, background 0.2s;
    }

    .search-input:focus {
        outline: none;
        border-color: var(--color-primary);
        background: var(--color-background);
    }

    .search-input::placeholder {
        color: var(--color-grey-50);
    }

    /* ── Sort ───────────────────────────────────────────────────── */
    .sort-container {
        position: relative;
        flex-shrink: 0;
    }

    .sort-button {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        padding: 0.625rem 1rem;
        font-size: 0.875rem;
        border: 1px solid var(--color-grey-20);
        border-radius: 8px;
        background: var(--color-grey-10);
        color: var(--color-grey-80);
        cursor: pointer;
        transition: border-color 0.2s, background 0.2s;
        white-space: nowrap;
    }

    .sort-button:hover {
        border-color: var(--color-grey-40);
        background: var(--color-grey-15);
    }

    .sort-icon {
        width: 16px;
        height: 16px;
        flex-shrink: 0;
    }

    .sort-dropdown {
        position: absolute;
        top: calc(100% + 4px);
        right: 0;
        min-width: 160px;
        background: var(--color-grey-blue);
        border: 1px solid var(--color-grey-20);
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        z-index: 100;
        overflow: hidden;
    }

    .sort-option {
        display: block;
        width: 100%;
        padding: 0.75rem 1rem;
        font-size: 0.875rem;
        text-align: left;
        background: transparent;
        border: none;
        color: var(--color-grey-80);
        cursor: pointer;
        transition: background 0.15s;
    }

    .sort-option:hover {
        background: var(--color-grey-15);
    }

    .sort-option.active {
        color: var(--color-primary);
        font-weight: 600;
    }

    /* Full-screen invisible backdrop that closes dropdown on outside click */
    .sort-backdrop {
        position: fixed;
        inset: 0;
        z-index: 99;
        background: transparent;
        border: none;
        cursor: default;
    }
</style>
