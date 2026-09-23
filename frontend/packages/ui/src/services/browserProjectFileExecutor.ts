/** Browser assembly for encrypted Project file jobs. */
import { encode as toonEncode } from "@toon-format/toon";
import { get } from "svelte/store";

import { userProfile } from "../stores/userProfile";
import {
  recordProjectFileChange,
  requestProjectIgnoredReadApproval,
  requestProjectWriteApproval,
} from "../stores/projectFileApprovalStore";
import {
  decryptWithEmbedKey,
  encryptWithEmbedKey,
  wrapEmbedKeyWithChatKey,
} from "./cryptoService";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import {
  executeHostedProjectFileJob,
  type HostedProjectFile,
} from "./hostedProjectFileExecutor";
import {
  createProjectFileJobExecutor,
  type ProjectFileJob,
  type ProjectReadApprovalRequest,
  type ProjectWriteApprovalRequest,
} from "./projectFileJobExecutor";
import {
  approveProjectWrite,
  getActiveProjectFocus,
  getProject,
  getProjectContents,
  getProjectFileRevisionReceipt,
  getProjectSettings,
  listProjectSources,
  readEncryptedProjectFile,
  requestProjectRemoteAccess,
} from "./projectService";
import type { ProjectFileMutation } from "../utils/projectFileMutationProtocol";
import { broadcastProjectFilesChanged } from "./projectBrowserEvents";

export interface BrowserProjectFileTransport {
  send: (event: string, payload: Record<string, unknown>) => void | Promise<void>;
  commit: (payload: Record<string, unknown>) => Promise<Record<string, unknown>>;
}

export interface BrowserProjectFileExecutorOptions {
  transport: BrowserProjectFileTransport;
  isActiveChat: (chatId: string) => boolean;
  requestApproval?: (request: ProjectWriteApprovalRequest) => boolean | Promise<boolean>;
  requestReadApproval?: (request: ProjectReadApprovalRequest) => boolean | Promise<boolean>;
  onWaitingForUser?: (request: ProjectWriteApprovalRequest) => void;
  onWaitingForRead?: (request: ProjectReadApprovalRequest) => void;
  onMutationApplied?: (request: ProjectWriteApprovalRequest) => void;
}

const MAX_PRIVATE_PATHS = 256;

function fail(code: string): never {
  throw Object.assign(new Error(code), { code });
}

function privatePathsFromSettings(value: string | null): string[] {
  if (value === null) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    fail("protected_path");
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) fail("protected_path");
  const fileAccess = (parsed as Record<string, unknown>).file_access;
  if (fileAccess === undefined) return [];
  if (!fileAccess || typeof fileAccess !== "object" || Array.isArray(fileAccess)) fail("protected_path");
  const privatePaths = (fileAccess as Record<string, unknown>).private_paths;
  if (privatePaths === undefined) return [];
  if (!Array.isArray(privatePaths) || privatePaths.length > MAX_PRIVATE_PATHS
      || privatePaths.some((path) => typeof path !== "string" || !path || path.length > 4096)) {
    fail("protected_path");
  }
  return privatePaths as string[];
}

async function authoritativePrivatePaths(
  encryptedSettings: string | null | undefined,
  projectKey: Uint8Array,
): Promise<string[]> {
  if (!encryptedSettings) return [];
  const plaintext = await decryptWithEmbedKey(encryptedSettings, projectKey);
  if (plaintext === null) fail("protected_path");
  return privatePathsFromSettings(plaintext);
}

/** Build one browser executor. ChatSync owns its WebSocket and auth lifetime. */
export function createBrowserProjectFileExecutor(options: BrowserProjectFileExecutorOptions) {
  let stopped = false;
  const executor = createProjectFileJobExecutor({
    isActiveChat: (chatId) => !stopped && options.isActiveChat(chatId),
    send: options.transport.send,
    requestApproval: options.requestApproval ?? requestProjectWriteApproval,
    requestReadApproval: options.requestReadApproval ?? requestProjectIgnoredReadApproval,
    onWaitingForUser: options.onWaitingForUser,
    onWaitingForRead: options.onWaitingForRead,
    onMutationApplied: options.onMutationApplied ?? ((request) => {
      recordProjectFileChange(request);
      broadcastProjectFilesChanged(request.projectId);
    }),
    approve: async (request, proposalDigest) => {
      const focus = await getActiveProjectFocus(request.chatId);
      if (focus?.project_id !== request.projectId) fail("project_focus_required");
      await approveProjectWrite(request.projectId, {
        chat_id: request.chatId,
        operation_id: request.mutation.operation_id,
        proposal_digest: proposalDigest,
      }, { teamId: focus.team_id });
    },
    resolve: async (job) => {
      const focus = await getActiveProjectFocus(job.chat_id);
      if (focus?.project_id !== job.project_id) fail("project_focus_required");
      const chatKey = await chatKeyManager.getKey(job.chat_id);
      if (!chatKey) fail("chat_key_unavailable");
      const context = { teamId: focus.team_id };
      const project = await getProject(job.project_id, context);
      const [settings, sources, contents] = await Promise.all([
        getProjectSettings(project, context),
        listProjectSources(project, context),
        getProjectContents(project, context),
      ]);
      const privatePaths = await authoritativePrivatePaths(
        settings.encrypted.encrypted_settings,
        project.projectKey,
      );
      const source = job.source_id
        ? sources.find((candidate) => candidate.source_id === job.source_id)
        : sources.length === 1 ? sources[0] : undefined;
      if (job.source_id && !source || !job.source_id && sources.length > 1) {
        fail("source_selection_required");
      }
      return {
        projectKey: project.projectKey,
        sourceId: source?.source_id ?? null,
        writeMode: settings.selectionRequired ? null : settings.writeMode,
        execute: async (
          currentJob: ProjectFileJob,
          mutation?: ProjectFileMutation,
          approvedIgnoredRead?: { path: string; chatId: string; operationId: string },
        ) => {
          if (stopped || !options.isActiveChat(job.chat_id)) fail("chat_inactive");
          const currentFocus = await getActiveProjectFocus(job.chat_id);
          if (currentFocus?.project_id !== job.project_id || currentFocus.team_id !== focus.team_id) {
            fail("project_focus_required");
          }
          if (source) {
            const ownerId = get(userProfile).user_id;
            if (!ownerId) fail("requester_identity_unavailable");
            return requestProjectRemoteAccess(
              project,
              source,
              { ownerId, teamId: focus.team_id },
              currentJob.operation,
              mutation ? { chat_id: job.chat_id, mutation } : currentJob.arguments,
              undefined,
              approvedIgnoredRead,
            );
          }
          return executeHostedProjectFileJob({
            projectId: job.project_id,
            projectKey: project.projectKey,
            chatKey,
            teamId: focus.team_id,
            privatePaths,
            isIgnoredReadApproved: (path, approvalJob) => Boolean(
              approvedIgnoredRead
              && approvedIgnoredRead.path === path
              && approvedIgnoredRead.chatId === approvalJob.chat_id
              && approvedIgnoredRead.operationId === approvalJob.operation_id
            ),
            encrypt: encryptWithEmbedKey,
            wrap: wrapEmbedKeyWithChatKey,
            encodeContent: async (content) => toonEncode(content),
            listFiles: async () => {
              const files: HostedProjectFile[] = [];
              for (const item of contents.items) {
                if (item.item_type !== "embed" && item.item_type !== "upload" || !item.target_id) continue;
                let metadata = item.metadata;
                if (item.encrypted.encrypted_metadata) {
                  const plaintext = await decryptWithEmbedKey(item.encrypted.encrypted_metadata, project.projectKey);
                  if (plaintext === null) {
                    files.push({ embedId: item.target_id, path: "/" });
                    continue;
                  }
                  try {
                    const parsed = JSON.parse(plaintext) as unknown;
                    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error();
                    metadata = parsed as Record<string, unknown>;
                  } catch {
                    files.push({ embedId: item.target_id, path: "/" });
                    continue;
                  }
                }
                const path = metadata.path ?? metadata.file_path ?? metadata.filename ?? item.displayName;
                if (typeof path === "string" && path) files.push({ embedId: item.target_id, path });
              }
              return files;
            },
            readHead: (embedId) => readEncryptedProjectFile(project, embedId, { teamId: focus.team_id }),
            receipt: (embedId, receiptJob, digest) => getProjectFileRevisionReceipt(
              job.project_id,
              embedId,
              receiptJob.operation_id,
              receiptJob.chat_id,
              digest,
              { teamId: focus.team_id },
            ),
            commit: options.transport.commit,
          }, currentJob, mutation);
        },
      };
    },
  });
  return {
    available: executor.available,
    request: executor.request,
    stop: () => {
      if (stopped) return;
      stopped = true;
      executor.stop();
    },
  };
}
