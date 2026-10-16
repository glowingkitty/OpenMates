import { beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({ key: vi.fn(), decrypt: vi.fn(), codePut: vi.fn(), notebookPut: vi.fn() }));
vi.mock("../db", () => ({ chatDB: {} }));
vi.mock("../embedStore", () => ({ embedStore: { getEmbedKey: state.key } }));
vi.mock("../encryption/MetadataEncryptor", () => ({ decryptWithEmbedKey: state.decrypt }));
vi.mock("../db/codeRunOutputs", () => ({ upsertCodeRunOutput: state.codePut }));
vi.mock("../db/notebookRunOutputs", () => ({ upsertNotebookRunOutput: state.notebookPut }));

import { handleCodeRunOutputSyncedImpl } from "../handlersCodeRunOutputs";
import { handleNotebookRunOutputSyncedImpl } from "../handlersNotebookRunOutputs";

const cases = [
  { name: "Code", handler: handleCodeRunOutputSyncedImpl, put: state.codePut,
    plain: { output: "fixture output", saved_at: 1 }, event: "codeRunOutputSynced" },
  { name: "Notebook", handler: handleNotebookRunOutputSyncedImpl, put: state.notebookPut,
    plain: { cell_outputs: [{ cell_index: 0, outputs: [] }], saved_at: 1 }, event: "notebookRunOutputSynced" },
];
const payload = { id: "sidecar", embed_id: "embed", notebook_embed_id: "embed", chat_id: "source", encrypted_payload: "ciphertext" };
beforeEach(() => {
  state.key.mockReset().mockResolvedValue(new Uint8Array(32));
  state.decrypt.mockReset(); state.codePut.mockReset().mockResolvedValue(undefined);
  state.notebookPut.mockReset().mockResolvedValue(undefined);
});

for (const scenario of cases) describe(`${scenario.name} shared read guards`, () => {
  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
  it.each(["key", "decrypt"])("rejects an owner change during delayed %s before the local write", async stage => {
    let current = true, release!: (value: unknown) => void;
    state.decrypt.mockResolvedValue(JSON.stringify(scenario.plain));
    const delayed = new Promise(resolve => { release = resolve; });
    if (stage === "key") state.key.mockReturnValue(delayed);
    else state.decrypt.mockReturnValue(delayed);
    const dispatch = vi.spyOn(window, "dispatchEvent");
    const pending = scenario.handler(payload, () => { if (!current) throw new Error("Workspace changed"); });
    if (stage === "decrypt") await vi.waitFor(() => expect(state.decrypt).toHaveBeenCalled());
    current = false; release(stage === "key" ? new Uint8Array(32) : JSON.stringify(scenario.plain));
    await expect(pending).rejects.toThrow("Workspace changed");
    expect(scenario.put).not.toHaveBeenCalled(); expect(dispatch).not.toHaveBeenCalled();
    dispatch.mockRestore();
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
  it("suppresses plaintext dispatch when the owner changes during an already-issued local write", async () => {
    let current = true, release!: () => void;
    state.decrypt.mockResolvedValue(JSON.stringify(scenario.plain));
    scenario.put.mockReturnValue(new Promise<void>(resolve => { release = resolve; }));
    const dispatch = vi.spyOn(window, "dispatchEvent");
    const pending = scenario.handler(payload, () => { if (!current) throw new Error("Workspace changed"); });
    await vi.waitFor(() => expect(scenario.put).toHaveBeenCalledTimes(1));
    current = false; release();
    await expect(pending).rejects.toThrow("Workspace changed");
    expect(dispatch).not.toHaveBeenCalled(); dispatch.mockRestore();
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("preserves default handler behavior for existing callers", async () => {
    state.decrypt.mockResolvedValue(JSON.stringify(scenario.plain));
    const dispatch = vi.spyOn(window, "dispatchEvent");
    await scenario.handler(payload);
    expect(scenario.put).toHaveBeenCalledTimes(1);
    expect(dispatch).toHaveBeenCalledWith(expect.objectContaining({ type: scenario.event }));
    dispatch.mockRestore();
  });
});
