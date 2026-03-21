<!-- frontend/packages/ui/src/components/settings/SearchSortBar.svelte

     Shared search & sort bar for settings list views.
     Matches Figma "Search & sort" element (node 5040-64488).

     Design:
     - Search input: white pill (24px radius, shadow), search icon left, placeholder grey
     - Optional delete icon: shown on the right inside the input when query is non-empty,
       fades in/out with an opacity transition, clears the input on click.
     - Sort button: white pill (24px radius, shadow), sort.svg icon only.
       On click opens a NATIVE OS <select> dropdown (not a custom dropdown).

     The <select> is visually hidden behind the sort icon button so clicking the
     icon triggers the native OS dropdown.

     Preview: /dev/preview/settings
-->

<script lang="ts">
    /** Sort/filter option definition */
    interface SelectOption {
        value: string;
        label: string;
    }

    let {
        searchQuery = $bindable(''),
        sortBy = $bindable(''),
        filterBy = $bindable(''),
        searchPlaceholder = '',
        sortOptions = [],
        filterOptions = [],
        onFocusIn = undefined,
        onInput = undefined,
        onClear = undefined,
    }: {
        /** Current search query — use bind:searchQuery in parent */
        searchQuery?: string;
        /** Currently selected sort value — use bind:sortBy in parent */
        sortBy?: string;
        /** Currently selected filter value — use bind:filterBy in parent */
        filterBy?: string;
        /** Placeholder text for the search input */
        searchPlaceholder?: string;
        /** Available sort options rendered in the native <select> dropdown */
        sortOptions?: SelectOption[];
        /** Available filter options rendered in the native <select> dropdown */
        filterOptions?: SelectOption[];
        /** Called when the search input gains focus (e.g. to open full-screen search) */
        onFocusIn?: (() => void) | undefined;
        /** Called with each keystroke value (e.g. to pipe into search store) */
        onInput?: ((value: string) => void) | undefined;
        /** Called when the delete/clear button is pressed — clears the query */
        onClear?: (() => void) | undefined;
    } = $props();

    function handleClear() {
        searchQuery = '';
        onClear?.();
        onInput?.('');
    }
</script>

<div class="search-sort-bar">
    <!-- Search input with search icon and optional clear button -->
    <div class="search-container">
        <div class="search-icon" aria-hidden="true"></div>
        <input
            type="text"
            class="search-input"
            placeholder={searchPlaceholder}
            bind:value={searchQuery}
            aria-label={searchPlaceholder}
            onfocusin={onFocusIn}
            oninput={(e) => onInput?.((e.target as HTMLInputElement).value)}
        />
        <!-- Delete/clear button — fades in when query is non-empty -->
        <button
            type="button"
            class="clear-button"
            class:visible={searchQuery.length > 0}
            aria-label="Clear search"
            onclick={handleClear}
        ></button>
    </div>

    <!-- Filter: visible icon button over a hidden native <select> -->
    {#if filterOptions.length > 0}
        <div class="filter-container">
            <div class="filter-icon" aria-hidden="true"></div>
            <select
                class="filter-select"
                bind:value={filterBy}
                aria-label="Filter"
            >
                {#each filterOptions as option}
                    <option value={option.value}>{option.label}</option>
                {/each}
            </select>
        </div>
    {/if}

    <!-- Sort: visible icon button over a hidden native <select> -->
    {#if sortOptions.length > 0}
        <div class="sort-container">
            <div class="sort-icon" aria-hidden="true"></div>
            <select
                class="sort-select"
                bind:value={sortBy}
                aria-label="Sort"
            >
                {#each sortOptions as option}
                    <option value={option.value}>{option.label}</option>
                {/each}
            </select>
        </div>
    {/if}
</div>

<style>
    .search-sort-bar {
        display: flex;
        gap: 0.5rem;
        align-items: center;
    }

    /* ── Search pill ─────────────────────────────────────────────── */
    .search-container {
        flex: 1;
        position: relative;
        display: flex;
        align-items: center;
    }

    .search-icon {
        position: absolute;
        left: 0.875rem;
        width: 1.125rem;
        height: 1.125rem;
        pointer-events: none;
        -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
        -webkit-mask-size: contain;
        -webkit-mask-repeat: no-repeat;
        -webkit-mask-position: center;
        mask-image: url('@openmates/ui/static/icons/search.svg');
        mask-size: contain;
        mask-repeat: no-repeat;
        mask-position: center;
        background-color: var(--color-grey-50);
    }

    .search-input {
        width: 100%;
        padding: 0.625rem 1rem 0.625rem 2.5rem;
        background: var(--color-grey-0);
        border: none;
        border-radius: 1.5rem;
        box-shadow: 0 0.25rem 0.25rem rgba(0, 0, 0, 0.1);
        font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-weight: 500;
        font-size: var(--input-font-size, 1rem);
        line-height: 1.25;
        color: var(--color-grey-100);
        transition: box-shadow 0.2s ease;
        box-sizing: border-box;
    }

    .search-input::placeholder {
        color: var(--color-grey-50);
    }

    .search-input:focus {
        box-shadow: 0 0.25rem 0.5rem rgba(0, 0, 0, 0.15),
                    0 0 0 0.125rem var(--color-primary-start);
    }

    /* ── Filter pill ────────────────────────────────────────────── */
    .filter-container {
        position: relative;
        flex-shrink: 0;
        width: 2.75rem;
        height: 2.75rem;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--color-grey-0);
        border-radius: 1.5rem;
        box-shadow: 0 0.25rem 0.25rem rgba(0, 0, 0, 0.1);
        cursor: pointer;
    }

    .filter-icon {
        width: 1.375rem;
        height: 1.375rem;
        pointer-events: none;
        -webkit-mask-image: url('@openmates/ui/static/icons/filter.svg');
        -webkit-mask-size: contain;
        -webkit-mask-repeat: no-repeat;
        -webkit-mask-position: center;
        mask-image: url('@openmates/ui/static/icons/filter.svg');
        mask-size: contain;
        mask-repeat: no-repeat;
        mask-position: center;
        background: var(--color-primary);
        transition: opacity 0.2s ease;
    }

    .filter-container:hover .filter-icon {
        opacity: 0.8;
    }

    .filter-select {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        opacity: 0;
        cursor: pointer;
        border: none;
        font-size: 1rem;
    }

    /* ── Sort pill ───────────────────────────────────────────────── */
    .sort-container {
        position: relative;
        flex-shrink: 0;
        width: 2.75rem;
        height: 2.75rem;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--color-grey-0);
        border-radius: 1.5rem;
        box-shadow: 0 0.25rem 0.25rem rgba(0, 0, 0, 0.1);
        cursor: pointer;
    }

    .sort-icon {
        width: 1.375rem;
        height: 1.375rem;
        pointer-events: none;
        -webkit-mask-image: url('@openmates/ui/static/icons/sort.svg');
        -webkit-mask-size: contain;
        -webkit-mask-repeat: no-repeat;
        -webkit-mask-position: center;
        mask-image: url('@openmates/ui/static/icons/sort.svg');
        mask-size: contain;
        mask-repeat: no-repeat;
        mask-position: center;
        background: var(--color-primary);
        transition: opacity 0.2s ease;
    }

    .sort-container:hover .sort-icon {
        opacity: 0.8;
    }

    /* Native <select> stretched over the entire pill — invisible but clickable */
    .sort-select {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        opacity: 0;
        cursor: pointer;
        border: none;
        /* Larger font prevents iOS auto-zoom on focus */
        font-size: 1rem;
    }

    /* ── Clear / delete button inside search pill ────────────────── */
    .clear-button {
        position: absolute;
        right: 1rem;
        top: 50%;
        transform: translateY(-50%);
        width: 1.25rem;
        height: 1.25rem;
        border: none;
        background: transparent;
        cursor: pointer;
        padding: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.2s ease;
        /* Red delete icon using mask + background-color */
        -webkit-mask-image: url('@openmates/ui/static/icons/delete.svg');
        -webkit-mask-size: contain;
        -webkit-mask-repeat: no-repeat;
        -webkit-mask-position: center;
        mask-image: url('@openmates/ui/static/icons/delete.svg');
        mask-size: contain;
        mask-repeat: no-repeat;
        mask-position: center;
        background-color: var(--color-error);
    }

    .clear-button.visible {
        opacity: 0.7;
        pointer-events: auto;
    }

    .clear-button.visible:hover {
        opacity: 1;
    }

    /* Add right padding to search input so text doesn't overlap clear button */
    .search-container:has(.clear-button.visible) .search-input {
        padding-right: 2.75rem;
    }
</style>
