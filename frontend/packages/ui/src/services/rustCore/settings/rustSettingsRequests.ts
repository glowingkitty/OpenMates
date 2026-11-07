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
