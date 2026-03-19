<script lang="ts">
    // frontend/packages/ui/src/components/Not404Screen.svelte
    /**
     * @file Not404Screen.svelte
     * @description 404 not-found screen. Shows a branded banner with the server
     * icon, "404" heading and "Page not found" subtitle — followed by an explanation
     * block (why the page might be missing, copyable URL) and two action buttons
     * (Search / Ask AI) separated by an "or" divider.
     *
     * Architecture: rendered by ActiveChat.svelte when notFoundPathStore is non-null.
     * Clears the store when the user acts so the normal welcome screen takes over.
     *
     * Test reference: tests/not-found-404-flow.spec.ts
     */
    import { text } from '@repo/ui';
    import { notFoundPathStore } from '../stores/notFoundPathStore';

    interface Props {
        onSearch: (query: string) => void;
        onAskAI: (message: string) => void;
    }

    let { onSearch, onAskAI }: Props = $props();

    const path = $derived($notFoundPathStore ?? '');

    // Full URL shown to the user (path only — we don't know the origin at build time)
    const displayUrl = $derived(path);

    function humanizePath(raw: string): string {
        const clean = raw.replace(/^\//, '').split('?')[0].split('#')[0];
        return clean.split('/').filter(Boolean).join(' ').replace(/[-_]/g, ' ');
    }

    function searchQuery(raw: string): string {
        const clean = raw.replace(/^\//, '').split('?')[0].split('#')[0];
        const segments = clean.split('/').filter(Boolean);
        return (segments.length > 1 ? segments[0] : segments.join(' ')).replace(/[-_]/g, ' ');
    }

    const topic = $derived(humanizePath(path));
    const query = $derived(searchQuery(path));

    // Copy URL feedback state
    let urlCopied = $state(false);
    let copyTimeout: ReturnType<typeof setTimeout> | null = null;

    function handleCopyUrl() {
        // Copy the full URL (path) to clipboard
        const fullUrl = typeof window !== 'undefined'
            ? window.location.origin + path
            : path;
        navigator.clipboard.writeText(fullUrl).then(() => {
            urlCopied = true;
            if (copyTimeout) clearTimeout(copyTimeout);
            copyTimeout = setTimeout(() => { urlCopied = false; }, 2000);
        });
    }

    function handleSearch() {
        onSearch(query);
    }

    function handleAskAI() {
        const message = $text('common.not_found.ask_ai_message', { values: { topic } });
        onAskAI(message);
    }
</script>

<div class="not-found-screen">
    <!-- ── Banner: server icon + "404" + "Page not found" ──────────────────── -->
    <div class="not-found-banner">
        <div class="banner-orbs" aria-hidden="true">
            <div class="orb orb-1"></div>
            <div class="orb orb-2"></div>
            <div class="orb orb-3"></div>
        </div>

        <div class="banner-content">
            <div class="banner-icon icon_server" aria-hidden="true"></div>
            <span class="banner-title">{$text('common.not_found.title')}</span>
            <p class="banner-summary">{$text('common.not_found.summary')}</p>
        </div>
    </div>

    <!-- ── Body: explanation + action buttons ─────────────────────────────── -->
    <div class="not-found-body">
        <div class="not-found-explanation">
            <p class="explanation-lead">{$text('common.not_found.explanation')}</p>
            <ul class="explanation-list">
                <li>
                    {$text('common.not_found.reason_typo')}:
                    <span class="url-chip">
                        <code class="url-text">{displayUrl}</code>
                        <button
                            class="copy-url-btn"
                            onclick={handleCopyUrl}
                            aria-label={$text('common.not_found.copy_url')}
                            title={$text('common.not_found.copy_url')}
                            type="button"
                        >
                            {#if urlCopied}
                                <span class="icon_check copy-icon" aria-hidden="true"></span>
                            {:else}
                                <span class="icon_copy copy-icon" aria-hidden="true"></span>
                            {/if}
                            {#if urlCopied}
                                <span class="copy-feedback">{$text('common.not_found.url_copied')}</span>
                            {/if}
                        </button>
                    </span>
                </li>
                <li>{$text('common.not_found.reason_removed')}</li>
            </ul>

            <p class="suggestion-heading">{$text('common.not_found.suggestion_heading')}</p>
            <p class="suggestion-body">{$text('common.not_found.suggestion_body')}</p>
        </div>

        <!-- Action buttons with "or" separator -->
        <div class="not-found-actions">
            <button class="action-btn action-btn-search" onclick={handleSearch} type="button">
                <span class="icon_search action-icon" aria-hidden="true"></span>
                {$text('common.not_found.search_label', { values: { query } })}
            </button>

            <span class="or-separator">{$text('common.not_found.or_separator')}</span>

            <button class="action-btn action-btn-chat" onclick={handleAskAI} type="button">
                <span class="icon_chat action-icon" aria-hidden="true"></span>
                {$text('common.not_found.ask_ai_label', { values: { topic } })}
            </button>
        </div>
    </div>
</div>

<style>
    /* ── Screen container ─────────────────────────────────────────────────── */

    .not-found-screen {
        display: flex;
        flex-direction: column;
        width: 100%;
        height: 100%;
        overflow-y: auto;
    }

    /* ── Banner ───────────────────────────────────────────────────────────── */

    .not-found-banner {
        position: relative;
        width: 100%;
        height: 240px;
        border-radius: 0 0 14px 14px;
        overflow: hidden;
        display: flex;
        align-items: center;
        justify-content: center;
        background: var(--color-primary);
        --orb-color-a: #4867cd;
        --orb-color-b: #a0beff;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
        pointer-events: none;
        user-select: none;
        flex-shrink: 0;
    }

    .banner-orbs {
        position: absolute;
        inset: 0;
        z-index: 0;
        pointer-events: none;
        overflow: hidden;
    }

    .orb {
        position: absolute;
        width: 480px;
        height: 420px;
        background: radial-gradient(
            ellipse at center,
            var(--orb-color-b) 0%,
            var(--orb-color-b) 40%,
            transparent 85%
        );
        filter: blur(28px);
        opacity: 0.55;
        will-change: transform, border-radius;
    }

    .orb-1 {
        top: -80px;
        left: -100px;
        animation: orbMorph1 11s ease-in-out infinite, orbDrift1 19s ease-in-out infinite;
    }

    .orb-2 {
        bottom: -120px;
        right: -120px;
        width: 460px;
        height: 400px;
        animation: orbMorph2 13s ease-in-out infinite, orbDrift2 23s ease-in-out infinite;
    }

    .orb-3 {
        top: -20px;
        left: 25%;
        width: 340px;
        height: 300px;
        opacity: 0.38;
        animation: orbMorph3 17s ease-in-out infinite, orbDrift3 29s ease-in-out infinite;
    }

    @media (prefers-reduced-motion: reduce) {
        .orb { animation: none !important; }
    }

    .banner-content {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 6px;
        z-index: 2;
        padding: 16px 24px;
        max-width: 480px;
        width: 100%;
        animation: fadeIn 0.35s ease-out;
    }

    @keyframes fadeIn {
        from { opacity: 0; }
        to   { opacity: 1; }
    }

    /* Server icon — white mask over transparent background */
    .banner-icon {
        width: 38px;
        height: 38px;
        flex-shrink: 0;
        background-color: rgba(255, 255, 255, 0.9) !important;
        background-image: none !important;
    }

    .banner-title {
        display: block;
        font-size: 20px;
        font-weight: 700;
        color: #ffffff;
        text-align: center;
        line-height: 1.3;
    }

    .banner-summary {
        margin: 2px 0 0;
        font-size: 14px;
        font-weight: 500;
        color: rgba(255, 255, 255, 0.9);
        line-height: 1.45;
        text-align: center;
    }

    @media (max-width: 730px) {
        .not-found-banner { height: 190px; }
        .banner-content { padding: 12px 20px; max-width: 360px; }
        .banner-icon { width: 32px; height: 32px; }
        .banner-title { font-size: 17px; }
        .banner-summary { font-size: 13px; }
    }

    /* ── Body ─────────────────────────────────────────────────────────────── */

    .not-found-body {
        display: flex;
        flex-direction: column;
        align-items: center;
        padding: 28px 24px 40px;
        max-width: 560px;
        width: 100%;
        margin: 0 auto;
        box-sizing: border-box;
        gap: 28px;
    }

    /* ── Explanation text ────────────────────────────────────────────────── */

    .not-found-explanation {
        display: flex;
        flex-direction: column;
        gap: 10px;
        width: 100%;
    }

    .explanation-lead,
    .suggestion-body {
        margin: 0;
        font-size: var(--font-size-p);
        color: var(--color-font-secondary);
        line-height: 1.6;
    }

    .explanation-list {
        margin: 0;
        padding-left: 20px;
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .explanation-list li {
        font-size: var(--font-size-p);
        color: var(--color-font-secondary);
        line-height: 1.6;
    }

    /* URL chip with copy button */
    .url-chip {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        margin-top: 4px;
        padding: 3px 8px 3px 10px;
        background: var(--color-grey-15);
        border: 1px solid var(--color-grey-25);
        border-radius: 8px;
        max-width: 100%;
        overflow: hidden;
    }

    .url-text {
        font-family: monospace;
        font-size: 0.85em;
        color: var(--color-font-primary);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 300px;
    }

    .copy-url-btn {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 2px 4px !important;
        min-width: unset !important;
        background: transparent !important;
        border: none !important;
        border-radius: 4px !important;
        cursor: pointer;
        color: var(--color-font-tertiary);
        transition: color 0.15s ease, background 0.15s ease;
        flex-shrink: 0;
        filter: none !important;
    }

    .copy-url-btn:hover {
        color: var(--color-font-primary) !important;
        background: var(--color-grey-20) !important;
        scale: none !important;
    }

    .copy-icon {
        width: 14px;
        height: 14px;
        display: block;
        opacity: 0.7;
    }

    .copy-feedback {
        font-size: 11px;
        color: var(--color-success, #4caf50);
        white-space: nowrap;
    }

    .suggestion-heading {
        margin: 6px 0 0;
        font-size: var(--font-size-p);
        font-weight: 600;
        color: var(--color-font-primary);
    }

    /* ── Action buttons ──────────────────────────────────────────────────── */

    .not-found-actions {
        display: flex;
        flex-direction: row;
        align-items: center;
        gap: 12px;
        width: 100%;
        flex-wrap: wrap;
        justify-content: center;
    }

    .action-btn {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 10px 20px;
        border-radius: 10px;
        font-size: var(--font-size-p);
        font-weight: 500;
        cursor: pointer;
        transition: background 0.15s ease, border-color 0.15s ease, transform 0.1s ease;
        white-space: nowrap;
    }

    .action-btn:active {
        transform: scale(0.97);
        filter: none !important;
    }

    /* Search — secondary style */
    .action-btn-search {
        background: var(--color-grey-15);
        border: 1.5px solid var(--color-grey-30);
        color: var(--color-font-primary);
    }

    .action-btn-search:hover {
        background: var(--color-grey-20) !important;
        border-color: var(--color-grey-40) !important;
        scale: none !important;
        filter: none !important;
    }

    /* Ask AI — primary style */
    .action-btn-chat {
        background: var(--color-primary);
        border: 1.5px solid var(--color-primary);
        color: #ffffff;
    }

    .action-btn-chat:hover {
        background: var(--color-primary-hover, var(--color-primary)) !important;
        opacity: 0.9;
        scale: none !important;
        filter: none !important;
    }

    .action-icon {
        width: 16px;
        height: 16px;
        flex-shrink: 0;
        opacity: 0.85;
    }

    .or-separator {
        font-size: var(--font-size-small, 13px);
        color: var(--color-font-tertiary);
        flex-shrink: 0;
    }

    @media (max-width: 500px) {
        .not-found-actions {
            flex-direction: column;
            align-items: stretch;
        }

        .action-btn {
            justify-content: center;
        }

        .or-separator {
            text-align: center;
        }
    }
</style>
