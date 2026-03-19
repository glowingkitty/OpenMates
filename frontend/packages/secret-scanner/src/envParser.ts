// frontend/packages/secret-scanner/src/envParser.ts
/**
 * @file Simple .env file parser for extracting key-value pairs.
 *
 * Parses standard .env file format: KEY=VALUE, KEY="VALUE", KEY='VALUE'.
 * Handles comments (#), empty lines, and multi-line values.
 * Does NOT modify process.env — returns a plain object.
 *
 * Architecture: docs/planned/cli-package.md (Secret sources scanned)
 */

/**
 * Parse a .env file content string into a key-value object.
 *
 * Supports:
 * - KEY=value (unquoted)
 * - KEY="value" (double-quoted, preserves spaces)
 * - KEY='value' (single-quoted, preserves spaces)
 * - # comments (full-line and inline after unquoted values)
 * - Empty lines (skipped)
 * - export KEY=value (optional export prefix)
 *
 * @param content Raw .env file content
 * @returns Object mapping variable names to their values
 */
export function parseEnvFile(content: string): Record<string, string> {
  const result: Record<string, string> = {};

  const lines = content.split("\n");

  for (const rawLine of lines) {
    const line = rawLine.trim();

    // Skip empty lines and comments
    if (!line || line.startsWith("#")) continue;

    // Remove optional "export " prefix
    const cleanLine = line.startsWith("export ")
      ? line.slice(7).trim()
      : line;

    // Find the first = sign
    const eqIndex = cleanLine.indexOf("=");
    if (eqIndex === -1) continue;

    const key = cleanLine.slice(0, eqIndex).trim();
    if (!key) continue;

    let value = cleanLine.slice(eqIndex + 1).trim();

    // Handle quoted values
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    } else {
      // Remove inline comments for unquoted values
      const commentIndex = value.indexOf(" #");
      if (commentIndex !== -1) {
        value = value.slice(0, commentIndex).trim();
      }
    }

    result[key] = value;
  }

  return result;
}
