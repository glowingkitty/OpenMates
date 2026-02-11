<!--
  frontend/packages/ui/src/components/DemoMessageContent.svelte
  
  A wrapper component for rendering demo chat message content that handles
  special placeholders like [[example_chats_group]], [[app_store_group]],
  [[skills_group]], [[focus_modes_group]], [[settings_memories_group]],
  and their developer-specific variants ([[dev_app_store_group]], etc.).
  
  Also handles [[for_developers_embed]] to render an inline embed preview
  of the for-developers intro chat at the end of the for-everyone chat.
  
  This component:
  1. Splits content at placeholder markers
  2. Renders each markdown section using ReadOnlyMessage
  3. Inserts the corresponding group component at each placeholder position
-->

<script lang="ts">
  import ReadOnlyMessage from './ReadOnlyMessage.svelte';
  import ExampleChatsGroup from './embeds/ExampleChatsGroup.svelte';
  import AppStoreGroup from './embeds/AppStoreGroup.svelte';
  import SkillsGroup from './embeds/SkillsGroup.svelte';
  import FocusModesGroup from './embeds/FocusModesGroup.svelte';
  import SettingsMemoriesGroup from './embeds/SettingsMemoriesGroup.svelte';
  import IntroChatEmbed from './embeds/IntroChatEmbed.svelte';
  
  /**
   * Props interface for DemoMessageContent
   */
  interface Props {
    /** The message content (may contain special placeholders) */
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
  
  /**
   * Developer-focused app IDs. These apps are excluded from the "for everyone"
   * intro chat groups and shown exclusively in the "for developers" intro chat.
   * Currently only the code app, but designed to be easily extended.
   */
  const DEVELOPER_APP_IDS = ['code'];
  
  // Placeholder constants
  // NOTE: Uses [[...]] instead of {...} to avoid ICU MessageFormat variable interpolation in svelte-i18n
  const EXAMPLE_CHATS_PLACEHOLDER = '[[example_chats_group]]';
  const DEV_EXAMPLE_CHATS_PLACEHOLDER = '[[dev_example_chats_group]]';
  const APP_STORE_PLACEHOLDER = '[[app_store_group]]';
  const SKILLS_PLACEHOLDER = '[[skills_group]]';
  const FOCUS_MODES_PLACEHOLDER = '[[focus_modes_group]]';
  const SETTINGS_MEMORIES_PLACEHOLDER = '[[settings_memories_group]]';
  // Developer-specific variants: show ONLY developer app content
  const DEV_APP_STORE_PLACEHOLDER = '[[dev_app_store_group]]';
  const DEV_SKILLS_PLACEHOLDER = '[[dev_skills_group]]';
  const DEV_FOCUS_MODES_PLACEHOLDER = '[[dev_focus_modes_group]]';
  const DEV_SETTINGS_MEMORIES_PLACEHOLDER = '[[dev_settings_memories_group]]';
  // Embed for linking to the for-developers intro chat from for-everyone
  const FOR_DEVELOPERS_EMBED_PLACEHOLDER = '[[for_developers_embed]]';
  
  // All supported placeholder tokens and their part types
  const PLACEHOLDERS = [
    EXAMPLE_CHATS_PLACEHOLDER,
    DEV_EXAMPLE_CHATS_PLACEHOLDER,
    APP_STORE_PLACEHOLDER,
    SKILLS_PLACEHOLDER,
    FOCUS_MODES_PLACEHOLDER,
    SETTINGS_MEMORIES_PLACEHOLDER,
    DEV_APP_STORE_PLACEHOLDER,
    DEV_SKILLS_PLACEHOLDER,
    DEV_FOCUS_MODES_PLACEHOLDER,
    DEV_SETTINGS_MEMORIES_PLACEHOLDER,
    FOR_DEVELOPERS_EMBED_PLACEHOLDER,
  ] as const;
  
  /** Map placeholder strings to their part type identifiers */
  const PLACEHOLDER_TYPE_MAP: Record<string, string> = {
    [EXAMPLE_CHATS_PLACEHOLDER]: 'example_chats_group',
    [DEV_EXAMPLE_CHATS_PLACEHOLDER]: 'dev_example_chats_group',
    [APP_STORE_PLACEHOLDER]: 'app_store_group',
    [SKILLS_PLACEHOLDER]: 'skills_group',
    [FOCUS_MODES_PLACEHOLDER]: 'focus_modes_group',
    [SETTINGS_MEMORIES_PLACEHOLDER]: 'settings_memories_group',
    [DEV_APP_STORE_PLACEHOLDER]: 'dev_app_store_group',
    [DEV_SKILLS_PLACEHOLDER]: 'dev_skills_group',
    [DEV_FOCUS_MODES_PLACEHOLDER]: 'dev_focus_modes_group',
    [DEV_SETTINGS_MEMORIES_PLACEHOLDER]: 'dev_settings_memories_group',
    [FOR_DEVELOPERS_EMBED_PLACEHOLDER]: 'for_developers_embed',
  };
  
  type PartType = 'markdown' | 'example_chats_group' | 'dev_example_chats_group' | 'app_store_group' | 'skills_group' | 'focus_modes_group' | 'settings_memories_group' | 'dev_app_store_group' | 'dev_skills_group' | 'dev_focus_modes_group' | 'dev_settings_memories_group' | 'for_developers_embed';
  
  /**
   * Split content at all placeholder tokens into typed parts.
   * Handles multiple different placeholder types in a single pass using a regex
   * that matches any of the supported placeholders.
   */
  let contentParts = $derived((() => {
    const hasAnyPlaceholder = PLACEHOLDERS.some(p => content.includes(p));
    
    if (!hasAnyPlaceholder) {
      // No placeholder, return single part
      return [{ type: 'markdown' as PartType, content }];
    }
    
    // Build a regex that matches any placeholder (escaped for regex safety)
    const escapedPlaceholders = PLACEHOLDERS.map(p => p.replace(/[[\]]/g, '\\$&'));
    const placeholderRegex = new RegExp(`(${escapedPlaceholders.join('|')})`);
    
    // Split at any placeholder, keeping the delimiters in the result
    const segments = content.split(placeholderRegex);
    
    const parts: Array<{ type: PartType; content: string }> = [];
    
    for (const segment of segments) {
      const partType = PLACEHOLDER_TYPE_MAP[segment];
      if (partType) {
        parts.push({ type: partType as PartType, content: '' });
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
        <ExampleChatsGroup excludeChatId={chatId} demoChatCategory="for_everyone" />
      {:else if part.type === 'dev_example_chats_group'}
        <ExampleChatsGroup excludeChatId={chatId} demoChatCategory="for_developers" />
      {:else if part.type === 'app_store_group'}
        <!-- For-everyone: exclude developer-focused apps -->
        <AppStoreGroup excludeAppIds={DEVELOPER_APP_IDS} />
      {:else if part.type === 'skills_group'}
        <!-- For-everyone: exclude developer-focused app skills -->
        <SkillsGroup excludeAppIds={DEVELOPER_APP_IDS} />
      {:else if part.type === 'focus_modes_group'}
        <!-- For-everyone: exclude developer-focused app focus modes -->
        <FocusModesGroup excludeAppIds={DEVELOPER_APP_IDS} />
      {:else if part.type === 'settings_memories_group'}
        <!-- For-everyone: exclude developer-focused app settings & memories -->
        <SettingsMemoriesGroup excludeAppIds={DEVELOPER_APP_IDS} />
      {:else if part.type === 'dev_app_store_group'}
        <!-- For-developers: show ONLY developer-focused apps -->
        <AppStoreGroup onlyAppIds={DEVELOPER_APP_IDS} />
      {:else if part.type === 'dev_skills_group'}
        <!-- For-developers: show ONLY developer-focused app skills -->
        <SkillsGroup onlyAppIds={DEVELOPER_APP_IDS} />
      {:else if part.type === 'dev_focus_modes_group'}
        <!-- For-developers: show ONLY developer-focused app focus modes -->
        <FocusModesGroup onlyAppIds={DEVELOPER_APP_IDS} />
      {:else if part.type === 'dev_settings_memories_group'}
        <!-- For-developers: show ONLY developer-focused app settings & memories -->
        <SettingsMemoriesGroup onlyAppIds={DEVELOPER_APP_IDS} />
      {:else if part.type === 'for_developers_embed'}
        <!-- Embedded preview of the for-developers intro chat -->
        <IntroChatEmbed introChatId="demo-for-developers" />
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
