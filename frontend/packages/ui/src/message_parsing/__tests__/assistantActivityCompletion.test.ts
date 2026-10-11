import { describe, expect, it, vi } from 'vitest';
import { assistantSkillRefs, areAssistantSkillsTerminal } from '../assistantActivityCompletion';
import type { AssistantDocument } from '../assistantActivityRuns';

describe('assistant activity completion', () => {
  // contract-test: direct surface=gui.web assertions=chat-processing-feedback.completed-processing-summary
  it('uses every real grouped skill status from storage despite stale document attrs', async () => {
    const document: AssistantDocument = { type: 'doc', content: [{
      type: 'paragraph', content: [{ type: 'embed', attrs: {
        type: 'app-skill-use-group', id: 'synthetic-group', status: 'finished',
        groupedItems: [
          { id: 'first', contentRef: 'embed:first', status: 'processing' },
          { id: 'second', contentRef: 'embed:second', status: 'processing' },
        ],
      } }],
    }] };
    const refs = assistantSkillRefs(document);
    expect(refs).toEqual(['embed:first', 'embed:second']);
    const statuses = new Map([['embed:first', 'finished'], ['embed:second', 'processing']]);
    const lookup = vi.fn(async (ref: string) => ({ status: statuses.get(ref) }));
    expect(await areAssistantSkillsTerminal(refs, lookup)).toBe(false);
    statuses.set('embed:second', 'cancelled');
    expect(await areAssistantSkillsTerminal(refs, lookup)).toBe(true);
    statuses.set('embed:first', 'error');
    expect(await areAssistantSkillsTerminal(refs, lookup)).toBe(true);
    statuses.set('embed:first', 'unknown');
    expect(await areAssistantSkillsTerminal(refs, lookup)).toBe(false);
    expect(lookup).not.toHaveBeenCalledWith('embed:synthetic-group');
  });
});
