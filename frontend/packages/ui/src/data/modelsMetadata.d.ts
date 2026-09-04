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
  search_aliases?: string[];
}

export const modelsMetadata: AIModelMetadata[];

export function getModelsById(): Record<string, AIModelMetadata>;

export function getTopModels(count?: number): AIModelMetadata[];
