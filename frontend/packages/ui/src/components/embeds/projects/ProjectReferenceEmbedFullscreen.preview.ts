const content = { type: 'app-skill-use', app_id: 'projects', skill_id: 'search', query: 'README',
  results: [
    { project_id: 'preview-project', project_name: 'OpenMates', source_id: 'preview-source', path: 'README.md', line: 12 },
    { project_id: 'preview-project', project_name: 'OpenMates', embed_id: 'preview-hosted-file', path: 'docs/architecture.md' },
  ] };
const standard = { data: { decodedContent: content, embedData: { status: 'finished' } }, embedId: 'preview-project-reference', onClose: () => {} };
export default standard;
export const variants = {
  empty: { ...standard, data: { decodedContent: { ...content, results: [] }, embedData: { status: 'finished' } } },
  processing: { ...standard, data: { decodedContent: { ...content, results: [] }, embedData: { status: 'processing' } } },
};
