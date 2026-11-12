/**
 * Display helpers of a videos.generate card (the result card and the request card).
 *
 * - Progress: processing updates of the result child carry `progress_stage`,
 *   `progress_attempt` and, for a change of an earlier video, `change` and
 *   `source_embed_id` (wire contract: backend/apps/videos/tasks/generate_progress.py).
 * - Maker: the model that made the video, shown once as "Created by <name>".
 * - Thumbnail: the card never loads the MP4; it shows `files.thumbnail`, which is
 *   encrypted with the same AES key as `files.original`, or a public poster.
 */
import { getModelDisplayName } from '../../../utils/modelDisplayName';
import { hasMediaEncryptionMetadata } from '../../../services/encryption/mediaEncryption';
import { decodeToonContent, resolveEmbed } from '../../../services/embedResolver';
import { createImageUrlOwner, fetchAndDecryptImage, getCachedImageUrl } from '../images/imageEmbedCrypto';

export const VIDEO_PROGRESS_STAGES = ['deciding', 'writing', 'rendering', 'correcting', 'generating'] as const;
export type VideoProgressStage = (typeof VIDEO_PROGRESS_STAGES)[number];
export const VIDEO_CHANGES = ['edit', 'extend_start', 'extend_end'] as const;
export type VideoChange = (typeof VIDEO_CHANGES)[number];

export interface VideoProgress {
  stage?: VideoProgressStage;
  /** 1-based round of the stage (a correction counts the rounds). */
  attempt?: number;
  change?: VideoChange;
  /** Embed id of the video being changed. */
  sourceEmbedId?: string;
}

export const EMPTY_VIDEO_PROGRESS: VideoProgress = {};

export interface VideoFileVariant {
  s3_key: string;
  size_bytes?: number;
  format?: string;
  mime_type?: string;
  duration_seconds?: number;
  aes_nonce?: string;
  encryption?: string;
}

export interface VideoFiles {
  original?: VideoFileVariant;
  thumbnail?: VideoFileVariant;
}

type Translate = (key: string, options?: { values: Record<string, string> }) => string;
type ImageUrlOwner = ReturnType<typeof createImageUrlOwner>;

function isStage(value: unknown): value is VideoProgressStage {
  return typeof value === 'string' && (VIDEO_PROGRESS_STAGES as readonly string[]).includes(value);
}

function isChange(value: unknown): value is VideoChange {
  return typeof value === 'string' && (VIDEO_CHANGES as readonly string[]).includes(value);
}

/** Merge one processing update into the known progress; unknown values keep the previous state. */
export function readVideoProgress(
  content: Record<string, unknown> | null | undefined,
  prev: VideoProgress = EMPTY_VIDEO_PROGRESS,
): VideoProgress {
  if (!content) return prev;
  const stage = isStage(content.progress_stage) ? content.progress_stage : prev.stage;
  const attempt = typeof content.progress_attempt === 'number' && content.progress_attempt >= 1
    ? Math.floor(content.progress_attempt)
    : (stage === prev.stage ? prev.attempt : undefined);
  const change = isChange(content.change) ? content.change : prev.change;
  const sourceEmbedId = typeof content.source_embed_id === 'string' && content.source_embed_id
    ? content.source_embed_id
    : prev.sourceEmbedId;
  return { stage, attempt, change, sourceEmbedId };
}

/** Card props of decoded generated_video content beyond the shared media fields (maker, progress, change). */
export function videoGenerateCardProps(content: Record<string, unknown> | null | undefined): {
  authorModel?: string; madeBy?: string; progressStage?: VideoProgressStage; progressAttempt?: number;
  change?: VideoChange; sourceEmbedId?: string;
} {
  const progress = readVideoProgress(content);
  return {
    authorModel: typeof content?.author_model === 'string' ? content.author_model : undefined,
    madeBy: typeof content?.made_by === 'string' ? content.made_by : undefined,
    progressStage: progress.stage,
    progressAttempt: progress.attempt,
    change: progress.change,
    sourceEmbedId: progress.sourceEmbedId,
  };
}

/** Translated label of the current step, or undefined before the first step is known. */
export function videoStageText(progress: VideoProgress, t: Translate): string | undefined {
  if (!progress.stage) return undefined;
  if (progress.stage === 'correcting' && progress.attempt) {
    return t('embeds.video_generate.progress_correcting_round', { values: { round: String(progress.attempt) } });
  }
  return t(`embeds.video_generate.progress_${progress.stage}`);
}

/** Translated label of the kind of change, or undefined for a new video. */
export function videoChangeText(change: VideoChange | undefined, t: Translate): string | undefined {
  return change ? t(`embeds.video_generate.change_${change}`) : undefined;
}

/**
 * Display name of the model that made the video: the author model of a composed
 * video, the video model of a generative one. `composed` is a route, not a model.
 */
export function videoMakerName(content: { model?: string; authorModel?: string; madeBy?: string }): string | undefined {
  const candidates = content.madeBy === 'composed'
    ? [content.authorModel, content.model]
    : [content.model, content.authorModel];
  const id = candidates.find((value) => typeof value === 'string' && value.trim() && value !== 'composed');
  return id ? getModelDisplayName(id.trim()) : undefined;
}

export interface VideoThumbnailSource {
  previewImageUrl?: string;
  s3BaseUrl?: string;
  files?: VideoFiles;
  aesKey?: string;
  aesNonce?: string;
}

function readString(content: Record<string, unknown>, ...keys: string[]): string | undefined {
  for (const key of keys) {
    const value = content[key];
    if (typeof value === 'string' && value) return value;
  }
  return undefined;
}

/** The thumbnail inputs of decoded generated_video content. */
export function videoThumbnailSourceOf(content: Record<string, unknown>): VideoThumbnailSource {
  return {
    previewImageUrl: readString(content, 'previewImageUrl', 'preview_image_url'),
    s3BaseUrl: readString(content, 's3_base_url'),
    files: typeof content.files === 'object' && content.files !== null ? content.files as VideoFiles : undefined,
    aesKey: readString(content, 'aes_key'),
    aesNonce: readString(content, 'aes_nonce'),
  };
}

/**
 * URL of the video's still image: the public poster, else the decrypted
 * `files.thumbnail`. Undefined when the video has neither (older embeds).
 * The decrypted image stays retained by `owner` until the owner is destroyed.
 */
export async function loadVideoThumbnail(source: VideoThumbnailSource, owner: ImageUrlOwner): Promise<string | undefined> {
  if (source.previewImageUrl) return source.previewImageUrl;
  const file = source.files?.thumbnail;
  if (!file?.s3_key || !source.s3BaseUrl || !source.aesKey || !hasMediaEncryptionMetadata(file, source.aesNonce)) {
    return undefined;
  }
  let url = getCachedImageUrl(file.s3_key);
  if (!url) {
    await fetchAndDecryptImage(source.s3BaseUrl, file.s3_key, source.aesKey, source.aesNonce ?? '', file);
    url = getCachedImageUrl(file.s3_key);
  }
  owner.retain(file.s3_key);
  return url;
}

/** Thumbnail of another video embed from this client's embed store (the video being changed). */
export async function loadSourceVideoThumbnail(
  embedId: string,
  chatId: string | null,
  owner: ImageUrlOwner,
): Promise<string | undefined> {
  const embed = await resolveEmbed(embedId, { chatId });
  const content = embed?.content ? await decodeToonContent(embed.content) : null;
  return content ? loadVideoThumbnail(videoThumbnailSourceOf(content), owner) : undefined;
}
