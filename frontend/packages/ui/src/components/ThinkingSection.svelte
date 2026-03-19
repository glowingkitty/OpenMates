<!--
  ThinkingSection.svelte
  
  Displays AI thinking/reasoning content from thinking models (Gemini, Anthropic Claude, etc.)
  
  Features:
  - Auto-expands while streaming so the user sees thinking content as it arrives
  - Auto-collapses when streaming completes (collapsed by default for finished thinking)
  - User can manually toggle expand/collapse at any time (respected during streaming)
  - Auto-scrolls content to the bottom as new chunks arrive
  - Animated rotating gradient border while streaming (clearly signals "thinking in progress")
  - Uses ReadOnlyMessage for markdown rendering
  - All user-facing text is i18n-translated
  
  Visual Design:
  - reasoning.svg icon on the left
  - Translated "Thinking..." text during streaming, "Thought process" when done
  - Apple Intelligence-style rainbow glow border animates while streaming (full-spectrum conic-gradient + soft bloom)
  - dropdown.svg icon on the right that rotates 180° when expanded
  - Hover color change to indicate clickability
  
  Props:
  - thinkingContent: The thinking markdown content
  - isStreaming: Whether thinking is currently streaming
  - isExpanded: Whether the section is expanded (bindable)
-->
<script lang="ts">
    import { slide } from 'svelte/transition';
    import { tick } from 'svelte';
    import ReadOnlyMessage from './ReadOnlyMessage.svelte';
    import { parse_message } from '../message_parsing/parse_message';
    import { text } from '@repo/ui'; // For i18n translations
    
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

    // DOM ref for the content scroll container — used to auto-scroll to bottom
    let contentEl = $state<HTMLDivElement | null>(null);
    
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
                contentEl.scrollTo({ top: contentEl.scrollHeight, behavior: 'smooth' });
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
    <div class="thinking-section" class:streaming={isStreaming} class:expanded={isExpanded}>
        <!-- Collapsed Header (always visible) -->
        <button 
            class="thinking-header"
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
            <div class="thinking-content" class:streaming-content={isStreaming} bind:this={contentEl} transition:slide={{ duration: 200 }}>
                <ReadOnlyMessage 
                    content={parsedThinkingContent}
                    isStreaming={isStreaming}
                />
            </div>
        {/if}
    </div>
{/if}

<style>
    /*
     * Register --gradient-angle as an animatable CSS custom property.
     * This is required for @keyframes to interpolate the angle value used in
     * the conic-gradient on the streaming border pseudo-element.
     * Without this, browsers cannot tween custom properties in @keyframes.
     * @property is widely supported (Chrome 85+, Firefox 128+, Safari 16.4+).
     */
    @property --gradient-angle {
        syntax: '<angle>';
        initial-value: 0deg;
        inherits: false;
    }

    /*
     * Register --glow-angle for the outer glow halo layer — offset so the
     * bloom trails the sharp border ring, creating Apple Intelligence depth.
     */
    @property --glow-angle {
        syntax: '<angle>';
        initial-value: 60deg;
        inherits: false;
    }

    .thinking-section {
        margin-bottom: 12px;
        border-radius: 8px;
        background: var(--color-surface-secondary, rgba(0, 0, 0, 0.03));
        border: 1px solid var(--color-border-subtle, rgba(0, 0, 0, 0.08));
        overflow: hidden;
        position: relative;
        /* isolation: isolate keeps the ::before gradient behind children */
        isolation: isolate;
        transition: border-color 0.2s ease, background-color 0.2s ease;
    }

    /*
     * Outer glow while streaming — radiates outside the container boundary.
     * Using filter: drop-shadow on the element itself would be clipped by
     * overflow:hidden, so we animate a dedicated outer glow via a wide
     * box-shadow on the container. The shadow colour cycles through the
     * rainbow hues at 1/3 of the ring speed, approximating the Apple
     * Intelligence "breathing" ambient glow that trails the border arc.
     */
    .thinking-section.streaming {
        /* Remove the static accent border — the animated pseudo-element replaces it */
        border-color: transparent;
        /* Outer glow — three stacked shadows at increasing radius/spread for bloom depth */
        box-shadow:
            0 0  8px  2px rgba(255,  45,  85, 0.40),   /* tight red halo      */
            0 0 18px  6px rgba(191,  90, 242, 0.28),   /* mid purple bloom    */
            0 0 32px 10px rgba( 50, 173, 230, 0.18);   /* wide cyan diffusion */
        animation: glow-shift 9s linear infinite;       /* 3× ring speed = same phase */
    }

    /*
     * Animated gradient border while streaming.
     * A conic-gradient rotates slowly inside a ::before pseudo-element that is
     * positioned to match the container edges. The container clips it so only
     * the 1px border strip is visible — giving a subtle "living" border effect.
     * The ::after pseudo-element acts as the interior background fill so the
     * gradient doesn't bleed into the content area.
     *
     * Technique: pseudo-element sits behind all children (z-index: -1) and is
     * slightly larger than the box so the gradient covers the border zone.
     * overflow:hidden on the parent clips it to the border-radius shape.
     */


    /*
     * Apple Intelligence-style rainbow glow border.
     *
     * Layer 1 (::before) — the sharp rotating rainbow ring.
     * A full-spectrum conic-gradient spins around the container perimeter.
     * filter: blur(1px) softens the hard colour stops just enough to give
     * the "luminous" quality without losing the rainbow definition.
     *
     * Layer 2 (::after) is split: the top half handles the interior fill mask
     * so the gradient doesn't bleed into the content; the second pseudo-element
     * is simulated via a box-shadow on ::before for the outer glow halo.
     *
     * Apple Intelligence colour stops (sampled from recorded references):
     * magenta → orange → yellow → green → cyan → blue → violet → magenta
     */
    /*
     * ::before — the sharp rotating rainbow ring.
     * blur(2px) on the ring itself softens colour-stop transitions so the
     * hues blend smoothly (no hard lines between red and orange, etc.)
     * while still reading as a distinct coloured border — not a pure blur.
     */
    .thinking-section.streaming::before {
        content: '';
        position: absolute;
        inset: -2px;
        border-radius: 10px;
        background: conic-gradient(
            from var(--gradient-angle, 0deg),
            #ff2d55,   /*  0deg  — Apple red/pink  */
            #ff6b2b,   /* 51deg  — orange          */
            #ffd60a,   /* 102deg — yellow          */
            #30d158,   /* 153deg — green           */
            #32ade6,   /* 204deg — cyan/blue       */
            #bf5af2,   /* 255deg — purple          */
            #ff375f,   /* 306deg — magenta         */
            #ff2d55    /* 360deg — loop back       */
        );
        animation: rainbow-spin 3s linear infinite;
        z-index: -1;
        opacity: 1;
        filter: blur(2px);
    }

    /*
     * ::after — interior fill mask.
     * Sits above the ::before gradient ring but behind all children,
     * covering the content area so the rainbow doesn't bleed into the text.
     * inset: 2px = the 2px border zone exposed by ::before's -2px inset.
     */
    .thinking-section.streaming::after {
        content: '';
        position: absolute;
        inset: 2px;
        border-radius: 7px;
        background: var(--color-surface-secondary, rgba(0, 0, 0, 0.03));
        z-index: -1;
    }
    
    .thinking-section.expanded {
        background: var(--color-grey-20);
    }

    /* When expanded AND streaming, keep the interior fill consistent with expanded bg */
    .thinking-section.expanded.streaming::after {
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
    
    .thinking-header:hover .thinking-icon {
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
    
    .thinking-summary {
        flex: 1;
        font-weight: 500;
        transition: color 0.15s ease;
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
    
    .thinking-content {
        padding: 0 14px 14px;
        border-top: 1px solid var(--color-border-subtle, rgba(0, 0, 0, 0.08));
        font-size: 14px;
        line-height: 1.6;
        color: var(--color-text-secondary, #555);
    }
    
    /* While streaming, cap the content height and auto-scroll so the thinking
     * area doesn't push the rest of the chat off-screen. */
    .thinking-content.streaming-content {
        max-height: 200px;
        overflow-y: auto;
        scroll-behavior: smooth;
        scrollbar-width: none; /* Firefox */
        -ms-overflow-style: none; /* IE/Edge */
    }
    .thinking-content.streaming-content::-webkit-scrollbar {
        display: none;
    }
    
    /* Override ReadOnlyMessage styles for thinking content */
    .thinking-content :global(.tiptap-editor) {
        font-size: 13px;
        opacity: 0.85;
    }
    
    /*
     * Rainbow spin — rotates --gradient-angle so the full spectrum travels
     * around the container perimeter. 3s gives the snappy-but-elegant pace
     * seen in Apple Intelligence demos (faster than the old 4s blue spin).
     * Falls back gracefully: without @property support the gradient is static.
     */
    @keyframes rainbow-spin {
        from { --gradient-angle: 0deg; }
        to   { --gradient-angle: 360deg; }
    }

    /*
     * glow-shift — smoothly cycles the outer box-shadow colours through the
     * same rainbow spectrum as the border ring, at 1/3 of the ring speed
     * (9s vs 3s) so the glow colour always roughly matches the arc region
     * nearest the top of the container. Pure CSS approximation — no JS.
     */
    @keyframes glow-shift {
        0%   { box-shadow: 0 0  8px  2px rgba(255,  45,  85, 0.40), 0 0 18px  6px rgba(191,  90, 242, 0.28), 0 0 32px 10px rgba( 50, 173, 230, 0.18); }
        16%  { box-shadow: 0 0  8px  2px rgba(255, 107,  43, 0.40), 0 0 18px  6px rgba(255,  45,  85, 0.28), 0 0 32px 10px rgba(191,  90, 242, 0.18); }
        33%  { box-shadow: 0 0  8px  2px rgba(255, 214,  10, 0.40), 0 0 18px  6px rgba(255, 107,  43, 0.28), 0 0 32px 10px rgba(255,  45,  85, 0.18); }
        50%  { box-shadow: 0 0  8px  2px rgba( 48, 209,  88, 0.40), 0 0 18px  6px rgba(255, 214,  10, 0.28), 0 0 32px 10px rgba(255, 107,  43, 0.18); }
        66%  { box-shadow: 0 0  8px  2px rgba( 50, 173, 230, 0.40), 0 0 18px  6px rgba( 48, 209,  88, 0.28), 0 0 32px 10px rgba(255, 214,  10, 0.18); }
        83%  { box-shadow: 0 0  8px  2px rgba(191,  90, 242, 0.40), 0 0 18px  6px rgba( 50, 173, 230, 0.28), 0 0 32px 10px rgba( 48, 209,  88, 0.18); }
        100% { box-shadow: 0 0  8px  2px rgba(255,  45,  85, 0.40), 0 0 18px  6px rgba(191,  90, 242, 0.28), 0 0 32px 10px rgba( 50, 173, 230, 0.18); }
    }

    /* Dark mode variant — wider radius, no opacity boost needed on dark bg */
    @keyframes glow-shift-dark {
        0%   { box-shadow: 0 0 12px  4px rgba(255,  45,  85, 0.50), 0 0 24px  8px rgba(191,  90, 242, 0.35), 0 0 40px 14px rgba( 50, 173, 230, 0.22); }
        16%  { box-shadow: 0 0 12px  4px rgba(255, 107,  43, 0.50), 0 0 24px  8px rgba(255,  45,  85, 0.35), 0 0 40px 14px rgba(191,  90, 242, 0.22); }
        33%  { box-shadow: 0 0 12px  4px rgba(255, 214,  10, 0.50), 0 0 24px  8px rgba(255, 107,  43, 0.35), 0 0 40px 14px rgba(255,  45,  85, 0.22); }
        50%  { box-shadow: 0 0 12px  4px rgba( 48, 209,  88, 0.50), 0 0 24px  8px rgba(255, 214,  10, 0.35), 0 0 40px 14px rgba(255, 107,  43, 0.22); }
        66%  { box-shadow: 0 0 12px  4px rgba( 50, 173, 230, 0.50), 0 0 24px  8px rgba( 48, 209,  88, 0.35), 0 0 40px 14px rgba(255, 214,  10, 0.22); }
        83%  { box-shadow: 0 0 12px  4px rgba(191,  90, 242, 0.50), 0 0 24px  8px rgba( 50, 173, 230, 0.35), 0 0 40px 14px rgba( 48, 209,  88, 0.22); }
        100% { box-shadow: 0 0 12px  4px rgba(255,  45,  85, 0.50), 0 0 24px  8px rgba(191,  90, 242, 0.35), 0 0 40px 14px rgba( 50, 173, 230, 0.22); }
    }
    
    /* Dark mode support */
    :global(.dark) .thinking-section {
        background: var(--color-surface-secondary, rgba(255, 255, 255, 0.03));
        border-color: var(--color-border-subtle, rgba(255, 255, 255, 0.1));
    }

    /*
     * Dark mode streaming: transparent border + outer glow animation.
     * Wider radius/spread than light mode since dark backgrounds let the glow bloom further.
     */
    :global(.dark) .thinking-section.streaming {
        border-color: transparent;
        box-shadow:
            0 0 12px  4px rgba(255,  45,  85, 0.50),
            0 0 24px  8px rgba(191,  90, 242, 0.35),
            0 0 40px 14px rgba( 50, 173, 230, 0.22);
        animation: glow-shift-dark 9s linear infinite;
    }

    /* Dark interior fill mask */
    :global(.dark) .thinking-section.streaming::after {
        background: var(--color-surface-secondary, rgba(255, 255, 255, 0.03));
    }
    
    :global(.dark) .thinking-section.expanded {
        background: var(--color-surface-primary, #1a1a1a);
    }

    :global(.dark) .thinking-section.expanded.streaming::after {
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
