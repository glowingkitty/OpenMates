<!--
  frontend/packages/ui/src/components/DemoMessageContent.svelte
  
  A wrapper component for rendering demo chat message content that handles
  special placeholders like {example_chats_group}.
  
  This component:
  1. Splits content at placeholder markers
  2. Renders each markdown section using ReadOnlyMessage
  3. Inserts the ExampleChatsGroup component at placeholder positions
-->

<script lang="ts">
  import ReadOnlyMessage from './ReadOnlyMessage.svelte';
  import ExampleChatsGroup from './embeds/ExampleChatsGroup.svelte';
  
  /**
   * Props interface for DemoMessageContent
   */
  interface Props {
    /** The message content (may contain {example_chats_group} placeholder) */
    content: string;
    /** Current chat ID to exclude from example chats group */
    chatId?: string;
    /** Whether the content is still streaming */
    isStreaming?: boolean;
    /** Whether text is selectable */
    selectable?: boolean;
  }
  
  let {
    content,
    chatId = 'demo-for-everyone',
    isStreaming = false,
    selectable = false
  }: Props = $props();
  
  // Placeholder constant
  const EXAMPLE_CHATS_PLACEHOLDER = '{example_chats_group}';
  
  // Split content at the placeholder
  let contentParts = $derived((() => {
    if (!content.includes(EXAMPLE_CHATS_PLACEHOLDER)) {
      // No placeholder, return single part
      return [{ type: 'markdown' as const, content }];
    }
    
    // Split at placeholder
    const parts: Array<{ type: 'markdown' | 'example_chats_group'; content: string }> = [];
    const segments = content.split(EXAMPLE_CHATS_PLACEHOLDER);
    
    segments.forEach((segment, index) => {
      // Add markdown segment (even if empty, for spacing)
      if (segment.trim() || index === 0) {
        parts.push({ type: 'markdown', content: segment });
      }
      
      // Add placeholder component (except after the last segment)
      if (index < segments.length - 1) {
        parts.push({ type: 'example_chats_group', content: '' });
      }
    });
    
    return parts;
  })());
  
  // Check if we have the placeholder (used to determine if we need special rendering)
  let hasPlaceholder = $derived(content.includes(EXAMPLE_CHATS_PLACEHOLDER));
</script>

{#if hasPlaceholder}
  <!-- Render with placeholder handling -->
  <div class="demo-message-content">
    {#each contentParts as part, index (index)}
      {#if part.type === 'markdown' && part.content.trim()}
        <ReadOnlyMessage
          content={part.content}
          {isStreaming}
          {selectable}
        />
      {:else if part.type === 'example_chats_group'}
        <ExampleChatsGroup excludeChatId={chatId} />
      {/if}
    {/each}
  </div>
{:else}
  <!-- No placeholder, render normally -->
  <ReadOnlyMessage
    {content}
    {isStreaming}
    {selectable}
  />
{/if}

<style>
  .demo-message-content {
    display: flex;
    flex-direction: column;
    width: 100%;
  }
  
  /* Ensure proper spacing between parts */
  .demo-message-content > :global(*) {
    width: 100%;
  }
</style>
