<script lang="ts">
    import Icon from './Icon.svelte';

    // Props using Svelte 5 runes mode
    let { 
        iconGrid = [],
        size = '67px',
        gridGap = '30px',
        shifting = '30px',
        shifted = 'none',
        borderColor = undefined
    }: {
        iconGrid?: (string | null)[][];
        size?: string;
        gridGap?: string;
        shifting?: string;
        shifted?: 'columns' | 'rows' | 'none';
        borderColor?: string | null | undefined;
    } = $props();
    
    // Track if gridGap and shifting were explicitly set using $state (Svelte 5 runes mode)
    let isGridGapExplicit = $state(false);
    let isShiftingExplicit = $state(false);
    
    // In runes mode, we can't easily detect if props were explicitly passed
    // For now, we'll assume they are explicit if they differ from defaults
    // This is a limitation of the runes mode approach
    $effect(() => {
        isGridGapExplicit = gridGap !== '30px';
        isShiftingExplicit = shifting !== '30px';
    });
    
    // Compute grid gap based on icon size only if not explicitly set using $effect (Svelte 5 runes mode)
    $effect(() => {
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
    });
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

    
</style>