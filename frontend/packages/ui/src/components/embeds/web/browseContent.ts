/** Read only known envelope fields; never guess how flattened JSON keys were nested. */
export function browseContent(content: Record<string, unknown>) {
  const result = Array.isArray(content.results) && content.results[0] && typeof content.results[0] === 'object'
    ? content.results[0] as Record<string, unknown> : content;
  const string = (key: string) => typeof result[key] === 'string' ? result[key] as string
    : typeof content[key] === 'string' ? content[key] as string : '';
  let data: unknown = result.data ?? null;
  if (typeof result.data_json === 'string') {
    try { data = JSON.parse(result.data_json); } catch { data = null; }
  }
  const status = typeof result.status === 'string' ? result.status : String(content.status || 'processing');
  const screenshot = string('screenshot_base64');
  return {
    sessionId: string('session_id'), runId: string('run_id'), status,
    title: string('title'), url: string('url') || string('start_url'),
    reason: string('reason'), task: string('task'), data,
    // Only the bounded, masked JPEG from the encrypted embed is renderable.
    screenshot: screenshot && /^[A-Za-z0-9+/=\r\n]+$/.test(screenshot)
      ? `data:image/jpeg;base64,${screenshot}` : '',
  };
}
export function browseStatusKey(status: string): string {
  const states: Record<string, string> = {
    processing: 'running', ai: 'running', user: 'user_control', paused: 'paused',
    completed: 'completed', no_results: 'no_results', needs_user: 'needs_user',
    blocked: 'blocked', failed: 'failed', error: 'failed', cancelled: 'cancelled',
    budget_exceeded: 'budget_exceeded', closed: 'closed', expired: 'expired',
  };
  return `embeds.browse.${states[status] || 'unavailable'}`;
}
