/**
 * Browser/CLI shared proposal commitment for encrypted Project file writes.
 *
 * The server can compare an approval with a proposal without receiving paths,
 * file hashes, or a guessable plaintext-content digest. The executing client
 * recomputes this keyed commitment after decrypting the proposal.
 */
export interface ProjectFileMutation {
  operation: "create_file" | "update_file";
  operation_id: string;
  path: string;
  expected_base: string | null;
  content?: string;
  patch?: string;
}

export const PROJECT_FILE_OPERATIONS = ["create_file", "update_file"] as const;

export function isProjectFileMutationOperation(value: string): value is ProjectFileMutation["operation"] {
  return value === "create_file" || value === "update_file";
}

export function validateProjectFileMutation(value: unknown): ProjectFileMutation {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("invalid_file_mutation");
  }
  const input = value as Record<string, unknown>;
  const allowed = new Set(["operation", "operation_id", "path", "expected_base", "content", "patch"]);
  if (Object.keys(input).some((key) => !allowed.has(key))
    || typeof input.operation !== "string" || !isProjectFileMutationOperation(input.operation)
    || typeof input.operation_id !== "string" || !/^[a-zA-Z0-9._:-]{1,128}$/.test(input.operation_id)
    || typeof input.path !== "string" || !input.path || input.path.length > 4096
    || input.path.includes("\0")) {
    throw new Error("invalid_file_mutation");
  }
  if (input.operation === "create_file") {
    if (input.expected_base !== null || typeof input.content !== "string" || input.patch !== undefined) {
      throw new Error("invalid_file_mutation");
    }
  } else if (typeof input.expected_base !== "string" || !/^[a-f0-9]{64}$/.test(input.expected_base)
    || typeof input.patch !== "string" || !input.patch || input.content !== undefined) {
    throw new Error("invalid_file_mutation");
  }
  if (new TextEncoder().encode((input.content ?? input.patch) as string).byteLength > 200 * 1024) {
    throw new Error("file_mutation_too_large");
  }
  return input as unknown as ProjectFileMutation;
}

export async function projectFileMutationDigest(
  projectKey: Uint8Array,
  projectId: string,
  chatId: string,
  proposal: ProjectFileMutation,
): Promise<string> {
  const mutation = validateProjectFileMutation(proposal);
  if (projectKey.byteLength !== 32 || !projectId || !chatId) {
    throw new Error("invalid_file_mutation_identity");
  }
  // An ordered tuple also avoids JSON object-order differences across callers.
  const message = JSON.stringify([
    "openmates-project-file-proposal-v1", projectId, chatId,
    mutation.operation, mutation.operation_id, mutation.path, mutation.expected_base,
    mutation.content ?? null, mutation.patch ?? null,
  ]);
  const keyBytes = new Uint8Array(projectKey).buffer;
  const key = await crypto.subtle.importKey("raw", keyBytes, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message));
  return Array.from(new Uint8Array(signature), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
