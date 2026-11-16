/**
 * Page client of the shared Worker's `presentRemote` unit (slides presentation
 * remote). The state format, embed-key encryption and ordering live in the Rust
 * core; this file only opens the unit port for the bound generation and forwards
 * calls. A `local_session` / `not_admitted` refusal asks once for the existing
 * server-checked session upgrade and resends. Failures reject with a
 * `UnitPortError` whose `code` is the core's stable code.
 */
import { requireSharedRustCore, type SharedRustCore } from '../host/sharedCoreRegistry';
import { createUnitPort, UnitPortError, type UnitPort } from '../host/unitPort';
import { withServerSession } from '../projects/projectTimelineClient';
import type { PresentRemoteState, PresentRemoteUnitProtocol } from './presentRemoteProtocol';

export type { PresentRemoteOrigin, PresentRemoteState } from './presentRemoteProtocol';

const BIND_WAIT_MS = 15_000;
const BIND_POLL_MS = 50;

interface Opened { core: SharedRustCore; generation: number; unit: UnitPort<PresentRemoteUnitProtocol> }
let current: { generation: number; opening: Promise<Opened> } | null = null;

async function boundGeneration(core: SharedRustCore): Promise<number> {
	const deadline = Date.now() + BIND_WAIT_MS;
	while (core.generation === null) {
		if (Date.now() >= deadline) throw new UnitPortError('present_remote_not_bound');
		await new Promise((resolve) => setTimeout(resolve, BIND_POLL_MS));
	}
	return core.generation;
}

async function open(core: SharedRustCore, generation: number): Promise<Opened> {
	const unit = createUnitPort<PresentRemoteUnitProtocol>(await core.openUnit('presentRemote'));
	core.onCrash(() => unit.close());
	return { core, generation, unit };
}

async function unit(): Promise<UnitPort<PresentRemoteUnitProtocol>> {
	const core = requireSharedRustCore();
	const generation = await boundGeneration(core);
	if (current?.generation === generation) {
		const opened = await current.opening;
		if (opened.core === core && !opened.unit.closed) return opened.unit;
	}
	const opening = open(core, generation);
	current = { generation, opening };
	opening.catch(() => { if (current?.opening === opening) current = null; });
	return (await opening).unit;
}

async function call<K extends keyof PresentRemoteUnitProtocol & string>(
	op: K, payload: PresentRemoteUnitProtocol[K]['request'],
): Promise<PresentRemoteUnitProtocol[K]['response']> {
	return withServerSession(async () => (await unit()).request(op, payload));
}

/** Encrypts the state with the deck's embed key (key resolved inside the Worker). */
export function encryptPresentRemoteState(state: PresentRemoteState): Promise<string> {
	return call('encrypt', { state });
}

/** Decrypts a relayed ciphertext; rejects when it belongs to another embed. */
export function decryptPresentRemoteState(embedId: string, ciphertext: string): Promise<PresentRemoteState> {
	return call('decrypt', { embedId, ciphertext });
}

/** Core ordering rule: true when the state should be applied. */
export function acceptPresentRemoteState(state: PresentRemoteState): Promise<boolean> {
	return call('accept', { state });
}
