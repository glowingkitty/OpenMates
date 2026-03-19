// frontend/packages/secret-scanner/src/types.ts
/**
 * @file Core type definitions for the secret scanner package.
 *
 * Provides interfaces for secret registry entries, detection results,
 * and redaction/restoration mappings. Used by both CLI and web app
 * for consistent secret handling.
 *
 * Architecture: docs/architecture/pii-protection.md
 */

/**
 * Sources from which secrets can be discovered.
 * Each source corresponds to a file type or system that stores credentials.
 */
export type SecretSource =
  | "env"        // .env, .env.*, .envrc files
  | "aws"        // ~/.aws/credentials
  | "ssh"        // ~/.ssh/id_rsa, id_ed25519, etc.
  | "gcloud"     // ~/.config/gcloud/application_default_credentials.json
  | "process"    // Process environment variables matching secret patterns
  | "settings"   // Settings & Memories synced from web UI
  | "custom";    // User-configured additional paths

/**
 * Types of secrets that can be detected. Aligned with PIIType in
 * piiDetectionService.ts for vendor-specific patterns, plus additional
 * types for CLI-specific credential sources.
 */
export type SecretType =
  // API keys (same as piiDetectionService.ts)
  | "AWS_ACCESS_KEY"
  | "AWS_SECRET_KEY"
  | "OPENAI_KEY"
  | "ANTHROPIC_KEY"
  | "GITHUB_PAT"
  | "STRIPE_KEY"
  | "GOOGLE_API_KEY"
  | "SLACK_TOKEN"
  | "TWILIO_KEY"
  | "SENDGRID_KEY"
  | "AZURE_KEY"
  | "HUGGINGFACE_KEY"
  | "DATABRICKS_TOKEN"
  | "FIREBASE_KEY"
  | "GENERIC_SECRET"
  | "PRIVATE_KEY"
  | "JWT"
  // Personal data (from Settings & Memories)
  | "PERSONAL_DATA"
  // Environment variable (known from registry, not pattern-matched)
  | "ENV_VAR";

/**
 * A single entry in the in-memory secret registry.
 * Maps a plaintext secret value to its metadata and token.
 */
export interface SecretRegistryEntry {
  /** The plaintext secret value (held encrypted in memory where possible) */
  value: string;
  /** Generated placeholder token, e.g. [OPENAI_KEY_f9d] */
  token: string;
  /** Where the secret was found */
  source: SecretSource;
  /** Variable/key name, e.g. "OPENAI_API_KEY" */
  name: string;
  /** Detection type for categorization */
  type: SecretType;
  /** Character length of the original value */
  length: number;
}

/**
 * A mapping between a placeholder token and its original value.
 * Created during redaction, used for restoration.
 * Stored encrypted alongside message data (same pattern as encrypted_pii_mappings).
 */
export interface SecretMapping {
  /** The placeholder token, e.g. [OPENAI_KEY_f9d] */
  placeholder: string;
  /** The original secret value */
  original: string;
  /** Secret type for categorization and styling */
  type: SecretType;
  /** Where the secret was discovered */
  source: SecretSource;
}

/**
 * Result of a redaction operation.
 */
export interface RedactResult {
  /** Text with all secrets replaced by placeholder tokens */
  redacted: string;
  /** Mappings for all replaced secrets (for later restoration) */
  mappings: SecretMapping[];
}

/**
 * Options for configuring the secret scanner.
 */
export interface ScannerOptions {
  /** Minimum secret length to consider for registry-based scanning (default: 8) */
  minSecretLength?: number;
  /** Number of suffix characters to use in placeholder tokens (default: 3) */
  suffixLength?: number;
  /** Whether to scan for vendor-specific API key patterns (default: true) */
  enablePatternDetection?: boolean;
  /** Whether to scan against the known-value registry (default: true) */
  enableRegistryDetection?: boolean;
  /** Personal data entries from Settings & Memories for substring matching */
  personalDataEntries?: PersonalDataEntry[];
}

/**
 * A user-defined personal data entry from Settings & Memories.
 * Used for substring-based detection of names, addresses, etc.
 * Mirrors PersonalDataForDetection in piiDetectionService.ts.
 */
export interface PersonalDataEntry {
  /** Unique entry ID */
  id: string;
  /** The text to find (case-insensitive substring match) */
  textToHide: string;
  /** The placeholder to replace it with, e.g. [MY_FIRST_NAME] */
  replaceWith: string;
  /** Optional additional text lines to detect (for address entries) */
  additionalTexts?: string[];
}

/**
 * Environment variable name patterns that indicate a secret value.
 * Used to filter process.env for registry population.
 */
export const SECRET_ENV_PATTERNS = [
  /_KEY$/,
  /_SECRET$/,
  /_TOKEN$/,
  /_PASSWORD$/,
  /_PASSWD$/,
  /_CREDENTIAL$/,
  /^API_KEY$/,
  /^AUTH_TOKEN$/,
  /^SECRET$/,
  /^DATABASE_URL$/,
  /^REDIS_URL$/,
  /^MONGODB_URI$/,
  /^AMQP_URL$/,
] as const;
