import { v4 as uuidv4 } from 'uuid';

const SESSION_ID_KEY = 'session_id';

export function getSessionId(): string {
  let sessionId = sessionStorage.getItem(SESSION_ID_KEY);
  if (!sessionId) {
    sessionId = uuidv4();
    sessionStorage.setItem(SESSION_ID_KEY, sessionId);
  }
  return sessionId;
}

export function deleteSessionId(): void {
  sessionStorage.removeItem(SESSION_ID_KEY);
}
