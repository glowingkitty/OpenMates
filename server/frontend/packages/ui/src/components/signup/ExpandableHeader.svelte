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
    <AppIconGrid 
        iconGrid={IconGrid}
        size="30px" 
        gridGap="3px"
        shifting="-10px"
        shifted="columns"
    />
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
</style>
