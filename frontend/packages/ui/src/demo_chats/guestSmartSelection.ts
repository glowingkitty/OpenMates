// frontend/packages/ui/src/demo_chats/guestSmartSelection.ts
// Deterministic local ranking helpers for guest interest smart selection.
// This module deliberately avoids browser APIs, Svelte stores, and network
// dependencies so selected interests never need server-side personalization.
// Guest persistence and encrypted account sync are handled by later layers.

import {
  getInterestTagById,
  INTEREST_TAGS,
  normalizeInterestTagIds,
  type InterestTag,
  type InterestTagId,
} from "./interestTags";

interface RankableDailyInspiration {
  inspiration_id: string;
  category?: string;
  personalized?: boolean;
}

interface RankedValue<T> {
  value: T;
  index: number;
  score: number;
  priority: number;
}

type InterestSurfaceKey =
  | "dailyInspirations"
  | "introChats"
  | "exampleChats"
  | "suggestions";

const MATCH_SCORE = 1000;
const RELATED_SCORE = 80;
const SHARED_CATEGORY_SCORE = 20;
const PERSONALIZED_SCORE = 100000;

export function rankInterestTagsForSelection(
  selectedTagIds: readonly string[],
): InterestTag[] {
  const selected = normalizeInterestTagIds(selectedTagIds);
  const selectedSet = new Set(selected);
  const selectedOrder = new Map(selected.map((id, index) => [id, index]));

  return [...INTEREST_TAGS].sort((a, b) => {
    const aSelectedIndex = selectedOrder.get(a.id);
    const bSelectedIndex = selectedOrder.get(b.id);

    if (aSelectedIndex !== undefined || bSelectedIndex !== undefined) {
      return (aSelectedIndex ?? Number.MAX_SAFE_INTEGER) - (bSelectedIndex ?? Number.MAX_SAFE_INTEGER);
    }

    const aScore = scoreTagRelation(a, selected, selectedSet);
    const bScore = scoreTagRelation(b, selected, selectedSet);
    if (aScore !== bScore) {
      return bScore - aScore;
    }

    return a.defaultOrder - b.defaultOrder;
  });
}

export function rankDailyInspirationsByInterests<T extends RankableDailyInspiration>(
  inspirations: readonly T[],
  selectedTagIds: readonly string[],
): T[] {
  return rankValues(inspirations, selectedTagIds, "dailyInspirations", (item) => item.inspiration_id, {
    getCategory: (item) => item.category,
    getExtraScore: (item) => (item.personalized ? PERSONALIZED_SCORE : 0),
  });
}

export function rankIntroChatIdsByInterests(
  chatIds: readonly string[],
  selectedTagIds: readonly string[],
): string[] {
  return rankValues(chatIds, selectedTagIds, "introChats", (id) => id);
}

export function rankExampleChatIdsByInterests(
  chatIds: readonly string[],
  selectedTagIds: readonly string[],
): string[] {
  return rankValues(chatIds, selectedTagIds, "exampleChats", (id) => id);
}

export function rankSuggestionKeysByInterests(
  suggestionKeys: readonly string[],
  selectedTagIds: readonly string[],
): string[] {
  return rankValues(suggestionKeys, selectedTagIds, "suggestions", (key) => key);
}

function rankValues<T>(
  values: readonly T[],
  selectedTagIds: readonly string[],
  surface: InterestSurfaceKey,
  getId: (value: T) => string,
  options: {
    getCategory?: (value: T) => string | undefined;
    getExtraScore?: (value: T) => number;
  } = {},
): T[] {
  const selected = normalizeInterestTagIds(selectedTagIds);
  const selectedTags = selected
    .map((tagId) => getInterestTagById(tagId))
    .filter((tag): tag is InterestTag => Boolean(tag));
  const deduped = dedupeValues(values, getId);

  return deduped
    .map<RankedValue<T>>((value, index) => {
      const id = getId(value);
      return {
        value,
        index,
        score:
          scoreContentId(id, surface, selectedTags) +
          scoreContentCategory(options.getCategory?.(value), selectedTags) +
          (options.getExtraScore?.(value) ?? 0),
        priority: getContentPriority(id, surface, selectedTags),
      };
    })
    .sort((a, b) => {
      if (a.score !== b.score) {
        return b.score - a.score;
      }
      if (a.priority !== b.priority) {
        return a.priority - b.priority;
      }
      return a.index - b.index;
    })
    .map((ranked) => ranked.value);
}

function dedupeValues<T>(values: readonly T[], getId: (value: T) => string): T[] {
  const seen = new Set<string>();
  const deduped: T[] = [];

  for (const value of values) {
    const id = getId(value);
    if (seen.has(id)) {
      continue;
    }
    seen.add(id);
    deduped.push(value);
  }

  return deduped;
}

function scoreTagRelation(
  tag: InterestTag,
  selected: readonly InterestTagId[],
  selectedSet: Set<InterestTagId>,
): number {
  let score = 0;

  for (let selectedIndex = 0; selectedIndex < selected.length; selectedIndex += 1) {
    const selectedId = selected[selectedIndex];
    const selectedTag = getInterestTagById(selectedId);
    if (!selectedTag) {
      continue;
    }

    if (selectedTag.related.includes(tag.id) || tag.related.includes(selectedId)) {
      score += RELATED_SCORE - selectedIndex;
    }
    if (tag.gradientCategory === selectedTag.gradientCategory) {
      score += SHARED_CATEGORY_SCORE;
    }
    score += sharedSurfaceCount(tag, selectedTag);
  }

  return selectedSet.has(tag.id) ? Number.MAX_SAFE_INTEGER : score;
}

function sharedSurfaceCount(tag: InterestTag, selectedTag: InterestTag): number {
  const surfaces: InterestSurfaceKey[] = [
    "dailyInspirations",
    "introChats",
    "exampleChats",
    "suggestions",
  ];

  return surfaces.reduce((count, surface) => {
    const selectedItems = new Set(selectedTag[surface]);
    return count + tag[surface].filter((item) => selectedItems.has(item)).length;
  }, 0);
}

function scoreContentId(
  id: string,
  surface: InterestSurfaceKey,
  selectedTags: readonly InterestTag[],
): number {
  let score = 0;

  for (let tagIndex = 0; tagIndex < selectedTags.length; tagIndex += 1) {
    const tag = selectedTags[tagIndex];
    const contentIndex = tag[surface].indexOf(id);
    if (contentIndex === -1) {
      continue;
    }
    score += MATCH_SCORE - tagIndex * 100 - contentIndex;
  }

  return score;
}

function getContentPriority(
  id: string,
  surface: InterestSurfaceKey,
  selectedTags: readonly InterestTag[],
): number {
  let priority = Number.MAX_SAFE_INTEGER;

  for (let tagIndex = 0; tagIndex < selectedTags.length; tagIndex += 1) {
    const tag = selectedTags[tagIndex];
    const contentIndex = tag[surface].indexOf(id);
    if (contentIndex === -1) {
      continue;
    }
    priority = Math.min(priority, tagIndex * 100 + contentIndex);
  }

  return priority;
}

function scoreContentCategory(
  category: string | undefined,
  selectedTags: readonly InterestTag[],
): number {
  if (!category) {
    return 0;
  }

  return selectedTags.some((tag) => tag.gradientCategory === category)
    ? SHARED_CATEGORY_SCORE
    : 0;
}
