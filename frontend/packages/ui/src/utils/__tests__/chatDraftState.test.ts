// frontend/packages/ui/src/utils/__tests__/chatDraftState.test.ts
//
// Regression coverage for persisted draft-only chat classification. Draft
// payload fields can be transiently absent during save/restore, while draft_v
// remains the durable signal that the chat shell still contains a draft.

import { describe, expect, it } from "vitest";

import type { Chat } from "../../types/chat";
import { isDraftOnlyChatSurface, isPersistedDraftOnlyChat, isFirstTurnComposerContext, classifyFirstTurnComposerContext, canBindUnclaimedFreshShell, reserveInitialFreshShellId } from "../chatDraftState";

describe("persisted draft-only chat classification", () => {
  // contract-test: supporting surface=gui.web assertions=drafts.draft-only.lifecycle,chat-navigation.draft-only.addressable
  it("uses a positive draft version when encrypted draft fields are absent", () => {
    const chat = {
      chat_id: "draft-chat",
      draft_v: 1,
      messages_v: 0,
    } as Chat;

    expect(isPersistedDraftOnlyChat(chat)).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=drafts.established-chat.presentation-unchanged
  it("does not classify established chats with messages as draft-only", () => {
    const chat = {
      chat_id: "established-chat",
      draft_v: 1,
      messages_v: 1,
    } as Chat;

    expect(isPersistedDraftOnlyChat(chat)).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=drafts.draft-only.lifecycle,chat-navigation.draft-only.addressable
  it("uses live composer content while persisted draft fields catch up", () => {
    const chat = {
      chat_id: "live-draft-chat",
      messages_v: 0,
    } as Chat;

    expect(isDraftOnlyChatSurface(chat, true)).toBe(true);
  });

  // contract-test: supporting surface=gui.web assertions=drafts.established-chat.presentation-unchanged
  it("keeps established chats with live draft content in normal chat presentation", () => {
    const chat = {
      chat_id: "established-chat-with-live-draft",
      messages_v: 2,
    } as Chat;

    expect(isDraftOnlyChatSurface(chat, true)).toBe(false);
  });
});


describe("first-turn composer data proof", () => {
  const scope = { authenticated: true, accountId: "account-a", teamId: null };
  const shell = { chat: null, temporaryChatId: "fresh-id", draftChatId: "fresh-id",
    hasLiveDraftContent: false, ...scope };

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership
  it("accepts an exact unsent shell and rejects other workspace identities", () => {
    expect(isFirstTurnComposerContext(shell)).toBe(true);
    expect(classifyFirstTurnComposerContext(shell)).toBe('eligible_shell');
    expect(isFirstTurnComposerContext({ ...shell, draftChatId: "other-id" })).toBe(false);
    expect(isFirstTurnComposerContext({ ...shell, teamId: "team-a" })).toBe(false);
    expect(isFirstTurnComposerContext({ ...shell, authenticated: false })).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership,drafts.draft-only.lifecycle
  it("keeps a persisted first draft eligible after visible content clears", () => {
    const chat = { chat_id: "draft-id", user_id: "account-a", team_id: null,
      messages_v: 0, draft_v: 1, title_v: 0 } as Chat;
    const input = { ...scope, chat, temporaryChatId: null, draftChatId: "draft-id",
      hasLiveDraftContent: false };
    expect(isFirstTurnComposerContext(input)).toBe(true);
    expect(classifyFirstTurnComposerContext(input)).toBe('eligible_draft');
    expect(isFirstTurnComposerContext({ ...input, chat: { ...chat, messages_v: 1 } })).toBe(false);
    expect(isFirstTurnComposerContext({ ...input, chat: { ...chat, title_v: 1 } })).toBe(false);
    expect(isFirstTurnComposerContext({ ...input, chat: { ...chat, user_id: "account-b" } })).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership
  it("does not treat an empty loaded chat without a draft as a new turn", () => {
    const input = { ...scope, chat: { chat_id: "empty-id", messages_v: 0 } as Chat,
      temporaryChatId: null, draftChatId: "empty-id", hasLiveDraftContent: false };
    expect(isFirstTurnComposerContext(input)).toBe(false);
    expect(classifyFirstTurnComposerContext(input)).toBe('not_draft_only');
  });
});


describe("unclaimed fresh shell draft binding", () => {
  const shell = { chat: null, temporaryChatId: "shell-id", composerChatId: "shell-id",
    draftChatId: null, activeChatId: null, pendingDraftSelection: false, hasMessages: false, hasLiveDraftContent: false,
    showWelcome: true, authenticated: true, accountId: "account-a", teamId: null, incognito: false };

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership
  it("claims only the exact personal shell with no existing draft binding", () => {
    expect(canBindUnclaimedFreshShell(shell)).toBe(true);
    expect(canBindUnclaimedFreshShell({ ...shell, composerChatId: "other-id" })).toBe(false);
    expect(canBindUnclaimedFreshShell({ ...shell, draftChatId: "other-id" })).toBe(false);
    expect(canBindUnclaimedFreshShell({ ...shell, draftChatId: "shell-id" })).toBe(false);
    expect(canBindUnclaimedFreshShell({ ...shell, activeChatId: "saved-id" })).toBe(false);
    expect(canBindUnclaimedFreshShell({ ...shell, pendingDraftSelection: true })).toBe(false);
    expect(canBindUnclaimedFreshShell({ ...shell, hasMessages: true })).toBe(false);
    expect(canBindUnclaimedFreshShell({ ...shell, hasLiveDraftContent: true })).toBe(false);
    expect(canBindUnclaimedFreshShell({ ...shell, showWelcome: false })).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership
  it("rejects other account, Team, incognito and persisted-chat scopes", () => {
    expect(canBindUnclaimedFreshShell({ ...shell, authenticated: false })).toBe(false);
    expect(canBindUnclaimedFreshShell({ ...shell, accountId: null })).toBe(false);
    expect(canBindUnclaimedFreshShell({ ...shell, teamId: "team-id" })).toBe(false);
    expect(canBindUnclaimedFreshShell({ ...shell, incognito: true })).toBe(false);
    expect(canBindUnclaimedFreshShell({ ...shell, chat: { chat_id: "shell-id", draft_v: 1 } as Chat })).toBe(false);
  });
});


describe("initial fresh shell identity", () => {
  // contract-test: supporting surface=gui.web assertions=message-input.send.ownership
  it("reserves the visible ID once and reuses only an exact prepared draft", () => {
    let allocations = 0;
    const createId = () => `new-${++allocations}`;
    const first = reserveInitialFreshShellId({ chat: null, temporaryChatId: null,
      selectedChatId: null, preparedDraftChatId: null, showWelcome: true, hasMessages: false }, createId);
    expect(first).toBe('new-1');
    expect(reserveInitialFreshShellId({ chat: null, temporaryChatId: first,
      selectedChatId: null, preparedDraftChatId: null, showWelcome: true, hasMessages: false }, createId)).toBe(first);
    expect(reserveInitialFreshShellId({ chat: null, temporaryChatId: null,
      selectedChatId: null, preparedDraftChatId: 'prepared-id', showWelcome: true, hasMessages: false }, createId)).toBe('prepared-id');
    expect(reserveInitialFreshShellId({ chat: { chat_id: 'saved-id' } as Chat, temporaryChatId: null,
      selectedChatId: 'saved-id', preparedDraftChatId: null, showWelcome: false, hasMessages: false }, createId)).toBeNull();
    expect(reserveInitialFreshShellId({ chat: null, temporaryChatId: null,
      selectedChatId: null, preparedDraftChatId: 'prepared-id', showWelcome: false,
      hasMessages: false }, createId)).toBe('new-2');
    expect(allocations).toBe(2);
  });
});
