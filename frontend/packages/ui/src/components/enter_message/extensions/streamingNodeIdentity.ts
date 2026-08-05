// frontend/packages/ui/src/components/enter_message/extensions/streamingNodeIdentity.ts
// Pure semantic identity checks for streamed embed NodeViews.
// Presentation metadata may change in place; persisted embed and normalized
// result-view descriptor identity determines whether remounting is necessary.
// Spec: docs/specs/streaming-message-render-convergence/spec.yml

interface LargePreviewIdentityAttrs {
  embedId?: unknown;
  embedRef?: unknown;
}

interface ResultViewIdentityAttrs {
  id?: unknown;
  mapEmbedRefs?: unknown;
  mapSourceRefs?: unknown;
  mapHighlightRefs?: unknown;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

export function hasStableLargePreviewIdentity(
  previous: LargePreviewIdentityAttrs,
  next: LargePreviewIdentityAttrs,
): boolean {
  if (previous.embedId && next.embedId) {
    return previous.embedId === next.embedId;
  }
  if (previous.embedRef && previous.embedRef === next.embedRef) return true;
  return false;
}

export function hasStableResultViewIdentity(
  previous: ResultViewIdentityAttrs,
  next: ResultViewIdentityAttrs,
): boolean {
  return (
    previous.id === next.id &&
    stringArray(previous.mapEmbedRefs).join("\u0000") ===
      stringArray(next.mapEmbedRefs).join("\u0000") &&
    stringArray(previous.mapSourceRefs).join("\u0000") ===
      stringArray(next.mapSourceRefs).join("\u0000") &&
    stringArray(previous.mapHighlightRefs).join("\u0000") ===
      stringArray(next.mapHighlightRefs).join("\u0000")
  );
}
