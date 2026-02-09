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
 * - Phone numbers (US, EU, international formats with spaces/dashes/slashes)
 * - API keys (AWS, OpenAI, Anthropic, GitHub, Stripe, Google, Slack, Twilio,
 *   SendGrid, Azure, Hugging Face, Databricks, Firebase)
 * - Generic secrets (api_key=..., password=..., token=..., etc.)
 * - Credit card numbers (with Luhn validation)
 * - Social Security Numbers (SSN)
 * - IP addresses (IPv4 and IPv6)
 * - Private keys (PEM format)
 * - JWT tokens
 * - IBAN / bank account numbers (with ISO 7064 Mod 97-10 validation)
 * - Home folder paths (/home/user/, /Users/user/, C:\Users\user\)
 * - Terminal prompts with user@hostname (marco@MacBook ~ %, user@server:~$)
 * - MAC addresses (network hardware identifiers)
 * - Passport numbers (context-dependent, major country formats)
 * - Tax ID / VAT numbers (EU VAT format + context-dependent national formats)
 * - Vehicle license plate numbers (context-dependent)
 * - Cryptocurrency wallet addresses (Bitcoin Legacy/SegWit, Ethereum)
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
  | "TWILIO_KEY"
  | "SENDGRID_KEY"
  | "AZURE_KEY"
  | "HUGGINGFACE_KEY"
  | "DATABRICKS_TOKEN"
  | "FIREBASE_KEY"
  | "GENERIC_SECRET"
  | "CREDIT_CARD"
  | "SSN"
  | "IPV4"
  | "IPV6"
  | "PRIVATE_KEY"
  | "JWT"
  | "IBAN"
  | "HOME_FOLDER"
  | "USER_AT_HOSTNAME"
  | "MAC_ADDRESS"
  | "PASSPORT"
  | "TAX_ID"
  | "VEHICLE_PLATE"
  | "CRYPTO_WALLET";

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
 * IBAN validation using ISO 7064 Mod 97-10 check digit algorithm.
 * Rearranges the IBAN (move first 4 chars to end), converts letters to numbers
 * (A=10, B=11, ..., Z=35), and checks if the result mod 97 equals 1.
 *
 * @param iban IBAN string (may contain spaces)
 * @returns true if valid IBAN check digits
 */
function ibanCheck(iban: string): boolean {
  // Remove spaces and convert to uppercase
  const cleaned = iban.replace(/\s/g, "").toUpperCase();
  if (cleaned.length < 15 || cleaned.length > 34) return false;

  // Move first 4 chars to end
  const rearranged = cleaned.substring(4) + cleaned.substring(0, 4);

  // Convert letters to numbers (A=10, B=11, ..., Z=35)
  let numericStr = "";
  for (const char of rearranged) {
    const code = char.charCodeAt(0);
    if (code >= 65 && code <= 90) {
      // A-Z → 10-35
      numericStr += (code - 55).toString();
    } else {
      numericStr += char;
    }
  }

  // Mod 97 on the large number (process in chunks to avoid BigInt)
  let remainder = 0;
  for (const digit of numericStr) {
    remainder = (remainder * 10 + parseInt(digit, 10)) % 97;
  }

  return remainder === 1;
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
  {
    type: "TWILIO_KEY",
    // Twilio Account SID (AC...) and Auth Token (SK...)
    regex: /\b(?:AC[a-f0-9]{32}|SK[a-f0-9]{32})\b/g,
    label: "Twilio Key",
    getPlaceholder: (_, i) => `[TWILIO_KEY_${i + 1}]`,
  },
  {
    type: "SENDGRID_KEY",
    // SendGrid API keys start with SG.
    regex: /\bSG\.[a-zA-Z0-9_-]{22}\.[a-zA-Z0-9_-]{43}\b/g,
    label: "SendGrid API Key",
    getPlaceholder: (_, i) => `[SENDGRID_KEY_${i + 1}]`,
  },
  {
    type: "AZURE_KEY",
    // Azure subscription keys are 32-character hex strings, matched only when
    // preceded by a contextual keyword to avoid false positives on random hex.
    regex:
      /(?:azure|subscription|ocp-apim)[_-]?(?:key|secret|token)['":\s=]+([0-9a-f]{32})\b/gi,
    label: "Azure Key",
    getPlaceholder: (_, i) => `[AZURE_KEY_${i + 1}]`,
  },
  {
    type: "HUGGINGFACE_KEY",
    // Hugging Face API tokens: hf_...
    regex: /\bhf_[a-zA-Z0-9]{34,}\b/g,
    label: "Hugging Face Token",
    getPlaceholder: (_, i) => `[HF_TOKEN_${i + 1}]`,
  },
  {
    type: "DATABRICKS_TOKEN",
    // Databricks personal access tokens: dapi...
    regex: /\bdapi[a-f0-9]{32,40}\b/g,
    label: "Databricks Token",
    getPlaceholder: (_, i) => `[DATABRICKS_TOKEN_${i + 1}]`,
  },
  {
    type: "FIREBASE_KEY",
    // Firebase server keys typically start with AAAA and are ~152 chars
    regex: /\bAAAA[A-Za-z0-9_-]{100,200}\b/g,
    label: "Firebase Key",
    getPlaceholder: (_, i) => `[FIREBASE_KEY_${i + 1}]`,
  },

  {
    type: "GENERIC_SECRET",
    // Generic secret/key/token/password patterns — catches assignment-style secrets
    // that don't match any vendor-specific pattern above. Requires a keyword like
    // "api_key", "secret", "password", "token", "auth", "credential", "access_key",
    // followed by an assignment operator and a value of 8+ alphanumeric characters.
    // The value must be 8+ chars to avoid matching trivial assignments like key="id".
    regex:
      /(?:api[_-]?key|api[_-]?secret|secret[_-]?key|auth[_-]?token|access[_-]?token|bearer[_-]?token|private[_-]?key|password|passwd|credential|client[_-]?secret|app[_-]?secret|signing[_-]?key|encryption[_-]?key)['":\s=]+['"]?([A-Za-z0-9_\-/.+=]{8,200})['"]?/gi,
    label: "Secret/Credential",
    getPlaceholder: (_, i) => `[SECRET_${i + 1}]`,
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
    // Comprehensive phone number detection covering multiple international formats:
    //
    // Branch 1 — International with country code (+ or 00 prefix):
    //   Matches +49 2123 21234, +44 20 7946 0958, +1 (555) 123-4567,
    //   0049 2123 21234, 0044-20-7946-0958, +492123212234 (E.164)
    //   Requires country code digit [1-9] then 6-14 more digits with optional
    //   separators (space, dash, dot, slash, parens) between groups.
    //
    // Branch 2 — US/Canada format without country code:
    //   Matches (555) 123-4567, 555-123-4567, 555.123.4567
    //   Area code starts with [2-9] per NANP rules.
    //
    // Branch 3 — Local format with leading 0 (common in DE, UK, FR, etc.):
    //   Matches 01123/121/31222, 030 1234 5678, 0171-123-4567
    //   Leading 0 + at least 7 more digits with separators.
    //
    // Validation function filters false positives (plain numbers, years, etc.)
    regex:
      /(?:(?:\+|00)[1-9]\d{0,2}[-.\s/]?(?:\(?\d{1,5}\)?[-.\s/]?){1,4}\d{2,4})|(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}|(?:0\d[-.\s/]?(?:\(?\d{1,5}\)?[-.\s/]?){1,4}\d{2,4})/g,
    label: "Phone Number",
    getPlaceholder: (_, i) => `[PHONE_${i + 1}]`,
    // Validate: require at least 7 digits total (country code excluded) to avoid
    // matching short number-like strings (zip codes, years, short IDs).
    validate: (match: string) => {
      const digits = match.replace(/\D/g, "");
      // Phone numbers have at least 7 digits (local) and at most 15 (ITU-T E.164)
      if (digits.length < 7 || digits.length > 15) return false;
      // Reject matches that are purely a year-like 4-digit number (shouldn't happen
      // given min 7 digits, but guard against edge cases)
      if (/^\d{4}$/.test(match.trim())) return false;
      return true;
    },
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

  // Bank account numbers (IBAN)
  {
    type: "IBAN",
    // IBAN format: 2-letter country code + 2 check digits + up to 30 alphanumeric chars.
    // Supports both compact (DE89370400440532013000) and spaced (DE89 3704 0044 0532 0130 00).
    // Country code is required to reduce false positives on random alphanumeric strings.
    regex:
      /\b[A-Z]{2}\d{2}[\s]?[\dA-Z]{4}[\s]?(?:[\dA-Z]{4}[\s]?){1,7}[\dA-Z]{1,4}\b/g,
    label: "IBAN",
    getPlaceholder: (_, i) => `[IBAN_${i + 1}]`,
    validate: ibanCheck,
  },

  // Home folder / user directory paths that leak the local username.
  //   /home/marco/projects/foo, /Users/marco/.ssh/config, C:\Users\Marco\Documents
  //   PS C:\Users\Marco>, PS /home/marco>
  {
    type: "HOME_FOLDER",
    // Two branches:
    // Branch 1 — Unix/macOS/Windows home directory paths:
    //   /home/user, /Users/user, C:\Users\user
    //   Username: 1-64 alphanumeric/dash/underscore/dot chars.
    //   Requires trailing slash, backslash, or word boundary.
    //
    // Branch 2 — PowerShell prompt with home path:
    //   PS C:\Users\user> or PS /home/user>
    regex:
      /(?:\/home\/|\/Users\/|[A-Z]:\\Users\\)[a-zA-Z0-9_.-]{1,64}(?=[/\\]|\b)|PS [A-Z]:\\Users\\[a-zA-Z0-9_.-]{1,64}(?=[\\>]|\b)|PS \/(?:home|Users)\/[a-zA-Z0-9_.-]{1,64}(?=[/>]|\b)/g,
    label: "Home Folder",
    getPlaceholder: (_, i) => `[HOME_PATH_${i + 1}]`,
    // Exclude common system/service accounts that are not personal
    validate: (match: string) => {
      const username = match
        .replace(/^(?:PS\s+)?(?:\/home\/|\/Users\/|[A-Z]:\\Users\\)/i, "")
        .toLowerCase();
      const systemAccounts = new Set([
        "root",
        "admin",
        "shared",
        "public",
        "default",
        "guest",
        "nobody",
        "daemon",
        "www-data",
        "ubuntu",
      ]);
      return !systemAccounts.has(username);
    },
  },

  // Terminal prompt user@hostname patterns that leak username and machine name.
  //   marco@Marcos-MacBook-Pro-3 ~ %      (zsh on macOS)
  //   marco@devserver:~/projects$          (bash on Linux)
  //   [marco@centos8 ~]$                   (RHEL/CentOS bash)
  {
    type: "USER_AT_HOSTNAME",
    // Matches user@hostname followed by common terminal prompt context characters
    // (colon, space, tilde, ~). The hostname may contain dots (FQDN) and dashes.
    // The lookahead for [:~ \s] ensures we only match in prompt-like contexts,
    // not in email addresses (which are caught earlier by the EMAIL pattern
    // due to pattern ordering — EMAIL is checked before USER_AT_HOSTNAME).
    regex:
      /\b[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,31}@[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,63}(?=[\s:~])/g,
    label: "User@Hostname",
    getPlaceholder: (_, i) => `[USER_HOST_${i + 1}]`,
    // Exclude well-known service accounts and non-personal user@host patterns
    validate: (match: string) => {
      const username = match.split("@")[0].toLowerCase();
      const host = (match.split("@")[1] ?? "").toLowerCase();

      // Skip well-known service patterns (git@github.com, etc.)
      // These are not personal identity leaks.
      const serviceHosts = new Set([
        "github.com",
        "gitlab.com",
        "bitbucket.org",
        "ssh.dev.azure.com",
      ]);
      if (serviceHosts.has(host)) return false;

      const systemAccounts = new Set([
        "root",
        "admin",
        "guest",
        "nobody",
        "daemon",
        "www-data",
        "noreply",
        "no-reply",
        "git",
        "svn",
        "user",
        "test",
        "ubuntu",
      ]);
      return !systemAccounts.has(username);
    },
  },

  // MAC addresses (network hardware identifiers)
  {
    type: "MAC_ADDRESS",
    // Standard MAC address formats:
    // - Colon-separated: AA:BB:CC:DD:EE:FF
    // - Dash-separated: AA-BB-CC-DD-EE-FF
    // Case-insensitive, requires word boundaries to avoid matching inside hex strings.
    regex: /\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b/g,
    label: "MAC Address",
    getPlaceholder: (_, i) => `[MAC_${i + 1}]`,
    // Exclude broadcast and zero addresses
    validate: (match: string) => {
      const normalized = match.replace(/[:-]/g, "").toUpperCase();
      if (normalized === "000000000000" || normalized === "FFFFFFFFFFFF")
        return false;
      return true;
    },
  },

  // Passport numbers (major countries — context-dependent to reduce false positives)
  {
    type: "PASSPORT",
    // Matches passport numbers when preceded by a context keyword like "passport",
    // "reisepass", "passeport", or passport-number-like labels.
    // Formats covered:
    //   - US: 9 digits (C + 8 digits, or 9 digits)
    //   - DE: 9 alphanumeric (C followed by 8 chars, or 9 uppercase alphanumeric)
    //   - UK: 9 digits
    //   - FR: 2 digits + 2 letters + 5 digits
    //   - Generic: 6-9 alphanumeric (with context keyword requirement)
    // The context keyword requirement is critical to avoid matching random short strings.
    regex:
      /(?:passport|reisepass|passeport|pass(?:port)?[\s._-]?(?:no|nr|num(?:ber)?|#))[:\s#=]*([A-Z0-9]{6,9})\b/gi,
    label: "Passport Number",
    getPlaceholder: (_, i) => `[PASSPORT_${i + 1}]`,
  },

  // Tax ID / VAT numbers (EU VAT + context-dependent national formats)
  {
    type: "TAX_ID",
    // Two branches:
    // Branch 1 — EU VAT numbers: 2-letter country prefix + 8-12 alphanumeric digits.
    //   e.g., DE123456789, GB123456789, FR12345678901, ATU12345678
    //   Requires \b boundaries to avoid matching inside longer strings.
    //
    // Branch 2 — Context-dependent: matches when preceded by keywords like
    //   "tax id", "tax number", "steuer", "steuernummer", "tin", "vat",
    //   "tax identification", followed by a colon/equals/space and a number.
    //   This catches national tax IDs like US EIN (XX-XXXXXXX), German
    //   Steuernummer (XXX/XXX/XXXXX), etc.
    regex:
      /\b(?:AT ?U\d{8}|BE ?0?\d{9,10}|BG ?\d{9,10}|HR ?\d{11}|CY ?\d{8}[A-Z]|CZ ?\d{8,10}|DK ?\d{8}|EE ?\d{9}|FI ?\d{8}|FR ?[0-9A-Z]{2}\d{9}|DE ?\d{9}|EL ?\d{9}|HU ?\d{8}|IE ?\d{7}[A-Z]{1,2}|IT ?\d{11}|LV ?\d{11}|LT ?\d{9,12}|LU ?\d{8}|MT ?\d{8}|NL ?\d{9}B\d{2}|PL ?\d{10}|PT ?\d{9}|RO ?\d{2,10}|SK ?\d{10}|SI ?\d{8}|ES ?[A-Z0-9]\d{7}[A-Z0-9]|SE ?\d{12}|GB ?\d{9}(?:\d{3})?)\b|(?:tax[\s_-]?(?:id|number|no|nr)|steuer(?:nummer|identifikationsnummer|nr|ident(?:nummer)?)?|tin|vat[\s_-]?(?:id|number|no|nr)?|tax[\s_-]?identification(?:[\s_-]?number)?)[:\s#=]+([A-Z0-9\s/-]{5,20})/gi,
    label: "Tax ID",
    getPlaceholder: (_, i) => `[TAX_ID_${i + 1}]`,
  },

  // Vehicle license plate numbers (DE, AT, CH, UK, FR, NL, IT, ES, PL, US)
  {
    type: "VEHICLE_PLATE",
    // Context-dependent: requires a preceding keyword like "license plate",
    // "kennzeichen", "nummernschild", "immatriculation", "plate number", etc.
    // to avoid false positives on random letter-number combinations.
    //
    // Without context, plate formats (e.g., "B AB 1234") are too ambiguous
    // and would match many non-plate strings. The keyword requirement
    // eliminates nearly all false positives while still catching explicit mentions.
    regex:
      /(?:license[\s_-]?plate|plate[\s_-]?(?:number|no|nr)|kennzeichen|nummernschild|kfz[\s_-]?kennzeichen|immatriculation|registration[\s_-]?(?:number|no|nr|plate)|vrm|numberplate)[:\s#=]*([A-Z0-9]{1,4}[\s-]?[A-Z0-9]{1,4}[\s-]?[A-Z0-9]{1,6})\b/gi,
    label: "Vehicle Plate",
    getPlaceholder: (_, i) => `[PLATE_${i + 1}]`,
  },

  // Cryptocurrency wallet addresses (Bitcoin + Ethereum)
  {
    type: "CRYPTO_WALLET",
    // Three branches:
    // Branch 1 — Bitcoin Bech32 (SegWit): bc1 + 25-87 lowercase alphanumeric chars
    //   e.g., bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4
    //
    // Branch 2 — Bitcoin Legacy (P2PKH/P2SH): starts with 1 or 3, 25-34 base58 chars
    //   e.g., 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa
    //   Base58 excludes 0, O, I, l to avoid ambiguity.
    //
    // Branch 3 — Ethereum: 0x + 40 hex characters
    //   e.g., 0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18
    regex:
      /\b(?:bc1[a-z0-9]{25,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,34}|0x[0-9a-fA-F]{40})\b/g,
    label: "Crypto Wallet",
    getPlaceholder: (_, i) => `[WALLET_${i + 1}]`,
  },
];

/**
 * Minimum text length before running PII detection.
 * Most PII patterns (emails, phone numbers, API keys) need at least 6 characters.
 * This avoids running 32 regexes on very short text like "hi" or "ok".
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
 * Generic PII mapping interface with the minimum fields needed for placeholder/original operations.
 * Both PIIMapping (types/chat.ts) and PIIMappingForStorage satisfy this interface.
 */
export interface PIIMappingGeneric {
  placeholder: string;
  original: string;
  type?: string;
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
 * Replace PII original values back with their placeholders in text.
 * Used when copying/downloading/sharing content with PII hidden.
 * This is the reverse of restorePIIInText().
 *
 * @param text Text containing PII original values (already restored)
 * @param mappings Array of PII mappings with placeholder/original pairs
 * @returns Text with original values replaced by placeholders
 */
export function replacePIIOriginalsWithPlaceholders(
  text: string,
  mappings: PIIMappingGeneric[],
): string {
  if (!mappings || mappings.length === 0) return text;

  let result = text;

  // Sort by original length descending to replace longer matches first
  // This prevents partial replacement issues (e.g., replacing "john" before "john@example.com")
  const sortedMappings = [...mappings].sort(
    (a, b) => (b.original?.length || 0) - (a.original?.length || 0),
  );

  for (const mapping of sortedMappings) {
    if (!mapping.original) continue;
    // Replace all occurrences of the original value with the placeholder
    result = result.split(mapping.original).join(mapping.placeholder);
  }

  return result;
}

/**
 * Restore PII placeholders in text with their original values.
 * Used for displaying the original user content in read-only messages.
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
