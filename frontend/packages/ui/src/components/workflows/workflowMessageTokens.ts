import type { JSONContent } from '@tiptap/core';
import type { Output } from './workflowBuilder';

export const WORKFLOW_OUTPUT_NODE = 'workflowOutput';
const friendly = (value: string): string => value.replace(/[._]/g, ' ').replace(/\b\w/g, letter => letter.toUpperCase());

export function outputTemplateSyntax(reference: string): string {
  return `{{${reference.replace(/^\$nodes\./, 'steps.').replace('.output.', '.')}}}`;
}

export function outputToken(output: Pick<Output, 'reference' | 'label'>): JSONContent {
  return { type: WORKFLOW_OUTPUT_NODE, attrs: { mentionType: 'workflow_output', displayName: output.label, mentionSyntax: outputTemplateSyntax(output.reference), mentionId: output.reference } };
}

function parsedToken(expression: string, outputs: Pick<Output, 'reference' | 'label'>[]): JSONContent {
  const path = expression.trim();
  const reference = path.startsWith('steps.') ? path.replace(/^steps\.([^.]+)\./, '$nodes.$1.output.') : path;
  const known = outputs.find(output => output.reference === reference);
  if (known) return outputToken(known);
  const parts = reference.match(/^\$nodes\.([^.]+)\.output\.(.+)$/);
  const displayName = parts ? `${friendly(parts[1])} · ${friendly(parts[2])}` : path === 'clock.now' ? 'Current date and time' : path.startsWith('trigger.') ? friendly(path.slice(8)) : 'Selected output';
  return { type: WORKFLOW_OUTPUT_NODE, attrs: { mentionType: 'workflow_output', displayName, mentionSyntax: `{{${path}}}`, mentionId: reference } };
}

/** Templates are storage syntax only; editors receive plain text and atomic labels. */
export function templateToDocument(template: string, outputs: Pick<Output, 'reference' | 'label'>[] = []): JSONContent {
  return { type: 'doc', content: template.split('\n').map(line => {
    const content: JSONContent[] = [];
    let offset = 0;
    for (const match of line.matchAll(/\{\{\s*([^{}]+?)\s*\}\}/g)) {
      if (match.index! > offset) content.push({ type: 'text', text: line.slice(offset, match.index) });
      content.push(parsedToken(match[1], outputs));
      offset = match.index! + match[0].length;
    }
    if (offset < line.length) content.push({ type: 'text', text: line.slice(offset) });
    return { type: 'paragraph', content };
  }) };
}

/** The existing backend still receives the same canonical deterministic template. */
export function documentToTemplate(document: JSONContent): string {
  function serialize(node: JSONContent): string {
    if (node.type === WORKFLOW_OUTPUT_NODE) return typeof node.attrs?.mentionSyntax === 'string' ? node.attrs.mentionSyntax : '';
    if (node.type === 'text') return node.text ?? '';
    if (node.type === 'hardBreak') return '\n';
    return (node.content ?? []).map(serialize).join(node.type === 'doc' ? '\n' : '');
  }
  return serialize(document);
}
