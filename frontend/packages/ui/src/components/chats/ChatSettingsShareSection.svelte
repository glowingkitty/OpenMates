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
  import {
    SettingsButton,
    SettingsCard,
    SettingsDivider,
    SettingsInfoBox,
    SettingsInput,
    SettingsItem,
  } from '../settings/elements';

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
        void markChatShared(result.usedLongFallback ? null : generatedLink).catch((error) => {
          console.error('[ChatSettingsShareSection] Failed to persist shared chat state:', error);
        });
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
    <SettingsCard>
      <SettingsItem
        type="action"
        icon="subsetting_icon share"
        title="Share with community"
        subtitleTop="Allow this shared chat to appear in community surfaces."
        hasToggle={true}
        checked={shareWithCommunity}
        data-testid="chat-settings-share-community"
        onClick={() => { shareWithCommunity = !shareWithCommunity; }}
      />
      <SettingsItem
        type="action"
        icon="subsetting_icon key"
        title="Password protection"
        subtitleTop="Require a short password before opening the shared chat."
        hasToggle={true}
        checked={passwordEnabled}
        data-testid="chat-settings-share-password"
        onClick={() => { passwordEnabled = !passwordEnabled; }}
      />
    {#if passwordEnabled}
        <SettingsInput
          bind:value={password}
          type="password"
          maxlength={10}
          placeholder="Password"
          dataTestid="chat-settings-share-password-input"
        />
    {/if}
      <SettingsItem
        type="action"
        icon="subsetting_icon clock"
        title="Auto expire"
        subtitleTop="Expire the share link after 10 minutes."
        hasToggle={true}
        checked={autoExpireEnabled}
        data-testid="chat-settings-share-expire"
        onClick={() => { autoExpireEnabled = !autoExpireEnabled; }}
      />
      <SettingsButton fullWidth={true} loading={isGenerating} dataTestid="share-generate-link" onClick={() => void generateLink()}>
        {isGenerating ? 'Sharing chat...' : 'Share chat'}
      </SettingsButton>
    </SettingsCard>
    {#if isGenerating}
      <p data-testid="share-generation-status">Sharing chat...</p>
    {/if}
    <SettingsDivider spacing="sm" />
    <SettingsCard>
      <SettingsItem type="action" icon="subsetting_icon download" title="Download chat" data-testid="chat-settings-share-download-chat" onClick={() => void downloadChat()} />
      <SettingsItem type="action" icon="subsetting_icon files" title="Download chat zip" data-testid="chat-settings-share-download-zip" onClick={() => void downloadChatZip()} />
    </SettingsCard>
    <SettingsCard>
      <div class="share-preview" data-testid="share-chat-preview">
        <span class="option-icon icon_chat"></span>
        <div>
          <strong data-testid="chat-title">{title}</strong>
          {#if summary}<small>{summary}</small>{/if}
        </div>
      </div>
    </SettingsCard>
  {:else}
    <SettingsCard>
      <div class="generated" data-testid="chat-settings-share-generated">
        <SettingsInfoBox type="success">Share link created. Auto expire: {autoExpireEnabled ? '10 minutes' : 'never'}.</SettingsInfoBox>
      </div>
      <div class="generated-actions" data-testid="share-short-link-section">
      <SettingsItem type="action" icon="subsetting_icon copy" title={isCopied ? 'Copied' : 'Copy to clipboard'} data-testid="share-copy-link" onClick={() => void copyGeneratedLink()} />
      <div data-testid="share-short-link-copy" class="short-link-copy">
        <span data-testid="share-short-link-url">{generatedLink}</span>
      </div>
      <SettingsItem type="action" icon="subsetting_icon camera" title={showQr ? 'Hide QR code' : 'Show QR code'} data-testid={showQr ? 'chat-settings-share-hide-qr' : 'chat-settings-share-show-qr'} onClick={() => { showQr = !showQr; }} />
      {#if showQr}
        <div class="qr-code" data-testid="chat-settings-share-qr">
          <img src={qrCodeImageUrl} alt="Share QR code" />
        </div>
      {/if}
      <SettingsItem type="action" icon="subsetting_icon copy" title={showUrl ? 'Hide URL' : 'Show URL'} data-testid={showUrl ? 'chat-settings-share-hide-url' : 'chat-settings-share-show-url'} onClick={() => { showUrl = !showUrl; }} />
      {#if showUrl}
        <div class="url-box" data-testid="chat-settings-share-url" data-share-url-kind={generatedLink === generatedLongLink ? 'long' : 'short'}>{generatedLink}</div>
      {/if}
      {#if shortLinkError}
        <p class="share-error" data-testid="share-short-link-error">{shortLinkError}</p>
      {/if}
      <SettingsItem type="action" icon="subsetting_icon delete" title="Stop sharing" data-testid="chat-settings-share-stop" onClick={() => void stopSharing()} />
      </div>
    </SettingsCard>
    <SettingsDivider spacing="sm" />
    <SettingsCard>
      <SettingsItem type="action" icon="subsetting_icon download" title="Download chat" data-testid="chat-settings-share-download-chat" onClick={() => void downloadChat()} />
      <SettingsItem type="action" icon="subsetting_icon files" title="Download chat zip" data-testid="chat-settings-share-download-zip" onClick={() => void downloadChatZip()} />
    </SettingsCard>
  {/if}
</section>

<style>
  .chat-share {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-4);
  }

  .share-preview {
    display: grid;
    grid-template-columns: 3.25rem 1fr;
    gap: var(--spacing-4);
    align-items: center;
    min-height: 3.25rem;
    color: var(--color-primary);
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

  .generated-actions {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-3);
  }

  .qr-code {
    display: flex;
    justify-content: center;
    padding: var(--spacing-4);
  }

  .share-error {
    color: var(--color-warning, #a16207);
  }
</style>
