<script lang="ts">
    import Icon from './Icon.svelte';

    // Props
    export let iconGrid: (string | null)[][] = [];
    export let size: string = '67px'; // Default size in pixels
    export let gridGap: string = '30px';
    export let shifting: string = '30px';
    // Define which elements should be shifted (columns, rows, or none)
    export let shifted: 'columns' | 'rows' | 'none' = 'none';
    // Border color prop
    export let borderColor: string | null | undefined = undefined;
    
    // Track if gridGap and shifting were explicitly set
    let isGridGapExplicit = false;
    let isShiftingExplicit = false;
    
    // Mark props as explicitly set if they were passed in
    $: {
        if ($$props.gridGap !== undefined) isGridGapExplicit = true;
        if ($$props.shifting !== undefined) isShiftingExplicit = true;
    }
    
    // Compute grid gap based on icon size only if not explicitly set
    $: {
        // Extract numeric value from size
        const sizeValue = parseInt(size);
        
        // Set grid gap proportionally to icon size only if not explicitly provided
        if (!isGridGapExplicit) {
            // For 67px icons, use 30px gap
            // For smaller icons, use proportionally smaller gap
            const gapRatio = 30/67; // reference ratio from default 
            gridGap = `${Math.round(sizeValue * gapRatio)}px`;
        }
        
        // Similarly for shifting, only if not explicitly provided
        if (!isShiftingExplicit) {
            shifting = `${Math.round(sizeValue * 0.45)}px`;
        }
    }
</script>

<div 
    class="icon-grid" 
    class:shifted-rows={shifted === 'rows'} 
    class:shifted-columns={shifted === 'columns'} 
    style="--icon-gap: {gridGap}; --shifting: {shifting};"
>
    {#each iconGrid as row, rowIndex}
        <div class="icon-row" class:row-shifted={shifted === 'rows' && rowIndex % 2 === 1}>
            {#each row as appName, colIndex}
                <div 
                    class="icon-wrapper" 
                    class:column-shifted={shifted === 'columns' && colIndex % 2 === 1}
                    data-app={appName}
                >
                    {#if appName === null}
                        <Icon 
                            type="placeholder"
                            in_header={true}
                            size={size}
                            borderColor={borderColor}
                        />
                    {:else}
                        <Icon 
                            name={appName} 
                            type="app"
                            in_header={true}
                            size={size}
                            borderColor={borderColor}
                        />
                    {/if}
                </div>
            {/each}
        </div>
    {/each}
</div>

<style>
    .icon-grid {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: var(--icon-gap, 4px);
        /* Center by default */
        margin: 0 auto;
        width: 100%;
    }

    .icon-row {
        display: flex;
        flex-direction: row;
        align-items: center;
        justify-content: center;
        gap: var(--icon-gap, 4px);
    }

    /* Row shifting (previously called staggered) */
    .row-shifted {
        transform: translateX(var(--shifting)) translateY(0);
    }

    /* Column shifting (new feature) */
    .column-shifted {
        transform: translateY(calc(-1*var(--shifting)));
    }

    .icon-wrapper {
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0.2;
        transition: opacity 0.3s ease;
        width: auto;
        height: auto;
    }

    /* Style for small icons on mobile */
    .small .icon-wrapper {
        width: 36px;
        height: 36px;
        border-radius: 8px;
    }
    
    .small .icon-row {
        gap: 16px;
    }
    
    .small {
        gap: 16px;
    }
    
    /* Icon size adjustments */
    .small [class^="icon_"] {
        transform: scale(0.7);
    }
    
</style>