<!--
  GuestInterestTags.svelte — logged-out interest selector for smart welcome ranking.

  This component persists guest selections only through topicPreferencesStore,
  which writes to sessionStorage. It emits every selection change so the parent
  can rerank inspirations and suggestion cards without sending interests to the
  server.
-->
<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { text } from '@repo/ui';
  import {
    rankInterestTagsForSelection,
  } from '../demo_chats/guestSmartSelection';
  import { INTEREST_TAGS, type InterestTagId } from '../demo_chats/interestTags';
  import { appsMetadata } from '../data/appsMetadata';
  import {
    topicPreferencesStore,
  } from '../stores/topicPreferencesStore';
  import { getCategoryGradientColors } from '../utils/categoryUtils';
  import { getLucideIcon } from '../utils/categoryUtils';

  const CheckIcon = getLucideIcon('check');
  const AVAILABLE_TAG_LIMIT = 10;
  const MIN_TAGS_TO_CONTINUE = 4;
  const TAG_RAIL_CENTER_ITEM_WIDTH = 150;

  let {
    onSelectionChange,
    onContinue,
    onSkip,
  }: {
    onSelectionChange: (selectedTagIds: InterestTagId[]) => void;
    onContinue: (selectedTagIds: InterestTagId[]) => void;
    onSkip: () => void;
  } = $props();

  let selectedTagIds = $state<InterestTagId[]>([]);
  let railEl = $state<HTMLDivElement | null>(null);
  let rankedTags = $derived(rankInterestTagsForSelection(selectedTagIds));
  let selectedSet = $derived(new Set(selectedTagIds));
  let visibleTags = $derived.by(() => {
    const tagById = new Map(INTEREST_TAGS.map((tag) => [tag.id, tag]));
    const selectedTags = selectedTagIds
      .map((id) => tagById.get(id))
      .filter((tag): tag is (typeof INTEREST_TAGS)[number] => Boolean(tag));
    const availableTags = rankedTags.filter((tag) => !selectedSet.has(tag.id));
    return [...selectedTags, ...availableTags.slice(0, AVAILABLE_TAG_LIMIT)];
  });
  let canContinue = $derived(selectedTagIds.length >= MIN_TAGS_TO_CONTINUE);

  onMount(() => {
    const payload = topicPreferencesStore.loadGuest();
    selectedTagIds = payload?.selectedTagIds ?? [];
    onSelectionChange(selectedTagIds);
  });

  function labelFor(labelKey: string, fallbackLabel: string): string {
    const translated = $text(labelKey);
    return translated && translated !== labelKey && !translated.startsWith('T:') ? translated : fallbackLabel;
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
    selectedTagIds = next;
    onSelectionChange(selectedTagIds);
    tick().then(() => {
      restoreRailScroll(0);
    });
  }

  function restoreRailScroll(scrollLeft: number) {
    const rail = railEl;
    if (!rail) return;

    const previousScrollBehavior = rail.style.scrollBehavior;
    rail.style.scrollBehavior = 'auto';
    rail.scrollLeft = scrollLeft;
    requestAnimationFrame(() => {
      rail.scrollLeft = scrollLeft;
      requestAnimationFrame(() => {
        rail.scrollLeft = scrollLeft;
        rail.style.scrollBehavior = previousScrollBehavior;
      });
    });
  }

  function handleContinue() {
    if (!canContinue) return;
    const payload = topicPreferencesStore.setGuestSelectedTagIds(selectedTagIds);
    selectedTagIds = payload.selectedTagIds;
    onContinue(selectedTagIds);
  }

</script>

<div class="guest-interest-tags" data-testid="guest-interest-tags">
  <div
    class="guest-interest-rail"
    data-testid="guest-interest-rail"
    bind:this={railEl}
    style:--guest-interest-center-offset={`${TAG_RAIL_CENTER_ITEM_WIDTH / 2}px`}
  >
    {#each visibleTags as tag (tag.id)}
      {@const IconComponent = getLucideIcon(tag.icon)}
      {@const isActive = selectedSet.has(tag.id)}
      <button
        type="button"
        class="guest-interest-tag"
        class:active={isActive}
        data-testid={`interest-tag-${tag.id}`}
        data-interest-active={isActive ? 'true' : 'false'}
        data-app-id={tag.appId}
        style:background={gradientFor(tag.appId, tag.gradientCategory)}
        onclick={() => toggleTag(tag.id)}
      >
        {#if isActive}
          <span class="guest-interest-active-check" data-testid={`interest-tag-${tag.id}-check`} aria-hidden="true">
            <CheckIcon size={11} color="white" strokeWidth={3} />
          </span>
        {/if}
        <IconComponent size={15} color="white" />
        <span>{labelFor(tag.labelKey, tag.fallbackLabel)}</span>
      </button>
    {/each}
  </div>
  <div class="guest-interest-actions">
    {#if canContinue}
      <button
        type="button"
        class="guest-interest-continue"
        data-testid="guest-interest-continue"
        onclick={handleContinue}
      >
        {$text('chat.interests.continue')}
      </button>
    {/if}
    <button
      type="button"
      class="guest-interest-skip"
      data-testid="guest-interest-skip"
      onclick={onSkip}
    >
      {$text('chat.interests.skip')}
    </button>
  </div>
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
    padding: 4px 12px 8px max(6px, calc(50% - var(--guest-interest-center-offset, 75px)));
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
    position: relative;
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

  .guest-interest-active-check {
    position: absolute;
    top: -5px;
    right: -5px;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    border-radius: 999px;
    background: #18a957;
    border: 2px solid var(--color-grey-20, #222);
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.26);
    pointer-events: none;
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

  .guest-interest-actions {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-4, 16px);
    min-height: 40px;
  }

  .guest-interest-skip {
    border: none;
    background: transparent;
    color: var(--color-grey-60, #777);
    padding: 0;
    font: inherit;
    font-size: 0.86rem;
    font-weight: 650;
    cursor: pointer;
    text-decoration: none;
  }
</style>
