<!--
  ThinkingSection.svelte
  
  Displays AI thinking/reasoning content from thinking models (Gemini, Anthropic Claude, etc.)
  
  Features:
  - Auto-expands while streaming so the user sees thinking content as it arrives
  - Auto-collapses when streaming completes (collapsed by default for finished thinking)
  - User can manually toggle expand/collapse at any time (respected during streaming)
  - Auto-scrolls content to the bottom as new chunks arrive
  - Grey border highlight while streaming (clearly signals "thinking in progress")
  - Uses ReadOnlyMessage for markdown rendering
  - All user-facing text is i18n-translated

  Visual Design:
  - reasoning.svg icon on the left
  - Translated "Thinking..." text during streaming, "Thought process" when done
  - Subtle grey border while streaming
  - dropdown.svg icon on the right that rotates 180° when expanded
  - Hover color change to indicate clickability
  
  Props:
  - thinkingContent: The thinking markdown content
  - isStreaming: Whether thinking is currently streaming
  - isExpanded: Whether the section is expanded (bindable)
-->
<script lang="ts">
    import { slide } from 'svelte/transition';
    import { onMount, tick } from 'svelte';
    import ReadOnlyMessage from './ReadOnlyMessage.svelte';
    import { parse_message } from '../message_parsing/parse_message';
    import type { PIIMapping } from '../types/chat';
    import { text } from '@repo/ui'; // For i18n translations
    
    // Props using Svelte 5 runes mode
    let {
        thinkingContent = '',
        isStreaming = false,
        isExpanded = $bindable(false),
        chatId, piiMappings, piiRevealed = false
    }: {
        thinkingContent: string;
        isStreaming: boolean;
        isExpanded?: boolean;
        chatId?: string;
        piiMappings?: PIIMapping[];
        piiRevealed?: boolean;
    } = $props();

    // DOM ref for the content scroll container — used to auto-scroll to bottom
    let contentEl = $state<HTMLDivElement | null>(null);
    let prefersReducedMotion = $state(false);

    onMount(() => {
        const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
        const updateMotionPreference = () => {
            prefersReducedMotion = motionQuery.matches;
        };
        updateMotionPreference();
        motionQuery.addEventListener('change', updateMotionPreference);
        return () => motionQuery.removeEventListener('change', updateMotionPreference);
    });
    
    // Auto-expand while streaming so the user sees thinking content (or placeholder)
    // as it arrives. When streaming finishes, collapse automatically.
    // The user can still toggle manually at any time.
    let userToggledWhileStreaming = $state(false);
    
    $effect(() => {
        if (isStreaming && !userToggledWhileStreaming) {
            isExpanded = true;
        }
        if (!isStreaming) {
            // Streaming ended — collapse and reset the toggle flag for next time
            if (!userToggledWhileStreaming) {
                isExpanded = false;
            }
            userToggledWhileStreaming = false;
        }
    });
    
    // Generate summary text for collapsed state (i18n)
    const collapsedSummary = $derived(
        isStreaming ? $text('chat.thinking.header_streaming') : $text('chat.thinking.header_done')
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
    
    // (Preview extraction removed — content is now always shown expanded during streaming)

    // Auto-scroll the content container to the bottom whenever content changes while streaming.
    // This ensures the user always sees the newest lines as they arrive.
    $effect(() => {
        void thinkingContent; // track dependency — re-run on every new chunk

        if (!isStreaming || !contentEl) return;

        // Wait for the DOM to update after content change before scrolling
        tick().then(() => {
            if (contentEl) {
                contentEl.scrollTo({
                    top: contentEl.scrollHeight,
                    behavior: prefersReducedMotion ? 'auto' : 'smooth'
                });
            }
        });
    });
    
    function toggleExpanded() {
        isExpanded = !isExpanded;
        if (isStreaming) {
            userToggledWhileStreaming = true;
        }
    }
</script>

{#if hasContent || isStreaming}
    <div class="thinking-section" data-testid="thinking-section" class:streaming={isStreaming} class:expanded={isExpanded}>
        <!-- Collapsed Header (always visible) -->
        <button 
            class="thinking-header"
            data-testid="thinking-header"
            onclick={toggleExpanded}
            aria-expanded={isExpanded}
            aria-label={isExpanded ? $text('chat.thinking.collapse') : $text('chat.thinking.expand')}
        >
            <!-- Reasoning icon -->
            <div class="thinking-icon"></div>
            
            <!-- Summary text -->
            <span class="thinking-summary">{collapsedSummary}</span>
            
            <!-- Dropdown icon that rotates when expanded -->
            <div class="expand-icon" class:rotated={isExpanded}></div>
        </button>
        
        <!-- Expanded Content: Full thinking content visible while streaming or when user expands -->
        {#if isExpanded && parsedThinkingContent}
            <div
                class="thinking-content"
                data-testid="thinking-content"
                class:streaming-content={isStreaming}
                bind:this={contentEl}
                transition:slide={{ duration: prefersReducedMotion ? 0 : 200 }}
            >
                <ReadOnlyMessage 
                    content={parsedThinkingContent}
                    isStreaming={isStreaming} role="assistant" {chatId} {piiMappings} {piiRevealed}
                />
            </div>
        {/if}
    </div>
{/if}

<style>
    .thinking-section {
        margin-bottom: var(--spacing-6);
        border-radius: var(--radius-3);
        background: var(--color-grey-10);
        border: 1px solid var(--color-grey-25);
        overflow: hidden;
        position: relative;
        transition: background-color var(--duration-normal) var(--easing-default);
    }

    .thinking-section.streaming {
        border-color: var(--color-grey-20);
    }
    
    .thinking-section.expanded {
        background: var(--color-grey-20);
    }

    .thinking-header {
        display: flex;
        align-items: center;
        gap: var(--spacing-4);
        padding: 10px 14px;
        width: 100%;
        background: transparent;
        border: none;
        cursor: pointer;
        color: var(--color-font-secondary);
        font-size: var(--font-size-xs);
        font-family: inherit;
        text-align: left;
        transition: background-color var(--duration-fast) var(--easing-default), color var(--duration-fast) var(--easing-default);
    }
    
    .thinking-header:hover {
        background: var(--color-grey-20);
        color: var(--color-primary-start);
    }
    
    .thinking-header:hover .thinking-icon {
        background-color: var(--color-primary-start);
    }
    
    .thinking-header:hover .expand-icon {
        background-color: var(--color-primary-start);
    }
    
    .thinking-header:focus {
        box-shadow: inset 0 0 0 2px var(--color-button-primary);
    }
    
    /* Reasoning icon using mask-image */
    .thinking-icon {
        width: 18px;
        height: 18px;
        flex-shrink: 0;
        background-color: var(--color-font-tertiary);
        -webkit-mask-image: var(--icon-url-reasoning);
        mask-image: var(--icon-url-reasoning);
        -webkit-mask-size: contain;
        mask-size: contain;
        -webkit-mask-position: center;
        mask-position: center;
        -webkit-mask-repeat: no-repeat;
        mask-repeat: no-repeat;
        transition: background-color var(--duration-fast) var(--easing-default);
    }
    
    .thinking-summary {
        flex: 1;
        font-weight: 500;
        transition: color var(--duration-fast) var(--easing-default);
    }
    
    /* Dropdown expand icon using mask-image */
    .expand-icon {
        width: 16px;
        height: 16px;
        flex-shrink: 0;
        background-color: var(--color-font-tertiary);
        -webkit-mask-image: var(--icon-url-dropdown);
        mask-image: var(--icon-url-dropdown);
        -webkit-mask-size: contain;
        mask-size: contain;
        -webkit-mask-position: center;
        mask-position: center;
        -webkit-mask-repeat: no-repeat;
        mask-repeat: no-repeat;
        transition: transform var(--duration-normal) var(--easing-default), background-color var(--duration-fast) var(--easing-default);
    }
    
    /* Rotate dropdown icon when expanded */
    .expand-icon.rotated {
        transform: rotate(180deg);
    }
    
    .thinking-content {
        padding: 0 14px 14px;
        border-top: 1px solid var(--color-grey-25);
        font-size: var(--font-size-small);
        line-height: 1.6;
        color: var(--color-font-secondary);
    }
    
    /* While streaming, cap the content height and auto-scroll so the thinking
     * area doesn't push the rest of the chat off-screen. */
    .thinking-content.streaming-content {
        box-sizing: border-box;
        max-height: 200px;
        overflow-y: auto;
        scroll-behavior: smooth;
        scrollbar-width: none; /* Firefox */
        -ms-overflow-style: none; /* IE/Edge */
    }
    .thinking-content.streaming-content::-webkit-scrollbar {
        display: none;
    }

    @media (prefers-reduced-motion: reduce) {
        .thinking-content.streaming-content {
            scroll-behavior: auto;
        }
    }
    
    /* Override ReadOnlyMessage styles for thinking content */
    .thinking-content :global(.tiptap-editor) {
        font-size: var(--font-size-xs);
        opacity: 0.85;
    }
    
    /* Dark mode support */
    :global(.dark) .thinking-section {
        background: var(--color-grey-10);
        border-color: var(--color-grey-25);
    }

    :global(.dark) .thinking-section.streaming {
        border-color: var(--color-grey-20);
    }

    :global(.dark) .thinking-section.expanded {
        background: var(--color-grey-0);
    }
    
    :global(.dark) .thinking-header {
        color: var(--color-font-secondary);
    }
    
    :global(.dark) .thinking-header:hover {
        background: var(--color-grey-20);
    }
    
    :global(.dark) .thinking-content {
        border-color: var(--color-grey-25);
        color: var(--color-font-secondary);
    }
</style>
