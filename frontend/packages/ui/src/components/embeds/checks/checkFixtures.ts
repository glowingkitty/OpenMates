/** Fixture Checks for /dev/preview pages and component specs (synthetic data). */
import type { CheckView, SourceView } from './checkTypes';

const e2e = (id: string, status: 'passed' | 'failed' = 'passed'): SourceView => ({
  binding_id: id, kind: 'e2e', role: 'required', title: `Checkout flow ${id}`, ref_label: 'checkout.spec.ts',
  latest_result: { status, summary: status === 'passed' ? '2 of 2 tests passed' : '1 of 2 tests failed', test_result_embed_id: `tr-${id}` },
});
const unit = (status: 'passed' | 'failed' = 'passed', role: 'required' | 'supporting' = 'required'): SourceView => ({
  binding_id: `unit-${role}`, kind: 'unit', role, title: 'Price rounding', ref_label: 'rounding.test.ts',
  latest_result: { status, summary: status === 'passed' ? '1 of 1 passed' : '0 of 1 passed' },
});
const ai = (): SourceView => ({
  binding_id: 'ai-1', kind: 'ai_evaluation', role: 'supporting', title: 'Error message is understandable', ref_label: 'Decision model',
  latest_result: { status: 'passed', summary: 'Judged acceptable', ai: {
    question: 'Does the error message explain how to recover?', verdict: 'pass', score: 0.86, threshold: 0.7,
    feedback: 'The message names the problem and the next step.' } },
});
const human = (pending: boolean): SourceView => ({
  binding_id: 'human-1', kind: 'human_confirmation', role: 'required', title: 'Looks right on mobile', ref_label: 'Owner',
  latest_result: pending
    ? { status: 'waiting_for_confirmation', summary: 'Waiting for confirmation', human: { instruction: 'Open the checkout on a phone and confirm the layout.' } }
    : { status: 'passed', summary: 'Confirmed', human: { instruction: 'Open the checkout on a phone and confirm the layout.', decision: 'confirmed', confirmer_label: 'Alex', confirmed_at: '2026-11-12T10:00:00Z' } },
});

const base: CheckView = {
  id: 'check-1', title: 'Checkout works end to end', description: 'A shopper can pay and sees a receipt.', status: 'ready',
  revision_number: 3, aggregate: 'passed', stale: false, requires_deterministic: true,
  covered_claims: ['A shopper can pay', 'A receipt is shown'], sources: [], runs: [
    { run_id: 'run-3', revision_number: 3, subject_label: 'main@a1b2c3', status: 'passed', started_at: '2026-11-12T10:00:00Z', finished_at: '2026-11-12T10:05:00Z' },
    { run_id: 'run-2', revision_number: 2, subject_label: 'main@9f8e7d', status: 'failed', started_at: '2026-11-10T10:00:00Z', finished_at: '2026-11-10T10:04:00Z', stale: true },
  ],
};

export const passedMixed: CheckView = { ...base, sources: [e2e('e2e-1'), e2e('e2e-2'), unit(), ai(), human(false)] };
export const failedRequiredUnit: CheckView = { ...base, aggregate: 'failed', sources: [e2e('e2e-1'), unit('failed'), ai()] };
export const supportingFailure: CheckView = { ...base, aggregate: 'passed', sources: [e2e('e2e-1'), unit('failed', 'supporting')] };
export const waitingForConfirmation: CheckView = { ...base, aggregate: 'waiting_for_confirmation', sources: [e2e('e2e-1'), unit(), human(true)] };
/** A Check saved from the CLI: the human source's title, reference and instruction are one text, runs have no subject. */
const storedInstruction = 'Taste the pancakes and confirm they are fluffy';
export const storedHumanSource: CheckView = {
  ...base, aggregate: 'waiting_for_confirmation', title: 'Pancake recipe works',
  runs: [{ run_id: 'run-1', revision_number: 1, subject_label: '', status: 'waiting_for_confirmation', started_at: '2026-11-14T01:57:54Z' }],
  sources: [unit(), {
    binding_id: 's2', kind: 'human_confirmation', role: 'required', title: storedInstruction, ref_label: storedInstruction,
    latest_result: { status: 'waiting_for_confirmation', summary: '', human: { instruction: storedInstruction } },
  }],
};
export const stale: CheckView = { ...base, stale: true, stale_reason: 'Check revision changed since the last pass', sources: [e2e('e2e-1'), unit()] };
export const neverRun: CheckView = { ...base, aggregate: 'never_run', runs: [], sources: [
  { ...e2e('e2e-1'), latest_result: undefined }, { ...unit(), latest_result: undefined }] };
export const running: CheckView = { ...base, aggregate: 'running', sources: [e2e('e2e-1')] };
