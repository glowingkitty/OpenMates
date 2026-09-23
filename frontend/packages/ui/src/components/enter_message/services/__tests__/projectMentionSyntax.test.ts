import { describe, expect, it } from "vitest";
import { buildProjectMentionSyntax } from "../projectMentionSyntax";

describe("Project mention syntax", () => {
  // contract-test: direct surface=gui.web assertions=projects.files.chat-focus-required,projects.surface.semantic-parity
  it("retains the selected remote source id in folder and file mentions", () => {
    expect(buildProjectMentionSyntax(
      "project_folder",
      "project-1",
      "read",
      "src/components",
      "source-1",
    )).toBe("@project-folder:project-1:source-1:src%2Fcomponents:read");
    expect(buildProjectMentionSyntax(
      "project_file",
      "project-1",
      "read_write",
      "src/main.ts",
      "source-1",
    )).toBe("@project-file:project-1:source-1:src%2Fmain.ts:read_write");
  });

  // contract-test: supporting surface=gui.web assertions=projects.files.chat-focus-required
  it("keeps whole-Project mentions and legacy hosted paths source-neutral", () => {
    expect(buildProjectMentionSyntax("project", "project-1", "read_write"))
      .toBe("@project:project-1:read_write");
    expect(buildProjectMentionSyntax("project_file", "project-1", "read", "notes.md"))
      .toBe("@project-file:project-1:notes.md:read");
  });
});
