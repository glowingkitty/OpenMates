<!--
  Frozen synthetic recipient states for rendered Apple comparison. This harness
  issues no share API calls, decrypts no real data and performs no mutations.
  Gate markup/CSS mirrors share/chat/[chatId]/+page.svelte. The ready state uses
  production ChatHeader/ChatMessage and ChatHistory/ActiveChat layout rules.
  Native Swift counterparts:
  - apple/OpenMates/Sources/Features/SharedChats/SharedChatRecipientView.swift
-->
<script lang="ts">
  import ChatHeader from '../ChatHeader.svelte';
  import ChatMessage from '../ChatMessage.svelte';
  import { text } from '@repo/ui';
  let { state: viewState = 'loading', invalidPassword = false }: {
    state?: 'loading' | 'password' | 'error' | 'ready'; invalidPassword?: boolean;
  } = $props();
  let password = $state('');
  let width = $state(390);
  const messages = [
    { id: 'recipient-user', role: 'user' as const, content: 'What should we verify before release?' },
    { id: 'recipient-assistant', role: 'assistant' as const, content: 'Verify the result and review the evidence before completion.' }
  ];
</script>

{#if viewState === 'ready'}
  <div class="recipient-ready" bind:clientWidth={width} data-testid="shared-recipient-ready">
    <ChatHeader title="Launch preparation" currentChatId="recipient-preview" category="general_knowledge"
      summary="Coordinate the work and verify the outcome before completion."
      chatCreatedAt={1788883200} isSharedChat={true} writable={false}
      onSaveTitle={() => {}} onSaveDescription={() => {}} />
    <div class="recipient-history">
      <div class="chat-history-content">
        {#each messages as message (message.id)}
          <div class="message-wrapper {message.role}" data-message-id={message.id}>
            <ChatMessage role={message.role} content={message.content} messageId={message.id}
              category="general_knowledge" sender_name={message.role === 'assistant' ? 'Sophia' : undefined}
              status="synced" containerWidth={width} canAnnotate={false} isFirstMessage={message.role === 'user'} />
          </div>
        {/each}
        <div class="read-only-indicator">
          <div class="read-only-icon">🔒</div>
          <p class="read-only-text">{$text('chat.read_only_shared')}</p>
        </div>
      </div>
    </div>
  </div>
{:else}
  <div class="share-chat-page" data-testid="shared-recipient-gate">
    {#if viewState === 'loading'}
      <div class="loading-container">
        <img class="openmates-logo" src="/favicon.svg" alt="OpenMates" />
        <p>Decrypting chat…</p>
        <div class="loading-spinner"></div>
      </div>
    {:else if viewState === 'error'}
      <div class="error-container">
        <div class="error-icon">⚠️</div>
        <h1>Unable to Load Chat</h1>
        <p>This shared chat is no longer available or the link is invalid.</p>
        <button onclick={() => {}}>Go to Home</button>
      </div>
    {:else}
      <div class="password-container">
        <div class="password-icon">🔒</div>
        <h1>Password Required</h1>
        <p>This shared chat is protected with a password.</p>
        <form data-testid="shared-chat-password-form" onsubmit={(event) => event.preventDefault()}>
          <input data-testid="shared-chat-password-input" type="password" bind:value={password}
            placeholder="Enter password" maxlength="10" class:error={invalidPassword} />
          {#if invalidPassword}<p class="password-error" data-testid="shared-chat-password-error">Incorrect password. Please try again.</p>{/if}
          <button type="submit" data-testid="shared-chat-password-submit">Access Chat</button>
        </form>
      </div>
    {/if}
  </div>
{/if}

<style>
  .share-chat-page { min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 20px; background-color: var(--color-grey-5, #f5f5f5); box-sizing: border-box; width: 100%; }
  .loading-container, .error-container, .password-container { max-width: 500px; width: 100%; text-align: center; padding: 40px; background: white; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,.1); }
  .loading-container { display: flex; flex-direction: column; align-items: center; justify-content: center; }
  .loading-spinner { width: 48px; height: 48px; border: 4px solid var(--color-grey-20, #e0e0e0); border-top-color: var(--color-primary, #6b46c1); border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto; }
  .openmates-logo { width: 96px; height: 96px; margin-bottom: 18px; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .error-icon, .password-icon { font-size: calc(var(--font-size-xxxl) * 2); margin-bottom: 20px; }
  h1 { font-size: 24px; margin: 0 0 12px; color: var(--color-grey-100, #1a1a1a); }
  p { font-size: 16px; font-family: var(--font-primary, 'Lexend Deca', sans-serif); text-align: center; color: var(--color-grey-70, #666); margin: 0 0 18px; }
  button { padding: 12px 24px; background-color: var(--color-primary, #6b46c1); color: white; border: none; border-radius: 8px; font-size: 16px; font-weight: 500; cursor: pointer; transition: background-color .2s ease; }
  button:hover { background-color: var(--color-primary-dark, #5a36b2); }
  form { display: flex; flex-direction: column; gap: 12px; margin-top: 24px; }
  input[type='password'] { padding: 12px; border: 2px solid var(--color-grey-30, #d0d0d0); border-radius: 8px; font-size: 16px; }
  input[type='password'].error { border-color: var(--color-error, #dc2626); }
  .password-error { color: var(--color-error, #dc2626); font-size: 14px; margin: -8px 0 0; }
  .recipient-ready { min-height: 100vh; width: 100%; background: var(--color-grey-0); }
  .recipient-history { padding: 10px; }
  .chat-history-content { width: 100%; max-width: var(--chat-content-max-width, 1000px); margin: 0 auto; box-sizing: border-box; }
  .message-wrapper { margin: 5px 0; width: 100%; display: flex; flex-shrink: 0; }
  .message-wrapper.user { justify-content: flex-end; }
  .message-wrapper.assistant { justify-content: flex-start; }
  .message-wrapper :global(.chat-message) { width: 100%; }
  .read-only-indicator { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: var(--spacing-12) var(--spacing-8); margin-bottom: var(--spacing-6); background-color: var(--color-grey-10, #f0f0f0); border: 1px solid var(--color-grey-30, #d0d0d0); border-radius: var(--radius-3); text-align: center; }
  .read-only-icon { font-size: var(--font-size-xxxl); margin-bottom: var(--spacing-6); opacity: .7; }
  .read-only-text { font-size: var(--font-size-small); color: var(--color-grey-70, #666); margin: 0; line-height: 1.5; max-width: 500px; }
</style>
