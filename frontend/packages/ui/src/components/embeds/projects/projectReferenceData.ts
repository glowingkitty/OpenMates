/** Project skill embeds contain references, never copies of connected file content. */
export interface ProjectFileReference {
  project_id: string;
  project_name: string;
  team_id?: string | null;
  source_id?: string;
  path: string;
  embed_id?: string;
  line?: number;
  expected_base?: string;
}

export function projectFileReferences(content: Record<string, unknown>): ProjectFileReference[] {
  const results = Array.isArray(content.results) ? content.results : [];
  return results.flatMap((value): ProjectFileReference[] => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
    const row = value as Record<string, unknown>;
    const projectId = stringField(row.project_id) || stringField(content.project_id);
    const projectName = stringField(row.project_name) || stringField(content.project_name) || '';
    const sourceId = stringField(row.source_id);
    const embedId = stringField(row.embed_id);
    const path = stringField(row.path);
    if (!projectId || !path || (!sourceId && !embedId)) return [];
    const line = typeof row.line === 'number' && Number.isInteger(row.line) && row.line > 0 ? row.line : undefined;
    const teamId = stringField(row.team_id) || stringField(content.team_id);
    const revisionHash = stringField(row.expected_base);
    return [{ project_id: projectId, project_name: projectName, path,
      ...(sourceId ? { source_id: sourceId } : {}), ...(embedId ? { embed_id: embedId } : {}),
      ...(teamId ? { team_id: teamId } : {}), ...(line ? { line } : {}),
      ...(revisionHash && /^[a-f0-9]{64}$/.test(revisionHash) ? { expected_base: revisionHash } : {}) }];
  });
}

export function stringField(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}
