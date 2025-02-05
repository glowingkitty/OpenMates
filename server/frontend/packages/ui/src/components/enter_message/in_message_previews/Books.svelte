<script lang="ts">
    import InlinePreviewBase from './InlinePreviewBase.svelte';
    
    export let src: string;
    export let filename: string;
    export let bookname: string;
    export let author: string;
    export let id: string;
    export let coverUrl: string;
</script>

<InlinePreviewBase {id} type="book" {src} {filename} height="200px">
    <div 
        class="preview-container"
    >
        <div class="book-preview">
            <img src={coverUrl} alt="Book cover" class="cover-image" />
        </div>
        <div class="info-bar">
            <div class="text-container">
                <span class="bookname">{bookname}</span>
                <span class="author">{author}</span>
            </div>
        </div>
    </div>
</InlinePreviewBase>

<style>
    .preview-container {
        position: relative;
        width: 100%;
        height: 100%;
        border-radius: 8px;
        overflow: hidden;
        transition: transform 300ms cubic-bezier(0.4, 0, 0.2, 1),
                   opacity 300ms cubic-bezier(0.4, 0, 0.2, 1);
        transform-origin: center center;
    }

    .preview-container.transitioning {
        transform: scale(1.15);
        opacity: 0;
    }

    .preview-container.transitioning-in {
        transform: scale(1);
        opacity: 1;
        animation: scaleIn 300ms cubic-bezier(0.4, 0, 0.2, 1);
    }

    @keyframes scaleIn {
        from {
            transform: scale(1.15);
            opacity: 0;
        }
        to {
            transform: scale(1);
            opacity: 1;
        }
    }

    .book-preview {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        padding: 16px;
        overflow: hidden;
        max-height: 100%;
        transition: opacity 300ms cubic-bezier(0.4, 0, 0.2, 1);
    }

    .transitioning .book-preview {
        opacity: 0;
    }

    .info-bar {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        border-radius: 30px;
        height: 60px;
        background-color: var(--color-grey-20);
        display: flex;
        align-items: center;
        padding-left: 70px;
        padding-right: 16px;
        /* align-items: flex-start; */
        transition: opacity 300ms cubic-bezier(0.4, 0, 0.2, 1);
    }

    .transitioning .info-bar {
        opacity: 0;
    }

    /* Create a container for the stacked text */
    .text-container {
        display: flex;
        flex-direction: column;
        justify-content: center;
        height: 100%;
        line-height: 1.3;
    }

    .bookname {
        font-size: 16px;
        color: var(--color-font-primary);
    }

    .author {
        font-size: 16px;
        color: var(--color-font-secondary);
    }
</style>