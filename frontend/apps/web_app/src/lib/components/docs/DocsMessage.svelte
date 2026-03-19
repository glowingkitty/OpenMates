<script lang="ts">
    /**
     * DocsMessage Component
     *
     * Renders documentation content styled as a single assistant chat message.
     * Uses ReadOnlyMessage for TipTap-based markdown rendering, wrapped in
     * the same visual structure as ChatMessage (avatar + sender name + bubble).
     *
     * Architecture: docs/architecture/docs-web-app.md
     * Test: N/A — visual component, tested via E2E
     */
    import { ReadOnlyMessage, text } from '@repo/ui';

    interface Props {
        /** Original markdown content to render via TipTap */
        content: string;
        /** Category for the avatar gradient (maps to mate-profile CSS classes) */
        category: string;
    }

    let { content, category }: Props = $props();
</script>

<div class="docs-message chat-message assistant">
    <div class="mate-profile {category}"></div>

    <div class="message-align-left">
        <div class="mate-message-content" role="article">
            <div class="chat-mate-name">{$text('documentation.sender_name')}</div>
            <div class="chat-message-text">
                <ReadOnlyMessage {content} role="assistant" selectable={true} />
            </div>
        </div>
    </div>
</div>

<style>
    .docs-message {
        padding: 0 1rem;
    }

    /* Override max-width for docs — content should use full available width */
    .docs-message :global(.message-align-left) {
        max-width: 100%;
    }

    /* Remove the speech bubble tail for docs — cleaner look for long content */
    .docs-message :global(.mate-message-content::before) {
        display: none;
    }

    /* Remove drop shadow on docs content for a flatter reading experience */
    .docs-message :global(.mate-message-content) {
        filter: none;
        margin-inline-end: 0;
    }
</style>
