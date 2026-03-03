// frontend/packages/ui/scripts/generate-embed-registry.js
//
// Build script to generate embedRegistry.generated.ts from:
//   1. backend/apps/*/app.yml (embed_types sections)
//   2. shared/config/embed_types.yml (virtual embed types not tied to an app)
//
// This eliminates the "death by a thousand registration points" problem where
// adding a new embed type required manual changes to 12+ files across 15+ locations.
//
// Architecture: docs/architecture/embeds.md
// Pattern follows: generate-apps-metadata.js

import { readFileSync, readdirSync, statSync, writeFileSync } from "fs";
import { join, dirname, resolve } from "path";
import { fileURLToPath } from "url";
import yaml from "yaml";

// Get the directory of this script
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Paths
const BACKEND_APPS_DIR = resolve(__dirname, "../../../../backend/apps");
const SHARED_EMBED_TYPES = resolve(
  __dirname,
  "../../../../shared/config/embed_types.yml",
);
const OUTPUT_FILE = resolve(
  __dirname,
  "../src/data/embedRegistry.generated.ts",
);

/**
 * Collect all embed type definitions from app.yml files.
 * Each entry is enriched with app_id derived from the directory name.
 *
 * @returns {Array<Object>} Flat list of embed type definitions with app_id added
 */
function collectAppEmbedTypes() {
  const embedTypes = [];

  let entries;
  try {
    entries = readdirSync(BACKEND_APPS_DIR, { withFileTypes: true });
  } catch (err) {
    console.error(
      "[generate-embed-registry] Error reading backend/apps directory:",
      err,
    );
    throw err;
  }

  for (const entry of entries) {
    if (!entry.isDirectory()) continue;

    const appId = entry.name;
    const appYmlPath = join(BACKEND_APPS_DIR, appId, "app.yml");

    try {
      if (!statSync(appYmlPath).isFile()) continue;
    } catch {
      continue; // No app.yml for this app
    }

    try {
      const content = readFileSync(appYmlPath, "utf-8");
      const appData = yaml.parse(content);

      if (!appData || !Array.isArray(appData.embed_types)) continue;

      for (const embedDef of appData.embed_types) {
        embedTypes.push({
          ...embedDef,
          app_id: appId,
        });
      }

      if (appData.embed_types.length > 0) {
        console.log(
          `[generate-embed-registry]   ${appId}: ${appData.embed_types.length} embed type(s)`,
        );
      }
    } catch (err) {
      console.warn(
        `[generate-embed-registry] Could not parse ${appId}/app.yml: ${err.message}`,
      );
    }
  }

  return embedTypes;
}

/**
 * Collect virtual embed types from shared/config/embed_types.yml.
 * These are embed types that don't belong to any specific app (e.g., sheets, focus_mode_activation).
 *
 * @returns {Array<Object>} List of virtual embed type definitions (already have app_id in YAML)
 */
function collectVirtualEmbedTypes() {
  try {
    if (!statSync(SHARED_EMBED_TYPES).isFile()) return [];
  } catch {
    console.warn(
      "[generate-embed-registry] shared/config/embed_types.yml not found, skipping virtual types",
    );
    return [];
  }

  try {
    const content = readFileSync(SHARED_EMBED_TYPES, "utf-8");
    const data = yaml.parse(content);

    if (!data || !Array.isArray(data.embed_types)) return [];

    console.log(
      `[generate-embed-registry]   [virtual]: ${data.embed_types.length} embed type(s)`,
    );
    return data.embed_types;
  } catch (err) {
    console.warn(
      `[generate-embed-registry] Could not parse embed_types.yml: ${err.message}`,
    );
    return [];
  }
}

/**
 * Build the backend-to-frontend type normalization map.
 * This replaces the hand-maintained maps in embedParsing.ts and embedStore.ts.
 *
 * @param {Array<Object>} allEmbedTypes - All embed type definitions
 * @returns {Record<string, string>} Map from backend_type to frontend_type
 */
function buildTypeNormalizationMap(allEmbedTypes) {
  const typeMap = {};

  for (const def of allEmbedTypes) {
    // Map the backend_type → frontend_type
    if (def.backend_type && def.frontend_type) {
      typeMap[def.backend_type] = def.frontend_type;
    }

    // Also map child backend_type → child frontend_type (for composite embeds)
    if (def.child_type && def.child_frontend_type) {
      typeMap[def.child_type] = def.child_frontend_type;
    }
  }

  return typeMap;
}

/**
 * Build the child embed type resolution map.
 * This replaces the hand-maintained get_child_embed_type() in embed_service.py.
 *
 * @param {Array<Object>} allEmbedTypes - All embed type definitions
 * @returns {Record<string, string>} Map from "app_id:skill_id" to child_type
 */
function buildChildTypeMap(allEmbedTypes) {
  const childMap = {};

  for (const def of allEmbedTypes) {
    if (def.has_children && def.child_type && def.skill_id && def.app_id) {
      const key = `${def.app_id}:${def.skill_id}`;
      childMap[key] = def.child_type;
    }
  }

  return childMap;
}

/**
 * Build the app-skill → component path lookup tables for preview and fullscreen.
 *
 * @param {Array<Object>} allEmbedTypes - All embed type definitions
 * @returns {{ preview: Record<string, string>, fullscreen: Record<string, string> }}
 */
function buildComponentMaps(allEmbedTypes) {
  const preview = {};
  const fullscreen = {};

  for (const def of allEmbedTypes) {
    // For app-skill-use embeds, key is "app:<app_id>:<skill_id>"
    // For direct embeds, key is the frontend_type string
    let key;
    if (def.category === "app-skill-use" && def.app_id && def.skill_id) {
      key = `app:${def.app_id}:${def.skill_id}`;
    } else if (def.category === "direct" && def.frontend_type) {
      key = def.frontend_type;
    } else {
      continue;
    }

    if (def.preview_component) {
      preview[key] = def.preview_component;
    }
    if (def.fullscreen_component && def.fullscreen_component !== "null") {
      fullscreen[key] = def.fullscreen_component;
    }

    // Also register child component paths for composite embeds
    if (def.has_children && def.child_frontend_type) {
      if (def.child_preview_component) {
        preview[def.child_frontend_type] = def.child_preview_component;
      }
      if (def.child_fullscreen_component) {
        fullscreen[def.child_frontend_type] = def.child_fullscreen_component;
      }
    }
  }

  return { preview, fullscreen };
}

/**
 * Build the renderer type map for TipTap embed renderers (embed_renderers/index.ts).
 * Maps frontend_type → renderer class name.
 *
 * @param {Array<Object>} allEmbedTypes - All embed type definitions
 * @returns {Record<string, string>} Map from frontend type to renderer identifier
 */
function buildRendererMap(allEmbedTypes) {
  const rendererMap = {};

  for (const def of allEmbedTypes) {
    const frontendType = def.frontend_type;
    if (!frontendType) continue;

    if (def.category === "app-skill-use" && frontendType === "app-skill-use") {
      // The parent app-skill-use type uses AppSkillUseRenderer (registered once)
      rendererMap["app-skill-use"] = "AppSkillUseRenderer";
    } else if (frontendType === "focus-mode-activation") {
      rendererMap["focus-mode-activation"] = "FocusModeActivationRenderer";
    } else if (frontendType === "image") {
      rendererMap["image"] = "ImageRenderer";
    } else if (frontendType === "pdf") {
      rendererMap["pdf"] = "PdfRenderer";
    } else if (frontendType === "recording") {
      rendererMap["recording"] = "RecordingRenderer";
    } else if (frontendType === "maps") {
      rendererMap["maps"] = "MapLocationRenderer";
    } else if (frontendType === "math-plot") {
      rendererMap["math-plot"] = "MathPlotRenderer";
    } else {
      // Most types (web-website, videos-video, code-code, etc.) use GroupRenderer
      rendererMap[frontendType] = "GroupRenderer";
    }

    // Also add child type → GroupRenderer for composite embeds
    if (def.has_children && def.child_frontend_type) {
      if (!rendererMap[def.child_frontend_type]) {
        rendererMap[def.child_frontend_type] = "GroupRenderer";
      }
    }

    // Add -group variants for groupable types
    if (def.groupable && frontendType !== "app-skill-use") {
      rendererMap[`${frontendType}-group`] = "GroupRenderer";
    }
    if (
      def.has_children &&
      def.child_frontend_type &&
      def.child_frontend_type !== "app-skill-use"
    ) {
      // Child types of composite embeds are always groupable
      rendererMap[`${def.child_frontend_type}-group`] = "GroupRenderer";
    }
  }

  // app-skill-use group always exists
  rendererMap["app-skill-use-group"] = "GroupRenderer";

  return rendererMap;
}

/**
 * Build the icon and gradient map for embed types.
 *
 * @param {Array<Object>} allEmbedTypes - All embed type definitions
 * @returns {Record<string, { icon: string, gradient_var: string }>}
 */
function buildEmbedMetadataMap(allEmbedTypes) {
  const metadataMap = {};

  for (const def of allEmbedTypes) {
    let key;
    if (def.category === "app-skill-use" && def.app_id && def.skill_id) {
      key = `app:${def.app_id}:${def.skill_id}`;
    } else if (def.category === "direct" && def.frontend_type) {
      key = def.frontend_type;
    } else {
      continue;
    }

    metadataMap[key] = {};
    if (def.icon) metadataMap[key].icon = def.icon;
    if (def.gradient_var) metadataMap[key].gradientVar = def.gradient_var;
    if (def.i18n_namespace) metadataMap[key].i18nNamespace = def.i18n_namespace;
    if (def.app_id) metadataMap[key].appId = def.app_id;
    if (def.skill_id) metadataMap[key].skillId = def.skill_id;
    if (def.has_children) metadataMap[key].hasChildren = def.has_children;
    if (def.child_frontend_type)
      metadataMap[key].childFrontendType = def.child_frontend_type;
  }

  return metadataMap;
}

/**
 * Build the groupable types set for the TipTap editor.
 *
 * @param {Array<Object>} allEmbedTypes - All embed type definitions
 * @returns {string[]} List of frontend_type strings that are groupable
 */
function buildGroupableTypes(allEmbedTypes) {
  const groupable = new Set();

  for (const def of allEmbedTypes) {
    if (def.groupable && def.frontend_type) {
      groupable.add(def.frontend_type);
    }
    // Child types of composite embeds with groupable parent are also groupable
    if (def.has_children && def.child_frontend_type) {
      groupable.add(def.child_frontend_type);
    }
  }

  return [...groupable].sort();
}

/**
 * Map a YAML field type to a TypeScript type string.
 *
 * @param {string} yamlType - The YAML type (string, number, boolean, array, object)
 * @returns {string} TypeScript type annotation
 */
function mapFieldType(yamlType) {
  switch (yamlType) {
    case "string":
      return "string";
    case "number":
      return "number";
    case "boolean":
      return "boolean";
    case "array":
      return "unknown[]";
    case "object":
      return "Record<string, unknown>";
    default:
      return "unknown";
  }
}

/**
 * Convert a kebab-case or snake_case embed type ID to PascalCase for TypeScript interface names.
 * Examples: "web-website" → "WebWebsite", "code_code" → "CodeCode", "focus-mode-activation" → "FocusModeActivation"
 *
 * @param {string} str - Input string
 * @returns {string} PascalCase string
 */
function toPascalCase(str) {
  return str
    .split(/[-_]/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join("");
}

/**
 * Build TypeScript interface declarations from content_fields definitions in embed types.
 * Each embed type with content_fields produces an interface like:
 *   export interface CodeCodeEmbedContent { language: string; code: string; ... }
 *
 * Child content fields (from composite embeds) produce a separate interface.
 *
 * @param {Array<Object>} allEmbedTypes - All embed type definitions
 * @returns {{ interfaces: string[], interfaceCount: number }}
 */
function buildContentTypeInterfaces(allEmbedTypes) {
  const interfaces = [];
  let count = 0;

  for (const def of allEmbedTypes) {
    // Generate interface for the main embed type's content_fields
    if (Array.isArray(def.content_fields) && def.content_fields.length > 0) {
      const typeName =
        def.category === "app-skill-use" && def.app_id && def.skill_id
          ? toPascalCase(`${def.app_id}-${def.skill_id}`)
          : def.frontend_type
            ? toPascalCase(def.frontend_type)
            : toPascalCase(def.id);

      const interfaceName = `${typeName}EmbedContent`;
      const lines = [];
      lines.push(
        `/** Content fields for ${def.app_id || ""}:${def.id || def.frontend_type} embeds (finished state). */`,
      );
      lines.push(`export interface ${interfaceName} {`);

      // Always include base fields present in all embeds
      lines.push(`  /** App identifier */`);
      lines.push(`  app_id: string;`);
      lines.push(`  /** Skill identifier */`);
      lines.push(`  skill_id: string;`);
      lines.push(`  /** Embed status */`);
      lines.push(`  status: string;`);

      for (const field of def.content_fields) {
        const tsType = mapFieldType(field.type);
        const optional = field.required ? "" : "?";
        if (field.description) {
          lines.push(`  /** ${field.description} */`);
        }
        lines.push(`  ${field.name}${optional}: ${tsType};`);
      }

      // Allow additional dynamic fields (TOON content is loosely typed)
      lines.push(`  [key: string]: unknown;`);
      lines.push(`}`);
      interfaces.push(lines.join("\n"));
      count++;
    }

    // Generate interface for child content fields (composite embeds)
    if (
      Array.isArray(def.child_content_fields) &&
      def.child_content_fields.length > 0 &&
      def.child_frontend_type
    ) {
      const childTypeName = toPascalCase(def.child_frontend_type);
      const interfaceName = `${childTypeName}EmbedContent`;
      const lines = [];
      lines.push(
        `/** Content fields for ${def.child_frontend_type} child embeds. */`,
      );
      lines.push(`export interface ${interfaceName} {`);

      for (const field of def.child_content_fields) {
        const tsType = mapFieldType(field.type);
        const optional = field.required ? "" : "?";
        if (field.description) {
          lines.push(`  /** ${field.description} */`);
        }
        lines.push(`  ${field.name}${optional}: ${tsType};`);
      }

      lines.push(`  [key: string]: unknown;`);
      lines.push(`}`);
      interfaces.push(lines.join("\n"));
      count++;
    }
  }

  return { interfaces, interfaceCount: count };
}

/**
 * Generate the TypeScript output file.
 *
 * @param {Object} maps - All generated maps
 * @returns {string} TypeScript source code
 */
function generateTypeScript(maps) {
  const {
    typeNormalizationMap,
    childTypeMap,
    componentMaps,
    rendererMap,
    embedMetadataMap,
    groupableTypes,
    contentTypeInterfaces,
    totalCount,
  } = maps;

  const lines = [];

  // Header
  lines.push(`// frontend/packages/ui/src/data/embedRegistry.generated.ts`);
  lines.push(`//`);
  lines.push(
    `// ⚠️  WARNING: THIS FILE IS AUTO-GENERATED — DO NOT EDIT MANUALLY ⚠️`,
  );
  lines.push(`//`);
  lines.push(
    `// Generated from backend app.yml files and shared/config/embed_types.yml`,
  );
  lines.push(`// by: frontend/packages/ui/scripts/generate-embed-registry.js`);
  lines.push(`//`);
  lines.push(
    `// To add a new embed type, add an entry to the relevant app.yml`,
  );
  lines.push(`// under the embed_types section, then rebuild.`);
  lines.push(`//`);
  lines.push(`// Generated: ${new Date().toISOString()}`);
  lines.push(`// Total embed types: ${totalCount}`);
  lines.push(``);

  // Type normalization map (backend_type → frontend_type)
  lines.push(`/**`);
  lines.push(
    ` * Maps server/backend embed type strings to frontend type strings.`,
  );
  lines.push(
    ` * Used by embedParsing.ts (mapEmbedReferenceType) and embedStore.ts (normalizeEmbedType).`,
  );
  lines.push(` *`);
  lines.push(
    ` * Example: "app_skill_use" → "app-skill-use", "website" → "web-website"`,
  );
  lines.push(` */`);
  lines.push(
    `export const EMBED_TYPE_NORMALIZATION_MAP: Record<string, string> = ${JSON.stringify(typeNormalizationMap, null, 2)};`,
  );
  lines.push(``);

  // Child type map (app_id:skill_id → child_type)
  lines.push(`/**`);
  lines.push(
    ` * Maps "app_id:skill_id" to the canonical child embed type string.`,
  );
  lines.push(
    ` * Used to determine the type for individual results within composite embeds.`,
  );
  lines.push(` *`);
  lines.push(` * Example: "web:search" → "website", "maps:search" → "place"`);
  lines.push(` */`);
  lines.push(
    `export const EMBED_CHILD_TYPE_MAP: Record<string, string> = ${JSON.stringify(childTypeMap, null, 2)};`,
  );
  lines.push(``);

  // Preview component paths
  lines.push(`/**`);
  lines.push(` * Maps embed registry keys to preview component import paths.`);
  lines.push(
    ` * Keys use "app:<appId>:<skillId>" for app-skill-use, or frontend_type for direct.`,
  );
  lines.push(` * Paths are relative to the components/embeds/ directory.`);
  lines.push(` */`);
  lines.push(
    `export const EMBED_PREVIEW_COMPONENTS: Record<string, string> = ${JSON.stringify(componentMaps.preview, null, 2)};`,
  );
  lines.push(``);

  // Fullscreen component paths
  lines.push(`/**`);
  lines.push(
    ` * Maps embed registry keys to fullscreen component import paths.`,
  );
  lines.push(
    ` * Keys use "app:<appId>:<skillId>" for app-skill-use, or frontend_type for direct.`,
  );
  lines.push(` */`);
  lines.push(
    `export const EMBED_FULLSCREEN_COMPONENTS: Record<string, string> = ${JSON.stringify(componentMaps.fullscreen, null, 2)};`,
  );
  lines.push(``);

  // Renderer map
  lines.push(`/**`);
  lines.push(
    ` * Maps frontend embed type strings to TipTap renderer class identifiers.`,
  );
  lines.push(
    ` * Used by embed_renderers/index.ts to build the renderer registry.`,
  );
  lines.push(` */`);
  lines.push(
    `export const EMBED_RENDERER_MAP: Record<string, string> = ${JSON.stringify(rendererMap, null, 2)};`,
  );
  lines.push(``);

  // Embed metadata map
  lines.push(`/**`);
  lines.push(
    ` * Per-embed-type metadata: icon, gradient CSS var, i18n namespace, etc.`,
  );
  lines.push(
    ` * Keys use "app:<appId>:<skillId>" for app-skill-use, or frontend_type for direct.`,
  );
  lines.push(` */`);
  lines.push(`export interface EmbedTypeMetadata {`);
  lines.push(`  icon?: string;`);
  lines.push(`  gradientVar?: string;`);
  lines.push(`  i18nNamespace?: string;`);
  lines.push(`  appId?: string;`);
  lines.push(`  skillId?: string;`);
  lines.push(`  hasChildren?: boolean;`);
  lines.push(`  childFrontendType?: string;`);
  lines.push(`}`);
  lines.push(``);
  lines.push(
    `export const EMBED_METADATA: Record<string, EmbedTypeMetadata> = ${JSON.stringify(embedMetadataMap, null, 2)};`,
  );
  lines.push(``);

  // Groupable types
  lines.push(`/**`);
  lines.push(
    ` * Frontend type strings that can be grouped in the TipTap editor.`,
  );
  lines.push(` */`);
  lines.push(
    `export const EMBED_GROUPABLE_TYPES: string[] = ${JSON.stringify(groupableTypes, null, 2)};`,
  );
  lines.push(``);

  // Content Type Contracts — TypeScript interfaces generated from content_fields in app.yml
  if (contentTypeInterfaces && contentTypeInterfaces.interfaces.length > 0) {
    lines.push(
      `// ── Content Type Contracts ─────────────────────────────────────────────`,
    );
    lines.push(
      `// Generated from content_fields and child_content_fields in app.yml.`,
    );
    lines.push(
      `// Use these interfaces for type-safe access to decoded embed content.`,
    );
    lines.push(
      `// Example: const content = decodedContent as WebSearchEmbedContent;`,
    );
    lines.push(``);
    for (const iface of contentTypeInterfaces.interfaces) {
      lines.push(iface);
      lines.push(``);
    }
  }

  // Utility function: normalizeEmbedType
  lines.push(`/**`);
  lines.push(
    ` * Normalize a server/backend embed type string to its frontend equivalent.`,
  );
  lines.push(
    ` * Drop-in replacement for the manual switch/map in embedStore.ts and embedParsing.ts.`,
  );
  lines.push(` */`);
  lines.push(
    `export function normalizeEmbedType(backendType: string): string {`,
  );
  lines.push(
    `  return EMBED_TYPE_NORMALIZATION_MAP[backendType] ?? backendType;`,
  );
  lines.push(`}`);
  lines.push(``);

  // Utility function: getChildEmbedType
  lines.push(`/**`);
  lines.push(
    ` * Get the canonical child embed type for a composite embed's app_id + skill_id.`,
  );
  lines.push(
    ` * Returns "website" as default (matches existing backend behavior).`,
  );
  lines.push(` */`);
  lines.push(
    `export function getChildEmbedType(appId: string, skillId: string): string {`,
  );
  lines.push(`  const key = \`\${appId}:\${skillId}\`;`);
  lines.push(`  return EMBED_CHILD_TYPE_MAP[key] ?? "website";`);
  lines.push(`}`);
  lines.push(``);

  // Utility function: isGroupableType
  lines.push(`/**`);
  lines.push(
    ` * Check if a frontend embed type can be grouped in the TipTap editor.`,
  );
  lines.push(` */`);
  lines.push(
    `export function isGroupableType(frontendType: string): boolean {`,
  );
  lines.push(`  return EMBED_GROUPABLE_TYPES.includes(frontendType);`);
  lines.push(`}`);
  lines.push(``);

  return lines.join("\n");
}

/**
 * Main entry point.
 */
function main() {
  console.log(
    "[generate-embed-registry] Starting embed registry generation...",
  );
  console.log(
    `[generate-embed-registry] Reading apps from: ${BACKEND_APPS_DIR}`,
  );
  console.log(
    `[generate-embed-registry] Reading virtual types from: ${SHARED_EMBED_TYPES}`,
  );

  // Collect all embed type definitions
  const appEmbedTypes = collectAppEmbedTypes();
  const virtualEmbedTypes = collectVirtualEmbedTypes();
  const allEmbedTypes = [...appEmbedTypes, ...virtualEmbedTypes];

  console.log(
    `[generate-embed-registry] Total: ${allEmbedTypes.length} embed types (${appEmbedTypes.length} from apps, ${virtualEmbedTypes.length} virtual)`,
  );

  // Build all maps
  const typeNormalizationMap = buildTypeNormalizationMap(allEmbedTypes);
  const childTypeMap = buildChildTypeMap(allEmbedTypes);
  const componentMaps = buildComponentMaps(allEmbedTypes);
  const rendererMap = buildRendererMap(allEmbedTypes);
  const embedMetadataMap = buildEmbedMetadataMap(allEmbedTypes);
  const groupableTypes = buildGroupableTypes(allEmbedTypes);
  const contentTypeInterfaces = buildContentTypeInterfaces(allEmbedTypes);

  if (contentTypeInterfaces.interfaceCount > 0) {
    console.log(
      `[generate-embed-registry] Generated ${contentTypeInterfaces.interfaceCount} content type interface(s)`,
    );
  }

  // Generate TypeScript
  const tsCode = generateTypeScript({
    typeNormalizationMap,
    childTypeMap,
    componentMaps,
    rendererMap,
    embedMetadataMap,
    groupableTypes,
    contentTypeInterfaces,
    totalCount: allEmbedTypes.length,
  });

  // Write output
  writeFileSync(OUTPUT_FILE, tsCode, "utf-8");
  console.log(`[generate-embed-registry] Generated: ${OUTPUT_FILE}`);
  console.log(
    `[generate-embed-registry] ✓ Successfully generated registry with ${allEmbedTypes.length} embed types`,
  );
}

// Run
main();
