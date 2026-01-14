<!--
  ThinkingSection.svelte
  
  Displays AI thinking/reasoning content from thinking models (Gemini, Anthropic Claude, etc.)
  
  Features:
  - Collapsed by default showing "Thinking..." or "Thought process"
  - Expandable to show full thinking content
  - Streaming support with animated loader
  - Uses ReadOnlyMessage for markdown rendering
  
  Props:
  - thinkingContent: The thinking markdown content
  - isStreaming: Whether thinking is currently streaming
  - isExpanded: Whether the section is expanded (bindable)
-->
<script lang="ts">
    import { slide } from 'svelte/transition';
    import ReadOnlyMessage from './ReadOnlyMessage.svelte';
    import Icon from './Icon.svelte';
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
            <div class="thinking-icon-wrapper" class:spinning={isStreaming}>
                <Icon name={isStreaming ? 'loader-2' : 'brain'} size="16" />
            </div>
            <span class="thinking-summary">{collapsedSummary}</span>
            <div class="expand-icon">
                <Icon name={isExpanded ? 'chevron-up' : 'chevron-down'} size="16" />
            </div>
        </button>
        
        <!-- Expanded Content -->
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
        transition: border-color 0.2s ease;
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
        transition: background-color 0.15s ease;
    }
    
    .thinking-header:hover {
        background: var(--color-surface-hover, rgba(0, 0, 0, 0.04));
    }
    
    .thinking-header:focus {
        outline: none;
        box-shadow: inset 0 0 0 2px var(--color-accent-primary, #3b82f6);
    }
    
    .thinking-icon-wrapper {
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0.7;
        color: var(--color-text-tertiary, #888);
    }
    
    .thinking-icon-wrapper.spinning {
        animation: spin 1s linear infinite;
        color: var(--color-accent-secondary, #6366f1);
        opacity: 1;
    }
    
    .thinking-summary {
        flex: 1;
        font-weight: 500;
    }
    
    .expand-icon {
        display: flex;
        align-items: center;
        justify-content: center;
        opacity: 0.5;
        transition: opacity 0.15s ease;
    }
    
    .thinking-header:hover .expand-icon {
        opacity: 0.8;
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
    
    @keyframes spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
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
</style>
