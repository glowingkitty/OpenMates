/**
 * Recovery delivery of a generated image child's version N+1
 * (`images-generate.revision.same-embed-new-version`; VITE_OPENMATES_RUST_CORE
 * builds only). The server seals two outputs per change: `(embed, N+1)` (the
 * `send_embed_data` payload with `revision`) and `(diff, N+1)` (its
 * snapshot-only history row). Contract:
 * docs/plans/image-edit-as-embed-version/wire-contract.md ("The same event
 * arrives through recovery").
 *
 * Glue only: the Rust core decides whether an output is a child revision, writes
 * a missing version through the same `prepare_child_revision` path the live
 * event uses, and decides from the canonical rows whether that exact version is
 * stored and which digest is acknowledged (`child_revision_embed_receipt`,
 * `child_revision_row_receipt`). The head keeps the hash of the message that
 * created the image and history rows open with the parent's key; the ordinary
 * recovery checks (sealed changing message, HKDF of the child id) do not apply.
 * Nothing is acknowledged unless Rust returns `verified`: the output stays
 * pending and is retried.
 */
import type { ChatSynchronizationService } from '../../chatSyncService';
import type { CanonicalEmbedWriteLease } from '../../canonicalEmbedWriteCoordinator';
import { UnitPortError, type UnitPort } from '../host/unitPort';
import type { StreamCompletionInput } from '../embedWriteAdapter';
import type { EmbedWriteProtocol } from './embedDataProtocol';
import type { RevisionRecoveryReceipt } from './childRevisionProtocol';

type WriteUnit = UnitPort<EmbedWriteProtocol>;
type Read = { status: number; body: unknown };

/** The fields of a recovery output this module routes on. */
export interface RecoveredRevisionOutput {
	target_chat_id: string;
	subject_id: string;
	output_kind: string;
	output_version: number;
}

/** What the recovery loop acknowledges (`canonical_digest`, `canonical_source`). */
export interface RecoveredRevisionReceipt {
	digest: string;
	source: 'head' | 'version_row';
}

/** Page IO (injected so the order is unit-tested without a network or socket). */
export interface RecoveredRevisionIO {
	unit: WriteUnit;
	/** Installs the chat key and loads the stored keys of `embedId` and `parentId` in the Worker. */
	loadKeys(chatId: string, embedId: string, parentId: string | null): Promise<void>;
	/** Canonical head row (`GET /v1/embeds/chats/{chat}/embeds/{id}` `.embed`), null on 404. */
	readHead(chatId: string, embedId: string): Promise<Record<string, unknown> | null>;
	/** Bounded-v1 page of `version` (`body` undefined on 404). */
	readVersion(chatId: string, embedId: string, version: number): Promise<Read>;
	/** Writes the sealed revision through the live Rust child revision path (under the caller's lease). */
	writeRevision(content: Record<string, unknown>): Promise<void>;
}

/** Recovery receipts need the Rust core; flag-off builds keep the ordinary path unchanged. */
const RUST_CORE_BUILD: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === '1';

/**
 * True when this embed/diff output is a child revision (embed: the sealed
 * payload carries `revision`; diff: Rust `is_child_revision_row`). Always false
 * in builds without the Rust core.
 */
export async function isRecoveredChildRevision(unit: () => Promise<WriteUnit>, output: RecoveredRevisionOutput,
	content: Record<string, unknown>): Promise<boolean> {
	if (!RUST_CORE_BUILD) return false;
	if (output.output_kind === 'embed') return content.revision !== undefined && content.revision !== null;
	if (output.output_kind !== 'diff' || output.output_version < 2) return false;
	return (await unit()).request('isChildRevisionRow', { row: content });
}

function verified(receipt: RevisionRecoveryReceipt): RecoveredRevisionReceipt {
	if (receipt.state !== 'verified') throw new UnitPortError('embed_revision_not_applied');
	return { digest: receipt.canonical_digest, source: receipt.canonical_source };
}

async function page(io: RecoveredRevisionIO, chatId: string, embedId: string, version: number): Promise<unknown> {
	const read = await io.readVersion(chatId, embedId, version);
	if (read.status === 404) return undefined;
	if (read.status !== 200 || read.body === undefined) throw new UnitPortError('embed_revision_canonical_read_failed');
	return read.body;
}

/**
 * `(embed, N+1)`: verify against the canonical head; when the server does not
 * hold N+1 yet, write it through the live child revision path, then verify.
 * A head past N+1 is verified by its bounded-v1 row N+1.
 */
export async function verifyRecoveredRevisionEmbed(io: RecoveredRevisionIO, output: RecoveredRevisionOutput,
	content: Record<string, unknown>): Promise<RecoveredRevisionReceipt> {
	const chatId = output.target_chat_id;
	const embedId = output.subject_id;
	if (content.embed_id !== embedId) throw new UnitPortError('embed_revision_head_mismatch');
	const parentId = typeof content.parent_embed_id === 'string' && content.parent_embed_id ? content.parent_embed_id : null;
	await io.loadKeys(chatId, embedId, parentId);
	const sealed = content as unknown as StreamCompletionInput;
	const ask = async (head: Record<string, unknown>): Promise<RevisionRecoveryReceipt> => {
		const receipt = await io.unit.request('childRevisionRecoveryReceipt', { sealed, head });
		if (receipt.state !== 'version_page_required') return receipt;
		const body = await page(io, chatId, embedId, receipt.version);
		if (body === undefined) throw new UnitPortError('embed_revision_canonical_read_failed');
		return io.unit.request('childRevisionRecoveryReceipt', { sealed, head, page: body });
	};
	let head = await io.readHead(chatId, embedId);
	// No server head at all: the child itself is not stored yet; stays pending.
	if (!head) throw new UnitPortError('embed_revision_head_missing');
	let receipt = await ask(head);
	if (receipt.state === 'not_applied') {
		await io.writeRevision(content);
		head = await io.readHead(chatId, embedId);
		if (!head) throw new UnitPortError('embed_revision_head_missing');
		receipt = await ask(head);
	}
	return verified(receipt);
}

/**
 * `(diff, N+1)`: the row opens with the key of the canonical head's parent
 * (children inherit it), never HKDF(chat key, child id). Resolves only when
 * the server stores exactly this row; before the head reached N+1 it stays
 * pending (the embed output writes it).
 */
export async function verifyRecoveredRevisionRow(io: RecoveredRevisionIO, output: RecoveredRevisionOutput,
	content: Record<string, unknown>): Promise<RecoveredRevisionReceipt> {
	const chatId = output.target_chat_id;
	const embedId = output.subject_id;
	if (content.embed_id !== embedId || content.version_number !== output.output_version) {
		throw new UnitPortError('embed_revision_head_mismatch');
	}
	const head = await io.readHead(chatId, embedId);
	if (!head) throw new UnitPortError('embed_revision_head_missing');
	const parentId = typeof head.parent_embed_id === 'string' && head.parent_embed_id ? head.parent_embed_id : null;
	// Rust refuses a root head; the parent id only routes the key load.
	await io.loadKeys(chatId, embedId, parentId);
	const body = await page(io, chatId, embedId, output.output_version);
	return verified(await io.unit.request('childRevisionRowReceipt', { row: content, head, page: body }));
}

/** Production IO: the Rust embed writer unit, the canonical HTTP reads and the live child revision write. */
export async function recoveredRevisionIO(write: (content: Record<string, unknown>) => Promise<void>): Promise<RecoveredRevisionIO> {
	// Compile-time gate: builds without the Rust core must not bundle its embed units.
	if (!RUST_CORE_BUILD) throw new UnitPortError('embed_revision_requires_rust_core');
	const { rustEmbedWriter } = await import('./embedWriteSession');
	const { loadEmbedWriteKeys, readCanonicalVersion } = await import('./rustStreamedEmbedWrite');
	const { chatDB } = await import('../../db');
	const { getApiEndpoint, storageArchiveFetch } = await import('../../../config/api');
	const { unit } = await rustEmbedWriter();
	return {
		unit,
		loadKeys: (chatId, embedId, parentId) => loadEmbedWriteKeys(unit, chatId, embedId, parentId),
		async readHead(chatId, embedId) {
			const chat = await chatDB.getChat(chatId);
			const query = chat?.team_id ? `?team_id=${encodeURIComponent(chat.team_id)}` : '';
			const response = await storageArchiveFetch(getApiEndpoint(
				`/v1/embeds/chats/${encodeURIComponent(chatId)}/embeds/${encodeURIComponent(embedId)}${query}`
			), { credentials: 'include' });
			if (response.status === 404) return null;
			if (!response.ok) throw new UnitPortError('embed_revision_canonical_read_failed');
			const embed = ((await response.json()) as { embed?: unknown }).embed;
			if (typeof embed !== 'object' || embed === null) throw new UnitPortError('embed_revision_head_mismatch');
			return embed as Record<string, unknown>;
		},
		readVersion: readCanonicalVersion,
		writeRevision: write
	};
}

/**
 * Recovery-loop entry (inside the per-embed canonical write lease): the
 * receipt of a child revision output, or null for every other output (the
 * ordinary recovery path handles it unchanged).
 */
export async function recoveredChildRevisionReceipt(service: ChatSynchronizationService, lease: CanonicalEmbedWriteLease,
	output: RecoveredRevisionOutput, content: Record<string, unknown>): Promise<RecoveredRevisionReceipt | null> {
	// Compile-time gate, so the Rust imports below are dropped from builds without the core.
	if (!RUST_CORE_BUILD) return null;
	const writer = async (): Promise<WriteUnit> => (await (await import('./embedWriteSession')).rustEmbedWriter()).unit;
	if (!(await isRecoveredChildRevision(writer, output, content))) return null;
	const io = await recoveredRevisionIO(async (sealed) => {
		const { writeStreamedEmbedInRust } = await import('./rustStreamedEmbedWrite');
		const embedData = sealed as unknown as Parameters<typeof writeStreamedEmbedInRust>[1];
		if (!(await writeStreamedEmbedInRust(service, embedData, lease, false))) throw new UnitPortError('embed_revision_requires_rust_core');
	});
	return output.output_kind === 'embed'
		? verifyRecoveredRevisionEmbed(io, output, content)
		: verifyRecoveredRevisionRow(io, output, content);
}
