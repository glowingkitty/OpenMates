/** Reversible, client-owned PII handling at the Project file/model boundary. */
import {
  detectPII, PII_TYPE_TO_CATEGORY, type PIIDetectionOptions, type PIIMappingGeneric,
} from "../components/enter_message/services/piiDetectionService";
import { validateProjectFileMutation, type ProjectFileMutation } from "../utils/projectFileMutationProtocol";

export interface ProjectFilePrivacyOptions {
  detection?: PIIDetectionOptions;
  enabled?: boolean;
  mappings?: PIIMappingGeneric[];
  /** Persist ciphertext locally before exposing any new token to the server/model. */
  save: (mappings: PIIMappingGeneric[]) => Promise<void>;
  /** Optional local semantic classifier, supplied only by capable clients. */
  detectEnhanced?: (text: string) => Promise<Array<{ start: number; end: number; type?: string }>>;
  /** Already-prepared CLI messages contain genuine tokens from these mappings. */
  preserveMappedTokens?: boolean;
}

function fail(code: string): never { throw Object.assign(new Error(code), { code }); }
const TOKEN = /\[[A-Za-z][A-Za-z0-9_]*\]/g;
const GENERATED_TOKEN = /^\[OM_PII_[A-F0-9]{32}\]$/;
function legacyToken(token: string): boolean {
  const match = /^\[([A-Z_]+)_\d+_[A-Za-z0-9]{1,3}\]$/.exec(token);
  return Boolean(match && Object.prototype.hasOwnProperty.call(PII_TYPE_TO_CATEGORY, match[1]!));
}

export class ProjectFilePrivacy {
  private readonly values = new Map<string, PIIMappingGeneric>();
  private readonly ambiguous = new Set<string>();
  private readonly conflicts: PIIMappingGeneric[] = [];
  private readonly options: ProjectFilePrivacyOptions;
  private savePending: Promise<void> = Promise.resolve();

  constructor(options: ProjectFilePrivacyOptions) {
    this.options = options;
    this.addMappings(options.mappings ?? []);
  }

  addMappings(mappings: PIIMappingGeneric[]): void {
    for (const mapping of mappings) {
      if (!mapping || typeof mapping.original !== "string" || !mapping.original || typeof mapping.placeholder !== "string"
          || !/^\[[A-Za-z][A-Za-z0-9_]*\]$/.test(mapping.placeholder)) continue;
      const previous = this.values.get(mapping.placeholder);
      if (previous && previous.original !== mapping.original) {
        this.ambiguous.add(mapping.placeholder);
        if (!this.conflicts.some((value) => value.placeholder === mapping.placeholder && value.original === mapping.original)) this.conflicts.push({ ...mapping });
      }
      else this.values.set(mapping.placeholder, { ...mapping });
    }
    if (this.values.size + this.conflicts.length > 10_000) fail("pii_mapping_limit");
  }

  restoreText(text: string): string {
    // One pass: substituted originals are never interpreted as further tokens.
    return text.replace(TOKEN, (token) => {
      if (this.ambiguous.has(token)) fail("pii_mapping_ambiguous");
      const mapping = this.values.get(token);
      const customToken = this.options.detection?.personalDataEntries?.some((entry) =>
        (entry.replaceWith.startsWith("[") ? entry.replaceWith : `[${entry.replaceWith}]`) === token);
      if (!mapping && (GENERATED_TOKEN.test(token) || legacyToken(token) || customToken)) fail("pii_mapping_unavailable");
      return mapping?.original ?? token;
    });
  }

  restoreArguments(arguments_: Record<string, unknown>): Record<string, unknown> {
    const result = { ...arguments_ };
    for (const key of ["path", "query", "glob"]) {
      if (typeof result[key] === "string") result[key] = this.restoreText(result[key] as string);
    }
    return result;
  }

  restoreMutation(mutation: ProjectFileMutation): ProjectFileMutation {
    // Authority fields (operation id and real-file base hash) are never rewritten.
    const result = { ...mutation, path: this.restoreText(mutation.path) };
    if (mutation.content !== undefined) result.content = this.restoreText(mutation.content);
    if (mutation.patch !== undefined) {
      result.patch = mutation.patch.split("\n").map((line) => {
        const restored = this.restoreText(line);
        // File-read tokens preserve line boundaries. Refuse a legacy multiline
        // message token rather than silently changing unified-patch hunk counts.
        if (restored.includes("\n")) fail("pii_multiline_patch_token");
        return restored;
      }).join("\n");
    }
    return validateProjectFileMutation(result);
  }

  private token(original: string, type?: string): string {
    for (const [token, mapping] of Array.from(this.values)) {
      if (!this.ambiguous.has(token) && mapping.original === original) return token;
    }
    let placeholder: string;
    do { placeholder = `[OM_PII_${crypto.randomUUID().replace(/-/g, "").toUpperCase()}]`; }
    while (this.values.has(placeholder));
    this.addMappings([{ placeholder, original, type }]);
    return placeholder;
  }

  redactText(text: string, enhanced: Array<{ start: number; end: number; type?: string }> = []): string {
    const ranges: Array<{ start: number; end: number; type?: string }> = [];
    // Input here is original file/proposal text. Shield literal token spellings
    // that collide with known mappings; one-pass restoration preserves them.
    const tokens = Array.from(text.matchAll(TOKEN)).map((match) => ({ start: match.index!, end: match.index! + match[0].length }));
    for (const range of tokens) {
      const literal = text.slice(range.start, range.end);
      if (!(this.options.preserveMappedTokens && this.values.has(literal))
          && (this.values.has(literal) || GENERATED_TOKEN.test(literal) || legacyToken(literal))) ranges.push(range);
    }
    const overlaps = (start: number, end: number) => [...tokens, ...ranges].some((r) => start < r.end && end > r.start);
    // Known values are matched exactly, so restoration preserves original case.
    for (const mapping of Array.from(this.values.values()).sort((a, b) => b.original.length - a.original.length)) {
      let start = text.indexOf(mapping.original);
      while (start !== -1) {
        const end = start + mapping.original.length;
        if (!overlaps(start, end)) ranges.push({ start, end, type: mapping.type });
        start = text.indexOf(mapping.original, end);
      }
    }
    if (this.options.enabled !== false) {
      for (const match of detectPII(text, this.options.detection)) {
        if (!overlaps(match.startIndex, match.endIndex)) ranges.push({ start: match.startIndex, end: match.endIndex, type: match.type });
      }
      for (const range of enhanced) {
        if (!Number.isInteger(range.start) || !Number.isInteger(range.end) || range.start < 0 || range.end <= range.start || range.end > text.length) fail("pii_invalid_semantic_range");
        // Preserve deterministic precedence without losing the uncovered suffix
        // of a broader semantic match (e.g. configured first name + surname).
        let fragments = [{ ...range }];
        for (const shield of [...tokens, ...ranges]) fragments = fragments.flatMap((part) => {
          if (part.start >= shield.end || part.end <= shield.start) return [part];
          return [part.start < shield.start ? { ...part, end: shield.start } : null,
            part.end > shield.end ? { ...part, start: shield.end } : null].filter((part): part is typeof range => part !== null);
        });
        ranges.push(...fragments);
      }
    }
    let cursor = 0;
    let result = "";
    for (const range of ranges.sort((a, b) => a.start - b.start)) {
      result += text.slice(cursor, range.start);
      // Keep CR/LF and source line numbers intact even for PEM/multiline values.
      result += text.slice(range.start, range.end).split(/(\r?\n)/)
        .map((part) => !part || /^(?:\r?\n)$/.test(part) ? part : this.token(part, range.type)).join("");
      cursor = range.end;
    }
    return result + text.slice(cursor);
  }

  async redactResult(value: unknown): Promise<unknown> {
    const visit = async (item: unknown): Promise<unknown> => {
      if (typeof item === "string") return this.redactText(item, this.options.enabled !== false && this.options.detectEnhanced ? await this.options.detectEnhanced(item) : []);
      if (Array.isArray(item)) { const result = []; for (const child of item) result.push(await visit(child)); return result; }
      if (item && typeof item === "object") {
        const result: Record<string, unknown> = {};
        for (const [key, child] of Object.entries(item)) {
        // These are protocol commitments, not content. Preserve their exact bytes.
          result[key] = ["expected_base", "content_hash", "proposal_commitment"].includes(key) ? child : await visit(child);
        }
        return result;
      }
      return item;
    };
    const result = await visit(value);
    const save = this.savePending.catch(() => {}).then(() => this.options.save([...Array.from(this.values.values()), ...this.conflicts]));
    this.savePending = save;
    await save;
    return result;
  }
}
