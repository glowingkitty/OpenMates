// frontend/packages/ui/src/components/embeds/code/__tests__/codeRunSupport.test.ts
// Regression tests for the Code Run CTA allowlist.
// Verifies the frontend only offers execution for languages supported by the
// backend runner and keeps Atopile hidden until a dedicated hardware flow exists.
// Architecture: docs/architecture/messaging/embeds.md

import { describe, expect, it } from "vitest";
import { AUTOMATIC_DEPENDENCY_VERSION, defaultDependencyVersion, dependencyPackageSpec, isCodeRunSupported } from "../codeRunSupport";

describe("isCodeRunSupported", () => {
  // contract-test: supporting surface=gui.web assertions=code-run.execution.e2b-only
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

  // contract-test: supporting surface=gui.web assertions=code-run.execution.e2b-only
  it.each([
    ["", "main.c"],
    ["", "main.cc"],
    ["", "main.cxx"],
    ["", "main.rs"],
    ["", "main.go"],
  ])("supports executable extensions when language is missing", (language, filename) => {
    expect(isCodeRunSupported(language, filename)).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=code-run.execution.e2b-only
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


describe("dependency version selection", () => {
  // contract-test: supporting surface=gui.web assertions=code-run.request.validated
  it("leaves imported Python packages unpinned even when the registry latest requires a newer interpreter", () => {
    // Frozen regression: numpy 2.5.4 requires >=3.12, but the sandbox uses 3.11.
    const version = defaultDependencyVersion("python", "2.5.4");
    expect(version).toBe(AUTOMATIC_DEPENDENCY_VERSION);
    expect(dependencyPackageSpec("python", "numpy", version)).toBe("numpy");
  });

  // contract-test: supporting surface=gui.web assertions=code-run.request.validated
  it("preserves an explicitly selected Python version, including registry latest", () => {
    expect(dependencyPackageSpec("python", "numpy", "2.5.4")).toBe("numpy==2.5.4");
    expect(dependencyPackageSpec("python", "numpy", "2.4.6")).toBe("numpy==2.4.6");
    expect(dependencyPackageSpec("python", "numpy", AUTOMATIC_DEPENDENCY_VERSION)).toBe("numpy");
  });

  // contract-test: supporting surface=gui.web assertions=code-run.request.validated
  it("keeps npm latest and scoped package pins unchanged", () => {
    const version = defaultDependencyVersion("npm", "4.0.0");
    expect(version).toBe("4.0.0");
    expect(dependencyPackageSpec("npm", "@example/parser", version)).toBe("@example/parser@4.0.0");
  });
});
