/**
 * Regression coverage for saved generated-image references reduced to bangs.
 * Exercises retained parent graphs, deduplication and invalid graph handling.
 * Checks that recovery never rewrites the original assistant document.
 * These tests resolve metadata only and never generate or fetch image bytes.
 */
import { describe, expect, it, vi } from 'vitest';
import { lostImageParents, recoverGeneratedImageDocument } from '../generatedImageRecovery';
import type { AssistantDocument } from '../assistantActivityRuns';
const parentId = '11111111-1111-4111-8111-111111111111';
const childId = '22222222-2222-4222-8222-222222222222';
const secondId = '33333333-3333-4333-8333-333333333333';
const invocation = { type: 'paragraph', content: [{ type: 'embed', attrs: {
  type: 'app-skill-use', id: parentId, app_id: 'images', skill_id: 'generate',
} }] };
const bang = { type: 'paragraph', content: [{ type: 'text', text: '!\n!' }] };
const document = (): AssistantDocument => ({ type: 'doc', content: [invocation, bang] });
const parent = { app_id: 'images', skill_id: 'generate', status: 'finished', embed_ids: [childId, secondId] };
// contract-test: supporting surface=gui.web assertions=app-skills.media.visible-assistant-results,app-skills.media.parent-children-and-attribution
describe('saved generated image display recovery', () => {
  // contract-test: supporting surface=gui.web assertions=app-skills.media.visible-assistant-results,app-skills.media.parent-children-and-attribution
  it('recovers both retained SVG children without rewriting the source or repeating previews', async () => {
    const source = document();
    const resolve = vi.fn().mockResolvedValue(parent);
    const recovered = await recoverGeneratedImageDocument(source, resolve);
    expect(resolve).toHaveBeenCalledExactlyOnceWith(parentId);
    expect(recovered?.content.map(node => node.type)).toEqual(['paragraph', 'embedPreviewLarge', 'embedPreviewLarge']);
    expect(recovered?.content[1]).toMatchObject({ attrs: { embedId: childId, carouselIndex: 0, carouselTotal: 2 } });
    expect(source.content).toEqual([invocation, bang]);
    expect(await recoverGeneratedImageDocument(recovered!, resolve)).toBeNull();
  });
  // contract-test: supporting surface=gui.web assertions=app-skills.media.visible-assistant-results,app-skills.media.parent-children-and-attribution
  it('preserves an already visible child and adds only its missing sibling', async () => {
    const source = document();
    source.content.push({ type: 'embedPreviewLarge', attrs: { embedRef: 'generated-images-222222222222' } });
    const result = await recoverGeneratedImageDocument(source, async () => parent);
    expect(result?.content.filter(node => node.type === 'embedPreviewLarge')).toHaveLength(2);
    expect(result?.content[result.content.length - 1]).toMatchObject({ attrs: { embedId: secondId } });
  });
  // contract-test: supporting surface=gui.web assertions=app-skills.media.visible-assistant-results,app-skills.media.parent-children-and-attribution
  it.each([null, { ...parent, status: 'processing' }, { ...parent, app_id: 'web' }, { ...parent, embed_ids: ['invented'] }])('leaves unresolved or invalid graphs unchanged', async value => {
    expect(await recoverGeneratedImageDocument(document(), async () => value)).toBeNull();
  });
  // contract-test: supporting surface=gui.web assertions=app-skills.media.visible-assistant-results,app-skills.media.parent-children-and-attribution
  it('does not read unrelated parents or remove ordinary exclamations', async () => {
    const source = document();
    source.content[1] = { type: 'paragraph', content: [{ type: 'text', text: 'Looks great!' }] };
    expect(lostImageParents(source)).toEqual([]);
    const resolve = vi.fn();
    expect(await recoverGeneratedImageDocument(source, resolve)).toBeNull();
    expect(resolve).not.toHaveBeenCalled();
  });
});
