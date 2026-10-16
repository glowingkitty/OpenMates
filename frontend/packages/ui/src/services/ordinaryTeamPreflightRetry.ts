/** Persist one ciphertext-only ordinary Team preflight across an uncertain ACK. */
import type { Message } from "../types/chat";

const ORDINARY_TEAM_PREFLIGHT_PREFIX = "openmates:ordinary-team-preflight:v1:";

export interface OrdinaryTeamPreflightIdentity {
	accountId: string;
	teamId: string;
	chatId: string;
	messageId: string;
	content: string | undefined;
	senderName: string | undefined;
	role: Message["role"];
	createdAt: number;
	chatKey: Uint8Array;
	encryptedChatKey: string;
}

interface StoredOrdinaryTeamPreflight {
	version: 1;
	account_id: string;
	team_id: string;
	chat_id: string;
	message_id: string;
	message_mac: string;
	preflight_payload: Record<string, unknown>;
}

export function ordinaryTeamPreflightStorageKey(chatId: string, messageId: string): string {
	return `${ORDINARY_TEAM_PREFLIGHT_PREFIX}${chatId}:${messageId}`;
}

async function ordinaryTeamMessageMac(identity: OrdinaryTeamPreflightIdentity): Promise<string> {
	const key = await crypto.subtle.importKey(
		"raw", Uint8Array.from(identity.chatKey), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
	);
	const signed = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(JSON.stringify([
		identity.accountId, identity.teamId, identity.chatId, identity.messageId,
		identity.role, identity.createdAt, identity.content, identity.senderName
	])));
	return Array.from(new Uint8Array(signed), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function assertCiphertextOnlyTeamPreflight(preflight: Record<string, unknown>, identity: OrdinaryTeamPreflightIdentity): void {
	const inference = preflight.inference_request as Record<string, unknown> | undefined;
	const message = inference?.message as Record<string, unknown> | undefined;
	const encrypted = preflight.encrypted_user_message as Record<string, unknown> | undefined;
	if (
		preflight.chat_id !== identity.chatId || preflight.team_id !== identity.teamId ||
		preflight.message_id !== identity.messageId || preflight.encrypted_chat_key !== identity.encryptedChatKey ||
		typeof preflight.turn_id !== "string" || !preflight.turn_id ||
		typeof preflight.expected_messages_v !== "number" ||
		inference?.chat_id !== identity.chatId || inference.team_id !== identity.teamId ||
		message?.message_id !== identity.messageId || message.encrypted_content !== encrypted?.encrypted_content ||
		encrypted?.client_message_id !== identity.messageId || !encrypted.encrypted_content ||
		(message && "content" in message) ||
		["message_history", "team_ai_invocation", "embeds", "mentioned_settings_memories_cleartext",
			"connected_account_directory", "connected_account_token_refs", "active_focus_id"].some((field) => field in inference)
	) {
		throw new Error("Ordinary Team preflight must preserve one scoped ciphertext-only message.");
	}
}

export async function retainOrReuseOrdinaryTeamPreflight(
	identity: OrdinaryTeamPreflightIdentity,
	candidate: Record<string, unknown>,
	storage: Pick<Storage, "getItem" | "setItem"> = sessionStorage,
): Promise<Record<string, unknown>> {
	const key = ordinaryTeamPreflightStorageKey(identity.chatId, identity.messageId);
	const messageMac = await ordinaryTeamMessageMac(identity);
	const raw = storage.getItem(key);
	if (raw) {
		let saved: StoredOrdinaryTeamPreflight;
		try { saved = JSON.parse(raw) as StoredOrdinaryTeamPreflight; }
		catch { throw new Error("Stored ordinary Team preflight is invalid."); }
		if (
			saved.version !== 1 || saved.account_id !== identity.accountId ||
			saved.team_id !== identity.teamId || saved.chat_id !== identity.chatId ||
			saved.message_id !== identity.messageId || saved.message_mac !== messageMac ||
			!saved.preflight_payload
		) {
			throw new Error("Ordinary Team retry changed account, scope, key, or message content.");
		}
		assertCiphertextOnlyTeamPreflight(saved.preflight_payload, identity);
		return saved.preflight_payload;
	}
	assertCiphertextOnlyTeamPreflight(candidate, identity);
	const snapshot: StoredOrdinaryTeamPreflight = {
		version: 1, account_id: identity.accountId, team_id: identity.teamId,
		chat_id: identity.chatId, message_id: identity.messageId, message_mac: messageMac,
		preflight_payload: JSON.parse(JSON.stringify(candidate)) as Record<string, unknown>
	};
	// A failed write must stop the send: after a lost ACK, only this exact snapshot
	// can replay the committed transaction without changing ciphertext or commitment.
	storage.setItem(key, JSON.stringify(snapshot));
	return snapshot.preflight_payload;
}

