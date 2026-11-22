/**
 * Sub-chat spawn decisions answered by the Rust core (`openmates_sdk::web_subchat`).
 * spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
 *
 * The core builds the child chat shell (encrypted title/category/icon, focus id) and
 * decides the Plan-assumption link PATCH and its backoff. This file only forwards JSON
 * to the chatState unit and performs the HTTP request the core describes.
 */
import { getApiEndpoint } from '../../../config/api';
import { chatStateCall } from './chatListUnitClient';

export interface SpawnChildPayload {
	id?: string;
	chat_id?: string;
	title?: string;
	prompt?: string;
	category?: string;
	icon?: string;
	focus_id?: string | null;
	project_base?: { project_id: string } | null;
	link?: { kind: 'assumption' | 'task'; plan_id: string; id: string } | null;
}

export interface SubchatShell {
	chat: Record<string, unknown>;
	project_id: string | null;
}

interface LinkRequest { method: string; path: string; body: unknown }
interface LinkRetry { retry: boolean; delay_ms?: number; warn?: boolean }

const decide = (op: string, input: unknown) => chatStateCall('subchatDecide', { op, input });

function toBase64(bytes: Uint8Array): string {
	let binary = '';
	for (const byte of bytes) binary += String.fromCharCode(byte);
	return btoa(binary);
}

/** Builds the child chat record from one spawn child and the parent's key and metadata. */
export async function rustSubchatShell(args: {
	parentChatId: string; parentKey: Uint8Array; userId?: string; now: number; child: SpawnChildPayload;
}): Promise<SubchatShell> {
	const answer = await decide('subchatShell', {
		parent_chat_id: args.parentChatId, parent_key: toBase64(args.parentKey),
		user_id: args.userId, now: args.now, child: args.child,
	});
	return answer as SubchatShell;
}

/** Links a Plan assumption to the child chat; retries while the assumption is not created yet, never throws. */
export async function linkSubChatAssumption(chatId: string, link: SpawnChildPayload['link']): Promise<void> {
	const request = (await decide('subchatLinkRequest', { chat_id: chatId, link })) as LinkRequest | null;
	if (!request) return;
	for (let attempt = 1; ; attempt++) {
		try {
			const response = await fetch(getApiEndpoint(request.path), {
				method: request.method, credentials: 'include',
				headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request.body),
			});
			if (response.ok) return;
		} catch (error) {
			console.warn('[subchat] assumption link request failed', error);
		}
		const next = (await decide('subchatLinkRetry', { attempt })) as LinkRetry;
		if (!next.retry) {
			console.warn(`[subchat] could not link assumption to sub-chat ${chatId}; the Plan or assumption is missing`);
			return;
		}
		await new Promise((resolve) => setTimeout(resolve, next.delay_ms));
	}
}
