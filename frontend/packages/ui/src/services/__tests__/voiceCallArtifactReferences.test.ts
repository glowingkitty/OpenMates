import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CodeBlockStateMachine } from '../../message_parsing/utils';
const journal = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('../embedStore', () => ({ embedStore: journal }));
import { callArtifactReferencesInText, formatVoiceArtifactReference, loadVoiceArtifactReference,
  voiceArtifactReferenceFromPayload } from '../voiceCallArtifactReferences';
beforeEach(() => journal.get.mockReset());

describe('canonical voice artifacts', () => {
  // contract-test: supporting surface=gui.web assertions=video-call.chat.skill-integration,video-call.chat.transcripts
  it('uses the real shared JSON-fence grammar and retains authoritative reference metadata', () => {
    const reference = { type: 'app_skill_use', embed_id: 'search-parent', app_id: 'web', skill_id: 'search',
      query: 'Fictional recipe', provider: 'Fixture', status: 'finished' };
    const parsed = voiceArtifactReferenceFromPayload({ embed_id: reference.embed_id, embed_reference: JSON.stringify(reference) })!;
    const text = formatVoiceArtifactReference(parsed);
    const machine = new CodeBlockStateMachine();
    const events = text.split('\n').map((line, index) => machine.processLine(line, index));
    expect(events.at(-1)).toMatchObject({ event: 'block_closed', specialFence: 'json' });
    expect(JSON.parse(events.at(-1)!.content!)).toEqual(reference);
    expect(callArtifactReferencesInText(`Spoken reply\n\n${text}`)).toEqual([reference]);
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.skill-integration,video-call.privacy
  it('does not attach child updates or mismatched references as standalone cards', () => {
    expect(voiceArtifactReferenceFromPayload({ embed_id: 'child-one', parent_embed_id: 'search-parent', type: 'web_website' })).toBeUndefined();
    expect(voiceArtifactReferenceFromPayload({ embed_id: 'search-parent', embed_reference: '{"type":"app_skill_use","embed_id":"foreign"}' })).toBeUndefined();
  });

  // contract-test: supporting surface=gui.web assertions=video-call.chat.skill-integration,video-call.lifecycle.recovery-and-billing
  it('resolves cold receipt IDs from decrypted journal delivery and excludes child cards', async () => {
    journal.get.mockResolvedValueOnce(undefined);
    await expect(loadVoiceArtifactReference('search-parent')).rejects.toThrow('awaiting encrypted embed delivery');
    journal.get.mockResolvedValueOnce({ embed_id: 'search-parent', type: 'app_skill_use',
      content: 'app_id: web\nskill_id: search\nquery: Fictional recipe' });
    expect(await loadVoiceArtifactReference('search-parent')).toMatchObject({ embed_id: 'search-parent',
      type: 'app_skill_use', app_id: 'web', skill_id: 'search', query: 'Fictional recipe' });
    journal.get.mockResolvedValueOnce({ embed_id: 'child-one', parent_embed_id: 'search-parent', type: 'web_website' });
    expect(await loadVoiceArtifactReference('child-one')).toBeNull();
  });
});
