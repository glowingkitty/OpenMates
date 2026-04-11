/**
 * Skill Store Example Fullscreen Store.
 *
 * Holds a synthetic fullscreen embed state produced by the app-store
 * "Examples" section (SkillExamplesSection.svelte). ActiveChat subscribes
 * to this store and mounts the example inside its normal
 * `.fullscreen-embed-container` so skill examples open with the same
 * slide-up animation and data-driven routing as real chat embeds.
 *
 * Unlike real embeds, these are not persisted in embedStore and are not
 * fetched from the backend — the example props come from curated
 * `*Preview.examples.ts` fixtures captured from real skill runs.
 */

import { writable } from "svelte/store";

/**
 * Payload used to open a synthetic skill-example fullscreen inside
 * ActiveChat. `decodedContent` is what the fullscreen component receives
 * under `data.decodedContent`, and must include `app_id` + `skill_id`
 * so the embed registry can resolve the fullscreen component.
 */
export interface SkillStoreExampleFullscreen {
  /** Synthetic, unique-per-example id — used as ActiveChat's re-key token. */
  embedId: string;
  /** App id, e.g. "web". */
  appId: string;
  /** Skill id, e.g. "search". */
  skillId: string;
  /** Decoded content payload forwarded into the fullscreen component. */
  decodedContent: Record<string, unknown>;
}

export const skillStoreExampleFullscreenStore =
  writable<SkillStoreExampleFullscreen | null>(null);

export function openSkillStoreExampleFullscreen(
  payload: SkillStoreExampleFullscreen
): void {
  skillStoreExampleFullscreenStore.set(payload);
}

export function closeSkillStoreExampleFullscreen(): void {
  skillStoreExampleFullscreenStore.set(null);
}
