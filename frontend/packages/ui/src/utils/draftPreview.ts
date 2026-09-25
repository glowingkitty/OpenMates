/** Turn serialized embed references in saved draft previews into readable labels. */
const EMBED_LABELS: Record<string, string> = {
  image: "Image",
  audio: "Audio",
  "audio-recording": "Audio",
  recording: "Recording",
  website: "Website",
  "web-website": "Website",
  video: "Video",
  "videos-video": "Video",
  location: "Location",
  maps: "Location",
  pdf: "PDF",
  file: "File",
  book: "Book",
  code: "Code",
  "code-code": "Code",
  "code-code-group": "Code",
};

export function draftEmbedLabel(type: string): string {
  const label = EMBED_LABELS[type] ?? type.replace(/[-_]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
  return `[${label}]`;
}

function labelForReference(content: string): string {
  // Older encrypted previews were truncated after 100 characters, often before
  // the closing brace or fence. Read only the type; never require valid JSON.
  const type = content.match(/"type"\s*:\s*"([a-zA-Z0-9_-]+)"/)?.[1];
  if (!type) return /"embed_id"\s*:/.test(content) ? "[Embed]" : "[Code]";
  if (!EMBED_LABELS[type] && !/"embed_id"\s*:/.test(content)) return "[Code]";
  return draftEmbedLabel(type);
}

export function formatDraftPreview(value: string | null | undefined): string {
  if (!value) return "";

  const withoutMarkers = value.replace(/<<<TEST_LIVE_MOCK:[^>]+>>>/g, " ");
  const withLabels = withoutMarkers.replace(/```(?:json|json_embed)\s*([\s\S]*?)(?:```|$)/g, (_block, content: string) => {
    return ` ${labelForReference(content)} `;
  });

  // Some older clients saved the reference object without a Markdown fence.
  const trimmed = withLabels.trim();
  if (trimmed.startsWith("{") && /"embed_id"\s*:/.test(trimmed) && /"type"\s*:/.test(trimmed)) {
    return labelForReference(trimmed);
  }

  return withLabels.replace(/\s+/g, " ").trim();
}
