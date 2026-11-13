/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) page adapter for the deferred draft deletion
 * replay check of the shared Rust core Worker `sendPrep` unit. Loaded only by the
 * guarded branch of sendersSync.ts. There is no TypeScript fallback.
 */
import type { DeferredDeleteFacts } from './sendPrepProtocol';
import { sendPrepCall } from './sendPrepUnitClient';

export async function rustIsDeferredDeleteReplayable(facts: DeferredDeleteFacts): Promise<boolean> {
	return (await sendPrepCall('deferredDeleteReplay', facts)).eligible;
}
