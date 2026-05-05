// frontend/packages/ui/src/services/pendingAIResponses.ts
// Tracks AI responses that couldn't be sent to the server (ai_response_completed)
// because the WebSocket was disconnected at the moment streaming finished.
//
// Only message_id + chat_id are stored (no plaintext content) so localStorage
// stays safe. On reconnect, the full message is loaded from IndexedDB and
// sendCompletedAIResponseImpl is called again to encrypt + send.
//
// The queue survives page reloads but is cleared on logout so stale entries
// from previous sessions are never replayed.

const STORAGE_KEY = "openmates_pending_ai_responses";

interface PendingAIResponse {
	message_id: string;
	chat_id: string;
}

export function getPendingAIResponses(): PendingAIResponse[] {
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (!raw) return [];
		const parsed = JSON.parse(raw);
		if (!Array.isArray(parsed)) return [];
		return parsed;
	} catch {
		return [];
	}
}

export function addPendingAIResponse(message_id: string, chat_id: string): void {
	try {
		const current = getPendingAIResponses();
		if (!current.some((r) => r.message_id === message_id)) {
			current.push({ message_id, chat_id });
			localStorage.setItem(STORAGE_KEY, JSON.stringify(current));
			console.warn(
				`[PendingAIResponses] Queued AI response ${message_id} for reconnect send. Total pending: ${current.length}`
			);
		}
	} catch (error) {
		console.error(`[PendingAIResponses] Failed to queue AI response ${message_id}:`, error);
	}
}

export function removePendingAIResponse(message_id: string): void {
	try {
		const current = getPendingAIResponses();
		const updated = current.filter((r) => r.message_id !== message_id);
		if (updated.length === 0) {
			localStorage.removeItem(STORAGE_KEY);
		} else {
			localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
		}
	} catch (error) {
		console.error(`[PendingAIResponses] Failed to remove AI response ${message_id}:`, error);
	}
}

export function clearAllPendingAIResponses(): void {
	try {
		localStorage.removeItem(STORAGE_KEY);
		console.debug("[PendingAIResponses] Cleared all pending AI responses");
	} catch (error) {
		console.error("[PendingAIResponses] Failed to clear pending AI responses:", error);
	}
}
