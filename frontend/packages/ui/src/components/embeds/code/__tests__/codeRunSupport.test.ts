// frontend/packages/ui/src/components/embeds/code/__tests__/codeRunSupport.test.ts
// Regression tests for the Code Run CTA allowlist.
// Verifies the frontend only offers execution for languages supported by the
// backend runner and keeps Atopile hidden until a dedicated hardware flow exists.
// Architecture: docs/architecture/messaging/embeds.md

import { describe, expect, it } from "vitest";
import { isCodeRunSupported } from "../codeRunSupport";

describe("isCodeRunSupported", () => {
  it.each([
    ["python", "main.py"],
    ["javascript", "main.js"],
    ["typescript", "main.ts"],
    ["bash", "run.sh"],
    ["c", "main.c"],
    ["cpp", "main.cpp"],
    ["rust", "main.rs"],
    ["go", "main.go"],
  ])("supports %s code", (language, filename) => {
    expect(isCodeRunSupported(language, filename)).toBe(true);
  });

  it.each([
    ["", "main.c"],
    ["", "main.cc"],
    ["", "main.cxx"],
    ["", "main.rs"],
    ["", "main.go"],
  ])("supports executable extensions when language is missing", (language, filename) => {
    expect(isCodeRunSupported(language, filename)).toBe(true);
  });

  it.each([
    ["atopile", "board.ato"],
    ["ato", "board.ato"],
    ["", "board.ato"],
    ["markdown", "notes.md"],
    ["html", "index.html"],
  ])("does not support %s / %s", (language, filename) => {
    expect(isCodeRunSupported(language, filename)).toBe(false);
  });
});
