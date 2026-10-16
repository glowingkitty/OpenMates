// contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
import { describe, expect, it } from 'vitest';
import darkHtml from './diagramHtmlExampleDark.html?raw';
import lightHtml from './diagramHtmlExampleLight.html?raw';
import { diagramHtmlDecorativeFixture } from './diagramHtmlDecorativeFixture';
import { generatedDiagramArtifacts } from './diagramHtmlGeneratedArtifacts';
import { buildDiagramFrame, buildDiagramSrcdoc, diagramBackgroundColor, validateDiagramHtml } from './diagramHtmlContent';

describe('HTML diagram isolation', () => {
  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it('preserves static rounded elbows and arc bridges while rejecting invalid editable paths', () => {
    const paths = [
      'M 110,30 H 142 Q 150,30 150,38 V 52 Q 150,60 158,60 H 200',
      'M 110,30 H 142 a 8,8 0 0,1 16,0 H 200',
      'M 110,30 C 120,40 180,40 200,30',
    ];
    const source = (path: string) => `<html><head><title>Rounded connector</title></head><body><svg data-om-diagram="architecture" viewBox="0 0 300 200"><g data-om-component="from"></g><g data-om-component="to"></g><g data-om-edge="route" data-om-from="from" data-om-to="to" data-om-from-side="right" data-om-to-side="left"><path data-om-path d="${path}"/></g></svg></body></html>`;
    for (const path of paths) {
      expect(validateDiagramHtml(source(path)).querySelector('path')?.getAttribute('d')).toBe(path);
    }
    expect(() => validateDiagramHtml(source('M 110,30 javascript:alert(1)'))).toThrow();
    expect(() => validateDiagramHtml(source('H 200'))).toThrow();
    expect(() => validateDiagramHtml(source(paths[0]).replace('data-om-to="to"', 'data-om-to="missing"'))).toThrow();
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
  it('uses the canonical page color for the outer preview and fullscreen surround', () => {
    expect(buildDiagramFrame(darkHtml).backgroundColor).toBe('#2d3142');
    expect(buildDiagramFrame(lightHtml).backgroundColor).toBe('#f5f5f5');
    expect(diagramBackgroundColor(darkHtml.replace(' data-om-background="#2d3142"', ''))).toBe('#2d3142');
    expect(diagramBackgroundColor(lightHtml.replace(' data-om-background="#f5f5f5"', ''))).toBe('#f5f5f5');
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
  it('prefers safe declared color and ignores unsafe or unresolved CSS colors', () => {
    expect(diagramBackgroundColor(darkHtml.replace('data-om-background="#2d3142"', 'data-om-background="#123456"'))).toBe('#123456');
    expect(diagramBackgroundColor(darkHtml.replace('data-om-background="#2d3142"', 'data-om-background="navy"'))).toBe('navy');
    expect(diagramBackgroundColor(darkHtml.replace('data-om-background="#2d3142"', 'data-om-background="hsl(220 20% 22%)"'))).toBe('hsl(220 20% 22%)');
    expect(diagramBackgroundColor(darkHtml.replace('data-om-background="#2d3142"', 'data-om-background="rgb(45 49 66)"'))).toBe('rgb(45 49 66)');
    const noDeclaration = darkHtml.replace('data-om-background="#2d3142"', 'data-om-background="var(--bad)"');
    expect(diagramBackgroundColor(noDeclaration)).toBe('#2d3142');
    expect(diagramBackgroundColor(noDeclaration.replace(/--color-paper:\s*#2d3142/g, '--color-paper: navy'))).toBe('navy');
    expect(diagramBackgroundColor(noDeclaration.replace(/--color-paper:\s*#2d3142/g, '--color-paper: hsl(220 20% 22%)'))).toBe('hsl(220 20% 22%)');
    expect(diagramBackgroundColor(noDeclaration.replace(/--color-paper:\s*#2d3142/g, '--color-paper: transparent'))).toBe('#ffffff');
    expect(diagramBackgroundColor(noDeclaration.replace(/--color-paper:\s*#2d3142/g, '--color-paper: var(--missing)'))).toBe('#ffffff');
    expect(diagramBackgroundColor(darkHtml.replace('data-om-background="#2d3142"', 'data-om-background="red; background: blue"'))).toBe('#2d3142');
    expect(() => diagramBackgroundColor(noDeclaration.replace(/--color-paper:\s*#2d3142/g, '--color-paper: red; background-image: url(https://invalid.example/x)'))).toThrow();
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
  it('preserves the substantial upstream composition and injects only a local font', () => {
    const rendered = buildDiagramSrcdoc(darkHtml);
    expect(rendered).toContain('High-level architecture');
    expect(rendered).toContain('data-om-component="nifi"');
    expect(rendered).toContain('data-om-edge="nifi-trino"');
    expect(rendered).toContain('data:font/woff2;base64,');
    expect(rendered).not.toContain('fonts.googleapis.com');
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
  it.each([
    '<script nonce="diagram-editor">parent.postMessage("leak","*")</script>',
    '<svg><script nonce="diagram-editor">alert(1)</script></svg>',
    '<svg><foreignObject><iframe srcdoc="bad"></iframe></foreignObject></svg>',
    '<svg><style>@import url(https://evil.example/a.css)</style></svg>',
    '<svg><style>@\\69mport "https://evil.example/a.css";</style></svg>',
    '<svg><style>rect{fill:u\\72l(https://evil.example/a.svg)}</style></svg>',
    '<svg><rect style="fill:url(https://evil.example/a.svg)"/></svg>',
    '<svg><image href="https://evil.example/a.svg"/></svg>',
    '<svg><text onclick="alert(1)">bad</text></svg>',
  ])('rejects active or external generated markup: %s', (injection) => {
    expect(() => validateDiagramHtml(`<!DOCTYPE html><html><body><svg viewBox="0 0 100 100"></svg>${injection}</body></html>`)).toThrow();
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
  it('accepts quoted local SVG paint references', () => {
    expect(() => validateDiagramHtml('<html><head><title>Safe</title></head><body><svg data-om-diagram="safe" viewBox="0 0 100 100"><style>rect{fill:url(\'#dots\')}</style><rect fill="url(&quot;#dots&quot;)"/></svg></body></html>')).not.toThrow();
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
  it('requires a complete original document rather than a DOMParser-repaired fragment', () => {
    expect(() => validateDiagramHtml('<svg viewBox="0 0 100 100"></svg>')).toThrow();
    expect(() => validateDiagramHtml('<html><body><svg viewBox="0 0 100 100"></svg></body></html>')).toThrow();
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence,chats.layout.responsive-history
  it('accepts bounded embedded WOFF2 only within a font face', () => {
    const font = btoa('wOF2' + 'test-font');
    const base = `<html><head><title>Safe</title><style>@font-face{font-family:Local;src:url(data:font/woff2;base64,${font})}</style></head><body><svg data-om-diagram="safe" viewBox="0 0 100 100"></svg></body></html>`;
    expect(() => validateDiagramHtml(base)).not.toThrow();
    expect(() => validateDiagramHtml(base.replace('@font-face', 'rect'))).toThrow();
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it('requires exactly one primary SVG while permitting a leading decoration', () => {
    expect(() => validateDiagramHtml(diagramHtmlDecorativeFixture)).not.toThrow();
    expect(() => validateDiagramHtml(diagramHtmlDecorativeFixture.replace('data-om-diagram="architecture"', ''))).toThrow();
    expect(() => validateDiagramHtml(diagramHtmlDecorativeFixture.replace('</body>', '<svg data-om-diagram="second" viewBox="0 0 10 10"></svg></body>'))).toThrow();
  });

  // contract-test: supporting surface=gui.web assertions=chats.rendering.assistant-document-convergence
  it('accepts the exact passwordless sequence produced by a real model request', () => {
    const source = generatedDiagramArtifacts.generatedPasswordless.html_source;
    const document = validateDiagramHtml(source);
    expect(document.querySelector('svg[data-om-diagram="sequence"]')).not.toBeNull();
    expect(document.querySelectorAll('g[data-om-edge]')).toHaveLength(10);
    expect(document.querySelector('g[data-om-edge="msg-7"]')?.textContent).toContain('401 CODE EXPIRED');
  });
});
