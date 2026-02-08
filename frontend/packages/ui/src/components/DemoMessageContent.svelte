<!--
  frontend/packages/ui/src/components/DemoMessageContent.svelte
  
  A wrapper component for rendering demo chat message content that handles
  special placeholders like [[example_chats_group]] and [[app_store_group]].
  
  This component:
  1. Splits content at placeholder markers
  2. Renders each markdown section using ReadOnlyMessage
  3. Inserts the ExampleChatsGroup component at [[example_chats_group]] positions
  4. Inserts the AppStoreGroup component at [[app_store_group]] positions
-->

<script lang="ts">
  import ReadOnlyMessage from './ReadOnlyMessage.svelte';
  import ExampleChatsGroup from './embeds/ExampleChatsGroup.svelte';
  import AppStoreGroup from './embeds/AppStoreGroup.svelte';
  
  /**
   * Props interface for DemoMessageContent
   */
  interface Props {
    /** The message content (may contain [[example_chats_group]] and [[app_store_group]] placeholders) */
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
  
  // Placeholder constants
  // NOTE: Uses [[...]] instead of {...} to avoid ICU MessageFormat variable interpolation in svelte-i18n
  const EXAMPLE_CHATS_PLACEHOLDER = '[[example_chats_group]]';
  const APP_STORE_PLACEHOLDER = '[[app_store_group]]';
  
  // All supported placeholder tokens
  const PLACEHOLDERS = [EXAMPLE_CHATS_PLACEHOLDER, APP_STORE_PLACEHOLDER] as const;
  
  /**
   * Split content at all placeholder tokens into typed parts.
   * Handles multiple different placeholder types in a single pass using a regex
   * that matches any of the supported placeholders.
   */
  let contentParts = $derived((() => {
    const hasAnyPlaceholder = PLACEHOLDERS.some(p => content.includes(p));
    
    if (!hasAnyPlaceholder) {
      // No placeholder, return single part
      return [{ type: 'markdown' as const, content }];
    }
    
    // Build a regex that matches any placeholder (escaped for regex safety)
    const escapedPlaceholders = PLACEHOLDERS.map(p => p.replace(/[[\]]/g, '\\$&'));
    const placeholderRegex = new RegExp(`(${escapedPlaceholders.join('|')})`);
    
    // Split at any placeholder, keeping the delimiters in the result
    const segments = content.split(placeholderRegex);
    
    const parts: Array<{ type: 'markdown' | 'example_chats_group' | 'app_store_group'; content: string }> = [];
    
    for (const segment of segments) {
      if (segment === EXAMPLE_CHATS_PLACEHOLDER) {
        parts.push({ type: 'example_chats_group', content: '' });
      } else if (segment === APP_STORE_PLACEHOLDER) {
        parts.push({ type: 'app_store_group', content: '' });
      } else if (segment.trim()) {
        parts.push({ type: 'markdown', content: segment });
      }
    }
    
    return parts;
  })());
  
  // Check if we have any placeholder (used to determine if we need special rendering)
  let hasPlaceholder = $derived(PLACEHOLDERS.some(p => content.includes(p)));
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
      {:else if part.type === 'app_store_group'}
        <AppStoreGroup />
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
