/*
 * Project file-risk classifier for CLI remote-access safety checks.
 *
 * Purpose: keep high-risk write/read exclusions deterministic before any LLM
 * reasoning or future patch-apply flow is considered.
 * Architecture: mirrors backend/shared/python_utils/project_file_risk.py.
 * Security: built-in and user-protected sensitive paths require explicit user
 * approval; this module never silently weakens Project policy.
 * Tests: frontend/packages/openmates-cli/tests/remoteAccess.test.ts.
 */

export interface ProjectFileRiskResult {
  isHighRisk: boolean;
  reasons: string[];
}

const SECRET_OR_ENVIRONMENT_PATTERNS = [
  ".env",
  ".env.*",
  "**/.env",
  "**/.env.*",
];

const DEPLOYMENT_OR_CONFIG_PATTERNS = [
  "Caddyfile",
  "Dockerfile",
  "docker-compose.yml",
  "docker-compose.*.yml",
  "**/terraform/**",
  "**/*.tf",
];

const DEPENDENCY_EXECUTION_PATTERNS = [
  "package.json",
  "package-lock.json",
  "pnpm-lock.yaml",
  "yarn.lock",
  "requirements.txt",
  "pyproject.toml",
  "poetry.lock",
];

const AUTH_SECURITY_PRIVACY_PATTERNS = [
  "**/auth/**",
  "**/security/**",
  "**/privacy/**",
  "**/compliance/**",
  "**/*auth*",
  "**/*security*",
  "**/*privacy*",
];

const MIGRATION_SCHEMA_CI_PATTERNS = [
  "**/migrations/**",
  "**/schemas/**",
  ".github/workflows/**",
  ".gitignore",
];

const BUILT_IN_PATTERNS: Array<{ reason: string; patterns: string[] }> = [
  { reason: "secret_or_environment_file", patterns: SECRET_OR_ENVIRONMENT_PATTERNS },
  { reason: "deployment_or_config_file", patterns: DEPLOYMENT_OR_CONFIG_PATTERNS },
  { reason: "dependency_or_execution_file", patterns: DEPENDENCY_EXECUTION_PATTERNS },
  { reason: "auth_security_privacy_or_compliance_file", patterns: AUTH_SECURITY_PRIVACY_PATTERNS },
  { reason: "migration_schema_or_ci_file", patterns: MIGRATION_SCHEMA_CI_PATTERNS },
];

export function classifyProjectFileRisk(path: string, userProtectedPatterns: string[] = []): ProjectFileRiskResult {
  const normalizedPath = normalizePath(path);
  const reasons: string[] = [];

  for (const group of BUILT_IN_PATTERNS) {
    if (group.patterns.some((pattern) => matchesPattern(normalizedPath, pattern))) {
      reasons.push(group.reason);
    }
  }

  if (userProtectedPatterns.some((pattern) => matchesPattern(normalizedPath, normalizePath(pattern)))) {
    reasons.push("user_protected_pattern");
  }

  return { isHighRisk: reasons.length > 0, reasons: [...new Set(reasons)] };
}

function normalizePath(path: string): string {
  return path.replace(/\\/g, "/").replace(/^\.\//, "");
}

function matchesPattern(path: string, pattern: string): boolean {
  const regex = new RegExp(`^${globToRegex(pattern)}$`);
  return regex.test(path);
}

function globToRegex(pattern: string): string {
  let output = "";
  for (let index = 0; index < pattern.length; index += 1) {
    const char = pattern[index];
    const next = pattern[index + 1];
    if (char === "*" && next === "*") {
      output += ".*";
      index += 1;
    } else if (char === "*") {
      output += "[^/]*";
    } else {
      output += escapeRegex(char ?? "");
    }
  }
  return output;
}

function escapeRegex(value: string): string {
  return value.replace(/[|\\{}()[\]^$+?.]/g, "\\$&");
}
