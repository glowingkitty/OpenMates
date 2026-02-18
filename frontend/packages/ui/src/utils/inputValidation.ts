// frontend/packages/ui/src/utils/inputValidation.ts
//
// Input validation constants and helpers for settings/memories forms.
//
// These limits serve two purposes:
//   1. UX — keep memories concise so they are useful context for the AI, not
//      walls of text that inflate the system prompt and cost more tokens.
//   2. Storage hygiene — the backend enforces a matching encrypted-payload size
//      limit so these constants must stay in sync with MAX_ENCRYPTED_ENTRY_BYTES
//      in store_app_settings_memories_handler.py.
//
// Field type mapping:
//   SHORT  — single-line text inputs: names, titles, labels, genre, author, city…
//   URL    — URLs can be long; git repos, websites (separate limit)
//   MULTILINE — multi-line textareas: notes, descriptions, freeform text
//   GENERIC_VALUE — the raw "item value" textarea in the generic fallback form
//                   (can contain JSON, so it gets a higher limit)
//
// To increase a single field's limit, set `maxLength` on the schema property
// in the app.yml — the getMaxLength() function will respect it.

/** Maximum characters for standard single-line fields (names, titles, labels, city, genre…). */
export const MAX_LENGTH_SHORT = 100;

/** Maximum characters for URL fields (git repos, websites, etc.). */
export const MAX_LENGTH_URL = 300;

/** Maximum characters for multi-line text fields (notes, descriptions, freeform). */
export const MAX_LENGTH_MULTILINE = 500;

/** Maximum characters for the generic form's "item value" textarea (supports JSON). */
export const MAX_LENGTH_GENERIC_VALUE = 1000;

/** Maximum characters for the generic form's "item key" field. */
export const MAX_LENGTH_GENERIC_KEY = 100;

/**
 * Minimal subset of a schema property needed for max-length resolution.
 * Kept separate from SchemaPropertyDefinition to avoid circular imports.
 */
export interface PropForMaxLength {
  maxLength?: number;
  multiline?: boolean;
  format?: string; // JSON Schema format: "uri", "date", "email", etc.
  [key: string]: unknown; // allow passing full SchemaPropertyDefinition
}

/**
 * Return the appropriate max-length for a schema property.
 *
 * Priority order:
 *   1. Explicit `maxLength` on the property (author override in app.yml)
 *   2. `multiline: true` → MULTILINE limit
 *   3. `format: "uri"` or `format: "url"` → URL limit
 *   4. Default → SHORT limit
 */
export function getMaxLength(prop: PropForMaxLength): number {
  if (typeof prop.maxLength === "number") return prop.maxLength;
  if (prop.multiline === true) return MAX_LENGTH_MULTILINE;
  if (prop.format === "uri" || prop.format === "url") return MAX_LENGTH_URL;
  return MAX_LENGTH_SHORT;
}

/**
 * Validate a string value against a max-length constraint.
 * Returns an error message string if invalid, null if valid.
 *
 * @param value   The string value to validate
 * @param max     Maximum allowed character count
 * @param label   Human-readable field label for the error message
 */
export function validateMaxLength(
  value: string,
  max: number,
  label: string,
): string | null {
  if (value.length > max) {
    return `${label} must be ${max} characters or fewer (currently ${value.length})`;
  }
  return null;
}
