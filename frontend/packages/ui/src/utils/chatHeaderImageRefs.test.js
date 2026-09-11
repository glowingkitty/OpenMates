/**
 * Regression for assistant-linked chat header image priority.
 * Covers block previews, inline links and legacy link marks in reading order.
 * Grouped tool cards are fallback sources, not explicit assistant references.
 * Runs locally with Node and makes no network requests.
 * Architecture: docs/architecture/messaging/embeds.md
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { collectHeaderImageRefs } from '../components/embeds/embedPreviewHydration.ts';

// contract-test: supporting surface=gui.web assertions=chat-share-settings.shared-link-open
test('collects assistant-linked event and image refs in message order without promoting tool cards', () => {
  const doc = { content: [
    { attrs: { groupedItems: [{ embedRef: 'unlinked-tool-card' }] } },
    { type: 'embedPreviewLarge', attrs: { embedRef: 'selected-event' } },
    { type: 'text', marks: [{ attrs: { href: 'embed:selected-image' } }] },
    { type: 'embedInline', attrs: { embedRef: 'selected-event' } },
  ] };
  assert.deepEqual(collectHeaderImageRefs(doc), ['selected-event', 'selected-image']);
});
