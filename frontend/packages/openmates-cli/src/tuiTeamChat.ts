/** Owner-fenced refresh and sender labels for the open encrypted Team chat. */
import type { DecryptedMessage, OpenMatesClient } from './client.js';
import type { TuiMessage, TuiState } from './tuiRenderer.js';
import { captureTuiWorkspaceOwner } from './tuiCachedWorkspaces.js';
import { registerChatEmbedAliases, hydrateChatEmbedPreviews } from './tuiEmbeds.js';
import { terminalText } from './tuiText.js';
import { createHash } from 'node:crypto';

export function tuiChatMessages(messages: DecryptedMessage[], teamId: string | null, username: string | null, currentUserHash: string | null): TuiMessage[] {
  const ownName = username?.trim().toLocaleLowerCase();
  return messages.map((message) => {
    const role = message.role === 'user' ? 'user' : message.role === 'system' ? 'system' : 'assistant';
    const name = message.senderName ? terminalText(message.senderName).trim() : '';
    const remoteUser = !!teamId && role === 'user' && (message.hashedSenderUserId
      ? !currentUserHash || message.hashedSenderUserId !== currentUserHash
      : !!name && (!ownName || name.toLocaleLowerCase() !== ownName));
    return { id: message.clientMessageId || message.id, role, content: message.content, title: name || null,
      remoteUser, senderUserHash: message.hashedSenderUserId ?? null, category: message.category, embedIds: message.embedIds };
  });
}

/** Keep loaded older history while a bounded latest window replaces its overlap. */
export function mergeTuiTeamChatWindow(existing: TuiMessage[], latest: TuiMessage[], hasMoreBefore: boolean):
  {messages:TuiMessage[];hasGap:boolean} {
  if (!hasMoreBefore) return {messages:latest,hasGap:false};
  const existingById=new Map(existing.flatMap((message,index)=>message.id?[[message.id,index] as const]:[]));
  const overlap=latest.findIndex(message=>!!message.id&&existingById.has(message.id));
  if(overlap<0)return {messages:[...existing,...latest],hasGap:true};
  const older=existing.slice(0,existingById.get(latest[overlap].id!)!);
  // Only unacknowledged local rows lack a canonical ID. An omitted confirmed
  // tail is a server deletion, rather than a pending send to retain forever.
  const trailing=existing.slice(older.length).filter(message=>!message.id);
  return {messages:[...older,...latest,...trailing],hasGap:false};
}

/** Correct sender labels after identity arrives without replacing an in-flight send's message array. */
export function reconcileTuiTeamSenderLabels(state: TuiState): void {
  if (!state.currentUserHash || state.screen!=='chat' || state.isBusy) return;
  for (const message of state.messages) {
    if (message.role==='user' && message.senderUserHash)
      message.remoteUser=message.senderUserHash!==state.currentUserHash;
  }
}

export async function loadTuiTeamIdentity(state: TuiState, client: OpenMatesClient, render: () => void,
  isCurrent: () => boolean = () => true): Promise<{profileLoaded:boolean;teamLoaded:boolean}|null> {
  const teamId=client.getActiveTeamId();
  if (!client.hasSession() || !teamId) return null;
  const ownerCurrent = captureTuiWorkspaceOwner(client);
  const [profile,team]=await Promise.allSettled([
    typeof client.whoAmI==='function' ? client.whoAmI() : Promise.reject(new Error('Profile unavailable')),
    typeof client.getTeamDetails==='function' ? client.getTeamDetails(teamId) : Promise.reject(new Error('Team unavailable')),
  ]);
  if (!isCurrent() || !ownerCurrent() || client.getActiveTeamId()!==teamId) return null;
  let profileLoaded=false;
  if (profile.status==='fulfilled') {
    const user=profile.value;
    const id = String(user.id ?? '');
    if (id) {state.currentUserHash = createHash('sha256').update(id).digest('hex');profileLoaded=true;}
    if (typeof user.username === 'string') state.username = terminalText(user.username);
  }
  if (team.status==='fulfilled') state.activeTeamName=terminalText(team.value.name).trim()||null;
  reconcileTuiTeamSenderLabels(state);
  render();
  return {profileLoaded,teamLoaded:team.status==='fulfilled'};
}

export function createTuiTeamChatRefresh(state: TuiState, client: OpenMatesClient, render: () => void,
  pollIntervalMs = 5_000) {
  let closed = false, inFlight = false, pending = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  // This timer must remain independent of sidebar activity: that request can
  // stall while an open Team chat still needs to receive a human message.
  const poll = setInterval(() => request(), pollIntervalMs);
  poll.unref?.();
  const eligible = () => !closed && state.signedIn && client.hasSession()
    && state.workspace === 'chats' && state.screen === 'chat' && !!state.activeChatId
    && !!state.activeTeamId && state.activeTeamId === client.getActiveTeamId();
  const refresh = async () => {
    timer = null;
    if (!pending || inFlight || !eligible()) return;
    if (state.isBusy) { request(); return; }
    pending = false; inFlight = true;
    const chatId = state.activeChatId!, teamId = client.getActiveTeamId()!;
    const route = state.routeVersion, messages = state.messages;
    const ownerCurrent = captureTuiWorkspaceOwner(client);
    const current = () => eligible() && ownerCurrent() && state.routeVersion === route
      && state.activeChatId === chatId && client.getActiveTeamId() === teamId && state.messages === messages && !state.isBusy;
    try {
      const window = typeof client.getChatMessagesWindow === 'function'
        ? await client.getChatMessagesWindow(chatId,{teamId,direction:'latest',limit:100,
          respectCompressionBoundary:false,preferCache:true}) : null;
      const result = window ?? await client.getChatMessages(chatId, { teamId });
      if (!current() || result.chat.id !== chatId) return;
      const fetched=tuiChatMessages(result.messages, teamId, state.username, state.currentUserHash);
      const merged=window ? mergeTuiTeamChatWindow(messages,fetched,window.hasMoreBefore) : {messages:fetched,hasGap:false};
      const next=merged.messages;
      if(merged.hasGap)state.status='Some older Team messages may be missing. Use /refresh to load full history.';
      // An activity event can carry metadata only. Avoid rerendering and replacing
      // selected message objects when the encrypted message set has not changed.
      if (next.length === messages.length && next.every((message, index) =>
        message.id === messages[index].id && message.role === messages[index].role
        && message.content === messages[index].content && message.category === messages[index].category
        && message.title === messages[index].title && message.remoteUser === messages[index].remoteUser
        && message.senderUserHash === messages[index].senderUserHash
        && (message.embedIds??[]).length === (messages[index].embedIds??[]).length
        && (message.embedIds??[]).every((id, embedIndex) => id === messages[index].embedIds?.[embedIndex]))) return;
      state.messages = next;
      state.activeChat = result.chat;
      registerChatEmbedAliases(state);
      if (typeof client.getEmbed === 'function') void hydrateChatEmbedPreviews(state, client, render);
      render();
    } catch {
      // The open chat stays readable while a transient sync fails. The next
      // activity event or fallback poll retries with the same owner checks.
    } finally {
      inFlight = false;
      if (state.isBusy && eligible()) pending = true;
      if (pending && eligible()) request();
    }
  };
  const request = () => {
    if (!eligible()) return;
    pending = true;
    if (timer || inFlight) return;
    timer = setTimeout(() => { void refresh(); }, state.isBusy ? Math.min(1_000,pollIntervalMs) : 250);
  };
  return { request, dispose: () => { closed = true; clearInterval(poll); if (timer) clearTimeout(timer); timer = null; } };
}
