import { projectFileReferences, stringField } from './projectReferenceData';

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
