// frontend/packages/ui/src/components/embeds/code/testResultContent.ts
//
// Presentation-only normalisation of decoded `test_result` embed content for the
// web preview and fullscreen. The run itself, evidence encryption and staleness
// policy are owned by the Rust core and the Code worker; this file only coerces
// the decoded fields into typed rows and formats them for display.
// Shape source: backend/apps/code/tasks/test_result_embed.py.
// Tests: frontend/apps/web_app/tests/components/test-result-embed.spec.ts.

import { getApiEndpoint } from '../../../config/api';

export type TestResultKind = 'unit' | 'browser' | 'cli';
export type TestResultRunStatus = 'passed' | 'failed' | 'error' | 'cancelled' | 'timed_out';
export type TestResultRowStatus = 'passed' | 'failed' | 'skipped' | 'error';

export interface TestResultStep {
  name: string;
  startMs: number;
  endMs: number;
  status: string;
  error?: string;
  isPreview: boolean;
  command?: string;
  output?: string;
}

export interface TestResultTest {
  name: string;
  status: string;
  durationMs?: number;
  error?: string;
}

export interface TestResultEvidence {
  kind: string;
  path: string;
  mimeType?: string;
  assetId?: string;
  variant?: string;
  atStep?: number;
}

export interface TestResultView {
  kind: TestResultKind;
  target: string;
  runStatus: TestResultRunStatus;
  exitCode?: number;
  durationMs?: number;
  passed: number;
  failed: number;
  skipped: number;
  error?: string;
  previewStepIndex?: number;
  tests: TestResultTest[];
  steps: TestResultStep[];
  evidence: TestResultEvidence[];
  isCurrent: boolean;
  staleReason?: string;
}

/** Resolves stored evidence to a short-lived playable/displayable URL. */
export type EvidenceUrlResolver = (evidence: TestResultEvidence) => Promise<string | null>;

const KINDS: TestResultKind[] = ['unit', 'browser', 'cli'];
const RUN_STATUSES: TestResultRunStatus[] = ['passed', 'failed', 'error', 'cancelled', 'timed_out'];

const str = (value: unknown): string | undefined =>
  typeof value === 'string' && value.length > 0 ? value : undefined;
const num = (value: unknown): number | undefined =>
  typeof value === 'number' && Number.isFinite(value) ? value : undefined;
const records = (value: unknown): Record<string, unknown>[] =>
  Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => !!item && typeof item === 'object' && !Array.isArray(item))
    : [];

export function parseTestResult(content: Record<string, unknown> | undefined | null): TestResultView {
  const dc = content ?? {};
  const kind = KINDS.find((k) => k === dc.kind) ?? 'unit';
  const runStatus = RUN_STATUSES.find((s) => s === dc.run_status) ?? 'error';
  return {
    kind,
    target: str(dc.target) ?? '',
    runStatus,
    exitCode: num(dc.exit_code),
    durationMs: num(dc.duration_ms),
    passed: num(dc.passed) ?? 0,
    failed: num(dc.failed) ?? 0,
    skipped: num(dc.skipped) ?? 0,
    error: str(dc.error),
    previewStepIndex: num(dc.preview_step_index),
    tests: records(dc.tests).map((t) => ({
      name: str(t.name) ?? '',
      status: str(t.status) ?? 'passed',
      durationMs: num(t.duration_ms),
      error: str(t.error),
    })),
    steps: records(dc.steps).map((s) => ({
      name: str(s.name) ?? '',
      startMs: num(s.start_ms) ?? 0,
      endMs: num(s.end_ms) ?? 0,
      status: str(s.status) ?? 'passed',
      error: str(s.error),
      isPreview: s.is_preview === true,
      command: str(s.command),
      output: typeof s.output === 'string' ? s.output : undefined,
    })),
    evidence: records(dc.evidence).map((e) => ({
      kind: str(e.kind) ?? '',
      path: str(e.path) ?? '',
      mimeType: str(e.mime_type),
      assetId: str(e.asset_id),
      variant: str(e.variant),
      atStep: num(e.at_step),
    })),
    isCurrent: dc.is_current !== false,
    staleReason: str(dc.stale_reason),
  };
}

export function formatDuration(ms: number | undefined): string {
  if (ms === undefined) return '';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
}

/** Row status as shown on a step or test: anything not passed/skipped counts as failed. */
export function rowStatus(status: string): TestResultRowStatus {
  if (status === 'passed' || status === 'skipped' || status === 'error') return status;
  return 'failed';
}

/** Index of the step playing at `currentMs` (last step that has started). */
export function activeStepIndex(steps: TestResultStep[], currentMs: number): number {
  let active = -1;
  steps.forEach((step, index) => {
    if (step.startMs <= currentMs) active = index;
  });
  return active;
}

export function findEvidence(view: TestResultView, kind: string): TestResultEvidence | undefined {
  const matches = view.evidence.filter((e) => e.kind === kind);
  if (kind === 'preview_frame' && view.previewStepIndex !== undefined) {
    return matches.find((e) => e.atStep === view.previewStepIndex) ?? matches[0];
  }
  return matches[0];
}

/**
 * Default evidence resolver: evidence bytes stay in the encrypted Code Run asset
 * (`asset_id`), one file per `variant`. The existing generated-assets route checks
 * ownership and mints a fresh short-lived link, so a result keeps playing after
 * the run's own links expired. Evidence without both ids has no stored file.
 */
export const resolveArtifactEvidenceUrl: EvidenceUrlResolver = async (evidence) => {
  if (!evidence.assetId || !evidence.variant) return null;
  const response = await fetch(
    getApiEndpoint(
      `/v1/generated-assets/${encodeURIComponent(evidence.assetId)}/files/${encodeURIComponent(evidence.variant)}/download-url`,
    ),
    { credentials: 'include' },
  );
  if (!response.ok) throw new Error(`Test evidence unavailable (${response.status})`);
  const result = await response.json() as { download_url?: unknown };
  return typeof result.download_url === 'string' ? result.download_url : null;
};
