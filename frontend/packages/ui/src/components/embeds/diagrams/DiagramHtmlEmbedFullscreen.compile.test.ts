// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
import { readFileSync } from 'node:fs';
import { compile } from 'svelte/compiler';
import { describe, expect, it } from 'vitest';

describe('diagram fullscreen snippet bindings', () => {
  it('keeps the diagram payload distinct from the required content snippet', () => {
    const filename = new URL('./DiagramHtmlEmbedFullscreen.svelte', import.meta.url);
    const compiled = compile(readFileSync(filename, 'utf8'), { filename: filename.pathname, generate: 'client' }).js.code;
    expect(compiled).toContain('const content = ');
    expect(compiled).toContain('const diagram = $.derived');
    expect(compiled).toContain('$.get(diagram).title');
    expect(compiled).not.toContain('$.get(content)');
  });
});
