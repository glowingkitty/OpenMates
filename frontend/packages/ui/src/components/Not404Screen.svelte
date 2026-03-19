<script lang="ts">
    // frontend/packages/ui/src/components/Not404Screen.svelte
    /**
     * @file Not404Screen.svelte
     * @description 404 not-found screen with self-contained banner (title + summary)
     * and two recovery options: search and ask AI.
     *
     * Uses a self-contained banner instead of ChatHeader because ChatHeader requires
     * category!=null to render the loaded state (title/summary/icon). This avoids
     * that dependency while matching the same visual language (primary gradient,
     * same dimensions, same text styles, same orb animation).
     *
     * Test reference: tests/not-found-404-flow.spec.ts
     */
    import { text } from '@repo/ui';
    import { getLucideIcon } from '../utils/categoryUtils';

    const MapPinOff = getLucideIcon('map-pin-off');
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

    function handleSearch() {
        onSearch(query);
    }

    function handleAskAI() {
        const message = $text('common.not_found.ask_ai_message', { values: { topic } });
        onAskAI(message);
    }
</script>

<div class="not-found-screen">
    <div class="not-found-banner">
        <div class="banner-orbs" aria-hidden="true">
            <div class="orb orb-1"></div>
            <div class="orb orb-2"></div>
            <div class="orb orb-3"></div>
        </div>

        <div class="banner-content">
            <div class="banner-icon" aria-hidden="true">
                {#if MapPinOff}
                    <MapPinOff size={38} color="rgba(255,255,255,0.9)" />
                {/if}
            </div>
            <span class="banner-title">{$text('common.not_found.title')}</span>
            <p class="banner-summary">{$text('common.not_found.summary')}</p>
        </div>
    </div>

    <div class="not-found-options">
        <button class="not-found-option" onclick={handleSearch}>
            <span class="not-found-option-icon icon_search" aria-hidden="true"></span>
            <span class="not-found-option-label">
                {$text('common.not_found.search_label', { values: { query } })}
            </span>
        </button>

        <button class="not-found-option not-found-option-primary" onclick={handleAskAI}>
            <span class="not-found-option-icon icon_chat" aria-hidden="true"></span>
            <span class="not-found-option-label">
                {$text('common.not_found.ask_ai_label', { values: { topic } })}
            </span>
        </button>
    </div>
</div>

<style>
    .not-found-screen {
        display: flex;
        flex-direction: column;
        width: 100%;
        height: 100%;
        overflow: hidden;
    }

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
        animation:
            orbMorph1 11s ease-in-out infinite,
            orbDrift1 19s ease-in-out infinite;
    }

    .orb-2 {
        bottom: -120px;
        right: -120px;
        width: 460px;
        height: 400px;
        animation:
            orbMorph2 13s ease-in-out infinite,
            orbDrift2 23s ease-in-out infinite;
    }

    .orb-3 {
        top: -20px;
        left: 25%;
        width: 340px;
        height: 300px;
        opacity: 0.38;
        animation:
            orbMorph3 17s ease-in-out infinite,
            orbDrift3 29s ease-in-out infinite;
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

    .banner-icon {
        width: 38px;
        height: 38px;
        flex-shrink: 0;
        display: flex;
        align-items: center;
        justify-content: center;
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
        .not-found-banner {
            height: 190px;
        }

        .banner-content {
            padding: 12px 20px;
            max-width: 360px;
        }

        .banner-icon {
            width: 32px;
            height: 32px;
        }

        .banner-icon :global(svg) {
            width: 32px !important;
            height: 32px !important;
        }

        .banner-title {
            font-size: 17px;
        }

        .banner-summary {
            font-size: 13px;
        }
    }

    .not-found-options {
        display: flex;
        flex-direction: column;
        gap: 12px;
        padding: 32px 24px;
        max-width: 480px;
        width: 100%;
        margin: 0 auto;
        box-sizing: border-box;
    }

    .not-found-option {
        display: flex;
        align-items: center;
        gap: 14px;
        padding: 18px 20px;
        border-radius: 14px;
        border: 1.5px solid var(--color-grey-25);
        background: var(--color-grey-10);
        color: var(--color-font-primary);
        cursor: pointer;
        text-align: left;
        font-size: var(--font-size-p);
        transition: background 0.15s ease, border-color 0.15s ease, transform 0.1s ease;
        width: 100%;
        box-sizing: border-box;
    }

    .not-found-option:hover {
        background: var(--color-grey-15);
        border-color: var(--color-grey-35);
        transform: translateY(-1px);
    }

    .not-found-option:active {
        transform: translateY(0);
    }

    .not-found-option-primary {
        border-color: var(--color-primary-20, var(--color-primary));
        background: var(--color-primary-5, var(--color-grey-10));
    }

    .not-found-option-primary:hover {
        background: var(--color-primary-10, var(--color-grey-15));
        border-color: var(--color-primary);
    }

    .not-found-option-icon {
        flex-shrink: 0;
        width: 20px;
        height: 20px;
        opacity: 0.75;
    }

    .not-found-option-label {
        font-size: var(--font-size-p);
        color: var(--color-font-primary);
        line-height: 1.3;
        word-break: break-word;
    }
</style>
