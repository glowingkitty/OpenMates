// tests/mentions.test.ts
// contract-test-file: infrastructure
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
  resolveWikipediaMentions,
  WikipediaMentionResolutionError,
  type MentionContext,
} from "../src/mentions.ts";

function docAssert(claimId: string, assertion: () => void): void {
  try {
    assertion();
  } catch (error) {
    if (error instanceof Error) {
      error.message = `[doc-assert:${claimId}] ${error.message}`;
    }
    throw error;
  }
}

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
      focus_modes: [
        { id: "research", name: "Research" },
        { id: "deep_web_research", name: "Deep Research" },
      ],
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

describe("resolveWikipediaMentions", () => {
  const result = (overrides: Partial<{
    page_id: number;
    key: string;
    title: string;
    description: string;
    disambiguation: boolean;
    language: string;
  }> = {}) => ({
    page_id: 736,
    key: "Albert_Einstein",
    title: "Albert Einstein",
    description: "Theoretical physicist",
    disambiguation: false,
    language: "en",
    ...overrides,
  });

  // contract-test: direct surface=cli assertions=wikipedia-mentions.syntax.explicit-trigger,wikipedia-mentions.resolution.first-result
  it("resolves explicit Wiki shorthand to canonical backend syntax", async () => {
    const calls: Array<[string, string, number]> = [];
    const parsed = await resolveWikipediaMentions("@wiki:AlbertEinstein explain", "de-DE", async (...args) => {
      calls.push(args);
      return [result({ language: "de" })];
    });
    assert.deepEqual(calls, [["AlbertEinstein", "de", 5]]);
    assert.equal(parsed.processedMessage, "@wikipedia:de:Albert_Einstein explain");
    assert.equal(parsed.resolved[0].type, "wikipedia");
  });

  // contract-test: direct surface=cli assertions=wikipedia-mentions.syntax.explicit-trigger
  it("honors an explicit language and never searches generic mentions", async () => {
    let calls = 0;
    const parsed = await resolveWikipediaMentions("@Sophia @wiki:en:AlbertEinstein", "de", async (query, language) => {
      calls += 1;
      assert.equal(query, "AlbertEinstein");
      assert.equal(language, "en");
      return [result()];
    });
    assert.equal(calls, 1);
    assert.equal(parsed.processedMessage, "@Sophia @wikipedia:en:Albert_Einstein");
  });

  // contract-test: direct surface=cli assertions=wikipedia-mentions.resolution.disambiguation-visible
  it("blocks disambiguation and returns specific alternatives", async () => {
    await assert.rejects(
      resolveWikipediaMentions("@wiki:Mercury explain", "en", async () => [
        result({ key: "Mercury", title: "Mercury", disambiguation: true }),
        result({ key: "Mercury_(planet)", title: "Mercury (planet)" }),
        result({ key: "Mercury_(element)", title: "Mercury (element)" }),
      ]),
      (error: unknown) => error instanceof WikipediaMentionResolutionError
        && error.code === "disambiguation"
        && error.alternatives.includes("@wiki:en:Mercury_(planet)"),
    );
  });

  // contract-test: direct surface=cli assertions=wikipedia-mentions.references.maximum-three
  it("rejects a fourth Wikipedia reference before searching", async () => {
    let calls = 0;
    await assert.rejects(
      resolveWikipediaMentions("@wiki:One @wiki:Two @wiki:Three @wiki:Four", "en", async () => {
        calls += 1;
        return [result()];
      }),
      (error: unknown) => error instanceof WikipediaMentionResolutionError
        && error.code === "too_many_references",
    );
    assert.equal(calls, 0);
  });

  // contract-test: direct surface=cli assertions=wikipedia-mentions.resolution.first-result,wikipedia-mentions.surfaces.semantic-parity
  it("preserves authored order and percent-encodes canonical titles", async () => {
    const parsed = await resolveWikipediaMentions("@wiki:One compare @wiki:Two", "en", async (query) => [
      result({ key: query === "One" ? "C++" : "São_Paulo", title: query }),
    ]);
    assert.equal(parsed.processedMessage, "@wikipedia:en:C%2B%2B compare @wikipedia:en:S%C3%A3o_Paulo");
  });

  it("keeps balanced article parentheses while preserving sentence punctuation", async () => {
    const parsed = await resolveWikipediaMentions("Read @wiki:en:Mercury_(planet).", "en", async (query, language) => {
      assert.equal(query, "Mercury_(planet)");
      assert.equal(language, "en");
      return [result({ key: "Mercury_(planet)", title: "Mercury (planet)" })];
    });

    assert.equal(parsed.processedMessage, "Read @wikipedia:en:Mercury_(planet).");
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

  describe("task references", () => {
    it("passes @TASK short IDs through for backend task context resolution", () => {
      const result = parseMentions(
        "Use @TASK-1234, as context for this chat",
        testContext,
      );

      assert.equal(result.unresolved.length, 0);
      assert.equal(result.resolved.length, 0);
      assert.equal(result.processedMessage, "Use @TASK-1234, as context for this chat");
    });
  });

  describe("models", () => {
    it("resolves model name to wire syntax", () => {
      const result = parseMentions(
        "@Claude-Opus-5 explain this code",
        testContext,
      );
      assert.equal(result.resolved.length, 1);
      assert.equal(result.resolved[0].type, "model");
      assert.equal(result.resolved[0].wireSyntax, "@ai-model:claude-opus-5");
    });

    it("resolves model id directly", () => {
      const result = parseMentions(
        "@gpt-5.4 what's the weather?",
        testContext,
      );
      assert.equal(result.resolved.length, 1);
      assert.equal(result.resolved[0].wireSyntax, "@ai-model:gpt-5.4");
    });

    it("resolves GPT-5.6 display names", () => {
      for (const [mention, modelId] of [
        ["@GPT-6-Astra", "gpt-6-astra"],
        ["@GPT-5.6-Luna", "gpt-5.6-luna"],
        ["@GPT-5.6-Terra", "gpt-5.6-terra"],
        ["@GPT-5.6-Sol", "gpt-5.6-sol"],
        ["@GPT-5.6-Sol-Max", "gpt-5.6-sol-max"],
      ] as const) {
        const result = parseMentions(`${mention} explain this`, testContext);

        assert.equal(result.unresolved.length, 0);
        assert.equal(result.resolved.length, 1);
        assert.equal(result.resolved[0].type, "model");
        assert.equal(result.resolved[0].wireSyntax, `@ai-model:${modelId}`);
      }
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

    it("accepts backend focus wire syntax unchanged", () => {
      const result = parseMentions(
        "@focus:web:deep_web_research investigate egg prices",
        testContext,
      );
      assert.equal(result.unresolved.length, 0);
      assert.equal(result.resolved.length, 1);
      assert.equal(result.resolved[0].type, "focus_mode");
      assert.equal(result.resolved[0].wireSyntax, "@focus:web:deep_web_research");
      assert.ok(result.processedMessage.startsWith("@focus:web:deep_web_research"));
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
    docAssert("cli-mentions-list-includes-skills-focus-and-memories", () => {
      assert.ok(types.has("model_alias"));
      assert.ok(types.has("model"));
      assert.ok(types.has("mate"));
      assert.ok(types.has("skill"));
      assert.ok(types.has("focus_mode"));
      assert.ok(types.has("settings_memory"));
    });
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
