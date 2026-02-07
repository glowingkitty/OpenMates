// frontend/packages/ui/src/components/enter_message/services/piiDetectionService.ts
/**
 * @file piiDetectionService.ts
 * @description Client-side PII (Personally Identifiable Information) detection service.
 *
 * Detects sensitive data patterns in user input and provides placeholders for anonymization.
 * Users can click on detected PII to restore the original text if it's a false positive.
 *
 * Supported patterns (high reliability, low false positives):
 * - Email addresses
 * - Phone numbers (US/international formats)
 * - API keys (AWS, OpenAI, Anthropic, GitHub, Stripe, Google, Slack)
 * - Credit card numbers (with Luhn validation)
 * - Social Security Numbers (SSN)
 * - IP addresses (IPv4 and IPv6)
 * - Private keys (PEM format)
 * - JWT tokens
 */

/**
 * Types of PII that can be detected
 */
export type PIIType =
  | "EMAIL"
  | "PHONE"
  | "AWS_ACCESS_KEY"
  | "AWS_SECRET_KEY"
  | "OPENAI_KEY"
  | "ANTHROPIC_KEY"
  | "GITHUB_PAT"
  | "STRIPE_KEY"
  | "GOOGLE_API_KEY"
  | "SLACK_TOKEN"
  | "CREDIT_CARD"
  | "SSN"
  | "IPV4"
  | "IPV6"
  | "PRIVATE_KEY"
  | "JWT";

/**
 * A detected PII match in text
 */
export interface PIIMatch {
  /** Type of PII detected */
  type: PIIType;
  /** The matched text */
  match: string;
  /** Start position in the text (0-indexed) */
  startIndex: number;
  /** End position in the text (exclusive) */
  endIndex: number;
  /** Placeholder to replace the PII with */
  placeholder: string;
  /** Unique ID for this detection (for tracking exclusions) */
  id: string;
}

/**
 * PII pattern definition
 */
interface PIIPattern {
  type: PIIType;
  regex: RegExp;
  /** Human-readable label for the PII type */
  label: string;
  /** Function to generate placeholder text */
  getPlaceholder: (match: string, index: number) => string;
  /** Optional validation function for additional checks (e.g., Luhn for credit cards) */
  validate?: (match: string) => boolean;
}

/**
 * Luhn algorithm validation for credit card numbers
 * @param cardNumber Credit card number string (digits only)
 * @returns true if valid according to Luhn algorithm
 */
function luhnCheck(cardNumber: string): boolean {
  const digits = cardNumber.replace(/\D/g, "");
  if (digits.length < 13 || digits.length > 19) return false;

  let sum = 0;
  let isEven = false;

  for (let i = digits.length - 1; i >= 0; i--) {
    let digit = parseInt(digits[i], 10);
    if (isEven) {
      digit *= 2;
      if (digit > 9) digit -= 9;
    }
    sum += digit;
    isEven = !isEven;
  }
  return sum % 10 === 0;
}

/**
 * Generate a stable, deterministic ID for a PII match.
 * Uses type + position so the same match always gets the same ID across
 * re-detections. This makes exclusion lookups O(1) via Set.has().
 */
function generateMatchId(type: PIIType, startIndex: number): string {
  return `pii-${type}-${startIndex}`;
}

/**
 * PII detection patterns ordered by specificity (more specific patterns first)
 * to prevent overlapping matches
 */
const PII_PATTERNS: PIIPattern[] = [
  // API Keys (most specific - check first to avoid partial matches)
  {
    type: "AWS_ACCESS_KEY",
    regex: /\bAKIA[0-9A-Z]{16}\b/g,
    label: "AWS Access Key",
    getPlaceholder: (_, i) => `[AWS_KEY_${i + 1}]`,
  },
  {
    type: "OPENAI_KEY",
    // Matches: sk-proj-..., sk-svcacct-..., sk-... (legacy)
    regex: /\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,200}\b/g,
    label: "OpenAI API Key",
    getPlaceholder: (_, i) => `[OPENAI_KEY_${i + 1}]`,
  },
  {
    type: "ANTHROPIC_KEY",
    regex: /\bsk-ant-api03-[A-Za-z0-9_-]{90,110}\b/g,
    label: "Anthropic API Key",
    getPlaceholder: (_, i) => `[ANTHROPIC_KEY_${i + 1}]`,
  },
  {
    type: "GITHUB_PAT",
    // Classic PAT, fine-grained PAT, and OAuth tokens
    regex:
      /\b(?:ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9]{22}_[a-zA-Z0-9]{59}|gho_[a-zA-Z0-9]{36})\b/g,
    label: "GitHub Token",
    getPlaceholder: (_, i) => `[GITHUB_TOKEN_${i + 1}]`,
  },
  {
    type: "STRIPE_KEY",
    // Live, test, and restricted keys
    regex: /\b[sr]k_(?:live|test)_[0-9a-zA-Z]{24,99}\b/g,
    label: "Stripe API Key",
    getPlaceholder: (_, i) => `[STRIPE_KEY_${i + 1}]`,
  },
  {
    type: "GOOGLE_API_KEY",
    regex: /\bAIza[0-9A-Za-z\-_]{35}\b/g,
    label: "Google API Key",
    getPlaceholder: (_, i) => `[GOOGLE_KEY_${i + 1}]`,
  },
  {
    type: "SLACK_TOKEN",
    // Bot, user, and app tokens
    regex: /\bxox[bpras]-[0-9a-zA-Z-]{10,250}\b/g,
    label: "Slack Token",
    getPlaceholder: (_, i) => `[SLACK_TOKEN_${i + 1}]`,
  },
  {
    type: "AWS_SECRET_KEY",
    // 40-character base64-like string - only match if preceded by common context keywords
    // This reduces false positives significantly
    regex:
      /(?:aws_secret|secret_key|secretkey|secret_access_key)['":\s=]+([0-9a-zA-Z/+=]{40})\b/gi,
    label: "AWS Secret Key",
    getPlaceholder: (_, i) => `[AWS_SECRET_${i + 1}]`,
  },

  // Private keys and tokens
  {
    type: "PRIVATE_KEY",
    regex:
      /-----BEGIN (?:RSA |DSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |DSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----/g,
    label: "Private Key",
    getPlaceholder: (_, i) => `[PRIVATE_KEY_${i + 1}]`,
  },
  {
    type: "JWT",
    // JWT format: base64.base64.base64
    regex: /\beyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+/g,
    label: "JWT Token",
    getPlaceholder: (_, i) => `[JWT_TOKEN_${i + 1}]`,
  },

  // Personal identifiers
  {
    type: "EMAIL",
    regex: /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g,
    label: "Email Address",
    getPlaceholder: (_, i) => `[EMAIL_${i + 1}]`,
  },
  {
    type: "CREDIT_CARD",
    // Major card formats: Visa, Mastercard, Amex, Discover
    // With optional spaces or dashes between groups
    regex:
      /\b(?:4[0-9]{3}[-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4}|5[1-5][0-9]{2}[-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4}|3[47][0-9]{2}[-\s]?[0-9]{6}[-\s]?[0-9]{5}|6(?:011|5[0-9]{2})[-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4})\b/g,
    label: "Credit Card",
    getPlaceholder: (_, i) => `[CARD_${i + 1}]`,
    validate: luhnCheck,
  },
  {
    type: "SSN",
    // US Social Security Number: XXX-XX-XXXX or XXX XX XXXX or XXXXXXXXX
    regex: /\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b/g,
    label: "SSN",
    getPlaceholder: (_, i) => `[SSN_${i + 1}]`,
    // Additional validation: first 3 digits can't be 000, 666, or 900-999
    validate: (match: string) => {
      const digits = match.replace(/\D/g, "");
      if (digits.length !== 9) return false;
      const area = parseInt(digits.substring(0, 3), 10);
      if (area === 0 || area === 666 || area >= 900) return false;
      const group = parseInt(digits.substring(3, 5), 10);
      if (group === 0) return false;
      const serial = parseInt(digits.substring(5, 9), 10);
      if (serial === 0) return false;
      return true;
    },
  },
  {
    type: "PHONE",
    // US phone formats: +1 (XXX) XXX-XXXX, XXX-XXX-XXXX, (XXX) XXX-XXXX, etc.
    // Also international E.164 format: +XXXXXXXXXXX
    regex:
      /(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b|\+[1-9]\d{6,14}\b/g,
    label: "Phone Number",
    getPlaceholder: (_, i) => `[PHONE_${i + 1}]`,
  },

  // IP Addresses
  {
    type: "IPV4",
    regex:
      /\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b/g,
    label: "IP Address",
    getPlaceholder: (_, i) => `[IP_${i + 1}]`,
    // Exclude common non-sensitive IPs
    validate: (match: string) => {
      // Allow localhost and private ranges to pass through (not sensitive)
      if (match === "127.0.0.1" || match === "0.0.0.0") return false;
      if (
        match.startsWith("192.168.") ||
        match.startsWith("10.") ||
        match.startsWith("172.")
      )
        return false;
      return true;
    },
  },
  {
    type: "IPV6",
    // Full IPv6 format
    regex: /\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b/g,
    label: "IPv6 Address",
    getPlaceholder: (_, i) => `[IPV6_${i + 1}]`,
  },
];

/**
 * Minimum text length before running PII detection.
 * Most PII patterns (emails, phone numbers, API keys) need at least 6 characters.
 * This avoids running 16 regexes on very short text like "hi" or "ok".
 */
const MIN_PII_TEXT_LENGTH = 6;

/**
 * Detect all PII in the given text
 *
 * @param text The text to scan for PII
 * @param excludedIds Set of match IDs that user has excluded (clicked to restore).
 *   IDs use the stable format "pii-TYPE-startIndex" so Set.has() works directly.
 * @returns Array of PII matches found in the text
 */
export function detectPII(
  text: string,
  excludedIds: Set<string> = new Set(),
): PIIMatch[] {
  // Early exit for very short text — no PII pattern can match
  if (!text || text.length < MIN_PII_TEXT_LENGTH) return [];

  const matches: PIIMatch[] = [];
  const coveredRanges: Array<{ start: number; end: number }> = [];

  // Track how many of each type we've found (for placeholder numbering)
  const typeCounts: Record<PIIType, number> = {} as Record<PIIType, number>;

  const hasExclusions = excludedIds.size > 0;

  for (const pattern of PII_PATTERNS) {
    // Reset regex lastIndex directly instead of creating a new RegExp object.
    // The patterns are defined with the 'g' flag so resetting lastIndex is sufficient.
    pattern.regex.lastIndex = 0;
    let regexMatch;

    while ((regexMatch = pattern.regex.exec(text)) !== null) {
      const matchText = regexMatch[0];
      const startIndex = regexMatch.index;
      const endIndex = startIndex + matchText.length;

      // Skip if this range overlaps with an already detected PII
      const overlaps = coveredRanges.some(
        (range) =>
          (startIndex >= range.start && startIndex < range.end) ||
          (endIndex > range.start && endIndex <= range.end) ||
          (startIndex <= range.start && endIndex >= range.end),
      );

      if (overlaps) continue;

      // Run additional validation if provided
      if (pattern.validate && !pattern.validate(matchText)) {
        continue;
      }

      // Generate stable match ID (deterministic: type + position)
      const matchId = generateMatchId(pattern.type, startIndex);

      // Skip if user has excluded this match.
      // IDs are now stable ("pii-TYPE-startIndex") so a direct Set.has() works — O(1).
      if (hasExclusions && excludedIds.has(matchId)) continue;

      // Increment type count for placeholder numbering
      typeCounts[pattern.type] = (typeCounts[pattern.type] || 0) + 1;

      matches.push({
        type: pattern.type,
        match: matchText,
        startIndex,
        endIndex,
        placeholder: pattern.getPlaceholder(
          matchText,
          typeCounts[pattern.type] - 1,
        ),
        id: matchId,
      });

      // Mark this range as covered
      coveredRanges.push({ start: startIndex, end: endIndex });
    }
  }

  // Sort by start index for consistent processing
  matches.sort((a, b) => a.startIndex - b.startIndex);

  return matches;
}

/**
 * Replace all PII in text with placeholders
 *
 * @param text Original text
 * @param matches PII matches to replace (from detectPII)
 * @returns Text with PII replaced by placeholders
 */
export function replacePIIWithPlaceholders(
  text: string,
  matches: PIIMatch[],
): string {
  if (matches.length === 0) return text;

  // Sort by start index descending to replace from end to start
  // This preserves indices while replacing
  const sortedMatches = [...matches].sort(
    (a, b) => b.startIndex - a.startIndex,
  );

  let result = text;
  for (const match of sortedMatches) {
    result =
      result.substring(0, match.startIndex) +
      match.placeholder +
      result.substring(match.endIndex);
  }

  return result;
}

/**
 * Get human-readable label for a PII type.
 * Accepts string to support both PIIType enum values and generic string types
 * from deserialized PII mappings.
 */
export function getPIILabel(type: string): string {
  const pattern = PII_PATTERNS.find((p) => p.type === type);
  return pattern?.label ?? type;
}

/**
 * Get all unique PII types from a list of matches
 */
export function getUniquePIITypes(matches: PIIMatch[]): PIIType[] {
  return Array.from(new Set(matches.map((m) => m.type)));
}

/**
 * Create a summary of detected PII for display
 * e.g., "2 emails, 1 API key, 1 phone number"
 */
export function createPIISummary(matches: PIIMatch[]): string {
  const typeCounts: Record<string, number> = {};

  for (const match of matches) {
    const label = getPIILabel(match.type);
    typeCounts[label] = (typeCounts[label] || 0) + 1;
  }

  const parts: string[] = [];
  for (const [label, count] of Object.entries(typeCounts)) {
    parts.push(`${count} ${label.toLowerCase()}${count > 1 ? "s" : ""}`);
  }

  return parts.join(", ");
}

/**
 * PIIMapping format for storage (matches the PIIMapping interface in types/chat.ts)
 */
export interface PIIMappingForStorage {
  /** The placeholder text (e.g., "[EMAIL_1]") */
  placeholder: string;
  /** The original PII value (e.g., "user@example.com") */
  original: string;
  /** The type of PII for styling purposes */
  type: PIIType;
}

/**
 * Convert PII matches to storage format for message persistence.
 * This creates an array of mappings that can be encrypted and stored
 * with the message for later restoration.
 *
 * @param matches PII matches from detectPII()
 * @returns Array of PII mappings ready for storage
 */
export function createPIIMappingsForStorage(
  matches: PIIMatch[],
): PIIMappingForStorage[] {
  return matches.map((match) => ({
    placeholder: match.placeholder,
    original: match.match,
    type: match.type,
  }));
}

/**
 * Generic PII mapping interface for restoration (accepts both PIIMapping and PIIMappingForStorage)
 */
interface PIIMappingGeneric {
  placeholder: string;
  original: string;
  type: string;
}

/**
 * Restore PII placeholders in text with the original plain-text values.
 * The replacement is plain text (no HTML) so the result can safely be passed
 * through a markdown parser or TipTap without escaping issues.
 *
 * Visual highlighting is applied separately via ProseMirror decorations
 * in the ReadOnlyMessage component using {@link findRestoredPIIPositions}.
 *
 * @param text Text containing PII placeholders (e.g., "[EMAIL_1]")
 * @param mappings Array of PII mappings from storage
 * @returns Text with placeholders replaced by original plain-text values
 */
export function restorePIIInText(
  text: string,
  mappings: PIIMappingGeneric[],
): string {
  if (!mappings || mappings.length === 0) return text;

  let result = text;

  for (const mapping of mappings) {
    // Replace all occurrences of the placeholder with the original value (plain text)
    result = result.split(mapping.placeholder).join(mapping.original);
  }

  return result;
}

/**
 * A restored PII position in rendered text, used for ProseMirror decoration.
 */
export interface RestoredPIIPosition {
  /** Start index in the text (0-based) */
  startIndex: number;
  /** End index in the text (exclusive) */
  endIndex: number;
  /** PII type for styling (e.g. "EMAIL", "PHONE") */
  type: string;
  /** Human-readable label for tooltips */
  label: string;
}

/**
 * Find positions of restored PII values in a rendered text string.
 * Called after placeholder replacement to locate where each original value
 * sits in the final text, so ProseMirror decorations can highlight them.
 *
 * @param text Text that has already been through restorePIIInText()
 * @param mappings The same PII mappings used for restoration
 * @returns Array of positions suitable for building ProseMirror Decoration.inline()
 */
export function findRestoredPIIPositions(
  text: string,
  mappings: PIIMappingGeneric[],
): RestoredPIIPosition[] {
  if (!text || !mappings || mappings.length === 0) return [];

  const positions: RestoredPIIPosition[] = [];

  for (const mapping of mappings) {
    const original = mapping.original;
    if (!original) continue;

    // Find all occurrences of the original value in the text
    let searchFrom = 0;
    while (searchFrom < text.length) {
      const idx = text.indexOf(original, searchFrom);
      if (idx === -1) break;

      positions.push({
        startIndex: idx,
        endIndex: idx + original.length,
        type: mapping.type,
        label: getPIILabel(mapping.type),
      });

      // Move past this occurrence to find the next one
      searchFrom = idx + original.length;
    }
  }

  // Sort by position for consistent decoration ordering
  positions.sort((a, b) => a.startIndex - b.startIndex);
  return positions;
}
