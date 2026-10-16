/** Explicit device-local model controls; ordinary CLI startup never downloads. */
import { createInterface } from "node:readline/promises";
import { dirname } from "node:path";
import { rm } from "node:fs/promises";
import {
  ENHANCED_ANONYMIZATION_LABEL, installPrivacyModel, privacyModelPath, privacyStatus, privacyCapability,
  updatePrivacyPreferences, verifyInstalledModel, verifyPrivacyRuntime,
} from "./privacyModel.js";
import { privacyRpc, stopPrivacyDaemon } from "./privacyWorker.js";

export const PRIVACY_HELP = `${ENHANCED_ANONYMIZATION_LABEL}
  openmates privacy install [--yes] [--download-only] [--model-file PATH]
  openmates privacy status [--json]
  openmates privacy enable|disable
  openmates privacy enable|disable --documents
  openmates privacy enable|disable --project FULL_PROJECT_ID
  openmates privacy update [--yes]
  openmates privacy remove [--yes]

About 1.6 GB download, 2 GB active RAM. First supported target: Linux ARM64
with FP16/dot-product instructions, 2 CPU cores and 4 GB RAM (8 GB recommended).
Messages are scanned when enabled. Documents and Projects require separate opt-in.
Inference runs offline; disabling keeps existing deterministic detection.
`;

export async function runPrivacyCommand(action = "status", options: {
  yes?: boolean; downloadOnly?: boolean; modelFile?: string; documents?: boolean;
  project?: string; json?: boolean; progress?: (received: number, total: number) => void;
} = {}): Promise<string> {
  if (action === "help") return PRIVACY_HELP;
  if (options.project && !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(options.project)) throw new Error("Use the full Project ID for its local privacy setting.");
  const confirm = async (question: string) => {
    if (options.yes) return;
    if (!process.stdin.isTTY || !process.stdout.isTTY) throw new Error("This explicit operation requires --yes in scripts.");
    const rl = createInterface({ input: process.stdin, output: process.stdout });
    try { if (!/^y(?:es)?$/i.test((await rl.question(question + " [y/N] ")).trim())) throw new Error("Cancelled. Existing privacy settings are unchanged."); }
    finally { rl.close(); }
  };
  if (action === "install" || action === "update") {
    await confirm(`Download and ${options.downloadOnly ? "install" : "enable"} ${ENHANCED_ANONYMIZATION_LABEL}? About 1.6 GB disk and 2 GB active RAM.`);
    await installPrivacyModel({ ...options });
    return options.downloadOnly ? "Offline model installed. Run 'openmates privacy enable' to enable message scanning." : "Offline model installed and enabled for messages. Documents and Projects retain their separate settings.";
  }
  if (action === "enable" || action === "disable") {
    const enabled = action === "enable";
    if (enabled) { const capability = await privacyCapability(); if (!capability.supported) throw new Error(capability.reason); await verifyInstalledModel(); await verifyPrivacyRuntime(); }
    await updatePrivacyPreferences((p) => ({ ...p,
      enabled: options.documents || options.project ? (enabled || p.enabled) : enabled,
      documents: options.documents ? enabled : p.documents,
      projects: options.project ? [...new Set(enabled ? [...p.projects, options.project] : p.projects.filter((id) => id !== options.project))] : p.projects,
    }));
    if (!enabled && !options.documents && !options.project) await stopPrivacyDaemon();
    return `${options.documents ? "Document" : options.project ? "Project" : "Message"} enhanced scanning ${enabled ? "enabled" : "disabled"}. Existing deterministic detection remains available.`;
  }
  if (action === "remove") {
    await confirm("Remove the offline model from this device? This affects all CLI profiles using it.");
    await stopPrivacyDaemon();
    await updatePrivacyPreferences((p) => ({ ...p, enabled: false }));
    // Only the managed, pinned model directory is removed; no Project/account data.
    await rm(dirname(privacyModelPath()), { recursive: true, force: true });
    return "Offline model removed. Existing deterministic detection remains available.";
  }
  if (action !== "status") throw new Error(PRIVACY_HELP);
  const status = await privacyStatus();
  try { const worker = await privacyRpc({ op: "status" }, 500); status.worker = worker.state; }
  catch { status.worker = "stopped"; }
  if (options.json) return JSON.stringify(status, null, 2);
  return `${ENHANCED_ANONYMIZATION_LABEL}\nState: ${status.state} · worker: ${status.worker}\nMessages: ${status.messages ? "on" : "off"} · documents: ${status.documents ? "on" : "off"}\nEnhanced Projects: ${(status.projects as string[]).length}\n${status.reason ?? "No text is sent to an external inference service."}`;
}
