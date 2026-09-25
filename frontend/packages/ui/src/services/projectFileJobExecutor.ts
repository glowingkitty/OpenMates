/** Client-owned execution of transient Project file jobs; ciphertext stays client-owned. */
import {
  isProjectFileMutationOperation, projectFileMutationDigest, validateProjectFileMutation,
  type ProjectFileMutation,
} from "../utils/projectFileMutationProtocol";

export interface ProjectWriteApprovalRequest {
  projectId: string;
  chatId: string;
  mutation: ProjectFileMutation;
}

export interface ProjectReadApprovalRequest {
  projectId: string;
  sourceId: string | null;
  chatId: string;
  operationId: string;
  path: string;
}

export interface ProjectApprovedIgnoredRead {
  path: string;
  chatId: string;
  operationId: string;
}

export interface ProjectFileJob {
  protocol_version: 1;
  operation_id: string;
  chat_id: string;
  project_id: string;
  source_id?: string | null;
  operation: "list" | "search" | "read_text" | "create_file" | "update_file";
  arguments: Record<string, unknown>;
  lease_token: string;
  lease_generation: number;
  lease_expires_at: number;
}

export interface ProjectFileExecutionContext {
  projectKey: Uint8Array;
  /** Actual source selected by the fresh resolver; null identifies hosted Project files. */
  sourceId?: string | null;
  writeMode: "apply_and_show" | "always_ask" | null;
  execute: (
    job: ProjectFileJob,
    mutation?: ProjectFileMutation,
    approvedIgnoredRead?: ProjectApprovedIgnoredRead,
  ) => Promise<unknown>;
}

export interface ProjectFileJobExecutorOptions {
  isActiveChat: (chatId: string) => boolean;
  send: (event: string, payload: Record<string, unknown>) => void | Promise<void>;
  /** Must freshly validate current focus/access, never trust authority in the event. */
  resolve: (job: ProjectFileJob) => Promise<ProjectFileExecutionContext>;
  approve: (request: ProjectWriteApprovalRequest, proposalDigest: string) => Promise<void>;
  requestApproval?: (request: ProjectWriteApprovalRequest) => boolean | Promise<boolean>;
  onWaitingForUser?: (request: ProjectWriteApprovalRequest) => void;
  requestReadApproval?: (request: ProjectReadApprovalRequest) => boolean | Promise<boolean>;
  onWaitingForRead?: (request: ProjectReadApprovalRequest) => void;
  /** Client-only display of the exact proposal after a confirmed successful edit. */
  onMutationApplied?: (request: ProjectWriteApprovalRequest) => void;
}

const OPERATIONS = new Set(["list", "search", "read_text", "create_file", "update_file"]);
const SAFE_CODE = /^[a-z][a-z0-9_]{1,79}$/;

function identity(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const item = value as Record<string, unknown>;
  if (item.protocol_version !== 1 || !OPERATIONS.has(String(item.operation))
      || [item.operation_id, item.chat_id, item.project_id].some((id) => typeof id !== "string" || !id || id.length > 128)) return null;
  return item;
}

function scope(job: Pick<ProjectFileJob, "operation_id" | "chat_id" | "project_id">): Record<string, unknown> {
  return { protocol_version: 1, operation_id: job.operation_id, chat_id: job.chat_id, project_id: job.project_id };
}

export function createProjectFileJobExecutor(options: ProjectFileJobExecutorOptions) {
  let stopped = false;
  const processing = new Set<string>();
  // This is only a prompt-deduplication hint; server authority is checked on every write.
  const approved = new Map<string, string>();
  const approvedIgnoredReads = new Set<string>();
  const active = (chatId: string) => !stopped && options.isActiveChat(chatId);

  async function available(value: unknown): Promise<void> {
    const item = identity(value);
    if (!item || !active(String(item.chat_id)) || processing.has(String(item.operation_id))) return;
    await options.send("project_file_operation_claim", scope(item as unknown as ProjectFileJob));
  }

  async function request(value: unknown): Promise<void> {
    const item = identity(value);
    if (!item || !active(String(item.chat_id)) || processing.has(String(item.operation_id))) return;
    if (typeof item.lease_token !== "string" || item.lease_token.length < 16
        || !Number.isSafeInteger(item.lease_generation) || Number(item.lease_generation) < 1
        || typeof item.lease_expires_at !== "number" || !item.arguments
        || typeof item.arguments !== "object" || Array.isArray(item.arguments)) return;
    const job = item as unknown as ProjectFileJob;
    processing.add(job.operation_id);
    let leaseReleased = false;
    const result = async (status: string, body: unknown) => {
      await options.send("project_file_operation_result", {
        ...scope(job), lease_token: job.lease_token, lease_generation: job.lease_generation,
        status, result: body,
      });
    };
    try {
      const context = await options.resolve(job);
      if (!active(job.chat_id)) throw Object.assign(new Error(), { code: "chat_inactive" });
      if (job.lease_expires_at * 1000 <= Date.now()) throw Object.assign(new Error(), { code: "lease_expired" });
      let mutation: ProjectFileMutation | undefined;
      let proposalCommitment: string | undefined;
      if (isProjectFileMutationOperation(job.operation)) {
        mutation = validateProjectFileMutation({ ...job.arguments, operation: job.operation, operation_id: job.operation_id });
        if (!context.writeMode) throw Object.assign(new Error(), { code: "write_policy_required" });
        const digest = await projectFileMutationDigest(context.projectKey, job.project_id, job.chat_id, mutation);
        proposalCommitment = digest;
        if (context.writeMode === "always_ask" && approved.get(job.operation_id) !== digest) {
          const approvalRequest = { projectId: job.project_id, chatId: job.chat_id, mutation };
          await result("awaiting_approval", { proposal_commitment: digest, proposal: mutation });
          leaseReleased = true;
          options.onWaitingForUser?.(approvalRequest);
          if (!options.requestApproval) return;
          const accepted = await options.requestApproval(approvalRequest);
          if (!active(job.chat_id)) return;
          if (!accepted) {
            await options.send("project_file_operation_reject", scope(job));
            return;
          }
          await options.approve(approvalRequest, digest);
          approved.set(job.operation_id, digest);
          // A new lease is mandatory: never execute under the pre-approval lease.
          processing.delete(job.operation_id);
          await options.send("project_file_operation_claim", scope(job));
          return;
        }
      }
      if (job.lease_expires_at * 1000 <= Date.now()) throw Object.assign(new Error(), { code: "lease_expired" });
      const requestedPath = job.operation === "read_text" && typeof job.arguments.path === "string"
        ? job.arguments.path : null;
      const readApprovalRequest: ProjectReadApprovalRequest | null = requestedPath ? {
        projectId: job.project_id,
        sourceId: context.sourceId !== undefined ? context.sourceId : job.source_id ?? null,
        chatId: job.chat_id,
        operationId: job.operation_id,
        path: requestedPath,
      } : null;
      const readApprovalKey = readApprovalRequest
        ? JSON.stringify([readApprovalRequest.projectId, readApprovalRequest.sourceId, readApprovalRequest.chatId, readApprovalRequest.path])
        : null;
      let output: unknown;
      try {
        output = await context.execute(job, mutation,
          readApprovalRequest && readApprovalKey && approvedIgnoredReads.has(readApprovalKey)
            ? { path: readApprovalRequest.path, chatId: job.chat_id, operationId: job.operation_id }
            : undefined);
      } catch (error) {
        const code = (error as { code?: unknown })?.code;
        if (code !== "ignored_path_requires_approval" || !readApprovalRequest || !readApprovalKey) throw error;
        await result("awaiting_approval", { reason: "ignored_path_requires_approval", path: readApprovalRequest.path });
        leaseReleased = true;
        options.onWaitingForRead?.(readApprovalRequest);
        if (!options.requestReadApproval) return;
        const accepted = await options.requestReadApproval(readApprovalRequest);
        if (!active(job.chat_id)) return;
        if (!accepted) {
          await options.send("project_file_operation_reject", scope(job));
          return;
        }
        approvedIgnoredReads.add(readApprovalKey);
        processing.delete(job.operation_id);
        await options.send("project_file_operation_claim", scope(job));
        return;
      }
      approved.delete(job.operation_id);
      await result("completed", { ...(output && typeof output === "object" ? output : { value: output }), ...(proposalCommitment ? { proposal_commitment: proposalCommitment } : {}) });
      if (mutation) {
        // Display failure cannot turn an acknowledged successful write into a failed job.
        try { options.onMutationApplied?.({ projectId: job.project_id, chatId: job.chat_id, mutation }); }
        catch { /* The committed result remains authoritative. */ }
      }
    } catch (error) {
      // The original error may contain a private path, command, or credential.
      const rawCode = (error as { code?: unknown })?.code;
      const candidate = typeof rawCode === "string" ? rawCode.toLowerCase() : rawCode;
      const code = typeof candidate === "string" && SAFE_CODE.test(candidate) ? candidate : "client_execution_failed";
      if (!leaseReleased) {
        if (["source_offline", "protocol_timeout", "file_key_unavailable"].includes(code)) {
          await result("waiting_for_executor", { reason: code });
        } else {
          await result(["stale_base", "revision_conflict", "file_exists", "file_changed", "target_exists", "operation_conflict"].includes(code) ? "conflict" : "failed", { code });
        }
      }
    } finally {
      processing.delete(job.operation_id);
    }
  }

  return { available, request, stop: () => { stopped = true; approved.clear(); approvedIgnoredReads.clear(); } };
}
