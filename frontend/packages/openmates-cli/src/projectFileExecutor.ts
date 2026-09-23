/** Saved-chat Project executor. Decryption and patch application stay on this client. */
import { randomUUID } from "node:crypto";
import type { OpenMatesClient } from "./client.js";
import type { OpenMatesWsClient } from "./ws.js";
import { decryptWithAesGcmCombined, encryptBytesWithAesGcm, encryptWithAesGcmCombined } from "./crypto.js";
import { requestProjectRemoteOperation } from "./projectRequester.js";
import { createProjectFileJobExecutor, type ProjectWriteApprovalRequest } from "../../ui/src/services/projectFileJobExecutor.js";
import { executeHostedProjectFileJob, normalizeHostedProjectPath, type HostedProjectFile } from "../../ui/src/services/hostedProjectFileExecutor.js";
import { toonEncodeContent } from "./embedCreator.js";

export async function activateCliProjectFocus(client: OpenMatesClient, projectId: string, chatId: string, teamId: string | null): Promise<void> {
  const context = { teamId, personal: !teamId };
  const [detail, settings] = await Promise.all([client.getProject(projectId, context), client.getProjectSettings(projectId, context)]);
  const key = await client.decryptProjectKey(detail.project, context);
  if (!settings.encrypted_settings || settings.selection_required) throw new Error("Choose this Project's write policy in Project settings before starting work.");
  const text = await decryptWithAesGcmCombined(settings.encrypted_settings, key);
  const focus = text ? (JSON.parse(text) as { default_focus?: { focus_id?: string; instructions?: string } }).default_focus : undefined;
  if (!focus?.focus_id || typeof focus.instructions !== "string") throw new Error("The Project's default focus is unavailable.");
  await client.activateProjectFocus(projectId, { chat_id: chatId, focus_id: focus.focus_id, instruction: focus.instructions }, context);
}

export function registerCliProjectFileExecutor(options: {
  client: OpenMatesClient;
  ws: OpenMatesWsClient;
  chatId: string;
  chatKey: Uint8Array;
  requestApproval?: (request: ProjectWriteApprovalRequest) => boolean | Promise<boolean>;
}) {
  let closed = false;
  const executor = createProjectFileJobExecutor({
    isActiveChat: (chatId) => !closed && chatId === options.chatId,
    send: (event, payload) => options.ws.sendAsync(event, payload),
    requestApproval: options.requestApproval,
    approve: async (request, digest) => {
      const focus = await options.client.getActiveProjectFocus(request.chatId);
      if (focus?.project_id !== request.projectId) throw Object.assign(new Error(), { code: "project_focus_required" });
      await options.client.approveProjectWrite(request.projectId, { chat_id: request.chatId, operation_id: request.mutation.operation_id, proposal_digest: digest }, { teamId: focus.team_id, personal: !focus.team_id });
    },
    resolve: async (job) => {
      const focus = await options.client.getActiveProjectFocus(job.chat_id);
      if (focus?.project_id !== job.project_id) throw Object.assign(new Error(), { code: "project_focus_required" });
      const context = { teamId: focus.team_id, personal: !focus.team_id };
      const [detail, settings, sources] = await Promise.all([
        options.client.getProject(job.project_id, context),
        options.client.getProjectSettings(job.project_id, context),
        options.client.listProjectSources(job.project_id, context),
      ]);
      const projectKey = await options.client.decryptProjectKey(detail.project, context);
      const source = job.source_id ? sources.find((item) => item.source_id === job.source_id) : sources.length === 1 ? sources[0] : undefined;
      if (job.source_id && !source || !job.source_id && sources.length > 1) throw Object.assign(new Error(), { code: "source_selection_required" });
      return {
        projectKey,
        writeMode: settings.selection_required ? null : settings.write_mode,
        execute: async (currentJob, mutation) => {
          if (closed) throw Object.assign(new Error(), { code: "chat_inactive" });
          if (source) return requestProjectRemoteOperation({
            client: options.client, projectId: job.project_id, projectKey, source,
            operation: currentJob.operation,
            arguments: mutation ? { chat_id: job.chat_id, mutation } : currentJob.arguments,
            context,
          });
          return executeHostedProjectFileJob({
            projectId: job.project_id, projectKey, chatKey: options.chatKey, teamId: focus.team_id,
            encrypt: encryptWithAesGcmCombined, wrap: encryptBytesWithAesGcm,
            encodeContent: async (content) => toonEncodeContent(content),
            listFiles: async () => {
              const files: HostedProjectFile[] = [];
              for (const item of detail.items) {
                if (item.item_type !== "embed" && item.item_type !== "upload") continue;
                const [target, metadataText, displayName] = await Promise.all([
                  decryptWithAesGcmCombined(item.target_id_encrypted, projectKey),
                  item.encrypted_metadata ? decryptWithAesGcmCombined(item.encrypted_metadata, projectKey) : null,
                  item.encrypted_display_name ? decryptWithAesGcmCombined(item.encrypted_display_name, projectKey) : null,
                ]);
                const metadata = metadataText ? JSON.parse(metadataText) as Record<string, unknown> : {};
                const path = metadata.path ?? metadata.file_path ?? metadata.filename ?? displayName;
                if (!target || typeof path !== "string") continue;
                try { files.push({ embedId: target, path: normalizeHostedProjectPath(path) }); } catch { /* Protected/non-file items are not source files. */ }
              }
              return files;
            },
            readHead: (embedId) => options.client.readEncryptedProjectFile(job.project_id, embedId, projectKey, context),
            receipt: (embedId, receiptJob, digest) => options.client.getProjectFileRevisionReceipt(job.project_id, embedId, receiptJob.operation_id, receiptJob.chat_id, digest, context),
            commit: async (payload) => {
              const requestId = randomUUID();
              const pending = options.ws.waitForMessage("commit_embed_revision_result", (value) => (value as Record<string, unknown>).request_id === requestId, 30_000);
              await options.ws.sendAsync("commit_embed_revision", { ...payload, request_id: requestId });
              return (await pending).payload as Record<string, unknown>;
            },
          }, currentJob, mutation);
        },
      };
    },
  });
  const listeners = [
    options.ws.onMessageType("project_file_operation_available", (payload) => { void executor.available(payload).catch(() => {}); }),
    options.ws.onMessageType("project_file_operation_request", (payload) => { void executor.request(payload).catch(() => {}); }),
  ];
  const stop = () => { closed = true; executor.stop(); listeners.forEach((off) => off()); };
  options.ws.onClose(stop);
  return stop;
}
