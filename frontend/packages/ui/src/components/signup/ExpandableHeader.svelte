<script lang="ts">
    import AppIconGrid from '../AppIconGrid.svelte';
    
    export let visible = false;
    // Optional credits amount to display specific icon grid
    export let credits_amount: number | undefined = undefined;

    // Define icon grids for both sides based on the original layout
    const IconGrid50000Credits = [
        ['diagrams','sheets','lifecoaching','jobs','fashion','calendar','contacts','hosting','socialmedia'],
        ['slides','docs','audio','code','ai','photos','events','travel','mail'],
        ['weather','notes','videos',null,null,null,'pcbdesign','legal','web'],
        ['calculator','maps','finance',null,null,null,'health','home','design'],
        ['3dmodels','games','news',null,null,null,'movies','whiteboards','projectmanagement']
    ];
    const IconGrid20000Credits = [
        ['diagrams','sheets','lifecoaching','jobs','fashion','calendar','contacts','hosting','socialmedia'],
        ['slides','docs','audio','code','ai','photos','events','travel','mail']
    ];
    const IconGrid10000Credits = [
        ['lifecoaching','jobs','fashion','calendar','contacts'],
        ['audio','code','ai','photos','events']
    ];
    const IconGrid1000Credits = [
        [null,null,null,null,null],
        [null,'code','ai','photos',null]
    ];

    // Function to select the appropriate icon grid based on credits amount
    function getIconGridForCredits(amount: number | undefined) {
        // If no specific amount is provided, default to 20000 grid (for step 9)
        if (amount === undefined) return IconGrid20000Credits;
        
        // Select grid based on amount
        if (amount >= 50000) return IconGrid50000Credits;
        if (amount >= 20000) return IconGrid20000Credits;
        if (amount >= 10000) return IconGrid10000Credits;
        if (amount >= 1000) return IconGrid1000Credits;
        return IconGrid1000Credits; // Fallback to smallest grid
    }

    // Reactively compute the icon grid to use
    $: iconGrid = getIconGridForCredits(credits_amount);
</script>

<div class="expandable-header" class:visible>
    <div class="icon-grid-wrapper">
        <AppIconGrid 
            iconGrid={iconGrid}
            size="35px" 
            gridGap="3px"
            shifting="-10px"
            shifted="columns"
            borderColor={null}
        />
    </div>
</div>

<style>
    .expandable-header {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        width: 100%;
        height: 0;
        background: var(--color-primary);
        overflow: hidden;
        transition: height 0.4s cubic-bezier(0.22, 1, 0.36, 1);
        z-index: 1; /* Make sure it's above other content but below navigation */
    }

    .expandable-header.visible {
        height: 130px
    }

    @media (max-width: 600px) {
        .expandable-header.visible {
            height: 60px;
        }
    }

    .icon-grid-wrapper {
        margin-top:-29px;
    }
</style>
