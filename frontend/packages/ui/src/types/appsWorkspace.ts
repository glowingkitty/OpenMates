import type { Schema } from '../components/workflows/workflowBuilder';

/** Public, account-independent skill presentation returned by the Apps API. */
export interface AppsSkillDetails {
  app_id: string;
  skill_id: string;
  slug: string;
  name: string;
  name_translation_key: string;
  description: string;
  description_translation_key: string;
  icon_image: string | null;
  input_schema: Schema;
  primary_fields: string[];
  defaults: Record<string, unknown>;
  pricing: Record<string, unknown> | null;
  providers: Record<string, unknown>[];
  models: Record<string, unknown>[];
  anonymous_allowed: boolean;
  execution_available: boolean;
  unavailable_reason: string | null;
  execution_mode: 'sync' | 'async_job' | 'sandbox' | string | null;
}

export type AppsSkillGuestEligibility = { allowed: boolean; reason: string | null };

export interface AppsSkillResponse {
  success?: boolean;
  data?: unknown;
  error?: string;
  credits_charged?: number;
  [key: string]: unknown;
}
