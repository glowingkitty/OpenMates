import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import YAML from "yaml";
import { describe, expect, it } from "vitest";

type Translation = { en: string; de?: string };
const documents = Object.fromEntries(["terms", "privacy"].map((name) => [
  name,
  YAML.parse(readFileSync(resolve(process.cwd(), `src/i18n/sources/legal/${name}.yml`), "utf8")) as Record<string, Translation>,
]));

// Provider names, numbered brand headings, and the word "Details" are also German.
const sharedNames = new Set([
  "3.14 Flightradar24",
  "Wikimedia Foundation (Wikipedia)", "ExampleClinicA (EU)", "Edamam", "Details", "Hetzner", "Mistral AI",
  "OpenAI", "Google Gemini", "Google Calendar",
  "SEC EDGAR", "Open-Meteo", "Bright Sky", "JobTech JobSearch", "ExampleJobsD",
]);

const placeholders = (value: string) => [...value.matchAll(/\{[^{}]+\}/g)].map(([match]) => match).sort();

describe("German legal translations", () => {
  for (const [name, translations] of Object.entries(documents)) {
    // contract-test: supporting surface=gui.web assertions=storage.privacy.ciphertext-boundary
    it(`${name} has German copy without an English prose fallback`, () => {
      for (const [key, entry] of Object.entries(translations)) {
        expect(entry.de?.trim(), `${name}.${key} needs German text`).toBeTruthy();
        if (!sharedNames.has(entry.en)) {
          expect(entry.de, `${name}.${key} copies English prose`).not.toBe(entry.en);
        }
        expect(placeholders(entry.de!), `${name}.${key} preserves link placeholders`)
          .toEqual(placeholders(entry.en));
      }
    });
  }
});
