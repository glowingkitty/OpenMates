/**
 * Flag branch for the assistant render plan used by the synchronous message
 * mapper in ChatHistory.svelte.
 *
 * Flag off (default): exactly the previous synchronous createAssistantRenderPlan
 * call, so output and bundle stay unchanged (the Rust branch below is statically
 * dead and its dynamic import is eliminated by the build).
 *
 * Flag on (VITE_OPENMATES_RUST_CORE=1): the shared Rust `parse` unit decides the
 * blocks asynchronously. The mapper stays synchronous and reads the resolved
 * plan from a per-message cache; a miss starts the (serialized per message)
 * async computation and returns null, and `onRenderPlanReady` tells the page to
 * remap that message once the plan is available. There is no TypeScript
 * fallback for block decisions: a refused call is logged and the message keeps
 * its last resolved document.
 *
 * spec: specifications/surfaces/sdk#sdk.client.thin-platform-boundary
 */
import {
	createAssistantRenderPlan,
	type AssistantRenderPlan,
	type CreateAssistantRenderPlanOptions,
} from '../../../message_parsing/streamingMessageBlocks';

const RUST_PARSE_BUILD: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === '1';

type PlanOptions = Omit<CreateAssistantRenderPlanOptions, 'previous'>;
interface MessageState {
	/** Key of the newest request: markdown + phase + chat id. */
	requested: string;
	/** Key of the plan stored in the page plan map. */
	resolved: string | null;
	chain: Promise<void>;
	/** Consecutive failed requests; picks the delay before the next attempt. */
	failures: number;
}

/** Delay before a failed plan request is tried again (last value repeats). */
const RETRY_DELAYS_MS = [1_000, 3_000, 10_000, 30_000];

const states = new Map<string, MessageState>();
const readyListeners = new Set<(messageId: string) => void>();
let generation = 0;

function keyOf(markdown: string, options: PlanOptions): string {
	return `${options.phase}\u0000${options.chatId ?? ''}\u0000${markdown}`;
}

/** Subscribe to "plan for this message resolved"; returns the unsubscribe. */
export function onRenderPlanReady(listener: (messageId: string) => void): () => void {
	readyListeners.add(listener);
	return () => { readyListeners.delete(listener); };
}

/** True when render plans resolve asynchronously (flag-on build). */
export function renderPlansAreAsync(): boolean {
	return RUST_PARSE_BUILD;
}

/** Forget in-flight and cached state (account switch / chat teardown). */
export function resetRenderPlanState(): void {
	generation++;
	states.clear();
}

function schedule(
	messageId: string,
	markdown: string,
	options: PlanOptions,
	plans: Map<string, AssistantRenderPlan>,
	state: MessageState,
	key: string,
): void {
	const startedIn = generation;
	state.chain = state.chain.then(async () => {
		// A newer request (or a reset) superseded this one; only the newest needs a plan.
		if (startedIn !== generation || state.requested !== key) return;
		try {
			const { createAssistantRenderPlanRust } = await import('./rustAssistantRenderPlan');
			const plan = await createAssistantRenderPlanRust(markdown, { ...options, previous: plans.get(messageId) });
			if (startedIn !== generation) return;
			plans.set(messageId, plan);
			state.resolved = key;
			state.failures = 0;
			for (const listener of readyListeners) listener(messageId);
		} catch (error) {
			console.error('[rust-parse] assistant render plan failed', error);
			retryAfterFailure(messageId, state, key, startedIn);
		}
	});
}

/**
 * A failed request (the parse unit did not answer) must not leave the message
 * without a plan for the rest of the page's life: forget the request after a
 * growing delay and ask the page to remap, which requests the plan again.
 */
function retryAfterFailure(messageId: string, state: MessageState, key: string, startedIn: number): void {
	const delay = RETRY_DELAYS_MS[Math.min(state.failures, RETRY_DELAYS_MS.length - 1)];
	state.failures++;
	setTimeout(() => {
		if (startedIn !== generation || state.requested !== key || state.resolved === key) return;
		state.requested = '';
		for (const listener of readyListeners) listener(messageId);
	}, delay);
}

/**
 * True after a plan request for this message failed and no plan has resolved
 * since. The page then shows the plain text instead of an empty message.
 */
export function renderPlanRequestFailed(messageId: string): boolean {
	return (states.get(messageId)?.failures ?? 0) > 0;
}

/**
 * Returns the plan for this exact source, or null when it is still resolving
 * (flag on only). `plans` holds the newest resolved plan per message (the
 * `previous` for the next diff and the stale document shown while resolving).
 */
export function resolveAssistantRenderPlan(
	messageId: string,
	markdown: string,
	options: PlanOptions,
	plans: Map<string, AssistantRenderPlan>,
): AssistantRenderPlan | null {
	if (!RUST_PARSE_BUILD) {
		const plan = createAssistantRenderPlan(markdown, { ...options, previous: plans.get(messageId) });
		plans.set(messageId, plan);
		return plan;
	}
	const key = keyOf(markdown, options);
	let state = states.get(messageId);
	if (!state) {
		state = { requested: '', resolved: null, chain: Promise.resolve(), failures: 0 };
		states.set(messageId, state);
	}
	if (state.resolved === key) return plans.get(messageId) ?? null;
	if (state.requested !== key) {
		state.requested = key;
		schedule(messageId, markdown, options, plans, state, key);
	}
	return null;
}
