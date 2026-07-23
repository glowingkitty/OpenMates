/**
 * Remember-message CLI/SDK rewrite tests.
 *
 * Purpose: lock the visible quote-block rewrite used before encryption/sending.
 * Architecture: explicit user text resolves to plaintext only in the client.
 * Security: no backend hidden context or compression state is mutated.
 * Run: node --test --experimental-strip-types --loader ./tests/loader.mjs tests/rememberMessage.test.ts
 */

import { describe, it } from "node:test";
import assert from "node:assert/strict";

const { hasRememberMessageReference, rewriteRememberMessageReferences } = await import("../src/rememberMessage.ts");

describe("remember message rewrite", () => {
  it("rewrites short message references into visible quote blocks", () => {
    const rewritten = rewriteRememberMessageReferences("Remember my message @abc12345", [
      { id: "abc12345-0000-4000-8000-000000000000", content: "Original line\nSecond [embed](embed:ref-1)" },
    ]);

    assert.equal(
      rewritten,
      "Remember my earlier message:\n\n> Original line\n> Second [embed](embed:ref-1)",
    );
  });

  it("leaves unresolved references unchanged", () => {
    assert.equal(hasRememberMessageReference("Remember my earlier message @missing"), true);
    assert.equal(rewriteRememberMessageReferences("Remember my earlier message @missing", []), "Remember my earlier message @missing");
  });
});
