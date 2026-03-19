// tests/mentions.test.ts
/**
 * Unit tests for CLI mention parsing and resolution.
 *
 * Run: node --test --experimental-strip-types tests/mentions.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  extractMentionTokens,
  parseMentions,
  listMentionOptions,
  CHAT_MODELS,
  MODEL_ALIASES,
  type MentionContext,
} from "../src/mentions.ts";

/** Minimal mention context for testing */
const testContext: MentionContext = {
  models: CHAT_MODELS,
  mates: {
    software_development: "Sophia",
    finance: "Finn",
    design: "Denise",
  },
  apps: [
    {
      id: "web",
      name: "Web",
      skills: [
        { id: "search", name: "Search" },
        { id: "read", name: "Read" },
      ],
      focus_modes: [{ id: "research", name: "Research" }],
      settings_and_memories: [],
    },
    {
      id: "code",
      name: "Code",
      skills: [{ id: "get_docs", name: "Get Docs" }],
      focus_modes: [],
      settings_and_memories: [
        { id: "projects", name: "Projects", type: "list" },
        { id: "preferred_tech", name: "Preferred Tech", type: "list" },
      ],
    },
    {
      id: "ai",
      name: "AI",
      skills: [{ id: "ask", name: "Ask" }],
      focus_modes: [{ id: "deep_think", name: "Deep Think" }],
      settings_and_memories: [],
    },
  ],
  memoryEntries: [
    {
      id: "entry-abc123",
      app_id: "code",
      item_type: "projects",
      title: "MyApp",
    },
  ],
};

describe("extractMentionTokens", () => {
  it("extracts simple @tokens", () => {
    const tokens = extractMentionTokens("Hello @Sophia how are you?");
    assert.deepEqual(tokens, ["Sophia"]);
  });

  it("extracts hyphenated @tokens", () => {
    const tokens = extractMentionTokens("Use @Web-Search for this");
    assert.deepEqual(tokens, ["Web-Search"]);
  });

  it("extracts multiple @tokens", () => {
    const tokens = extractMentionTokens(
      "@best tell me about @Code-Projects",
    );
    assert.deepEqual(tokens, ["best", "Code-Projects"]);
  });

  it("extracts file paths", () => {
    const tokens = extractMentionTokens(
      "Check @/home/user/.env and @./config.ts",
    );
    assert.deepEqual(tokens, ["/home/user/.env", "./config.ts"]);
  });

  it("extracts model names with dots", () => {
    const tokens = extractMentionTokens("Use @Claude-Opus-4.6 for this");
    assert.deepEqual(tokens, ["Claude-Opus-4.6"]);
  });

  it("returns empty for no mentions", () => {
    const tokens = extractMentionTokens("No mentions here");
    assert.deepEqual(tokens, []);
  });

  it("handles @token at start of message", () => {
    const tokens = extractMentionTokens("@Sophia help me");
    assert.deepEqual(tokens, ["Sophia"]);
  });
});

describe("parseMentions", () => {
  describe("model aliases", () => {
    it("resolves @best to wire syntax", () => {
      const result = parseMentions("@best what is TypeScript?", testContext);
      assert.equal(result.unresolved.length, 0);
      assert.equal(result.resolved.length, 1);
      assert.equal(result.resolved[0].type, "model_alias");
      assert.equal(result.resolved[0].wireSyntax, "@best-model:best");
      assert.ok(result.processedMessage.includes("@best-model:best"));
    });

    it("resolves @fast to wire syntax", () => {
      const result = parseMentions("@fast summarize this", testContext);
      assert.equal(result.resolved[0].wireSyntax, "@best-model:fast");
    });
  });

  describe("models", () => {
    it("resolves model name to wire syntax", () => {
      const result = parseMentions(
        "@Claude-Opus-4.6 explain this code",
        testContext,
      );
      assert.equal(result.resolved.length, 1);
      assert.equal(result.resolved[0].type, "model");
      assert.equal(result.resolved[0].wireSyntax, "@ai-model:claude-opus-4-6");
    });

    it("resolves model id directly", () => {
      const result = parseMentions(
        "@gpt-5.4 what's the weather?",
        testContext,
      );
      assert.equal(result.resolved.length, 1);
      assert.equal(result.resolved[0].wireSyntax, "@ai-model:gpt-5.4");
    });
  });

  describe("mates", () => {
    it("resolves mate name to wire syntax", () => {
      const result = parseMentions("@Sophia help with code", testContext);
      assert.equal(result.resolved.length, 1);
      assert.equal(result.resolved[0].type, "mate");
      assert.equal(
        result.resolved[0].wireSyntax,
        "@mate:software_development",
      );
    });

    it("resolves mate name case-insensitively", () => {
      const result = parseMentions("@sophia help", testContext);
      assert.equal(result.resolved.length, 1);
      assert.equal(result.resolved[0].type, "mate");
    });
  });

  describe("skills", () => {
    it("resolves App-Skill format", () => {
      const result = parseMentions(
        "@Web-Search find AI papers",
        testContext,
      );
      assert.equal(result.resolved.length, 1);
      assert.equal(result.resolved[0].type, "skill");
      assert.equal(result.resolved[0].wireSyntax, "@skill:web:search");
    });

    it("resolves Code-Get-Docs", () => {
      const result = parseMentions("@Code-Get-Docs react hooks", testContext);
      assert.equal(result.resolved.length, 1);
      assert.equal(result.resolved[0].wireSyntax, "@skill:code:get_docs");
    });
  });

  describe("focus modes", () => {
    it("resolves focus mode format", () => {
      const result = parseMentions("@Web-Research AI trends", testContext);
      assert.equal(result.resolved.length, 1);
      assert.equal(result.resolved[0].type, "focus_mode");
      assert.equal(result.resolved[0].wireSyntax, "@focus:web:research");
    });
  });

  describe("memory categories", () => {
    it("resolves memory category", () => {
      const result = parseMentions(
        "@Code-Projects review architecture",
        testContext,
      );
      assert.equal(result.resolved.length, 1);
      assert.equal(result.resolved[0].type, "settings_memory");
      assert.equal(
        result.resolved[0].wireSyntax,
        "@memory:code:projects:list",
      );
    });
  });

  describe("file paths", () => {
    it("identifies file paths separately", () => {
      const result = parseMentions(
        "Check @/home/user/.env please",
        testContext,
      );
      assert.equal(result.filePaths.length, 1);
      assert.equal(result.filePaths[0], "/home/user/.env");
      assert.equal(result.resolved.length, 0);
    });

    it("identifies relative file paths", () => {
      const result = parseMentions("Read @./config.ts", testContext);
      assert.equal(result.filePaths.length, 1);
      assert.equal(result.filePaths[0], "./config.ts");
    });
  });

  describe("unresolved mentions", () => {
    it("reports unknown mentions with suggestions", () => {
      const result = parseMentions("@Soph help me", testContext);
      assert.equal(result.unresolved.length, 1);
      assert.equal(result.unresolved[0].original, "@Soph");
      assert.ok(result.unresolved[0].suggestions.length > 0);
      // "Sophia" should be in suggestions since "Soph" is a prefix
      assert.ok(
        result.unresolved[0].suggestions.some((s) =>
          s.toLowerCase().includes("sophia"),
        ),
      );
    });
  });

  describe("multiple mentions", () => {
    it("resolves multiple different mention types", () => {
      const result = parseMentions(
        "@Sophia use @Web-Search to find info",
        testContext,
      );
      assert.equal(result.resolved.length, 2);
      assert.ok(
        result.processedMessage.includes("@mate:software_development"),
      );
      assert.ok(result.processedMessage.includes("@skill:web:search"));
    });
  });

  describe("no mentions", () => {
    it("returns message unchanged when no @ tokens", () => {
      const result = parseMentions("Just a normal message", testContext);
      assert.equal(result.processedMessage, "Just a normal message");
      assert.equal(result.resolved.length, 0);
      assert.equal(result.unresolved.length, 0);
    });
  });
});

describe("listMentionOptions", () => {
  it("lists all mention types", () => {
    const options = listMentionOptions(testContext);
    assert.ok(options.length > 0);

    const types = new Set(options.map((o) => o.type));
    assert.ok(types.has("model_alias"));
    assert.ok(types.has("model"));
    assert.ok(types.has("mate"));
    assert.ok(types.has("skill"));
    assert.ok(types.has("focus_mode"));
    assert.ok(types.has("settings_memory"));
  });

  it("filters by type", () => {
    const mates = listMentionOptions(testContext, "mate");
    assert.ok(mates.every((m) => m.type === "mate"));
    assert.equal(mates.length, 3); // Sophia, Finn, Denise
  });

  it("excludes ai.ask skill", () => {
    const skills = listMentionOptions(testContext, "skill");
    assert.ok(!skills.some((s) => s.displayName.includes("AI-Ask")));
  });

  it("includes model aliases", () => {
    const aliases = listMentionOptions(testContext, "model_alias");
    assert.equal(aliases.length, Object.keys(MODEL_ALIASES).length);
    assert.ok(aliases.some((a) => a.displayName === "@Best"));
    assert.ok(aliases.some((a) => a.displayName === "@Fast"));
  });
});
