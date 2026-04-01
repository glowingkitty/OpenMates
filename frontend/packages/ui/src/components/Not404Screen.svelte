<script lang="ts">
    // frontend/packages/ui/src/components/Not404Screen.svelte
    /**
     * @file Not404Screen.svelte
     * @description 404 not-found screen. Shows a branded banner (server icon floating
     * at edges + centered icon/title/summary) followed by an explanation section and
     * two standard orange <button> elements with icons, separated by an "or" line.
     *
     * Architecture: rendered by ActiveChat.svelte when notFoundPathStore is non-null.
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

    let urlCopied = $state(false);
    let copyTimeout: ReturnType<typeof setTimeout> | null = null;

    function handleCopyUrl() {
        const fullUrl = typeof window !== 'undefined' ? window.location.origin + path : path;
        navigator.clipboard.writeText(fullUrl).then(() => {
            urlCopied = true;
            if (copyTimeout) clearTimeout(copyTimeout);
            copyTimeout = setTimeout(() => { urlCopied = false; }, 2000);
        });
    }

    function handleSearch() { onSearch(query); }

    function handleAskAI() {
        const message = $text('common.not_found.ask_ai_message', { values: { topic } });
        onAskAI(message);
    }
</script>

<div class="not-found-screen" data-testid="not-found-screen">
    <!-- Banner: matches ChatHeader visual language exactly -->
    <div class="not-found-banner">
        <!-- Living gradient orbs -->
        <div class="banner-orbs" aria-hidden="true">
            <div class="orb orb-1"></div>
            <div class="orb orb-2"></div>
            <div class="orb orb-3"></div>
        </div>

        <!-- Decorative floating server icons at edges (126×126px, same as ChatHeader) -->
        <div class="deco-icon deco-icon-left icon_server" aria-hidden="true"></div>
        <div class="deco-icon deco-icon-right icon_server" aria-hidden="true"></div>

        <!-- Centered content: small server icon + title + summary -->
        <div class="banner-content">
            <div class="banner-icon icon_server" aria-hidden="true"></div>
            <span class="banner-title" data-testid="banner-title">{$text('common.not_found.title')}</span>
            <p class="banner-summary">{$text('common.not_found.summary')}</p>
        </div>
    </div>

    <!-- Body: explanation + action buttons -->
    <div class="not-found-body">
        <div class="not-found-explanation">
            <p class="explanation-lead">{$text('common.not_found.explanation')}</p>
            <ul class="explanation-list">
                <li>
                    {$text('common.not_found.reason_typo')}:
                    <span class="url-chip">
                        <code class="url-text">{path}</code>
                        <button
                            class="copy-url-btn"
                            onclick={handleCopyUrl}
                            aria-label={$text('common.not_found.copy_url')}
                            title={$text('common.not_found.copy_url')}
                            type="button"
                        >
                            <span
                                class:copy-icon-check={urlCopied}
                                class:copy-icon-copy={!urlCopied}
                                class="copy-icon"
                                aria-hidden="true"
                            ></span>
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

        <!-- Stacked buttons with "or" separator line between them -->
        <div class="not-found-actions" data-testid="not-found-actions">
            <button onclick={handleSearch} type="button">
                <span class="btn-icon btn-icon-search" aria-hidden="true"></span>
                {$text('common.not_found.search_label', { values: { query } })}
            </button>

            <span class="or-separator">{$text('common.not_found.or_separator')}</span>

            <button onclick={handleAskAI} type="button">
                <span class="btn-icon btn-icon-chat" aria-hidden="true"></span>
                {$text('common.not_found.ask_ai_label', { values: { topic } })}
            </button>
        </div>
    </div>
</div>

<style>
    /* ── Screen ───────────────────────────────────────────────────────────── */

    .not-found-screen {
        display: flex;
        flex-direction: column;
        width: 100%;
        height: 100%;
        overflow-y: auto;
    }

    /* ── Banner: mirrors ChatHeader dimensions exactly ────────────────────── */

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

    /* ── Orbs ─────────────────────────────────────────────────────────────── */

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

    .orb-1 { top: -80px; left: -100px; animation: orbMorph1 11s ease-in-out infinite, orbDrift1 19s ease-in-out infinite; }
    .orb-2 { bottom: -120px; right: -120px; width: 460px; height: 400px; animation: orbMorph2 13s ease-in-out infinite, orbDrift2 23s ease-in-out infinite; }
    .orb-3 { top: -20px; left: 25%; width: 340px; height: 300px; opacity: 0.38; animation: orbMorph3 17s ease-in-out infinite, orbDrift3 29s ease-in-out infinite; }

    @media (prefers-reduced-motion: reduce) {
        .orb { animation: none !important; }
    }

    /* ── Decorative floating server icons (126×126, same as ChatHeader) ──── */

    .deco-icon {
        position: absolute;
        width: 126px;
        height: 126px;
        z-index: 1;
        pointer-events: none;
        --float-rx: 10px;
        --float-ry: 12px;
        /* White icon via CSS mask — override icon_server's background-image */
        background-color: rgba(255, 255, 255, 0.2) !important;
        background-image: none !important;
        animation:
            decoEnter 0.6s ease-out 0.1s both,
            decoFloat 16s linear 0.7s infinite;
    }

    .deco-icon-left {
        left: calc(50% - 240px - 106px);
        bottom: -15px;
        --deco-rotate: -15deg;
    }

    .deco-icon-right {
        right: calc(50% - 240px - 106px);
        bottom: -15px;
        --deco-rotate: 15deg;
        animation-delay: 0.1s, -8s;
    }

    @media (prefers-reduced-motion: reduce) {
        .deco-icon { animation: decoEnter 0.6s ease-out 0.1s both !important; }
    }

    /* ── Centered banner content ──────────────────────────────────────────── */

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

    @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

    /* Small server icon: white mask, 38×38px (same as ChatHeader loaded-icon) */
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
        .deco-icon { width: 90px; height: 90px; }
        .deco-icon-left { left: calc(50% - 180px - 70px); }
        .deco-icon-right { right: calc(50% - 180px - 70px); }
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
        gap: 24px;
    }

    /* ── Explanation ──────────────────────────────────────────────────────── */

    .not-found-explanation {
        display: flex;
        flex-direction: column;
        gap: 10px;
        width: 100%;
    }

    .explanation-lead, .suggestion-body {
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

    .url-chip {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        margin-top: 4px;
        padding: 3px 6px 3px 10px;
        background: var(--color-grey-15);
        border: 1px solid var(--color-grey-25);
        border-radius: 8px;
    }

    .url-text {
        font-family: monospace;
        font-size: 0.85em;
        color: var(--color-font-primary);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 280px;
    }

    /* Override global button styles for the tiny copy button */
    .copy-url-btn {
        display: inline-flex !important;
        align-items: center !important;
        gap: 4px !important;
        padding: 2px 5px !important;
        min-width: unset !important;
        background: transparent !important;
        background-color: transparent !important;
        border: none !important;
        border-radius: 4px !important;
        box-shadow: none !important;
        filter: none !important;
        cursor: pointer !important;
        color: var(--color-font-tertiary) !important;
        transition: background 0.15s ease !important;
        flex-shrink: 0 !important;
    }

    .copy-url-btn:hover {
        background-color: var(--color-grey-20) !important;
        scale: none !important;
        filter: none !important;
    }

    .copy-url-btn:active {
        scale: none !important;
        filter: none !important;
    }

    .copy-icon {
        width: 14px !important;
        height: 14px !important;
        display: block;
        flex-shrink: 0;
        -webkit-mask-size: contain;
        mask-size: contain;
        -webkit-mask-repeat: no-repeat;
        mask-repeat: no-repeat;
        -webkit-mask-position: center;
        mask-position: center;
        background-color: var(--color-grey-70) !important;
        background-image: none !important;
    }

    .copy-icon-copy {
        -webkit-mask-image: url('@openmates/ui/static/icons/copy.svg');
        mask-image: url('@openmates/ui/static/icons/copy.svg');
    }

    .copy-icon-check {
        -webkit-mask-image: url('@openmates/ui/static/icons/check.svg');
        mask-image: url('@openmates/ui/static/icons/check.svg');
        background-color: var(--color-success, #4caf50) !important;
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

    /* ── Action buttons: stacked column, "or" as full-width separator line ── */

    .not-found-actions {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 0;
        width: 100%;
        max-width: 420px;
    }

    /* The two <button> elements inherit the global orange button style.
       We only need to set width + flex layout for the icon+label inside. */
    .not-found-actions button {
        width: 100%;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        gap: 10px !important;
    }

    .btn-icon {
        width: 20px;
        height: 20px;
        flex-shrink: 0;
        display: block;
        -webkit-mask-size: contain;
        mask-size: contain;
        -webkit-mask-repeat: no-repeat;
        mask-repeat: no-repeat;
        -webkit-mask-position: center;
        mask-position: center;
        /* Buttons are orange; icons need to be white */
        background-color: #ffffff !important;
        background-image: none !important;
    }

    .btn-icon-search {
        -webkit-mask-image: url('@openmates/ui/static/icons/search.svg');
        mask-image: url('@openmates/ui/static/icons/search.svg');
    }

    .btn-icon-chat {
        -webkit-mask-image: url('@openmates/ui/static/icons/chat.svg');
        mask-image: url('@openmates/ui/static/icons/chat.svg');
    }

    .or-separator {
        display: block;
        width: 100%;
        text-align: center;
        font-size: var(--font-size-small, 13px);
        color: var(--color-font-tertiary);
        padding: 4px 0;
    }
</style>
