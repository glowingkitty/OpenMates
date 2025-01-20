<script lang="ts">
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
    class="preview-container pdf"
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
    <div class="icon_rounded pdf"></div>
    <div class="filename-container">
        <span class="filename">{filename}</span>
    </div>
</div>

<style>
    .preview-container {
        width: 300px;
        height: 60px;
        background-color: var(--color-grey-20);
        border-radius: 30px;
        position: relative;
        cursor: pointer;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        transition: background-color 0.2s;
        display: flex;
        align-items: center;
        margin: 4px 0;
    }

    .preview-container:hover {
        background-color: var(--color-grey-30);
    }

    .filename-container {
        position: absolute;
        left: 65px;
        right: 16px;
        min-height: 40px;
        padding: 5px 0;
        display: flex;
        align-items: center;
    }

    .filename {
        display: -webkit-box;
        -webkit-line-clamp: 2;
        line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
        text-overflow: ellipsis;
        line-height: 1.3;
        font-size: 14px;
        color: var(--color-font-primary);
        width: 100%;
        word-break: break-word;
        max-height: 2.6em;
    }
</style> 