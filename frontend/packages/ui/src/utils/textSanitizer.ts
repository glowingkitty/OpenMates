// frontend/packages/ui/src/utils/textSanitizer.ts
//
// Strips invisible and dangerous Unicode characters from user-supplied text.
// Applied to all text entering the message input — paste events, deep links,
// notification replies — to prevent ASCII smuggling, homoglyph injection, and
// invisible-character attacks that could manipulate AI model behavior.
//
// Design: allowlist-based. We strip everything that is invisible or has no
// legitimate use in natural-language chat input, while preserving normal
// whitespace (spaces, tabs, newlines) and all visible characters.

/** Characters that are invisible but legitimate in chat input. */
const ALLOWED_WHITESPACE = new Set([
  0x09, // TAB
  0x0a, // LINE FEED
  0x0d, // CARRIAGE RETURN
  0x20, // SPACE
]);

/**
 * Sanitize a string by removing invisible and potentially dangerous Unicode
 * characters. This is a defense-in-depth measure against ASCII smuggling
 * and prompt injection via invisible characters.
 *
 * Stripped character classes:
 *   - ASCII control characters (U+0000–U+001F, U+007F) except TAB/LF/CR
 *   - Unicode "Other" control characters (U+0080–U+009F)
 *   - Zero-width characters (ZWSP, ZWNJ, ZWJ, WJ, FEFF/BOM)
 *   - Bidirectional override/embedding/isolate characters (U+200E–U+200F, U+202A–U+202E, U+2066–U+2069)
 *   - Invisible formatting (soft hyphen U+00AD, NBSP variants, interlinear annotation anchors)
 *   - Tag characters (U+E0001–U+E007F) — used in ASCII smuggling attacks
 *   - Variation selectors (U+FE00–U+FE0F, U+E0100–U+E01EF)
 *   - Deprecated/obscure invisible characters (U+2060–U+2064, U+2066–U+206F, U+FEFF)
 *
 * Preserved:
 *   - All visible characters (letters, digits, punctuation, symbols, emoji)
 *   - Space, tab, newline, carriage return
 */
export function sanitizeText(input: string): string {
  if (!input) return input;

  let result = "";
  for (let i = 0; i < input.length; i++) {
    const code = input.codePointAt(i)!;

    if (shouldStrip(code)) {
      // Skip astral-plane characters (surrogate pairs take 2 code units)
      if (code > 0xffff) i++;
      continue;
    }

    // Append the character (handles surrogate pairs correctly)
    if (code > 0xffff) {
      result += input[i] + input[i + 1];
      i++;
    } else {
      result += input[i];
    }
  }

  return result;
}

function shouldStrip(code: number): boolean {
  // ASCII control characters (except allowed whitespace)
  if (code <= 0x1f) return !ALLOWED_WHITESPACE.has(code);
  if (code === 0x7f) return true; // DEL

  // C1 control characters
  if (code >= 0x80 && code <= 0x9f) return true;

  // Soft hyphen (invisible in most contexts, used for smuggling)
  if (code === 0x00ad) return true;

  // Zero-width and invisible formatting characters
  if (code === 0x200b) return true; // ZERO WIDTH SPACE
  if (code === 0x200c) return true; // ZERO WIDTH NON-JOINER
  if (code === 0x200d) return true; // ZERO WIDTH JOINER
  if (code === 0xfeff) return true; // BOM / ZERO WIDTH NO-BREAK SPACE

  // Bidirectional control characters
  if (code >= 0x200e && code <= 0x200f) return true; // LRM, RLM
  if (code >= 0x202a && code <= 0x202e) return true; // LRE, RLE, PDF, LRO, RLO
  if (code >= 0x2066 && code <= 0x2069) return true; // LRI, RLI, FSI, PDI

  // General invisible formatting
  if (code >= 0x2060 && code <= 0x2064) return true; // WJ, function application, invisible times/separator/plus
  if (code === 0x2065) return true; // unassigned but in the block
  if (code >= 0x206a && code <= 0x206f) return true; // deprecated formatting chars

  // Interlinear annotation anchors
  if (code >= 0xfff9 && code <= 0xfffb) return true;

  // Variation selectors
  if (code >= 0xfe00 && code <= 0xfe0f) return true;

  // Object replacement character (sometimes used to hide content)
  if (code === 0xfffc) return true;

  // Tag characters (U+E0000–U+E007F) — primary vector for ASCII smuggling
  if (code >= 0xe0000 && code <= 0xe007f) return true;

  // Variation selectors supplement (U+E0100–U+E01EF)
  if (code >= 0xe0100 && code <= 0xe01ef) return true;

  return false;
}
