/** Collapsed assistant activity row: wording for an assistant-created Project. */
import { describe, expect, it } from 'vitest';
import { activitySummaryCandidates, type ActivitySummaryState } from '../assistantActivitySummary';

const base: ActivitySummaryState = {
  apps: [], memories: [], focuses: ['Work on Recipe Manager'], thinking: false, usingApps: false,
  thinkingStreaming: false, activatingFocus: false, subChats: false, workingSubChats: false,
  active: false, cancelledFocus: false,
};
const translate = (key: string, values?: Record<string, string | number>) => `${key}|${JSON.stringify(values ?? {})}`;

describe('assistant activity summary', () => {
  // contract-test: supporting surface=gui.web assertions=projects.creation.assistant-inferred
  it('names the created Project before its focus, with a short form', () => {
    const [full, compact] = activitySummaryCandidates({ ...base, createdProjects: ['Recipe Manager'] }, translate);
    expect(full).toContain('chat.response_activity.project_created_focus');
    expect(full).toContain('"project":"Recipe Manager"');
    expect(full).toContain('"focus":"Work on Recipe Manager"');
    expect(compact).toContain('chat.response_activity.project_created|');
  });
  // contract-test: supporting surface=gui.web assertions=projects.creation.assistant-inferred
  it('keeps the plain focus wording without a created Project', () => {
    expect(activitySummaryCandidates(base, translate)[0]).toContain('chat.response_activity.focus_activated|');
  });
});
