import type { EmbedSourceChatContext } from '../../../types/embedFullscreen';

/** An owner lookup is normal; only an explicit private chat permits live controls. */
export function canViewBrowseSession(authenticated: boolean, userId: string | null, source?: EmbedSourceChatContext): boolean {
  return !!(authenticated && userId && source?.chatId && source.isReadOnly === false && !source.exampleChatId
    && (!source.lookupChatId || source.lookupChatId === source.chatId));
}

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
  // JSON paths the run could not verify; empty or absent means complete.
  const rawMissing = Array.isArray(result.missing) ? result.missing : Array.isArray(content.missing) ? content.missing : [];
  const missing = rawMissing.filter((item): item is string => typeof item === 'string' && item.trim() !== '').map(item => item.trim());
  return {
    sessionId: string('session_id'), runId: string('run_id'), status,
    title: string('title'), url: string('url') || string('start_url'),
    reason: string('reason'), task: string('task'), data, missing,
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

/** Translation key for a step verb; unknown kinds fall back to the neutral "Started" wording. */
export function browseStepKey(kind: string): string {
  const kinds: Record<string, string> = {
    start: 'step_start', goto: 'step_goto', click: 'step_click', type: 'step_type',
    select: 'step_select', scroll: 'step_scroll', wait: 'step_wait', back: 'step_back',
  };
  return `embeds.browse.${kinds[kind] || 'step_goto'}`;
}
/** Only verbs that act on a named page element show the observed target label. */
export function browseStepShowsLabel(kind: string): boolean {
  return kind === 'click' || kind === 'type' || kind === 'select';
}
export function browsePhaseKey(phase: string | undefined): string {
  return phase === 'starting' || phase === 'working' || phase === 'finishing' ? `embeds.browse.phase_${phase}` : '';
}
