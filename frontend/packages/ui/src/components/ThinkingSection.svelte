<!--
  ThinkingSection.svelte
  
  Displays AI thinking/reasoning content from thinking models (Gemini, Anthropic Claude, etc.)
  
  Features:
  - Shows last 3 lines of thinking as preview while streaming (gives user glimpse of activity)
  - Once streaming completes, preview is hidden (collapsed by default)
  - Expandable to show full thinking content when clicked
  - Streaming support with shimmer animation on icon and text
  - Uses ReadOnlyMessage for markdown rendering
  
  Visual Design:
  - reasoning.svg icon on the left with shimmer during streaming
  - "Thinking..." text during streaming, "Thought process" when done
  - Last 3 lines preview shown below header during streaming
  - dropdown.svg icon on the right that rotates 180° when expanded
  - Hover color change to indicate clickability (when not streaming)
  
  Props:
  - thinkingContent: The thinking markdown content
  - isStreaming: Whether thinking is currently streaming
  - isExpanded: Whether the section is expanded (bindable)
-->
<script lang="ts">
    import { slide } from 'svelte/transition';
    import ReadOnlyMessage from './ReadOnlyMessage.svelte';
    import { parse_message } from '../message_parsing/parse_message';
    
    // Props using Svelte 5 runes mode
    let {
        thinkingContent = '',
        isStreaming = false,
        isExpanded = $bindable(false)
    }: {
        thinkingContent: string;
        isStreaming: boolean;
        isExpanded?: boolean;
    } = $props();
    
    // Generate summary text for collapsed state
    const collapsedSummary = $derived(
        isStreaming ? 'Thinking...' : 'Thought process'
    );
    
    // Parse thinking content for display (plain markdown, no embeds)
    // Memoize to avoid re-parsing on every render
    const parsedThinkingContent = $derived.by(() => {
        if (!thinkingContent) return null;
        try {
            return parse_message(thinkingContent, 'read', { unifiedParsingEnabled: true });
        } catch (error) {
            console.error('[ThinkingSection] Error parsing thinking content:', error);
            return null;
        }
    });
    
    // Track if we have content to show
    const hasContent = $derived(!!thinkingContent && thinkingContent.length > 0);
    
    // Extract the last 3 lines for streaming preview
    // This gives users a glimpse of what the model is thinking while processing
    const last3Lines = $derived.by(() => {
        if (!thinkingContent || !isStreaming) return null;
        
        // Split by newlines and filter out empty lines
        const lines = thinkingContent.split('\n').filter(line => line.trim().length > 0);
        
        if (lines.length === 0) return null;
        
        // Get the last 3 non-empty lines
        const lastLines = lines.slice(-3);
        return lastLines.join('\n');
    });
    
    // Parse the last 3 lines for preview display during streaming
    const parsedPreviewContent = $derived.by(() => {
        if (!last3Lines) return null;
        try {
            return parse_message(last3Lines, 'read', { unifiedParsingEnabled: true });
        } catch (error) {
            console.error('[ThinkingSection] Error parsing preview content:', error);
            return null;
        }
    });
    
    function toggleExpanded() {
        isExpanded = !isExpanded;
    }
</script>

{#if hasContent || isStreaming}
    <div class="thinking-section" class:streaming={isStreaming} class:expanded={isExpanded}>
        <!-- Collapsed Header (always visible) -->
        <button 
            class="thinking-header"
            onclick={toggleExpanded}
            aria-expanded={isExpanded}
            aria-label={isExpanded ? 'Collapse thought process' : 'Expand thought process'}
        >
            <!-- Reasoning icon with shimmer during streaming -->
            <div class="thinking-icon" class:shimmer={isStreaming}></div>
            
            <!-- Summary text with shimmer during streaming -->
            <span class="thinking-summary" class:shimmer={isStreaming}>{collapsedSummary}</span>
            
            <!-- Dropdown icon that rotates when expanded -->
            <div class="expand-icon" class:rotated={isExpanded}></div>
        </button>
        
        <!-- Streaming Preview: Show last 3 lines while processing -->
        {#if isStreaming && parsedPreviewContent && !isExpanded}
            <div class="thinking-preview" transition:slide={{ duration: 150 }}>
                <ReadOnlyMessage 
                    content={parsedPreviewContent}
                    isStreaming={true}
                />
            </div>
        {/if}
        
        <!-- Expanded Content: Full thinking content when user clicks to expand -->
        {#if isExpanded && parsedThinkingContent}
            <div class="thinking-content" transition:slide={{ duration: 200 }}>
                <ReadOnlyMessage 
                    content={parsedThinkingContent}
                    isStreaming={isStreaming}
                />
            </div>
        {/if}
    </div>
{/if}

<style>
    .thinking-section {
        margin-bottom: 12px;
        border-radius: 8px;
        background: var(--color-surface-secondary, rgba(0, 0, 0, 0.03));
        border: 1px solid var(--color-border-subtle, rgba(0, 0, 0, 0.08));
        overflow: hidden;
        transition: border-color 0.2s ease, background-color 0.2s ease;
    }
    
    .thinking-section.streaming {
        border-color: var(--color-accent-secondary, #6366f1);
    }
    
    .thinking-section.expanded {
        background: var(--color-grey-20);
    }
    
    .thinking-header {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 10px 14px;
        width: 100%;
        background: transparent;
        border: none;
        cursor: pointer;
        color: var(--color-text-secondary, #666);
        font-size: 13px;
        font-family: inherit;
        text-align: left;
        transition: background-color 0.15s ease, color 0.15s ease;
    }
    
    .thinking-header:hover {
        background: var(--color-surface-hover, rgba(0, 0, 0, 0.04));
        color: var(--color-primary, #007aff);
    }
    
    .thinking-header:hover .thinking-icon:not(.shimmer) {
        background-color: var(--color-primary, #007aff);
    }
    
    .thinking-header:hover .expand-icon {
        background-color: var(--color-primary, #007aff);
    }
    
    .thinking-header:focus {
        outline: none;
        box-shadow: inset 0 0 0 2px var(--color-accent-primary, #3b82f6);
    }
    
    /* Reasoning icon using mask-image */
    .thinking-icon {
        width: 18px;
        height: 18px;
        flex-shrink: 0;
        background-color: var(--color-text-tertiary, #888);
        -webkit-mask-image: url('@openmates/ui/static/icons/reasoning.svg');
        mask-image: url('@openmates/ui/static/icons/reasoning.svg');
        -webkit-mask-size: contain;
        mask-size: contain;
        -webkit-mask-position: center;
        mask-position: center;
        -webkit-mask-repeat: no-repeat;
        mask-repeat: no-repeat;
        transition: background-color 0.15s ease;
    }
    
    /* Shimmer animation for streaming state */
    .thinking-icon.shimmer {
        background: linear-gradient(
            90deg,
            var(--color-grey-70) 0%,
            var(--color-grey-70) 30%,
            var(--color-grey-50) 50%,
            var(--color-grey-70) 70%,
            var(--color-grey-70) 100%
        );
        background-size: 200% 100%;
        animation: shimmer 1.5s infinite linear;
        /* Preserve mask while animating background */
    }
    
    .thinking-summary {
        flex: 1;
        font-weight: 500;
        transition: color 0.15s ease;
    }
    
    /* Shimmer animation for summary text during streaming */
    .thinking-summary.shimmer {
        background: linear-gradient(
            90deg,
            var(--color-grey-70) 0%,
            var(--color-grey-70) 30%,
            var(--color-grey-50) 50%,
            var(--color-grey-70) 70%,
            var(--color-grey-70) 100%
        );
        background-size: 200% 100%;
        background-clip: text;
        -webkit-background-clip: text;
        color: transparent;
        animation: shimmer 1.5s infinite linear;
    }
    
    /* Dropdown expand icon using mask-image */
    .expand-icon {
        width: 16px;
        height: 16px;
        flex-shrink: 0;
        background-color: var(--color-text-tertiary, #888);
        -webkit-mask-image: url('@openmates/ui/static/icons/dropdown.svg');
        mask-image: url('@openmates/ui/static/icons/dropdown.svg');
        -webkit-mask-size: contain;
        mask-size: contain;
        -webkit-mask-position: center;
        mask-position: center;
        -webkit-mask-repeat: no-repeat;
        mask-repeat: no-repeat;
        transition: transform 0.2s ease, background-color 0.15s ease;
    }
    
    /* Rotate dropdown icon when expanded */
    .expand-icon.rotated {
        transform: rotate(180deg);
    }
    
    /* Streaming preview: shows last 3 lines while processing */
    .thinking-preview {
        padding: 8px 14px 12px;
        border-top: 1px solid var(--color-border-subtle, rgba(0, 0, 0, 0.08));
        font-size: 13px;
        line-height: 1.5;
        color: var(--color-text-tertiary, #777);
        max-height: 80px;
        overflow: hidden;
        position: relative;
    }
    
    /* Fade effect at the top of preview to indicate there's more content above */
    .thinking-preview::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 20px;
        background: linear-gradient(
            to bottom,
            var(--color-surface-secondary, rgba(0, 0, 0, 0.03)) 0%,
            transparent 100%
        );
        pointer-events: none;
        z-index: 1;
    }
    
    /* Override ReadOnlyMessage styles for preview */
    .thinking-preview :global(.tiptap-editor) {
        font-size: 12px;
        opacity: 0.75;
    }
    
    .thinking-content {
        padding: 0 14px 14px;
        border-top: 1px solid var(--color-border-subtle, rgba(0, 0, 0, 0.08));
        font-size: 14px;
        line-height: 1.6;
        color: var(--color-text-secondary, #555);
    }
    
    /* Override ReadOnlyMessage styles for thinking content */
    .thinking-content :global(.tiptap-editor) {
        font-size: 13px;
        opacity: 0.85;
    }
    
    /* Shimmer animation keyframes */
    @keyframes shimmer {
        0% {
            background-position: 200% 0;
        }
        100% {
            background-position: -200% 0;
        }
    }
    
    /* Dark mode support */
    :global(.dark) .thinking-section {
        background: var(--color-surface-secondary, rgba(255, 255, 255, 0.03));
        border-color: var(--color-border-subtle, rgba(255, 255, 255, 0.1));
    }
    
    :global(.dark) .thinking-section.expanded {
        background: var(--color-surface-primary, #1a1a1a);
    }
    
    :global(.dark) .thinking-header {
        color: var(--color-text-secondary, #aaa);
    }
    
    :global(.dark) .thinking-header:hover {
        background: var(--color-surface-hover, rgba(255, 255, 255, 0.05));
    }
    
    :global(.dark) .thinking-content {
        border-color: var(--color-border-subtle, rgba(255, 255, 255, 0.1));
        color: var(--color-text-secondary, #bbb);
    }
    
    :global(.dark) .thinking-preview {
        border-color: var(--color-border-subtle, rgba(255, 255, 255, 0.1));
        color: var(--color-text-tertiary, #888);
    }
    
    :global(.dark) .thinking-preview::before {
        background: linear-gradient(
            to bottom,
            var(--color-surface-secondary, rgba(255, 255, 255, 0.03)) 0%,
            transparent 100%
        );
    }
</style>
