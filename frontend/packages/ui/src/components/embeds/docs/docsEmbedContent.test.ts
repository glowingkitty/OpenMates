import { describe, expect, it, vi } from 'vitest';
import { decode } from '@toon-format/toon';
import { communityGardenVolunteerOnboardingChat } from '../../../demo_chats/data/example_chats/community-garden-volunteer-onboarding';
import { docxModelToHtml, sanitizeDocumentHtml } from './docsEmbedContent';

vi.mock('../../../utils/embedLinkUtils', () => ({
  convertEmbedAnchorsToSpans: (value: string) => value,
  convertMarkdownEmbedLinksInHtml: (value: string) => value,
  convertMarkdownWikiLinksInHtml: (value: string) => value,
  convertWikiAnchorsToSpans: (value: string) => value,
}));

describe('document model rendering', () => {
  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  it('preserves the admitted public document structure and text', () => {
    const source = decode(communityGardenVolunteerOnboardingChat.embeds[0].content, { strict: false }) as Record<string, unknown>;
    const html = docxModelToHtml(source.docx_model);
    expect(html).toContain('<h1>Community Garden Volunteer Guide</h1>');
    expect(html).toContain('<h2>3. Safety &amp; Tool Care</h2>');
    expect(html).toContain('<li>Wear sturdy, closed-toe shoes and garden gloves at all times.</li>');
    expect(html).toContain('<strong>[Coordinator Name]</strong>');
    expect(html).toContain('First aid is stocked at [First Aid Box Location].');
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering
  it('escapes model text before sanitizing document HTML', () => {
    const html = sanitizeDocumentHtml(docxModelToHtml({ blocks: [
      { type: 'paragraph', runs: [{ text: '<img src=x onerror=alert(1)> & welcome', bold: true }] },
      { type: 'table', headers: ['<script>alert(1)</script>'], rows: [['<b>value</b>']] },
    ] }));
    expect(html).toContain('&lt;img src=x onerror=alert(1)&gt;');
    expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;');
    expect(html).not.toContain('<img');
    expect(html).not.toContain('<script');
  });
});
