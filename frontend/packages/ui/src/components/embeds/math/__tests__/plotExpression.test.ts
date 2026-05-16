// frontend/packages/ui/src/components/embeds/math/__tests__/plotExpression.test.ts
// Regression tests for math plot expression normalization.
// Covers Euler constant syntax that users and LLMs naturally write but the
// function-plot parser does not accept as a built-in symbol.
// Architecture: docs/architecture/embeds.md

import { describe, expect, it } from "vitest";
import { normalizePlotExpression } from "../plotExpression";

describe("normalizePlotExpression", () => {
  it("converts parenthesized Euler exponentials to exp calls", () => {
    expect(normalizePlotExpression("cos(10 * e^(-0.5 * x))")).toBe(
      "cos(10 * exp(-0.5 * x))",
    );
  });

  it("converts simple Euler exponentials to exp calls", () => {
    expect(normalizePlotExpression("e^x + e^-x")).toBe("exp(x) + exp(-x)");
  });

  it("converts standalone Euler constants without touching identifiers", () => {
    expect(normalizePlotExpression("2 * e + exp(x) + sec(x)")).toBe(
      "2 * 2.718281828459045 + exp(x) + sec(x)",
    );
  });
});
