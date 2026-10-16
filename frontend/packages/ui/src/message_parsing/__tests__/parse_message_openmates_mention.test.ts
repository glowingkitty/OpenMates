import { describe, expect, it, vi } from "vitest";

vi.mock("../../services/chatSyncService", () => ({ chatSyncService: {} }));
import { parse_message } from "../parse_message";

function inlineNodes(markdown: string): any[] {
  const document = parse_message(markdown, "read", {
    unifiedParsingEnabled: true,
    role: "user",
  });
  return document.content[0].content;
}

describe("public OpenMates mention", () => {
  // contract-test: direct surface=gui.web assertions=teams.chat.sender-identity-layout
  it("renders the public handle as a Mate gradient node without changing surrounding text", () => {
    const nodes = inlineNodes("Ask @openmates, then @OpenMates.");
    expect(nodes.map((node) => node.type)).toEqual(["text", "mate", "text", "mate", "text"]);
    expect(nodes.filter((node) => node.type === "mate").map((node) => node.attrs.name)).toEqual(["openmates", "openmates"]);
    expect(nodes[1].attrs).toMatchObject({
      displayName: "openmates",
      colorStart: "var(--color-primary-start)",
      colorEnd: "var(--color-primary-end)",
    });
  });

  // contract-test: supporting surface=gui.web assertions=teams.chat.sender-identity-layout
  it("keeps domains, code and links as text", () => {
    expect(inlineNodes("help@openmates.org").some((node) => node.type === "mate")).toBe(false);
    expect(inlineNodes("@openmates.org").some((node) => node.type === "mate")).toBe(false);
    expect(inlineNodes("`@openmates`").some((node) => node.type === "mate")).toBe(false);
    expect(inlineNodes("[@openmates](https://example.org)").some((node) => node.type === "mate")).toBe(false);
  });
});
