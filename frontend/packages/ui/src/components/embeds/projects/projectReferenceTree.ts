/** Folder-tree rows for the Project read card: folders first, files indented below them. */
export interface ProjectReferenceTreeRow {
  kind: 'folder' | 'file';
  name: string;
  depth: number;
}

export interface ProjectReferenceTree {
  rows: ProjectReferenceTreeRow[];
  /** Files that did not fit into `maxRows`; the card shows them as "+N more". */
  hiddenFiles: number;
}

/** Rows (folders not yet emitted, then the file) one path adds to the tree. */
function rowsFor(path: string, emitted: Set<string>): { rows: ProjectReferenceTreeRow[]; keys: string[] } {
  const parts = path.split('/');
  const rows: ProjectReferenceTreeRow[] = [];
  const keys: string[] = [];
  parts.slice(0, -1).forEach((name, index) => {
    const key = parts.slice(0, index + 1).join('/');
    if (emitted.has(key) || keys.includes(key)) return;
    keys.push(key);
    rows.push({ kind: 'folder', name, depth: index });
  });
  rows.push({ kind: 'file', name: parts[parts.length - 1], depth: parts.length - 1 });
  return { rows, keys };
}

/**
 * Group unique paths by folder (sorted) within `maxRows` visible rows, folder rows
 * included, so the tree fits the fixed-height card. When not every file fits, one
 * row is kept free for the "+N more" line.
 */
export function buildProjectReferenceTree(paths: string[], maxRows = 5): ProjectReferenceTree {
  const unique = [...new Set(paths)].sort((a, b) => a.localeCompare(b));
  const build = (budget: number): ProjectReferenceTree => {
    const rows: ProjectReferenceTreeRow[] = [];
    const emitted = new Set<string>();
    let shown = 0;
    for (const path of unique) {
      const next = rowsFor(path, emitted);
      if (rows.length + next.rows.length > budget) break;
      next.keys.forEach((key) => emitted.add(key));
      rows.push(...next.rows);
      shown += 1;
    }
    return { rows, hiddenFiles: unique.length - shown };
  };
  const all = build(maxRows);
  return all.hiddenFiles === 0 ? all : build(Math.max(maxRows - 1, 1));
}
