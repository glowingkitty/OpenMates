<!--
  StartScreenChatSuggestions.svelte — new-chat suggestions below the Chats
  start-screen row (TASK-1321), in the same style as the follow-up suggestions
  below an open chat (FollowUpSuggestions). Signed-in users see their own synced
  suggestions, newest first; guests (and users without any) see the translated
  defaults, ranked by selected interests. Tapping one puts it into the composer.

  Spec: specifications/features/daily-inspiration (daily-inspiration.start-row-suggestions)
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import { get } from 'svelte/store';
  import FollowUpSuggestions from '../FollowUpSuggestions.svelte';
  import { setClickedSuggestion } from '../../stores/suggestionTracker';
  import type { InterestTagId } from '../../demo_chats/interestTags';
  import {
    buildDefaultStartScreenSuggestions,
    loadStoredStartScreenSuggestions,
    type StartScreenSuggestion,
  } from '../../services/startScreenSuggestions';

  /** Three prompts keep the row, suggestions and composer on one phone screen. */
  const VISIBLE_COUNT = 3;

  type Props = {
    isAuthenticated: boolean;
    selectedInterestTagIds: InterestTagId[];
    /** Changes when synced suggestions or the language may have changed. */
    reloadKey: string;
    onSuggestionClick: (suggestion: string) => void;
  };

  let { isAuthenticated, selectedInterestTagIds, reloadKey, onSuggestionClick }: Props = $props();

  let suggestions = $state<StartScreenSuggestion[]>([]);
  let loadGeneration = 0;

  $effect(() => {
    const auth = isAuthenticated;
    const tags = [...selectedInterestTagIds];
    void reloadKey;
    const generation = ++loadGeneration;
    const defaults = () => buildDefaultStartScreenSuggestions(get(text), tags);
    if (!auth) {
      suggestions = defaults();
      return;
    }
    loadStoredStartScreenSuggestions().then(
      (stored) => {
        if (generation !== loadGeneration) return;
        suggestions = stored.length > 0 ? stored : defaults();
      },
      (error: unknown) => {
        if (generation !== loadGeneration) return;
        console.error('[StartScreenChatSuggestions] Loading synced suggestions failed; showing defaults:', error);
        suggestions = defaults();
      },
    );
  });

  let visible = $derived(suggestions.slice(0, VISIBLE_COUNT));

  function handleClick(body: string) {
    const picked = suggestions.find((suggestion) => suggestion.text === body);
    if (isAuthenticated && picked?.encrypted) setClickedSuggestion(body, picked.encrypted);
    onSuggestionClick(body);
  }
</script>

{#if visible.length > 0}
  <div class="start-screen-suggestions" data-testid="start-screen-suggestions">
    <FollowUpSuggestions suggestions={visible.map((suggestion) => suggestion.text)} dismissOnClick={false} singleLine align="start" onSuggestionClick={handleClick} />
  </div>
{/if}

<style>
  /* As wide as the message input (min(629px, 100%)), centred, lines left-aligned:
     the same layout as the other start screens (WorkspaceHomeShell, Marco 22 Nov). */
  .start-screen-suggestions {
    display: flex;
    justify-content: center;
    width: min(629px, 100%);
    margin-inline: auto;
    padding: 0 var(--spacing-6);
    box-sizing: border-box;
    pointer-events: auto;
    text-align: left;
  }
</style>
