// Unit tests for embed resolver decoding behavior.
// Code embeds can contain arbitrary multiline source text.
// These tests cover the defensive recovery path used when the TOON decoder
// misinterprets multiline code as a malformed key instead of a `code` field.
// The test keeps the fixture close to the failing dev issue payload shape.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { authStore } from "../../stores/authState";
import {
  recoverCodeEmbedFromToon,
  requestEmbedFromServerOnce,
} from "../embedResolver";

const mockSendMessage = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));

vi.mock("../websocketService", () => ({
  webSocketService: {
    sendMessage: mockSendMessage,
  },
}));

beforeEach(() => {
  mockSendMessage.mockClear();
  authStore.set({ isAuthenticated: true, isInitialized: true });
});

describe("recoverCodeEmbedFromToon", () => {
  it("recovers multiline code and lineCount from malformed decoded TOON", () => {
    const toonContent = `type: code
language: python
code: "# Sample list
numbers = [5, 2, 9]
print(f"sorted list: {sorted(numbers)}")"
filename: sorting_basics.py
status: finished
line_count: 3`;
    const malformedDecoded = {
      type: "code",
      language: "python",
      'code: "# Sample list\nnumbers =': "",
      filename: "sorting_basics.py",
      status: "finished",
    };

    const recovered = recoverCodeEmbedFromToon(
      toonContent,
      malformedDecoded,
    ) as Record<string, unknown>;

    expect(recovered.code).toContain("numbers = [5, 2, 9]");
    expect(recovered.code).toContain("sorted list");
    expect(recovered.filename).toBe("sorting_basics.py");
    expect(recovered.lineCount).toBe(3);
  });
});

describe("requestEmbedFromServerOnce", () => {
  it("suppresses repeated requests for the same embed during cooldown", async () => {
    const embedId = "11111111-1111-4111-8111-111111111111";

    const firstRequest = await requestEmbedFromServerOnce(embedId, "test-first");
    const secondRequest = await requestEmbedFromServerOnce(embedId, "test-second");

    expect(firstRequest).toBe(true);
    expect(secondRequest).toBe(false);
    expect(mockSendMessage).toHaveBeenCalledTimes(1);
    expect(mockSendMessage).toHaveBeenCalledWith("request_embed", {
      embed_id: embedId,
    });
  });

  it("does not request synthetic embed IDs from the server", async () => {
    const requested = await requestEmbedFromServerOnce(
      "youtube-XK4yjmApcHo",
      "test-synthetic",
    );

    expect(requested).toBe(false);
    expect(mockSendMessage).not.toHaveBeenCalled();
  });
});
