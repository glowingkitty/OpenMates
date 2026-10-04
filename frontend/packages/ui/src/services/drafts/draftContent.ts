/** Inspect the editor document rather than its plain text: embeds have no text. */
export function inspectDraftContent(value: unknown): {
  hasMeaningfulContent: boolean;
  hasPendingEmbed: boolean;
  embedCount: number;
  embedIds: Set<string>;
} {
  const embedIds = new Set<string>();
  let hasMeaningfulContent = false;
  let hasPendingEmbed = false;
  let embedCount = 0;

  const visit = (value: unknown): void => {
    if (!value || typeof value !== 'object') return;
    const node = value as Record<string, unknown>;
    const attrs = node.attrs && typeof node.attrs === 'object'
      ? node.attrs as Record<string, unknown> : {};
    if (node.type === 'text' && typeof node.text === 'string' && node.text.trim()) {
      hasMeaningfulContent = true;
    }
    if ((node.type === 'inlineMath' || node.type === 'blockMath') &&
      typeof attrs.latex === 'string' && attrs.latex.trim()) {
      hasMeaningfulContent = true;
    }
    if (node.type === 'horizontalRule') hasMeaningfulContent = true;
    if (node.type === 'embed') {
      hasMeaningfulContent = true;
      embedCount += 1;
      const id = attrs.id ?? attrs.embedId ?? attrs.contentRef;
      if (typeof id === 'string' && id) embedIds.add(id.replace(/^embed:/, ''));
      const status = attrs.status;
      if (status === 'uploading' || status === 'processing' || status === 'transcribing' || status === 'correcting' || !attrs.contentRef) {
        hasPendingEmbed = true;
      }
    }
    if (typeof node.type === 'string' && (node.type === 'mate' || /mention/i.test(node.type))) {
      hasMeaningfulContent = true;
    }
    if (Array.isArray(node.content)) node.content.forEach(visit);
  };
  visit(value);
  return { hasMeaningfulContent, hasPendingEmbed, embedCount, embedIds };
}

export function incomingDraftOmitsLocalEmbed(local: unknown, incoming: unknown): boolean {
  const localState = inspectDraftContent(local);
  if (localState.embedCount === 0) return false;
  const incomingState = inspectDraftContent(incoming);
  if (localState.hasPendingEmbed && incomingState.embedCount < localState.embedCount) return true;
  for (const id of localState.embedIds) if (!incomingState.embedIds.has(id)) return true;
  return false;
}
