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

export function projectAssistantSpeech(content: string): ProjectedAssistantSpeechSegment[] {
  let nearestHeading = "";
  return content
    .split(/\n\n+/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean)
    .flatMap((paragraph) => {
      const heading = paragraph.split("\n").map((line) => line.match(/^#{1,6}\s+(.+?)\s*#*$/)?.[1]?.trim()).find(Boolean);
      if (heading) nearestHeading = heading;
      return splitLongParagraph(paragraph).map((chunk) => ({ chunk, heading: nearestHeading }));
    })
    .slice(0, 20)
    .map(({ chunk, heading }, sequence) => {
      const projected = projectParagraph(chunk);
      return {
        sequence,
        ...projected,
        chapter: chapterFor(projected.kind, heading, sequence),
      };
    })
    .filter((segment) => segment.speakableText.length > 0);
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
  while (remainder.length > 2_000) {
    let boundary = remainder.lastIndexOf(" ", 2_000);
    if (boundary <= 0) boundary = 2_000;
    chunks.push(remainder.slice(0, boundary).trim());
    remainder = remainder.slice(boundary).trimStart();
  }
  if (remainder) chunks.push(remainder);
  return chunks;
}

function projectParagraph(markdown: string): Omit<ProjectedAssistantSpeechSegment, "sequence" | "chapter"> {
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
