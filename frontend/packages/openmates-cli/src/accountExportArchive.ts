/**
 * Account Export V1 archive writer.
 *
 * Purpose: create a local human-readable export layout from resumable job chunks.
 * Architecture: docs/specs/account-export-v1/spec.yml.
 * Security: rejects reusable credential/key fields before they are written.
 * Privacy: writes only user-requested export data and excludes root checksums.
 * Tests: frontend/packages/openmates-cli/tests/account-export.test.ts.
 */

const ACCOUNT_EXPORT_FORBIDDEN_FIELD_NAMES = new Set([
  "access_token",
  "api_key",
  "backup_code_hash",
  "encrypted_master_key",
  "lookup_hash",
  "password_hash",
  "private_key",
  "raw_key",
  "refresh_token",
  "share_key",
  "signing_secret",
  "token_hash",
  "totp_seed",
  "webhook_secret",
]);

const ACCOUNT_EXPORT_REDACTION_CATEGORIES = [
  "api_credentials",
  "authentication_tokens",
  "key_material",
  "password_and_recovery_hashes",
  "webhook_secrets",
];

const ACCOUNT_EXPORT_FORBIDDEN_VALUE_PATTERNS: RegExp[] = [
  /-----BEGIN [A-Z ]*PRIVATE KEY-----/,
  /(?:^|[^a-z0-9])sk-(?:api|proj|live|test)[-_a-z0-9]{6,}/i,
  /#key=[A-Za-z0-9_-]{8,}/,
];

export type AccountExportArchiveBundle = {
  export: Record<string, unknown>;
  manifest: Record<string, unknown>;
  chunks: Array<Record<string, unknown>>;
};

export type AccountExportArchiveResult = {
  output: string;
  format: "zip" | "directory";
  files: number;
};

export async function writeAccountExportArchive(
  bundle: AccountExportArchiveBundle,
  flags: Record<string, string | boolean> = {},
): Promise<AccountExportArchiveResult> {
  const { mkdir, mkdtemp, rm, writeFile } = await import("node:fs/promises");
  const { tmpdir } = await import("node:os");
  const { execFileSync } = await import("node:child_process");
  const { join, dirname } = await import("node:path");
  const exportId = safeArchiveSegment(String(bundle.export.export_id ?? `export-${Date.now()}`));
  const archiveFormat = flags.format === "directory" ? "directory" : "zip";
  const outputPath = typeof flags.output === "string"
    ? flags.output
    : join(process.cwd(), archiveFormat === "zip" ? `openmates-account-export-${exportId}.zip` : `openmates-account-export-${exportId}`);
  const stagingDir = archiveFormat === "directory"
    ? outputPath
    : await mkdtemp(join(tmpdir(), `openmates-account-export-${exportId}-`));
  const writtenFiles: string[] = [];

  async function writeArchiveText(relativePath: string, content: string): Promise<void> {
    assertAccountExportTextSafe(content, relativePath);
    const fullPath = join(stagingDir, relativePath);
    await mkdir(dirname(fullPath), { recursive: true });
    await writeFile(fullPath, content, "utf-8");
    writtenFiles.push(relativePath);
  }

  await writeArchiveText("README.md", buildAccountExportReadme(bundle));
  await writeArchiveText("manifest.yml", serializeArchiveYaml(bundle.manifest));
  await writeArchiveText("manifest.json", `${JSON.stringify(bundle.manifest, null, 2)}\n`);
  await writeArchiveText("export-report.yml", serializeArchiveYaml(buildAccountExportReport(bundle)));

  const domainPayloads = collectAccountExportDomainPayloads(bundle.chunks);
  for (const [domain, payloads] of Object.entries(domainPayloads)) {
    const domainFile = payloads.length === 1 ? payloads[0] : { chunks: payloads };
    await writeArchiveText(`domains/${safeArchiveSegment(domain)}.json`, `${JSON.stringify(domainFile, null, 2)}\n`);
  }
  await writeAccountExportChatFiles(domainPayloads.chats ?? [], writeArchiveText);

  if (archiveFormat === "directory") return { output: outputPath, format: "directory", files: writtenFiles.length };

  await mkdir(dirname(outputPath), { recursive: true });
  try {
    execFileSync("zip", ["-r", outputPath, "."], { cwd: stagingDir, stdio: "pipe" });
    return { output: outputPath, format: "zip", files: writtenFiles.length };
  } finally {
    await rm(stagingDir, { recursive: true, force: true });
  }
}

export function assertAccountExportPayloadSafe(value: unknown, path = "$export"): void {
  if (value === null || value === undefined) return;
  if (typeof value === "string") {
    for (const pattern of ACCOUNT_EXPORT_FORBIDDEN_VALUE_PATTERNS) {
      if (pattern.test(value)) throw new Error(`Account export contains forbidden secret-like value at ${path}`);
    }
    return;
  }
  if (typeof value !== "object") return;
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertAccountExportPayloadSafe(item, `${path}[${index}]`));
    return;
  }
  for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
    const normalizedKey = key.toLowerCase();
    if (ACCOUNT_EXPORT_FORBIDDEN_FIELD_NAMES.has(normalizedKey)) {
      throw new Error(`Account export contains forbidden secret field '${key}' at ${path}`);
    }
    assertAccountExportPayloadSafe(child, `${path}.${key}`);
  }
}

export function sanitizeAccountExportManifest(manifest: Record<string, unknown>): Record<string, unknown> {
  const copy = JSON.parse(JSON.stringify(manifest)) as Record<string, unknown>;
  const report = copy.report;
  if (report && typeof report === "object" && !Array.isArray(report)) {
    const reportObject = report as Record<string, unknown>;
    if (Array.isArray(reportObject.redactions)) {
      reportObject.redactions = ACCOUNT_EXPORT_REDACTION_CATEGORIES;
    }
  }
  assertAccountExportPayloadSafe(copy, "$manifest");
  return copy;
}

function assertAccountExportTextSafe(content: string, relativePath: string): void {
  for (const pattern of ACCOUNT_EXPORT_FORBIDDEN_VALUE_PATTERNS) {
    if (pattern.test(content)) throw new Error(`Account export file ${relativePath} contains forbidden secret-like content`);
  }
  for (const field of ACCOUNT_EXPORT_FORBIDDEN_FIELD_NAMES) {
    if (new RegExp(`"?${field}"?\\s*:`, "i").test(content)) {
      throw new Error(`Account export file ${relativePath} contains forbidden secret field '${field}'`);
    }
  }
}

function buildAccountExportReadme(bundle: AccountExportArchiveBundle): string {
  const selectedDomains = Array.isArray(bundle.manifest.selected_domains) ? bundle.manifest.selected_domains.map(String) : [];
  return [
    "# OpenMates Account Export",
    "",
    `Export ID: ${String(bundle.export.export_id ?? "unknown")}`,
    `Status: ${String(bundle.export.status ?? "unknown")}`,
    `Schema: ${String(bundle.manifest.schema_version ?? "account-export-v1")}`,
    `Exported at: ${new Date().toISOString()}`,
    "",
    "## Contents",
    "",
    "- `manifest.yml` records selected domains, filters, and domain status.",
    "- `export-report.yml` summarizes completion, failures, and redacted categories.",
    "- `domains/` contains one JSON file per exported domain.",
    "- `chats/` contains one Markdown and one YAML file per chat when chat rows include readable content.",
    "",
    "## Selected Domains",
    "",
    ...(selectedDomains.length > 0 ? selectedDomains.map((domain) => `- ${domain}`) : ["- none"]),
    "",
    "Reusable credentials, token hashes, private keys, and raw secrets are intentionally excluded.",
    "",
  ].join("\n");
}

function buildAccountExportReport(bundle: AccountExportArchiveBundle): Record<string, unknown> {
  const report = bundle.manifest.report && typeof bundle.manifest.report === "object" && !Array.isArray(bundle.manifest.report)
    ? bundle.manifest.report as Record<string, unknown>
    : {};
  return {
    export_id: bundle.export.export_id ?? null,
    status: bundle.export.status ?? report.status ?? "unknown",
    selected_domains: Array.isArray(bundle.manifest.selected_domains) ? bundle.manifest.selected_domains : [],
    failures: Array.isArray(report.failures) ? report.failures : [],
    redacted_secret_categories: ACCOUNT_EXPORT_REDACTION_CATEGORIES,
    partial_requires_acceptance: Boolean(report.partial_requires_acceptance),
  };
}

function collectAccountExportDomainPayloads(chunks: Array<Record<string, unknown>>): Record<string, Array<Record<string, unknown>>> {
  const grouped: Record<string, Array<Record<string, unknown>>> = {};
  for (const chunk of chunks) {
    const domain = safeArchiveSegment(String(chunk.domain ?? "unknown"));
    const payload = chunk.payload && typeof chunk.payload === "object" && !Array.isArray(chunk.payload)
      ? chunk.payload as Record<string, unknown>
      : { value: chunk.payload ?? null };
    grouped[domain] = grouped[domain] ?? [];
    grouped[domain].push({
      chunk_id: chunk.chunk_id ?? null,
      sequence: chunk.sequence ?? null,
      status: chunk.status ?? null,
      ...payload,
    });
  }
  return grouped;
}

async function writeAccountExportChatFiles(
  chatPayloads: Array<Record<string, unknown>>,
  writeArchiveText: (relativePath: string, content: string) => Promise<void>,
): Promise<void> {
  const chats: Array<Record<string, unknown>> = [];
  for (const payload of chatPayloads) {
    if (Array.isArray(payload.items)) {
      chats.push(...payload.items.filter((item): item is Record<string, unknown> => item !== null && typeof item === "object" && !Array.isArray(item)));
    }
  }
  for (const [index, chat] of chats.entries()) {
    const chatId = safeArchiveSegment(String(chat.id ?? chat.chat_id ?? `chat-${index + 1}`));
    await writeArchiveText(`chats/${chatId}.yml`, serializeArchiveYaml({ chat, messages: Array.isArray(chat.messages) ? chat.messages : [] }));
    await writeArchiveText(`chats/${chatId}.md`, buildAccountExportChatMarkdown(chat));
  }
}

function buildAccountExportChatMarkdown(chat: Record<string, unknown>): string {
  const title = String(chat.title ?? chat.name ?? chat.id ?? chat.chat_id ?? "Untitled Chat");
  const lines = [`# ${title}`, ""];
  if (typeof chat.summary === "string" && chat.summary.trim()) {
    lines.push("## Summary", "", chat.summary.trim(), "");
  }
  const messages = Array.isArray(chat.messages) ? chat.messages : [];
  if (messages.length > 0) {
    lines.push("## Messages", "");
    for (const message of messages) {
      if (!message || typeof message !== "object" || Array.isArray(message)) continue;
      const record = message as Record<string, unknown>;
      lines.push(`### ${String(record.role ?? record.sender ?? "message")}`, "", String(record.content ?? record.text ?? ""), "");
    }
  } else {
    lines.push("No readable message records were included in this export chunk.", "");
  }
  return `${lines.join("\n")}\n`;
}

function serializeArchiveYaml(data: Record<string, unknown>, indent = 0): string {
  const pad = "  ".repeat(indent);
  let out = "";
  for (const [key, val] of Object.entries(data)) {
    if (val === null || val === undefined) {
      out += `${pad}${key}: null\n`;
    } else if (typeof val === "boolean" || typeof val === "number") {
      out += `${pad}${key}: ${val}\n`;
    } else if (typeof val === "string") {
      out += val.includes("\n") ? `${pad}${key}: |\n${val.split("\n").map((line) => `${pad}  ${line}`).join("\n")}\n` : `${pad}${key}: ${quoteYamlString(val)}\n`;
    } else if (Array.isArray(val)) {
      out += `${pad}${key}:\n`;
      for (const item of val) {
        if (item && typeof item === "object" && !Array.isArray(item)) {
          out += `${pad}- \n${serializeArchiveYaml(item as Record<string, unknown>, indent + 2)}`;
        } else {
          out += `${pad}- ${typeof item === "string" ? quoteYamlString(item) : String(item)}\n`;
        }
      }
    } else if (typeof val === "object") {
      out += `${pad}${key}:\n${serializeArchiveYaml(val as Record<string, unknown>, indent + 1)}`;
    }
  }
  return out;
}

function quoteYamlString(value: string): string {
  const needsQuote = value.includes(":") || value.includes("#") || value.startsWith("{") || value.startsWith("[") || value === "" || ["true", "false", "null"].includes(value);
  return needsQuote ? `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"` : value;
}

function safeArchiveSegment(value: string): string {
  const cleaned = value.trim().replace(/[^a-zA-Z0-9._-]+/g, "-").replace(/^-+|-+$/g, "");
  return cleaned || "unknown";
}
