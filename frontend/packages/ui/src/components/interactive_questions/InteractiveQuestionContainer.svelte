<!--
  frontend/packages/ui/src/components/interactive_questions/InteractiveQuestionContainer.svelte

  Master container for InteractiveQuestions.
  Manages clear/send buttons, tracks validation, checks subsequent messages
  to identify and load the answered/locked state, and formats response payloads.
  Uses Svelte 5 Runes for properties and reactivity.

  Architecture: Svelte 5 Socratic assessment UI
-->

<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { fly } from 'svelte/transition';
  import type {
    InteractiveQuestionPayload,
    InteractiveQuestionResponse,
  } from './types';
  import {
    findSubsequentResponse,
    formatInteractiveQuestionUserResponse,
    submitResponse
  } from './utils/questionState';
  import { chatDB } from '../../services/db';
  import { chatSyncService } from '../../services/chatSyncService';
  import type { Message } from '../../types/chat';
  import { activeChatStore } from '../../stores/activeChatStore';
  import ChoiceQuestion from './renderers/ChoiceQuestion.svelte';
  import InputQuestion from './renderers/InputQuestion.svelte';
  import SliderQuestion from './renderers/SliderQuestion.svelte';
  import SwipeQuestion from './renderers/SwipeQuestion.svelte';
  import RatingQuestion from './renderers/RatingQuestion.svelte';

  // Svelte 5 Props (passed from NodeView / ChatMessage rendering context)
  let {
    payload,
    chatId = ''
  }: {
    payload: InteractiveQuestionPayload;
    chatId?: string;
  } = $props();

  // Reactive message list state
  let loadedHistory = $state<Message[]>([]);

  // Reactive state: find if already answered in subsequent messages
  let answeredState = $derived(findSubsequentResponse(loadedHistory, payload.id));
  let isAnswered = $derived(!!answeredState);

  // Selection states managed by the child renderers
  let currentSelection = $state<InteractiveQuestionResponse | null>(null);
  let isValid = $state(false);

  // Load and refresh message history from IndexedDB
  async function refreshHistory() {
    const activeChatId = chatId || activeChatStore.get() || '';
    if (!activeChatId) return;
    try {
      const msgs = await chatDB.getMessagesForChat(activeChatId);
      if (msgs) {
        loadedHistory = msgs;
      }
    } catch (err) {
      console.warn('[InteractiveQuestionContainer] Failed to load chat history:', err);
    }
  }

  // Handle events from chatSyncService
  function handleSyncEvent() {
    refreshHistory();
  }

  onMount(() => {
    refreshHistory();
    // Subscriptions for dynamic live-updates
    chatSyncService.addEventListener('messageStatusChanged', handleSyncEvent);
    chatSyncService.addEventListener('chatUpdated', handleSyncEvent);
  });

  onDestroy(() => {
    chatSyncService.removeEventListener('messageStatusChanged', handleSyncEvent);
    chatSyncService.removeEventListener('chatUpdated', handleSyncEvent);
  });

  // Handle "Clear" click to reset selections
  function handleClear() {
    currentSelection = null;
    isValid = false;
  }

  // Handle "Send" click
  async function handleSend() {
    const activeChatId = chatId || activeChatStore.get() || '';
    if (!isValid || !activeChatId || isAnswered || !currentSelection) return;

    try {
      const responseText = formatInteractiveQuestionUserResponse(payload, currentSelection);
      await submitResponse(activeChatId, responseText);
      // Optimistic lock before sync triggers DB refresh
      loadedHistory = [
        ...loadedHistory,
        {
          message_id: `${activeChatId.slice(-10)}-${crypto.randomUUID()}`,
          chat_id: activeChatId,
          role: 'user',
          created_at: Math.floor(Date.now() / 1000),
          status: 'synced',
          content: responseText
        }
      ];
    } catch (e) {
      console.error('[InteractiveQuestionContainer] Submit response failed:', e);
    }
  }
</script>

<div class="interactive-question-card" class:locked={isAnswered}>
  <div class="question-header">
    {#if payload.type === 'choice'}
      <span class="type-badge choice-badge">Choice</span>
    {:else if payload.type === 'input'}
      <span class="type-badge input-badge">Form</span>
    {:else if payload.type === 'slider'}
      <span class="type-badge slider-badge">Scale</span>
    {:else if payload.type === 'swipe'}
      <span class="type-badge swipe-badge">Swipe Decision</span>
    {:else if payload.type === 'rating'}
      <span class="type-badge rating-badge">Rating</span>
    {/if}

    {#if isAnswered}
      <span class="answered-badge">
        <svg viewBox="0 0 24 24" class="lock-icon">
          <path fill="currentColor" d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
        </svg>
        Answered
      </span>
    {/if}
  </div>

  {#if payload.question}
    <h4 class="question-title">{payload.question}</h4>
  {/if}

  <div class="question-body">
    {#if payload.type === 'choice'}
      <ChoiceQuestion
        data={payload}
        bind:value={currentSelection}
        bind:isValid
        disabled={isAnswered}
        answeredValue={answeredState?.selection}
      />
    {:else if payload.type === 'input'}
      <InputQuestion
        data={payload}
        bind:value={currentSelection}
        bind:isValid
        disabled={isAnswered}
        answeredValue={answeredState?.inputs}
      />
    {:else if payload.type === 'slider'}
      <SliderQuestion
        data={payload}
        bind:value={currentSelection}
        bind:isValid
        disabled={isAnswered}
        answeredValue={answeredState?.value}
      />
    {:else if payload.type === 'swipe'}
      <SwipeQuestion
        data={payload}
        bind:value={currentSelection}
        bind:isValid
        disabled={isAnswered}
        answeredValue={answeredState?.swipes}
      />
    {:else if payload.type === 'rating'}
      <RatingQuestion
        data={payload}
        bind:value={currentSelection}
        bind:isValid
        disabled={isAnswered}
        answeredValue={answeredState}
      />
    {/if}
  </div>

  {#if !isAnswered}
    <div class="card-footer" transition:fly={{ y: 8, duration: 150 }}>
      <button class="btn btn-clear" onclick={handleClear}>Clear</button>
      <button class="btn btn-send" class:disabled={!isValid} onclick={handleSend} disabled={!isValid}>Send</button>
    </div>
  {/if}
</div>

<style>
  .interactive-question-card {
    background: var(--color-grey-10, #f8f9fa);
    border: 1px solid var(--color-grey-20, #e9ecef);
    border-radius: var(--radius-12, 12px);
    padding: var(--spacing-12, 12px);
    box-shadow: var(--shadow-sm, 0 1px 3px rgba(0,0,0,0.05));
    display: flex;
    flex-direction: column;
    gap: var(--spacing-12, 12px);
    box-sizing: border-box;
    width: 100%;
    max-width: 100%;
    margin: var(--spacing-8, 8px) 0;
    transition: all 0.25s ease;
  }

  .interactive-question-card.locked {
    background: transparent;
    border-color: var(--color-grey-15, #f1f3f5);
    box-shadow: none;
    padding: var(--spacing-12, 12px) 0;
  }

  .question-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
  }

  .type-badge {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 2px var(--spacing-8, 8px);
    border-radius: var(--radius-full, 12px);
    line-height: 1.2;
  }

  .choice-badge {
    background: #e7f5ff;
    color: #228be6;
  }

  .input-badge {
    background: #f3f0ff;
    color: #7950f2;
  }

  .slider-badge {
    background: #fff0f6;
    color: #d6336c;
  }

  .swipe-badge {
    background: #e8f7f5;
    color: #0ca678;
  }

  .rating-badge {
    background: #fff9db;
    color: #f08c00;
  }

  .answered-badge {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    font-weight: 500;
    color: var(--color-font-secondary, #495057);
  }

  .lock-icon {
    width: 14px;
    height: 14px;
    color: var(--color-success, #40c057);
  }

  .question-body {
    width: 100%;
  }

  .card-footer {
    display: flex;
    justify-content: flex-end;
    gap: var(--spacing-12, 12px);
    width: 100%;
    border-top: 1px solid var(--color-grey-15, #f1f3f5);
    padding-top: var(--spacing-12, 12px);
  }

  .btn {
    border: 1px solid transparent;
    border-radius: var(--radius-8, 8px);
    font-size: var(--font-size-small, 13px);
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s ease;
    min-height: 34px;
    padding: 0 var(--spacing-16, 16px);
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .btn-clear {
    background: none;
    border-color: var(--color-grey-35, #ced4da);
    color: var(--color-font-primary, #212529);
  }

  .btn-clear:hover {
    background: var(--color-grey-10, #f8f9fa);
  }

  .btn-send {
    background: var(--color-primary, #4dabf7);
    color: white;
  }

  .btn-send:hover {
    background: #339af0;
  }

  .btn-send.disabled {
    background: var(--color-grey-30, #ced4da);
    color: var(--color-grey-50, #868e96);
    cursor: not-allowed;
  }
</style>
