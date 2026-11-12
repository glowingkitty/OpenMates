/**
 * Page hook that asks the history bootstrap for its SERVER-CHECKED Rust session
 * (VITE_OPENMATES_RUST_CORE builds only).
 *
 * The page's history session starts as a local-only admission (`restore_local`,
 * cached reads, no server authority) and is upgraded on the same Worker to the
 * server-checked admission (`restore_existing`) only when a read needs the
 * server. A sibling unit that writes to the server (embed edits) borrows that
 * same client and is refused `local_session` until then. This registry lets
 * such a unit's page client request the existing upgrade (the bootstrap's own
 * `ensureSession`) instead of a second admission or key hand-over.
 *
 * The web app registers once (`rustChatHistoryBootstrap.ts`); with nothing
 * registered (flag-off build, history opted out) there is no upgrade to ask for.
 * The bootstrap also reports each server-checked admission
 * (`notifyServerCheckedSession`), so work deferred on a local session (the
 * chat-open notice reconcile) runs once one exists, without causing an upgrade.
 */

/** Resolves once the server-checked session is admitted; rejects with its failure. */
export type ServerCheckedSessionAdmission = () => Promise<void>;

let admission: ServerCheckedSessionAdmission | null = null;
const admittedListeners = new Set<() => void>();

/** Registers the single admission hook; returns an unregister bound to this registration. */
export function registerServerCheckedSession(next: ServerCheckedSessionAdmission): () => void {
	admission = next;
	return () => { if (admission === next) admission = null; };
}

/**
 * Asks for the server-checked session, at most `timeoutMs`. Resolves `true`
 * once admitted, `false` when no hook is registered; rejects with
 * `server_session_timeout` past the bound or with the admission's failure.
 */
export async function ensureServerCheckedSession(timeoutMs: number): Promise<boolean> {
	const current = admission;
	if (!current) return false;
	let timer: ReturnType<typeof setTimeout> | undefined;
	const timeout = new Promise<never>((_, reject) => {
		timer = setTimeout(() => reject(new Error('server_session_timeout')), timeoutMs);
	});
	try {
		await Promise.race([current(), timeout]);
		return true;
	} finally {
		clearTimeout(timer);
	}
}

/** Runs `listener` once, on the next server-checked admission; returns its removal. */
export function onceServerCheckedSession(listener: () => void): () => void {
	const once = () => { admittedListeners.delete(once); listener(); };
	admittedListeners.add(once);
	return () => { admittedListeners.delete(once); };
}

/** Called by the bootstrap after each server-checked admission. */
export function notifyServerCheckedSession(): void {
	for (const listener of [...admittedListeners]) listener();
}
