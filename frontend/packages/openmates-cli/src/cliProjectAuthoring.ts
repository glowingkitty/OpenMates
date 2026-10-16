/** Two-stage Project recommendation; authoring starts only from an explicit user action. */
import { createHash } from "node:crypto";
import type { OpenMatesClient } from "./client.js";
import { decryptWithAesGcmCombined } from "./crypto.js";
import { loadActiveCliProjectContext, parseFocusAuthoringDocument, type FocusAuthoringDocument } from "./cliJevContext.js";
import { parseChatContextEvent, type ChatContextEvent } from "./chatContextEvents.js";

export type AuthoringHistory = Array<{ role: "user" | "assistant"; content: string }>;
export type AuthoringRecommendation = Extract<ChatContextEvent, { type: "project_authoring_recommendation" }>;
export function boundedAuthoringHistory(rows: Array<{ role: string; content: string }>): AuthoringHistory {
  const history = rows.filter((row): row is AuthoringHistory[number] => ["user", "assistant"].includes(row.role) && Boolean(row.content.trim()));
  if (history.length <= 60 && history.reduce((sum, row) => sum + row.content.length, 0) <= 12_000) return history;
  const firstUser = history.find(row => row.role === "user");
  const recent = history.slice(-8).map(row => ({ ...row, content: row.content.slice(0, 1000) }));
  return firstUser && history.length > 8 ? [{ ...firstUser, content: firstUser.content.slice(0, 3000) }, ...recent] : recent;
}

export function projectItemRevision(item: Record<string, unknown>): string {
  return createHash("sha256").update(["updated_at", "encrypted_metadata", "encrypted_note", "target_id_hash", "deleted_target_state"]
    .map(field => item[field] ? String(item[field]) : "").join("\0")).digest("hex");
}

async function selectedFocus(client: OpenMatesClient, chatId: string, projectId: string, targetId: string, revision: string): Promise<FocusAuthoringDocument> {
  const focus = await client.getActiveProjectFocus(chatId);
  if (focus?.project_id !== projectId) throw new Error("This Project Focus is no longer active.");
  const options = { teamId: focus.team_id, personal: !focus.team_id };
  const detail = await client.getProject(projectId, options);
  const item = detail.items.find(item => item.project_item_id === targetId && item.item_type === "embed" && !item.deleted_target_state);
  if (!item || projectItemRevision(item) !== revision) throw new Error("The selected Project Focus changed. Refresh the recommendation.");
  const key = await client.decryptProjectKey(detail.project, options);
  const target = await decryptWithAesGcmCombined(item.target_id_encrypted, key);
  if (!target) throw new Error("The selected Project Focus is unavailable.");
  const head = await client.readEncryptedProjectFile(projectId, target, key, options);
  const document = [head.content.text, head.content.markdown, head.content.code, head.content.content].find(value => typeof value === "string");
  if (typeof document !== "string") throw new Error("The selected Project Focus document is unavailable.");
  const latest = await client.getActiveProjectFocus(chatId);
  if (latest?.project_id !== projectId || latest.team_id !== focus.team_id || latest.focus_id !== focus.focus_id || latest.activated_at !== focus.activated_at) throw new Error("This Project Focus is no longer active.");
  return parseFocusAuthoringDocument(document);
}

export async function assessCliProjectAuthoring(client: OpenMatesClient, frame: {
  chat_id: string; project_id: string; user_message_id: string;
}, history: AuthoringHistory): Promise<AuthoringRecommendation[]> {
  const active = await client.getActiveProjectFocus(frame.chat_id);
  if (active?.project_id !== frame.project_id || !history.length) return [];
  const context = await loadActiveCliProjectContext(client, frame.chat_id);
  if (context.projectId !== frame.project_id || context.focusCatalogComplete === false) return [];
  const options = { teamId: active.team_id, personal: !active.team_id };
  const [detail, workflows] = await Promise.all([client.getProject(frame.project_id, options), client.listWorkflows(options)]);
  const key = await client.decryptProjectKey(detail.project, options);
  const linked = new Set<string>();
  for (const item of detail.items.filter(item => item.item_type === "workflow" && !item.deleted_target_state)) {
    const id = await decryptWithAesGcmCombined(item.target_id_encrypted, key); if (id) linked.add(id);
  }
  const catalog: Array<{ kind: "focus" | "workflow"; id: string; title: string; summary: string; revision: string }> =
    (context.project_focus_catalog ?? []).map(entry => ({ kind: "focus", ...entry }));
  for (const workflow of workflows) {
    if (!linked.has(workflow.id) || workflow.status === "deleted" || !Number.isSafeInteger(workflow.version) || Number(workflow.version) < 1) continue;
    if (catalog.length >= 40) return []; // An incomplete catalog must not become a duplicate Create proposal.
    catalog.push({ kind: "workflow", id: workflow.id, title: workflow.title.slice(0, 200), summary: (workflow.description ?? "").slice(0, 640), revision: String(workflow.version) });
  }
  const recommendations = await client.requestProjectAuthoringRecommendations(frame.project_id, {
    chat_id: frame.chat_id, message_id: frame.user_message_id, team_id: active.team_id, catalog, history,
  });
  const result: AuthoringRecommendation[] = [];
  for (let recommendation of recommendations) {
    if (recommendation.chat_id !== frame.chat_id || recommendation.project_id !== frame.project_id) continue;
    if (recommendation.action === "inspect" && recommendation.kind === "focus"
        && typeof recommendation.target_id === "string" && typeof recommendation.expected_revision === "string"
        && typeof recommendation.recommendation_id === "string") {
      const document = await selectedFocus(client, frame.chat_id, frame.project_id, recommendation.target_id, recommendation.expected_revision);
      const inspected = await client.inspectProjectFocusRecommendation(frame.project_id, {
        assessment_id: recommendation.recommendation_id, document, history,
      });
      if (!inspected) continue;
      recommendation = inspected;
    }
    const event = parseChatContextEvent({ ...recommendation, type: "project_authoring_recommendation",
      event_id: recommendation.recommendation_id,
      created_at: Math.floor(Number(recommendation.created_at ?? (Number(recommendation.expires_at) - 1200))) }, frame.chat_id);
    if (event?.type === "project_authoring_recommendation") result.push(event);
  }
  return result;
}

export async function startCliProjectAuthoring(client: OpenMatesClient, recommendation: AuthoringRecommendation, history: AuthoringHistory): Promise<Record<string, unknown>> {
  const active = await client.getActiveProjectFocus(recommendation.chat_id ?? "");
  if (active?.project_id !== recommendation.project_id) throw new Error("This Project is no longer active in the chat.");
  const target = recommendation.kind === "focus" && recommendation.action === "update"
    ? await selectedFocus(client, recommendation.chat_id!, recommendation.project_id, recommendation.target_id!, recommendation.expected_revision!) : undefined;
  let remoteBinding: Record<string, unknown> | undefined;
  if (recommendation.kind === "workflow" && recommendation.target_id) {
    const options = { teamId: active.team_id, personal: !active.team_id };
    const detail = await client.getProject(recommendation.project_id, options);
    const key = await client.decryptProjectKey(detail.project, options);
    for (const item of detail.items.filter(item => item.item_type === "workflow" && !item.deleted_target_state)) {
      if (await decryptWithAesGcmCombined(item.target_id_encrypted, key) !== recommendation.target_id) continue;
      const text = item.encrypted_metadata ? await decryptWithAesGcmCombined(item.encrypted_metadata, key) : null;
      const metadata = text ? JSON.parse(text) as Record<string, unknown> : {};
      if (metadata.remote_workflow_file && typeof metadata.remote_workflow_file === "object") remoteBinding = metadata.remote_workflow_file as Record<string, unknown>;
      break;
    }
  }
  return client.startProjectAuthoringJob(recommendation.project_id, { ...(remoteBinding ? { remote_binding: remoteBinding } : {}), recommendation_id: recommendation.recommendation_id,
    expected_revision: recommendation.expected_revision ?? null, history, ...(target ? { target } : {}),
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone });
}
