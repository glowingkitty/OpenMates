// assistantSpeechProjection.ts
// Shared deterministic projection for web and paired CLI speech requests.
// It removes URLs and raw structured syntax before transient text leaves the
// owner client, bounds every segment, and keeps canonical ordering identical
// across first-party clients.

export interface ProjectedAssistantSpeechSegment {
  sequence: number;
  kind: "code_summary" | "table_summary" | "embed_summary" | "prose_paragraph";
  speakableText: string;
  chapter: { kind: "heading"; text: string } | { kind: "part"; number: number } | { kind: "semantic"; type: "code" | "table" | "structured" };
}

const MAX_SPEECH_SEGMENTS = 20;
const MAX_SEGMENT_CHARACTERS = 2_000;
const FENCED_BLOCK = /^```[\s\S]*```$/;

export function projectAssistantSpeech(content: string): ProjectedAssistantSpeechSegment[] {
  let nearestHeading = "";
  // Keep fences atomic, including blank lines and large payloads. Splitting before
  // projection can expose pieces of internal JSON as ordinary speakable prose.
  const paragraphs = content.split(/(```[\s\S]*?```)/g).flatMap((block) =>
    FENCED_BLOCK.test(block.trim()) ? [block] : block.split(/\n\n+/),
  );
  const segments: ProjectedAssistantSpeechSegment[] = [];
  for (const paragraph of paragraphs.map((block) => block.trim()).filter(Boolean)) {
    if (!FENCED_BLOCK.test(paragraph)) {
      const heading = paragraph.split("\n").map((line) => line.match(/^#{1,6}\s+(.+?)\s*#*$/)?.[1]?.trim()).find(Boolean);
      if (heading) nearestHeading = heading;
    }
    const projected = projectParagraph(paragraph);
    for (const speakableText of splitLongParagraph(projected.speakableText)) {
      if (segments.length === MAX_SPEECH_SEGMENTS) return segments;
      const sequence = segments.length;
      segments.push({
        sequence, kind: projected.kind, speakableText,
        chapter: chapterFor(projected.kind, nearestHeading, sequence),
      });
    }
  }
  return segments;
}

function chapterFor(
  kind: ProjectedAssistantSpeechSegment["kind"],
  heading: string,
  sequence: number,
): ProjectedAssistantSpeechSegment["chapter"] {
  if (kind === "code_summary") return { kind: "semantic", type: "code" };
  if (kind === "table_summary") return { kind: "semantic", type: "table" };
  if (kind === "embed_summary") return { kind: "semantic", type: "structured" };
  if (heading) return { kind: "heading", text: heading };
  return { kind: "part", number: sequence + 1 };
}

function splitLongParagraph(paragraph: string): string[] {
  const chunks: string[] = [];
  let remainder = paragraph;
  while (remainder.length > MAX_SEGMENT_CHARACTERS) {
    let boundary = remainder.lastIndexOf(" ", MAX_SEGMENT_CHARACTERS);
    if (boundary <= 0) boundary = MAX_SEGMENT_CHARACTERS;
    chunks.push(remainder.slice(0, boundary).trim());
    remainder = remainder.slice(boundary).trimStart();
  }
  if (remainder) chunks.push(remainder);
  return chunks;
}

function projectFence(markdown: string): Omit<ProjectedAssistantSpeechSegment, "sequence" | "chapter"> {
  // Search results are serialized in fences too; fences alone do not mean code.
  const body = markdown.replace(/^```[^\n]*\n|\n?```$/g, "").trim();
  let payload: Record<string, unknown> | null = null;
  try {
    const parsed: unknown = JSON.parse(body);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) payload = parsed as Record<string, unknown>;
  } catch {
    // Ordinary code is not JSON; only recognized embed metadata changes its type.
  }
  if (payload?.type === "app_skill_use") {
    return { kind: "embed_summary", speakableText: payload.skill_id === "search" ? "Search results are available." : "App results are available." };
  }
  if (payload && (payload.embed_id || ["website", "image", "audio", "video"].includes(String(payload.type)))) {
    return { kind: "embed_summary", speakableText: "Structured data is available." };
  }
  return { kind: "code_summary", speakableText: "A code example is available." };
}

function projectParagraph(markdown: string): Omit<ProjectedAssistantSpeechSegment, "sequence" | "chapter"> {
  const trimmed = markdown.trim();
  if (/^```[\s\S]*```$/.test(trimmed)) return projectFence(trimmed);
  const lines = trimmed.split("\n").filter((line) => line.trim());
  if (lines.length >= 2 && lines.every((line) => /^\s*\|.*\|\s*$/.test(line))) {
    return { kind: "table_summary", speakableText: "A table is available." };
  }
  if (trimmed.startsWith("{") || (trimmed.startsWith("[") && !/^\[[^\]]+\]\([^)]*\)/.test(trimmed))) {
    return { kind: "embed_summary", speakableText: "Structured data is available." };
  }
  const speakableText = trimmed
    .replace(/```[\s\S]*?```/g, (fence) => ` ${projectFence(fence).speakableText} `)
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
