/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) Apps result retention and outbox/library
 * policy over the shared Rust core Worker `apps` unit. Loaded only by guarded
 * branches of appsWorkspaceResultsService.ts, appsWorkspaceResultOutbox.ts and
 * appsWorkspaceLibraryService.ts, so default builds never bundle it.
 *
 * Rust (web_apps/results.rs) decides: result status, which results become child
 * rows (as paths into the page's own response object), their stable ids and
 * types, the asset ids deferred to the server, persisted linked ids, result
 * count, the graph-size bound, the merged accepted task ids, the outbox record
 * scope check and recommendation freshness. The page keeps WebCrypto,
 * IndexedDB, the embed store, Fetch and the service's in-memory state (passed
 * in as `RetentionDeps`). Parity: web_apps/results_ts_vectors.json.
 *
 * Deliberately TypeScript (synchronous Svelte `$derived` reads, which cannot await
 * the Worker): `freshAppsRecommendations` inside AppsWorkspace.svelte,
 * `isAppsSearchSaved`, the preview item projection, and the recent-chats service
 * (its decisions are interleaved with IndexedDB reads).
 */
import { get, type Readable } from 'svelte/store';
import { EMBED_CHILD_TYPE_MAP } from '../../../data/embedRegistry.generated';
import { appsResultRequestFields } from '../../../utils/appsResultRequestFields';
import { userProfile } from '../../../stores/userProfile';
import { embedStore } from '../../embedStore';
import { encryptWithEmbedKey, generateEmbedKey, wrapEmbedKeyWithChatKey, wrapEmbedKeyWithMasterKey } from '../../cryptoService';
import { getTeamKey } from '../../teamService';
import { unwrapAnonymousChatKey, wrapAnonymousChatKey } from '../../anonymousChatKeyWrapping';
import { makePendingAppsResultId, type AppsCipherRow, type AppsResultGraph, type PendingAppsResult } from '../../appsWorkspaceResultOutbox';
import type { AppsResultSaveState, RetainAppsResultInput } from '../../appsWorkspaceResultsService';
import { appsCall } from './appsUnitClient';

type Context = { teamId: string | null; guest: boolean; userId: string | null; wrapper?: string };
type Graph = AppsResultGraph & { created_at: number };

/** In-memory state and IO helpers owned by appsWorkspaceResultsService.ts. */
export interface RetentionDeps {
	activeKeys: Map<string, Uint8Array>;
	activeContexts: Map<string, Context>;
	pendingGraphs: Map<string, PendingAppsResult>;
	saveStates: Readable<Record<string, AppsResultSaveState>>;
	guestRecords(): Promise<Graph[]>;
	getAppsResult(rootId: string, teamId?: string | null): Promise<void>;
	hydrateRows(rows: AppsCipherRow[], appId: string, skillId: string, key: Uint8Array, createdAt: number, expectedUserId?: string): Promise<void>;
	writeGuest(graph: Graph): Promise<void>;
	assertSameAuthenticatedUser(userId: string): void;
	stagePendingAppsResult(record: PendingAppsResult): Promise<void>;
	setSaveState(record: PendingAppsResult, state: AppsResultSaveState): void;
	notifyResultUpdated(record: PendingAppsResult): void;
	uploadPendingResult(record: PendingAppsResult): Promise<void>;
	uploadGraph(graph: Graph, expectedUserId: string): Promise<{ root_embed_id: string; linked_embed_ids: string[] }>;
	refreshAppsGeneratedAssetUrls(embedIds: string[], teamId?: string | null, expectedUserId?: string | null): Promise<void>;
	saveKey(userId: string, teamId: string | null | undefined, rootId: string): string;
	savePendingError(rootId: string): Error;
}

/** The value at a Rust path (object keys and array indices) inside the page's response. */
function at(root: unknown, path: (string | number)[]): unknown {
	return path.reduce<unknown>((value, segment) => (value as Record<string | number, unknown>)[segment], root);
}

/** `retainAppsResult` with every result-graph decision taken by Rust. */
export async function retainRustAppsResult(args: RetainAppsResultInput, deps: RetentionDeps): Promise<string> {
	const rootId = args.rootEmbedId || args.requestId || crypto.randomUUID();
	const guest = Boolean(args.guest);
	if (!guest && !get(userProfile).user_id) throw new Error('Apps result owner is unavailable');
	const submittedContext = { teamId: args.teamId ?? null, guest, userId: guest ? null : get(userProfile).user_id };
	const previousContext = deps.activeContexts.get(rootId);
	if (previousContext && (previousContext.teamId !== submittedContext.teamId || previousContext.guest !== guest || previousContext.userId !== submittedContext.userId)) {
		throw new Error('Apps result account changed while request was processing');
	}
	if (!previousContext) deps.activeContexts.set(rootId, submittedContext);
	const existingGuest = guest ? (await deps.guestRecords()).find((row) => row.root_embed_id === rootId) : undefined;
	let key = deps.activeKeys.get(rootId) ?? await embedStore.getEmbedKey(rootId);
	if (!key && existingGuest) key = await unwrapAnonymousChatKey(existingGuest.encrypted_embed_key);
	if (!key && !guest && !args.newRequest) {
		// A missing remote result is a new result (the TypeScript service's contract).
		try { await deps.getAppsResult(rootId, args.teamId); key = deps.activeKeys.get(rootId) ?? await embedStore.getEmbedKey(rootId); } catch { /* New result. */ }
	}
	key ||= generateEmbedKey();
	deps.activeKeys.set(rootId, key);
	const childType = EMBED_CHILD_TYPE_MAP[`${args.appId}:${args.skillId}`];
	const facts = JSON.stringify({ appId: args.appId, skillId: args.skillId, rootId, childType: childType || null });
	const response = JSON.stringify(args.response ?? null);
	let plan = await appsCall('retentionPlan', { facts, response, previous: '' });
	if (plan.kind === 'ok' && plan.status === 'processing') {
		// Only a processing row merges the prior row's accepted task ids.
		const previous = await embedStore.get(`embed:${rootId}`);
		if (previous && typeof previous === 'object' && typeof previous.content === 'string') {
			plan = await appsCall('retentionPlan', { facts, response, previous: previous.content });
		}
	}
	if (plan.kind === 'error') throw new Error(plan.message);
	const { status, persistedIds, taskIds: acceptedTaskIds } = plan;
	const results = plan.results.map((path) => at(args.response, path));
	const resultIds = new Set(plan.resultIds);
	const children: AppsCipherRow[] = [];
	for (const child of plan.children) {
		const result = at(args.response, child.path);
		const resultObject = result && typeof result === 'object' ? result as Record<string, unknown> : {};
		children.push({
			embed_id: child.id,
			encrypted_type: await encryptWithEmbedKey(child.type, key),
			encrypted_content: await encryptWithEmbedKey(JSON.stringify({ app_id: args.appId, skill_id: args.skillId, ...resultObject, result }), key),
			status: 'finished',
			parent_embed_id: rootId,
		});
	}
	const childIds = children.map((child) => child.embed_id);
	const responseData = at(args.response, plan.metadataPath);
	const metadata = responseData && typeof responseData === 'object' ? responseData as Record<string, unknown> : {};
	const { results: _nestedResults, ...responseMetadata } = metadata;
	const rootContent = {
		...appsResultRequestFields(args.input),
		...responseMetadata,
		app_id: args.appId, skill_id: args.skillId, input: args.input,
		...(args.requestText ? { request_text: args.requestText } : {}),
		...(acceptedTaskIds.length ? { task_ids: acceptedTaskIds } : {}),
		...(childType ? {} : { results }), result_count: plan.resultCount,
		embed_ids: [...childIds, ...persistedIds], status,
	};
	const root: AppsCipherRow = {
		embed_id: rootId,
		encrypted_type: await encryptWithEmbedKey('app_skill_use', key),
		encrypted_content: await encryptWithEmbedKey(JSON.stringify(rootContent), key),
		status,
		embed_ids: [...childIds, ...persistedIds],
	};
	const createdAt = existingGuest?.created_at ?? Math.floor(Date.now() / 1000);
	const wrapper = previousContext?.wrapper || existingGuest?.encrypted_embed_key || (guest ? await wrapAnonymousChatKey(key)
		: args.teamId ? await wrapEmbedKeyWithChatKey(key, await getTeamKey(args.teamId))
		: await wrapEmbedKeyWithMasterKey(key));
	if (!wrapper) throw new Error('Apps result key could not be wrapped');
	deps.activeContexts.set(rootId, { ...submittedContext, wrapper });
	const graph: Graph = { app_id: args.appId, skill_id: args.skillId, root_embed_id: rootId,
		...(args.teamId ? { team_id: args.teamId } : {}), embeds: [root, ...children], linked_embed_ids: persistedIds,
		encrypted_embed_key: wrapper, created_at: createdAt };
	if (guest) {
		await deps.hydrateRows([root, ...children], args.appId, args.skillId, key, createdAt);
		await deps.writeGuest(graph);
	} else {
		const userId = submittedContext.userId as string;
		deps.assertSameAuthenticatedUser(userId);
		if (args.persistence === 'background') {
			const record: PendingAppsResult = {
				id: makePendingAppsResultId(userId, submittedContext.teamId, rootId),
				userId, teamId: submittedContext.teamId, rootEmbedId: rootId,
				revision: crypto.randomUUID(), graph, updatedAt: Date.now(), deferredChildIds: Array.from(resultIds),
			};
			deps.pendingGraphs.set(record.id, record);
			let staged = false;
			// An unstaged record surfaces as the visible `error` save state (TypeScript service contract).
			try { await deps.stagePendingAppsResult(record); staged = true; deps.setSaveState(record, 'saving'); }
			catch { deps.setSaveState(record, 'error'); }
			deps.assertSameAuthenticatedUser(userId);
			await deps.hydrateRows([root, ...children.filter((row) => !resultIds.has(row.embed_id))], args.appId, args.skillId, key, createdAt, userId);
			deps.notifyResultUpdated(record);
			if (staged && (status !== 'processing' || acceptedTaskIds.length)) {
				const uploaded = deps.uploadPendingResult(record);
				if (resultIds.size) {
					await uploaded;
					if (get(deps.saveStates)[deps.saveKey(record.userId, record.teamId, rootId)] !== 'saved') throw deps.savePendingError(rootId);
				}
			}
		} else {
			const saved = await deps.uploadGraph(graph, userId);
			deps.assertSameAuthenticatedUser(userId);
			const linked = new Set(saved.linked_embed_ids);
			await deps.hydrateRows([root, ...children.filter((row) => !linked.has(row.embed_id))], args.appId, args.skillId, key, createdAt, userId);
		}
	}
	if (status === 'finished') {
		// The encrypted graph is already durable; reopening the result retries a failed URL refresh.
		try { if (['images', 'audio', 'music', 'videos'].includes(args.appId)) await deps.refreshAppsGeneratedAssetUrls(childIds, args.teamId, submittedContext.userId); }
		catch { /* Reopening the result retries the refresh. */ }
	}
	return rootId;
}

/** `validateRecord` in Rust: throws the outbox's own error for a mis-scoped record. */
export async function assertRustOutboxScope(record: PendingAppsResult): Promise<void> {
	const scope = JSON.stringify({ id: record.id, userId: record.userId, teamId: record.teamId, rootEmbedId: record.rootEmbedId,
		revision: record.revision, graphRootEmbedId: record.graph.root_embed_id, graphTeamId: record.graph.team_id ?? null });
	if (!await appsCall('outboxScopeValid', { scope })) throw new Error('Invalid Apps result outbox scope');
}

/** `freshAppsRecommendations` in Rust (async callers; the sync Svelte `$derived` keeps the TS filter). */
export async function freshRustRecommendations<T>(items: T[], now = Date.now()): Promise<T[]> {
	const fresh = await appsCall('freshRecommendations', { items: JSON.stringify(items), now });
	return fresh.map((index) => items[index]);
}
