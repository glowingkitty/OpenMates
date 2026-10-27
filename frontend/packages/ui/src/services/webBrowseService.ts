import { getApiEndpoint } from '../config/api';

export interface BrowseSession {
  session_id: string;
  chat_id: string;
  status: 'ai' | 'user' | 'paused' | 'closed' | 'expired';
  task: string;
  url: string;
  sign_in_notice: string;
  sign_in_origins: string[];
  needs_sign_in_consent?: boolean;
  sign_in_origin?: string;
  max_credits: number;
  accrued_credits: number;
  charged_credits: number;
  accounting_pending: boolean;
  expires_at: number;
}
export type BrowseInput = { kind: 'click'; x: number; y: number }
  | { kind: 'type'; text: string }
  | { kind: 'key'; key: 'Enter' | 'Tab' | 'Shift+Tab' | 'Backspace' | 'Escape' | 'ArrowDown' | 'ArrowUp' | 'Control+A' }
  | { kind: 'scroll'; delta: number };
export interface BrowseCommand {
  operation: 'take_control' | 'resume' | 'stop' | 'close' | 'input' | 'sign_in';
  action?: BrowseInput;
  sign_in_origin?: string;
}
export class BrowseHttpError extends Error {
  constructor(public status: number) { super('browser_request_failed'); }
}
export interface BrowseClient {
  state(sessionId: string, signal: AbortSignal): Promise<BrowseSession>;
  frame(sessionId: string, signal: AbortSignal): Promise<Blob>;
  control(sessionId: string, command: BrowseCommand, signal: AbortSignal): Promise<BrowseSession>;
}
function endpoint(id: string, suffix = ''): string {
  if (!/^[0-9a-f-]{36}$/.test(id)) throw new Error('invalid_browser_session');
  return getApiEndpoint(`/v1/apps/web/browse/${encodeURIComponent(id)}${suffix}`);
}
async function checked(response: Response): Promise<Response> {
  if (!response.ok) throw new BrowseHttpError(response.status);
  return response;
}
/** First-party cookies only. No credentials in URLs, persistent caches or logs. */
export const webBrowseClient: BrowseClient = {
  async state(id, signal) {
    return (await checked(await fetch(endpoint(id), { credentials: 'include', cache: 'no-store', signal }))).json();
  },
  async frame(id, signal) {
    return (await checked(await fetch(endpoint(id, '/frame'), { credentials: 'include', cache: 'no-store', signal }))).blob();
  },
  async control(id, command, signal) {
    return (await checked(await fetch(endpoint(id, '/control'), {
      method: 'POST', credentials: 'include', cache: 'no-store', signal,
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(command),
    }))).json();
  },
};
