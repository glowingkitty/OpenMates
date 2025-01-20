<script lang="ts">
    // Props for the image preview
    export let src: string;
    export let filename: string;
    export let id: string;

    function handleClick(e: MouseEvent) {
        document.dispatchEvent(new CustomEvent('embedclick', { 
            bubbles: true, 
            detail: { 
                id,
                elementId: `embed-${id}`
            }
        }));
    }
</script>

<div 
    class="preview-container photo"
    role="button"
    tabindex="0"
    data-type="custom-embed"
    data-src={src}
    data-filename={filename}
    data-id={id}
    id="embed-{id}"
    on:click={handleClick}
    on:keydown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            handleClick(e as unknown as MouseEvent);
        }
    }}
>
    <div class="checkerboard-background">
        <img {src} alt="Preview" class="preview-image fill-container" />
    </div>
    <div class="icon_rounded photos"></div>
</div>

<style>
    .preview-container {
        width: 300px;
        height: 200px;
        border-radius: 30px;
        position: relative;
        overflow: hidden;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        cursor: pointer;
        margin: 4px 0;
    }

    .checkerboard-background {
        width: 100%;
        height: 100%;
        background-image: linear-gradient(45deg, var(--color-grey-20) 25%, transparent 25%),
                         linear-gradient(-45deg, var(--color-grey-20) 25%, transparent 25%),
                         linear-gradient(45deg, transparent 75%, var(--color-grey-20) 75%),
                         linear-gradient(-45deg, transparent 75%, var(--color-grey-20) 75%);
        background-size: 20px 20px;
        background-position: 0 0, 0 10px, 10px -10px, -10px 0px;
        background-color: var(--color-grey-0);
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .preview-image.fill-container {
        width: 100%;
        height: 100%;
        object-fit: cover;
    }
</style> 