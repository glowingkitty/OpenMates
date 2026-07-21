/*
 * Revolut Business certificate generation helpers for the OpenMates CLI.
 *
 * Purpose: create the private key and public X.509 certificate Revolut Business
 * requires before consent/token exchange can happen.
 * Architecture: local-only setup helper; private key never leaves the machine.
 * Security: only the public certificate is intended to be pasted into Revolut.
 * Tests: frontend/packages/openmates-cli/tests/cli.test.ts.
 */

import { execFileSync } from "node:child_process";
import { createSign, randomUUID } from "node:crypto";
import { chmodSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";

export const REVOLUT_BUSINESS_CERTIFICATE_DOCS_URL = "https://developer.revolut.com/docs/guides/manage-accounts/get-started/make-your-first-api-request#generate-a-private-and-a-public-certificate";
export const REVOLUT_BUSINESS_DEFAULT_SANDBOX_REDIRECT_URI = "https://app.dev.openmates.org/oauth/revolut-business/callback";
export const REVOLUT_BUSINESS_DEFAULT_PRODUCTION_REDIRECT_URI = "https://openmates.org/oauth/revolut-business/callback";
export const REVOLUT_BUSINESS_DEFAULT_CERTIFICATE_TITLE = "OpenMates FinanceApp";
export const REVOLUT_BUSINESS_CLIENT_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer";
export const REVOLUT_BUSINESS_AUDIENCE = "https://revolut.com";

export type RevolutBusinessCertificateEnvironment = "sandbox" | "production";

export type RevolutBusinessCertificateOptions = {
  environment?: RevolutBusinessCertificateEnvironment;
  outputDir?: string;
  title?: string;
  redirectUri?: string;
  overwrite?: boolean;
};

export type RevolutBusinessCertificateResult = {
  environment: RevolutBusinessCertificateEnvironment;
  title: string;
  redirectUri: string;
  docsUrl: string;
  outputDir: string;
  privateKeyPath: string;
  publicCertificatePath: string;
  publicCertificatePem: string;
};

export type RevolutBusinessConsentUrlOptions = {
  environment?: RevolutBusinessCertificateEnvironment;
  clientId: string;
  redirectUri?: string;
  scope?: string;
};

export type RevolutBusinessAuthorizationTokenResponse = {
  access_token?: string;
  token_type?: string;
  expires_in?: number;
  refresh_token?: string;
  [key: string]: unknown;
};

export type RevolutBusinessAuthorizationExchangeOptions = {
  environment?: RevolutBusinessCertificateEnvironment;
  clientId: string;
  codeOrRedirectUrl: string;
  redirectUri?: string;
  privateKeyPath?: string;
  privateKeyPem?: string;
};

const CERTIFICATE_DAYS = "1825";
const RSA_BITS = "2048";

export function defaultRevolutBusinessCertificateDir(environment: RevolutBusinessCertificateEnvironment): string {
  return join(homedir(), ".openmates", "revolut-business", environment);
}

export function defaultRevolutBusinessRedirectUri(environment: RevolutBusinessCertificateEnvironment): string {
  return environment === "sandbox"
    ? REVOLUT_BUSINESS_DEFAULT_SANDBOX_REDIRECT_URI
    : REVOLUT_BUSINESS_DEFAULT_PRODUCTION_REDIRECT_URI;
}

export function buildRevolutBusinessConsentUrl(options: RevolutBusinessConsentUrlOptions): string {
  const environment = options.environment ?? "sandbox";
  const clientId = options.clientId.trim();
  if (!clientId) throw new Error("Missing Revolut Business client ID.");
  const redirectUri = (options.redirectUri ?? defaultRevolutBusinessRedirectUri(environment)).trim();
  const url = new URL(environment === "sandbox"
    ? "https://sandbox-business.revolut.com/app-confirm"
    : "https://business.revolut.com/app-confirm");
  url.searchParams.set("client_id", clientId);
  url.searchParams.set("redirect_uri", redirectUri);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("scope", options.scope?.trim() || "READ");
  return url.toString();
}

export async function exchangeRevolutBusinessAuthorizationCode(
  options: RevolutBusinessAuthorizationExchangeOptions,
): Promise<RevolutBusinessAuthorizationTokenResponse> {
  const environment = options.environment ?? "sandbox";
  const clientId = options.clientId.trim();
  if (!clientId) throw new Error("Missing Revolut Business client ID.");
  const code = extractRevolutBusinessAuthorizationCode(options.codeOrRedirectUrl);
  if (!code) throw new Error("Missing Revolut Business authorization code.");
  const privateKeyPem = options.privateKeyPem
    ?? readFileSync(options.privateKeyPath ?? join(defaultRevolutBusinessCertificateDir(environment), "privatecert.pem"), "utf8");
  const redirectUri = (options.redirectUri ?? defaultRevolutBusinessRedirectUri(environment)).trim();
  const clientAssertion = generateRevolutBusinessClientAssertion({ clientId, privateKeyPem, redirectUri });
  const response = await fetch(environment === "sandbox"
    ? "https://sandbox-b2b.revolut.com/api/1.0/auth/token"
    : "https://b2b.revolut.com/api/1.0/auth/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code,
      client_assertion_type: REVOLUT_BUSINESS_CLIENT_ASSERTION_TYPE,
      client_assertion: clientAssertion,
    }),
  });
  const payload = await response.json().catch(() => ({})) as RevolutBusinessAuthorizationTokenResponse;
  if (!response.ok) {
    const error = typeof payload.error === "string" ? payload.error : `HTTP ${response.status}`;
    const description = typeof payload.error_description === "string" ? `: ${payload.error_description}` : "";
    throw new Error(`Revolut Business authorization-code exchange failed (${error}${description})`);
  }
  return payload;
}

export function extractRevolutBusinessAuthorizationCode(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return "";
  if (!trimmed.startsWith("http://") && !trimmed.startsWith("https://")) return trimmed;
  const url = new URL(trimmed);
  return url.searchParams.get("code") ?? "";
}

export function generateRevolutBusinessClientAssertion(options: {
  clientId: string;
  privateKeyPem: string;
  redirectUri: string;
  nowSeconds?: number;
}): string {
  const issuer = issuerFromRedirectUri(options.redirectUri);
  const now = options.nowSeconds ?? Math.floor(Date.now() / 1000);
  const header = base64UrlJson({ alg: "RS256", typ: "JWT" });
  const payload = base64UrlJson({
    iss: issuer,
    sub: options.clientId,
    aud: REVOLUT_BUSINESS_AUDIENCE,
    exp: now + 3600,
    iat: now,
    jti: randomUUID(),
  });
  const unsigned = `${header}.${payload}`;
  const signer = createSign("RSA-SHA256");
  signer.update(unsigned);
  signer.end();
  return `${unsigned}.${base64Url(signer.sign(options.privateKeyPem))}`;
}

export function generateRevolutBusinessCertificate(
  options: RevolutBusinessCertificateOptions = {},
): RevolutBusinessCertificateResult {
  const environment = options.environment ?? "sandbox";
  const outputDir = resolve(options.outputDir ?? defaultRevolutBusinessCertificateDir(environment));
  const title = (options.title ?? REVOLUT_BUSINESS_DEFAULT_CERTIFICATE_TITLE).trim();
  const redirectUri = (options.redirectUri ?? defaultRevolutBusinessRedirectUri(environment)).trim();
  if (!title) throw new Error("Revolut certificate title must not be empty.");
  if (!redirectUri.startsWith("https://")) throw new Error("Revolut OAuth redirect URI must start with https://.");

  mkdirSync(outputDir, { recursive: true, mode: 0o700 });
  chmodSync(outputDir, 0o700);
  const privateKeyPath = join(outputDir, "privatecert.pem");
  const publicCertificatePath = join(outputDir, "publiccert.cer");
  if (!options.overwrite && (existsSync(privateKeyPath) || existsSync(publicCertificatePath))) {
    throw new Error(`Revolut certificate files already exist in ${outputDir}. Re-run with --overwrite to replace them.`);
  }

  try {
    execFileSync("openssl", ["genrsa", "-out", privateKeyPath, RSA_BITS], { stdio: "ignore" });
    chmodSync(privateKeyPath, 0o600);
    execFileSync(
      "openssl",
      [
        "req",
        "-new",
        "-x509",
        "-key",
        privateKeyPath,
        "-out",
        publicCertificatePath,
        "-days",
        CERTIFICATE_DAYS,
        "-subj",
        `/CN=${escapeOpenSslSubjectValue(title)}`,
      ],
      { stdio: "ignore" },
    );
  } catch (error) {
    throw new Error(`Failed to generate Revolut Business certificate with openssl: ${error instanceof Error ? error.message : String(error)}`);
  }

  return {
    environment,
    title,
    redirectUri,
    docsUrl: REVOLUT_BUSINESS_CERTIFICATE_DOCS_URL,
    outputDir,
    privateKeyPath,
    publicCertificatePath,
    publicCertificatePem: readFileSync(publicCertificatePath, "utf8").trim(),
  };
}

function escapeOpenSslSubjectValue(value: string): string {
  return value.replace(/[\\/]/g, "\\$&").replace(/\n/g, " ");
}

function issuerFromRedirectUri(redirectUri: string): string {
  const url = new URL(redirectUri);
  return url.host;
}

function base64UrlJson(value: Record<string, unknown>): string {
  return base64Url(Buffer.from(JSON.stringify(value), "utf8"));
}

function base64Url(value: Buffer): string {
  return value.toString("base64").replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
}
