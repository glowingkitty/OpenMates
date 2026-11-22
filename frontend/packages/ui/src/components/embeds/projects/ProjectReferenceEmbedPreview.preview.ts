const references = [
  { project_id: 'preview-project', project_name: 'OpenMates', source_id: 'preview-source', path: 'README.md', line: 12 },
  { project_id: 'preview-project', project_name: 'OpenMates', embed_id: 'preview-hosted-file', path: 'docs/architecture.md' },
];
const recipeFile = (path: string) => ({ project_id: 'recipe-project', project_name: 'Recipe Manager', embed_id: `hosted-${path}`, path });
const readContent = (paths: string[]) => ({ type: 'app-skill-use', app_id: 'projects', skill_id: 'read',
  query: paths.join(', '), project_name: 'Recipe Manager', results: paths.map(recipeFile) });
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
  searchOne: { ...standard, content: { ...standard.content, results: references.slice(0, 1) } },
  readOne: { ...standard, skillId: 'read' as const, content: readContent(['README.md']) },
  readSeveral: { ...standard, skillId: 'read' as const,
    content: readContent(['README.md', 'src/main.py', 'docs/guide.md']) },
  readMany: { ...standard, skillId: 'read' as const,
    content: readContent(['README.md', 'src/main.py', 'src/recipes/pasta.py', 'src/recipes/soup.py', 'docs/guide.md', 'docs/setup.md', 'tests/test_main.py', 'LICENSE']) },
  mobile: { ...standard, isMobile: true },
};
