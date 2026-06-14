/**
 * Text-only renderers for code embed types.
 * Used by copy-to-clipboard, markdown export, and CLI.
 */

import { str } from '../../../data/embedTextRenderers';

/** code-code — code block embed */
export function renderCode(c: Record<string, unknown>): string {
	const lang = str(c.language) ?? '';
	const filename = str(c.filename) ?? '';
	const lineCount = c.line_count;
	const lines: string[] = [];

	const header = [filename, lang].filter(Boolean).join(' · ');
	lines.push(`**Code**${header ? ` — ${header}` : ''}`);
	if (lineCount) lines.push(`${lineCount} lines`);

	const code = str(c.code) ?? str(c.content) ?? '';
	if (code) {
		const codeLines = code.split('\n').slice(0, 6);
		lines.push('```' + (lang || ''));
		lines.push(...codeLines);
		if (code.split('\n').length > 6) lines.push('...');
		lines.push('```');
	}
	return lines.join('\n');
}

/** app:code:get_docs — documentation lookup */
export function renderCodeDocs(c: Record<string, unknown>): string {
	const results = c.results as Array<Record<string, unknown>> | undefined;
	const first = Array.isArray(results) ? results[0] : null;
	const libId = (first?.library as Record<string, unknown>)?.id ?? first?.library_id ?? str(c.library);
	const wordCount = first?.word_count ?? c.word_count;
	const lines: string[] = ['**Documentation**'];
	if (libId) lines.push(`Library: ${String(libId)}`);
	if (wordCount) lines.push(`${String(wordCount)} words`);
	return lines.join('\n');
}

/** app:code:search_repos — GitHub repository search */
export function renderCodeRepoSearch(
  c: Record<string, unknown>,
  children: Record<string, unknown>[] = []
): string {
  const query = str(c.query) ?? 'repository search';
  const count = typeof c.result_count === 'number' ? c.result_count : children.length;
  const lines = [`**Repository search** — ${query}`];
  lines.push(`${count} ${count === 1 ? 'repository' : 'repositories'}`);
  for (const child of children.slice(0, 5)) {
    const fullName = str(child.full_name) ?? str(child.url);
    if (fullName) lines.push(`- ${fullName}`);
  }
  return lines.join('\n');
}

/** code-repo — GitHub repository embed */
export function renderCodeRepo(c: Record<string, unknown>): string {
  const fullName = str(c.full_name) ?? str(c.url) ?? 'GitHub repository';
  const description = str(c.description);
  const language = str(c.primary_language);
  const license = str(c.license_spdx_id) && str(c.license_spdx_id) !== 'NOASSERTION'
    ? str(c.license_spdx_id)
    : str(c.license_name);
  const lines = [`**Repository** — ${fullName}`];
  if (description) lines.push(description);
  const facts = [language, license, c.stars !== undefined ? `${c.stars} stars` : null, c.forks !== undefined ? `${c.forks} forks` : null].filter(Boolean);
  if (facts.length) lines.push(facts.join(' · '));
  return lines.join('\n');
}

/** code-application — generated application parent embed */
export function renderApplication(c: Record<string, unknown>): string {
  const name = str(c.name) ?? 'Application';
  const framework = str(c.framework);
  const runtime = str(c.runtime);
  const fileRefs = Array.isArray(c.file_refs) ? c.file_refs : [];
  const lines = [`**Application** — ${name}`];
  const facts = [framework, runtime, fileRefs.length ? `${fileRefs.length} files` : null].filter(Boolean);
  if (facts.length) lines.push(facts.join(' · '));
  for (const file of fileRefs.slice(0, 8)) {
    if (file && typeof file === 'object' && 'path' in file) {
      lines.push(`- ${String((file as { path?: unknown }).path)}`);
    }
  }
  return lines.join('\n');
}
