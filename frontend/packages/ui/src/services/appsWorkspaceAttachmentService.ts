import { uploadFileToServer } from '../components/enter_message/services/uploadService';

export type AppsDecisionAssets = Record<string, { type: 'image'; format: 'jpg'; data_base64: string }>;
export interface AppsAttachmentDescriptor {
  type: 'image' | 'audio'; name: string; mime_type: string; asset_ref?: string; input?: Record<string, unknown>;
}
export function appsImageDimensions(width: number, height: number) {
  const scale = Math.min(1, 1568 / width, 1568 / height);
  const imageWidth = Math.max(1, Math.round(width * scale));
  const imageHeight = Math.max(1, Math.round(height * scale));
  return { width: Math.max(280, imageWidth), height: Math.max(280, imageHeight), imageWidth, imageHeight };
}
async function imageAsset(file: File): Promise<string> {
  const url = URL.createObjectURL(file);
  try {
    const image = new Image(); image.src = url; await image.decode();
    if (!image.naturalWidth || !image.naturalHeight) throw new Error('invalid_image');
    const size = appsImageDimensions(image.naturalWidth, image.naturalHeight);
    const canvas = document.createElement('canvas'); canvas.width = size.width; canvas.height = size.height;
    const context = canvas.getContext('2d'); if (!context) throw new Error('image_processing_unavailable');
    context.fillStyle = '#ffffff'; context.fillRect(0, 0, size.width, size.height);
    context.drawImage(image, (size.width - size.imageWidth) / 2, (size.height - size.imageHeight) / 2, size.imageWidth, size.imageHeight);
    for (const quality of [0.88, 0.76, 0.6, 0.45, 0.25]) {
      const data = canvas.toDataURL('image/jpeg', quality).split(',')[1];
      if (data && Math.ceil(data.length * 3 / 4) <= 1024 * 1024) return data;
    }
    throw new Error('image_too_large');
  } finally { URL.revokeObjectURL(url); }
}
/** Uses the existing encrypted upload response for audio; keys are never model generated. */
export async function prepareAppsRequestAttachments(files: File[], options: { signal?: AbortSignal; chatId?: string; assertCurrent: () => void }): Promise<{ assets: AppsDecisionAssets; attachments: AppsAttachmentDescriptor[] }> {
  if (files.filter(file => file.type.startsWith('image/')).length > 4) throw new Error('too_many_images');
  const assets: AppsDecisionAssets = {}; const attachments: AppsAttachmentDescriptor[] = [];
  for (const file of files) {
    options.assertCurrent();
    if (file.type.startsWith('image/')) {
      const assetRef = crypto.randomUUID();
      assets[assetRef] = { type: 'image', format: 'jpg', data_base64: await imageAsset(file) };
      options.assertCurrent();
      attachments.push({ type: 'image', name: file.name, mime_type: file.type, asset_ref: assetRef });
    } else if (file.type.startsWith('audio/')) {
      const upload = await uploadFileToServer(file, options.signal); options.assertCurrent();
      const s3Key = upload.files.original?.s3_key ?? Object.values(upload.files)[0]?.s3_key;
      if (!s3Key) throw new Error('audio_upload_missing_key');
      attachments.push({ type: 'audio', name: file.name, mime_type: file.type,
        input: { id: crypto.randomUUID(), embed_id: upload.embed_id, s3_key: s3Key, s3_base_url: upload.s3_base_url,
          aes_key: upload.aes_key, aes_nonce: upload.aes_nonce, vault_wrapped_aes_key: upload.vault_wrapped_aes_key,
          filename: file.name, mime_type: file.type, ...(options.chatId ? { chat_id: options.chatId } : {}) } });
    } else throw new Error('unsupported_attachment');
  }
  return { assets, attachments };
}
