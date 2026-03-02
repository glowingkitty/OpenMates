// frontend/packages/ui/scripts/generate-providers-metadata.js
//
// Build script to generate providersMetadata.ts from backend provider YAML files.
// This script reads all provider *.yml files from backend/providers/ and generates
// a TypeScript file with provider metadata for the frontend provider detail pages.
//
// Each provider entry includes:
//   - id: provider_id from YAML
//   - name: display name
//   - description: short description of the provider
//   - logo_svg: icon path (e.g., "icons/anthropic.svg")
//   - country: ISO 3166-1 alpha-2 country code (from 'region' or first model's 'country_origin')
//
// **Usage**: Run this script during the build process.
// Generation script: frontend/packages/ui/scripts/generate-providers-metadata.js
// This script runs automatically via the 'prebuild' hook in package.json

import { readFileSync, readdirSync, writeFileSync } from "fs";
import { join, dirname, resolve, basename } from "path";
import { fileURLToPath } from "url";
import yaml from "yaml";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const BACKEND_PROVIDERS_DIR = resolve(
  __dirname,
  "../../../../backend/providers",
);
const OUTPUT_FILE = resolve(__dirname, "../src/data/providersMetadata.ts");

/**
 * Map a region string (EU/US/APAC) or model country_origin (ISO alpha-2) to a
 * two-letter ISO country code for flag display.
 *
 * - Providers with an explicit top-level `region` key use a best-match mapping.
 * - Providers whose country comes from their models' `country_origin` are already
 *   ISO alpha-2 (e.g., "US", "FR", "CN").
 */
function resolveCountry(region, countryOrigin) {
  if (countryOrigin && countryOrigin.length === 2) {
    return countryOrigin.toUpperCase();
  }
  if (region) {
    // Map region strings to representative ISO codes
    const regionMap = {
      EU: "EU", // Use EU flag emoji directly
      US: "US",
      APAC: "JP", // Approximate APAC with Japan
    };
    return regionMap[region.toUpperCase()] || "US";
  }
  return "US"; // Default
}

/**
 * Find all provider YAML files in the backend/providers directory.
 */
function findProviderYamlFiles() {
  const providers = [];
  try {
    const files = readdirSync(BACKEND_PROVIDERS_DIR);
    for (const file of files) {
      if (file.endsWith(".yml") || file.endsWith(".yaml")) {
        const providerId = basename(
          file,
          file.endsWith(".yml") ? ".yml" : ".yaml",
        );
        const filePath = join(BACKEND_PROVIDERS_DIR, file);
        providers.push({ providerId, filePath });
      }
    }
  } catch (err) {
    console.error(
      `[generate-providers-metadata] Error reading backend/providers directory:`,
      err,
    );
    throw err;
  }
  return providers;
}

/**
 * Parse a provider YAML file and return a ProviderMetadata object.
 * Returns null if the file cannot be parsed or has no meaningful data.
 */
function parseProviderYaml(providerId, filePath) {
  try {
    const content = readFileSync(filePath, "utf-8");
    const data = yaml.parse(content);

    if (!data || typeof data !== "object") {
      return null;
    }

    // Determine the country/region for this provider.
    // Priority: explicit top-level `region` → first model's country_origin → default US
    let country = "US";
    if (data.region) {
      country = resolveCountry(data.region, null);
    } else if (Array.isArray(data.models) && data.models.length > 0) {
      const firstModelWithCountry = data.models.find(
        (m) => m.country_origin && m.country_origin.length === 2,
      );
      if (firstModelWithCountry) {
        country = firstModelWithCountry.country_origin.toUpperCase();
      }
    }

    return {
      id: data.provider_id || providerId,
      name: data.name || providerId,
      description: data.description || "",
      logo_svg: `icons/${providerId}.svg`,
      country,
    };
  } catch (err) {
    console.error(
      `[generate-providers-metadata] ${providerId}: Error parsing YAML - ${err.message}`,
    );
    return null;
  }
}

/**
 * Generate the TypeScript source for providersMetadata.ts.
 */
function generateTypeScript(providers) {
  const entries = providers
    .map((p) => {
      const lines = ["    {"];
      lines.push(`        id: ${JSON.stringify(p.id)},`);
      lines.push(`        name: ${JSON.stringify(p.name)},`);
      lines.push(`        description: ${JSON.stringify(p.description)},`);
      lines.push(`        logo_svg: ${JSON.stringify(p.logo_svg)},`);
      lines.push(`        country: ${JSON.stringify(p.country)},`);
      lines.push("    },");
      return lines.join("\n");
    })
    .join("\n");

  return `// frontend/packages/ui/src/data/providersMetadata.ts
//
// WARNING: THIS FILE IS AUTO-GENERATED - DO NOT EDIT MANUALLY
//
// Generated from backend/providers/*.yml by:
//   frontend/packages/ui/scripts/generate-providers-metadata.js
//
// To modify provider metadata, edit the source YAML files.
//
// **Generated**: ${new Date().toISOString()}
// **Providers included**: ${providers.length}

/**
 * Provider metadata for the provider detail pages in the App Store settings.
 */
export interface ProviderMetadata {
    /** Unique provider identifier (matches provider YAML provider_id) */
    id: string;
    /** Display name for the provider */
    name: string;
    /** Short description of the provider */
    description: string;
    /** Path to provider logo SVG (e.g., "icons/anthropic.svg") */
    logo_svg: string;
    /** ISO 3166-1 alpha-2 country code for provider origin, or "EU" */
    country: string;
}

/**
 * Static provider metadata included in the build.
 * Keyed by provider_id for O(1) lookup.
 */
export const providersMetadata: Record<string, ProviderMetadata> = {
${providers.map((p) => `    ${JSON.stringify(p.id)}: {\n        id: ${JSON.stringify(p.id)},\n        name: ${JSON.stringify(p.name)},\n        description: ${JSON.stringify(p.description)},\n        logo_svg: ${JSON.stringify(p.logo_svg)},\n        country: ${JSON.stringify(p.country)},\n    },`).join("\n")}
};

/**
 * Look up a provider by name (case-insensitive).
 * Used to match app skill provider name strings (e.g. "Anthropic") to their metadata.
 */
export function findProviderByName(name: string): ProviderMetadata | undefined {
    const lowerName = name.toLowerCase().trim();
    return Object.values(providersMetadata).find(
        (p) => p.name.toLowerCase() === lowerName,
    );
}
`;
}

function main() {
  console.log(
    "[generate-providers-metadata] Starting provider metadata generation...",
  );

  const providerFiles = findProviderYamlFiles();
  console.log(
    `[generate-providers-metadata] Found ${providerFiles.length} provider file(s)`,
  );

  const providers = [];
  for (const { providerId, filePath } of providerFiles) {
    const meta = parseProviderYaml(providerId, filePath);
    if (meta) {
      providers.push(meta);
      console.log(`[generate-providers-metadata]   ✓ ${providerId}`);
    } else {
      console.log(
        `[generate-providers-metadata]   - ${providerId}: skipped (empty/invalid)`,
      );
    }
  }

  // Sort alphabetically by id for consistent output
  providers.sort((a, b) => a.id.localeCompare(b.id));

  const tsCode = generateTypeScript(providers);
  writeFileSync(OUTPUT_FILE, tsCode, "utf-8");
  console.log(`[generate-providers-metadata] Generated: ${OUTPUT_FILE}`);
  console.log(
    `[generate-providers-metadata] ✓ Successfully generated metadata for ${providers.length} provider(s)`,
  );
}

main();
