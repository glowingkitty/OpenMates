import { describe, expect, it } from 'vitest';
import { sortAllWorkflows, sortWorkflowContinue, type SortableWorkflow } from '../workflowHomeSorting';
import { hasRoomForLargeContinueCards } from '../../../utils/continueCardLayout';

const now = Date.UTC(2026, 9, 1, 12) / 1000;
const item = (id: string, editAge: number, runIn: number | null = null, enabled = true): SortableWorkflow => ({
  id, created_at: now - editAge, updated_at: now - editAge,
  next_run_at: runIn === null ? null : now + runIn, enabled,
});

describe('workflow home ordering', () => {
  // contract-test: direct surface=gui.web assertions=workflows-ui.workspace.continue-priority
  it('uses the five priority buckets and exact 30-minute and 24-hour boundaries', () => {
    const entries = [
      item('old', 86401), item('day-run', 86401, 86400),
      item('day-edit', 86400), item('minute-run', 86401, 1800),
      item('minute-edit', 1800), item('second-minute-edit', 1799),
    ];
    expect(sortWorkflowContinue(entries, now * 1000).map(entry => entry.id)).toEqual([
      'second-minute-edit', 'minute-edit', 'minute-run', 'day-edit', 'day-run', 'old',
    ]);
  });

  // contract-test: supporting surface=gui.web assertions=workflows-ui.workspace.continue-priority
  it('ignores disabled or elapsed runs and uses newest edit and earliest run within buckets', () => {
    const entries = [
      { ...item('created-newer', 100), updated_at: now - 5000 },
      item('soon-20', 90000, 1200), item('soon-10', 90000, 600),
      item('disabled', 90000, 100, false), item('elapsed', 90000, 0),
    ];
    expect(sortWorkflowContinue(entries, now * 1000).map(entry => entry.id)).toEqual([
      'created-newer', 'soon-10', 'soon-20', 'disabled', 'elapsed',
    ]);
  });

  // contract-test: direct surface=gui.web assertions=workflows-ui.workspace.owned-library-and-templates
  it('sorts the all-workflows grid by edits or future enabled runs', () => {
    const entries = [item('recent', 10), item('late-run', 200, 500), item('early-run', 300, 100), item('disabled', 5, 50, false)];
    expect(sortAllWorkflows(entries, 'recent', now * 1000).map(entry => entry.id)).toEqual(['disabled', 'recent', 'late-run', 'early-run']);
    expect(sortAllWorkflows(entries, 'running-next', now * 1000).map(entry => entry.id)).toEqual(['early-run', 'late-run', 'disabled', 'recent']);
    expect(entries.map(entry => entry.id)).toEqual(['recent', 'late-run', 'early-run', 'disabled']);
  });
});

describe('continue card space', () => {
  // contract-test: supporting surface=gui.web assertions=workspace-shell.start.available-space-cards
  it('requires both the carousel width and actual free height', () => {
    expect(hasRoomForLargeContinueCards(550, 420)).toBe(true);
    expect(hasRoomForLargeContinueCards(549, 420)).toBe(false);
    expect(hasRoomForLargeContinueCards(700, 419)).toBe(false);
  });
});
