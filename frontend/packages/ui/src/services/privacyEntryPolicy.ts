/**
 * Hydration plan of one decrypted privacy entry: the `??` / `||` defaults that
 * personalDataStore's performLoadFromStorage applies per item type. Pure and
 * synchronous; the shared Rust twin is packages/openmates-rust/src/web_settings_privacy.rs
 * (vectors: web_settings_privacy_ts_vectors.json).
 *
 * Known difference: a non-object `categories` value is spread by JavaScript
 * (string/array indices) but ignored by Rust.
 * spec: sdk.client.thin-platform-boundary
 */
export type PrivacyEntryPlan =
  | { kind: 'pii'; masterEnabled: unknown; enhancedEnabled: unknown; categories: Record<string, unknown> }
  | { kind: 'location'; impreciseByDefault: unknown }
  | { kind: 'personal'; type: unknown; title: unknown; textToHide: unknown; replaceWith: unknown; enabled: unknown; addressLines?: unknown }
  | { kind: 'other' };

export const PII_SETTINGS_ITEM_TYPE = 'pii_detection_settings';
export const LOCATION_SETTINGS_ITEM_TYPE = 'location_settings';
export const PERSONAL_DATA_ITEM_TYPE = 'personal_data_entry';

/** Plan for one entry; throws (TypeError) on null data for a known item type, as the inline code did. */
export function planPrivacyEntry(
  itemType: string, data: Record<string, unknown>, defaultCategories: Record<string, boolean>,
): PrivacyEntryPlan {
  if (itemType === PII_SETTINGS_ITEM_TYPE) {
    return {
      kind: 'pii',
      masterEnabled: data.masterEnabled ?? true,
      enhancedEnabled: data.enhancedEnabled ?? true,
      categories: { ...defaultCategories, ...((data.categories as Record<string, unknown> | undefined) || {}) },
    };
  }
  if (itemType === LOCATION_SETTINGS_ITEM_TYPE) {
    return { kind: 'location', impreciseByDefault: data.impreciseByDefault ?? true };
  }
  if (itemType === PERSONAL_DATA_ITEM_TYPE) {
    const plan: PrivacyEntryPlan = {
      kind: 'personal',
      type: data.type || 'custom',
      title: data.title || '',
      textToHide: data.textToHide || '',
      replaceWith: data.replaceWith || '',
      enabled: data.enabled ?? true,
    };
    if (data.addressLines !== undefined) plan.addressLines = data.addressLines;
    return plan;
  }
  return { kind: 'other' };
}
