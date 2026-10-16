const references = [
  { project_id: 'preview-project', project_name: 'OpenMates', source_id: 'preview-source', path: 'README.md', line: 12 },
  { project_id: 'preview-project', project_name: 'OpenMates', embed_id: 'preview-hosted-file', path: 'docs/architecture.md' },
];
const standard = {
  id: 'preview-project-reference', content: { type: 'app-skill-use', app_id: 'projects', skill_id: 'search',
    query: 'README', search_target: 'files', results: references }, status: 'finished' as const,
  skillId: 'search' as const, isMobile: false,
  onFullscreen: () => window.dispatchEvent(new CustomEvent('project-reference-fullscreen-request')),
};
export default standard;
export const variants = {
  processing: { ...standard, status: 'processing' as const, content: { ...standard.content, results: [] } },
  textSearch: { ...standard, content: { ...standard.content, search_target: 'content' } },
  empty: { ...standard, content: { ...standard.content, results: [] } },
  legacyEmpty: { ...standard, content: { type: 'projects-search', app_id: 'projects', skill_id: 'search', query: 'README', results: [] } },
  read: { ...standard, skillId: 'read' as const, content: { ...standard.content, skill_id: 'read' } },
  mobile: { ...standard, isMobile: true },
};
