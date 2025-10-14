<script lang="ts">
    import InlinePreviewBase from './InlinePreviewBase.svelte';
    
    // Props using Svelte 5 runes
    let { 
        content,
        id
    }: {
        content: string;
        id: string;
    } = $props();
    
    let filename = $derived(content?.split('\n')[0]?.slice(0, 50) || 'Text preview');
    
    $effect(() => {
        console.debug('Text preview rendered:', { id, contentLength: content?.length });
    });
</script>

<InlinePreviewBase {id} type="text" src={content} {filename}>
    <div class="preview-container">
        <div class="text-preview">
            {#if content}
                {content.slice(0, 200)}{content.length > 200 ? '...' : ''}
            {:else}
                <span class="placeholder">Empty text preview</span>
            {/if}
        </div>
        <div class="filename-container">
            <span class="filename">{filename}</span>
        </div>
    </div>
</InlinePreviewBase>

<style>
    .preview-container {
        position: relative;
        width: 100%;
        min-height: 40px;
    }

    .text-preview {
        padding: 8px 16px 8px 65px;
        font-size: 13px;
        color: var(--color-font-secondary);
        line-height: 1.4;
        white-space: pre-wrap;
        word-break: break-word;
    }

    .filename-container {
        position: absolute;
        left: 65px;
        right: 16px;
        top: 0;
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

    .placeholder {
        font-style: italic;
        color: var(--color-font-tertiary);
    }
</style> 