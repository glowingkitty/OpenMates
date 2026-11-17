/**
 * Renderer for `helplines` embeds (wellbeing layer helpline card).
 *
 * The server creates the embed with the payload documented in
 * docs/plans/safety-decisions-build/wellbeing-contract.md. This renderer decodes it
 * and mounts HelplineCard.svelte inline; the card has no fullscreen view.
 * Native counterpart: apple HelplineCardView.swift.
 */

import type { EmbedRenderer, EmbedRenderContext } from "./types";
import type { EmbedNodeAttributes } from "../../../../message_parsing/types";
import { mount, unmount, disposeEmbedTree } from "./mountedEmbedLifecycle";
import HelplineCard from "../../../embeds/wellbeing/HelplineCard.svelte";
import type { HelplineLine } from "../../../../types/helplines";
import { resolveEmbed, decodeToonContent } from "../../../../services/embedResolver";

const mountedComponents = new WeakMap<HTMLElement, ReturnType<typeof mount>>();

const asText = (value: unknown): string | null =>
  typeof value === "string" && value.trim() !== "" ? value : null;

/** Normalize one payload line; lines without a name are dropped. */
export function parseHelplineLine(raw: unknown): HelplineLine | null {
  if (!raw || typeof raw !== "object") return null;
  const record = raw as Record<string, unknown>;
  const name = asText(record.name);
  if (!name) return null;
  return {
    name,
    phone: asText(record.phone),
    sms: asText(record.sms),
    chat_url: asText(record.chat_url),
    hours: asText(record.hours),
    topics: Array.isArray(record.topics) ? record.topics.filter((t): t is string => typeof t === "string") : [],
  };
}

export class HelplinesRenderer implements EmbedRenderer {
  type = "helplines";

  async render(context: EmbedRenderContext): Promise<void> {
    const { attrs, content } = context;

    let fields: Record<string, unknown> | null = context.decodedContent ?? null;
    if (!fields && attrs.id) {
      const embed = (await resolveEmbed(attrs.id)) as { content?: unknown } | null;
      if (embed?.content) {
        fields = (await decodeToonContent(embed.content as string)) as Record<string, unknown> | null;
      }
    }

    const existing = mountedComponents.get(content);
    if (existing) unmount(existing);
    disposeEmbedTree(content, false);
    content.innerHTML = "";

    const emergencyNumber = asText(fields?.emergency_number);
    const directoryUrl = asText(fields?.directory_url);
    if (!fields || !emergencyNumber || !directoryUrl) {
      console.warn("[HelplinesRenderer] Helplines payload missing or incomplete; nothing to render", attrs.id);
      return;
    }

    const rawLines = Array.isArray(fields.lines) ? fields.lines : [];
    const container = content.parentElement || content;
    container.setAttribute("data-embed-type", "helplines");

    const component = mount(HelplineCard, {
      target: content,
      props: {
        lines: rawLines.map(parseHelplineLine).filter((l): l is HelplineLine => l !== null),
        emergency_number: emergencyNumber,
        directory_url: directoryUrl,
        country: asText(fields.country) ?? "",
        language: asText(fields.language) ?? "",
        source: fields.source === "throughline" ? "throughline" : "emergency_only",
      },
    });
    mountedComponents.set(content, component);
  }

  toMarkdown(attrs: EmbedNodeAttributes): string {
    void attrs;
    return "";
  }

  update(context: EmbedRenderContext): boolean {
    this.render(context).catch((err) => {
      console.error("[HelplinesRenderer] Error in update re-render:", err);
    });
    return true;
  }
}
