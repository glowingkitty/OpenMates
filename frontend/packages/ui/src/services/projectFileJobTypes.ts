/** Types of transient Project file jobs and their approval prompts (the core runs the protocol). */
import type { ProjectFileMutation } from "../utils/projectFileMutationProtocol";
import type { ProjectFilePrivacy } from "./projectFilePrivacy";

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
  privacy?: ProjectFilePrivacy;
  /** Actual source selected by the fresh resolver; null identifies hosted Project files. */
  sourceId?: string | null;
  writeMode: "apply_and_show" | "always_ask" | null;
  execute: (
    job: ProjectFileJob,
    mutation?: ProjectFileMutation,
    approvedIgnoredRead?: ProjectApprovedIgnoredRead,
  ) => Promise<unknown>;
}

