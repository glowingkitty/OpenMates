// frontend/packages/ui/scripts/generate-models-metadata.js
//
// Build script to generate modelsMetadata.ts from backend provider YAML files.
// This script reads all provider *.yml files from backend/providers/ and generates
// a TypeScript file with model metadata for the frontend @ mention dropdown.
//
// **Usage**: Run this script during the build process to include model metadata
// in the frontend bundle. Models are then filtered at runtime based on provider health.
//
// Models are included if they have input_types that include 'text' (AI chat models).
// At runtime, models are filtered based on provider health checks via the
// `isProviderHealthy` function from appHealthStore.
//
// NOTE: `allow_auto_select` is for a DIFFERENT feature (automatic model selection
// by the system). All models should be available for manual selection via @ mention.

import { readFileSync, readdirSync, writeFileSync } from "fs";
import { join, dirname, resolve, basename } from "path";
import { fileURLToPath } from "url";
import yaml from "yaml";

// Get the directory of this script
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Paths
const BACKEND_PROVIDERS_DIR = resolve(
  __dirname,
  "../../../../backend/providers",
);
const OUTPUT_FILE = resolve(__dirname, "../src/data/modelsMetadata.ts");

/**
 * Find all provider YAML files in the backend/providers directory.
 * @returns Array of { providerId, filePath } objects
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
      `[generate-models-metadata] Error reading backend/providers directory:`,
      err,
    );
    throw err;
  }

  return providers;
}

/**
 * Parse provider YAML file and extract models that can be auto-selected.
 *
 * @param {string} providerId - The provider ID (filename without extension)
 * @param {string} filePath - Path to the provider YAML file
 * @returns {Array} Array of model metadata objects
 */
function parseProviderYaml(providerId, filePath) {
  try {
    const content = readFileSync(filePath, "utf-8");
    const providerData = yaml.parse(content);

    // Handle empty or null YAML
    if (!providerData || typeof providerData !== "object") {
      console.warn(
        `[generate-models-metadata] ${providerId}: YAML file is empty or contains only comments, skipping`,
      );
      return [];
    }

    // Skip providers without models
    if (
      !Array.isArray(providerData.models) ||
      providerData.models.length === 0
    ) {
      return [];
    }

    const models = [];

    for (const model of providerData.models) {
      // Only include models that support text input (AI chat models)
      // This excludes image-only models like Flux for image generation
      if (
        !Array.isArray(model.input_types) ||
        !model.input_types.includes("text")
      ) {
        continue;
      }

      // Only include models that support text input (AI chat models)
      if (
        !Array.isArray(model.input_types) ||
        !model.input_types.includes("text")
      ) {
        continue;
      }

      // Determine tier based on pricing
      let tier = "standard";
      if (model.costs) {
        const inputCost = model.costs.input_per_million_token?.price || 0;
        const outputCost = model.costs.output_per_million_token?.price || 0;
        const avgCost = (inputCost + outputCost) / 2;

        if (avgCost < 0.5) {
          tier = "economy";
        } else if (avgCost > 5) {
          tier = "premium";
        }
      }

      const modelMetadata = {
        id: model.id,
        name: model.name || model.id,
        description: model.description || "",
        provider_id: providerData.provider_id || providerId,
        provider_name: providerData.name || providerId,
        // Use icons/ path for frontend - these are the provider logo SVGs
        logo_svg: `icons/${providerId}.svg`,
        country_origin: model.country_origin || "US",
        input_types: model.input_types || ["text"],
        output_types: model.output_types || ["text"],
        tier: tier,
      };

      // Add reasoning flag if model has it
      if (model.reasoning === true) {
        modelMetadata.reasoning = true;
      }

      // Add search aliases if present
      if (
        Array.isArray(model.search_aliases) &&
        model.search_aliases.length > 0
      ) {
        modelMetadata.search_aliases = model.search_aliases;
      }

      models.push(modelMetadata);
    }

    return models;
  } catch (err) {
    if (err.name === "YAMLParseError" || err.name === "YAMLSyntaxError") {
      console.error(
        `[generate-models-metadata] ${providerId}: YAML syntax error - ${err.message}`,
      );
    } else {
      console.error(
        `[generate-models-metadata] ${providerId}: Error parsing YAML - ${err.message}`,
      );
    }
    return [];
  }
}

/**
 * Generate TypeScript code for modelsMetadata.ts
 * @param {Array} models - Array of model metadata objects
 * @returns {string} TypeScript code
 */
function generateTypeScript(models) {
  const modelEntries = models
    .map((model) => {
      const lines = ["    {"];
      lines.push(`        id: ${JSON.stringify(model.id)},`);
      lines.push(`        name: ${JSON.stringify(model.name)},`);
      lines.push(`        description: ${JSON.stringify(model.description)},`);
      lines.push(`        provider_id: ${JSON.stringify(model.provider_id)},`);
      lines.push(
        `        provider_name: ${JSON.stringify(model.provider_name)},`,
      );
      lines.push(`        logo_svg: ${JSON.stringify(model.logo_svg)},`);
      lines.push(
        `        country_origin: ${JSON.stringify(model.country_origin)},`,
      );
      lines.push(`        input_types: ${JSON.stringify(model.input_types)},`);
      lines.push(
        `        output_types: ${JSON.stringify(model.output_types)},`,
      );

      if (model.reasoning) {
        lines.push(`        reasoning: true,`);
      }

      lines.push(`        tier: ${JSON.stringify(model.tier)},`);

      if (model.search_aliases && model.search_aliases.length > 0) {
        lines.push(
          `        search_aliases: ${JSON.stringify(model.search_aliases)},`,
        );
      }

      lines.push("    },");
      return lines.join("\n");
    })
    .join("\n");

  return `// frontend/packages/ui/src/data/modelsMetadata.ts
//
// WARNING: THIS FILE IS AUTO-GENERATED - DO NOT EDIT MANUALLY
//
// This file is automatically generated from backend provider YAML files during the build process.
// Any manual edits will be overwritten the next time the build runs.
//
// To modify model metadata, edit the source files:
// - Provider definitions: backend/providers/{provider_id}.yml
//
// Generation script: frontend/packages/ui/scripts/generate-models-metadata.js
// This script runs automatically via the 'prebuild' hook in package.json
//
// **Runtime Filtering**: Models are filtered at runtime based on provider health.
// The mentionSearchService uses isProviderHealthy() to filter out models from
// unhealthy providers. If health data is unavailable (offline), all models are shown.
//
// NOTE: All text-capable models are included here. The \`allow_auto_select\` field
// in provider YAMLs is for a different feature (automatic model selection by the system).
//
// **Generated**: ${new Date().toISOString()}
// **Models included**: ${models.length}

/**
 * AI model metadata structure for frontend display.
 */
export interface AIModelMetadata {
    /** Unique model identifier (matches provider YAML) */
    id: string;
    /** Display name for the model */
    name: string;
    /** Brief description of the model's capabilities */
    description: string;
    /** Provider ID (anthropic, openai, google, mistral, etc.) */
    provider_id: string;
    /** Provider display name */
    provider_name: string;
    /** Path to provider logo SVG (relative to static/) */
    logo_svg: string;
    /** ISO 3166-1 alpha-2 country code for model origin */
    country_origin: string;
    /** Supported input types */
    input_types: ('text' | 'image' | 'video' | 'audio')[];
    /** Supported output types */
    output_types: ('text' | 'image')[];
    /** Whether this is a reasoning/thinking model */
    reasoning?: boolean;
    /** Model tier for cost indication: economy, standard, premium */
    tier: 'economy' | 'standard' | 'premium';
    /** Alternative search terms (e.g., "chatgpt" for OpenAI models) */
    search_aliases?: string[];
}

/**
 * Static models metadata for the @ mention dropdown.
 * 
 * This data is generated at build time from backend provider YAML files.
 * All text-capable models are included here.
 * 
 * At runtime, models are filtered based on provider health checks.
 */
export const modelsMetadata: AIModelMetadata[] = [
${modelEntries}
];

/**
 * Get models metadata as a record keyed by model ID.
 */
export function getModelsById(): Record<string, AIModelMetadata> {
    return modelsMetadata.reduce((acc, model) => {
        acc[model.id] = model;
        return acc;
    }, {} as Record<string, AIModelMetadata>);
}

/**
 * Get the top N most popular models for default display.
 * @param count - Number of models to return (default: 4)
 */
export function getTopModels(count: number = 4): AIModelMetadata[] {
    return modelsMetadata.slice(0, count);
}
`;
}

/**
 * Main function to generate modelsMetadata.ts
 */
function main() {
  console.log(
    "[generate-models-metadata] Starting model metadata generation...",
  );
  console.log(
    `[generate-models-metadata] Reading providers from: ${BACKEND_PROVIDERS_DIR}`,
  );

  // Find all provider YAML files
  const providerFiles = findProviderYamlFiles();
  console.log(
    `[generate-models-metadata] Found ${providerFiles.length} provider(s)`,
  );

  // Parse each provider YAML file and collect models
  const allModels = [];
  for (const { providerId, filePath } of providerFiles) {
    console.log(`[generate-models-metadata] Processing: ${providerId}`);
    const models = parseProviderYaml(providerId, filePath);

    if (models.length > 0) {
      console.log(
        `[generate-models-metadata]   ✓ ${providerId}: ${models.length} text model(s)`,
      );
      allModels.push(...models);
    } else {
      console.log(
        `[generate-models-metadata]   - ${providerId}: No text models`,
      );
    }
  }

  // Sort models by provider and name for consistent output
  allModels.sort((a, b) => {
    if (a.provider_id !== b.provider_id) {
      return a.provider_id.localeCompare(b.provider_id);
    }
    return a.name.localeCompare(b.name);
  });

  // Generate TypeScript code
  const tsCode = generateTypeScript(allModels);

  // Write to file
  writeFileSync(OUTPUT_FILE, tsCode, "utf-8");
  console.log(`[generate-models-metadata] Generated: ${OUTPUT_FILE}`);
  console.log(
    `[generate-models-metadata] ✓ Successfully generated metadata for ${allModels.length} model(s)`,
  );
}

// Run the script
main();
