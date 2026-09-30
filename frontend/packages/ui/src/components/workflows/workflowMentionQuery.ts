/** An unfinished @ mention is ordinary authored text until a variable is selected. */
export function workflowMentionQuery(textBeforeCursor: string): { text: string; query: string; length: number } | null {
  const match = textBeforeCursor.match(/(?:^|[\s(])(@[^\s@{}\ufffc]{0,120})$/u);
  return match ? { text: match[1], query: match[1].slice(1), length: match[1].length } : null;
}

/** Match a fully qualified address by path, with word search for shorter queries. */
export function matchesWorkflowVariableQuery(label: string, query: string, canonicalName?: string | null): boolean {
  const words = (value: string) => value.toLocaleLowerCase().split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  const queryPath = query.toLocaleLowerCase().split('.');
  if (canonicalName && queryPath.length >= 3 && queryPath.every(Boolean)) {
    const canonicalPath = canonicalName.toLocaleLowerCase().split('.');
    return queryPath.length <= canonicalPath.length && queryPath.every((part, index) => canonicalPath[index]?.startsWith(part));
  }
  const candidates = words(label);
  return words(query).every(word => candidates.some(candidate => candidate.startsWith(word)) || (canonicalName ? words(canonicalName).some(candidate => candidate.startsWith(word)) : false));
}
