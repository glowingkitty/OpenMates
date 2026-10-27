import { describe, expect, it } from 'vitest';
import { svgImageSource } from '../svgImage';

describe('standalone SVG image detection', () => {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it.each([
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 10"><rect width="20" height="10"/></svg>',
    ' \n<?xml version="1.0"?>\n<!-- drawing -->\n<svg viewBox="0 0 20 10"><text>Grüße &amp; #1</text></svg>\n',
    '<svg/>',
  ])('loads a complete SVG as an encoded image: %s', (source) => {
    const url = svgImageSource(source);
    expect(url).toMatch(/^data:image\/svg\+xml;charset=utf-8,/);
    const svg = decodeURIComponent(url!.split(',')[1]);
    expect(svg).toContain('xmlns="http://www.w3.org/2000/svg"');
    expect(new DOMParser().parseFromString(svg, 'image/svg+xml').querySelector('parsererror')).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it.each([
    '<svg><path></svg>', '<svg><path/>',
    '<svg/>\nSome explanation', 'Example: <svg/>', '<svg/><svg/>',
    '<html><body><svg/></body></html>', 'const image = `<svg/>`;',
    '<svg xmlns="urn:other"/>',
    '<!DOCTYPE svg [<!ENTITY secret SYSTEM "file:///etc/passwd">]><svg>&secret;</svg>',
  ])('keeps mixed, incomplete or invalid source as code: %s', (source) => {
    expect(svgImageSource(source)).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it('excludes stylesheet processing instructions from the image document', () => {
    const url = svgImageSource('<?xml-stylesheet href="https://example.invalid/style.css"?><svg/>');
    expect(decodeURIComponent(url!)).not.toContain('xml-stylesheet');
  });
});
