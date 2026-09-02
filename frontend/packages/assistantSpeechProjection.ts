// assistantSpeechProjection.ts
// Shared deterministic projection for web and paired CLI speech requests.
// It removes URLs and raw structured syntax before transient text leaves the
// owner client, bounds every segment, and keeps canonical ordering identical
// across first-party clients.

export interface ProjectedAssistantSpeechSegment {
  sequence: number;
  kind: "code_summary" | "table_summary" | "embed_summary" | "prose_paragraph";
  speakableText: string;
}

export function projectAssistantSpeech(content: string): ProjectedAssistantSpeechSegment[] {
  return content
    .split(/\n\n+/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean)
    .flatMap(splitLongParagraph)
    .slice(0, 20)
    .map((paragraph, sequence) => ({ sequence, ...projectParagraph(paragraph) }))
    .filter((segment) => segment.speakableText.length > 0);
}

function splitLongParagraph(paragraph: string): string[] {
  const chunks: string[] = [];
  let remainder = paragraph;
  while (remainder.length > 2_000) {
    let boundary = remainder.lastIndexOf(" ", 2_000);
    if (boundary <= 0) boundary = 2_000;
    chunks.push(remainder.slice(0, boundary).trim());
    remainder = remainder.slice(boundary).trimStart();
  }
  if (remainder) chunks.push(remainder);
  return chunks;
}

function projectParagraph(markdown: string): Omit<ProjectedAssistantSpeechSegment, "sequence"> {
  const trimmed = markdown.trim();
  if (/^```[\s\S]*```$/.test(trimmed)) return { kind: "code_summary", speakableText: "A code example is available." };
  const lines = trimmed.split("\n").filter((line) => line.trim());
  if (lines.length >= 2 && lines.every((line) => /^\s*\|.*\|\s*$/.test(line))) {
    return { kind: "table_summary", speakableText: "A table is available." };
  }
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    return { kind: "embed_summary", speakableText: "Structured data is available." };
  }
  const speakableText = trimmed
    .replace(/```[\s\S]*?```/g, " A code example is available. ")
    .replace(/^\s*\|.*\|\s*$/gm, " A table is available. ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/`[^`]*`/g, "")
    .replace(/(?:https?|ftp):\/\/[^\s)\]>]+|[a-z][a-z0-9+.-]*:\/\/[^\s)\]>]+/gi, "")
    .replace(/(?:^|\s)[#>*_~]+|[_~]{1,3}/g, " ")
    .replace(/\s+/g, " ")
    .replace(/\s+([,.;:!?])/g, "$1")
    .replace(/^[\s,;:-]+|[\s,;:-]+$/g, "");
  return { kind: "prose_paragraph", speakableText };
}
