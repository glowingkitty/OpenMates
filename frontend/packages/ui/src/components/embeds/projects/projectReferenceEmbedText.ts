import { projectFileReferences, stringField } from './projectReferenceData';
import { readProjectFileChangeRows } from '../../projects/projectFileChangeEvent';

export function renderProjectReferences(content: Record<string, unknown>): string {
  const refs = projectFileReferences(content);
  const query = stringField(content.query) || 'Files';
  const projectName = refs[0]?.project_name || stringField(content.project_name);
  const lines = [`**Projects | ${stringField(content.skill_id) === 'read' ? 'Read' : 'Search'}**`,
    `query: ${query}`];
  if (projectName) lines.push(`project: ${projectName}`);
  if (!refs.length) lines.push('No file references found');
  for (const ref of refs) lines.push(`- ${ref.project_name ? `${ref.project_name}: ` : ''}${ref.path}${ref.line ? `:${ref.line}` : ''}`);
  return lines.join('\n');
}

/** Text form of an applied file-change system event: one line per changed path, no file content. */
export function renderProjectFileChanges(content: Record<string, unknown>): string {
  const rows = readProjectFileChangeRows(content);
  const lines = ['**Projects | File changed**'];
  if (rows[0]?.project_name) lines.push(`project: ${rows[0].project_name}`);
  for (const row of rows) {
    lines.push(`- ${row.action}: ${row.action === 'renamed' && row.from_path ? `${row.from_path} → ` : ''}${row.path}`);
  }
  return lines.join('\n');
}
