import { describe, expect, it, vi } from "vitest";
import type { EmbedStoreEntry } from "../../message_parsing/types";
import { EmbedStore } from "../embedStore";

function seedCandidate(store: EmbedStore, contentRef: string): void {
  const entry: EmbedStoreEntry = {
    contentRef,
    type: "code-code",
    createdAt: 1,
    updatedAt: 1,
    embed_id: contentRef.replace("embed:", ""),
    file_path: `src/${contentRef.replace("embed:", "")}.ts`,
  };
  (store as unknown as { uploadedFileCandidates: EmbedStoreEntry[] }).uploadedFileCandidates = [entry];
}

describe("uploaded-file live search performance", () => {
  // contract-test: supporting surface=gui.web assertions=message-input.suggestions.contextual
  it("reuses indexed filename metadata across warm searches", async () => {
    const store = new EmbedStore();
    seedCandidate(store, "embed:warm-file");
    const getNames = vi
      .spyOn(store as unknown as {
        getSearchableFileNames(entry: EmbedStoreEntry): Promise<string[]>;
      }, "getSearchableFileNames")
      .mockResolvedValue(["warm-file.ts"]);

    await expect(store.searchUploadedFiles("warm")).resolves.toHaveLength(1);
    await expect(store.searchUploadedFiles("file")).resolves.toHaveLength(1);

    expect(getNames).toHaveBeenCalledTimes(1);
  });

  // contract-test: supporting surface=gui.web assertions=message-input.suggestions.contextual
  it("stops an obsolete search before resolving filename metadata", async () => {
    const store = new EmbedStore();
    seedCandidate(store, "embed:cancelled-file");
    const getNames = vi.spyOn(
      store as unknown as {
        getSearchableFileNames(entry: EmbedStoreEntry): Promise<string[]>;
      },
      "getSearchableFileNames",
    );
    const controller = new AbortController();
    controller.abort();

    await expect(
      store.searchUploadedFiles("cancelled", undefined, controller.signal),
    ).rejects.toMatchObject({ name: "AbortError" });
    expect(getNames).not.toHaveBeenCalled();
  });
});
