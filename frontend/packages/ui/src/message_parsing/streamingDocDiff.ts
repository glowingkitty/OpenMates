/**
 * Incremental ProseMirror document update utilities for streaming messages.
 *
 * Instead of using editor.commands.setContent() (which destroys ALL NodeViews and
 * remounts all embed Svelte components), this module computes minimal ProseMirror
 * transactions that only touch the changed regions of the document.
 *
 * Architecture context: See docs/architecture/streaming-embeds.md (WI-2)
 *
 * Key insight: ProseMirror's Fragment.findDiffStart() / Fragment.findDiffEnd()
 * give us the byte-precise boundaries of what changed between two document trees.
 * We use these to build a single ReplaceStep transaction that swaps only the
 * changed slice, leaving all unmodified NodeViews (and their mounted Svelte
 * components) untouched.
 *
 * For "scattered" changes (e.g., grouping moves embeds from multiple positions),
 * we iterate top-level nodes to find all disjoint change regions and apply
 * multiple ReplaceSteps in a single transaction (reverse order to preserve offsets).
 */

import type { Editor } from "@tiptap/core";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import { ReplaceStep } from "@tiptap/pm/transform";

/**
 * Result of attempting an incremental update.
 * - applied: true if the transaction was dispatched successfully
 * - fallback: true if we fell back to setContent() (should not happen for common patterns)
 */
export interface IncrementalUpdateResult {
  applied: boolean;
  fallback: boolean;
  stepsApplied: number;
}

/**
 * A single change region in the document (from position → to position in old doc,
 * and the new content slice to replace it with).
 */
interface ChangeRegion {
  /** Start position in the OLD document */
  fromOld: number;
  /** End position in the OLD document */
  toOld: number;
  /** Start position in the NEW document */
  fromNew: number;
  /** End position in the NEW document */
  toNew: number;
}

/**
 * Apply an incremental update to a TipTap editor by computing the minimal diff
 * between the current document and the new content.
 *
 * This is the main entry point for streaming updates. It:
 * 1. Parses the new content into a ProseMirror doc
 * 2. Computes change regions between current and new doc
 * 3. Applies ReplaceStep transactions for each change region
 *
 * If the diff produces no changes (content is identical), it returns early.
 *
 * @param editor - The TipTap editor instance
 * @param newContent - The new TipTap JSON content (output of processContent)
 * @returns Result indicating whether the update was applied incrementally
 */
export function applyIncrementalUpdate(
  editor: Editor,
  newContent: Record<string, unknown>,
): IncrementalUpdateResult {
  if (!editor || editor.isDestroyed) {
    return { applied: false, fallback: false, stepsApplied: 0 };
  }

  const { state, view } = editor;
  const oldDoc = state.doc;

  // Parse the new content into a ProseMirror Node using the editor's schema
  let newDoc: ProseMirrorNode;
  try {
    newDoc = state.schema.nodeFromJSON(newContent);
  } catch (err) {
    console.warn(
      "[streamingDocDiff] Failed to parse new content, skipping incremental update:",
      err,
    );
    return { applied: false, fallback: false, stepsApplied: 0 };
  }

  // Quick equality check — if docs are identical, nothing to do
  if (oldDoc.eq(newDoc)) {
    return { applied: true, fallback: false, stepsApplied: 0 };
  }

  // Find all change regions between the two documents
  const regions = findChangeRegions(oldDoc, newDoc);

  if (regions.length === 0) {
    // Docs differ but we couldn't find specific regions — this shouldn't happen
    // but handle gracefully
    console.warn(
      "[streamingDocDiff] Docs differ but no change regions found, falling back",
    );
    return { applied: false, fallback: false, stepsApplied: 0 };
  }

  // Build and dispatch a transaction with ReplaceSteps for each change region.
  // Process regions in REVERSE order to preserve position offsets (later regions
  // are unaffected by earlier replacements).
  const tr = state.tr;
  let stepsApplied = 0;

  // Sort regions by fromOld in descending order for reverse processing
  const sortedRegions = [...regions].sort((a, b) => b.fromOld - a.fromOld);

  for (const region of sortedRegions) {
    try {
      // Extract the replacement slice from the new document
      const newSlice = newDoc.slice(region.fromNew, region.toNew);

      // Create and apply the replace step
      const step = new ReplaceStep(region.fromOld, region.toOld, newSlice);
      const result = tr.maybeStep(step);

      if (result.failed) {
        console.warn(
          "[streamingDocDiff] ReplaceStep failed:",
          result.failed,
          "region:",
          region,
        );
        // If any step fails, abort the whole transaction and return failure
        // The caller will fall back to setContent()
        return { applied: false, fallback: false, stepsApplied: 0 };
      }

      stepsApplied++;
    } catch (err) {
      console.warn(
        "[streamingDocDiff] Error applying ReplaceStep:",
        err,
        "region:",
        region,
      );
      return { applied: false, fallback: false, stepsApplied: 0 };
    }
  }

  // Dispatch the transaction (all steps applied atomically)
  if (stepsApplied > 0) {
    view.dispatch(tr);
  }

  return { applied: true, fallback: false, stepsApplied };
}

/**
 * Find all change regions between two ProseMirror documents.
 *
 * Strategy:
 * 1. Try simple diff first (findDiffStart / findDiffEnd on the full content).
 *    This handles the common streaming case: text appended at the end, or a
 *    single contiguous edit region.
 *
 * 2. If the simple diff covers the entire document (indicating scattered changes),
 *    fall back to per-top-level-node comparison to find individual change regions.
 *    This handles the grouping case where embeds are moved/merged across the document.
 *
 * @param oldDoc - The current ProseMirror document
 * @param newDoc - The target ProseMirror document
 * @returns Array of change regions, may be empty if docs are identical
 */
function findChangeRegions(
  oldDoc: ProseMirrorNode,
  newDoc: ProseMirrorNode,
): ChangeRegion[] {
  const oldContent = oldDoc.content;
  const newContent = newDoc.content;

  // Step 1: Simple diff using Fragment.findDiffStart / findDiffEnd
  const diffStart = oldContent.findDiffStart(newContent);
  if (diffStart === null || diffStart === undefined) {
    // No differences found (documents are identical at the content level)
    return [];
  }

  const diffEnd = oldContent.findDiffEnd(newContent);
  if (diffEnd === null || diffEnd === undefined) {
    // This shouldn't happen if diffStart found something, but handle gracefully.
    // Treat the entire tail as changed.
    return [
      {
        fromOld: diffStart,
        toOld: oldDoc.content.size,
        fromNew: diffStart,
        toNew: newDoc.content.size,
      },
    ];
  }

  // diffEnd returns { a: posInOld, b: posInNew }
  const endOld = diffEnd.a;
  const endNew = diffEnd.b;

  // Ensure the range is valid (end >= start)
  // findDiffEnd scans from the end backward, so endOld/endNew are the positions
  // where the suffix match begins. We need max(start, end) for a valid range.
  const fromOld = diffStart;
  const toOld = Math.max(diffStart, endOld);
  const fromNew = diffStart;
  const toNew = Math.max(diffStart, endNew);

  // Check if this single region is "reasonable" — if it covers less than 80%
  // of both documents, accept it as a single contiguous change.
  const oldSize = oldContent.size;
  const newSize = newContent.size;
  const changedOldRatio = oldSize > 0 ? (toOld - fromOld) / oldSize : 1;
  const changedNewRatio = newSize > 0 ? (toNew - fromNew) / newSize : 1;

  // Threshold: If < 80% of doc is changed, use the single region
  const SCATTERED_THRESHOLD = 0.8;

  if (
    changedOldRatio < SCATTERED_THRESHOLD &&
    changedNewRatio < SCATTERED_THRESHOLD
  ) {
    // Single contiguous change region — the common streaming case
    return [{ fromOld, toOld, fromNew, toNew }];
  }

  // Step 2: Scattered changes — compare top-level nodes individually
  // This handles the case where grouping moves embeds from multiple positions
  return findScatteredChangeRegions(oldDoc, newDoc);
}

/**
 * Compare two documents node-by-node at the top level to find all individual
 * change regions. This handles scattered changes like embed grouping where
 * nodes are moved/added/removed at different positions in the document.
 *
 * Algorithm: Walk both documents' top-level children simultaneously, comparing
 * each pair. When nodes differ, mark the region. When one doc has extra/fewer
 * nodes at the end, include those in the final region.
 */
function findScatteredChangeRegions(
  oldDoc: ProseMirrorNode,
  newDoc: ProseMirrorNode,
): ChangeRegion[] {
  const regions: ChangeRegion[] = [];
  const oldChildCount = oldDoc.childCount;
  const newChildCount = newDoc.childCount;
  const minCount = Math.min(oldChildCount, newChildCount);

  // Track positions as we walk through children
  // ProseMirror positions: doc starts at 0, first child content starts at 1
  // Each child node takes nodeSize positions (including open/close tokens)
  let oldPos = 0; // Position at start of current old child (inside doc)
  let newPos = 0; // Position at start of current new child (inside doc)

  // Track contiguous changed ranges to merge adjacent changes
  let rangeStartOld = -1;
  let rangeStartNew = -1;
  let rangeEndOld = -1;
  let rangeEndNew = -1;

  function flushRange() {
    if (rangeStartOld >= 0) {
      regions.push({
        fromOld: rangeStartOld,
        toOld: rangeEndOld,
        fromNew: rangeStartNew,
        toNew: rangeEndNew,
      });
      rangeStartOld = -1;
      rangeStartNew = -1;
      rangeEndOld = -1;
      rangeEndNew = -1;
    }
  }

  for (let i = 0; i < minCount; i++) {
    const oldChild = oldDoc.child(i);
    const newChild = newDoc.child(i);

    const oldChildStart = oldPos;
    const newChildStart = newPos;
    const oldChildEnd = oldPos + oldChild.nodeSize;
    const newChildEnd = newPos + newChild.nodeSize;

    if (!oldChild.eq(newChild)) {
      // This child differs — extend or start a new range
      if (rangeStartOld < 0) {
        rangeStartOld = oldChildStart;
        rangeStartNew = newChildStart;
      }
      rangeEndOld = oldChildEnd;
      rangeEndNew = newChildEnd;
    } else {
      // Children are identical — flush any accumulated range
      flushRange();
    }

    oldPos = oldChildEnd;
    newPos = newChildEnd;
  }

  // Handle trailing nodes (one doc has more children than the other)
  if (oldChildCount !== newChildCount) {
    if (rangeStartOld < 0) {
      rangeStartOld = oldPos;
      rangeStartNew = newPos;
    }

    // Include all remaining nodes from both docs
    let oldEnd = oldPos;
    for (let i = minCount; i < oldChildCount; i++) {
      oldEnd += oldDoc.child(i).nodeSize;
    }
    let newEnd = newPos;
    for (let i = minCount; i < newChildCount; i++) {
      newEnd += newDoc.child(i).nodeSize;
    }

    rangeEndOld = oldEnd;
    rangeEndNew = newEnd;
  }

  flushRange();

  return regions;
}
