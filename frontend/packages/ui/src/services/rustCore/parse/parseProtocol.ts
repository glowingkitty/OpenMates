/**
 * `parse` unit protocol of the shared Rust core Worker (unitPort.ts wire v1).
 *
 * Pure decisions of the shared Rust render-plan block model
 * (packages/openmates-rust/src/web_parse/blocks.rs, mirroring the pure parts of
 * message_parsing/streamingMessageBlocks.ts). Compiled TipTap documents are
 * produced by the page compiler and cross the boundary only as opaque JSON.
 */
import type { UnitProtocol } from '../host/unitPort';

export type ParsePhase = 'streaming' | 'final';
export interface ParseBlockRef { id: string; markdown: string }
/** Previous plan summary the Rust planner diffs against (null = none). */
export interface ParsePrevious { phase: ParsePhase; committed: ParseBlockRef[]; tail: ParseBlockRef | null }
export type ParseOperation =
	| { kind: 'append-blocks'; blockIds: string[] }
	| { kind: 'replace-tail' }
	| { kind: 'commit-tail' }
	| { kind: 'replace-block'; index: number; blockId: string }
	| { kind: 'delete-block'; index: number; blockId: string }
	| { kind: 'convergence-failure'; reason: 'non-local-divergence' };
/** `reuse` is the previous committed index whose compiled document is reused; null means compile. */
export interface ParsePlan {
	committed: Array<ParseBlockRef & { reuse: number | null }>;
	tail: string | null;
	operations: ParseOperation[];
	failed: boolean;
}
export interface ParseNormalized { appSkillIds: string[]; blocks: Array<{ id: string; nodeTypes: string[] }> }

export interface ParseUnitProtocol extends UnitProtocol {
	planBlocks: { request: { markdown: string; phase: ParsePhase; previous: string }; response: ParsePlan };
	normalizePlan: { request: { plan: string }; response: ParseNormalized };
	/** Read projection without voice-delivery cues (voiceDeliveryCues.ts semantics). */
	stripVoiceCues: { request: { markdown: string }; response: string };
	/** Parent embed ids a saved image answer needs read (generatedImageRecovery.ts lostImageParents). */
	imageRecoveryParents: { request: { source: string }; response: string[] };
	/** Recovered document (or null) from the resolved parents aligned with imageRecoveryParents (JSON array text). */
	recoverGeneratedImages: { request: { source: string; parents: string }; response: Record<string, unknown> | null };
}

/** Worker module exports (snake_case, JSON strings) of browser_parse.rs. */
export interface ParseBinding {
	parse_plan_blocks(markdown: string, phase: string, previousJson: string): string;
	parse_normalize_plan(planJson: string): string;
	parse_strip_voice_cues(markdown: string): string;
	parse_image_recovery_parents(sourceJson: string): string;
	parse_recover_generated_images(sourceJson: string, parentsJson: string): string;
}

const BINDING_EXPORTS: readonly (keyof ParseBinding)[] = [
	'parse_plan_blocks', 'parse_normalize_plan', 'parse_strip_voice_cues',
	'parse_image_recovery_parents', 'parse_recover_generated_images',
];

export function isParseBinding(value: unknown): value is ParseBinding {
	if (typeof value !== 'object' || value === null) return false;
	const binding = value as Record<string, unknown>;
	return BINDING_EXPORTS.every((name) => typeof binding[name] === 'function');
}
