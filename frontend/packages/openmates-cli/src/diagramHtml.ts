/** Conservative recognition for reopening exported source-first HTML diagrams. */
export interface DiagramHtmlInfo {
  title: string;
  diagramKind: string;
  renderWidth: number;
  renderHeight: number;
}

export function inspectDiagramHtml(source: string): DiagramHtmlInfo | null {
  if (!source || Buffer.byteLength(source, "utf8") > 1024 * 1024) return null;
  if (!/^\s*<!doctype html\s*>/i.test(source)
    || !/<html\b[^>]*>[\s\S]*<head\b[^>]*>[\s\S]*<\/head\s*>[\s\S]*<body\b[^>]*>[\s\S]*<svg\b/i.test(source)
    || !/<\/svg\s*>[\s\S]*<\/body\s*>[\s\S]*<\/html\s*>\s*$/i.test(source)
    || !/<g\b[^>]*\bdata-om-component\s*=\s*["'][a-z][a-z0-9_-]{0,63}["']/i.test(source)) return null;
  // HTML parser ambiguities and active/external resources stay ordinary code.
  let checked = source.replace(/\sxmlns(?::[\w-]+)?\s*=\s*["']http:\/\/www\.w3\.org\/[A-Za-z0-9/.-]+["']/gi, "");
  checked = checked.replace(/<!--[\s\S]*?-->/g, "").replace(/&amp;/gi, "&");
  checked = checked.replace(/data:font\/woff2;base64,([A-Za-z0-9+/]+={0,2})/gi, (whole, encoded: string) => {
    const bytes = Buffer.from(encoded, "base64");
    return bytes.length > 0 && bytes.length <= 256 * 1024 && bytes.subarray(0, 4).toString() === "wOF2"
      && /@font-face\s*\{[^}]*$/i.test(checked.slice(0, checked.indexOf(whole)))
      ? "#embedded-font" : "unsafe-font-data";
  });
  if (/<!--|-->|<![^d]|<\?|&#|&[a-z][a-z0-9]+;/i.test(checked)
    || /<\s*\/?\s*(?:script|iframe|frame|object|embed|applet|link|base|img|image|video|audio|source|track|form|input|textarea|select|button|template|portal|foreignobject|animate|set|discard|feimage|math|noscript)\b/i.test(source)
    || /\s(?:on[a-z]+|srcdoc|src|srcset|poster|data|action|formaction|background|http-equiv)\s*=/i.test(source)
    || /(?:https?:|file:|javascript:|data:|\/\/|unsafe-font-data)/i.test(checked)
    || /@\s*(?:import|namespace|document)|expression\s*\(|image-set\s*\(|behavior\s*:|-moz-binding\s*:|\\/i.test(checked)) return null;
  for (const match of checked.matchAll(/url\(\s*(['"]?)([^)"']+)\1\s*\)/gi)) {
    if (!/^#[a-z_][\w.:-]{0,119}$/i.test(match[2].trim())) return null;
  }
  if (/url\s*\(/i.test(checked.replace(/url\(\s*(['"]?)([^)"']+)\1\s*\)/gi, ""))) return null;
  const title = /<title\b[^>]*>([^<>]{1,160})<\/title\s*>/i.exec(source)?.[1]?.trim();
  const viewBox = /<svg\b[^>]*\bviewBox\s*=\s*["']([^"']+)["']/i.exec(source)?.[1];
  if (!title || !viewBox) return null;
  const parts = viewBox.trim().split(/[\s,]+/).map(Number);
  if (parts.length !== 4 || parts.some((n) => !Number.isFinite(n))
    || parts[2] < 1 || parts[2] > 8192 || parts[3] < 1 || parts[3] > 8192) return null;
  const kind = /<svg\b[^>]*\bdata-diagram-kind\s*=\s*["']([a-z][a-z0-9_-]{0,63})["']/i.exec(source)?.[1]
    ?? /<svg\b[^>]*\bdata-om-diagram\s*=\s*["']([a-z][a-z0-9_-]{0,63})["']/i.exec(source)?.[1]
    ?? /<meta\b[^>]*\bname\s*=\s*["']diagram-kind["'][^>]*\bcontent\s*=\s*["']([a-z][a-z0-9_-]{0,63})["']/i.exec(source)?.[1]
    ?? "diagram";
  const renderWidth = Number(/<html\b[^>]*\bdata-om-render-width\s*=\s*["']([0-9]{1,4})["']/i.exec(source)?.[1] ?? parts[2]);
  const renderHeight = Number(/<html\b[^>]*\bdata-om-render-height\s*=\s*["']([0-9]{1,4})["']/i.exec(source)?.[1] ?? parts[3]);
  if (!(renderWidth >= 1 && renderWidth <= 8192 && renderHeight >= 1 && renderHeight <= 8192)) return null;
  return { title, diagramKind: kind, renderWidth: Math.round(renderWidth), renderHeight: Math.round(renderHeight) };
}
