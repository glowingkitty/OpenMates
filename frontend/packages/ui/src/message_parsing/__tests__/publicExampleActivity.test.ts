import { parse } from 'yaml';
import { afterEach, describe, expect, it, vi } from 'vitest';
vi.mock('../../data/modelsMetadata', () => ({ modelsMetadata: [] }));
vi.mock('../../data/matesMetadata', () => ({ matesMetadata: [] }));
vi.mock('../../data/providersMetadata', () => ({ providersMetadata: {} }));
vi.mock('../../stores/appSettingsMemoriesStore', () => ({ appSettingsMemoriesStore: { subscribe: () => () => undefined } }));
vi.mock('../../stores/appSkillsStore', () => ({ appSkillsStore: { apps: {}, subscribe: () => () => undefined } }));
import { parse_message } from '../parse_message';
import { splitAssistantActivityRuns } from '../assistantActivityRuns';
import { registerEmbedRefIndex, clearEmbedRefIndexEntries, resolveEmbedRefIndexEntry } from '../../services/embedRefIndex';
import { deutschlandticketTrainFareBreakdownChat as train } from '../../demo_chats/data/example_chats/deutschlandticket-train-fare-breakdown';
import { communityGardenWelcomeMelodyChat as music } from '../../demo_chats/data/example_chats/community-garden-welcome-melody';
import { communityGardenVolunteerChimeChat as audio } from '../../demo_chats/data/example_chats/community-garden-volunteer-chime';
import { communityGardenSunflowerIllustrationChat as image } from '../../demo_chats/data/example_chats/community-garden-sunflower-illustration';

const sources = import.meta.glob('../../i18n/sources/example_chats/*.yml', { query: '?raw', import: 'default', eager: true });
const transcript = (name: string) => parse(sources[`../../i18n/sources/example_chats/${name}.yml`] as string).message_2.en;
const compile = (markdown: string, chatId: string) => parse_message(markdown, 'read', { unifiedParsingEnabled: true, role: 'assistant', chatId });
afterEach(clearEmbedRefIndexEntries);

describe('public example invocation activity', () => {
  // contract-test: supporting surface=gui.web assertions=chat-processing-feedback.completed-processing-summary,public-example-chats.transcript.safe-rendering
  it('classifies the actual train invocation as activity and retains its inline route results', () => {
    const runs = splitAssistantActivityRuns(compile(transcript('deutschlandticket_train_fare_breakdown'), train.chat_id))!;
    expect(runs[0].kind).toBe('skills');
    expect(runs[0].appIds).toEqual(['travel']);
    expect(runs[0].skillIds).toEqual(['search_connections']);
    expect(runs[0].document.content[0]).toMatchObject({ content: [{ type: 'embed', attrs: { id: train.embeds[0].embed_id, type: 'app-skill-use' } }] });
    expect(runs.some(run => run.kind === 'content')).toBe(true);
    expect(resolveEmbedRefIndexEntry(train.embeds[0].embed_id)).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=app-skills.media.visible-assistant-results,app-skills.media.parent-children-and-attribution
  it('keeps generated image children in the content run while its invocation remains activity', () => {
    const runs = splitAssistantActivityRuns(compile(transcript('community_garden_sunflower_illustration'), image.chat_id))!;
    const child = image.embeds.find(embed => embed.parent_embed_id)!;
    const results = runs.filter(run => run.kind === 'content').flatMap(run => run.document.content);
    expect(results).toContainEqual(expect.objectContaining({ type: 'embedPreviewLarge', attrs: expect.objectContaining({ embedId: child.embed_id, appId: 'images' }) }));
    expect(runs.filter(run => run.kind === 'skills').flatMap(run => run.skillIds)).toEqual(['generate']);
    const previousType = child.type;
    try {
      child.type = 'app_skill_use';
      const legacy = splitAssistantActivityRuns(compile(`[!](embed:${child.embed_id})`, image.chat_id))!;
      expect(legacy[0].kind).toBe('content');
      expect(legacy[0].document.content[0].type).toBe('embedPreviewLarge');
    } finally { child.type = previousType; }
  });

  // contract-test: supporting surface=gui.web assertions=app-skills.media.visible-assistant-results,chat-processing-feedback.completed-processing-summary
  it.each([
    ['community_garden_welcome_melody', music], ['community_garden_volunteer_chime', audio],
    ['community_garden_sunflower_illustration', image],
  ])('deduplicates echoed parent references for %s in live and saved documents', (name, fixture) => {
    const invocation = fixture.embeds.find(embed => !embed.parent_embed_id)!;
    const child = fixture.embeds.find(embed => embed.parent_embed_id)!;
    const markdown = transcript(name as string);
    const echoed = `${markdown}\n\n[!](embed:${invocation.embed_id})`;
    for (const source of [markdown, echoed]) {
      const runs = splitAssistantActivityRuns(compile(source, fixture.chat_id))!;
      expect(runs.filter(run => run.kind === 'skills')).toHaveLength(1);
      expect(runs.flatMap(run => run.skillIds)).toEqual(['generate']);
      expect(JSON.stringify(runs.filter(run => run.kind === 'content'))).toContain(child.embed_id);
    }
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  it('uses public metadata despite a private UUID collision and never falls back for missing public refs', () => {
    const id = train.embeds[0].embed_id;
    registerEmbedRefIndex(id, { embedId: id, type: 'generated_image', appId: 'images', skillId: 'generate' });
    expect(splitAssistantActivityRuns(compile(`[!](embed:${id})`, train.chat_id))![0].appIds).toEqual(['travel']);
    expect(compile(`[!](embed:${id})`, 'private-chat').content[0].type).toBe('embedPreviewLarge');
    registerEmbedRefIndex('missing-public', { embedId: 'private-secret', type: 'app_skill_use', appId: 'web', skillId: 'search' });
    expect(compile('[!](embed:missing-public)', train.chat_id).content[0]).toMatchObject({ type: 'embedPreviewLarge', attrs: { embedId: null, appId: null } });
  });
});
