/** Local model ranges join the existing reversible encrypted-mapping boundary. */
import { codingIdentifierRanges } from "../../secret-scanner/src/identifierRanges.js";
import { ProjectFilePrivacy } from "../../ui/src/services/projectFilePrivacy.js";
import type { PIIDetectionOptions, PIIMappingGeneric } from "../../ui/src/components/enter_message/services/piiDetectionService.js";
import type { DecryptedMemoryEntry } from "./client.js";
import { enhancedScopeEnabled, privacyError, privacyProfile, readPrivacyPreferences, type PrivacyScope } from "./privacyModel.js";
import { ensurePrivacyDaemon, privacyRpc, stopPrivacyDaemon, type NativePrivacyRange } from "./privacyWorker.js";

const LABELS: Record<string, { type: string; category: string }> = {
  private_person: { type: "OTHER", category: "names" }, private_address: { type: "ADDRESS", category: "addresses" },
  private_email: { type: "EMAIL", category: "email_addresses" }, private_phone: { type: "PHONE", category: "phone_numbers" },
  secret: { type: "GENERIC_SECRET", category: "generic_secrets" }, account_number: { type: "OTHER", category: "iban_bank_account" },
  private_date: { type: "OTHER", category: "birthdays" }, private_url: { type: "OTHER", category: "private_urls" },
};
export function convertNativePrivacyRanges(text: string, spans: NativePrivacyRange[], disabled = new Set<string>()): Array<{ start: number; end: number; type: string }> {
  const offsets = new Map<number, number>([[0, 0]]); let bytes = 0; let units = 0;
  for (const character of text) {
    if (character.length === 1 && /[\uD800-\uDFFF]/.test(character)) throw privacyError("privacy_invalid_unicode");
    bytes += Buffer.byteLength(character); units += character.length; offsets.set(bytes, units);
  }
  const protectedRanges = codingIdentifierRanges(text); const result = [];
  for (const span of spans) {
    const label = LABELS[span.label];
    const start = offsets.get(span.start), end = offsets.get(span.end);
    if (!label || !Number.isInteger(span.start) || !Number.isInteger(span.end) || start === undefined || end === undefined || end <= start) throw privacyError("privacy_invalid_semantic_range");
    if (disabled.has(label.category) || span.label === "secret" && disabled.has("api_keys")) continue;
    const context = text.slice(Math.max(0, start - 60), Math.min(text.length, end + 60));
    const explicitSecret = /\b(?:password|secret|credential|api[_ -]?key|token)\b/i.test(context);
    if (protectedRanges.some((r) => start < r.end && end > r.start) && !(span.label === "secret" && explicitSecret && !text.slice(start, end).startsWith("["))) continue;
    if ((span.label === "private_date" || span.label === "account_number") && /\b(?:commit|sha|hash|build|release|branch|timestamp|version)\b/i.test(context) && !/\b(?:birth|birthday|born|dob|account|iban)\b/i.test(context)) continue;
    result.push({ start, end, type: label.type });
  }
  return result;
}
export function privacyDetectionOptions(memories: DecryptedMemoryEntry[]): { enabled: boolean; detection: PIIDetectionOptions } {
  const settings = memories.find((m) => m.app_id === "privacy" && m.item_type === "pii_detection_settings")?.data as { masterEnabled?: boolean; categories?: Record<string, boolean> } | undefined;
  return { enabled: settings?.masterEnabled !== false, detection: {
    disabledCategories: new Set(Object.entries(settings?.categories ?? {}).filter(([, value]) => value === false).map(([key]) => key)),
    personalDataEntries: memories.filter((m) => m.app_id === "privacy" && m.item_type === "personal_data_entry").flatMap((entry) => {
      const data = entry.data as { enabled?: boolean; textToHide?: string; replaceWith?: string; addressLines?: Record<string, string> };
      return data.enabled && data.textToHide && data.replaceWith ? [{ id: entry.id, textToHide: data.textToHide, replaceWith: data.replaceWith, additionalTexts: Object.values(data.addressLines ?? {}) }] : [];
    }),
  } };
}
export async function scanEnhancedText(text: string, scope: PrivacyScope, disabled = new Set<string>(), progress?: (done: number, total: number) => void): Promise<Array<{ start: number; end: number; type: string }>> {
  const preferences = await readPrivacyPreferences(); if (!text || !enhancedScopeEnabled(preferences, scope)) return [];
  try {
    await ensurePrivacyDaemon();
    const ranges: Array<{ start: number; end: number; type: string }> = [];
    // Overlapping bounded windows process every character; neither truncation
    // nor a size-based switch back to deterministic detection is permitted.
    for (let start = 0; start < text.length; start += 8192) {
      let from = Math.max(0, start - 1024), end = Math.min(text.length, start + 9216);
      if (from > 0 && /[\uDC00-\uDFFF]/.test(text[from]!)) from--;
      if (end < text.length && /[\uDC00-\uDFFF]/.test(text[end]!)) end++;
      progress?.(start, text.length);
      const window = text.slice(from, end);
      const result = await privacyRpc({ op: "scan", text: window, scope: privacyProfile(), idleSeconds: preferences.idleSeconds });
      if (!Array.isArray(result.spans)) throw privacyError("privacy_worker_protocol_failed");
      ranges.push(...convertNativePrivacyRanges(window, result.spans, disabled).map((r) => ({ ...r, start: r.start + from, end: r.end + from })));
    }
    progress?.(text.length, text.length);
    return ranges;
  } catch (error) { await stopPrivacyDaemon(); throw error; }
}
export async function prepareCliMessagePrivacy(text: string, memories: DecryptedMemoryEntry[], existing: PIIMappingGeneric[] = [], scope: PrivacyScope = { kind: "message" }, progress?: (done: number, total: number) => void): Promise<{ message: string; mappings: Array<{ original: string; placeholder: string; type: string }> }> {
  const options = privacyDetectionOptions(memories); let mappings = existing;
  const privacy = new ProjectFilePrivacy({ ...options, preserveMappedTokens: true, mappings: existing, save: async (value) => { mappings = value; },
    detectEnhanced: (value) => scanEnhancedText(value, scope, options.detection.disabledCategories, progress),
  });
  const message = await privacy.redactResult(text) as string;
  return { message, mappings: mappings.map((mapping) => ({ ...mapping, type: mapping.type ?? "OTHER" })) };
}
