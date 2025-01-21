<script lang="ts">
    import InlinePreviewBase from './InlinePreviewBase.svelte';
    
    export let src: string;
    export let filename: string;
    export let id: string;
</script>

<InlinePreviewBase {id} type="pdf" {src} {filename}>
    <div class="filename-container">
        <span class="filename">{filename}</span>
    </div>
</InlinePreviewBase>

<style>

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