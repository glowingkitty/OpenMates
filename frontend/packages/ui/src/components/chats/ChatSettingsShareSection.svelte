<!--
  ChatSettingsShareSection.svelte

  Chat-only share UI for the Settings / Chats page. It keeps the existing
  zero-knowledge share-link format and short-link service while replacing the
  old mixed chat/embed SettingsShare visual surface.
-->
<script lang="ts">
  import QRCodeSVG from 'qrcode-svg';
  import { authStore } from '../../stores/authStore';
  import { getApiEndpoint } from '../../config/api';
  import { chatDB } from '../../services/db';
  import { generateShareKeyBlob, type ShareDuration } from '../../services/shareEncryption';
  import { generateShortUrlParts, encryptShareUrl, buildShortUrl } from '../../services/shortUrlEncryption';
  import { chatKeyManager } from '../../services/encryption/ChatKeyManager';
  import { encryptWithChatKey, uint8ArrayToBase64 } from '../../services/cryptoService';
  import { copyToClipboard } from '../../utils/clipboardUtils';
  import { notificationStore } from '../../stores/notificationStore';
  import { downloadChatAsYaml } from '../../services/chatExportService';
  import { downloadChatAsZip } from '../../services/zipExportService';
  import { userDB } from '../../services/userDB';
  import { isPublicChat } from '../../demo_chats/convertToChat';
  import type { Chat, Message } from '../../types/chat';

  const PRIMARY_SHORT_LINK_TIMEOUT_MS = 5000;

  let {
    chat,
    messages = [],
    title,
    summary = '',
  }: {
    chat: Chat;
    messages?: Message[];
    title: string;
    summary?: string;
  } = $props();

  let shareWithCommunity = $state(false);
  let passwordEnabled = $state(false);
  let password = $state('');
  let autoExpireEnabled = $state(false);
  let generatedLink = $state('');
  let generatedLongLink = $state('');
  let isGenerating = $state(false);
  let isCopied = $state(false);
  let showQr = $state(false);
  let showUrl = $state(false);
  let qrCodeImageUrl = $state('');
  let shortLinkError = $state('');

  let durationSeconds = $derived<ShareDuration>(autoExpireEnabled ? 600 : 0);

  function generateQrCode(link: string): void {
    const qr = new QRCodeSVG({
      content: link,
      padding: 4,
      width: 260,
      height: 260,
      color: '#000000',
      background: '#ffffff',
      ecl: 'M',
    });
    qrCodeImageUrl = `data:image/svg+xml;base64,${btoa(qr.svg())}`;
  }

  async function getChatEncryptionKey(chatId: string): Promise<string> {
    const chatKey = await getRawChatEncryptionKey(chatId);
    return uint8ArrayToBase64(chatKey);
  }

  async function getRawChatEncryptionKey(chatId: string): Promise<Uint8Array> {
    const chatKey = chatKeyManager.getKeySync(chatId) ?? await chatKeyManager.getKey(chatId);
    if (!chatKey) {
      throw new Error('Chat key not available; cannot create share link.');
    }
    return chatKey;
  }

  async function createPrimaryShareLink(
    longShareLink: string,
    ttlSeconds: ShareDuration,
    passwordProtected: boolean
  ): Promise<{ url: string; usedLongFallback: boolean }> {
    if (!$authStore.isAuthenticated) {
      return { url: longShareLink, usedLongFallback: false };
    }

    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    try {
      const { token, shortKey } = generateShortUrlParts();
      const encryptedBlob = await encryptShareUrl(longShareLink, token, shortKey);
      const controller = new AbortController();
      timeoutId = setTimeout(() => controller.abort(), PRIMARY_SHORT_LINK_TIMEOUT_MS);

      const response = await fetch(getApiEndpoint('/v1/share/short-url'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          'Origin': window.location.origin,
        },
        body: JSON.stringify({
          token,
          encrypted_url: encryptedBlob,
          content_type: 'chat',
          content_id: chat.chat_id,
          password_protected: passwordProtected,
          ttl_seconds: ttlSeconds > 0 ? ttlSeconds : null,
        }),
        credentials: 'include',
        signal: controller.signal,
      });

      if (!response.ok) {
        shortLinkError = 'Short link unavailable. Using a long encrypted link.';
        return { url: longShareLink, usedLongFallback: true };
      }

      return { url: buildShortUrl(token, shortKey), usedLongFallback: false };
    } catch (error) {
      console.warn('[ChatSettingsShareSection] Short link failed; using long link:', error);
      shortLinkError = 'Short link took too long. Using a long encrypted link.';
      return { url: longShareLink, usedLongFallback: true };
    } finally {
      if (timeoutId) clearTimeout(timeoutId);
    }
  }

  async function markChatShared(sharedShortUrl?: string | null): Promise<void> {
    const existing = await chatDB.getChat(chat.chat_id);
    if (!existing) return;
    const profile = await userDB.getUserProfile();
    let encryptedSharedShortUrl = sharedShortUrl === undefined ? existing.encrypted_shared_short_url : null;
    if (sharedShortUrl) {
      try {
        encryptedSharedShortUrl = await encryptWithChatKey(sharedShortUrl, await getRawChatEncryptionKey(chat.chat_id));
      } catch (error) {
        console.warn('[ChatSettingsShareSection] Failed to persist encrypted short URL:', error);
      }
    }
    await chatDB.updateChat({
      ...existing,
      is_shared: true,
      is_private: false,
      share_pii: shareWithCommunity,
      encrypted_shared_short_url: encryptedSharedShortUrl,
      user_id: existing.user_id || profile?.user_id || undefined,
    });
    window.dispatchEvent(new CustomEvent('chatShared', { detail: { chat_id: chat.chat_id } }));
  }

  async function generateLink(): Promise<void> {
    if (isGenerating) return;
    isGenerating = true;
    shortLinkError = '';
    try {
      if (passwordEnabled && (!password || password.length > 10)) {
        notificationStore.error('Use a password between 1 and 10 characters.');
        return;
      }

      if (isPublicChat(chat.chat_id)) {
        generatedLongLink = `${window.location.origin}/#chat-id=${chat.chat_id}`;
        generatedLink = generatedLongLink;
      } else {
        const chatKey = await getChatEncryptionKey(chat.chat_id);
        const encryptedBlob = await generateShareKeyBlob(
          chat.chat_id,
          chatKey,
          durationSeconds,
          passwordEnabled ? password : undefined
        );
        generatedLongLink = `${window.location.origin}/share/chat/${chat.chat_id}#key=${encryptedBlob}`;
        const result = await createPrimaryShareLink(generatedLongLink, durationSeconds, passwordEnabled);
        generatedLink = result.url;
        await markChatShared(result.usedLongFallback ? null : generatedLink);
      }
      generateQrCode(generatedLink);
      showQr = false;
      showUrl = false;
    } catch (error) {
      console.error('[ChatSettingsShareSection] Failed to generate share link:', error);
      notificationStore.error('Could not create share link.');
    } finally {
      isGenerating = false;
    }
  }

  async function copyGeneratedLink(): Promise<void> {
    if (!generatedLink) return;
    const result = await copyToClipboard(generatedLink);
    if (!result.success) {
      notificationStore.error('Could not copy link.');
      return;
    }
    isCopied = true;
    setTimeout(() => { isCopied = false; }, 2000);
  }

  async function stopSharing(): Promise<void> {
    const existing = await chatDB.getChat(chat.chat_id);
    if (!existing) return;
    await chatDB.updateChat({
      ...existing,
      is_shared: false,
      is_private: true,
      share_pii: false,
      share_highlights: false,
      encrypted_shared_short_url: null,
    });
    generatedLink = '';
    generatedLongLink = '';
    qrCodeImageUrl = '';
    showQr = false;
    showUrl = false;
    window.dispatchEvent(new CustomEvent('chatSharingStopped', { detail: { chat_id: chat.chat_id } }));
  }

  async function downloadChat(): Promise<void> {
    await downloadChatAsYaml(chat, messages);
  }

  async function downloadChatZip(): Promise<void> {
    await downloadChatAsZip(chat, messages);
  }
</script>

<section class="chat-share" data-testid="chat-settings-share-section">
  {#if !generatedLink}
    <div class="share-option" data-testid="chat-settings-share-community">
      <span class="option-icon icon_globe"></span>
      <strong>Share with community</strong>
      <label class="switch"><input type="checkbox" bind:checked={shareWithCommunity} /><span></span></label>
    </div>
    <div class="share-option" data-testid="chat-settings-share-password">
      <span class="option-icon icon_key"></span>
      <strong>Password protection</strong>
      <label class="switch"><input type="checkbox" bind:checked={passwordEnabled} /><span></span></label>
    </div>
    {#if passwordEnabled}
      <input class="password-input" data-testid="chat-settings-share-password-input" bind:value={password} maxlength="10" placeholder="Password" />
    {/if}
    <div class="share-option" data-testid="chat-settings-share-expire">
      <span class="option-icon icon_clock"></span>
      <strong>Auto expire</strong>
      <label class="switch"><input type="checkbox" bind:checked={autoExpireEnabled} /><span></span></label>
    </div>
    <button class="share-primary" data-testid="share-generate-link" onclick={() => void generateLink()} disabled={isGenerating}>
      {isGenerating ? 'Sharing chat...' : 'Share chat'}
    </button>
    {#if isGenerating}
      <p data-testid="share-generation-status">Sharing chat...</p>
    {/if}
    <div class="share-divider"><span></span><em>or</em><span></span></div>
    <button class="share-action" data-testid="chat-settings-share-download-chat" onclick={() => void downloadChat()}>
      <span class="option-icon icon_download"></span>
      <strong>Download chat</strong>
    </button>
    <button class="share-action" data-testid="chat-settings-share-download-zip" onclick={() => void downloadChatZip()}>
      <span class="option-icon icon_files"></span>
      <strong>Download chat zip</strong>
    </button>
    <div class="share-preview" data-testid="share-chat-preview">
      <span class="option-icon icon_chat"></span>
      <strong data-testid="chat-title">{title}</strong>
      {#if summary}<small>{summary}</small>{/if}
    </div>
  {:else}
    <div class="generated" data-testid="chat-settings-share-generated">
      <p><span class="check">✓</span><strong>Share Link created</strong></p>
      <p><span class="check">✓</span><strong>Auto expire in <mark>{autoExpireEnabled ? '10 minutes' : 'never'}</mark></strong></p>
    </div>
    <div class="generated-actions" data-testid="share-short-link-section">
      <button class:copied={isCopied} class="share-action" data-testid="share-copy-link" onclick={() => void copyGeneratedLink()}>
        <span class="option-icon icon_copy"></span>
        <strong>{isCopied ? 'Copied' : 'Copy to clipboard'}</strong>
      </button>
      <div data-testid="share-short-link-copy" class="short-link-copy">
        <span data-testid="share-short-link-url">{generatedLink}</span>
      </div>
      <button class="share-action" data-testid={showQr ? 'chat-settings-share-hide-qr' : 'chat-settings-share-show-qr'} onclick={() => { showQr = !showQr; }}>
        <span class="option-icon icon_camera"></span>
        <strong>{showQr ? 'Hide QR code' : 'Show QR code'}</strong>
      </button>
      {#if showQr}
        <div class="qr-code" data-testid="chat-settings-share-qr">
          <img src={qrCodeImageUrl} alt="Share QR code" />
        </div>
      {/if}
      <button class="share-action" data-testid={showUrl ? 'chat-settings-share-hide-url' : 'chat-settings-share-show-url'} onclick={() => { showUrl = !showUrl; }}>
        <span class="option-icon icon_copy"></span>
        <strong>{showUrl ? 'Hide URL' : 'Show URL'}</strong>
      </button>
      {#if showUrl}
        <div class="url-box" data-testid="chat-settings-share-url" data-share-url-kind={generatedLink === generatedLongLink ? 'long' : 'short'}>{generatedLink}</div>
      {/if}
      {#if shortLinkError}
        <p class="share-error" data-testid="share-short-link-error">{shortLinkError}</p>
      {/if}
      <button class="share-action danger" data-testid="chat-settings-share-stop" onclick={() => void stopSharing()}>
        <span class="option-icon icon_delete"></span>
        <strong>Stop sharing</strong>
      </button>
      <div class="share-divider"><span></span><em>or</em><span></span></div>
      <button class="share-action" data-testid="chat-settings-share-download-chat" onclick={() => void downloadChat()}>
        <span class="option-icon icon_download"></span>
        <strong>Download chat</strong>
      </button>
      <button class="share-action" data-testid="chat-settings-share-download-zip" onclick={() => void downloadChatZip()}>
        <span class="option-icon icon_files"></span>
        <strong>Download chat zip</strong>
      </button>
    </div>
  {/if}
</section>

<style>
  .chat-share {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-4);
  }

  .share-option,
  .share-action,
  .share-preview {
    display: grid;
    grid-template-columns: 3.25rem 1fr auto;
    gap: var(--spacing-4);
    align-items: center;
    min-height: 3.25rem;
    color: var(--color-primary);
  }

  .share-action,
  .share-primary {
    border: 0;
    background: transparent;
    cursor: pointer;
    text-align: left;
    font: inherit;
  }

  .share-primary {
    width: 100%;
    min-height: 3.75rem;
    border-radius: var(--radius-full);
    background: var(--color-error, #ff503f);
    color: var(--color-white);
    text-align: center;
    font-weight: var(--font-weight-bold);
    box-shadow: var(--shadow-sm);
  }

  .option-icon {
    width: 3rem;
    height: 3rem;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background-color: var(--color-primary);
    background-repeat: no-repeat;
    background-position: center;
    background-size: 1.45rem;
  }

  .switch input {
    display: none;
  }

  .switch span {
    display: block;
    width: 3.5rem;
    height: 2rem;
    border-radius: var(--radius-full);
    background: var(--color-grey-30);
    box-shadow: inset 0 0 0 1px var(--color-border);
    position: relative;
  }

  .switch span::after {
    content: '';
    position: absolute;
    width: 1.7rem;
    height: 1.7rem;
    top: 0.15rem;
    left: 0.15rem;
    border-radius: 50%;
    background: var(--color-white);
    box-shadow: var(--shadow-sm);
    transition: transform var(--duration-fast) var(--easing-default);
  }

  .switch input:checked + span::after {
    transform: translateX(1.5rem);
  }

  .password-input,
  .url-box,
  .short-link-copy {
    width: 100%;
    box-sizing: border-box;
    border: 0;
    border-radius: var(--radius-lg);
    background: var(--color-grey-10);
    padding: var(--spacing-4);
    font: inherit;
    word-break: break-all;
  }

  .share-divider {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    gap: var(--spacing-3);
    align-items: center;
    color: var(--color-grey-60);
    font-weight: var(--font-weight-bold);
  }

  .share-divider span {
    height: 2px;
    background: var(--color-grey-30);
  }

  .generated p {
    display: flex;
    align-items: center;
    gap: var(--spacing-3);
    margin: var(--spacing-1) 0;
    font-size: 1.35rem;
  }

  .check {
    color: var(--color-success, #0aa000);
    font-size: 2rem;
  }

  mark {
    color: var(--color-primary);
    background: transparent;
  }

  .qr-code {
    display: flex;
    justify-content: center;
    padding: var(--spacing-4);
  }

  .danger strong,
  .danger .option-icon {
    color: var(--color-error);
    background-color: var(--color-error);
  }

  .share-error {
    color: var(--color-warning, #a16207);
  }
</style>
