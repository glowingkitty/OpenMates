/**
 * Worker-side op for the signup / pair / recovery-print policy served by the
 * shared Rust `web_auth_flow` export (spec: specifications/features/auth). The
 * call is pure and synchronous in Rust; this file only checks the binding and
 * forwards the JSON. Refusals are Rust's fixed codes (`flow_op`, `flow_args`).
 */
export interface RustAuthFlowBinding {
	web_auth_flow(name: string, argsJson: string): string;
}

export function hasAuthFlowBinding(value: unknown): value is RustAuthFlowBinding {
	return typeof (value as Partial<RustAuthFlowBinding> | null)?.web_auth_flow === 'function';
}

/** Runs one named flow call on the realm's WASM binding; `unavailable` when it lacks the export. */
export function runFlowOp(binding: unknown, name: string, argsJson: string): unknown {
	if (!hasAuthFlowBinding(binding)) throw 'unavailable';
	return JSON.parse(binding.web_auth_flow(name, argsJson));
}
