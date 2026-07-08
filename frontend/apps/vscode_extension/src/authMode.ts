/*
 * OpenMates VS Code authentication mode contract.
 *
 * Purpose: keep the first internal VS Code extension release pair-login only.
 * Architecture: the shared app can query this adapter to hide browser-only
 * credential flows while preserving the normal browser app behavior elsewhere.
 * Security: V1 must never collect account passwords, passkeys, recovery keys,
 * backup codes, or 2FA OTPs inside the VS Code webview.
 */

export const VSCODE_ALLOWED_LOGIN_METHODS = ["pair_login"] as const;

export const VSCODE_BLOCKED_LOGIN_METHODS = [
  "passkey",
  "password",
  "2fa_otp",
  "recovery_key",
  "backup_code",
] as const;

export type OpenMatesPlatform = "browser" | "vscode";
export type LoginMethod =
  | (typeof VSCODE_ALLOWED_LOGIN_METHODS)[number]
  | (typeof VSCODE_BLOCKED_LOGIN_METHODS)[number];

const BROWSER_LOGIN_METHODS: LoginMethod[] = [
  "passkey",
  "password",
  "2fa_otp",
  "recovery_key",
  "backup_code",
  "pair_login",
];

export function getVisibleLoginMethods(platform: OpenMatesPlatform): LoginMethod[] {
  if (platform === "vscode") return [...VSCODE_ALLOWED_LOGIN_METHODS];
  return [...BROWSER_LOGIN_METHODS];
}

export function isLoginMethodAllowedInVscode(method: string): boolean {
  return (VSCODE_ALLOWED_LOGIN_METHODS as readonly string[]).includes(method);
}
