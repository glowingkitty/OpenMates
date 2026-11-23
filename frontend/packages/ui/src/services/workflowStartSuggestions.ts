/**
 * Start-screen suggestions of the Workflows page (Marco, 21 Nov; Task dd6af963).
 *
 * They are the workflow recommendations the user already got inside their chats (the
 * Recommendations card after a question), newest first. This shell part only reads and
 * decrypts each chat's stored `encrypted_recommendations` on this device; ordering,
 * filtering (new workflows only, not dismissed or saved) and de-duplication run in the
 * Rust core (`client::workflow_start_suggestions`). The server never sees plaintext.
 * Spec: workflows-ui.home.prompt-suggestions
 */
import { chatDB } from './db';
import { RECOMMENDATIONS_IN_BUILD, readStoredRecommendations, rustRecommendations } from './chatRecommendationsPersistence';
import type { ChatRecommendationsState, WorkflowStartSuggestion } from '../types/recommendations';

/** Chats read per load: the most recent ones, so opening Workflows stays fast on large accounts. */
const RECENT_CHATS_READ = 60;

/** Suggestions shown above the describe-a-workflow input. */
export const WORKFLOW_START_SUGGESTION_COUNT = 3;

/**
 * The newest workflow recommendations of the user's chats (empty when there are none
 * yet, or in builds without the Rust core, where Recommendations do not exist).
 */
export async function loadWorkflowStartSuggestions(): Promise<WorkflowStartSuggestion[]> {
  if (!RECOMMENDATIONS_IN_BUILD) return [];
  const chats = await chatDB.getAllChats(undefined, { limit: RECENT_CHATS_READ });
  const states: ChatRecommendationsState[] = [];
  for (const chat of chats) {
    if (!chat.encrypted_recommendations) continue;
    const state = await readStoredRecommendations(chat.chat_id);
    if (state) states.push(state);
  }
  if (states.length === 0) return [];
  const { workflowStartSuggestions } = await rustRecommendations();
  return workflowStartSuggestions({ states, limit: WORKFLOW_START_SUGGESTION_COUNT });
}
