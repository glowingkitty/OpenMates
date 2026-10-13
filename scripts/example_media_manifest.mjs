// Reviewed, content-addressed public media for a converted real example chat.
// The publisher verifies source ownership. This helper independently binds its
// public-only manifest to embed IDs in the extracted source graph.

const PUBLIC_HOSTS = new Set([
  'openmates-public-examples.nbg1.your-objectstorage.com',
  'dev-openmates-public-examples.nbg1.your-objectstorage.com',
]);

const MIME_EXTENSIONS = {
  'image/png': 'png',
  'image/jpeg': 'jpg',
  'image/webp': 'webp',
  'audio/mpeg': 'mp3',
  'audio/wav': 'wav',
  'audio/ogg': 'ogg',
  'video/mp4': 'mp4',
  'video/webm': 'webm',
  'model/gltf-binary': 'glb',
};

const MEDIA_APPS = {
  application_preview: 'code',
  image: 'images',
  audio: 'audio',
  music: 'music',
  video: 'videos',
  models3d: 'models3d',
};

const URL_FIELDS = new Set([
  'latest_screenshot_url', 'previewImageUrl', 'fullImageUrl',
  'preview_image_url', 'thumbnail_url', 'previewAudioUrl',
  'previewVideoUrl', 'posterUrl', 'modelUrl', 'downloadUrl',
]);

function exactKeys(value, expected, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || Object.keys(value).some((key) => !expected.includes(key))) {
    throw new Error(`${label} contains unsupported fields.`);
  }
}

function validatedVariant(mediaType, item) {
  exactKeys(item, ['variant', 'public_url', 'sha256', 'mime_type'], 'Public media variant');
  const variant = String(item.variant || '');
  const digest = String(item.sha256 || '');
  const mimeType = String(item.mime_type || '');
  const extension = MIME_EXTENSIONS[mimeType];
  if (!/^[a-z][a-z0-9_]{0,31}$/.test(variant) || !/^[a-f0-9]{64}$/.test(digest) || !extension) {
    throw new Error('Public media variant metadata is invalid.');
  }
  const matchesMedia = mediaType === 'application_preview' ? variant === 'preview' && mimeType === 'image/png'
    : mediaType === 'image' ? mimeType.startsWith('image/')
      : mediaType === 'audio' || mediaType === 'music' ? variant === 'original' && mimeType.startsWith('audio/')
        : mediaType === 'video' ? (variant === 'original' && mimeType.startsWith('video/'))
          || (['thumbnail', 'poster'].includes(variant) && mimeType.startsWith('image/'))
          : mediaType === 'models3d' ? (['preview', 'master'].includes(variant) && mimeType === 'model/gltf-binary')
            || (variant === 'poster' && mimeType.startsWith('image/')) : false;
  if (!matchesMedia) throw new Error('Public media variant does not match its media type.');
  let url;
  try { url = new URL(item.public_url); } catch { throw new Error('Public media URL is invalid.'); }
  const expectedPath = `/reviewed-media/${mediaType}/${variant}/sha256-${digest}.${extension}`;
  if (url.protocol !== 'https:' || url.username || url.password || url.port || url.search || url.hash
    || !PUBLIC_HOSTS.has(url.hostname) || url.pathname !== expectedPath || url.toString() !== item.public_url) {
    throw new Error('Public media fixtures must use immutable public example S3 URLs.');
  }
  return { variant, public_url: url.toString(), sha256: digest, mime_type: mimeType };
}

function publicFields(mediaType, variants) {
  const byName = Object.fromEntries(variants.map((entry) => [entry.variant, entry.public_url]));
  if (mediaType === 'application_preview') {
    if (!byName.preview) throw new Error('Application example needs a reviewed screenshot.');
    return { latest_screenshot_url: byName.preview };
  }
  if (mediaType === 'image') {
    const preview = byName.preview || byName.full || byName.original;
    if (!preview) throw new Error('Image example needs a public image.');
    return { previewImageUrl: preview, fullImageUrl: byName.full || byName.original || preview };
  }
  if (mediaType === 'audio' || mediaType === 'music') {
    if (!byName.original) throw new Error('Audio example needs a reviewed original.');
    return { previewAudioUrl: byName.original };
  }
  if (mediaType === 'video') {
    if (!byName.original) throw new Error('Video example needs a reviewed original.');
    return {
      previewVideoUrl: byName.original,
      ...(byName.thumbnail || byName.poster ? { previewImageUrl: byName.thumbnail || byName.poster } : {}),
    };
  }
  if (mediaType === 'models3d') {
    const model = byName.preview || byName.master;
    if (!model) throw new Error('3D example needs a reviewed GLB.');
    return {
      ...(byName.poster ? { posterUrl: byName.poster } : {}),
      modelUrl: byName.master || model,
      downloadUrl: byName.master || model,
    };
  }
  throw new Error('Unsupported public media type.');
}

function embedAppId(embed) {
  const content = String(embed.content || '');
  try {
    const parsed = JSON.parse(content);
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return typeof parsed.app_id === 'string' ? parsed.app_id : null;
    }
  } catch { /* TOON content follows. */ }
  return content.match(/^app_id:\s*([a-z0-9_]+)\s*$/m)?.[1] || null;
}

function addPublicFields(content, fields) {
  let parsed;
  try { parsed = JSON.parse(String(content || '')); } catch { /* TOON content follows. */ }
  if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
    const privateKeys = new Set([
      'vault_key_id', 'vault_wrapped_aes_key', 'aes_key', 'aes_nonce',
      's3_base_url', 's3_key', 'screenshot_s3_keys', 'files', 'screenshots', 'latest_screenshot',
    ]);
    function hasPrivateMetadata(value) {
      if (!value || typeof value !== 'object') return false;
      return Object.entries(value).some(([key, nested]) => privateKeys.has(key) || hasPrivateMetadata(nested));
    }
    if (hasPrivateMetadata(parsed)) {
      throw new Error('Private media metadata must be removed before public media is attached.');
    }
    const publicContent = { ...parsed };
    for (const field of URL_FIELDS) delete publicContent[field];
    return JSON.stringify({ ...publicContent, ...fields });
  }
  if (/\b(?:vault_key_id|vault_wrapped_aes_key|aes_key|aes_nonce|s3_base_url|s3_key|screenshot_s3_keys)\b/.test(String(content || ''))
    || /^(?:files|screenshots|latest_screenshot)(?:\[|:)\s*/m.test(String(content || ''))) {
    throw new Error('Private media metadata must be removed before public media is attached.');
  }
  const clean = String(content || '').split('\n').filter((line) => {
    const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*):\s*/);
    return !match || !URL_FIELDS.has(match[1]);
  }).join('\n').trimEnd();
  return `${clean}\n${Object.entries(fields).map(([key, value]) => `${key}: ${JSON.stringify(value)}`).join('\n')}`;
}

export function attachReviewedPublicMedia(chat, manifest) {
  exactKeys(manifest, ['reviewed', 'source_chat_id', 'embeds'], 'Public media manifest');
  if (manifest.reviewed !== true || manifest.source_chat_id !== chat?.chat_id
    || !Array.isArray(manifest.embeds) || manifest.embeds.length === 0) {
    throw new Error('Public media manifest must be reviewed and match the extracted source chat.');
  }
  const mediaByEmbedId = new Map();
  for (const entry of manifest.embeds) {
    exactKeys(entry, ['embed_id', 'media_type', 'variants'], 'Public media embed');
    const embedId = String(entry.embed_id || '');
    const mediaType = String(entry.media_type || '');
    if (!embedId || !MEDIA_APPS[mediaType] || mediaByEmbedId.has(embedId)
      || !Array.isArray(entry.variants) || entry.variants.length === 0) {
      throw new Error('Public media manifest has an invalid or repeated embed.');
    }
    const variants = entry.variants.map((variant) => validatedVariant(mediaType, variant));
    if (new Set(variants.map((variant) => variant.variant)).size !== variants.length) {
      throw new Error('Public media manifest repeats a variant.');
    }
    mediaByEmbedId.set(embedId, { appId: MEDIA_APPS[mediaType], fields: publicFields(mediaType, variants) });
  }

  const seen = new Set();
  function attachInChat(source) {
    return {
      ...source,
      embeds: (source.embeds || []).map((embed) => {
        const selected = mediaByEmbedId.get(embed.embed_id);
        if (!selected) return embed;
        if (seen.has(embed.embed_id) || embedAppId(embed) !== selected.appId) {
          throw new Error('Public media embed does not match the extracted source graph.');
        }
        seen.add(embed.embed_id);
        return { ...embed, content: addPublicFields(embed.content, selected.fields) };
      }),
      ...(Array.isArray(source.sub_chats)
        ? { sub_chats: source.sub_chats.map((child) => attachInChat(child)) }
        : {}),
    };
  }
  const updated = attachInChat(chat);
  if (seen.size !== mediaByEmbedId.size) {
    throw new Error('Public media manifest references an embed outside the extracted source graph.');
  }
  return updated;
}
