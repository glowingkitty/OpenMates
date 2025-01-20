<script lang="ts">
    // Remove unused imports and simplify
    export let url: string;
    export let id: string;  // Add id prop to match PDF component pattern

    // Enhanced URL parsing
    const urlObj = new URL(url);
    const parts = {
        subdomain: '',
        domain: '',
        path: ''
    };

    // Split hostname into parts
    const hostParts = urlObj.hostname.split('.');
    if (hostParts.length > 2) {
        parts.subdomain = hostParts[0] + '.';
        parts.domain = hostParts.slice(1).join('.');
    } else {
        parts.domain = urlObj.hostname;
    }

    // Get path and query parameters
    const fullPath = urlObj.pathname + urlObj.search + urlObj.hash;
    parts.path = fullPath === '/' ? '' : fullPath;

    // Simplified click handler to match PDF pattern
    function handleClick(e: MouseEvent) {
        document.dispatchEvent(new CustomEvent('embedclick', { 
            bubbles: true, 
            detail: { 
                id,
                elementId: `embed-${id}`
            }
        }));
    }

    // Track URL visibility state
    let urlVisible = true;
    let showCopiedMessage = false;

    // Export these functions to be called from parent
    export function showCopiedConfirmation() {
        urlVisible = false;
        setTimeout(() => {
            showCopiedMessage = true;
            setTimeout(() => {
                showCopiedMessage = false;
                setTimeout(() => {
                    urlVisible = true;
                }, 300);
            }, 1500);
        }, 300);
    }
</script>

<div 
    class="web-preview-container"
    role="button"
    tabindex="0"
    data-type="custom-embed"
    data-url={url}
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
    <!-- Web icon -->
    <div class="icon_rounded web"></div>
    
    <!-- URL -->
    <div class="url-container">
        <div class="url" class:fade-out={!urlVisible} class:hidden={!urlVisible}>
            <div class="domain-line">
                <span class="subdomain">{parts.subdomain}</span>
                <span class="main-domain">{parts.domain}</span>
            </div>
            {#if parts.path}
                <span class="path">{parts.path}</span>
            {/if}
        </div>
        {#if showCopiedMessage}
            <div class="copied-message fade-in">
                URL copied to clipboard
            </div>
        {/if}
    </div>
</div>

<style>
    .web-preview-container {
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
    }

    .web-preview-container:hover {
        background-color: var(--color-grey-30);
    }

    .url-container {
        position: absolute;
        left: 65px;
        right: 16px;
        min-height: 40px;
        padding: 5px 0;
        display: flex;
        align-items: center;
    }

    .url {
        display: flex;
        flex-direction: column;
        line-height: 1.3;
        font-size: 14px;
        width: 100%;
        word-break: break-word;
        max-height: 2.6em;
        overflow: hidden;
    }

    .domain-line {
        display: flex;
        flex-direction: row;
        align-items: baseline;
    }

    .subdomain {
        color: var(--color-font-tertiary);
    }

    .main-domain {
        color: var(--color-font-primary);
    }

    .path {
        color: var(--color-font-tertiary);
        display: block;
        text-overflow: ellipsis;
        overflow: hidden;
        white-space: nowrap;
    }

    .copied-message {
        position: absolute;
        top: 50%;
        transform: translateY(-50%);
        width: 100%;
        text-align: center;
        color: var(--color-font-primary);
        font-weight: 500;
    }

    .hidden {
        display: none;
    }

    .fade-in {
        animation: fadeIn 0.3s ease-in;
    }

    .fade-out {
        animation: fadeOut 0.3s ease-in;
    }

    @keyframes fadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
    }

    @keyframes fadeOut {
        from { opacity: 1; }
        to { opacity: 0; }
    }
</style>
