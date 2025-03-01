<script lang="ts">
    import Icon from './Icon.svelte';

    // Props
    export let iconGrid: (string | null)[][] = [];
    export let size = "67px";
    export let gridGap = '4px';
    export let shifting = '30px';
    export let side: 'left' | 'right' | 'center' | undefined = 'center';
    // New prop to define which elements should be shifted (columns, rows, or none)
    export let shifted: 'columns' | 'rows' | undefined = undefined;
</script>

<div class="icon-grid {side}" style="--icon-gap: {gridGap}; --shifting: {shifting};">
    {#each iconGrid as row, rowIndex}
        <div class="icon-column" class:row-shifted={shifted === 'rows' && rowIndex % 2 === 1}>
            {#each row as appName, colIndex}
                <div 
                    class="icon-wrapper" 
                    class:column-shifted={shifted === 'columns' && colIndex % 2 === 1}
                    data-app={appName}
                >
                    {#if appName !== null}
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
    }

    .icon-column {
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

    /* Center alignment */
    .icon-grid.center {
        margin: 0 auto;
    }

    /* Mobile styles */
    @media (max-width: 767px) {
        .icon-grid {
            position: absolute;
            top: 1rem;
            display: flex;
            flex-direction: column;
            gap: 0.1rem;
            width: auto;
            -webkit-mask-image: linear-gradient(to bottom, rgba(0,0,0,0.8) 0%, rgba(0,0,0,0.4) 40%, rgba(0,0,0,0) 100%);
            mask-image: linear-gradient(to bottom, rgba(0,0,0,0.8) 0%, rgba(0,0,0,0.4) 40%, rgba(0,0,0,0) 100%);
        }

        .icon-grid.left {
            right: 50vw;
        }

        .icon-grid.right {
            left: 50vw;
        }

        .icon-grid.center {
            position: relative;
            left: auto;
            right: auto;
            margin: 0 auto;
        }

        .icon-column {
            display: flex;
            flex-direction: row;
            gap: 0.25rem;
            margin-top: 0;
        }

        /* Adjust mobile shifting behavior */
        .icon-grid.left .row-shifted,
        .icon-grid.right .row-shifted {
            transform: translateX(24px) translateY(0);
        }

        /* Preserve column shifting on mobile, but with smaller offset */
        .column-shifted {
            transform: translateY(10px);
        }

        .icon-wrapper {
            opacity: 0.3;
        }
    }

    @media (max-width: 600px) {
        .icon-grid.left {
            padding-right: 20px;
            margin-right: -20px;
        }
    }
</style>