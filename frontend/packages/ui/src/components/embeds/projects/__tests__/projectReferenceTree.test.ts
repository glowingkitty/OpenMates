import { describe, expect, it } from 'vitest';
import { buildProjectReferenceTree } from '../projectReferenceTree';

describe('buildProjectReferenceTree', () => {
  // contract-test: supporting surface=gui.web assertions=projects.files.search-scoped
  it('groups files under their folder once', () => {
    const tree = buildProjectReferenceTree(['docs/b.md', 'README.md', 'docs/a.md']);
    expect(tree.rows.map((r) => `${r.depth}:${r.kind}:${r.name}`)).toEqual([
      '0:folder:docs', '1:file:a.md', '1:file:b.md', '0:file:README.md',
    ]);
    expect(tree.hiddenFiles).toBe(0);
  });

  // contract-test: supporting surface=gui.web assertions=projects.files.search-scoped
  it('keeps one row free for "+N more" when not every file fits', () => {
    const tree = buildProjectReferenceTree(['a', 'b', 'c', 'd'], 3);
    expect(tree.rows.map((r) => r.name)).toEqual(['a', 'b']);
    expect(tree.hiddenFiles).toBe(2);
  });

  // contract-test: supporting surface=gui.web assertions=projects.files.search-scoped
  it('counts folder rows against the row limit', () => {
    const tree = buildProjectReferenceTree(['docs/guide.md', 'docs/setup.md', 'LICENSE', 'README.md', 'src/main.py'], 5);
    expect(tree.rows.map((r) => r.name)).toEqual(['docs', 'guide.md', 'setup.md', 'LICENSE']);
    expect(tree.hiddenFiles).toBe(2);
  });

  // contract-test: supporting surface=gui.web assertions=projects.files.search-scoped
  it('shows every file when the whole tree fits exactly', () => {
    const tree = buildProjectReferenceTree(['README.md', 'docs/guide.md', 'src/main.py'], 5);
    expect(tree.rows).toHaveLength(5);
    expect(tree.hiddenFiles).toBe(0);
  });
});
