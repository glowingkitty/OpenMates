import { describe, expect, it } from 'vitest';
import { readProjectCreatedEvent } from './projectCreatedEvent';

const ref = (extra: Record<string, unknown>) =>
  `Done.\n\n\`\`\`json\n${JSON.stringify({ type: 'focus_mode_activation', embed_id: 'e1', ...extra })}\n\`\`\`\n`;

describe('readProjectCreatedEvent', () => {
  // contract-test: supporting surface=gui.web assertions=projects.creation.assistant-inferred
  it('reads the created Project from the activation reference', () => {
    expect(readProjectCreatedEvent(ref({ project_created: true, project_id: 'p1', project_name: 'Recipe Manager' })))
      .toEqual({ projectId: 'p1', projectName: 'Recipe Manager' });
  });
  // contract-test: supporting surface=gui.web assertions=projects.creation.assistant-inferred
  it('ignores ordinary activations, other blocks and non-strings', () => {
    expect(readProjectCreatedEvent(ref({ focus_id: 'web-research' }))).toBeNull();
    expect(readProjectCreatedEvent('```json\n{"project_created": true}\n```')).toBeNull();
    expect(readProjectCreatedEvent({ type: 'doc' })).toBeNull();
  });
});
