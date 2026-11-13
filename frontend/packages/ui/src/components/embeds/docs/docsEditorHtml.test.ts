import { describe, expect, it, vi } from 'vitest';
import { buildEditedContent, cleanEditedHtml } from './docsEditorHtml';

vi.mock('../../../utils/embedLinkUtils', () => ({
  convertEmbedAnchorsToSpans: (value: string) => value,
  convertMarkdownEmbedLinksInHtml: (value: string) => value,
  convertMarkdownWikiLinksInHtml: (value: string) => value,
  convertWikiAnchorsToSpans: (value: string) => value,
}));

describe('cleanEditedHtml', () => {
  // contract-test: supporting surface=gui.web assertions=doc-editor.edit.rich-text
  it('normalises browser formatting tags and divs to document tags', () => {
    expect(cleanEditedHtml('<div>Hello <b>bold</b> <i>it</i></div>')).toBe('<p>Hello <strong>bold</strong> <em>it</em></p>');
  });

  // contract-test: supporting surface=gui.web assertions=doc-editor.edit.rich-text
  it('keeps underline, headings and lists', () => {
    const out = cleanEditedHtml('<h2>Title</h2><ul><li>a</li></ul><ol><li><u>b</u></li></ol>');
    expect(out).toBe('<h2>Title</h2><ul><li>a</li></ul><ol><li><u>b</u></li></ol>');
  });

  // contract-test: supporting surface=gui.web assertions=doc-editor.edit.rich-text
  it('drops styles, font tags, plain spans, scripts and empty paragraphs', () => {
    const out = cleanEditedHtml('<p style="color:red"><font color="red"><span>text</span></font></p><p><br></p><script>alert(1)</script>');
    expect(out).toBe('<p>text</p>');
  });

  // contract-test: supporting surface=gui.web assertions=doc-editor.edit.rich-text
  it('moves a list out of the paragraph the browser wrapped it in', () => {
    expect(cleanEditedHtml('<div><ul><li>Apples</li></ul></div>')).toBe('<ul><li>Apples</li></ul>');
  });

  // contract-test: supporting surface=gui.web assertions=doc-editor.edit.rich-text
  it('keeps spans that carry link data', () => {
    expect(cleanEditedHtml('<p><span data-embed-ref="abc">link</span></p>')).toContain('data-embed-ref="abc"');
  });

  // contract-test: supporting surface=gui.web assertions=doc-editor.edit.rich-text
  it('removes event handler attributes', () => {
    expect(cleanEditedHtml('<p onclick="x()">hi</p>')).toBe('<p>hi</p>');
  });
});

describe('buildEditedContent', () => {
  // contract-test: supporting surface=gui.web assertions=doc-editor.edit.rich-text
  it('replaces html and version, keeps other fields and drops stale artifacts', () => {
    const next = buildEditedContent(
      { html: '<p>old</p>', title: 'Doc', filename: 'doc.docx', version_number: 2, pdf_s3_key: 'k', preview_page_urls: { '1': 'u' }, docx_model: {} },
      '<p>new text</p>',
      3
    );
    expect(next).toEqual({ html: '<p>new text</p>', title: 'Doc', filename: 'doc.docx', version_number: 3, word_count: 2 });
  });
});
