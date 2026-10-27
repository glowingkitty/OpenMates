/** Recognize a complete standalone SVG, independent of its code-fence language. */
export function svgImageSource(source: string): string | null {
  if (!source.trimStart().startsWith('<') || typeof DOMParser === 'undefined') return null;
  // Never resolve document entities. Ordinary SVG prologs/comments are supported.
  if (/<!ENTITY\s/i.test(source)) return null;
  const document = new DOMParser().parseFromString(source.trim(), 'image/svg+xml');
  const root = document.documentElement;
  if (document.querySelector('parsererror') || root.localName !== 'svg' ||
    (root.namespaceURI && root.namespaceURI !== 'http://www.w3.org/2000/svg')) return null;

  // SVG snippets often omit xmlns. It is required when loaded as an image file.
  if (!root.hasAttribute('xmlns')) root.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  // Serialize only the root, excluding document-level stylesheets and DTDs.
  // Always load as an <img>: SVG scripts and external resources cannot execute.
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(new XMLSerializer().serializeToString(root))}`;
}
