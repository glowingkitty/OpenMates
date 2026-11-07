/**
 * Flag switch for the app settings/memories request decisions. Default builds
 * run the TypeScript policy (appSettingsRequestPolicy.ts) unchanged; with
 * VITE_OPENMATES_RUST_CORE=1 the shared Rust Worker `settings` unit decides and
 * there is no TypeScript fallback. The const-false branch is dead-code
 * eliminated from flag-off builds, so no Rust adapter ships there.
 */
import { buildMemoryRequestMessage } from '../utils/appMemoryRequests';
import {
  confirmOutcome, planSelectedKeys, responseCategories, responseContent, selectEntryIds,
  type ConfirmOutcome, type ResponseCategory, type ResponseKeyPlan,
} from './appSettingsResponsePolicy';
import { isRequestAnswered, planRequestCategories, type RequestCategory } from './appSettingsRequestPolicy';

const RUST_SETTINGS_BUILD: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === '1';
type RustRequests = typeof import('./rustCore/settings/rustSettingsRequests');
let rustRequests: Promise<RustRequests> | null = null;
function rust(): Promise<RustRequests> | null {
  if (!RUST_SETTINGS_BUILD) return null;
  rustRequests ??= import('./rustCore/settings/rustSettingsRequests');
  return rustRequests;
}

export async function decideRequestCategories(
  requestedKeys: string[], entryCounts: ReadonlyMap<string, number>,
): Promise<{ categories: RequestCategory[]; validKeys: string[] }> {
  const adapter = rust();
  return adapter ? (await adapter).rustPlanRequestCategories(requestedKeys, entryCounts) : planRequestCategories(requestedKeys, entryCounts);
}

export async function decideRequestAnswered(systemContents: string[], userMessageId: string): Promise<boolean> {
  const adapter = rust();
  return adapter ? (await adapter).rustIsRequestAnswered(systemContents, userMessageId) : isRequestAnswered(systemContents, userMessageId);
}

export async function decideRequestMessage(params: {
  userMessageId: string; requestId: string; requestedKeys: string[]; createdAt: number;
  entryCounts: ReadonlyMap<string, number | null>; responseTransport?: 'voice';
}) {
  const adapter = rust();
  if (adapter) return (await adapter).rustBuildRequestMessage({ ...params, voice: params.responseTransport === 'voice' });
  return buildMemoryRequestMessage(params);
}

export async function decideSelectedKeys(selectedKeys: string[]): Promise<ResponseKeyPlan[]> {
  const adapter = rust();
  return adapter ? (await adapter).rustPlanSelectedKeys(selectedKeys) : planSelectedKeys(selectedKeys);
}

export async function decideSelectedEntryIds(entryIds: string[], selection: string[] | null): Promise<string[]> {
  const adapter = rust();
  return adapter ? (await adapter).rustSelectEntryIds(entryIds, selection) : selectEntryIds(entryIds, selection);
}

export async function decideResponseCategories(
  categories: Array<{ appId: string; itemType: string }>, released: Array<{ app_id: string; item_key: string }>,
): Promise<ResponseCategory[]> {
  const adapter = rust();
  return adapter ? (await adapter).rustResponseCategories(categories, released) : responseCategories(categories, released);
}

export async function decideConfirmOutcome(releasedCount: number, voice: boolean, hasMessageId: boolean): Promise<ConfirmOutcome> {
  const adapter = rust();
  return adapter ? (await adapter).rustConfirmOutcome(releasedCount, voice, hasMessageId) : confirmOutcome(releasedCount, voice, hasMessageId);
}

export async function decideResponseContent(
  userMessageId: string, action: 'included' | 'rejected', categories?: ResponseCategory[],
): Promise<string> {
  const adapter = rust();
  return adapter ? (await adapter).rustResponseContent(userMessageId, action, categories) : responseContent(userMessageId, action, categories);
}
