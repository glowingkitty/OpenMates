<script lang="ts">
    // Common props for all preview types
    export let id: string;
    export let type: 'audio' | 'pdf' | 'photos' | 'photos_recording' | 'web' | 'recording' | 'file' | 'code' | 'maps' | 'video' | 'video_recording' | 'book';
    
    // Optional props with default values
    export let src: string | undefined = undefined;
    export let filename: string | null | undefined = undefined;
    export let url: string | undefined = undefined;
    export let height: string = '60px';
    export let customClass: string = '';

    // Common click handler for all previews
    function handleClick(e: MouseEvent) {
        document.dispatchEvent(new CustomEvent('embedclick', { 
            bubbles: true, 
            detail: { 
                id,
                elementId: `embed-${id}`
            }
        }));
    }

    // New keydown handler to replace the inline code in markup
    function handleKeydown(e: KeyboardEvent) {
        // Check for Enter or Space key to simulate click behavior.
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            // Use type assertion here inside the script block (allowed)
            handleClick(e as unknown as MouseEvent);
        }
    }

    // Prepare data attributes object
    const dataAttributes = {
        'data-type': 'custom-embed',
        'data-id': id,
        ...(src && { 'data-src': src }),
        ...(filename && { 'data-filename': filename }),
        ...(url && { 'data-url': url })
    };
</script>

<div 
    class="preview-container {type} {customClass}"
    role="button"
    tabindex="0"
    id="embed-{id}"
    style="height: {height}"
    {...dataAttributes}
    on:click={handleClick}
    on:keydown={handleKeydown}
>
    <!-- Icon slot for the rounded icon -->
    <div class="icon_rounded {type}"></div>
    
    <!-- Main content slot -->
    <slot />
</div>

<style>
    .preview-container {
        width: 300px;
        background-color: var(--color-grey-20);
        border-radius: 30px;
        position: relative;
        cursor: pointer;
        box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
        transition: background-color 0.2s;
        display: flex;
        align-items: center;
        margin: 4px 0;
        overflow: hidden;
    }

    .preview-container:hover {
        background-color: var(--color-grey-30);
    }

    /* Common filename container styles */
    :global(.preview-container .filename-container) {
        position: absolute;
        left: 65px;
        right: 16px;
        min-height: 40px;
        padding: 5px 0;
        display: flex;
        align-items: center;
    }

    :global(.preview-container .filename) {
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

    /* Photo preview specific styles */
    .preview-container.photos {
        overflow: hidden;
    }
</style> 
