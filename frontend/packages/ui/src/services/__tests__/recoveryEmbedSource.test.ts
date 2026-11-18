import { describe, expect, it } from "vitest";
import { encode } from "@toon-format/toon";
import {
  catalogContextFromSealedEmbed, historySourceFromSealedEmbed, isUnwrittenInitialDiffRead,
} from "../recoveryEmbedSource";

describe("historical sealed embed source", () => {
  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery
  it("preserves the normal embed catalog projection from authenticated sealed data", async () => {
    const code = encode({ type: "code", app_id: "code", skill_id: "code", code: "const x = 1;" });
    expect(await catalogContextFromSealedEmbed(code, undefined, undefined)).toEqual({
      app_id: "code", skill_id: "code",
    });
    expect(await catalogContextFromSealedEmbed(code, "web", "search")).toEqual({
      app_id: "web", skill_id: "search",
    });
    await expect(catalogContextFromSealedEmbed(code, "code", undefined)).resolves.toEqual({
      app_id: "code", skill_id: "code",
    });
    await expect(catalogContextFromSealedEmbed("{}", "code", undefined))
      .rejects.toThrow(/catalog identity/);
    expect(await catalogContextFromSealedEmbed("{}", undefined, undefined)).toBeNull();
    const focusMode = encode({ type: "focus_mode_activation", app_id: "events", status: "activated" });
    expect(await catalogContextFromSealedEmbed(focusMode, undefined, undefined)).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery
  it("recovers embeds of hyphenated skills like the server's store_embed catalog check", async () => {
    const started = encode({ type: "app_skill_use", app_id: "openmates", skill_id: "start-chat" });
    expect(await catalogContextFromSealedEmbed(started, undefined, undefined)).toEqual({
      app_id: "openmates", skill_id: "start-chat",
    });
    expect(await catalogContextFromSealedEmbed("{}", "openmates", "report-to-creator")).toEqual({
      app_id: "openmates", skill_id: "report-to-creator",
    });
    await expect(catalogContextFromSealedEmbed("{}", "open-mates", "start-chat"))
      .rejects.toThrow(/catalog identity/);
    await expect(catalogContextFromSealedEmbed("{}", "openmates", "-start"))
      .rejects.toThrow(/catalog identity/);
  });

  // contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery
  it("creates only an unwritten v1 snapshot after the bounded read's exact missing-snapshot conflict", () => {
    expect(isUnwrittenInitialDiffRead(409, "snapshot_required", 1)).toBe(true);
    expect(isUnwrittenInitialDiffRead(409, "snapshot_required", 2)).toBe(false);
    expect(isUnwrittenInitialDiffRead(409, "Version chain is incomplete", 1)).toBe(false);
    expect(isUnwrittenInitialDiffRead(409, "Version chain has no starting snapshot", 1)).toBe(false);
    expect(isUnwrittenInitialDiffRead(404, "snapshot_required", 1)).toBe(false);
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery
  it("compares immutable version rows with code, mail, and document source inside sealed TOON", async () => {
    expect(await historySourceFromSealedEmbed(encode({ type: "code", code: "const value = 7;" }), "code"))
      .toBe("const value = 7;");
    expect(await historySourceFromSealedEmbed(encode({ type: "deck", slides_markup: "# One" }), "deck"))
      .toBe("# One");
    expect(await historySourceFromSealedEmbed(encode({
      type: "mail", receiver: "a@example.test", subject: "Hello", content: "Body", footer: "Bye",
    }), "mail")).toBe("to: a@example.test\nsubject: Hello\ncontent:\nBody\nfooter:\nBye");
    const model = { title: "Draft", blocks: [{ type: "paragraph", text: "Hello" }] };
    expect(await historySourceFromSealedEmbed(encode({ type: "document", html: "", docx_model: model }), "document"))
      .toBe(JSON.stringify(model, null, 2));
    await expect(historySourceFromSealedEmbed(encode({ type: "unknown", content: "x" }), "unknown"))
      .rejects.toThrow(/Historical recovery/);
  });
});
