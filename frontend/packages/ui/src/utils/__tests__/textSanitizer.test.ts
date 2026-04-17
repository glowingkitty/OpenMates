// frontend/packages/ui/src/utils/__tests__/textSanitizer.test.ts
//
// Unit tests for sanitizeText() — strips invisible Unicode characters to
// prevent ASCII smuggling, prompt injection via hidden characters, and
// bidirectional text attacks in chat input and deep links.

import { describe, it, expect } from "vitest";
import { sanitizeText } from "../textSanitizer";

describe("sanitizeText", () => {
  // ── Passthrough (no modification) ──────────────────────────────────

  it("returns empty string unchanged", () => {
    expect(sanitizeText("")).toBe("");
    expect(sanitizeText(null as unknown as string)).toBe(null);
    expect(sanitizeText(undefined as unknown as string)).toBe(undefined);
  });

  it("preserves plain ASCII text", () => {
    const input = "Hello, world! How are you?";
    expect(sanitizeText(input)).toBe(input);
  });

  it("preserves allowed whitespace (space, tab, newline, CR)", () => {
    const input = "line1\nline2\tindented\r\nwindows";
    expect(sanitizeText(input)).toBe(input);
  });

  it("preserves Unicode letters, digits, and punctuation", () => {
    const input = "Ärger über Größe — €42,00 ¿Qué? 日本語テスト مرحبا";
    expect(sanitizeText(input)).toBe(input);
  });

  it("preserves emoji", () => {
    const input = "Hello 👋🏽 world 🌍 test 🎉";
    expect(sanitizeText(input)).toBe(input);
  });

  it("preserves common symbols and math", () => {
    const input = "a + b = c × d ÷ e ≈ f ≠ g © ® ™ § ¶ • …";
    expect(sanitizeText(input)).toBe(input);
  });

  it("preserves email addresses and URLs", () => {
    const input = "john@example.com https://openmates.org/#settings/apps +49 170 1234567";
    expect(sanitizeText(input)).toBe(input);
  });

  // ── ASCII control characters ───────────────────────────────────────

  it("strips ASCII control characters (except tab/LF/CR)", () => {
    expect(sanitizeText("hello\x00world")).toBe("helloworld");
    expect(sanitizeText("hello\x01world")).toBe("helloworld");
    expect(sanitizeText("hello\x08world")).toBe("helloworld");
    expect(sanitizeText("hello\x1Fworld")).toBe("helloworld");
  });

  it("strips DEL character", () => {
    expect(sanitizeText("hello\x7Fworld")).toBe("helloworld");
  });

  // ── C1 control characters ─────────────────────────────────────────

  it("strips C1 control characters (U+0080–U+009F)", () => {
    expect(sanitizeText("hello\u0080world")).toBe("helloworld");
    expect(sanitizeText("hello\u0085world")).toBe("helloworld");
    expect(sanitizeText("hello\u009Fworld")).toBe("helloworld");
  });

  // ── Zero-width characters ─────────────────────────────────────────

  it("strips zero-width space (U+200B)", () => {
    expect(sanitizeText("hello\u200Bworld")).toBe("helloworld");
  });

  it("strips zero-width non-joiner (U+200C)", () => {
    expect(sanitizeText("hello\u200Cworld")).toBe("helloworld");
  });

  it("strips zero-width joiner (U+200D)", () => {
    expect(sanitizeText("hello\u200Dworld")).toBe("helloworld");
  });

  it("strips BOM / zero-width no-break space (U+FEFF)", () => {
    expect(sanitizeText("\uFEFFhello")).toBe("hello");
    expect(sanitizeText("hello\uFEFF")).toBe("hello");
  });

  // ── Bidirectional control characters ──────────────────────────────

  it("strips LRM and RLM (U+200E, U+200F)", () => {
    expect(sanitizeText("hello\u200Eworld")).toBe("helloworld");
    expect(sanitizeText("hello\u200Fworld")).toBe("helloworld");
  });

  it("strips bidi embedding/override characters (U+202A–U+202E)", () => {
    expect(sanitizeText("hello\u202Aworld")).toBe("helloworld"); // LRE
    expect(sanitizeText("hello\u202Bworld")).toBe("helloworld"); // RLE
    expect(sanitizeText("hello\u202Cworld")).toBe("helloworld"); // PDF
    expect(sanitizeText("hello\u202Dworld")).toBe("helloworld"); // LRO
    expect(sanitizeText("hello\u202Eworld")).toBe("helloworld"); // RLO
  });

  it("strips bidi isolate characters (U+2066–U+2069)", () => {
    expect(sanitizeText("hello\u2066world")).toBe("helloworld"); // LRI
    expect(sanitizeText("hello\u2067world")).toBe("helloworld"); // RLI
    expect(sanitizeText("hello\u2068world")).toBe("helloworld"); // FSI
    expect(sanitizeText("hello\u2069world")).toBe("helloworld"); // PDI
  });

  // ── Invisible formatting ──────────────────────────────────────────

  it("strips soft hyphen (U+00AD)", () => {
    expect(sanitizeText("in\u00ADvisible")).toBe("invisible");
  });

  it("strips word joiner and invisible operators (U+2060–U+2064)", () => {
    expect(sanitizeText("a\u2060b")).toBe("ab"); // WJ
    expect(sanitizeText("a\u2061b")).toBe("ab"); // function application
    expect(sanitizeText("a\u2062b")).toBe("ab"); // invisible times
    expect(sanitizeText("a\u2063b")).toBe("ab"); // invisible separator
    expect(sanitizeText("a\u2064b")).toBe("ab"); // invisible plus
  });

  it("strips deprecated formatting characters (U+206A–U+206F)", () => {
    expect(sanitizeText("a\u206Ab")).toBe("ab");
    expect(sanitizeText("a\u206Fb")).toBe("ab");
  });

  it("strips interlinear annotation anchors (U+FFF9–U+FFFB)", () => {
    expect(sanitizeText("a\uFFF9b\uFFFAc\uFFFBd")).toBe("abcd");
  });

  it("strips object replacement character (U+FFFC)", () => {
    expect(sanitizeText("a\uFFFCb")).toBe("ab");
  });

  // ── Variation selectors ───────────────────────────────────────────

  it("strips variation selectors (U+FE00–U+FE0F)", () => {
    expect(sanitizeText("a\uFE00b")).toBe("ab");
    expect(sanitizeText("a\uFE0Fb")).toBe("ab");
  });

  // ── Tag characters (ASCII smuggling vector) ───────────────────────

  it("strips tag characters (U+E0001–U+E007F)", () => {
    // Tag characters encode hidden ASCII — primary smuggling vector
    const tagA = String.fromCodePoint(0xe0041); // TAG LATIN CAPITAL LETTER A
    const tagZ = String.fromCodePoint(0xe005a); // TAG LATIN CAPITAL LETTER Z
    const cancel = String.fromCodePoint(0xe007f); // CANCEL TAG
    const begin = String.fromCodePoint(0xe0001); // LANGUAGE TAG

    expect(sanitizeText(`hello${begin}${tagA}${tagZ}${cancel}world`)).toBe("helloworld");
  });

  it("strips variation selectors supplement (U+E0100–U+E01EF)", () => {
    const vs17 = String.fromCodePoint(0xe0100);
    const vs256 = String.fromCodePoint(0xe01ef);
    expect(sanitizeText(`a${vs17}b${vs256}c`)).toBe("abc");
  });

  // ── Real-world attack patterns ────────────────────────────────────

  it("strips ASCII smuggling payload hidden in normal text", () => {
    // Simulates an attack where invisible tag characters encode a hidden instruction
    const visible = "Please summarize this document.";
    const hidden = [0xe0049, 0xe0067, 0xe006e, 0xe006f, 0xe0072, 0xe0065] // "Ignore" in tags
      .map((cp) => String.fromCodePoint(cp))
      .join("");
    const input = visible + hidden;
    expect(sanitizeText(input)).toBe(visible);
  });

  it("strips mixed invisible characters from a realistic message", () => {
    const input =
      "\uFEFF\u200BHello\u200C \u200Dworld\u200E!\u2060\u00AD";
    expect(sanitizeText(input)).toBe("Hello world!");
  });

  it("handles bidi override attack (filename spoofing pattern)", () => {
    // Classic RLO attack: "my-photo\u202Egnp.exe" displays as "my-photoexe.png"
    const input = "my-photo\u202Egnp.exe";
    expect(sanitizeText(input)).toBe("my-photognp.exe");
  });

  // ── Edge cases ────────────────────────────────────────────────────

  it("handles string that is entirely invisible characters", () => {
    const input = "\u200B\u200C\u200D\uFEFF\u2060";
    expect(sanitizeText(input)).toBe("");
  });

  it("handles astral plane visible characters correctly", () => {
    // Mathematical bold A (U+1D400) — visible, should be preserved
    const mathBoldA = String.fromCodePoint(0x1d400);
    expect(sanitizeText(`${mathBoldA}test`)).toBe(`${mathBoldA}test`);
  });

  it("handles mixed astral visible + astral invisible characters", () => {
    const mathBoldA = String.fromCodePoint(0x1d400);
    const tagA = String.fromCodePoint(0xe0041);
    expect(sanitizeText(`${mathBoldA}${tagA}test`)).toBe(`${mathBoldA}test`);
  });

  it("preserves normal astral-plane emoji sequences", () => {
    // Family emoji (compound), flag sequences, etc.
    const flag = "🇩🇪";
    const rocket = "🚀";
    expect(sanitizeText(`Go ${flag} ${rocket}`)).toBe(`Go ${flag} ${rocket}`);
  });
});
