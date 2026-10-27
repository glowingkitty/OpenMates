import { browseContent } from './browseContent';
import { str, trunc } from '../../../data/embedTextRenderers';

export function renderBrowse(content: Record<string, unknown>): string {
  const result = browseContent(content);
  return [
    `**Browse** — ${result.status}`,
    str(result.title), str(result.url), str(result.reason),
    result.data === null ? null : trunc(JSON.stringify(result.data, null, 2), 24000),
  ].filter(Boolean).join('\n');
}
