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
  // contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity
  it("keeps an adopted application inside its folder as the first entry, never at the root", () => {
    const application = item("app");
    application.metadata = { source: "project_application", path: "web-app", entry_path: "src/App.jsx" };
    const items = [
      item("manifest", "web-app/package.json"),
      application,
      item("entry", "web-app/src/App.jsx"),
      item("loose"),
    ];
    const root = projectVirtualBrowserView(items, null);
    expect(root.items.map((entry) => entry.project_item_id)).toEqual(["loose"]);
    expect(root.folders.map((folder) => [folder.name, folder.children])).toEqual([
      ["web-app", [{ name: "src", kind: "folder" }, { name: "package.json", kind: "file" }]],
    ]);
    const opened = projectVirtualBrowserView(items, "web-app");
    expect(opened.items.map((entry) => entry.project_item_id)).toEqual(["app", "manifest"]);
    expect(opened.folders.map((folder) => folder.name)).toEqual(["src"]);
  });

  // contract-test: supporting surface=gui.web assertions=projects.surface.semantic-parity
  it("lists a folder that only holds an application", () => {
    const application = item("app");
    application.metadata = { source: "project_application", path: "tools/web-app" };
    expect(projectVirtualBrowserView([application], null).folders.map((folder) => folder.path)).toEqual(["tools"]);
    expect(projectVirtualBrowserView([application], "tools").folders.map((folder) => folder.path)).toEqual(["tools/web-app"]);
    expect(projectVirtualBrowserView([application], "tools/web-app").items).toHaveLength(1);
  });

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
      folders: [{ name: "src", path: "src", children: [
        { name: "components", kind: "folder" },
        { name: "index.ts", kind: "file" },
      ] }],
      items: [values[2], values[3]],
    });
    expect(projectVirtualBrowserView(values, "src")).toEqual({
      folders: [{ name: "components", path: "src/components", children: [{ name: "Button.ts", kind: "file" }] }],
      items: [values[1]],
    });
    expect(projectBrowserItemName(values[0]!)).toBe("Button.ts");
    expect(projectVirtualBreadcrumbs("src/components")).toEqual([
      { name: "src", path: "src" },
      { name: "components", path: "src/components" },
    ]);
  });
});
