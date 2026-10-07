// frontend/packages/ui/src/data/modelsMetadata.d.ts
// Type declarations for the gitignored generated modelsMetadata.ts module.
// The runtime file is produced by frontend/packages/ui/scripts/generate-models-metadata.js
// during UI prepare/prebuild steps, but changed-file TypeScript checks can run
// before generated artifacts exist in a clean worktree.

export interface ModelServerInfo {
  id: string;
  name: string;
  region: "EU" | "US" | "APAC" | "global";
}

export interface ModelPricingPerUnit {
  credits: number;
  unit_name: string;
}

export interface ModelPricing {
  input_tokens_per_credit?: number;
  output_tokens_per_credit?: number;
  cache_read_tokens_per_credit?: number;
  cache_write_tokens_per_credit?: number;
  cache_write_1h_tokens_per_credit?: number;
  per_unit?: ModelPricingPerUnit;
  per_minute?: number;
  per_second?: number;
}

export interface AIModelMetadata {
  id: string;
  name: string;
  description: string;
  show_in_mentions?: boolean;
  provider_id: string;
  provider_name: string;
  logo_svg: string;
  country_origin: string;
  input_types: Array<"text" | "image" | "video" | "audio">;
  output_types: Array<"text" | "image">;
  for_app_skill?: string;
  reasoning?: boolean;
  tier: "economy" | "standard" | "premium";
  capability_level?: "low" | "medium" | "high" | "max";
  release_date?: string;
  servers?: ModelServerInfo[];
  default_server?: string;
  pricing?: ModelPricing;
  cache_pricing?: { enabled: boolean; write_billing?: "included_in_input" | "separate"; write_ttl?: string; pricing_version?: string; source_url?: string; reviewed_on?: string; effective_from?: string; expires_on?: string; status?: string; eligible_hosts?: string[]; cache_write_1h_hosts?: string[]; requires_cache_write_metric?: boolean; requires_cache_retention_metric?: boolean };
  search_aliases?: string[];
}

export const modelsMetadata: AIModelMetadata[];

export function getModelsById(): Record<string, AIModelMetadata>;

export function getTopModels(count?: number): AIModelMetadata[];
