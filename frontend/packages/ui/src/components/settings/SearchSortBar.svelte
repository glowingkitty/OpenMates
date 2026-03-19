<!-- frontend/packages/ui/src/components/settings/SearchSortBar.svelte

     Shared search & sort bar for settings list views.
     Matches Figma "Search & sort" element (node 5040-64488).

     Design:
     - Search input: white pill (24px radius, shadow), search icon left, placeholder grey
     - Sort button: white pill (24px radius, shadow), sort.svg icon only.
       On click opens a NATIVE OS <select> dropdown (not a custom dropdown).

     The <select> is visually hidden behind the sort icon button so clicking the
     icon triggers the native OS dropdown.

     Preview: /dev/preview/settings
-->

<script lang="ts">
    /** Sort option definition */
    interface SortOption {
        value: string;
        label: string;
    }

    let {
        searchQuery = $bindable(''),
        sortBy = $bindable(''),
        searchPlaceholder = '',
        sortOptions = [],
        onFocusIn = undefined,
        onInput = undefined,
    }: {
        /** Current search query — use bind:searchQuery in parent */
        searchQuery?: string;
        /** Currently selected sort value — use bind:sortBy in parent */
        sortBy?: string;
        /** Placeholder text for the search input */
        searchPlaceholder?: string;
        /** Available sort options rendered in the native <select> dropdown */
        sortOptions?: SortOption[];
        /** Called when the search input gains focus (e.g. to open full-screen search) */
        onFocusIn?: (() => void) | undefined;
        /** Called with each keystroke value (e.g. to pipe into search store) */
        onInput?: ((value: string) => void) | undefined;
    } = $props();
</script>

<div class="search-sort-bar">
    <!-- Search input with search icon -->
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
    </div>

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
        left: 1.1875rem;
        width: 1.4375rem;
        height: 1.4375rem;
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
        padding: 1.0625rem 1.4375rem 1.0625rem 3rem;
        background: var(--color-grey-0);
        border: none;
        border-radius: 1.5rem;
        box-shadow: 0 0.25rem 0.25rem rgba(0, 0, 0, 0.1);
        font-family: 'Lexend Deca Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        font-weight: 500;
        font-size: var(--input-font-size, 1rem);
        line-height: 1.25;
        color: var(--color-grey-100);
        outline: none;
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

    /* ── Sort pill ───────────────────────────────────────────────── */
    .sort-container {
        position: relative;
        flex-shrink: 0;
        width: 3.5625rem;
        height: 3.375rem;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--color-primary);
        border-radius: 1.5rem;
        box-shadow: 0 0.25rem 0.25rem rgba(0, 0, 0, 0.1);
        cursor: pointer;
    }

    .sort-icon {
        width: 1.9375rem;
        height: 1.9375rem;
        pointer-events: none;
        -webkit-mask-image: url('@openmates/ui/static/icons/sort.svg');
        -webkit-mask-size: contain;
        -webkit-mask-repeat: no-repeat;
        -webkit-mask-position: center;
        mask-image: url('@openmates/ui/static/icons/sort.svg');
        mask-size: contain;
        mask-repeat: no-repeat;
        mask-position: center;
        background-color: #ffffff;
        transition: background-color 0.2s ease;
    }

    .sort-container:hover .sort-icon {
        background-color: rgba(255, 255, 255, 0.85);
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
</style>
