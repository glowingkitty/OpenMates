// frontend/packages/ui/src/services/codeRunArtifactEmbeds.ts
//
// Materializes Code Run output metadata as client-encrypted child embeds.
// Child records inherit the parent code embed key and use deterministic IDs so
// same-path reruns update version history instead of creating duplicate children.
// The parent linkage is persisted only after every current child is stored.

import type { CodeRunArtifact, SendEmbedDataPayload } from '../types/chat';
import { codeRunArtifactChildId, routeCodeRunArtifactChild } from './codeRunArtifacts';
import { chatSyncService } from './chatSyncService';
import { handleSendEmbedDataImpl } from './chatSyncServiceHandlersAI';
import { sendStoreEmbedImpl } from './chatSyncServiceSenders';
import { embedStore } from './embedStore';

export interface CodeRunArtifactChild {
  embedId: string;
  path: string;
  appId: string;
  frontendType: string;
  renderer: 'registered_native' | 'generic_file';
  versionNumber: number;
}

interface MaterializeCodeRunArtifactChildrenInput {
  artifacts: CodeRunArtifact[];
  parentEmbedId: string;
  chatId: string;
  sourceExecutionId: string;
}

export async function materializeCodeRunArtifactChildren({
  artifacts,
  parentEmbedId,
  chatId,
  sourceExecutionId,
}: MaterializeCodeRunArtifactChildrenInput): Promise<CodeRunArtifactChild[]> {
  const parentEntry = await embedStore.getRawEntry(`embed:${parentEmbedId}`);
  if (
    !parentEntry?.hashed_chat_id
    || !parentEntry.hashed_message_id
    || !parentEntry.hashed_user_id
  ) {
    throw new Error(`Parent embed ${parentEmbedId} is missing persistence indexes`);
  }
  const persistenceIndexes = {
    hashed_chat_id: parentEntry.hashed_chat_id,
    hashed_message_id: parentEntry.hashed_message_id,
    hashed_user_id: parentEntry.hashed_user_id,
  };

  const orderedArtifacts = [...artifacts].sort((left, right) => (
    (left.normalized_path || left.path).localeCompare(right.normalized_path || right.path)
  ));
  const children: CodeRunArtifactChild[] = [];

  for (const artifact of orderedArtifacts) {
    const normalizedPath = artifact.normalized_path || artifact.path;
    const childEmbedId = codeRunArtifactChildId(parentEmbedId, normalizedPath);
    const versionNumber = (artifact.versions?.length ?? 0) + 1;
    const route = routeCodeRunArtifactChild(artifact);
    const content = buildArtifactChildContent({
      artifact,
      parentEmbedId,
      sourceExecutionId,
      versionNumber,
      appId: route.appId,
      frontendType: route.frontendType,
    });
    const now = Date.now();
    await handleSendEmbedDataImpl(chatSyncService, {
      embed_id: childEmbedId,
      type: route.frontendType,
      content: JSON.stringify(content),
      status: 'finished',
      chat_id: chatId,
      message_id: parentEmbedId,
      parent_embed_id: parentEmbedId,
      version_number: versionNumber,
      file_path: normalizedPath,
      app_id: route.appId,
      skill_id: route.frontendType,
      createdAt: now,
      updatedAt: now,
    } as unknown as SendEmbedDataPayload, persistenceIndexes);
    children.push({
      embedId: childEmbedId,
      path: normalizedPath,
      appId: route.appId,
      frontendType: route.frontendType,
      renderer: route.renderer,
      versionNumber,
    });
  }

  const parentPayload = await embedStore.updateChildEmbedIds(
    parentEmbedId,
    children.map((child) => child.embedId),
  );
  await sendStoreEmbedImpl(chatSyncService, parentPayload);
  return children;
}

function buildArtifactChildContent({
  artifact,
  parentEmbedId,
  sourceExecutionId,
  versionNumber,
  appId,
  frontendType,
}: {
  artifact: CodeRunArtifact;
  parentEmbedId: string;
  sourceExecutionId: string;
  versionNumber: number;
  appId: string;
  frontendType: string;
}): Record<string, unknown> {
  const normalizedPath = artifact.normalized_path || artifact.path;
  const common = {
    app_id: appId,
    skill_id: frontendType,
    type: frontendType,
    status: 'finished',
    parent_embed_id: parentEmbedId,
    source_execution_id: sourceExecutionId,
    path: artifact.path,
    normalized_path: normalizedPath,
    filename: normalizedPath.split('/').pop() || normalizedPath,
    mime_type: artifact.mime_type,
    size_bytes: artifact.size_bytes,
    asset_id: artifact.asset_id,
    variant: artifact.variant,
    download_url: artifact.download_url,
    download_expires_at: artifact.download_expires_at,
    version_number: versionNumber,
    versions: artifact.versions || [],
  };
  if (artifact.native_render_payload && appId === artifact.native_render_payload.app_id) {
    return { ...artifact.native_render_payload.content, ...common };
  }
  return common;
}
