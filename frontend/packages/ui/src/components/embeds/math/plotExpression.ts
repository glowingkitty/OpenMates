// frontend/packages/ui/src/components/embeds/math/plotExpression.ts
// Helpers for adapting model-generated plot expressions to function-plot syntax.
// The model and users commonly write Euler exponentials as e^(x), while the
// function-plot parser expects exp(x) and otherwise treats e as an undefined
// symbol. Keeping this conversion isolated makes renderer behavior testable.
// Architecture: docs/architecture/embeds.md

const EULER_NUMBER_LITERAL = "2.718281828459045";

function isWordChar(char: string | undefined): boolean {
  return !!char && /[a-zA-Z0-9_]/.test(char);
}

function readBalancedParentheses(value: string, openIndex: number): { inner: string; endIndex: number } | null {
  let depth = 0;

  for (let index = openIndex; index < value.length; index += 1) {
    const char = value[index];
    if (char === "(") depth += 1;
    if (char === ")") depth -= 1;

    if (depth === 0) {
      return {
        inner: value.slice(openIndex + 1, index),
        endIndex: index,
      };
    }
  }

  return null;
}

function readExponentToken(value: string, startIndex: number): { token: string; endIndex: number } | null {
  let index = startIndex;
  if (value[index] === "+" || value[index] === "-") index += 1;

  const tokenStart = index;
  while (index < value.length && /[a-zA-Z0-9_.]/.test(value[index])) {
    index += 1;
  }

  if (index === tokenStart) return null;

  return {
    token: value.slice(startIndex, index),
    endIndex: index - 1,
  };
}

export function normalizePlotExpression(expression: string): string {
  let normalized = "";

  for (let index = 0; index < expression.length; index += 1) {
    const char = expression[index];
    const isStandaloneEuler = char === "e" && !isWordChar(expression[index - 1]) && !isWordChar(expression[index + 1]);

    if (!isStandaloneEuler) {
      normalized += char;
      continue;
    }

    let cursor = index + 1;
    while (expression[cursor] === " ") cursor += 1;

    if (expression[cursor] !== "^") {
      normalized += EULER_NUMBER_LITERAL;
      continue;
    }

    cursor += 1;
    while (expression[cursor] === " ") cursor += 1;

    if (expression[cursor] === "(") {
      const balanced = readBalancedParentheses(expression, cursor);
      if (balanced) {
        normalized += `exp(${balanced.inner})`;
        index = balanced.endIndex;
        continue;
      }
    }

    const exponent = readExponentToken(expression, cursor);
    if (exponent) {
      normalized += `exp(${exponent.token})`;
      index = exponent.endIndex;
      continue;
    }

    normalized += EULER_NUMBER_LITERAL;
  }

  return normalized;
}
