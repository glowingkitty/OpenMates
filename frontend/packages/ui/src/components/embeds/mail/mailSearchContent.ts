/*
 * Purpose: Mail-search content sanitization helpers for preview/fullscreen embeds.
 * Sanitizes untrusted HTML email content with DOMPurify and rewrites external
 * image URLs through OpenMates proxyImage() to prevent direct third-party fetches.
 *
 * Architecture: docs/architecture/embeds.md
 * Tests: exercised by mail search embed rendering paths.
 */

import DOMPurify, { type Config as DOMPurifyConfig } from "dompurify";
import { proxyImage } from "../../../utils/imageProxy";

const MAIL_HTML_SANITIZE_CONFIG: DOMPurifyConfig = {
  ALLOWED_TAGS: [
    "a",
    "abbr",
    "b",
    "blockquote",
    "br",
    "code",
    "div",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "span",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
  ],
  ALLOWED_ATTR: [
    "href",
    "src",
    "alt",
    "title",
    "target",
    "rel",
    "class",
    "style",
  ],
  FORBID_TAGS: [
    "script",
    "iframe",
    "object",
    "embed",
    "form",
    "input",
    "button",
    "style",
  ],
  FORBID_ATTR: [
    "onerror",
    "onload",
    "onclick",
    "onmouseover",
    "onfocus",
    "onblur",
  ],
  KEEP_CONTENT: true,
  RETURN_TRUSTED_TYPE: false,
};

function rewriteHtmlImagesToProxy(safeHtml: string): string {
  const parser = new DOMParser();
  const doc = parser.parseFromString(safeHtml, "text/html");

  const imageNodes = Array.from(doc.querySelectorAll("img"));
  for (const imageNode of imageNodes) {
    const rawSrc = imageNode.getAttribute("src") || "";
    if (!rawSrc || rawSrc.startsWith("data:") || rawSrc.startsWith("blob:")) {
      continue;
    }
    imageNode.setAttribute("src", proxyImage(rawSrc));

    // Remove srcset to avoid bypassing proxy via alternate image URLs.
    if (imageNode.hasAttribute("srcset")) {
      imageNode.removeAttribute("srcset");
    }
  }

  const anchorNodes = Array.from(doc.querySelectorAll("a"));
  for (const anchorNode of anchorNodes) {
    anchorNode.setAttribute("target", "_blank");
    anchorNode.setAttribute("rel", "noopener noreferrer nofollow");
  }

  return doc.body.innerHTML;
}

export function sanitizeMailHtmlForRender(rawHtml: string): string {
  if (!rawHtml || !rawHtml.trim()) {
    return "";
  }

  const sanitized = DOMPurify.sanitize(
    rawHtml,
    MAIL_HTML_SANITIZE_CONFIG,
  ) as string;
  return rewriteHtmlImagesToProxy(sanitized);
}

export function buildMailBodyPreviewText(
  bodyText: string,
  bodyHtml: string,
): string {
  const source = (bodyText || "").trim();
  if (source) {
    return source;
  }

  // Convert sanitized HTML into plain text fallback for preview snippets.
  const safeHtml = sanitizeMailHtmlForRender(bodyHtml);
  if (!safeHtml) {
    return "";
  }

  const parser = new DOMParser();
  const doc = parser.parseFromString(safeHtml, "text/html");
  return (doc.body.textContent || "").trim();
}
