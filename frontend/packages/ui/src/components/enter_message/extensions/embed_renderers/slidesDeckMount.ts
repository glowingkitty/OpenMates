// slidesDeckMount.ts
//
// Mounts the slide deck preview card (SlidesDeckEmbedPreview) into an embed
// node-view wrapper. Extracted from GroupRenderer.ts, which is far over the
// file-size limit; GroupRenderer only keeps a one-line dispatch to this module.

import type { EmbedNodeAttributes } from "../../../../message_parsing/types";
import { mount, unmount, disposeEmbedTree } from "./mountedEmbedLifecycle";
import SlidesDeckEmbedPreview from "../../../embeds/slides/SlidesDeckEmbedPreview.svelte";

const mountedComponents = new WeakMap<HTMLElement, ReturnType<typeof mount>>();

/** Render a slide deck embed: first slide, title and slide count (kept current while streaming). */
export async function mountSlidesDeckPreview(
  item: EmbedNodeAttributes,
  decodedContent: Record<string, unknown> | null,
  content: HTMLElement,
  onFullscreen: () => void,
): Promise<void> {
  const slidesMarkup =
    typeof decodedContent?.slides_markup === "string" ? decodedContent.slides_markup : "";
  const title =
    (typeof decodedContent?.title === "string" ? decodedContent.title : "") || item.title;
  const slideCount =
    typeof decodedContent?.slide_count === "number" ? decodedContent.slide_count : 0;
  const status = item.status || (slidesMarkup ? "finished" : "processing");
  const embedId =
    item.contentRef?.replace("embed:", "")?.replace("preview:slides-deck:", "") ||
    item.id ||
    "";

  const existing = mountedComponents.get(content);
  if (existing) unmount(existing);
  disposeEmbedTree(content, false);
  content.innerHTML = "";

  const component = mount(SlidesDeckEmbedPreview, {
    target: content,
    props: {
      id: embedId,
      title,
      slideCount,
      slidesMarkup,
      status: status as "processing" | "finished" | "error",
      isMobile: false,
      onFullscreen,
    },
  });
  mountedComponents.set(content, component);
}
