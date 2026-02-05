// frontend/packages/ui/scripts/generate-apps-metadata.js
//
// Build script to generate appsMetadata.ts from backend app.yml files.
// This script reads all app.yml files from backend/apps/ and generates
// a TypeScript file with app metadata for the frontend.
//
// **Usage**: Run this script during the build process to include app metadata
// in the frontend bundle. This allows offline browsing of the App Store.

import { readFileSync, readdirSync, statSync, writeFileSync } from "fs";
import { join, dirname, resolve } from "path";
import { fileURLToPath } from "url";
import yaml from "yaml";

// Get the directory of this script
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Paths
const BACKEND_APPS_DIR = resolve(__dirname, "../../../../backend/apps");
const BACKEND_PROVIDERS_DIR = resolve(
  __dirname,
  "../../../../backend/providers",
);
const OUTPUT_FILE = resolve(__dirname, "../src/data/appsMetadata.ts");

// Check if we should include development items
// Use SERVER_ENVIRONMENT to match backend filtering logic (same as backend/core/api/main.py)
// Default to including development items unless SERVER_ENVIRONMENT is explicitly set to 'production'
// This ensures frontend static metadata matches what the backend API would return
const SERVER_ENVIRONMENT = (
  process.env.SERVER_ENVIRONMENT || "development"
).toLowerCase();
const INCLUDE_DEVELOPMENT =
  SERVER_ENVIRONMENT !== "production" ||
  process.env.INCLUDE_DEV_APPS === "true";

/**
 * Recursively find all app.yml files in the backend/apps directory.
 * @returns Array of { appId, filePath } objects
 */
function findAppYamlFiles() {
  const apps = [];

  try {
    const entries = readdirSync(BACKEND_APPS_DIR, { withFileTypes: true });

    for (const entry of entries) {
      if (entry.isDirectory()) {
        const appId = entry.name;
        const appYmlPath = join(BACKEND_APPS_DIR, appId, "app.yml");

        try {
          if (statSync(appYmlPath).isFile()) {
            apps.push({ appId, filePath: appYmlPath });
          }
        } catch (err) {
          // app.yml doesn't exist for this app, skip it
          console.warn(
            `[generate-apps-metadata] No app.yml found for app: ${appId}`,
          );
        }
      }
    }
  } catch (err) {
    console.error(
      `[generate-apps-metadata] Error reading backend/apps directory:`,
      err,
    );
    throw err;
  }

  return apps;
}

/**
 * Auto-prepend prefix to translation key if it doesn't already have it.
 * This allows simplified keys in app.yml (e.g., "web.text" instead of "apps.web.text").
 *
 * @param {string} key - The translation key (may or may not have prefix)
 * @param {string} prefix - The prefix to add (e.g., "apps.", "app_skills.")
 * @returns {string} Translation key with prefix
 */
function normalizeTranslationKey(key, prefix) {
  if (!key || typeof key !== "string") {
    return key;
  }

  const trimmedKey = key.trim();

  // If key already starts with the prefix, return as-is
  if (trimmedKey.startsWith(prefix)) {
    return trimmedKey;
  }

  // Otherwise, prepend the prefix
  return prefix + trimmedKey;
}

/**
 * Load provider YAML file and return parsed data.
 *
 * @param {string} providerId - Provider ID (e.g., "brave", "alibaba")
 * @returns {Object|null} Parsed provider YAML data, or null if not found
 */
function loadProviderYaml(providerId) {
  try {
    const providerPath = join(BACKEND_PROVIDERS_DIR, `${providerId}.yml`);
    if (!statSync(providerPath).isFile()) {
      return null;
    }
    const content = readFileSync(providerPath, "utf-8");
    return yaml.parse(content);
  } catch (err) {
    // Provider file doesn't exist or can't be read
    return null;
  }
}

/**
 * Auto-discover providers that have models for a specific app skill.
 * Scans all provider YAML files and returns provider names for those that have
 * at least one model with matching `for_app_skill`.
 *
 * @param {string} appSkill - The app.skill identifier (e.g., "ai.ask", "images.generate")
 * @returns {string[]} Array of provider display names (e.g., ["Alibaba", "Anthropic", "Google"])
 */
function discoverProvidersForAppSkill(appSkill) {
  const providers = [];

  try {
    const files = readdirSync(BACKEND_PROVIDERS_DIR);

    for (const file of files) {
      if (!file.endsWith(".yml") && !file.endsWith(".yaml")) {
        continue;
      }

      try {
        const filePath = join(BACKEND_PROVIDERS_DIR, file);
        const content = readFileSync(filePath, "utf-8");
        const providerData = yaml.parse(content);

        if (!providerData || !Array.isArray(providerData.models)) {
          continue;
        }

        // Check if any model in this provider has the matching for_app_skill
        const hasMatchingModel = providerData.models.some(
          (model) => model.for_app_skill === appSkill,
        );

        if (hasMatchingModel) {
          // Use the provider's display name from YAML, or capitalize the filename
          const providerName =
            providerData.name ||
            file
              .replace(/\.(yml|yaml)$/, "")
              .charAt(0)
              .toUpperCase() + file.replace(/\.(yml|yaml)$/, "").slice(1);
          providers.push(providerName);
        }
      } catch (err) {
        // Skip files that can't be parsed
        console.warn(
          `[generate-apps-metadata] Could not parse provider file ${file}: ${err.message}`,
        );
      }
    }
  } catch (err) {
    console.error(
      `[generate-apps-metadata] Error discovering providers for ${appSkill}:`,
      err,
    );
  }

  // Return sorted list of unique provider names
  return [...new Set(providers)].sort();
}

/**
 * Map provider name from app.yml to provider ID (provider YAML filename).
 *
 * @param {string} providerName - Provider name from app.yml (e.g., "Brave", "Google", "Firecrawl", "YouTube")
 * @param {string} appId - App ID for context (e.g., "maps" for Google Maps)
 * @returns {string|null} Provider ID (lowercase, matches provider YAML filename) or null if unknown
 */
function mapProviderNameToId(providerName, appId) {
  const normalized = providerName.toLowerCase().trim();

  // Handle special cases
  if (providerName === "Google" && appId === "maps") {
    return "google_maps";
  }
  // YouTube -> youtube
  if (providerName === "YouTube") {
    return "youtube";
  }
  // Most providers just need to be lowercased (Brave -> brave, Firecrawl -> firecrawl, etc.)
  return normalized;
}

/**
 * Extract pricing from provider YAML for a specific model.
 *
 * @param {string} providerId - Provider ID (e.g., "alibaba", "brave")
 * @param {string} modelId - Model ID (e.g., "qwen3-235b-a22b-2507" or null for provider-level pricing)
 * @returns {Object|null} Pricing object in SkillPricing format, or null if not found
 */
function extractProviderPricing(providerId, modelId = null) {
  const providerData = loadProviderYaml(providerId);
  if (!providerData) {
    return null;
  }

  // For provider-level pricing (e.g., Brave per_request_credits)
  if (!modelId && providerData.pricing) {
    const pricing = {};

    // Check for per_request_credits (Brave)
    if (providerData.pricing.per_request_credits !== undefined) {
      pricing.fixed = providerData.pricing.per_request_credits;
    }

    // Check for per_unit pricing
    if (providerData.pricing.per_unit) {
      pricing.per_unit = providerData.pricing.per_unit;
    }

    // Check for per_minute pricing
    if (providerData.pricing.per_minute !== undefined) {
      pricing.per_minute = providerData.pricing.per_minute;
    }

    if (Object.keys(pricing).length > 0) {
      return pricing;
    }
  }

  // For model-level pricing (e.g., Alibaba models)
  if (modelId && providerData.models) {
    const model = providerData.models.find((m) => m.id === modelId);
    if (model && model.pricing) {
      const pricing = {};

      // Extract token-based pricing
      if (model.pricing.tokens) {
        pricing.tokens = {};
        if (
          model.pricing.tokens.input &&
          model.pricing.tokens.input.per_credit_unit !== undefined
        ) {
          pricing.tokens.input = {
            per_credit_unit: model.pricing.tokens.input.per_credit_unit,
          };
        }
        if (
          model.pricing.tokens.output &&
          model.pricing.tokens.output.per_credit_unit !== undefined
        ) {
          pricing.tokens.output = {
            per_credit_unit: model.pricing.tokens.output.per_credit_unit,
          };
        }
      }

      // Extract per_unit pricing
      if (model.pricing.per_unit) {
        pricing.per_unit = model.pricing.per_unit;
      }

      // Extract per_minute pricing
      if (model.pricing.per_minute !== undefined) {
        pricing.per_minute = model.pricing.per_minute;
      }

      // Extract fixed pricing
      if (model.pricing.fixed !== undefined) {
        pricing.fixed = model.pricing.fixed;
      }

      if (Object.keys(pricing).length > 0) {
        return pricing;
      }
    }
  }

  return null;
}

/**
 * Extract pricing from skill_config.default_llms for AI ask skill.
 * Looks up the default model and extracts pricing from provider YAML.
 *
 * @param {Object} skillConfig - skill_config object from app.yml
 * @returns {Object|null} Pricing object in SkillPricing format, or null if not found
 */
function extractPricingFromSkillConfig(skillConfig) {
  if (!skillConfig || !skillConfig.default_llms) {
    return null;
  }

  const defaultLlms = skillConfig.default_llms;

  // Use main_processing_simple as the default model (primary model for AI ask skill)
  const mainModelId = defaultLlms.main_processing_simple;
  if (!mainModelId) {
    return null;
  }

  // Parse model ID format: "provider/model_id" (e.g., "alibaba/qwen3-235b-a22b-2507")
  const modelParts = mainModelId.split("/");
  if (modelParts.length !== 2) {
    return null;
  }

  const providerId = modelParts[0].toLowerCase(); // Normalize to lowercase
  const modelId = modelParts[1];

  // Extract pricing from provider YAML
  return extractProviderPricing(providerId, modelId);
}

/**
 * Parse app.yml file and convert to frontend AppMetadata format.
 * Only includes production-stage skills.
 *
 * @param {string} appId - The app ID (directory name)
 * @param {string} filePath - Path to the app.yml file
 * @returns {Object|null} App metadata in frontend format, or null if invalid
 */
function parseAppYaml(appId, filePath) {
  try {
    const content = readFileSync(filePath, "utf-8");
    const appData = yaml.parse(content);

    // Handle empty or null YAML (e.g., files with only comments)
    if (!appData || typeof appData !== "object") {
      console.warn(
        `[generate-apps-metadata] ${appId}: YAML file is empty or contains only comments, skipping`,
      );
      return null;
    }

    // Check if app has required fields (at least name/name_translation_key or description/description_translation_key)
    const hasName =
      appData.name && typeof appData.name === "string" && appData.name.trim();
    const hasNameTranslationKey =
      appData.name_translation_key &&
      typeof appData.name_translation_key === "string" &&
      appData.name_translation_key.trim();
    const hasDescription =
      appData.description &&
      typeof appData.description === "string" &&
      appData.description.trim();
    const hasDescriptionTranslationKey =
      appData.description_translation_key &&
      typeof appData.description_translation_key === "string" &&
      appData.description_translation_key.trim();

    if (
      !hasName &&
      !hasNameTranslationKey &&
      !hasDescription &&
      !hasDescriptionTranslationKey
    ) {
      console.warn(
        `[generate-apps-metadata] ${appId}: Missing required fields (name/name_translation_key and description/description_translation_key), skipping`,
      );
      return null;
    }

    // Note: We do NOT check app-level stage. Apps are included if ANY of their
    // skills, settings_and_memories, or focuses have a stage matching the environment.
    // This allows apps to have mixed-stage content and still appear in the App Store
    // if they have at least one item matching the current environment.

    // Extract app metadata
    // Auto-prepend "apps." prefix to app-level translation keys if not already present
    const appMetadata = {
      id: appId,
      name: hasName ? (appData.name || "").trim() : undefined,
      name_translation_key: hasNameTranslationKey
        ? normalizeTranslationKey(
            (appData.name_translation_key || "").trim(),
            "apps.",
          )
        : undefined,
      description: hasDescription
        ? (appData.description || "").trim()
        : undefined,
      description_translation_key: hasDescriptionTranslationKey
        ? normalizeTranslationKey(
            (appData.description_translation_key || "").trim(),
            "apps.",
          )
        : undefined,
      icon_image: appData.icon_image
        ? (appData.icon_image || "").trim()
        : undefined,
      icon_colorgradient: appData.icon_colorgradient
        ? {
            start: (appData.icon_colorgradient.start || "").trim(),
            end: (appData.icon_colorgradient.end || "").trim(),
          }
        : undefined,
      skills: [],
      focus_modes: [],
      settings_and_memories: [],
      providers: [], // Will be populated from skills
      category: appData.category ? (appData.category || "").trim() : undefined,
      last_updated: appData.last_updated
        ? (appData.last_updated || "").trim()
        : undefined,
    };

    // Collect all unique providers from skills
    const providersSet = new Set();

    // Process skills - include production-stage skills, and development if INCLUDE_DEVELOPMENT is true
    if (Array.isArray(appData.skills)) {
      for (const skill of appData.skills) {
        const stage = (skill.stage || "development").trim().toLowerCase();
        // Only include production-stage skills, or development if INCLUDE_DEVELOPMENT is true
        if (
          stage !== "production" &&
          (!INCLUDE_DEVELOPMENT || stage !== "development")
        ) {
          continue;
        }

        // Auto-prepend "app_skills." prefix to skill translation keys if not already present
        const skillMetadata = {
          id: (skill.id || "").trim(),
          name_translation_key: normalizeTranslationKey(
            (skill.name_translation_key || "").trim(),
            "app_skills.",
          ),
          description_translation_key: normalizeTranslationKey(
            (skill.description_translation_key || "").trim(),
            "app_skills.",
          ),
        };

        // Extract providers from skill
        // For skills with for_app_skill pattern (e.g., "ai.ask"), auto-discover providers
        // from provider YAML files that have models with matching for_app_skill
        const appSkillId = `${appId}.${skill.id}`; // e.g., "ai.ask", "images.generate"
        let skillProviders = [];

        if (Array.isArray(skill.providers) && skill.providers.length > 0) {
          // Use explicitly defined providers if present
          skillProviders = skill.providers
            .map((p) => (p || "").trim())
            .filter((p) => p.length > 0);
        } else {
          // Auto-discover providers from provider YAML files
          // This ensures the providers list stays in sync with available models
          skillProviders = discoverProvidersForAppSkill(appSkillId);
          if (skillProviders.length > 0) {
            console.log(
              `[generate-apps-metadata]   Auto-discovered ${skillProviders.length} provider(s) for ${appSkillId}: ${skillProviders.join(", ")}`,
            );
          }
        }

        if (skillProviders.length > 0) {
          skillMetadata.providers = skillProviders;
          // Add to app-level providers set
          skillProviders.forEach((provider) => providersSet.add(provider));
        }

        // Process pricing if present
        let pricing = null;

        // First, check if skill has explicit pricing in app.yml
        if (skill.pricing) {
          pricing = {};

          if (skill.pricing.tokens) {
            pricing.tokens = skill.pricing.tokens;
          }
          if (skill.pricing.per_unit) {
            pricing.per_unit = skill.pricing.per_unit;
          }
          if (skill.pricing.per_minute !== undefined) {
            pricing.per_minute = skill.pricing.per_minute;
          }
          if (skill.pricing.fixed !== undefined) {
            pricing.fixed = skill.pricing.fixed;
          }

          if (Object.keys(pricing).length === 0) {
            pricing = null;
          }
        }

        // If no explicit pricing, try to extract from skill_config.default_llms (for AI ask skill)
        if (!pricing && skill.skill_config && skill.skill_config.default_llms) {
          pricing = extractPricingFromSkillConfig(skill.skill_config);
        }

        // If still no pricing, try to extract from provider YAML based on skill providers
        if (!pricing && skill.providers && skill.providers.length > 0) {
          const providerName = skill.providers[0];
          const providerId = mapProviderNameToId(providerName, appId);

          // Extract provider-level pricing for all skills with providers
          if (providerId) {
            pricing = extractProviderPricing(providerId);
          }
        }

        // Fallback: if no pricing found, default to 1 credit minimum
        // No skill should ever be free - minimum charge is always 1 credit
        if (!pricing || Object.keys(pricing).length === 0) {
          pricing = { fixed: 1 };
        }

        // Only set pricing if we have valid pricing data
        if (pricing && Object.keys(pricing).length > 0) {
          skillMetadata.pricing = pricing;
        }

        // Only add skill if it has required fields
        if (
          skillMetadata.id &&
          skillMetadata.name_translation_key &&
          skillMetadata.description_translation_key
        ) {
          appMetadata.skills.push(skillMetadata);
        }
      }
    }

    // Convert providers set to sorted array
    appMetadata.providers = Array.from(providersSet).sort();

    // Include provider_display_order if defined in app.yml
    // This allows apps to specify a custom display order for provider icons
    // in the App Store preview cards. Providers listed here appear first,
    // followed by any remaining providers not in the list.
    if (
      Array.isArray(appData.provider_display_order) &&
      appData.provider_display_order.length > 0
    ) {
      appMetadata.provider_display_order = appData.provider_display_order
        .map((p) => (p || "").trim())
        .filter((p) => p.length > 0);
    }

    // Process focus modes - include production-stage focus modes, and development if INCLUDE_DEVELOPMENT is true
    const focusModes = appData.focuses || appData.focus_modes || [];
    if (Array.isArray(focusModes)) {
      for (const focus of focusModes) {
        const stage = (focus.stage || "development").trim().toLowerCase();
        // Only include production-stage focus modes, or development if INCLUDE_DEVELOPMENT is true
        if (
          stage !== "production" &&
          (!INCLUDE_DEVELOPMENT || stage !== "development")
        ) {
          continue;
        }

        // Auto-prepend "app_focus_modes." prefix to focus mode translation keys if not already present
        const focusMetadata = {
          id: (focus.id || "").trim(),
          name_translation_key: normalizeTranslationKey(
            (focus.name_translation_key || "").trim(),
            "app_focus_modes.",
          ),
          description_translation_key: normalizeTranslationKey(
            (focus.description_translation_key || "").trim(),
            "app_focus_modes.",
          ),
        };

        if (
          focusMetadata.id &&
          focusMetadata.name_translation_key &&
          focusMetadata.description_translation_key
        ) {
          appMetadata.focus_modes.push(focusMetadata);
        }
      }
    }

    // Process settings_and_memories - include production-stage items, and development if INCLUDE_DEVELOPMENT is true
    // Note: settings_and_memories is the field name in app.yml and is used consistently in the frontend
    const settingsAndMemories = appData.settings_and_memories || [];
    if (Array.isArray(settingsAndMemories)) {
      for (const item of settingsAndMemories) {
        // Stage field is required - no default
        const stage = item.stage
          ? (item.stage || "").trim().toLowerCase()
          : null;
        if (!stage) {
          continue;
        }
        // Only include production-stage settings_and_memories, or development if INCLUDE_DEVELOPMENT is true
        if (
          stage !== "production" &&
          (!INCLUDE_DEVELOPMENT || stage !== "development")
        ) {
          continue;
        }

        // Auto-prepend "app_settings_memories." prefix to settings/memory translation keys if not already present
        const memoryMetadata = {
          id: (item.id || "").trim(),
          name_translation_key: normalizeTranslationKey(
            (item.name_translation_key || "").trim(),
            "app_settings_memories.",
          ),
          description_translation_key: normalizeTranslationKey(
            (item.description_translation_key || "").trim(),
            "app_settings_memories.",
          ),
          type: (item.type || "single").trim(),
          // Include schema_definition if present (for dynamic form generation)
          schema_definition: item.schema || item.schema_definition || undefined,
        };

        if (
          memoryMetadata.id &&
          memoryMetadata.name_translation_key &&
          memoryMetadata.description_translation_key
        ) {
          appMetadata.settings_and_memories.push(memoryMetadata);
        }
      }
    }

    // Also process legacy memory_fields/memory for backward compatibility
    const memoryFields = appData.memory_fields || appData.memory || [];
    if (Array.isArray(memoryFields)) {
      for (const memory of memoryFields) {
        // Stage field is required - no default
        const stage = memory.stage
          ? (memory.stage || "").trim().toLowerCase()
          : null;
        if (!stage) {
          continue;
        }
        // Only include production-stage memory fields, or development if INCLUDE_DEVELOPMENT is true
        if (
          stage !== "production" &&
          (!INCLUDE_DEVELOPMENT || stage !== "development")
        ) {
          continue;
        }

        // Auto-prepend "app_settings_memories." prefix to legacy memory field translation keys if not already present
        const memoryMetadata = {
          id: (memory.id || "").trim(),
          name_translation_key: normalizeTranslationKey(
            (memory.name_translation_key || "").trim(),
            "app_settings_memories.",
          ),
          description_translation_key: normalizeTranslationKey(
            (memory.description_translation_key || "").trim(),
            "app_settings_memories.",
          ),
          type: (memory.type || "single").trim(),
        };

        if (
          memoryMetadata.id &&
          memoryMetadata.name_translation_key &&
          memoryMetadata.description_translation_key
        ) {
          appMetadata.settings_and_memories.push(memoryMetadata);
        }
      }
    }

    // Only include apps that have at least one skill, focus mode, or settings_and_memories
    // with a stage matching the current environment (production or development).
    // Apps are included if ANY of their items match the environment stage, regardless
    // of app-level stage field (which we don't check).
    const hasContent =
      appMetadata.skills.length > 0 ||
      appMetadata.focus_modes.length > 0 ||
      appMetadata.settings_and_memories.length > 0;

    if (!hasContent) {
      const stageType = INCLUDE_DEVELOPMENT
        ? "production or development"
        : "production";
      console.warn(
        `[generate-apps-metadata] ${appId}: No ${stageType} skills, focus modes, or settings_and_memories found. Excluding from App Store.`,
      );
      return null;
    }

    return appMetadata;
  } catch (err) {
    // Handle YAML parsing errors more gracefully
    if (err.name === "YAMLParseError" || err.name === "YAMLSyntaxError") {
      console.error(
        `[generate-apps-metadata] ${appId}: YAML syntax error - ${err.message}`,
      );
      if (err.linePos && err.linePos.length > 0) {
        const pos = err.linePos[0];
        console.error(
          `[generate-apps-metadata] ${appId}: Error at line ${pos.line}, column ${pos.col}`,
        );
      }
    } else {
      console.error(
        `[generate-apps-metadata] ${appId}: Error parsing app.yml - ${err.message}`,
      );
    }
    return null;
  }
}

/**
 * Generate TypeScript code for appsMetadata.ts
 * @param {Object} appsMetadata - Object mapping app IDs to app metadata
 * @returns {string} TypeScript code
 */
function generateTypeScript(appsMetadata) {
  const apps = Object.entries(appsMetadata)
    .map(([appId, app]) => {
      // Format app metadata as TypeScript object
      const lines = [`    "${appId}": {`];
      lines.push(`        id: "${app.id}",`);
      if (app.name !== undefined) {
        lines.push(`        name: ${JSON.stringify(app.name)},`);
      }
      if (app.name_translation_key !== undefined) {
        lines.push(
          `        name_translation_key: ${JSON.stringify(app.name_translation_key)},`,
        );
      }
      if (app.description !== undefined) {
        lines.push(`        description: ${JSON.stringify(app.description)},`);
      }
      if (app.description_translation_key !== undefined) {
        lines.push(
          `        description_translation_key: ${JSON.stringify(app.description_translation_key)},`,
        );
      }

      if (app.icon_image) {
        lines.push(`        icon_image: ${JSON.stringify(app.icon_image)},`);
      }

      if (app.icon_colorgradient) {
        lines.push(`        icon_colorgradient: {`);
        lines.push(
          `            start: ${JSON.stringify(app.icon_colorgradient.start)},`,
        );
        lines.push(
          `            end: ${JSON.stringify(app.icon_colorgradient.end)}`,
        );
        lines.push(`        },`);
      }

      // Providers array (if present)
      if (app.providers && app.providers.length > 0) {
        lines.push(`        providers: [`);
        for (const provider of app.providers) {
          lines.push(`            ${JSON.stringify(provider)},`);
        }
        lines.push(`        ],`);
      }

      // Provider display order (if present) - controls icon order in App Store
      if (app.provider_display_order && app.provider_display_order.length > 0) {
        lines.push(`        provider_display_order: [`);
        for (const provider of app.provider_display_order) {
          lines.push(`            ${JSON.stringify(provider)},`);
        }
        lines.push(`        ],`);
      }

      // Category (if present)
      if (app.category) {
        lines.push(`        category: ${JSON.stringify(app.category)},`);
      }

      // last_updated (if present)
      if (app.last_updated) {
        lines.push(
          `        last_updated: ${JSON.stringify(app.last_updated)},`,
        );
      }

      // Skills array
      lines.push(`        skills: [`);
      for (const skill of app.skills) {
        lines.push(`            {`);
        lines.push(`                id: ${JSON.stringify(skill.id)},`);
        lines.push(
          `                name_translation_key: ${JSON.stringify(skill.name_translation_key)},`,
        );
        lines.push(
          `                description_translation_key: ${JSON.stringify(skill.description_translation_key)},`,
        );
        if (skill.pricing) {
          lines.push(
            `                pricing: ${JSON.stringify(skill.pricing)},`,
          );
        }
        if (skill.providers && skill.providers.length > 0) {
          lines.push(
            `                providers: ${JSON.stringify(skill.providers)},`,
          );
        }
        lines.push(`            },`);
      }
      lines.push(`        ],`);

      // Focus modes array
      lines.push(`        focus_modes: [`);
      for (const focus of app.focus_modes) {
        lines.push(`            {`);
        lines.push(`                id: ${JSON.stringify(focus.id)},`);
        lines.push(
          `                name_translation_key: ${JSON.stringify(focus.name_translation_key)},`,
        );
        lines.push(
          `                description_translation_key: ${JSON.stringify(focus.description_translation_key)}`,
        );
        lines.push(`            },`);
      }
      lines.push(`        ],`);

      // Settings and memories array (maps to 'settings_and_memories' in app.yml)
      lines.push(`        settings_and_memories: [`);
      if (
        app.settings_and_memories &&
        Array.isArray(app.settings_and_memories)
      ) {
        for (const memory of app.settings_and_memories) {
          lines.push(`            {`);
          lines.push(`                id: ${JSON.stringify(memory.id)},`);
          lines.push(
            `                name_translation_key: ${JSON.stringify(memory.name_translation_key)},`,
          );
          lines.push(
            `                description_translation_key: ${JSON.stringify(memory.description_translation_key)},`,
          );
          // Include schema_definition if present (for dynamic form generation)
          if (memory.schema_definition) {
            lines.push(`                type: ${JSON.stringify(memory.type)},`);
            const schemaStr = JSON.stringify(
              memory.schema_definition,
              null,
              16,
            );
            // Indent each line of the schema to match the indentation level
            const indentedSchema = schemaStr
              .split("\n")
              .map((line, index) => {
                if (index === 0) {
                  return `                schema_definition: ${line}`;
                }
                return `                ${line}`;
              })
              .join("\n");
            lines.push(indentedSchema);
          } else {
            lines.push(`                type: ${JSON.stringify(memory.type)}`);
          }
          lines.push(`            },`);
        }
      }
      lines.push(`        ]`);

      lines.push(`    },`);
      return lines.join("\n");
    })
    .join("\n\n");

  return `// frontend/packages/ui/src/data/appsMetadata.ts
//
// ⚠️  WARNING: THIS FILE IS AUTO-GENERATED - DO NOT EDIT MANUALLY ⚠️
//
// This file is automatically generated from backend app.yml files during the build process.
// Any manual edits will be overwritten the next time the build runs.
//
// To modify app metadata, edit the source files:
// - App definitions: backend/apps/{app_id}/app.yml
// - Schema: backend/shared/python_schemas/app_metadata_schemas.py
//
// Generation script: frontend/packages/ui/scripts/generate-apps-metadata.js
// This script runs automatically via the 'prebuild' hook in package.json
//
// **Build Process**: 
// This file is generated during the build process by running:
//   npm run generate-apps-metadata
//   (or automatically via: npm run build)
//
// **Note**: Only production-stage skills are included. Development skills
// are only available on development servers, not production servers.
//
// **Usage**: Import and use directly - no API calls needed
// \`\`\`typescript
// import { appsMetadata } from '@repo/ui/data/appsMetadata';
// \`\`\`

import type { AppMetadata } from '../types/apps';

/**
 * Static apps metadata included in the build.
 * 
 * This data is generated at build time from backend app.yml files and included
 * in the web app bundle, allowing offline browsing of available apps, skills, and pricing.
 * 
 * **Generated**: ${new Date().toISOString()}
 * **Apps included**: ${Object.keys(appsMetadata).length}
 */
export const appsMetadata: Record<string, AppMetadata> = {
${apps}
};
`;
}

/**
 * Main function to generate appsMetadata.ts
 */
function main() {
  console.log("[generate-apps-metadata] Starting app metadata generation...");
  console.log(
    `[generate-apps-metadata] Server environment: ${SERVER_ENVIRONMENT}`,
  );
  console.log(
    `[generate-apps-metadata] Including development apps: ${INCLUDE_DEVELOPMENT}`,
  );
  console.log(
    `[generate-apps-metadata] Reading apps from: ${BACKEND_APPS_DIR}`,
  );

  // Find all app.yml files
  const appFiles = findAppYamlFiles();
  console.log(`[generate-apps-metadata] Found ${appFiles.length} app(s)`);

  // Parse each app.yml file
  const appsMetadata = {};
  for (const { appId, filePath } of appFiles) {
    console.log(`[generate-apps-metadata] Processing: ${appId}`);
    const appMetadata = parseAppYaml(appId, filePath);

    if (appMetadata) {
      appsMetadata[appId] = appMetadata;
      const skillsCount = appMetadata.skills.length;
      const focusCount = appMetadata.focus_modes.length;
      const memoryCount = appMetadata.settings_and_memories.length;
      console.log(
        `[generate-apps-metadata]   ✓ ${appId}: ${skillsCount} skill(s), ${focusCount} focus mode(s), ${memoryCount} settings/memory field(s)`,
      );
    } else {
      console.warn(
        `[generate-apps-metadata]   ✗ ${appId}: Failed to parse or excluded (no production content)`,
      );
    }
  }

  // Generate TypeScript code
  const tsCode = generateTypeScript(appsMetadata);

  // Write to file
  writeFileSync(OUTPUT_FILE, tsCode, "utf-8");
  console.log(`[generate-apps-metadata] Generated: ${OUTPUT_FILE}`);
  console.log(
    `[generate-apps-metadata] ✓ Successfully generated metadata for ${Object.keys(appsMetadata).length} app(s)`,
  );
}

// Run the script
main();
