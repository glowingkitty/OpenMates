<script lang="ts">
    import Icon from './Icon.svelte';

    // Props
    export let iconGrid: (string | null)[][] = [];
    export let size = "67px";
    export let gridGap = '30px';
    export let shifting = '30px';
    // New prop to define which elements should be shifted (columns, rows, or none)
    export let shifted: 'columns' | 'rows' | undefined = undefined;
</script>

<div class="icon-grid" style="--icon-gap: {gridGap}; --shifting: {shifting};">
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
                        />
                    {:else}
                        <Icon 
                            name={appName} 
                            type="app"
                            in_header={true}
                            size={size}
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
        align-content: start;
        gap: var(--icon-gap, 4px);
        /* Center by default */
        margin: 0 auto;
    }

    .icon-row {
        display: flex;
        flex-direction: row;
        align-items: center;
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