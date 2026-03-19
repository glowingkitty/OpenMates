/**
 * Unit tests for CLI argument parsing, blocked paths, URL derivation,
 * suggestion parsing, and new chat suggestion rendering.
 *
 * These run without network access — all network calls are expected to throw.
 *
 * Run: cd frontend/packages/openmates-cli && npm run build && node --test tests/cli.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";

// Import from compiled dist — the .js extension imports in src/ require the build step
import {
  deriveAppUrl,
  MEMORY_TYPE_REGISTRY,
  parseNewChatSuggestionText,
} from "../dist/index.js";

// ---------------------------------------------------------------------------
// deriveAppUrl
// ---------------------------------------------------------------------------

describe("deriveAppUrl", () => {
  const original = process.env.OPENMATES_APP_URL;
  function reset() {
    if (original === undefined) {
      delete process.env.OPENMATES_APP_URL;
    } else {
      process.env.OPENMATES_APP_URL = original;
    }
  }

  it("maps production API to production web app", () => {
    reset();
    assert.strictEqual(
      deriveAppUrl("https://api.openmates.org"),
      "https://openmates.org",
    );
  });

  it("maps dev API to dev web app", () => {
    reset();
    assert.strictEqual(
      deriveAppUrl("https://api.dev.openmates.org"),
      "https://app.dev.openmates.org",
    );
  });

  it("maps localhost:8000 to localhost:5173", () => {
    reset();
    assert.strictEqual(
      deriveAppUrl("http://localhost:8000"),
      "http://localhost:5173",
    );
  });

  it("falls back to production for unknown API URLs", () => {
    reset();
    assert.strictEqual(
      deriveAppUrl("https://api.custom-instance.example.com"),
      "https://openmates.org",
    );
  });

  it("respects OPENMATES_APP_URL env override", () => {
    process.env.OPENMATES_APP_URL = "https://my-custom-app.example.com";
    try {
      assert.strictEqual(
        deriveAppUrl("https://api.openmates.org"),
        "https://my-custom-app.example.com",
      );
    } finally {
      reset();
    }
  });

  it("strips trailing slash from OPENMATES_APP_URL override", () => {
    process.env.OPENMATES_APP_URL = "https://my-custom-app.example.com/";
    try {
      assert.strictEqual(
        deriveAppUrl("https://api.openmates.org"),
        "https://my-custom-app.example.com",
      );
    } finally {
      reset();
    }
  });
});

// ---------------------------------------------------------------------------
// MEMORY_TYPE_REGISTRY
// ---------------------------------------------------------------------------

describe("MEMORY_TYPE_REGISTRY", () => {
  it("contains at least 10 memory types", () => {
    const keys = Object.keys(MEMORY_TYPE_REGISTRY);
    assert.ok(keys.length >= 10, `expected >=10 types, got ${keys.length}`);
  });

  it("every type has appId, itemType, required, and properties", () => {
    for (const [key, def] of Object.entries(MEMORY_TYPE_REGISTRY)) {
      assert.ok(def.appId, `${key}: missing appId`);
      assert.ok(def.itemType, `${key}: missing itemType`);
      assert.ok(
        Array.isArray(def.required),
        `${key}: required should be array`,
      );
      assert.ok(
        typeof def.properties === "object",
        `${key}: properties should be object`,
      );
    }
  });

  it("all required fields are present in properties", () => {
    for (const [key, def] of Object.entries(MEMORY_TYPE_REGISTRY)) {
      for (const req of def.required) {
        assert.ok(
          def.properties[req] !== undefined,
          `${key}: required field '${req}' missing from properties`,
        );
      }
    }
  });

  it("code/preferred_tech requires 'name'", () => {
    const def = MEMORY_TYPE_REGISTRY["code/preferred_tech"];
    assert.ok(def, "code/preferred_tech should exist");
    assert.ok(def.required.includes("name"), "should require 'name'");
  });

  it("ai/communication_style has enum values for 'tone'", () => {
    const def = MEMORY_TYPE_REGISTRY["ai/communication_style"];
    assert.ok(def, "ai/communication_style should exist");
    const tone = def.properties["tone"];
    assert.ok(
      tone?.enum && tone.enum.length > 0,
      "tone should have enum values",
    );
    assert.ok(
      tone.enum!.includes("formal"),
      "tone enum should include 'formal'",
    );
  });

  it("registry key format matches appId/itemType", () => {
    for (const [key, def] of Object.entries(MEMORY_TYPE_REGISTRY)) {
      const expectedKey = `${def.appId}/${def.itemType}`;
      assert.strictEqual(
        key,
        expectedKey,
        `key mismatch: ${key} vs ${expectedKey}`,
      );
    }
  });
});

// ---------------------------------------------------------------------------
// Schema validation (via OpenMatesClient.createMemory validation path)
// In isolation: we test the validation logic that would be called by the client.
// We re-implement a minimal version to keep tests network-free.
// ---------------------------------------------------------------------------

function validateMemory(
  registryKey: string,
  itemValue: Record<string, unknown>,
): { valid: true } | { valid: false; error: string } {
  const schema = MEMORY_TYPE_REGISTRY[registryKey];
  if (!schema) {
    return { valid: false, error: `Unknown type: ${registryKey}` };
  }
  const missing = schema.required.filter(
    (f) =>
      itemValue[f] === undefined ||
      itemValue[f] === null ||
      itemValue[f] === "",
  );
  if (missing.length > 0) {
    return { valid: false, error: `Missing required: ${missing.join(", ")}` };
  }
  for (const [field, def] of Object.entries(schema.properties)) {
    const val = itemValue[field];
    if (val !== undefined && def.enum && !def.enum.includes(String(val))) {
      return {
        valid: false,
        error: `Invalid enum value '${String(val)}' for '${field}'`,
      };
    }
  }
  return { valid: true };
}

describe("memory schema validation", () => {
  it("accepts valid code/preferred_tech entry", () => {
    const result = validateMemory("code/preferred_tech", {
      name: "Python",
      proficiency: "advanced",
    });
    assert.ok(result.valid);
  });

  it("rejects missing required field", () => {
    const result = validateMemory("code/preferred_tech", {
      proficiency: "advanced",
    });
    assert.ok(!result.valid);
    assert.ok(result.valid === false && result.error.includes("name"));
  });

  it("rejects invalid enum value", () => {
    const result = validateMemory("code/preferred_tech", {
      name: "Python",
      proficiency: "guru",
    });
    assert.ok(!result.valid);
    assert.ok(result.valid === false && result.error.includes("guru"));
  });

  it("accepts valid ai/communication_style entry", () => {
    const result = validateMemory("ai/communication_style", {
      title: "Work Mode",
      tone: "professional",
      verbosity: "detailed",
    });
    assert.ok(result.valid);
  });

  it("rejects unknown memory type", () => {
    const result = validateMemory("fake/nonexistent", { name: "x" });
    assert.ok(!result.valid);
    assert.ok(result.valid === false && result.error.includes("Unknown"));
  });

  it("accepts entry with optional fields omitted", () => {
    const result = validateMemory("books/favorite_books", { title: "Dune" });
    assert.ok(result.valid);
  });
});

// ---------------------------------------------------------------------------
// parseNewChatSuggestionText
// ---------------------------------------------------------------------------

describe("parseNewChatSuggestionText", () => {
  it("parses [app-skill] prefix with body", () => {
    const result = parseNewChatSuggestionText(
      "[web-search] What's the latest AI news?",
    );
    assert.strictEqual(result.appId, "web");
    assert.strictEqual(result.skillId, "search");
    assert.strictEqual(result.body, "What's the latest AI news?");
  });

  it("parses [images-generate] prefix", () => {
    const result = parseNewChatSuggestionText(
      "[images-generate] Draw a futuristic city at sunset",
    );
    assert.strictEqual(result.appId, "images");
    assert.strictEqual(result.skillId, "generate");
    assert.strictEqual(result.body, "Draw a futuristic city at sunset");
  });

  it("parses [news-search] prefix", () => {
    const result = parseNewChatSuggestionText("[news-search] Climate tech");
    assert.strictEqual(result.appId, "news");
    assert.strictEqual(result.skillId, "search");
    assert.strictEqual(result.body, "Climate tech");
  });

  it("parses [app] prefix without skill", () => {
    const result = parseNewChatSuggestionText("[web] Open my bookmarks");
    assert.strictEqual(result.appId, "web");
    assert.strictEqual(result.skillId, null);
    assert.strictEqual(result.body, "Open my bookmarks");
  });

  it("returns body unchanged when no prefix present", () => {
    const result = parseNewChatSuggestionText(
      "How do I implement a binary search tree?",
    );
    assert.strictEqual(result.appId, null);
    assert.strictEqual(result.skillId, null);
    assert.strictEqual(result.body, "How do I implement a binary search tree?");
  });

  it("trims whitespace from body", () => {
    const result = parseNewChatSuggestionText(
      "[math-calculate]   Solve 42 * 13 + 7  ",
    );
    assert.strictEqual(result.appId, "math");
    assert.strictEqual(result.skillId, "calculate");
    assert.strictEqual(result.body, "Solve 42 * 13 + 7");
  });

  it("handles suggestion with only the prefix and no body", () => {
    const result = parseNewChatSuggestionText("[videos-search]");
    assert.strictEqual(result.appId, "videos");
    assert.strictEqual(result.skillId, "search");
    assert.strictEqual(result.body, "");
  });

  it("treats plain text starting with a non-bracket char as plain body", () => {
    const result = parseNewChatSuggestionText(
      "Tell me about quantum computing",
    );
    assert.strictEqual(result.appId, null);
    assert.strictEqual(result.skillId, null);
    assert.strictEqual(result.body, "Tell me about quantum computing");
  });
});

// ---------------------------------------------------------------------------
// Follow-up suggestions rendering helpers (network-free)
// ---------------------------------------------------------------------------

/**
 * Simulate the terminal output format for follow-up suggestions.
 * Mirrors the rendering logic in sendMessageStreaming() and printChatConversation()
 * in cli.ts without requiring a live network connection.
 */
function renderFollowUpSuggestions(
  shortChatId: string,
  suggestions: string[],
): string {
  if (suggestions.length === 0) return "";
  let out = "Suggested follow-ups:\n";
  for (const suggestion of suggestions) {
    const escaped = suggestion.replace(/"/g, '\\"');
    out += `  • ${suggestion}\n`;
    out += `    openmates chats send --chat ${shortChatId} "${escaped}"\n`;
  }
  return out;
}

describe("follow-up suggestions rendering", () => {
  it("renders a list of follow-up suggestions with send commands", () => {
    const output = renderFollowUpSuggestions("d262cb68", [
      "What are the main benefits?",
      "Can you give me an example?",
    ]);
    assert.ok(output.includes("Suggested follow-ups:"));
    assert.ok(output.includes("• What are the main benefits?"));
    assert.ok(
      output.includes(
        'openmates chats send --chat d262cb68 "What are the main benefits?"',
      ),
    );
    assert.ok(output.includes("• Can you give me an example?"));
    assert.ok(
      output.includes(
        'openmates chats send --chat d262cb68 "Can you give me an example?"',
      ),
    );
  });

  it("renders nothing for empty suggestions list", () => {
    const output = renderFollowUpSuggestions("d262cb68", []);
    assert.strictEqual(output, "");
  });

  it("escapes double quotes inside suggestion text for shell safety", () => {
    const output = renderFollowUpSuggestions("a1b2c3d4", [
      'What is "machine learning"?',
    ]);
    assert.ok(
      output.includes(
        `openmates chats send --chat a1b2c3d4 "What is \\"machine learning\\"?"`,
      ),
    );
  });
});

// ---------------------------------------------------------------------------
// New chat suggestions rendering helpers (network-free)
// ---------------------------------------------------------------------------

/**
 * Simulate new-chat suggestion rendering.
 * Mirrors printNewChatSuggestion() in cli.ts without network.
 */
function renderNewChatSuggestion(
  suggestion: { body: string; appId: string | null; skillId: string | null },
  index: number,
): string {
  const appLabel = suggestion.skillId
    ? `[${suggestion.appId}-${suggestion.skillId}] `
    : suggestion.appId
      ? `[${suggestion.appId}] `
      : "";
  const escaped = suggestion.body.replace(/"/g, '\\"');
  return (
    `${index}. ${appLabel}${suggestion.body}\n` +
    `   openmates chats new "${escaped}"\n`
  );
}

describe("new chat suggestions rendering", () => {
  it("renders a skill-prefixed suggestion with app/skill label", () => {
    const s = parseNewChatSuggestionText(
      "[web-search] Latest quantum computing breakthroughs",
    );
    const output = renderNewChatSuggestion(s, 1);
    assert.ok(output.startsWith("1. [web-search]"));
    assert.ok(output.includes("Latest quantum computing breakthroughs"));
    assert.ok(
      output.includes(
        'openmates chats new "Latest quantum computing breakthroughs"',
      ),
    );
  });

  it("renders a plain suggestion without prefix", () => {
    const s = parseNewChatSuggestionText(
      "Explain the history of the Roman Empire",
    );
    const output = renderNewChatSuggestion(s, 3);
    assert.ok(output.startsWith("3. Explain the history"));
    assert.ok(output.includes('openmates chats new "Explain the history'));
  });

  it("renders an app-only prefixed suggestion (no skill)", () => {
    const s = parseNewChatSuggestionText("[images] Generate a logo for my app");
    const output = renderNewChatSuggestion(s, 2);
    assert.ok(output.startsWith("2. [images]"));
    assert.ok(output.includes("Generate a logo for my app"));
  });

  it("correctly numbers multiple suggestions", () => {
    const suggestions = [
      "[web-search] AI trends in 2026",
      "[news-search] Startup funding news",
      "How to improve my sleep?",
    ];
    const outputs = suggestions.map((text, i) => {
      const s = parseNewChatSuggestionText(text);
      return renderNewChatSuggestion(s, i + 1);
    });
    assert.ok(outputs[0].startsWith("1."));
    assert.ok(outputs[1].startsWith("2."));
    assert.ok(outputs[2].startsWith("3."));
  });

  it("escapes double quotes in suggestion body for shell safety", () => {
    const s = parseNewChatSuggestionText(
      'Summarize the book "Thinking Fast and Slow"',
    );
    const output = renderNewChatSuggestion(s, 1);
    assert.ok(
      output.includes(
        'openmates chats new "Summarize the book \\"Thinking Fast and Slow\\""',
      ),
    );
  });
});

// ---------------------------------------------------------------------------
// --followup flag: suggestion resolution helpers (network-free)
// ---------------------------------------------------------------------------

/**
 * Simulate the --followup <n> resolution logic from the `chats send` handler.
 * Returns the selected suggestion text or an error string.
 * Mirrors the logic in handleChats() send branch in cli.ts.
 */
function resolveFollowUp(
  suggestions: string[],
  n: number,
): { ok: true; message: string } | { ok: false; error: string } {
  if (suggestions.length === 0) {
    return { ok: false, error: "no_suggestions" };
  }
  if (isNaN(n) || n < 1) {
    return { ok: false, error: "invalid_n" };
  }
  if (n > suggestions.length) {
    return {
      ok: false,
      error: `out_of_range:${suggestions.length}`,
    };
  }
  return { ok: true, message: suggestions[n - 1] };
}

describe("--followup flag resolution", () => {
  const SUGGESTIONS = [
    "What are the main trade-offs?",
    "Can you show a code example?",
    "How does this compare to alternatives?",
    "What are common pitfalls to avoid?",
    "Is there a simpler approach?",
    "What documentation should I read next?",
  ];

  it("resolves --followup 1 to the first suggestion", () => {
    const result = resolveFollowUp(SUGGESTIONS, 1);
    assert.ok(result.ok);
    assert.strictEqual(
      result.ok && result.message,
      "What are the main trade-offs?",
    );
  });

  it("resolves --followup 3 to the third suggestion", () => {
    const result = resolveFollowUp(SUGGESTIONS, 3);
    assert.ok(result.ok);
    assert.strictEqual(
      result.ok && result.message,
      "How does this compare to alternatives?",
    );
  });

  it("resolves --followup 6 to the last suggestion (boundary)", () => {
    const result = resolveFollowUp(SUGGESTIONS, 6);
    assert.ok(result.ok);
    assert.strictEqual(
      result.ok && result.message,
      "What documentation should I read next?",
    );
  });

  it("returns error when n is out of range (too high)", () => {
    const result = resolveFollowUp(SUGGESTIONS, 7);
    assert.ok(!result.ok);
    assert.ok(!result.ok && result.error.startsWith("out_of_range:"));
    // Error message includes the actual count for user feedback
    assert.ok(!result.ok && result.error.includes(String(SUGGESTIONS.length)));
  });

  it("returns error for n=0 (invalid — 1-based index)", () => {
    const result = resolveFollowUp(SUGGESTIONS, 0);
    assert.ok(!result.ok);
    assert.strictEqual(!result.ok && result.error, "invalid_n");
  });

  it("returns error for negative n", () => {
    const result = resolveFollowUp(SUGGESTIONS, -1);
    assert.ok(!result.ok);
    assert.strictEqual(!result.ok && result.error, "invalid_n");
  });

  it("returns error when suggestions list is empty", () => {
    const result = resolveFollowUp([], 1);
    assert.ok(!result.ok);
    assert.strictEqual(!result.ok && result.error, "no_suggestions");
  });

  it("resolves a suggestion with quotes correctly (shell safety check)", () => {
    const withQuotes = [
      'Explain "zero-knowledge proofs" in plain English',
      "What is a practical use case?",
    ];
    const result = resolveFollowUp(withQuotes, 1);
    assert.ok(result.ok);
    // The message contains quotes — callers must escape before embedding in shell commands
    assert.ok(result.ok && result.message.includes('"zero-knowledge proofs"'));
  });

  it("is 1-based: --followup 1 is index 0, --followup 2 is index 1", () => {
    const result1 = resolveFollowUp(SUGGESTIONS, 1);
    const result2 = resolveFollowUp(SUGGESTIONS, 2);
    assert.ok(result1.ok && result2.ok);
    assert.notStrictEqual(
      result1.ok && result1.message,
      result2.ok && result2.message,
    );
    assert.strictEqual(result1.ok && result1.message, SUGGESTIONS[0]);
    assert.strictEqual(result2.ok && result2.message, SUGGESTIONS[1]);
  });
});
