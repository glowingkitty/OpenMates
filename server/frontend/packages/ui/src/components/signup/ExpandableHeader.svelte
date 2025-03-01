<script lang="ts">
    import AppIconGrid from '../AppIconGrid.svelte';
    
    export let visible = false;

    // Define icon grids for both sides based on the original layout
    const IconGrid = [
        ['diagrams','sheets','life_coaching','jobs','fashion','calendar','contacts','hosting','social_media'],
        ['slides','docs','audio','code','ai','photos','events','travel','mail'],
        ['weather','notes','videos',null,null,null,'pcb_design','legal','web'],
        ['calculator','maps','finance',null,null,null,'health','home','design'],
        ['3d_models','games','news',null,null,null,'movies','whiteboards','project_management']
    ];
</script>

<div class="expandable-header" class:visible>
    <div class="header-content">
        <div class="app-icons-container expandable-header-icons">
            <div class="app-icons-side left">
                <AppIconGrid 
                    iconGrid={IconGrid}
                    size="30px" 
                    gridGap="2px"
                    shifted="columns"
                />
            </div>
        </div>
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

    .header-content {
        position: relative;
        height: 100%;
    }
    
    .app-icons-container {
        display: flex;
        justify-content: space-between;
        width: 100%;
        height: 100%;
        overflow: hidden;
    }
    
    .app-icons-side {
        width: 50%;
        position: relative;
    }
    
    .app-icons-side.left {
        display: flex;
        justify-content: flex-end;
        padding-right: 10px;
    }
    
    .app-icons-side.right {
        display: flex;
        justify-content: flex-start;
        padding-left: 10px;
    }
    
    /* Override styles from AppIconGrid for smaller icons and spacing */
    :global(.expandable-header-icons .icon-wrapper) {
        margin: 0;
    }
    
    :global(.expandable-header-icons .icon-grid) {
        gap: 2px;
    }
    
    :global(.expandable-header-icons .icon-column) {
        gap: 2px;
    }
    
    :global(.expandable-header-icons .icon-column:nth-child(2)) {
        transform: translateY(-0.5rem); /* Reduce the offset for smaller icons */
    }
    
    /* Override any margins that might be coming from the Icon component itself */
    :global(.expandable-header-icons :is(svg, img)) {
        margin: 0 !important;
        padding: 0 !important;
    }
    
    /* Target any wrapping elements that might be adding margins */
    :global(.expandable-header-icons .icon-wrapper > *) {
        margin: 0 !important;
        padding: 0 !important;
    }
</style>
