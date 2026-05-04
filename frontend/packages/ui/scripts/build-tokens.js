// frontend/packages/ui/scripts/build-tokens.js
//
// Build script to generate design tokens from YAML source files.
// Reads src/tokens/sources/*.yml and produces:
//   - src/tokens/generated/theme.generated.css   (CSS custom properties)
//   - src/tokens/generated/tokens.generated.ts    (TypeScript constants)
//   - src/tokens/generated/swift/*.generated.swift (Swift extensions)
//   - src/tokens/generated/swift/Assets.xcassets/  (Xcode color catalog)
//
// This is the single source of truth for all visual tokens across web and
// native platforms. The generated CSS must produce identical custom properties
// to the current theme.css and fonts.css for backwards compatibility.
//
// **Usage**: Run automatically via the "prepare" / "prebuild" npm scripts.
//            Run with --verify to diff against current theme.css/fonts.css.

import { readFileSync, writeFileSync, existsSync, mkdirSync, readdirSync, copyFileSync } from "fs";
import { dirname, resolve, basename } from "path";
import { fileURLToPath } from "url";
import YAML from "yaml";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// ── Paths ──────────────────────────────────────────────────────────────────
const SOURCES_DIR = resolve(__dirname, "../src/tokens/sources");
const GENERATED_DIR = resolve(__dirname, "../src/tokens/generated");
const SWIFT_DIR = resolve(GENERATED_DIR, "swift");
const XCASSETS_DIR = resolve(SWIFT_DIR, "Assets.xcassets");
const CSS_OUTPUT = resolve(GENERATED_DIR, "theme.generated.css");
const TS_OUTPUT = resolve(GENERATED_DIR, "tokens.generated.ts");
const ICONS_DIR = resolve(__dirname, "../static/icons");
const ICONS_XCASSETS_DIR = resolve(SWIFT_DIR, "Icons.xcassets");
const BRAND_FAVICON_PNG = resolve(__dirname, "../static/favicon.png");
const COMPONENTS_DIR = resolve(SOURCES_DIR, "components");
const COMPONENT_CSS_OUTPUT = resolve(GENERATED_DIR, "component-classes.generated.css");
const COMPONENT_SWIFT_OUTPUT = resolve(SWIFT_DIR, "ComponentTokens.generated.swift");

// ── Helpers ────────────────────────────────────────────────────────────────

/** Read and parse a YAML source file. */
function readYaml(filename) {
  const path = resolve(SOURCES_DIR, filename);
  if (!existsSync(path)) {
    console.error(`[build-tokens] Source file not found: ${path}`);
    process.exit(1);
  }
  return YAML.parse(readFileSync(path, "utf-8"));
}

/** Convert kebab-case to camelCase. */
function camelCase(str) {
  return str.replace(/-([a-z0-9])/g, (_, c) => c.toUpperCase());
}

/** Convert kebab-case to PascalCase. */
function pascalCase(str) {
  const cc = camelCase(str);
  return cc.charAt(0).toUpperCase() + cc.slice(1);
}

/** Ensure a directory exists. */
function ensureDir(dir) {
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true });
  }
}

/** Hex string to RGB components for xcassets. */
function hexToRgb(hex) {
  hex = hex.replace("#", "");
  if (hex.length === 3) hex = hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2];
  return {
    r: parseInt(hex.slice(0, 2), 16) / 255,
    g: parseInt(hex.slice(2, 4), 16) / 255,
    b: parseInt(hex.slice(4, 6), 16) / 255
  };
}

// ── CSS Generation ─────────────────────────────────────────────────────────

function generateCSS() {
  const colors = readYaml("colors.yml");
  const gradients = readYaml("gradients.yml");
  const typography = readYaml("typography.yml");
  const spacing = readYaml("spacing.yml");
  const radii = readYaml("radii.yml");
  const shadows = readYaml("shadows.yml");
  const zIndex = readYaml("z-index.yml");
  const transitions = readYaml("transitions.yml");
  const icons = readYaml("icons.yml");
  const layout = readYaml("layout.yml");

  const rootLines = [];
  const darkLines = [];

  // ── Layout tokens ──
  rootLines.push("  /* Layout */");
  for (const [name, value] of Object.entries(layout.dimensions || {})) {
    rootLines.push(`  --${name}: ${value}px;`);
  }
  rootLines.push("");

  // ── Icon gradients ──
  rootLines.push("  /* Icon */");
  const std = gradients.standard;
  for (const [name, grad] of Object.entries(gradients.icons || {})) {
    const prefix = `--icon-${name === "default" ? "" : name + "-"}background`;
    if (grad.start_ref) {
      rootLines.push(`  ${prefix}-start: var(--${grad.start_ref});`);
      rootLines.push(`  ${prefix}-end: var(--${grad.end_ref});`);
    } else {
      rootLines.push(`  ${prefix}-start: ${grad.start};`);
      rootLines.push(`  ${prefix}-end: ${grad.end};`);
    }
    rootLines.push(`  ${prefix}: linear-gradient(`);
    rootLines.push(`    ${std.angle},`);
    rootLines.push(`    var(${prefix}-start) ${std.start_stop},`);
    rootLines.push(`    var(${prefix}-end) ${std.end_stop}`);
    rootLines.push(`  );`);
  }
  // Icon border color (references grey-20)
  rootLines.push("  --icon-border-color: var(--color-grey-20);");
  rootLines.push("");

  // ── Primary gradient ──
  rootLines.push("  /* Primary Color */");
  const primary = gradients.primary;
  rootLines.push(`  --color-primary-start: ${primary.start};`);
  rootLines.push(`  --color-primary-end: ${primary.end};`);
  rootLines.push("  --color-primary: linear-gradient(");
  rootLines.push(`    ${std.angle},`);
  rootLines.push(`    var(--color-primary-start) ${std.start_stop},`);
  rootLines.push(`    var(--color-primary-end) ${std.end_stop}`);
  rootLines.push("  );");
  rootLines.push("");

  // ── Font colors ──
  rootLines.push("  /* Font Colors */");
  for (const [name, val] of Object.entries(colors.font || {})) {
    const lightVal = val.light || val.value;
    rootLines.push(`  --color-font-${name}: ${lightVal};`);
    if (val.dark) {
      darkLines.push(`  --color-font-${name}: ${val.dark};`);
    }
  }
  // Bold text uses --color-bold-text (not --color-font-bold) for historical reasons
  const boldText = colors["bold-text"];
  if (boldText) {
    rootLines.push(`  --color-bold-text: ${boldText.light};`);
    if (boldText.dark) {
      darkLines.push(`  --color-bold-text: ${boldText.dark};`);
    }
  }
  rootLines.push("");

  // ── Button colors ──
  rootLines.push("  /* Button Colors */");
  for (const [name, val] of Object.entries(colors.button || {})) {
    rootLines.push(`  --color-button-${name}: ${val.value};`);
  }
  rootLines.push("");

  // ── App card colors ──
  rootLines.push("  /* App Card Colors */");
  for (const [name, val] of Object.entries(colors["app-card"] || {})) {
    rootLines.push(`  --color-app-card-${name}: var(--${val.ref});`);
  }
  rootLines.push("");

  // ── App gradients ──
  rootLines.push("  /* App colors */");
  for (const [name, grad] of Object.entries(gradients.apps || {})) {
    const cssName = name; // preserve underscores as in current theme.css
    rootLines.push("");
    const comment = grad.legacy
      ? `  /* Legacy: Keep --color-app-${cssName} for backwards compatibility */`
      : `  /* App/${pascalCase(name)} */`;
    rootLines.push(comment);
    if (grad.start_ref) {
      rootLines.push(`  --color-app-${cssName}-start: var(--${grad.start_ref});`);
      rootLines.push(`  --color-app-${cssName}-end: var(--${grad.end_ref});`);
    } else {
      rootLines.push(`  --color-app-${cssName}-start: ${grad.start};`);
      rootLines.push(`  --color-app-${cssName}-end: ${grad.end};`);
    }
    rootLines.push(`  --color-app-${cssName}: linear-gradient(`);
    rootLines.push(`    ${std.angle},`);
    rootLines.push(`    var(--color-app-${cssName}-start) ${std.start_stop},`);
    rootLines.push(`    var(--color-app-${cssName}-end) ${std.end_stop}`);
    rootLines.push("  );");

    // Dark mode overrides for specific apps
    if (grad.dark_start || grad.dark_end) {
      darkLines.push(`  /* App/${pascalCase(name)} - dark mode */`);
      if (grad.dark_start) darkLines.push(`  --color-app-${cssName}-start: ${grad.dark_start};`);
      if (grad.dark_end)   darkLines.push(`  --color-app-${cssName}-end: ${grad.dark_end};`);
    }
  }
  rootLines.push("");

  // ── Semantic tokens ──
  rootLines.push("  /* Semantic tokens — error, warning, and UI radii */");
  for (const [name, val] of Object.entries(colors.semantic || {})) {
    rootLines.push(`  --color-${name}: ${val.light};`);
    if (val.dark) {
      darkLines.push(`  --color-${name}: ${val.dark};`);
    }
  }
  // Border radius medium (semantic)
  if (layout.semantic) {
    rootLines.push(`  --border-radius-medium: ${layout.semantic["border-radius-medium"]}px;`);
  }
  rootLines.push("");

  // ── Gradient alias ──
  rootLines.push("  /* Gradient alias for the primary gradient (used in settings links, credits icons, etc.) */");
  rootLines.push("  --gradient-primary: linear-gradient(");
  rootLines.push(`    ${std.angle},`);
  rootLines.push(`    var(--color-primary-start) ${std.start_stop},`);
  rootLines.push(`    var(--color-primary-end) ${std.end_stop}`);
  rootLines.push("  );");
  rootLines.push("");

  // ── Grey scale ──
  rootLines.push("  /* Default theme (light) */");
  for (const [name, val] of Object.entries(colors.grey || {})) {
    rootLines.push(`  --color-grey-${name}: ${val.light};`);
    if (val.dark) {
      darkLines.push(`  --color-grey-${name}: ${val.dark};`);
    }
  }
  rootLines.push("");

  // ── Record audio gradient ──
  rootLines.push("  /* Record Audio */");
  const recordAudio = gradients["record-audio"];
  if (recordAudio) {
    rootLines.push("  --color-record-audio-background: linear-gradient(");
    rootLines.push(`    ${std.angle},`);
    rootLines.push(`    var(--${recordAudio.start_ref}) ${std.start_stop},`);
    rootLines.push(`    var(--${recordAudio.end_ref}) ${std.end_stop}`);
    rootLines.push("  );");
    rootLines.push("");
  }

  // ── Footer gradient ──
  rootLines.push("  /* footer */");
  const footerLight = gradients.footer.light;
  rootLines.push(`  --color-footer-start: ${footerLight.start};`);
  rootLines.push(`  --color-footer-end: ${footerLight.end};`);
  rootLines.push("  --color-footer: linear-gradient(");
  rootLines.push(`    ${std.angle},`);
  rootLines.push(`    var(--color-footer-start) ${std.start_stop},`);
  rootLines.push(`    var(--color-footer-end) ${std.end_stop}`);
  rootLines.push("  );");
  rootLines.push("");

  // Chatcontainer min height mobile
  rootLines.push("  /* Chatcontainer min height mobile */");
  rootLines.push(`  --chat-container-min-height-mobile: ${layout.dimensions["chat-container-min-height-mobile"]}px;`);

  // ── Footer dark mode ──
  const footerDark = gradients.footer.dark;
  darkLines.push("");
  darkLines.push(`  --color-footer-start: ${footerDark.start};`);
  darkLines.push(`  --color-footer-end: ${footerDark.end};`);

  // ── NEW tokens (spacing, radii, shadows, z-index, transitions, icons) ──
  // These are new tokens not in the current theme.css — additive only.
  rootLines.push("");
  rootLines.push("  /* ── Spacing scale ── */");
  for (const [key, value] of Object.entries(spacing.scale || {})) {
    rootLines.push(`  --spacing-${key}: ${value === 0 ? "0" : value + "px"};`);
  }

  rootLines.push("");
  rootLines.push("  /* ── Border radius scale ── */");
  for (const [key, value] of Object.entries(radii.scale || {})) {
    rootLines.push(`  --radius-${key}: ${value}px;`);
  }

  rootLines.push("");
  rootLines.push("  /* ── Shadow presets ── */");
  for (const [key, value] of Object.entries(shadows.presets || {})) {
    rootLines.push(`  --shadow-${key}: ${value};`);
  }

  rootLines.push("");
  rootLines.push("  /* ── Z-index layers ── */");
  for (const [key, value] of Object.entries(zIndex.layers || {})) {
    rootLines.push(`  --z-index-${key}: ${value};`);
  }

  rootLines.push("");
  rootLines.push("  /* ── Transition presets ── */");
  for (const [key, value] of Object.entries(transitions.duration || {})) {
    rootLines.push(`  --duration-${key}: ${value};`);
  }
  for (const [key, value] of Object.entries(transitions.easing || {})) {
    rootLines.push(`  --easing-${key}: ${value};`);
  }

  rootLines.push("");
  rootLines.push("  /* ── Icon sizes ── */");
  for (const [key, value] of Object.entries(icons.size || {})) {
    rootLines.push(`  --icon-size-${key}: ${value}px;`);
  }

  rootLines.push("");
  rootLines.push("  /* ── Layout breakpoints ── */");
  for (const [key, value] of Object.entries(layout.breakpoints || {})) {
    rootLines.push(`  --breakpoint-${key}: ${value}px;`);
  }

  // ── Typography tokens ──
  rootLines.push("");
  rootLines.push("  /* ── Typography ── */");
  rootLines.push(`  --font-primary: "${typography["font-family"].primary}";`);
  for (const [key, value] of Object.entries(typography["font-weight"] || {})) {
    rootLines.push(`  --font-weight-${key}: ${value};`);
  }
  rootLines.push(`  --font-style-normal: ${typography["font-style"].normal};`);
  rootLines.push(`  --line-height-normal: ${typography["line-height"].normal};`);
  for (const [key, val] of Object.entries(typography["font-size"] || {})) {
    rootLines.push(`  --font-size-${key}: ${val.rem}rem;`);
    if (val.mobile_rem !== undefined) {
      rootLines.push(`  --font-size-${key}-mobile: ${val.mobile_rem}rem;`);
    }
  }
  // Component font sizes and weights — emit raw values to match current fonts.css
  const pSize = typography["font-size"].p.rem;
  const smallSize = typography["font-size"].small.rem;
  rootLines.push(`  --font-weight-p: ${typography["component-font-weight"].p};`);
  rootLines.push(`  --button-font-family: var(--font-primary);`);
  rootLines.push(`  --button-font-size: ${pSize}rem;`);
  rootLines.push(`  --button-font-weight: ${typography["component-font-weight"].button};`);
  rootLines.push(`  --button-text-decoration: none;`);
  rootLines.push(`  --input-font-size: ${pSize}rem;`);
  rootLines.push(`  --input-font-weight: ${typography["component-font-weight"].input};`);
  rootLines.push(`  --app-card-font-size: ${pSize}rem;`);
  rootLines.push(`  --chat-message-font-size: ${pSize}rem;`);
  rootLines.push(`  --processing-details-font-size: ${smallSize}rem;`);

  // ── Assemble CSS ──
  const css = `/* AUTO-GENERATED by build-tokens.js — DO NOT EDIT
 * Source: frontend/packages/ui/src/tokens/sources/
 * ${new Date().toISOString().split("T")[0]}
 */

:root {
${rootLines.join("\n")}
}

/* Dark theme overrides */
[data-theme="dark"] {
${darkLines.join("\n")}
}
`;

  return css;
}

// ── TypeScript Generation ──────────────────────────────────────────────────

function generateTypeScript() {
  const colors = readYaml("colors.yml");
  const spacing = readYaml("spacing.yml");
  const radii = readYaml("radii.yml");
  const shadows = readYaml("shadows.yml");
  const zIndex = readYaml("z-index.yml");
  const transitions = readYaml("transitions.yml");
  const icons = readYaml("icons.yml");
  const layout = readYaml("layout.yml");
  const typography = readYaml("typography.yml");

  const lines = [
    "// AUTO-GENERATED by build-tokens.js — DO NOT EDIT",
    `// Source: frontend/packages/ui/src/tokens/sources/`,
    "",
  ];

  // Color references (var() strings for use in JS-driven styles)
  lines.push("export const Color = Object.freeze({");
  for (const [name] of Object.entries(colors.grey || {})) {
    lines.push(`  grey${pascalCase(String(name))}: 'var(--color-grey-${name})',`);
  }
  for (const [name] of Object.entries(colors.font || {})) {
    lines.push(`  font${pascalCase(name)}: 'var(--color-font-${name})',`);
  }
  for (const [name] of Object.entries(colors.semantic || {})) {
    lines.push(`  ${camelCase(name)}: 'var(--color-${name})',`);
  }
  for (const [name] of Object.entries(colors.button || {})) {
    lines.push(`  button${pascalCase(name)}: 'var(--color-button-${name})',`);
  }
  lines.push("} as const);");
  lines.push("");

  // Spacing (raw numbers for calculations)
  lines.push("export const Spacing = Object.freeze({");
  for (const [key, value] of Object.entries(spacing.scale || {})) {
    lines.push(`  s${key}: ${value},`);
  }
  lines.push("} as const);");
  lines.push("");

  // Radii
  lines.push("export const Radius = Object.freeze({");
  for (const [key, value] of Object.entries(radii.scale || {})) {
    lines.push(`  r${key}: ${value},`);
  }
  lines.push("} as const);");
  lines.push("");

  // Shadows (var() strings)
  lines.push("export const Shadow = Object.freeze({");
  for (const key of Object.keys(shadows.presets || {})) {
    lines.push(`  ${key}: 'var(--shadow-${key})',`);
  }
  lines.push("} as const);");
  lines.push("");

  // Z-index
  lines.push("export const ZIndex = Object.freeze({");
  for (const [key, value] of Object.entries(zIndex.layers || {})) {
    lines.push(`  ${camelCase(key)}: ${value},`);
  }
  lines.push("} as const);");
  lines.push("");

  // Transitions
  lines.push("export const Duration = Object.freeze({");
  for (const [key, value] of Object.entries(transitions.duration || {})) {
    lines.push(`  ${key}: '${value}',`);
  }
  lines.push("} as const);");
  lines.push("");
  lines.push("export const Easing = Object.freeze({");
  for (const [key, value] of Object.entries(transitions.easing || {})) {
    lines.push(`  ${camelCase(key)}: '${value}',`);
  }
  lines.push("} as const);");
  lines.push("");

  // Icon sizes
  lines.push("export const IconSize = Object.freeze({");
  for (const [key, value] of Object.entries(icons.size || {})) {
    lines.push(`  ${key}: ${value},`);
  }
  lines.push("} as const);");
  lines.push("");

  // Breakpoints (replaces constants.ts)
  lines.push("export const Breakpoint = Object.freeze({");
  for (const [key, value] of Object.entries(layout.breakpoints || {})) {
    lines.push(`  ${camelCase(key)}: ${value},`);
  }
  lines.push("} as const);");
  lines.push("");

  // Layout dimensions
  lines.push("export const Layout = Object.freeze({");
  for (const [key, value] of Object.entries(layout.dimensions || {})) {
    lines.push(`  ${camelCase(key)}: ${value},`);
  }
  lines.push("} as const);");
  lines.push("");

  // Font sizes (rem values for reference, pt for native)
  lines.push("export const FontSize = Object.freeze({");
  for (const [key, val] of Object.entries(typography["font-size"] || {})) {
    lines.push(`  ${key}: { rem: ${val.rem}, pt: ${val.pt}${val.mobile_rem !== undefined ? `, mobileRem: ${val.mobile_rem}, mobilePt: ${val.mobile_pt}` : ""} },`);
  }
  lines.push("} as const);");
  lines.push("");

  // Backwards-compatible exports (deprecated, use Breakpoint.mobile etc.)
  lines.push("/** @deprecated Use Breakpoint.mobile */");
  lines.push(`export const MOBILE_BREAKPOINT = ${layout.breakpoints.mobile};`);
  lines.push("/** @deprecated Use Breakpoint.chatsOpen */");
  lines.push(`export const CHATS_DEFAULT_OPEN_BREAKPOINT = ${layout.breakpoints["chats-open"]};`);
  lines.push("");

  return lines.join("\n");
}

// ── Swift Generation ───────────────────────────────────────────────────────

function generateSwiftColors() {
  const colors = readYaml("colors.yml");

  const lines = [
    "// AUTO-GENERATED by build-tokens.js — DO NOT EDIT",
    "import SwiftUI",
    "",
    "extension Color {",
  ];

  // Grey scale — theme-aware via asset catalog
  lines.push("    // Grey scale");
  for (const [name] of Object.entries(colors.grey || {})) {
    lines.push(`    static let grey${pascalCase(String(name))} = Color("grey-${name}")`);
  }
  lines.push("");

  // Font colors
  lines.push("    // Font colors");
  for (const [name, val] of Object.entries(colors.font || {})) {
    if (val.dark || val.light) {
      lines.push(`    static let font${pascalCase(name)} = Color("font-${name}")`);
    } else {
      lines.push(`    static let font${pascalCase(name)} = Color(hex: 0x${val.value.replace("#", "").toUpperCase()})`);
    }
  }
  lines.push("");

  // Semantic colors
  lines.push("    // Semantic colors");
  for (const [name, val] of Object.entries(colors.semantic || {})) {
    if (val.light && val.light.startsWith("#")) {
      lines.push(`    static let ${camelCase(name)} = Color("${name}")`);
    }
  }
  lines.push("");

  // Button colors
  lines.push("    // Button colors");
  for (const [name, val] of Object.entries(colors.button || {})) {
    lines.push(`    static let button${pascalCase(name)} = Color(hex: 0x${val.value.replace("#", "").toUpperCase()})`);
  }

  lines.push("}");
  lines.push("");

  return lines.join("\n");
}

function generateSwiftSpacing() {
  const spacing = readYaml("spacing.yml");
  const radii = readYaml("radii.yml");
  const icons = readYaml("icons.yml");
  const layout = readYaml("layout.yml");

  const lines = [
    "// AUTO-GENERATED by build-tokens.js — DO NOT EDIT",
    "import SwiftUI",
    "",
    "extension CGFloat {",
    "    // Spacing scale",
  ];

  for (const [key, value] of Object.entries(spacing.scale || {})) {
    lines.push(`    static let spacing${key}: CGFloat = ${value}`);
  }
  lines.push("");

  lines.push("    // Border radius");
  for (const [key, value] of Object.entries(radii.scale || {})) {
    lines.push(`    static let radius${pascalCase(String(key))}: CGFloat = ${value}`);
  }
  lines.push("");

  lines.push("    // Icon sizes");
  for (const [key, value] of Object.entries(icons.size || {})) {
    lines.push(`    static let iconSize${pascalCase(key)}: CGFloat = ${value}`);
  }
  lines.push("");

  lines.push("    // Breakpoints");
  for (const [key, value] of Object.entries(layout.breakpoints || {})) {
    lines.push(`    static let breakpoint${pascalCase(key)}: CGFloat = ${value}`);
  }

  lines.push("}");
  lines.push("");

  return lines.join("\n");
}

function generateSwiftTypography() {
  const typography = readYaml("typography.yml");

  const lines = [
    "// AUTO-GENERATED by build-tokens.js — DO NOT EDIT",
    "import SwiftUI",
    "",
    "extension Font {",
  ];

  // Use the Swift-specific family name if defined; the CSS variable font name ("Lexend Deca Variable")
  // must not be used in Font.custom() — iOS registers static weights under "Lexend Deca".
  const swiftFamily = typography["font-family"].swift || typography["font-family"].primary.replace(/ /g, "-");
  for (const [key, val] of Object.entries(typography["font-size"] || {})) {
    lines.push(`    static let om${pascalCase(key)} = Font.custom("${swiftFamily}", size: ${val.pt})`);
  }

  lines.push("}");
  lines.push("");

  return lines.join("\n");
}

function generateSwiftGradients() {
  const gradients = readYaml("gradients.yml");

  const lines = [
    "// AUTO-GENERATED by build-tokens.js — DO NOT EDIT",
    "import SwiftUI",
    "",
    "extension LinearGradient {",
    "    /// Standard OpenMates gradient (135deg, 9.04% -> 90.06%)",
    "    static func omGradient(start: Color, end: Color) -> LinearGradient {",
    "        LinearGradient(",
    "            gradient: Gradient(stops: [",
    "                .init(color: start, location: 0.0904),",
    "                .init(color: end, location: 0.9006)",
    "            ]),",
    "            startPoint: .topLeading,",
    "            endPoint: .bottomTrailing",
    "        )",
    "    }",
    "",
  ];

  // App gradients (only those with raw hex, not var() refs)
  for (const [name, grad] of Object.entries(gradients.apps || {})) {
    if (grad.start && !grad.start_ref) {
      lines.push(`    static let app${pascalCase(name)} = omGradient(start: Color(hex: 0x${grad.start.replace("#", "").toUpperCase()}), end: Color(hex: 0x${grad.end.replace("#", "").toUpperCase()}))`);
    }
  }
  lines.push("");

  // Primary
  const primary = gradients.primary;
  lines.push(`    static let primary = omGradient(start: Color(hex: 0x${primary.start.replace("#", "").toUpperCase()}), end: Color(hex: 0x${primary.end.replace("#", "").toUpperCase()}))`);

  lines.push("}");
  lines.push("");

  return lines.join("\n");
}

function generateSwiftUmbrella() {
  return [
    "// AUTO-GENERATED by build-tokens.js — DO NOT EDIT",
    "// Umbrella file — import this to get all token extensions.",
    "",
    "// Color, Font, CGFloat, LinearGradient, Image extensions are defined in:",
    "//   ColorTokens.generated.swift",
    "//   TypographyTokens.generated.swift",
    "//   SpacingTokens.generated.swift",
    "//   GradientTokens.generated.swift",
    "//   IconMapping.generated.swift",
    "//   ComponentTokens.generated.swift",
    "",
  ].join("\n");
}

// ── Component Classes Generation (Phase E) ─────────────────────────────────
// Reads src/tokens/sources/components/*.yml and emits:
//   - src/tokens/generated/component-classes.generated.css (.ds-* classes)
//   - src/tokens/generated/swift/ComponentTokens.generated.swift (DS.* enums)
//
// Each YAML file declares one or more "primitives" keyed by name. A primitive
// is a map of CSS-ish properties. Values are either:
//   - a number  → treated as px for dimensional props, bare number otherwise
//   - a string  → emitted verbatim
//   - { ref }   → emitted as var(--<ref>) pointing at an existing token
//
// Architecture: docs/architecture/frontend/design-tokens.md

// Properties whose raw numeric values should be emitted with a px suffix.
const COMPONENT_DIMENSIONAL_PROPS = new Set([
  "width", "min-width", "max-width",
  "height", "min-height", "max-height",
  "border-radius", "radius",
  "padding", "padding-top", "padding-right", "padding-bottom", "padding-left",
  "padding-x", "padding-y",
  "margin", "margin-top", "margin-right", "margin-bottom", "margin-left",
  "gap", "top", "right", "bottom", "left",
]);

/** Resolve a raw YAML value to a CSS expression. */
function resolveComponentValue(value, propKey) {
  if (value === null || value === undefined) return null;
  if (typeof value === "object" && value !== null && "ref" in value) {
    return `var(--${value.ref})`;
  }
  if (typeof value === "number") {
    return COMPONENT_DIMENSIONAL_PROPS.has(propKey) ? `${value}px` : String(value);
  }
  return String(value);
}

/** Emit CSS declarations for one primitive. Handles composite props. */
function emitPrimitiveDeclarations(primitive) {
  const decls = [];
  let paddingX = null;
  let paddingY = null;

  for (const [key, rawValue] of Object.entries(primitive)) {
    const value = resolveComponentValue(rawValue, key);
    if (value === null) continue;

    if (key === "padding-x") { paddingX = value; continue; }
    if (key === "padding-y") { paddingY = value; continue; }
    if (key === "radius") { decls.push(`  border-radius: ${value};`); continue; }
    if (key === "webkit-box-orient") { decls.push(`  -webkit-box-orient: ${value};`); continue; }
    if (key === "line-clamp") {
      decls.push(`  display: -webkit-box;`);
      decls.push(`  -webkit-line-clamp: ${value};`);
      decls.push(`  line-clamp: ${value};`);
      decls.push(`  -webkit-box-orient: vertical;`);
      decls.push(`  overflow: hidden;`);
      continue;
    }
    decls.push(`  ${key}: ${value};`);
  }

  if (paddingY !== null && paddingX !== null) {
    decls.push(`  padding: ${paddingY} ${paddingX};`);
  } else if (paddingY !== null) {
    decls.push(`  padding-top: ${paddingY};`);
    decls.push(`  padding-bottom: ${paddingY};`);
  } else if (paddingX !== null) {
    decls.push(`  padding-left: ${paddingX};`);
    decls.push(`  padding-right: ${paddingX};`);
  }

  return decls;
}

/** Read every components/*.yml as { filename, primitives } pairs. */
function readComponentSources() {
  if (!existsSync(COMPONENTS_DIR)) return [];
  return readdirSync(COMPONENTS_DIR)
    .filter(f => f.endsWith(".yml"))
    .sort()
    .map(filename => {
      const raw = readFileSync(resolve(COMPONENTS_DIR, filename), "utf-8");
      const parsed = YAML.parse(raw) || {};
      return { filename, primitives: parsed };
    });
}

function generateComponentClasses() {
  const sources = readComponentSources();
  const sections = [];

  for (const { filename, primitives } of sources) {
    const entries = Object.entries(primitives).filter(([, v]) => v && typeof v === "object");
    if (entries.length === 0) continue;

    const groupName = basename(filename, ".yml");
    sections.push(`/* ── ${groupName} ── */`);
    for (const [name, spec] of entries) {
      const decls = emitPrimitiveDeclarations(spec);
      if (decls.length === 0) continue;
      sections.push(`.ds-${name} {`);
      sections.push(...decls);
      sections.push(`}`);
      sections.push("");
    }
  }

  const body = sections.length > 0 ? sections.join("\n") : "/* (no primitives lifted yet) */\n";
  return `/* AUTO-GENERATED by build-tokens.js — DO NOT EDIT
 * Source: frontend/packages/ui/src/tokens/sources/components/
 * ${new Date().toISOString().split("T")[0]}
 *
 * Design-system component primitive classes (Phase E).
 * Opt in by using class="ds-<name>" and deleting the legacy local rule in
 * the same atomic commit. See docs/architecture/frontend/design-tokens.md.
 */

${body}`;
}

// CSS-only layout/paint properties that should NOT appear in Swift output.
// SwiftUI expresses these via layout containers (HStack/VStack) and view
// modifiers (.lineLimit, .shadow, .clipShape) — not as constants.
const COMPONENT_SWIFT_SKIP_PROPS = new Set([
  "display",
  "align-items", "justify-content",
  "flex-wrap", "flex-direction", "flex-shrink", "flex-grow",
  "webkit-box-orient", "line-clamp", "-webkit-line-clamp",
  "overflow", "overflow-x", "overflow-y",
  "text-overflow", "word-break", "white-space",
  "position",
  "box-shadow",
  "background", "background-image",
  "margin",
  "transform", "cursor", "user-select", "pointer-events",
  "transition", "animation",
]);

// CSS font-weight numbers → SwiftUI Font.Weight symbols.
const FONT_WEIGHT_TO_SWIFT = {
  100: ".ultraLight",
  200: ".thin",
  300: ".light",
  400: ".regular",
  500: ".medium",
  600: ".semibold",
  700: ".bold",
  800: ".heavy",
  900: ".black",
};

/**
 * Resolve a component-primitive `{ ref: "..." }` value to a SwiftUI symbol.
 * Returns { symbol, type } or null if the ref points at a token without a
 * generated Swift counterpart (consumer falls back to a comment).
 *
 * Mapping rules:
 *   font-size-{key}        → Font.om{Key}            (Font)
 *   font-size-{key}-mobile → Font.om{Key}            (Font, Dynamic Type handles scaling)
 *   color-{name}           → Color.{camelCase name}  (Color)
 *   spacing-{N}            → CGFloat.spacing{N}      (CGFloat)
 *   radius-{key}           → CGFloat.radius{Key}     (CGFloat)
 *   icon-size-{key}        → CGFloat.iconSize{Key}   (CGFloat)
 */
function resolveSwiftRef(ref) {
  let m = ref.match(/^font-size-([a-z0-9]+)(?:-mobile)?$/);
  if (m) return { symbol: `Font.om${pascalCase(m[1])}`, type: "Font" };

  m = ref.match(/^color-(.+)$/);
  if (m) return { symbol: `Color.${camelCase(m[1])}`, type: "Color" };

  m = ref.match(/^spacing-(\d+)$/);
  if (m) return { symbol: `CGFloat.spacing${m[1]}`, type: "CGFloat" };

  m = ref.match(/^radius-(.+)$/);
  if (m) return { symbol: `CGFloat.radius${pascalCase(m[1])}`, type: "CGFloat" };

  m = ref.match(/^icon-size-(.+)$/);
  if (m) return { symbol: `CGFloat.iconSize${pascalCase(m[1])}`, type: "CGFloat" };

  return null;
}

function generateComponentSwift() {
  const sources = readComponentSources();
  const lines = [
    "// AUTO-GENERATED by build-tokens.js — DO NOT EDIT",
    "// Source: frontend/packages/ui/src/tokens/sources/components/",
    "//",
    "// Cross-platform counterparts to the .ds-* CSS classes — consumed by the",
    "// iOS SwiftUI app to share component primitive values with the web.",
    "//",
    "// CSS-only layout/paint props (display, align-items, flex-*, overflow,",
    "// box-shadow, background gradients, etc.) are intentionally omitted —",
    "// SwiftUI expresses those via layout containers and view modifiers.",
    "// Token references (ref:) are resolved to their SwiftUI symbol counterparts.",
    "",
    "import SwiftUI",
    "",
    "public enum DS {",
  ];

  let emitted = 0;
  for (const { primitives } of sources) {
    for (const [name, spec] of Object.entries(primitives)) {
      if (!spec || typeof spec !== "object") continue;

      const memberLines = [];
      for (const [key, rawValue] of Object.entries(spec)) {
        if (COMPONENT_SWIFT_SKIP_PROPS.has(key)) continue;
        const propName = camelCase(key);

        // Token reference → resolved Swift symbol (or comment fallback).
        if (typeof rawValue === "object" && rawValue !== null && "ref" in rawValue) {
          const resolved = resolveSwiftRef(rawValue.ref);
          if (resolved) {
            memberLines.push(`    public static let ${propName}: ${resolved.type} = ${resolved.symbol}`);
          } else {
            memberLines.push(`    // ${propName}: unresolved ref --${rawValue.ref}`);
          }
          continue;
        }

        // font-weight numeric → SwiftUI Font.Weight symbol.
        if (key === "font-weight" && typeof rawValue === "number" && FONT_WEIGHT_TO_SWIFT[rawValue]) {
          memberLines.push(`    public static let ${propName}: Font.Weight = ${FONT_WEIGHT_TO_SWIFT[rawValue]}`);
          continue;
        }

        // Plain numeric → CGFloat.
        if (typeof rawValue === "number") {
          memberLines.push(`    public static let ${propName}: CGFloat = ${rawValue}`);
          continue;
        }

        // String values: skip anything that's a CSS function call, percentage,
        // or a CSS-keyword value that isn't useful as a Swift constant.
        const stringVal = String(rawValue);
        if (/^(linear-gradient|radial-gradient|rgba?|hsla?|var|url|calc|cubic-bezier)\(/.test(stringVal)) continue;
        if (/%$/.test(stringVal)) continue;
        if (["0", "auto", "none", "inherit", "initial", "unset"].includes(stringVal)) continue;

        memberLines.push(`    public static let ${propName}: String = ${JSON.stringify(stringVal)}`);
      }

      // Skip primitives whose entire member set is CSS-only (e.g. flex wrappers).
      if (memberLines.length === 0) continue;

      lines.push(`  public enum ${pascalCase(name)} {`);
      lines.push(...memberLines);
      lines.push(`  }`);
      lines.push("");
      emitted++;
    }
  }

  if (emitted === 0) {
    lines.push("  // (no primitives lifted yet)");
  }

  lines.push("}");
  lines.push("");
  return lines.join("\n");
}

function generateXcassets() {
  const colors = readYaml("colors.yml");

  // Generate colorset for each theme-aware color
  const colorSets = [];

  // Grey scale
  for (const [name, val] of Object.entries(colors.grey || {})) {
    if (val.light && val.dark && val.light.startsWith("#") && val.dark.startsWith("#")) {
      colorSets.push({ name: `grey-${name}`, light: val.light, dark: val.dark });
    }
  }

  // Font colors
  for (const [name, val] of Object.entries(colors.font || {})) {
    const light = val.light || val.value;
    if (light && val.dark && light.startsWith("#") && val.dark.startsWith("#")) {
      colorSets.push({ name: `font-${name}`, light, dark: val.dark });
    }
  }

  // Semantic (only hex, not rgba)
  for (const [name, val] of Object.entries(colors.semantic || {})) {
    if (val.light && val.dark && val.light.startsWith("#") && val.dark.startsWith("#")) {
      colorSets.push({ name, light: val.light, dark: val.dark });
    }
  }

  // Write colorset directories
  for (const cs of colorSets) {
    const dir = resolve(XCASSETS_DIR, `${cs.name}.colorset`);
    ensureDir(dir);
    const lightRgb = hexToRgb(cs.light);
    const darkRgb = hexToRgb(cs.dark);
    const contents = {
      colors: [
        {
          color: {
            "color-space": "srgb",
            components: {
              red: `${lightRgb.r.toFixed(3)}`,
              green: `${lightRgb.g.toFixed(3)}`,
              blue: `${lightRgb.b.toFixed(3)}`,
              alpha: "1.000"
            }
          },
          idiom: "universal"
        },
        {
          appearances: [{ appearance: "luminosity", value: "dark" }],
          color: {
            "color-space": "srgb",
            components: {
              red: `${darkRgb.r.toFixed(3)}`,
              green: `${darkRgb.g.toFixed(3)}`,
              blue: `${darkRgb.b.toFixed(3)}`,
              alpha: "1.000"
            }
          },
          idiom: "universal"
        }
      ],
      info: { author: "build-tokens.js", version: 1 }
    };
    writeFileSync(resolve(dir, "Contents.json"), JSON.stringify(contents, null, 2) + "\n", "utf-8");
  }

  // Root Contents.json for the xcassets catalog
  writeFileSync(
    resolve(XCASSETS_DIR, "Contents.json"),
    JSON.stringify({ info: { author: "build-tokens.js", version: 1 } }, null, 2) + "\n",
    "utf-8"
  );

  return colorSets.length;
}

// ── Icon Mapping Generation ────────────────────────────────────────────────

function generateIconXcassets() {
  /** Copy custom SVGs into xcassets image sets for Xcode. */
  if (!existsSync(ICONS_DIR)) return 0;

  ensureDir(ICONS_XCASSETS_DIR);

  const svgFiles = readdirSync(ICONS_DIR)
    .filter(f => f.endsWith(".svg"))
    .sort();

  for (const file of svgFiles) {
    const name = basename(file, ".svg");
    const imagesetDir = resolve(ICONS_XCASSETS_DIR, `${name}.imageset`);
    ensureDir(imagesetDir);

    // Copy SVG into imageset
    copyFileSync(resolve(ICONS_DIR, file), resolve(imagesetDir, file));

    // Write Contents.json for the imageset
    const contents = {
      images: [
        {
          filename: file,
          idiom: "universal"
        }
      ],
      info: { author: "build-tokens.js", version: 1 },
      properties: {
        "preserves-vector-representation": true,
        "template-rendering-intent": "template"
      }
    };
    writeFileSync(resolve(imagesetDir, "Contents.json"), JSON.stringify(contents, null, 2) + "\n", "utf-8");
  }

  // Root Contents.json
  writeFileSync(
    resolve(ICONS_XCASSETS_DIR, "Contents.json"),
    JSON.stringify({ info: { author: "build-tokens.js", version: 1 } }, null, 2) + "\n",
    "utf-8"
  );

  return svgFiles.length;
}

function generateBrandImageAssets() {
  if (!existsSync(BRAND_FAVICON_PNG)) return 0;

  const imagesetDir = resolve(XCASSETS_DIR, "openmates-brand.imageset");
  ensureDir(imagesetDir);

  copyFileSync(BRAND_FAVICON_PNG, resolve(imagesetDir, "openmates-brand.png"));

  const contents = {
    images: [
      {
        filename: "openmates-brand.png",
        idiom: "universal"
      }
    ],
    info: { author: "build-tokens.js", version: 1 }
  };
  writeFileSync(resolve(imagesetDir, "Contents.json"), JSON.stringify(contents, null, 2) + "\n", "utf-8");

  return 1;
}

function generateSwiftIconMapping() {
  /** Generate Swift enum mapping Lucide names → SF Symbols + custom icon accessors. */
  const mapping = readYaml("icons-mapping.yml");

  const lines = [
    "// AUTO-GENERATED by build-tokens.js — DO NOT EDIT",
    "import SwiftUI",
    "",
    "// MARK: - SF Symbol mapping for Lucide icon equivalents",
    "",
    "/// Maps semantic icon names (used as Lucide names on web) to SF Symbols.",
    "/// Usage: Image(systemName: SFSymbol.bell)",
    "enum SFSymbol {",
  ];

  for (const [name, val] of Object.entries(mapping.lucide || {})) {
    const propName = camelCase(name);
    lines.push(`    static let ${propName} = "${val.sf}"`);
  }

  lines.push("}");
  lines.push("");

  // Custom icon accessors via xcassets
  lines.push("// MARK: - Custom icon accessors (SVGs from static/icons/ via Icons.xcassets)");
  lines.push("");
  lines.push("extension Image {");

  if (existsSync(ICONS_DIR)) {
    const svgFiles = readdirSync(ICONS_DIR)
      .filter(f => f.endsWith(".svg"))
      .sort();

    for (const file of svgFiles) {
      const name = basename(file, ".svg");
      // Convert to valid Swift identifier: replace hyphens/dots, handle leading digits
      let propName = camelCase(name);
      if (/^\d/.test(propName)) propName = "_" + propName;
      lines.push(`    static let icon${pascalCase(name)} = Image("${name}")`);
    }
  }

  lines.push("}");
  lines.push("");

  // Icon aliases
  lines.push("// MARK: - Icon aliases (app name → actual icon name)");
  lines.push("");
  lines.push("enum IconAlias {");

  for (const [alias, target] of Object.entries(mapping.aliases || {})) {
    lines.push(`    static let ${camelCase(alias)} = "${target}"`);
  }

  lines.push("}");
  lines.push("");

  return lines.join("\n");
}

function generateTSIconMapping() {
  /** Generate TypeScript icon mapping export. */
  const mapping = readYaml("icons-mapping.yml");

  const lines = [
    "",
    "/** Lucide icon name → SF Symbol name mapping for cross-platform icon parity. */",
    "export const LucideToSF = Object.freeze({",
  ];

  for (const [name, val] of Object.entries(mapping.lucide || {})) {
    lines.push(`  '${name}': '${val.sf}',`);
  }

  lines.push("} as const);");
  lines.push("");

  lines.push("/** App/feature name → actual SVG icon filename aliases. */");
  lines.push("export const IconAlias = Object.freeze({");

  for (const [alias, target] of Object.entries(mapping.aliases || {})) {
    lines.push(`  '${alias}': '${target}',`);
  }

  lines.push("} as const);");
  lines.push("");

  return lines.join("\n");
}

// ── Verify Mode ────────────────────────────────────────────────────────────

function extractCSSProperties(cssContent) {
  /** Extract all --var: value pairs from a CSS string. Returns a Map. */
  const props = new Map();
  // Match custom properties in :root and [data-theme="dark"] blocks
  const propRegex = /^\s*(--[\w-]+)\s*:\s*(.+?)\s*;?\s*$/gm;
  let match;
  while ((match = propRegex.exec(cssContent)) !== null) {
    const name = match[1];
    // Strip inline comments (/* ... */) and normalize whitespace
    const value = match[2]
      .replace(/\/\*.*?\*\//g, "")
      .replace(/\s+/g, " ")
      .trim()
      .replace(/;$/, "");
    props.set(name, value);
  }
  return props;
}

function verify(generatedCSS) {
  const THEME_CSS = resolve(__dirname, "../src/styles/theme.css");
  const FONTS_CSS = resolve(__dirname, "../src/styles/fonts.css");

  const themeCss = readFileSync(THEME_CSS, "utf-8");
  const fontsCss = readFileSync(FONTS_CSS, "utf-8");

  const currentProps = extractCSSProperties(themeCss + "\n" + fontsCss);
  const generatedProps = extractCSSProperties(generatedCSS);

  let mismatches = 0;
  let missing = 0;

  // Check all current properties exist in generated with same value
  for (const [name, value] of currentProps) {
    if (!generatedProps.has(name)) {
      console.error(`[verify] MISSING in generated: ${name}`);
      missing++;
    } else {
      const genValue = generatedProps.get(name);
      // Normalize for comparison: collapse whitespace, trim
      const normalizedCurrent = value.replace(/\s+/g, " ").trim();
      const normalizedGenerated = genValue.replace(/\s+/g, " ").trim();
      if (normalizedCurrent !== normalizedGenerated) {
        console.error(`[verify] MISMATCH: ${name}`);
        console.error(`  current:   ${normalizedCurrent}`);
        console.error(`  generated: ${normalizedGenerated}`);
        mismatches++;
      }
    }
  }

  if (mismatches === 0 && missing === 0) {
    console.log(`[verify] ✓ All ${currentProps.size} existing properties match.`);
    const newProps = generatedProps.size - currentProps.size;
    if (newProps > 0) {
      console.log(`[verify] + ${newProps} new tokens added (spacing, radii, shadows, z-index, transitions, icons, breakpoints).`);
    }
    return true;
  } else {
    console.error(`[verify] ✗ ${mismatches} mismatches, ${missing} missing properties.`);
    return false;
  }
}

// ── Main ───────────────────────────────────────────────────────────────────

function main() {
  const isVerify = process.argv.includes("--verify");

  ensureDir(GENERATED_DIR);
  ensureDir(SWIFT_DIR);
  ensureDir(XCASSETS_DIR);

  // Generate CSS
  const css = generateCSS();
  writeFileSync(CSS_OUTPUT, css, "utf-8");
  console.log(`[build-tokens] Generated CSS → ${CSS_OUTPUT}`);

  // Generate TypeScript (tokens + icon mapping)
  const ts = generateTypeScript() + generateTSIconMapping();
  writeFileSync(TS_OUTPUT, ts, "utf-8");
  console.log(`[build-tokens] Generated TypeScript → ${TS_OUTPUT}`);

  // Generate Swift
  writeFileSync(resolve(SWIFT_DIR, "ColorTokens.generated.swift"), generateSwiftColors(), "utf-8");
  writeFileSync(resolve(SWIFT_DIR, "TypographyTokens.generated.swift"), generateSwiftTypography(), "utf-8");
  writeFileSync(resolve(SWIFT_DIR, "SpacingTokens.generated.swift"), generateSwiftSpacing(), "utf-8");
  writeFileSync(resolve(SWIFT_DIR, "GradientTokens.generated.swift"), generateSwiftGradients(), "utf-8");
  writeFileSync(resolve(SWIFT_DIR, "Tokens.generated.swift"), generateSwiftUmbrella(), "utf-8");
  console.log(`[build-tokens] Generated Swift → ${SWIFT_DIR}/`);

  // Generate xcassets (colors)
  const colorSetCount = generateXcassets();
  console.log(`[build-tokens] Generated ${colorSetCount} color sets → ${XCASSETS_DIR}/`);

  const brandImageCount = generateBrandImageAssets();
  console.log(`[build-tokens] Generated ${brandImageCount} brand image sets → ${XCASSETS_DIR}/`);

  // Generate icon xcassets (SVGs)
  const iconCount = generateIconXcassets();
  console.log(`[build-tokens] Generated ${iconCount} icon image sets → ${ICONS_XCASSETS_DIR}/`);

  // Generate Swift icon mapping
  writeFileSync(resolve(SWIFT_DIR, "IconMapping.generated.swift"), generateSwiftIconMapping(), "utf-8");
  console.log(`[build-tokens] Generated Swift icon mapping → ${SWIFT_DIR}/IconMapping.generated.swift`);

  // Generate component primitive classes + Swift structs (Phase E)
  writeFileSync(COMPONENT_CSS_OUTPUT, generateComponentClasses(), "utf-8");
  console.log(`[build-tokens] Generated component classes → ${COMPONENT_CSS_OUTPUT}`);
  writeFileSync(COMPONENT_SWIFT_OUTPUT, generateComponentSwift(), "utf-8");
  console.log(`[build-tokens] Generated component Swift → ${COMPONENT_SWIFT_OUTPUT}`);

  // Verify mode
  if (isVerify) {
    console.log("\n[build-tokens] Running verification...");
    const ok = verify(css);
    if (!ok) {
      process.exit(1);
    }
  }
}

main();
