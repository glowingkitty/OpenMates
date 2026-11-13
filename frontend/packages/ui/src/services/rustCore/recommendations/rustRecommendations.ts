/**
 * Typed page-side wrapper of the chat Recommendations policy, which lives only in
 * the Rust client core (packages/openmates-rust/src/client/recommendations.rs).
 *
 * Calls run in the shared Worker's `parse` unit (stateless, pre-bind). There is
 * no TypeScript fallback: a refused or failed call rejects with the unit's fixed code.
 * Contract types: ../../../types/recommendations.ts.
 */
import type {
	ChatRecommendation,
	ContextEntryHistoryEvent,
	MemoryWriteUndoneEvent,
	ReconcileRecommendationsInput,
} from '../../../types/recommendations';
import { parseCall } from '../parse/parseClient';

/** Applies dismiss/resolved/duplicate/memory-match rules and caps 3 per kind. */
export function reconcileRecommendations(input: ReconcileRecommendationsInput): Promise<ChatRecommendation[]> {
	return parseCall('reconcileRecommendations', { input });
}

/** Validated JSON content of the `role: system` context_entry chat message. */
export function buildContextEntryEvent(event: ContextEntryHistoryEvent): Promise<string> {
	return parseCall('buildContextEntryEvent', { event });
}

/** The event, or null when the content is not a valid context_entry event. */
export function parseContextEntryEvent(content: string): Promise<ContextEntryHistoryEvent | null> {
	return parseCall('parseContextEntryEvent', { content });
}

/** The undone marker of an assistant Memory write, or null for any other content. */
export function parseMemoryWriteUndone(content: string): Promise<MemoryWriteUndoneEvent | null> {
	return parseCall('parseMemoryWriteUndone', { content });
}
