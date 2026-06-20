// frontend/packages/ui/src/services/__tests__/applicationProjectZip.test.ts
// Regression coverage for application embed project downloads.
// The fullscreen component delegates to zipExportService, so this test keeps the
// behavior focused on resolving child code embeds and preserving manifest paths.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import JSZip from "jszip";

const mockLoadEmbeds = vi.hoisted(() => vi.fn());
const mockDecodeToonContent = vi.hoisted(() => vi.fn());
let createdBlob: Blob | undefined;

vi.mock("../embedResolver", () => ({
  loadEmbeds: mockLoadEmbeds,
  decodeToonContent: mockDecodeToonContent,
  extractEmbedReferences: vi.fn(() => []),
}));

import { downloadApplicationProjectZip } from "../zipExportService";

describe("downloadApplicationProjectZip", () => {
  beforeEach(() => {
    mockLoadEmbeds.mockReset();
    mockDecodeToonContent.mockReset();
    createdBlob = undefined;
    vi.spyOn(URL, "createObjectURL").mockImplementation((blob) => {
      createdBlob = blob as Blob;
      return "blob:application-zip";
    });
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("preserves application manifest paths and strips code headers", async () => {
    const clicked: HTMLAnchorElement[] = [];
    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tagName: string) => {
      const element = originalCreateElement(tagName);
      if (tagName.toLowerCase() === "a") {
        vi.spyOn(element as HTMLAnchorElement, "click").mockImplementation(() => {
          clicked.push(element as HTMLAnchorElement);
        });
      }
      return element;
    });

    mockLoadEmbeds.mockResolvedValue([
      { embed_id: "file-1", content: "toon-1", type: "code", status: "finished" },
      { embed_id: "file-2", content: "toon-2", type: "code", status: "finished" },
    ]);
    mockDecodeToonContent.mockImplementation(async (content: string) => {
      if (content === "toon-1") {
        return { code: "svelte:ignored/path.svelte\n<script>let count = 1;</script>", language: "svelte" };
      }
      return { code: "export const main = true;", language: "typescript" };
    });

    await downloadApplicationProjectZip({
      appName: "Recipe App",
      fileRefs: [
        { embed_id: "file-1", path: "src/App.svelte" },
        { embed_id: "file-2", path: "src/main.ts" },
      ],
    });

    expect(clicked).toHaveLength(1);
    expect(clicked[0].download).toBe("recipe-app.zip");
    expect(mockLoadEmbeds).toHaveBeenCalledWith(["file-1", "file-2"]);

    expect(createdBlob).toBeInstanceOf(Blob);
    const zip = await JSZip.loadAsync(await createdBlob!.arrayBuffer());
    await expect(zip.file("src/App.svelte")?.async("string")).resolves.toBe("<script>let count = 1;</script>");
    await expect(zip.file("src/main.ts")?.async("string")).resolves.toBe("export const main = true;");
  });
});
