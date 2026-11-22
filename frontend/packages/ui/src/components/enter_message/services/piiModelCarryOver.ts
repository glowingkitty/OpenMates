/** Keeps still-valid model highlights visible while a fresh scan is pending. */
import type { PIIMatch } from './piiDetectionService';

const MODEL_ID_PREFIX = 'pii-model-';

/**
 * Model detections of the previous preview that still match the current text
 * at the same offsets, are not excluded and do not overlap the basic matches.
 * Without this, re-running the preview (after one highlight was kept as
 * original) briefly or permanently drops every model highlight, although the
 * send path still replaces them.
 */
export function carryOverModelMatches(
  previous: readonly PIIMatch[], text: string, basic: readonly PIIMatch[], excludedIds: ReadonlySet<string>,
): PIIMatch[] {
  const carried = previous.filter(match =>
    match.id.startsWith(MODEL_ID_PREFIX) && !excludedIds.has(match.id) &&
    text.slice(match.startIndex, match.endIndex) === match.match &&
    !basic.some(other => match.startIndex < other.endIndex && match.endIndex > other.startIndex));
  return [...basic, ...carried].sort((a, b) => a.startIndex - b.startIndex);
}
