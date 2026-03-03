/**
 * frontend/packages/ui/src/data/__tests__/embedRegistry.test.ts
 *
 * Embed Registry Validation Tests — CI gate ensuring the generated embed registry
 * stays consistent with component files on disk and the backend state machine.
 * Every new embed type must pass these checks before merging.
 *
 * Architecture: docs/architecture/embeds.md
 *
 * What this file validates:
 *   1. Every registered preview/fullscreen component path resolves to an actual .svelte file
 *   2. Backend and frontend state machines have identical statuses and transitions
 *   3. Required metadata fields are present for every embed type
 *   4. Registry maps are internally consistent (no dangling references)
 *   5. The code generator script runs without errors
 */

import { describe, it, expect } from "vitest";
import { existsSync, readFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";
import { execSync } from "child_process";

// ── Generated registry imports ──────────────────────────────────────────────
import {
  EMBED_TYPE_NORMALIZATION_MAP,
  EMBED_CHILD_TYPE_MAP,
  EMBED_PREVIEW_COMPONENTS,
  EMBED_FULLSCREEN_COMPONENTS,
  EMBED_RENDERER_MAP,
  EMBED_METADATA,
  EMBED_GROUPABLE_TYPES,
  normalizeEmbedType,
  getChildEmbedType,
  isGroupableType,
} from "../embedRegistry.generated";

// ── Frontend state machine imports ──────────────────────────────────────────
import {
  EmbedStatus,
  TERMINAL_STATUSES,
  isValidEmbedStatus,
  validateEmbedTransition,
  isTerminalStatus,
  normalizeEmbedStatus,
} from "../../services/embedStateMachine";

// ── Path resolution ─────────────────────────────────────────────────────────
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

/** Root of the embeds component directory */
const EMBEDS_DIR = resolve(__dirname, "../../components/embeds");

/** Root of the project (frontend/packages/ui) */
const UI_PACKAGE_ROOT = resolve(__dirname, "../../../");

/** Root of the entire project */
const PROJECT_ROOT = resolve(UI_PACKAGE_ROOT, "../../../");

// ═══════════════════════════════════════════════════════════════════════════
// Section 1: Component File Existence
// ═══════════════════════════════════════════════════════════════════════════

describe("Embed Registry — component files exist on disk", () => {
  it("every registered preview component path resolves to a real .svelte file", () => {
    const missing: string[] = [];

    for (const [key, relativePath] of Object.entries(
      EMBED_PREVIEW_COMPONENTS,
    )) {
      const fullPath = resolve(EMBEDS_DIR, relativePath);
      if (!existsSync(fullPath)) {
        missing.push(`[${key}] → ${relativePath} (expected at ${fullPath})`);
      }
    }

    expect(
      missing,
      `Missing preview component files:\n${missing.join("\n")}`,
    ).toHaveLength(0);
  });

  it("every registered fullscreen component path resolves to a real .svelte file", () => {
    const missing: string[] = [];

    for (const [key, relativePath] of Object.entries(
      EMBED_FULLSCREEN_COMPONENTS,
    )) {
      const fullPath = resolve(EMBEDS_DIR, relativePath);
      if (!existsSync(fullPath)) {
        missing.push(`[${key}] → ${relativePath} (expected at ${fullPath})`);
      }
    }

    expect(
      missing,
      `Missing fullscreen component files:\n${missing.join("\n")}`,
    ).toHaveLength(0);
  });

  it("every embed type with a preview also has a fullscreen (except virtual types)", () => {
    // focus-mode-activation is intentionally preview-only (no fullscreen)
    const PREVIEW_ONLY_ALLOWLIST = new Set(["focus-mode-activation"]);
    const mismatched: string[] = [];

    for (const key of Object.keys(EMBED_PREVIEW_COMPONENTS)) {
      if (PREVIEW_ONLY_ALLOWLIST.has(key)) continue;
      if (!EMBED_FULLSCREEN_COMPONENTS[key]) {
        mismatched.push(
          `[${key}] has preview but no fullscreen component registered`,
        );
      }
    }

    expect(
      mismatched,
      `Preview/fullscreen mismatch:\n${mismatched.join("\n")}`,
    ).toHaveLength(0);
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 2: Backend ↔ Frontend State Machine Parity
// ═══════════════════════════════════════════════════════════════════════════

describe("Embed State Machine — backend/frontend parity", () => {
  /** Read the Python state machine source and extract status values + transitions. */
  function parseBackendStateMachine(): {
    statuses: string[];
    transitions: Record<string, string[]>;
    terminalStatuses: string[];
  } {
    const pyPath = resolve(
      PROJECT_ROOT,
      "backend/shared/python_schemas/embed_status.py",
    );
    const content = readFileSync(pyPath, "utf-8");

    // Extract enum values: PROCESSING = "processing" etc.
    const statusRegex = /^\s+(\w+)\s*=\s*"(\w+)"/gm;
    const statuses: string[] = [];
    let match;
    while ((match = statusRegex.exec(content)) !== null) {
      statuses.push(match[2]);
    }

    // Extract ALLOWED_TRANSITIONS keys and their values
    // Pattern: EmbedStatus.X: frozenset({...})
    const transitions: Record<string, string[]> = {};
    const transBlock =
      content.match(/ALLOWED_TRANSITIONS.*?=\s*\{([\s\S]*?)\n\}/)?.[1] ?? "";

    const entryRegex = /EmbedStatus\.(\w+):\s*frozenset\(\{([^}]*)\}\)/g;
    while ((match = entryRegex.exec(transBlock)) !== null) {
      const fromStatus = match[1].toLowerCase();
      const targets = match[2]
        .split(",")
        .map((s) => {
          const m = s.match(/EmbedStatus\.(\w+)/);
          return m ? m[1].toLowerCase() : null;
        })
        .filter((s): s is string => s !== null)
        .sort();
      // Map enum name to value (they happen to match: PROCESSING → processing)
      transitions[fromStatus] = targets;
    }

    // Extract TERMINAL_STATUSES
    const termBlock =
      content.match(/TERMINAL_STATUSES.*?frozenset\(\{([\s\S]*?)\}\)/)?.[1] ??
      "";
    const terminalStatuses: string[] = [];
    const termRegex = /EmbedStatus\.(\w+)/g;
    let termMatch;
    while ((termMatch = termRegex.exec(termBlock)) !== null) {
      terminalStatuses.push(termMatch[1].toLowerCase());
    }
    terminalStatuses.sort();

    return { statuses, transitions, terminalStatuses };
  }

  it("frontend EmbedStatus enum has the same values as backend", () => {
    const backend = parseBackendStateMachine();
    const frontendValues = Object.values(EmbedStatus).sort();
    const backendValues = [...backend.statuses].sort();

    expect(frontendValues).toEqual(backendValues);
  });

  it("frontend ALLOWED_TRANSITIONS matches backend transitions", () => {
    const backend = parseBackendStateMachine();

    // Verify every backend transition is also valid on frontend
    for (const [from, targets] of Object.entries(backend.transitions)) {
      for (const target of targets) {
        expect(
          validateEmbedTransition(from, target, "test"),
          `Backend allows ${from} → ${target}, but frontend rejects it`,
        ).toBe(true);
      }
    }

    // Verify frontend doesn't allow transitions the backend doesn't
    const frontendStatuses = Object.values(EmbedStatus);
    for (const from of frontendStatuses) {
      for (const to of frontendStatuses) {
        const backendAllows = backend.transitions[from]?.includes(to) ?? false;
        const frontendAllows = validateEmbedTransition(from, to, "test");

        if (frontendAllows && !backendAllows) {
          // This is acceptable only if both sides agree — currently they should match
          expect.fail(`Frontend allows ${from} → ${to} but backend does not`);
        }
      }
    }
  });

  it("frontend TERMINAL_STATUSES matches backend", () => {
    const backend = parseBackendStateMachine();
    const frontendTerminal = Array.from(TERMINAL_STATUSES).sort();
    expect(frontendTerminal).toEqual(backend.terminalStatuses);
  });

  it("normalizeEmbedStatus handles known aliases", () => {
    // "completed" → "finished"
    expect(normalizeEmbedStatus("completed")).toBe(EmbedStatus.FINISHED);
    // null/undefined → "finished"
    expect(normalizeEmbedStatus(null)).toBe(EmbedStatus.FINISHED);
    expect(normalizeEmbedStatus(undefined)).toBe(EmbedStatus.FINISHED);
    // Valid statuses pass through
    expect(normalizeEmbedStatus("processing")).toBe(EmbedStatus.PROCESSING);
    expect(normalizeEmbedStatus("error")).toBe(EmbedStatus.ERROR);
    expect(normalizeEmbedStatus("cancelled")).toBe(EmbedStatus.CANCELLED);
  });

  it("isTerminalStatus correctly identifies terminal vs non-terminal", () => {
    expect(isTerminalStatus("finished")).toBe(true);
    expect(isTerminalStatus("error")).toBe(true);
    expect(isTerminalStatus("cancelled")).toBe(true);
    expect(isTerminalStatus("processing")).toBe(false);
    expect(isTerminalStatus("unknown")).toBe(false);
  });

  it("isValidEmbedStatus rejects unknown values", () => {
    expect(isValidEmbedStatus("processing")).toBe(true);
    expect(isValidEmbedStatus("finished")).toBe(true);
    expect(isValidEmbedStatus("completed")).toBe(false); // alias, not a valid status
    expect(isValidEmbedStatus("")).toBe(false);
    expect(isValidEmbedStatus(null)).toBe(false);
    expect(isValidEmbedStatus(42)).toBe(false);
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 3: Registry Metadata Completeness
// ═══════════════════════════════════════════════════════════════════════════

describe("Embed Registry — metadata completeness", () => {
  it("every embed type in EMBED_METADATA has required fields", () => {
    const REQUIRED_FIELDS = ["icon", "gradientVar", "i18nNamespace"] as const;
    const incomplete: string[] = [];

    for (const [key, meta] of Object.entries(EMBED_METADATA)) {
      for (const field of REQUIRED_FIELDS) {
        if (!meta[field]) {
          incomplete.push(`[${key}] missing '${field}'`);
        }
      }
    }

    expect(
      incomplete,
      `Incomplete metadata entries:\n${incomplete.join("\n")}`,
    ).toHaveLength(0);
  });

  it("every app-skill-use type in EMBED_METADATA has appId and skillId", () => {
    const missing: string[] = [];

    for (const [key, meta] of Object.entries(EMBED_METADATA)) {
      if (key.startsWith("app:")) {
        if (!meta.appId) missing.push(`[${key}] missing 'appId'`);
        if (!meta.skillId) missing.push(`[${key}] missing 'skillId'`);
      }
    }

    expect(
      missing,
      `app-skill-use types missing appId/skillId:\n${missing.join("\n")}`,
    ).toHaveLength(0);
  });

  it("every composite embed type has hasChildren and childFrontendType", () => {
    const missing: string[] = [];

    for (const [key, meta] of Object.entries(EMBED_METADATA)) {
      if (meta.hasChildren && !meta.childFrontendType) {
        missing.push(`[${key}] has hasChildren=true but no childFrontendType`);
      }
    }

    expect(
      missing,
      `Composite types with missing childFrontendType:\n${missing.join("\n")}`,
    ).toHaveLength(0);
  });

  it("EMBED_CHILD_TYPE_MAP entries correspond to composite embed metadata", () => {
    const orphaned: string[] = [];

    for (const [compositeKey] of Object.entries(EMBED_CHILD_TYPE_MAP)) {
      const [appId, skillId] = compositeKey.split(":");
      const metaKey = `app:${appId}:${skillId}`;
      const meta = EMBED_METADATA[metaKey];

      if (!meta) {
        orphaned.push(
          `EMBED_CHILD_TYPE_MAP has '${compositeKey}' but no matching EMBED_METADATA entry '${metaKey}'`,
        );
      } else if (!meta.hasChildren) {
        orphaned.push(
          `EMBED_CHILD_TYPE_MAP has '${compositeKey}' but EMBED_METADATA['${metaKey}'].hasChildren is not true`,
        );
      }
    }

    expect(
      orphaned,
      `Orphaned EMBED_CHILD_TYPE_MAP entries:\n${orphaned.join("\n")}`,
    ).toHaveLength(0);
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 4: Registry Internal Consistency
// ═══════════════════════════════════════════════════════════════════════════

describe("Embed Registry — internal consistency", () => {
  it("every groupable type has a corresponding renderer entry", () => {
    const missing: string[] = [];

    for (const type of EMBED_GROUPABLE_TYPES) {
      if (!EMBED_RENDERER_MAP[type]) {
        missing.push(
          `Groupable type '${type}' has no EMBED_RENDERER_MAP entry`,
        );
      }
      // Group variants (e.g., "code-code-group") should also exist
      const groupKey = `${type}-group`;
      if (!EMBED_RENDERER_MAP[groupKey]) {
        missing.push(
          `Groupable type '${type}' has no group variant '${groupKey}' in EMBED_RENDERER_MAP`,
        );
      }
    }

    expect(
      missing,
      `Groupable types missing renderer entries:\n${missing.join("\n")}`,
    ).toHaveLength(0);
  });

  it("normalizeEmbedType handles all aliases in the normalization map", () => {
    for (const [alias, normalized] of Object.entries(
      EMBED_TYPE_NORMALIZATION_MAP,
    )) {
      expect(normalizeEmbedType(alias)).toBe(normalized);
    }
  });

  it("normalizeEmbedType passes through unknown types unchanged", () => {
    expect(normalizeEmbedType("unknown-type-xyz")).toBe("unknown-type-xyz");
    expect(normalizeEmbedType("app-skill-use")).toBe("app-skill-use");
  });

  it("getChildEmbedType returns correct types for registered composites", () => {
    for (const [compositeKey, childType] of Object.entries(
      EMBED_CHILD_TYPE_MAP,
    )) {
      const [appId, skillId] = compositeKey.split(":");
      expect(getChildEmbedType(appId, skillId)).toBe(childType);
    }
  });

  it("getChildEmbedType defaults to 'website' for unknown composites", () => {
    expect(getChildEmbedType("unknown", "skill")).toBe("website");
  });

  it("isGroupableType correctly identifies groupable types", () => {
    for (const type of EMBED_GROUPABLE_TYPES) {
      expect(isGroupableType(type)).toBe(true);
    }
    expect(isGroupableType("not-a-real-type")).toBe(false);
  });

  it("EMBED_TYPE_NORMALIZATION_MAP identity mappings are only direct-type embeds", () => {
    // Some direct-type embeds (image, math-plot, pdf) have backend type strings
    // that already match the frontend type, so they appear as identity mappings.
    // This is intentional — the map serves as a complete catalogue of all backend
    // type strings. This test ensures that only known direct-type embeds have
    // identity mappings (no accidental app-skill-use duplicates).
    const ALLOWED_IDENTITY_TYPES = new Set(["image", "math-plot", "pdf"]);
    const unexpected: string[] = [];

    for (const [alias, normalized] of Object.entries(
      EMBED_TYPE_NORMALIZATION_MAP,
    )) {
      if (alias === normalized && !ALLOWED_IDENTITY_TYPES.has(alias)) {
        unexpected.push(
          `'${alias}' maps to itself but is not in the allowed identity set`,
        );
      }
    }

    expect(
      unexpected,
      `Unexpected identity mappings:\n${unexpected.join("\n")}`,
    ).toHaveLength(0);
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// Section 5: Code Generator Integrity
// ═══════════════════════════════════════════════════════════════════════════

describe("Embed Registry — code generator", () => {
  it("generate-embed-registry.js runs without errors", () => {
    const scriptPath = resolve(
      UI_PACKAGE_ROOT,
      "scripts/generate-embed-registry.js",
    );

    // Run the generator in dry-run mode (write to /dev/null) to verify it parses all YAML correctly
    // We redirect stdout to suppress the output, and check the exit code
    expect(() => {
      execSync(`node ${scriptPath}`, {
        cwd: UI_PACKAGE_ROOT,
        timeout: 30_000,
        stdio: ["pipe", "pipe", "pipe"],
      });
    }).not.toThrow();
  });

  it("generated file has a timestamp header", () => {
    const content = readFileSync(
      resolve(UI_PACKAGE_ROOT, "src/data/embedRegistry.generated.ts"),
      "utf-8",
    );

    expect(content).toContain("WARNING: THIS FILE IS AUTO-GENERATED");
    expect(content).toMatch(/Generated: \d{4}-\d{2}-\d{2}T/);
    expect(content).toMatch(/Total embed types: \d+/);
  });
});
