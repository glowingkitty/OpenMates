/**
 * Flag switch for the app settings/memories request decisions. Default builds
 * run the TypeScript policy (appSettingsRequestPolicy.ts) unchanged; with
 * VITE_OPENMATES_RUST_CORE=1 the shared Rust Worker `settings` unit decides and
 * there is no TypeScript fallback. The const-false branch is dead-code
 * eliminated from flag-off builds, so no Rust adapter ships there.
 */
import { buildMemoryRequestMessage } from '../utils/appMemoryRequests';
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
