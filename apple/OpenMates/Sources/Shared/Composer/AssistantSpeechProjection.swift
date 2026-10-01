import Foundation
import JavaScriptCore

// Canonical deterministic projection: frontend/packages/assistantSpeechProjection.ts.
// Regenerate the embedded script from that source when its contract changes.
// JavaScriptCore runs locally; no network, DOM, files or provider credentials.
// Specification: specifications/features/assistant-response-speech/specification.yml
// Assertions: assistant-speech.surface.semantic-parity
@MainActor
enum AssistantSpeechProjection {
    struct Part {
        let sequence: Int
        let kind: String
        let text: String
        let chapter: String
        var wire: [String: Any] {
            ["sequence": sequence, "kind": kind, "speakable_text": text,
             "source_version": 1, "source_hash": "server-verified"]
        }
    }
    private static let context: JSContext? = {
        let value = JSContext()
        value?.evaluateScript(script)
        return value
    }()
    static func project(_ markdown: String, language: String = "en") -> [Part] {
        guard let rows = context?.objectForKeyedSubscript("projectAssistantSpeech")?.call(withArguments: [markdown, language])?.toArray() as? [[String: Any]] else { return [] }
        return rows.compactMap { row in
            guard let sequence = row["sequence"] as? Int, let kind = row["kind"] as? String,
                  let text = row["speakableText"] as? String, let chapter = row["chapter"] as? [String: Any] else { return nil }
            let label: String
            if let heading = chapter["text"] as? String { label = heading }
            else if let type = chapter["type"] as? String { label = LocalizationManager.shared.text("chat.assistant_speech.\(type)") }
            else { label = LocalizationManager.shared.text("chat.assistant_speech.part").replacingOccurrences(of: "{number}", with: String(sequence + 1)) }
            return Part(sequence: sequence, kind: kind, text: text, chapter: label)
        }
    }
    private static let script = #"""
// assistantSpeechProjection.ts
// Shared deterministic projection for web and paired CLI speech requests.
// It removes URLs and raw structured syntax before transient text leaves the
// owner client, bounds every segment, and keeps canonical ordering identical
// across first-party clients.

                                                  
                   
                                                                               
                        
                                                                                                                                              
 

const MAX_SPEECH_SEGMENTS = 20;
const MAX_SEGMENT_CHARACTERS = 2_000;
const FENCED_BLOCK = /^```[\s\S]*```$/;

function projectAssistantSpeech(content        , language = "en")                                    {
  let nearestHeading = "";
  // Keep fences atomic, including blank lines and large payloads. Splitting before
  // projection can expose pieces of internal JSON as ordinary speakable prose.
  const paragraphs = content.split(/(```[\s\S]*?```)/g).flatMap((block) =>
    FENCED_BLOCK.test(block.trim()) ? [block] : block.split(/\n\n+/),
  );
  const segments                                    = [];
  const semanticSummaries = new Set        ();
  for (const paragraph of paragraphs.map((block) => block.trim()).filter(Boolean)) {
    if (!FENCED_BLOCK.test(paragraph)) {
      const heading = paragraph.split("\n").map((line) => line.match(/^#{1,6}\s+(.+?)\s*#*$/)?.[1]?.trim()).find(Boolean);
      if (heading) nearestHeading = heading;
    }
    const projected = projectParagraph(paragraph, language);
    for (const speakableText of splitLongParagraph(projected.speakableText)) {
      const semanticIdentity = `${projected.kind}:${speakableText}`;
      if (projected.kind === "embed_summary") {
        if (semanticSummaries.has(semanticIdentity)) continue;
        semanticSummaries.add(semanticIdentity);
      }
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
  kind                                         ,
  heading        ,
  sequence        ,
)                                             {
  if (kind === "code_summary") return { kind: "semantic", type: "code" };
  if (kind === "table_summary") return { kind: "semantic", type: "table" };
  if (kind === "embed_summary") return { kind: "semantic", type: "structured" };
  if (heading) return { kind: "heading", text: heading };
  return { kind: "part", number: sequence + 1 };
}

function splitLongParagraph(paragraph        )           {
  const chunks           = [];
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

function fallback(text        , language        )         {
  if (!language.toLowerCase().startsWith("de")) return text;
  const german                         = {
    "Search results are available.": "Suchergebnisse sind verfügbar.",
    "I used the News Search skill.": "Ich habe die News-Suche verwendet.",
    "App results are available.": "App-Ergebnisse sind verfügbar.",
    "Structured data is available.": "Strukturierte Daten sind verfügbar.",
    "A code example is available.": "Ein Codebeispiel ist verfügbar.",
    "A table is available.": "Eine Tabelle ist verfügbar.",
  };
  return german[text] ?? text;
}

function projectFence(markdown        , language        )                                                                {
  // Search results are serialized in fences too; fences alone do not mean code.
  const body = markdown.replace(/^```[^\n]*\n|\n?```$/g, "").trim();
  let payload                                 = null;
  try {
    const parsed          = JSON.parse(body);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) payload = parsed                           ;
  } catch {
    // Ordinary code is not JSON; only recognized embed metadata changes its type.
  }
  if (payload?.type === "app_skill_use") {
    return { kind: "embed_summary", speakableText: fallback(payload.skill_id === "search" ? (payload.app_id === "news" ? "I used the News Search skill." : "Search results are available.") : "App results are available.", language) };
  }
  if (payload && (payload.embed_id || ["website", "image", "audio", "video"].includes(String(payload.type)))) {
    return { kind: "embed_summary", speakableText: fallback("Structured data is available.", language) };
  }
  return { kind: "code_summary", speakableText: fallback("A code example is available.", language) };
}

function projectParagraph(markdown        , language        )                                                                {
  const trimmed = markdown.trim();
  if (/^```[\s\S]*```$/.test(trimmed)) return projectFence(trimmed, language);
  const lines = trimmed.split("\n").filter((line) => line.trim());
  if (lines.length >= 2 && lines.every((line) => /^\s*\|.*\|\s*$/.test(line))) {
    return { kind: "table_summary", speakableText: fallback("A table is available.", language) };
  }
  if (trimmed.startsWith("{") || (trimmed.startsWith("[") && !/^\[[^\]]+\]\([^)]*\)/.test(trimmed))) {
    return { kind: "embed_summary", speakableText: fallback("Structured data is available.", language) };
  }
  const speakableText = trimmed
    .replace(/```[\s\S]*?```/g, (fence) => ` ${projectFence(fence, language).speakableText} `)
    .replace(/^\s*\|.*\|\s*$/gm, ` ${fallback("A table is available.", language)} `)
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/`[^`]*`/g, "")
    .replace(/(?:https?|ftp):\/\/[^\s)\]>]+|[a-z][a-z0-9+.-]*:\/\/[^\s)\]>]+/gi, "")
    .replace(/(?:^|\s)[#>*_~]+|[_~]{1,3}/g, " ")
    .replace(/\s+/g, " ")
    .replace(/\s+([,.;:!?])/g, "$1")
    .replace(/^[\s,;:-]+|[\s,;:-]+$/g, "");
  return { kind: "prose_paragraph", speakableText };
}

"""#
}
