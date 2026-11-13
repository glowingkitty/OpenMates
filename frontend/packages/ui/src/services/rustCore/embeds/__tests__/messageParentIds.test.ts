// The skill-use parent ids a chat message renders: shell input for the core's
// message-version rule (embed_versions_by_message).
import { describe, expect, it } from 'vitest';
import { appSkillParentIds } from '../messageParentIds';

describe('appSkillParentIds', () => {
	// contract-test: direct surface=gui.web assertions=images-generate.revision.same-embed-new-version,images-generate.revision.message-shows-its-version
	it('reads skill-use blocks from the markdown and the rendered document, once each, in order', () => {
		const markdown = [
			'Here is the change.',
			'```json\n{"type":"app_skill_use","embed_id":"parent-a"}\n```',
			'```json\n{"type":"website","embed_id":"site-1"}\n```'
		].join('\n\n');
		const doc = {
			type: 'doc',
			content: [
				{ type: 'embed', attrs: { type: 'app-skill-use', contentRef: 'embed:parent-a' } },
				{ type: 'embed', attrs: { type: 'group', groupedItems: [{ type: 'app-skill-use', id: 'parent-b' }] } }
			]
		};
		expect(appSkillParentIds({ id: 'm1', content: doc, original_message: { content: markdown } })).toEqual(['parent-a', 'parent-b']);
	});

	// contract-test: direct surface=gui.web assertions=images-generate.revision.same-embed-new-version,images-generate.revision.message-shows-its-version
	it('returns nothing for a message without skill uses', () => {
		expect(appSkillParentIds({ id: 'm2', content: { type: 'doc', content: [{ type: 'paragraph' }] }, original_message: null })).toEqual([]);
	});
});
