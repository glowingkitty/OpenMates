/**
 * Text-only renderers for Diagrams embed types.
 * Used by copy-to-clipboard, markdown export, and CLI output.
 */

import { renderMermaidText } from './mermaidDiagramContent';

export function renderMermaidDiagram(c: Record<string, unknown>): string {
	return renderMermaidText(c, true);
}
