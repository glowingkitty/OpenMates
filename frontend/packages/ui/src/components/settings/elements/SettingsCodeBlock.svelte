<!--
    SettingsCodeBlock — Monospace text display for settings pages.

    Replaces custom `.account-debug-pre`, recovery key display, and API key
    display patterns across settings pages with a single canonical component
    supporting optional copy-to-clipboard and scroll overflow.

    Design reference: Figma "settings_menu_elements" frame (node 4944-31418)
    Preview: /dev/preview/settings
-->
<script lang="ts">
    let {
        code,
        copyable = false,
        maxHeight = '',
        wrap = true,
    }: {
        code: string;
        copyable?: boolean;
        maxHeight?: string;
        wrap?: boolean;
    } = $props();

    let copied = $state(false);

    async function handleCopy() {
        try {
            await navigator.clipboard.writeText(code);
            copied = true;
            setTimeout(() => {
                copied = false;
            }, 2000);
        } catch {
            /* clipboard API may be unavailable in non-secure contexts */
        }
    }
</script>

<div class="settings-code-block">
    <div
        class="code-container"
        class:wrap
        class:no-wrap={!wrap}
        style:max-height={maxHeight || undefined}
        style:overflow-y={maxHeight ? 'auto' : undefined}
    >
        {#if copyable}
            <button
                class="copy-button"
                class:copied
                onclick={handleCopy}
                aria-label="Copy to clipboard"
            >
                <span class="copy-icon"></span>
            </button>
        {/if}
        <pre>{code}</pre>
    </div>
</div>

<style>
    .settings-code-block {
        padding: 0 0.625rem;
    }

    .code-container {
        position: relative;
        background: var(--color-grey-10);
        border: 0.0625rem solid var(--color-grey-25);
        border-radius: 0.75rem;
        padding: 1rem;
    }

    .code-container pre {
        margin: 0;
        font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Menlo', monospace;
        font-size: var(--processing-details-font-size, 0.8125rem);
        color: var(--color-font-primary);
        line-height: 1.5;
    }

    .code-container.wrap pre {
        white-space: pre-wrap;
        word-break: break-word;
    }

    .code-container.no-wrap pre {
        white-space: pre;
        overflow-x: auto;
    }

    /* ── Copy button ─────────────────────────────────────────────── */
    .copy-button {
        position: absolute;
        top: 0.5rem;
        right: 0.5rem;
        width: 2rem;
        height: 2rem;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--color-grey-20);
        border: none;
        border-radius: 0.375rem;
        cursor: pointer;
        transition: background 0.2s ease;
    }

    .copy-button:hover {
        background: var(--color-grey-30);
    }

    .copy-icon {
        display: block;
        width: 1.25rem;
        height: 1.25rem;
        background: var(--color-font-secondary);
        -webkit-mask-image: var(--icon-url-copy, var(--icon-url-duplicate));
        mask-image: var(--icon-url-copy, var(--icon-url-duplicate));
        -webkit-mask-size: contain;
        mask-size: contain;
        -webkit-mask-repeat: no-repeat;
        mask-repeat: no-repeat;
        -webkit-mask-position: center;
        mask-position: center;
        transition: background 0.2s ease;
    }

    .copy-button.copied .copy-icon {
        -webkit-mask-image: var(--icon-url-check);
        mask-image: var(--icon-url-check);
        background: var(--color-success);
    }
</style>
