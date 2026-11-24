import { describe, expect, it } from 'vitest';
import { formatTaskDueDate, normalizeTaskResult, taskRestoreFromSource, taskVisibleId } from '../taskEmbedData';
import { resolveIconName } from '../../../../utils/iconNameResolver';

describe('normalizeTaskResult', () => {
  // contract-test: supporting surface=gui.web assertions=task-inline.presentation.no-raw-ids,task-inline.edit.diff-versioned
  it('reads due date, project name and validation errors', () => {
    const task = normalizeTaskResult('e1', {
      title: 'Water the basil',
      due_date: '2026-11-24',
      project_name: 'Balcony garden',
      validation: { status: 'invalid', errors: ['Unknown project', { message: 'Bad date' }], warnings: [] },
    });
    expect(task.due_date).toBe('2026-11-24');
    expect(task.project_name).toBe('Balcony garden');
    expect(task.validation).toEqual({ status: 'invalid', errors: ['Unknown project', 'Bad date'], warnings: [] });
  });

  // contract-test: supporting surface=gui.web assertions=task-inline.presentation.no-raw-ids,task-inline.edit.diff-versioned
  it('leaves validation undefined when absent', () => {
    expect(normalizeTaskResult('e1', { title: 'x' }).validation).toBeUndefined();
  });
});

describe('task display helpers', () => {
  // contract-test: supporting surface=gui.web assertions=task-inline.presentation.no-raw-ids,task-inline.edit.diff-versioned
  it('formats a short localized due date and ignores bad input', () => {
    expect(formatTaskDueDate('2026-11-24', 'en')).toBe('Nov 24');
    expect(formatTaskDueDate('not a date', 'en')).toBe('');
    expect(formatTaskDueDate(undefined, 'en')).toBe('');
  });

  // contract-test: supporting surface=gui.web assertions=task-inline.presentation.no-raw-ids,task-inline.edit.diff-versioned
  it('never exposes a raw task id', () => {
    expect(taskVisibleId('TASK-12')).toBe('TASK-12');
    expect(taskVisibleId(undefined)).toBe('');
    expect(taskVisibleId('01234567-89ab-cdef-abcd-0123456789ab')).toBe('');
  });

  // contract-test: supporting surface=gui.web assertions=task-inline.presentation.no-raw-ids,task-inline.edit.diff-versioned
  it('restores the rendered fields and encrypted Task patch from the same source', () => {
    const restored = taskRestoreFromSource('{"title":"Window break","description":"Open the window","status":"done","due_date":"2026-11-24","assignee":"openmates"}');
    expect(restored).toEqual({
      patch: { title: 'Window break', description: 'Open the window', status: 'done', assigneeType: 'openmates', dueAt: 1795478400 },
      fields: { title: 'Window break', description: 'Open the window', status: 'done', assignee_type: 'openmates', due_date: '2026-11-24' },
    });
    expect(taskRestoreFromSource('{"title":"Window break","assignee":"me"}')?.patch)
      .toMatchObject({ description: '', status: 'todo', assigneeType: 'user', dueAt: null });
    expect(taskRestoreFromSource('{"title":"Window break","due_date":"2026-11-24T04:00:00+04:00"}')?.patch.dueAt)
      .toBe(1795478400);
    expect(taskRestoreFromSource('nope')).toBeNull();
  });
});

describe('task embed link icon', () => {
  // contract-test: supporting surface=gui.web assertions=task-inline.presentation.no-raw-ids,task-inline.edit.diff-versioned
  it('uses the task icon for the tasks app id', () => {
    expect(resolveIconName('tasks')).toBe('task');
  });
});
