// frontend/packages/secret-scanner/src/patterns.ts
/**
 * @file Vendor-specific secret detection patterns.
 *
 * Ported from piiDetectionService.ts (frontend/packages/ui) for reuse
 * in both CLI output scanning and web app file processing. Only includes
 * patterns for API keys, tokens, and credentials — NOT personal data
 * (email, phone, SSN, etc.) which remain in piiDetectionService.ts.
 *
 * No generic high-entropy heuristic is included — only patterns with
 * proven low false-positive rates from production use.
 *
 * Architecture: docs/architecture/pii-protection.md
 */

import type { SecretType } from "./types.ts";

/**
 * A pattern definition for detecting a specific type of secret.
 */
export interface SecretPattern {
  /** Secret type identifier */
  type: SecretType;
  /** Regex pattern (must have global flag) */
  regex: RegExp;
  /** Human-readable label */
  label: string;
  /** Prefix for placeholder tokens, e.g. "OPENAI_KEY" → [OPENAI_KEY_1_f9d] */
  placeholderPrefix: string;
  /** Optional validation function for additional checks */
  validate?: (match: string) => boolean;
}

/**
 * Extract the last N characters from a secret value for suffix-based
 * placeholder identification. Strips trailing quotes/whitespace.
 *
 * Shared with piiDetectionService.ts — same algorithm, kept in sync.
 * See: getSecretSuffix() in piiDetectionService.ts
 */
export function getSecretSuffix(match: string, n = 3): string {
  const cleaned = match.replace(/['";\s]+$/g, "");
  if (cleaned.length <= n) return cleaned;
  return cleaned.slice(-n);
}

/**
 * Generate a placeholder token for a detected secret.
 * Always includes a 1-based counter to prevent collisions when multiple
 * values share the same suffix (e.g., two emails ending in ".com").
 *
 * @param prefix The type prefix (e.g., "OPENAI_KEY")
 * @param match The matched secret value
 * @param suffixLength Number of trailing chars to include (default: 3)
 * @param counter 1-based per-type counter for uniqueness
 * @returns Placeholder token, e.g. "[OPENAI_KEY_1_f9d]"
 */
export function generatePlaceholder(
  prefix: string,
  match: string,
  suffixLength = 3,
  counter = 1,
): string {
  return `[${prefix}_${counter}_${getSecretSuffix(match, suffixLength)}]`;
}

/**
 * Vendor-specific secret detection patterns.
 *
 * These are the same patterns used in piiDetectionService.ts, extracted
 * here for reuse. Ordered by specificity (most specific first) to
 * prevent overlapping matches.
 *
 * IMPORTANT: When updating patterns here, also update piiDetectionService.ts
 * and vice versa to keep detection consistent across CLI and web app.
 */
export const SECRET_PATTERNS: SecretPattern[] = [
  {
    type: "AWS_ACCESS_KEY",
    regex: /\bAKIA[0-9A-Z]{16}\b/g,
    label: "AWS Access Key",
    placeholderPrefix: "AWS_KEY",
  },
  {
    type: "OPENAI_KEY",
    regex: /\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,200}\b/g,
    label: "OpenAI API Key",
    placeholderPrefix: "OPENAI_KEY",
  },
  {
    type: "ANTHROPIC_KEY",
    regex: /\bsk-ant-api03-[A-Za-z0-9_-]{90,110}\b/g,
    label: "Anthropic API Key",
    placeholderPrefix: "ANTHROPIC_KEY",
  },
  {
    type: "GITHUB_PAT",
    regex:
      /\b(?:ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9]{22}_[a-zA-Z0-9]{59}|gho_[a-zA-Z0-9]{36})\b/g,
    label: "GitHub Token",
    placeholderPrefix: "GITHUB_TOKEN",
  },
  {
    type: "STRIPE_KEY",
    regex: /\b[sr]k_(?:live|test)_[0-9a-zA-Z]{24,99}\b/g,
    label: "Stripe API Key",
    placeholderPrefix: "STRIPE_KEY",
  },
  {
    type: "GOOGLE_API_KEY",
    regex: /\bAIza[0-9A-Za-z\-_]{35}\b/g,
    label: "Google API Key",
    placeholderPrefix: "GOOGLE_KEY",
  },
  {
    type: "SLACK_TOKEN",
    regex: /\bxox[bpras]-[0-9a-zA-Z-]{10,250}\b/g,
    label: "Slack Token",
    placeholderPrefix: "SLACK_TOKEN",
  },
  {
    type: "AWS_SECRET_KEY",
    regex:
      /(?:aws_secret|secret_key|secretkey|secret_access_key)['":\s=]+([0-9a-zA-Z/+=]{40})\b/gi,
    label: "AWS Secret Key",
    placeholderPrefix: "AWS_SECRET",
  },
  {
    type: "TWILIO_KEY",
    regex: /\b(?:AC[a-f0-9]{32}|SK[a-f0-9]{32})\b/g,
    label: "Twilio Key",
    placeholderPrefix: "TWILIO_KEY",
  },
  {
    type: "SENDGRID_KEY",
    regex: /\bSG\.[a-zA-Z0-9_-]{22}\.[a-zA-Z0-9_-]{43}\b/g,
    label: "SendGrid API Key",
    placeholderPrefix: "SENDGRID_KEY",
  },
  {
    type: "AZURE_KEY",
    regex:
      /(?:azure|subscription|ocp-apim)[_-]?(?:key|secret|token)['":\s=]+([0-9a-f]{32})\b/gi,
    label: "Azure Key",
    placeholderPrefix: "AZURE_KEY",
  },
  {
    type: "HUGGINGFACE_KEY",
    regex: /\bhf_[a-zA-Z0-9]{34,}\b/g,
    label: "Hugging Face Token",
    placeholderPrefix: "HF_TOKEN",
  },
  {
    type: "DATABRICKS_TOKEN",
    regex: /\bdapi[a-f0-9]{32,40}\b/g,
    label: "Databricks Token",
    placeholderPrefix: "DATABRICKS_TOKEN",
  },
  {
    type: "FIREBASE_KEY",
    regex: /\bAAAA[A-Za-z0-9_-]{100,200}\b/g,
    label: "Firebase Key",
    placeholderPrefix: "FIREBASE_KEY",
  },
  {
    type: "GENERIC_SECRET",
    regex:
      /(?:api[_-]?key|api[_-]?secret|secret[_-]?key|auth[_-]?token|access[_-]?token|bearer[_-]?token|private[_-]?key|password|passwd|credential|client[_-]?secret|app[_-]?secret|signing[_-]?key|encryption[_-]?key)['":\s=]+['"]?([A-Za-z0-9_\-/.+=]{8,200})['"]?/gi,
    label: "Secret/Credential",
    placeholderPrefix: "SECRET",
  },
  {
    type: "PRIVATE_KEY",
    regex:
      /-----BEGIN (?:RSA |DSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |DSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----/g,
    label: "Private Key",
    placeholderPrefix: "PRIVATE_KEY",
  },
  {
    type: "JWT",
    regex: /\beyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+/g,
    label: "JWT Token",
    placeholderPrefix: "JWT_TOKEN",
  },
];
