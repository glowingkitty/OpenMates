/** Classify only explicit, self-contained OpenMates diagram HTML uploads. */
import { validateDiagramHtml } from '../../embeds/diagrams/diagramHtmlContent';

export interface DiagramHtmlUpload {
  title: string;
  diagramKind: string;
  renderWidth: number;
  renderHeight: number;
}

export function classifyDiagramHtmlUpload(filename: string, source: string, sizeBytes: number): DiagramHtmlUpload | null {
  if (!filename.toLowerCase().endsWith('.html') || sizeBytes > 750_000 || !source.includes('data-om-diagram')) return null;
  try {
    const document = validateDiagramHtml(source);
    const svg = document.querySelector('svg[data-om-diagram][viewBox]');
    if (!svg || !svg.querySelector('g[data-om-component]')) return null;
    const diagramKind = svg.getAttribute('data-om-diagram') || 'diagram';
    if (!/^[a-z][a-z0-9_-]{0,63}$/i.test(diagramKind)) return null;
    const width = Number(document.documentElement.getAttribute('data-om-render-width'));
    const height = Number(document.documentElement.getAttribute('data-om-render-height'));
    return {
      title: document.title.trim() || filename.replace(/\.html$/i, ''),
      diagramKind,
      renderWidth: Number.isInteger(width) && width >= 200 && width <= 4096 ? width : 1240,
      renderHeight: Number.isInteger(height) && height >= 200 && height <= 4096 ? height : 900,
    };
  } catch { return null; }
}
