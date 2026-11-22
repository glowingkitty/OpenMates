/** Preview fixtures for the chat-history "Project file changed" system event (projects/change embed rows). */
const sha = (n: string) => n.repeat(64);
const row = (path: string, n: string) => ({ project_id: 'project-1', project_name: 'Web app', path, action: 'updated' as const, expected_base: sha(n) });
const diff = (path: string) => `--- a/${path}\n+++ b/${path}\n@@ -1 +1 @@\n-old\n+new\n`;
const live = (path: string) => ({ id: path, kind: 'write' as const, status: 'applied' as const,
  request: { projectId: 'project-1', chatId: 'chat-1', mutation: { operation: 'update_file', operation_id: path, path, expected_base: sha('a'), patch: diff(path) } } });
const paths = ['web-app/package.json', 'web-app/package-lock.json', 'web-app/src/main.ts'];

export default { rows: [row(paths[0], 'a')], entries: [live(paths[0])] };
export const variants = {
  several: { rows: paths.map((path) => row(path, 'a')), entries: paths.map(live) },
  /** After a reload no in-memory diff exists. */
  reloaded: { rows: [row(paths[0], 'a')], entries: [] },
};
