/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) reply-recovery decisions: the page adapter
 * over the shared Rust core Worker `sync` unit recovery ops (recoveryOps.ts).
 * Loaded only by the guarded branches of chatRecoveryVersionApply.ts,
 * chatRecoveryVersionRefresh.ts, recoveryEmbedSource.ts and
 * chatRecoveryReplyFields.ts, so default builds never bundle it.
 *
 * Rust (packages/openmates-rust/src/web_stream) decides; the page keeps fetch,
 * IndexedDB and TOON decoding. Public functions keep the TypeScript semantics
 * of the originals (same results, same error messages); no TypeScript fallback.
 */
import type { Chat } from '../../../types/chat';
import { syncCall } from './syncUnitClient';

/** `chatAfterRecoveredReply`: a newer local snapshot wins, else raise the version fence. */
export async function chatAfterRecoveredReply(current: Chat | null, baseline: Chat, committedVersion: number, now: number): Promise<Chat> {
	const latest = current ?? baseline;
	const outcome = await syncCall('recoveryApply', {
		latest: {
			messages_v: latest.messages_v,
			last_edited_overall_timestamp: latest.last_edited_overall_timestamp,
			updated_at: latest.updated_at,
		},
		committedVersion,
		now,
	});
	if (outcome.keep) return latest;
	const { keep: _keep, ...fence } = outcome;
	// JSON carries NaN as null; the TypeScript Math.max result was NaN.
	const restored = Object.fromEntries(Object.entries(fence).map(([key, value]) => [key, value === null ? NaN : value]));
	return { ...latest, ...restored };
}

export async function windowVersion(chatId: string, result: unknown): Promise<number | null> {
	return (await syncCall('recoveryWindowVersion', { chatId, result })).version;
}

export async function assistantVersion(chatId: string, assistantMessageId: string, userMessageId: string, result: unknown): Promise<number | null> {
	return (await syncCall('recoveryAssistantVersion', { chatId, assistantMessageId, userMessageId, result })).version;
}

export async function isUnwrittenInitialDiffRead(status: number, detail: unknown, version: number): Promise<boolean> {
	return (await syncCall('recoveryInitialDiff', { status, detail, version })).unwritten;
}

/** Catalog identity; `fields` is the decoded TOON object when the page had to read it. */
export async function catalogContext(
	producerApp: unknown, producerSkill: unknown, fields: Record<string, unknown> | null,
): Promise<{ app_id: string; skill_id: string } | null> {
	const outcome = await syncCall('recoveryCatalog', {
		...(producerApp === undefined ? {} : { producerApp }),
		...(producerSkill === undefined ? {} : { producerSkill }),
		...(fields ? { fields } : {}),
	});
	if (outcome.kind === 'none') return null;
	if (outcome.kind === 'invalid') throw new Error('Recovered embed catalog identity was invalid.');
	return { app_id: outcome.app_id, skill_id: outcome.skill_id };
}

const HISTORY_ERRORS = {
	mismatch: 'Sealed embed does not contain the expected historical source.',
	mail_fields: 'Sealed mail source has invalid fields.',
	document_body: 'Sealed document source has no supported historical body.',
	format: 'Historical recovery does not know this embed source format.',
} as const;

export async function historySource(type: string, decoded: unknown): Promise<string> {
	const outcome = await syncCall('recoveryHistorySource', { type, decoded });
	if (outcome.kind === 'error') throw new Error(HISTORY_ERRORS[outcome.code]);
	if (outcome.kind === 'source') return outcome.source;
	// Key order of the sealed model is the page's to print; Rust only picks the field.
	return JSON.stringify((decoded as Record<string, unknown>)[outcome.field], null, 2);
}
