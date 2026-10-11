// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
import { describe, expect, it } from 'vitest';
import darkHtml from '../../embeds/diagrams/diagramHtmlExampleDark.html?raw';
import { classifyDiagramHtmlUpload } from './diagramHtmlUploadDetection';

describe('diagram HTML attachment routing', () => {
  it('accepts an explicit safe diagram and leaves generic or escaped-CSS HTML as code', () => {
    expect(classifyDiagramHtmlUpload('architecture.html', darkHtml, darkHtml.length)?.diagramKind).toBe('architecture');
    expect(classifyDiagramHtmlUpload('page.html', '<html><body><svg viewBox="0 0 100 100"></svg></body></html>', 70)).toBeNull();
    const unsafe = darkHtml.replace('</style>', 'rect{fill:u\\72l(https://evil.example/a.svg)}</style>');
    expect(classifyDiagramHtmlUpload('architecture.html', unsafe, unsafe.length)).toBeNull();
  });
});
