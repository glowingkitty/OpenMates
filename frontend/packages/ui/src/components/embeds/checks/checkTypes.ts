/**
 * frontend/packages/ui/src/components/embeds/checks/checkTypes.ts
 *
 * View-model types for Check embeds (preview and fullscreen). Props-driven and
 * type-only: callers map the Check API contract onto these shapes.
 * Spec: specifications/features/checks (checks.gui.preview, checks.gui.fullscreen).
 */

export type CheckLifecycle = 'draft' | 'ready' | 'archived';

export type CheckAggregate =
  | 'queued' | 'running' | 'passed' | 'failed' | 'error' | 'blocked'
  | 'waiting_for_confirmation' | 'cancelled' | 'never_run';

export type SourceKind =
  | 'e2e' | 'unit' | 'integration' | 'static_analysis' | 'deterministic_audit'
  | 'ai_evaluation' | 'human_confirmation';

export type SourceRole = 'required' | 'supporting';

export type SourceResultStatus =
  | 'queued' | 'running' | 'passed' | 'failed' | 'error' | 'cancelled' | 'waiting_for_confirmation';

export type HumanDecision = 'confirmed' | 'rejected';

export interface SourceAiResult {
  question: string;
  verdict: 'pass' | 'fail' | 'inconclusive';
  score: number;
  threshold: number;
  feedback: string;
}

export interface SourceHumanResult {
  instruction: string;
  decision?: HumanDecision;
  confirmer_label?: string;
  confirmed_at?: string;
}

export interface SourceResultView {
  status: SourceResultStatus;
  summary: string;
  /** Deterministic e2e/unit sources may reference a test_result embed. */
  test_result_embed_id?: string;
  ai?: SourceAiResult;
  human?: SourceHumanResult;
}

export interface SourceView {
  binding_id: string;
  kind: SourceKind;
  role: SourceRole;
  title: string;
  ref_label: string;
  latest_result?: SourceResultView;
}

export interface RunView {
  run_id: string;
  revision_number: number;
  subject_label: string;
  status: CheckAggregate;
  started_at: string;
  finished_at?: string;
  /** True when the run was for an older Check revision or other files than current. */
  stale?: boolean;
}

export interface CheckView {
  id: string;
  title: string;
  description: string;
  status: CheckLifecycle;
  revision_number: number;
  aggregate: CheckAggregate;
  stale: boolean;
  stale_reason?: string;
  requires_deterministic: boolean;
  covered_claims: string[];
  sources: SourceView[];
  runs: RunView[];
}
