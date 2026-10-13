/** Ordered, translated alternatives: use the most informative one that fits. */
export interface ActivitySummaryState {
  apps: string[];
  memories: string[];
  focuses: string[];
  thinking: boolean;
  usingApps: boolean;
  thinkingStreaming: boolean;
  activatingFocus: boolean;
  subChats: boolean;
  workingSubChats: boolean;
  active: boolean;
  cancelledFocus: boolean;
}
type Translate = (key: string, values?: Record<string, string | number>) => string;

export function activitySummaryCandidates(state: ActivitySummaryState, translate: Translate): string[] {
  const t = (key: string, values?: Record<string, string | number>) => translate(`chat.response_activity.${key}`, values);
  const list = (names: string[]) => names.length > 1
    ? t('list_last', { items: names.slice(0, -1).join(', '), last: names[names.length - 1] }) : names[0] ?? '';
  const join = (parts: string[]) => parts.reduce((a, b) => a ? t('join', { first: a, last: b }) : b, '');
  const appCount = () => t(state.usingApps ? 'using_count' : state.thinking && !state.memories.length ? 'thought_used_count' : 'used_count', { count: state.apps.length });
  const focus = (compact: boolean) => t(compact ? state.activatingFocus ? 'focus_activating_count' : 'focus_activated_count'
    : state.activatingFocus ? 'focus_activating' : 'focus_activated', { focus: state.focuses.join("', '"), count: state.focuses.length });
  const subChats = () => t(state.workingSubChats ? 'sub_chats_working' : 'sub_chats');
  const memory = (compact: boolean) => t(!compact && state.memories.length === 1 ? 'memory_loaded' : 'memories_loaded', { memory: state.memories[0] ?? '', count: state.memories.length });
  const detailedApps = () => {
    if (state.apps.length > 3) return t(state.usingApps ? 'using_more' : state.thinking ? 'thought_used_more' : 'used_more', {
      apps: state.apps.slice(0, 3).join(', '), count: state.apps.length - 3,
    });
    return t(state.usingApps ? state.thinkingStreaming ? 'thinking_using' : 'using'
      : `${state.thinking ? 'thought_used' : 'used'}_${state.apps.length === 1 ? 'single' : 'multiple'}`, { apps: list(state.apps) });
  };
  const candidates: string[] = [];
  for (const compact of [false, true]) {
    const clauses: string[] = [];
    if (state.memories.length) {
      // Loading Memories always changes app names into a count, even on a wide screen.
      if (state.apps.length && state.memories.length === 1 && !state.focuses.length && !state.subChats && !compact) {
        clauses.push(t(state.usingApps ? 'memory_using_apps' : 'memory_used_apps', { memory: state.memories[0], count: state.apps.length }));
      } else {
        clauses.push(memory(compact));
        if (state.apps.length) clauses.push(appCount());
      }
    } else if (state.apps.length) clauses.push(compact ? appCount() : detailedApps());
    if (state.focuses.length) {
      if (!state.memories.length && !state.apps.length && state.subChats && !state.activatingFocus && !state.workingSubChats && !compact) {
        clauses.push(t('focus_sub_chats', { focus: state.focuses.join("', '") }));
      } else clauses.push(focus(compact));
    }
    if (state.subChats && !(state.focuses.length && !state.memories.length && !state.apps.length && !state.activatingFocus && !state.workingSubChats && !compact)) clauses.push(subChats());
    if (clauses.length) {
      const standaloneSentence = !compact && !state.focuses.length && !state.subChats &&
        ((state.memories.length === 1 && !!state.apps.length) || (!state.memories.length && state.apps.length > 3));
      candidates.push(standaloneSentence ? t('sentence', { activity: join(clauses) }) : join(clauses));
    }
  }
  // The compact ledger keeps every activity kind when long translated names do not fit.
  const counts: string[] = [];
  if (state.memories.length) counts.push(t('memory_count', { count: state.memories.length }));
  if (state.apps.length) counts.push(t('app_count', { count: state.apps.length }));
  if (state.focuses.length) counts.push(t('focus_count', { count: state.focuses.length }));
  if (state.subChats) counts.push(t('sub_chat_count'));
  if (counts.length) candidates.push(join(counts));
  if (!candidates.length && state.cancelledFocus) candidates.push(t('focus_cancelled'));
  if (!candidates.length) candidates.push(translate(state.active ? 'chat.thinking.header_streaming' : 'chat.thinking.header_done'));
  candidates.push(t(state.active ? 'activity_active' : 'activity_done'));
  return [...new Set(candidates)];
}
