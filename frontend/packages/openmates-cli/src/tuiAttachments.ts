/** Resolve explicit local @path attachments when the terminal user sends a message. */
import { createEmbedRef, createEmbedReferenceBlock, toonEncodeContent, type PreparedEmbed } from "./embedCreator.js";
import { formatEmbedsForMessage, processFilesAsync } from "./fileEmbed.js";
import { extractMentionTokens } from "./mentions.js";
import { OutputRedactor } from "./outputRedactor.js";
import { adoptUploadEmbedId, transcribeUploadedAudio, uploadFile } from "./uploadService.js";
import type { OpenMatesClient } from "./client.js";

export type PreparedTuiMessage = {
  message: string;
  preparedEmbeds: PreparedEmbed[];
  displayNames: string[];
};

const isExplicitPath = (token: string): boolean =>
  token.startsWith("./") || token.startsWith("../") || token.startsWith("~/") || token.startsWith("/");

function removePathMentions(message: string, paths: string[]): string {
  const values = new Set(paths);
  return message.replace(/(^|\s)@([^\s@]+)/g, (whole, before: string, token: string) =>
    values.has(token) ? before : whole).trim();
}

/** Call only from an explicit send action; message editing must not read local files. */
export async function prepareTuiMessage(client: OpenMatesClient, message: string): Promise<PreparedTuiMessage> {
  const paths = [...new Set(extractMentionTokens(message).filter(isExplicitPath))];
  if (!paths.length) return { message, preparedEmbeds: [], displayNames: [] };
  if (!client.hasSession()) {
    throw new Error("File attachments require a signed-in account. Sign in, then send this draft again.");
  }

  const redactor = new OutputRedactor();
  try {
    redactor.initializeFromMemories(await client.listMemories());
  } catch (error) {
    throw new Error(`Could not load privacy settings for file attachments: ${error instanceof Error ? error.message : String(error)}`);
  }

  const result = await processFilesAsync(paths, redactor);
  const failures = [
    ...result.blocked.map((item) => `Blocked @${item.path}: ${item.error}`),
    ...result.errors.map((item) => `Cannot attach @${item.path}: ${item.error}`),
  ];
  if (failures.length) throw new Error(failures.join("\n"));
  if (result.embeds.length !== paths.length) throw new Error("Some file attachments could not be prepared. Check the paths and try again.");

  const session = client.getSession();
  for (const file of result.embeds) {
    if (!file.requiresUpload) continue;
    if (!file.localPath) throw new Error(`Cannot upload ${file.displayName}: local path is missing.`);
    try {
      const uploaded = await uploadFile(file.localPath, session);
      adoptUploadEmbedId(file.embed, uploaded.embed_id);
      const type = file.embed.type;
      const transcription = type === "audio-recording"
        ? await transcribeUploadedAudio(uploaded, file.displayName, session, { requestId: file.embed.embedId })
        : null;
      const embedRef = file.embed.embedRef ?? createEmbedRef(type, uploaded.embed_id);
      file.embed.embedRef = embedRef;

      const content = type === "audio-recording" ? {
        app_id: "audio", skill_id: "transcribe", type: "audio-recording", status: "finished",
        filename: file.displayName, embed_ref: embedRef, mime_type: uploaded.content_type,
        transcript: transcription?.transcript ?? null,
        transcript_original: transcription?.transcript_original ?? null,
        transcript_corrected: transcription?.transcript_corrected ?? null,
        use_corrected: transcription?.use_corrected ?? null,
        correction_model: transcription?.correction_model ?? null,
        model: transcription?.model ?? null,
        waveform: transcription?.waveform ?? null,
        s3_base_url: uploaded.s3_base_url, files: uploaded.files,
        aes_key: uploaded.aes_key, aes_nonce: uploaded.aes_nonce,
        vault_wrapped_aes_key: uploaded.vault_wrapped_aes_key,
      } : type === "pdf" ? {
        type: "pdf", status: "processing", filename: file.displayName, embed_ref: embedRef,
        page_count: uploaded.page_count ?? null, content_hash: uploaded.content_hash,
        s3_base_url: uploaded.s3_base_url, files: uploaded.files,
        aes_key: uploaded.aes_key, aes_nonce: uploaded.aes_nonce,
        vault_wrapped_aes_key: uploaded.vault_wrapped_aes_key,
      } : {
        type: "image", app_id: "images", skill_id: "upload", status: "finished",
        filename: file.displayName, embed_ref: embedRef, content_hash: uploaded.content_hash,
        s3_base_url: uploaded.s3_base_url, files: uploaded.files,
        aes_key: uploaded.aes_key, aes_nonce: uploaded.aes_nonce,
        vault_wrapped_aes_key: uploaded.vault_wrapped_aes_key,
        ai_detection: uploaded.ai_detection,
      };
      file.embed.content = toonEncodeContent(content);
      file.embed.status = type === "pdf" ? "processing" : "finished";
      file.embed.contentHash = uploaded.content_hash;
      file.referenceBlock = createEmbedReferenceBlock(embedRef);
    } catch (error) {
      throw new Error(`Could not upload ${file.displayName}: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  return {
    message: removePathMentions(message, paths) + formatEmbedsForMessage(result.embeds),
    preparedEmbeds: result.embeds.map((file) => file.embed),
    displayNames: result.embeds.map((file) => file.displayName),
  };
}
