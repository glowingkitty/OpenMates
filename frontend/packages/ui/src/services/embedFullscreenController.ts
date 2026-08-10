// frontend/packages/ui/src/services/embedFullscreenController.ts
//
// Unified client-side controller for embed fullscreen routing.
// It keeps target resolution, canonical active-route writes, and parent-child
// back-stack behavior in one place while the existing fullscreen host continues
// to render via the embedfullscreen event listener.
// See docs/specs/unified-embed-fullscreen-routing/spec.yml.

import { writable } from "svelte/store";
import { activeEmbedStore } from "../stores/activeEmbedStore";
import { normalizeEmbedType as registryNormalizeEmbedType } from "../data/embedRegistry.generated";
import {
  hasFullscreenComponent,
  resolveRegistryKey,
} from "./embedFullscreenResolver";
import { embedStore } from "./embedStore";

export type FullscreenRouteOrigin = "direct" | "parent" | "hash" | "shared";

export interface FullscreenTargetResolution {
  targetEmbedId: string;
  focusChildEmbedId?: string;
}

export interface FullscreenRouteEntry {
  embedId: string;
  chatId: string | null;
}

export interface FullscreenRouteState {
  activeEmbedId: string | null;
  stack: FullscreenRouteEntry[];
}

export interface EmbedFullscreenDispatchDetail {
  embedId?: string | null;
  embedData?: unknown;
  decodedContent?: unknown;
  embedType?: string | null;
  attrs?: unknown;
  focusChildEmbedId?: string | null;
  highlightQuoteText?: string | null;
  focusLineRange?: { start: number; end: number } | null;
  focusSheetRange?: string | null;
  hasChatContext?: boolean;
}

export type ExampleFullscreenResolver = (
  embedId: string,
) => FullscreenTargetResolution | null;

const routeState = writable<FullscreenRouteState>({
  activeEmbedId: null,
  stack: [],
});

let currentRouteState: FullscreenRouteState = {
  activeEmbedId: null,
  stack: [],
};

routeState.subscribe((value) => {
  currentRouteState = value;
});

export const embedFullscreenRouteStore = {
  subscribe: routeState.subscribe,
};

function normalizeEmbedId(embedId: string): string {
  return embedId.startsWith("embed:") ? embedId.slice("embed:".length) : embedId;
}

function hasDirectFullscreen(
  embedType: string | null | undefined,
  decodedContent?: Record<string, unknown> | null,
): boolean {
  if (!embedType) return false;
  const registryKey = resolveRegistryKey(
    registryNormalizeEmbedType(embedType),
    decodedContent ?? undefined,
  );
  return !!registryKey && hasFullscreenComponent(registryKey);
}

export async function resolveEmbedFullscreenTarget(
  embedId: string,
  options: {
    embedType?: string | null;
    decodedContent?: Record<string, unknown> | null;
    exampleResolver?: ExampleFullscreenResolver;
  } = {},
): Promise<FullscreenTargetResolution> {
  const normalizedEmbedId = normalizeEmbedId(embedId);

  if (hasDirectFullscreen(options.embedType, options.decodedContent)) {
    return { targetEmbedId: normalizedEmbedId };
  }

  const exampleTarget = options.exampleResolver?.(normalizedEmbedId);
  if (exampleTarget) {
    return {
      targetEmbedId: normalizeEmbedId(exampleTarget.targetEmbedId),
      focusChildEmbedId: exampleTarget.focusChildEmbedId
        ? normalizeEmbedId(exampleTarget.focusChildEmbedId)
        : undefined,
    };
  }

  const storedTarget = await embedStore.resolveFullscreenTarget(normalizedEmbedId);
  return {
    targetEmbedId: normalizeEmbedId(storedTarget.targetEmbedId),
    focusChildEmbedId: storedTarget.focusChildEmbedId
      ? normalizeEmbedId(storedTarget.focusChildEmbedId)
      : undefined,
  };
}

export function setCanonicalFullscreenRoute(
  embedId: string,
  options: {
    chatId?: string | null;
    origin?: FullscreenRouteOrigin;
    previousVisibleEmbedId?: string | null;
  } = {},
): FullscreenRouteState {
  const normalizedEmbedId = normalizeEmbedId(embedId);
  const chatId = options.chatId ?? null;
  const nextStack = [...currentRouteState.stack];
  const previousVisibleEmbedId = options.previousVisibleEmbedId
    ? normalizeEmbedId(options.previousVisibleEmbedId)
    : null;

  if (previousVisibleEmbedId && previousVisibleEmbedId !== normalizedEmbedId) {
    const last = nextStack[nextStack.length - 1];
    if (last?.embedId !== previousVisibleEmbedId) {
      nextStack.push({ embedId: previousVisibleEmbedId, chatId });
    }
  } else if (options.origin !== "parent") {
    nextStack.length = 0;
  }

  activeEmbedStore.setActiveEmbed(normalizedEmbedId, chatId);
  const nextState = { activeEmbedId: normalizedEmbedId, stack: nextStack };
  routeState.set(nextState);
  return nextState;
}

export function setChildFullscreenRouteFromParent(
  childEmbedId: string,
  parentEmbedId: string,
  chatId: string | null = null,
): FullscreenRouteState {
  return setCanonicalFullscreenRoute(childEmbedId, {
    chatId,
    origin: "parent",
    previousVisibleEmbedId: parentEmbedId,
  });
}

export function restorePreviousFullscreenRoute(
  fallbackEmbedId?: string | null,
  chatId: string | null = null,
): FullscreenRouteEntry | null {
  const nextStack = [...currentRouteState.stack];
  const previous = nextStack.pop() ?? null;

  if (previous) {
    activeEmbedStore.setActiveEmbed(previous.embedId, previous.chatId);
    routeState.set({ activeEmbedId: previous.embedId, stack: nextStack });
    return previous;
  }

  if (fallbackEmbedId) {
    const normalizedFallback = normalizeEmbedId(fallbackEmbedId);
    activeEmbedStore.setActiveEmbed(normalizedFallback, chatId);
    routeState.set({ activeEmbedId: normalizedFallback, stack: [] });
    return { embedId: normalizedFallback, chatId };
  }

  activeEmbedStore.clearActiveEmbed();
  routeState.set({ activeEmbedId: null, stack: [] });
  return null;
}

export function clearFullscreenRoute(): void {
  activeEmbedStore.clearActiveEmbed();
  routeState.set({ activeEmbedId: null, stack: [] });
}

export function dispatchEmbedFullscreen(detail: EmbedFullscreenDispatchDetail): void {
  document.dispatchEvent(
    new CustomEvent("embedfullscreen", {
      detail,
      bubbles: true,
    }),
  );
}
