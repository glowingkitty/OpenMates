// Pins the flag-off TypeScript inbound decisions to the committed vectors that
// the shared Rust module (web_sync/inbound.rs) is proven against, so the two
// implementations cannot drift.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { clearDraftOnlyShellForMessages, draftApplyTs, updateFrameInvalidTs } from "../chatInboundDecisions";
import type { Chat } from "../../types/chat";

const VECTORS = resolve(__dirname, "../../../../../../packages/openmates-rust/src/web_sync/inbound_vectors.json");
const vectors = JSON.parse(readFileSync(VECTORS, "utf8"));

describe("inbound decision vectors", () => {
  // contract-test: supporting surface=gui.web assertions=sync.client.shared-rust-policy
  it("clears draft-only shells exactly as committed", async () => {
    for (const { chat, messagesV, clear } of vectors.draft) {
      const result = await clearDraftOnlyShellForMessages(chat as Chat, messagesV);
      expect(result !== chat).toBe(clear);
      if (clear) expect(result).toMatchObject({ encrypted_draft_md: null, encrypted_draft_preview: null, draft_v: 0 });
    }
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it("admits title and draft frames exactly as committed", () => {
    for (const { kind, payload, invalid } of vectors.frame) {
      expect(updateFrameInvalidTs(kind, payload)).toBe(invalid);
    }
  });

  // contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
  it("decides stale draft frames and cleared versions exactly as committed", () => {
    for (const { local, incomingDraftV, deletion, stale, clearedDraftV } of vectors.apply) {
      expect(draftApplyTs(local as Chat, incomingDraftV, deletion)).toEqual({ stale, clearedDraftV });
    }
  });
});
