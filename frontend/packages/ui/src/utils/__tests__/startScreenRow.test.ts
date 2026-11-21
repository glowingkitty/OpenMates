// Unit tests for the start-screen row rhythm (daily-inspiration.start-row-rhythm).
import { describe, expect, it } from 'vitest';
import type { DailyInspiration } from '../../stores/dailyInspirationStore';
import {
  interleaveStartRow,
  selectChatRowInspirations,
  selectWorkflowRowInspirations,
} from '../startScreenRow';

const own = (count: number) => Array.from({ length: count }, (_, i) => `c${i + 1}`);
const insp = (count: number) => Array.from({ length: count }, (_, i) => `i${i + 1}`);
const flat = (entries: { kind: string; item: string }[]) => entries.map((entry) => entry.item);

function inspiration(partial: Partial<DailyInspiration>): DailyInspiration {
  return {
    inspiration_id: partial.inspiration_id ?? 'x',
    phrase: 'p',
    category: 'science',
    content_type: 'video',
    video: null,
    generated_at: 0,
    ...partial,
  };
}

describe('interleaveStartRow', () => {
  // contract-test: supporting surface=gui.web assertions=daily-inspiration.start-row-rhythm
  it('shows two own items, then one inspiration after every third own item', () => {
    expect(flat(interleaveStartRow(own(7), insp(6)))).toEqual([
      'c1', 'c2', 'i1', 'c3', 'c4', 'c5', 'i2', 'c6', 'c7',
    ]);
  });

  // contract-test: supporting surface=gui.web assertions=daily-inspiration.start-row-rhythm
  it('shows at most ten cards in total, inspirations included', () => {
    expect(flat(interleaveStartRow(own(14), insp(6)))).toEqual([
      'c1', 'c2', 'i1', 'c3', 'c4', 'c5', 'i2', 'c6', 'c7', 'c8',
    ]);
  });

  // contract-test: supporting surface=gui.web assertions=daily-inspiration.start-row-rhythm
  it('shows only inspirations for a user without own items', () => {
    expect(flat(interleaveStartRow([], insp(6)))).toEqual(insp(6));
    expect(interleaveStartRow([], insp(12))).toHaveLength(10);
  });

  // contract-test: supporting surface=gui.web assertions=daily-inspiration.start-row-rhythm
  it('adds one inspiration after a single own item', () => {
    expect(flat(interleaveStartRow(own(1), insp(6)))).toEqual(['c1', 'i1']);
  });

  // contract-test: supporting surface=gui.web assertions=daily-inspiration.start-row-rhythm
  it('keeps own items only when no inspirations exist', () => {
    expect(flat(interleaveStartRow(own(5), []))).toEqual(own(5));
  });

  // contract-test: supporting surface=gui.web assertions=daily-inspiration.start-row-rhythm
  it('never repeats an inspiration when there are fewer than slots', () => {
    expect(flat(interleaveStartRow(own(8), insp(1)))).toEqual(['c1', 'c2', 'i1', 'c3', 'c4', 'c5', 'c6', 'c7', 'c8']);
  });
});

describe('selectChatRowInspirations', () => {
  // contract-test: supporting surface=gui.web assertions=daily-inspiration.start-row-rhythm,daily-inspiration.start-row-cards
  it('keeps unopened chat video and article inspirations only', () => {
    const selected = selectChatRowInspirations([
      inspiration({ inspiration_id: 'video' }),
      inspiration({ inspiration_id: 'wiki', content_type: 'wiki' }),
      inspiration({ inspiration_id: 'feature', content_type: 'feature' }),
      inspiration({ inspiration_id: 'opened', is_opened: true }),
      inspiration({ inspiration_id: 'workflow-surface', surface: 'workflows' }),
    ]);
    expect(selected.map((item) => item.inspiration_id)).toEqual(['video', 'wiki']);
  });
});

describe('selectWorkflowRowInspirations', () => {
  // contract-test: supporting surface=gui.web assertions=daily-inspiration.workflow-recommendation-hook
  it('keeps recommended workflows with a workflow payload only', () => {
    const selected = selectWorkflowRowInspirations([
      inspiration({ inspiration_id: 'tip', surface: 'workflows', content_type: 'feature' }),
      inspiration({ inspiration_id: 'no-payload', surface: 'workflows', content_type: 'workflow' }),
      inspiration({
        inspiration_id: 'recommended',
        surface: 'workflows',
        content_type: 'workflow',
        workflow: { template_id: 'weekly-summary' },
      }),
    ]);
    expect(selected.map((item) => item.inspiration_id)).toEqual(['recommended']);
  });
});
