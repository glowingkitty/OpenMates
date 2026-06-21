<!--
  GuestInterestTags.svelte — logged-out interest selector for smart welcome ranking.

  This component persists guest selections only through topicPreferencesStore,
  which writes to sessionStorage. It emits every selection change so the parent
  can rerank inspirations and suggestion cards without sending interests to the
  server.
-->
<script lang="ts">
  import { onMount } from 'svelte';
  import { text } from '@repo/ui';
  import {
    rankInterestTagsForSelection,
  } from '../demo_chats/guestSmartSelection';
  import type { InterestTagId } from '../demo_chats/interestTags';
  import { appsMetadata } from '../data/appsMetadata';
  import {
    topicPreferencesStore,
  } from '../stores/topicPreferencesStore';
  import { getCategoryGradientColors } from '../utils/categoryUtils';
  import { getLucideIcon } from '../utils/categoryUtils';

  let {
    onSelectionChange,
    onContinue,
  }: {
    onSelectionChange: (selectedTagIds: InterestTagId[]) => void;
    onContinue: (selectedTagIds: InterestTagId[]) => void;
  } = $props();

  let selectedTagIds = $state<InterestTagId[]>([]);
  let rankedTags = $derived(rankInterestTagsForSelection(selectedTagIds));
  let selectedSet = $derived(new Set(selectedTagIds));

  onMount(() => {
    const payload = topicPreferencesStore.loadGuest();
    selectedTagIds = payload?.selectedTagIds ?? [];
    onSelectionChange(selectedTagIds);
  });

  function labelFor(labelKey: string, fallbackLabel: string): string {
    const translated = $text(labelKey);
    return translated && translated !== labelKey ? translated : fallbackLabel;
  }

  function gradientFor(appId: string, category: string): string {
    const gradient = appsMetadata[appId]?.icon_colorgradient
      || getCategoryGradientColors(category)
      || { start: '#6366f1', end: '#4f46e5' };
    return `var(--color-app-${appId}, linear-gradient(135deg, ${gradient.start}, ${gradient.end}))`;
  }

  function toggleTag(tagId: InterestTagId) {
    const next = selectedSet.has(tagId)
      ? selectedTagIds.filter((id) => id !== tagId)
      : [...selectedTagIds, tagId];
    const payload = topicPreferencesStore.setGuestSelectedTagIds(next);
    selectedTagIds = payload.selectedTagIds;
    onSelectionChange(selectedTagIds);
  }

  function handleContinue() {
    onContinue(selectedTagIds);
  }
</script>

<div class="guest-interest-tags" data-testid="guest-interest-tags">
  <div class="guest-interest-rail" data-testid="guest-interest-rail">
    {#each rankedTags as tag (tag.id)}
      {@const IconComponent = getLucideIcon(tag.icon)}
      <button
        type="button"
        class="guest-interest-tag"
        class:active={selectedSet.has(tag.id)}
        data-testid={`interest-tag-${tag.id}`}
        data-interest-active={selectedSet.has(tag.id) ? 'true' : 'false'}
        data-app-id={tag.appId}
        style:background={gradientFor(tag.appId, tag.gradientCategory)}
        onclick={() => toggleTag(tag.id)}
      >
        <IconComponent size={15} color="white" />
        <span>{labelFor(tag.labelKey, tag.fallbackLabel)}</span>
      </button>
    {/each}
  </div>
  {#if selectedTagIds.length > 0}
    <button
      type="button"
      class="guest-interest-continue"
      data-testid="guest-interest-continue"
      onclick={handleContinue}
    >
      {$text('chat.interests.continue')}
    </button>
  {/if}
</div>

<style>
  .guest-interest-tags {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2, 8px);
    width: 100%;
    max-width: 1040px;
    margin: 10px auto 0;
    align-items: center;
    pointer-events: auto;
  }

  .guest-interest-rail {
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 8px;
    width: 100%;
    max-width: 100%;
    overflow-x: auto;
    overflow-y: hidden;
    -webkit-overflow-scrolling: touch;
    scroll-behavior: smooth;
    overscroll-behavior-x: contain;
    touch-action: pan-x;
    padding: 4px 6px 8px;
    box-sizing: border-box;
    justify-content: flex-start;
    scrollbar-width: none;
    -ms-overflow-style: none;
    pointer-events: auto;
  }

  .guest-interest-rail::-webkit-scrollbar {
    display: none;
  }

  .guest-interest-tag {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    border: 1px solid rgba(255, 255, 255, 0.28);
    border-radius: 999px;
    color: white;
    font: inherit;
    font-size: 0.82rem;
    line-height: 1;
    white-space: nowrap;
    flex: 0 0 auto;
    width: auto;
    min-width: max-content;
    padding: 8px 11px;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.18);
    opacity: 0.78;
    cursor: pointer;
    pointer-events: auto;
    touch-action: manipulation;
    transition: opacity 0.16s ease, transform 0.16s ease, box-shadow 0.16s ease;
  }

  .guest-interest-tag:hover,
  .guest-interest-tag.active {
    opacity: 1;
    transform: translateY(-1px);
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.24);
  }

  .guest-interest-tag.active {
    border-color: rgba(255, 255, 255, 0.72);
  }

  .guest-interest-continue {
    border: none;
    border-radius: 999px;
    background: var(--color-button-primary, #6366f1);
    color: var(--color-font-button, white);
    padding: 8px 16px;
    font: inherit;
    font-weight: 600;
    cursor: pointer;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.22);
  }
</style>
