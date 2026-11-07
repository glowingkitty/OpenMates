/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) decisions of the app settings/memories
 * permission request handler: the page adapter over the shared Rust core Worker
 * `settings` unit. Loaded only through appSettingsRequestDecisions.ts, whose
 * guarded branch default builds drop.
 *
 * Rust (web_settings.rs) decides dialog categories, the answered
 * guard and the persisted request message; the page passes facts in and keeps
 * IndexedDB, the decrypted entry store and the dialog.
 */
import type { RequestCategory } from '../../appSettingsRequestPolicy';
import type { ConfirmOutcome, ResponseCategory, ResponseKeyPlan } from '../../appSettingsResponsePolicy';
import type { PrivacyEntryPlan } from '../../privacyEntryPolicy';
import type { SettingsRequestMessageOutcome } from './settingsProtocol';
import { settingsCall } from './settingsClient';

export async function rustPlanRequestCategories(
	requestedKeys: string[], entryCounts: ReadonlyMap<string, number>,
): Promise<{ categories: RequestCategory[]; validKeys: string[] }> {
	return settingsCall('categoryPlan', { requestedKeys: JSON.stringify(requestedKeys), counts: JSON.stringify(Object.fromEntries(entryCounts)) });
}

export function rustIsRequestAnswered(systemContents: string[], userMessageId: string): Promise<boolean> {
	return settingsCall('requestAnswered', { systemContents: JSON.stringify(systemContents), userMessageId });
}

/** Builds the persisted request message; the TypeScript error texts are preserved as thrown errors. */
export async function rustBuildRequestMessage(params: {
	userMessageId: string; requestId: string; requestedKeys: string[]; createdAt: number;
	entryCounts: ReadonlyMap<string, number | null>; voice: boolean;
}): Promise<Extract<SettingsRequestMessageOutcome, { kind: 'ok' }>['message']> {
	const outcome = await settingsCall('buildRequestMessage', {
		userMessageId: params.userMessageId, requestId: params.requestId, requestedKeys: JSON.stringify(params.requestedKeys),
		createdAt: JSON.stringify(params.createdAt), counts: JSON.stringify(Object.fromEntries(params.entryCounts)), voice: params.voice,
	});
	if (outcome.kind === 'error') throw new Error(outcome.message);
	return outcome.message;
}

export function rustPlanSelectedKeys(selectedKeys: string[]): Promise<ResponseKeyPlan[]> {
	return settingsCall('planSelectedKeys', { selectedKeys: JSON.stringify(selectedKeys) });
}

export function rustSelectEntryIds(entryIds: string[], selection: string[] | null): Promise<string[]> {
	return settingsCall('selectEntryIds', { entryIds: JSON.stringify(entryIds), selection: JSON.stringify(selection) });
}

export function rustResponseCategories(
	categories: Array<{ appId: string; itemType: string }>, released: Array<{ app_id: string; item_key: string }>,
): Promise<ResponseCategory[]> {
	return settingsCall('responseCategories', { categories: JSON.stringify(categories), released: JSON.stringify(released) });
}

export function rustConfirmOutcome(releasedCount: number, voice: boolean, hasMessageId: boolean): Promise<ConfirmOutcome> {
	return settingsCall('confirmOutcome', { releasedCount, voice, hasMessageId });
}

export function rustResponseContent(userMessageId: string, action: 'included' | 'rejected', categories?: ResponseCategory[]): Promise<string> {
	return settingsCall('responseContent', { userMessageId, action, categories: JSON.stringify(categories ?? null) });
}

/** Hydration plan of one decrypted privacy entry (personalDataStore); rejects `protocol` where the TS policy throws. */
export function rustPlanPrivacyEntry(itemType: string, data: unknown, defaultCategories: Record<string, boolean>): Promise<PrivacyEntryPlan> {
	return settingsCall('planPrivacyEntry', { itemType, data: JSON.stringify(data), defaultCategories: JSON.stringify(defaultCategories) });
}
