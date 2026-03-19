<script lang="ts">
    // frontend/packages/ui/src/components/Not404Screen.svelte
    /**
     * @file Not404Screen.svelte
     * @description Shown when a user lands on an unknown URL path. Provides two
     * recovery options: (1) open in-app search pre-filled with the first path
     * segment, (2) pre-fill the message input with a human-readable AI prompt
     * derived from the full failed path.
     *
     * Architecture: the parent ActiveChat.svelte renders this instead of the normal
     * welcome screen when notFoundPathStore is non-null. The screen calls
     * notFoundPathStore.set(null) to dismiss itself once the user acts.
     *
     * Data flow:
     *   unknown URL → vercel catch-all → SPA boot → +page.svelte detects pathname
     *   → notFoundPathStore.set(path) → ActiveChat shows Not404Screen
     *   → user clicks Search or Ask AI → action taken, store cleared
     */
    import ChatHeader from './ChatHeader.svelte';
    import { text } from '@repo/ui';
    import { notFoundPathStore } from '../stores/notFoundPathStore';

    interface Props {
        /** Called when the user picks the search option */
        onSearch: (query: string) => void;
        /** Called when the user picks the Ask AI option; receives the pre-filled message */
        onAskAI: (message: string) => void;
    }

    let { onSearch, onAskAI }: Props = $props();

    const path = $derived($notFoundPathStore ?? '');

    /**
     * Strips leading slash, query string and fragment from a URL path, then
     * replaces hyphens/underscores with spaces.
     * "/iphone-review" → "iphone review"
     * "/ai/image-generator?ref=x" → "ai image generator"
     */
    function humanizePath(raw: string): string {
        const clean = raw.replace(/^\//, '').split('?')[0].split('#')[0];
        return clean.split('/').filter(Boolean).join(' ').replace(/[-_]/g, ' ');
    }

    /**
     * For search: use the first path segment only when the path has multiple
     * segments. For single-segment paths the whole humanized string is used.
     * "/ai/image-generator" → "ai"
     * "/iphone-review"      → "iphone review"
     */
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
        const message = $text('common.not_found.ask_ai_message', { topic });
        onAskAI(message);
    }
</script>

<div class="not-found-screen">
    <ChatHeader
        title={$text('common.not_found.title')}
        summary={$text('common.not_found.summary')}
        isLoading={false}
        icon="alert-circle"
        category={null}
    />

    <div class="not-found-options">
        <!-- Option 1: Search -->
        <button class="not-found-option" onclick={handleSearch}>
            <span class="not-found-option-icon icon_search" aria-hidden="true"></span>
            <span class="not-found-option-label">
                {$text('common.not_found.search_label', { query })}
            </span>
        </button>

        <!-- Option 2: Ask AI -->
        <button class="not-found-option not-found-option-primary" onclick={handleAskAI}>
            <span class="not-found-option-icon icon_chat" aria-hidden="true"></span>
            <span class="not-found-option-label">
                {$text('common.not_found.ask_ai_label', { topic })}
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
