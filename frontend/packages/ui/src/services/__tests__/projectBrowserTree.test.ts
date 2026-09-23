import { describe, expect, it } from "vitest";

import type { ProjectItemViewModel } from "../projectService";
import {
  projectBrowserItemName,
  projectVirtualBreadcrumbs,
  projectVirtualBrowserView,
} from "../projectBrowserTree";

function item(id: string, path?: string, folderHash?: string): ProjectItemViewModel {
  return {
    project_item_id: id,
    item_type: "embed",
    target_id: `embed-${id}`,
    displayName: path ?? id,
    metadata: path ? { source: "hosted_project_file", path } : {},
    encrypted: {
      project_item_id: id,
      item_type: "embed",
      target_id_hash: `hash-${id}`,
      target_id_encrypted: `cipher-${id}`,
      hashed_folder_id: folderHash ?? null,
      created_at: 1,
      updated_at: 1,
      position: 0,
    },
  };
}

describe("hosted Project virtual browser tree", () => {
  // contract-test: direct surface=gui.web assertions=projects.files.hosted-ciphertext-commit
  it("derives nested folders locally while preserving root and manual-folder items", () => {
    const values = [
      item("nested", "src/components/Button.ts"),
      item("source", "src/index.ts"),
      item("root", "README.md"),
      item("linked"),
      item("manual", "manual/file.ts", "folder-hash"),
    ];

    expect(projectVirtualBrowserView(values, null)).toEqual({
      folders: [{ name: "src", path: "src" }],
      items: [values[2], values[3]],
    });
    expect(projectVirtualBrowserView(values, "src")).toEqual({
      folders: [{ name: "components", path: "src/components" }],
      items: [values[1]],
    });
    expect(projectBrowserItemName(values[0]!)).toBe("Button.ts");
    expect(projectVirtualBreadcrumbs("src/components")).toEqual([
      { name: "src", path: "src" },
      { name: "components", path: "src/components" },
    ]);
  });
});
