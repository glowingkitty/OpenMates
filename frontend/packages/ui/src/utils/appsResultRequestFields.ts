/** Presentation fields from the direct caller's flat or requests-array input. */
export function appsResultRequestFields(input: unknown): Record<string, unknown> {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return {};
  const record = input as Record<string, unknown>;
  const first = Array.isArray(record.requests) ? record.requests[0] : null;
  return { ...(first && typeof first === 'object' && !Array.isArray(first) ? first : {}), ...record };
}

/** Older encrypted parents keep request fields only inside `input`. */
export function appsResultPresentationContent(content: Record<string, unknown>): Record<string, unknown> {
  return { ...appsResultRequestFields(content.input), ...content };
}
