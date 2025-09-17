<script lang="ts">
    import { _ } from 'svelte-i18n';
    import InlinePreviewBase from './InlinePreviewBase.svelte';
    
    // Props using Svelte 5 runes
    let { 
        url,
        id
    }: {
        url: string;
        id: string;
    } = $props();

    const urlObj = new URL(url);
    const parts = {
        subdomain: '',
        domain: '',
        path: ''
    };

    const hostParts = urlObj.hostname.split('.');
    if (hostParts.length > 2) {
        parts.subdomain = hostParts[0] + '.';
        parts.domain = hostParts.slice(1).join('.');
    } else {
        parts.domain = urlObj.hostname;
    }

    const fullPath = urlObj.pathname + urlObj.search + urlObj.hash;
    parts.path = fullPath === '/' ? '' : fullPath;

    let showCopied = false;
</script>

<InlinePreviewBase {id} type="web" {url} customClass={showCopied ? 'show-copied' : ''}>
    <div class="url-container">
        <div class="url">
            <div class="domain-line">
                <span class="subdomain">{parts.subdomain}</span>
                <span class="main-domain">{parts.domain}</span>
            </div>
            {#if parts.path}
                <span class="path">{parts.path}</span>
            {/if}
        </div>
        <div class="copied-message">
            {$_('enter_message.press_and_hold_menu.copied_to_clipboard.text')}
        </div>
    </div>
</InlinePreviewBase>

<style>
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
        font-size: 16px;
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
        left: 0;
        width: 100%;
        transform: translateY(-50%);
        text-align: center;
        opacity: 0;
    }

    :global(.show-copied .url) {
        opacity: 0;
    }

    :global(.show-copied .copied-message) {
        opacity: 1;
    }
</style>
