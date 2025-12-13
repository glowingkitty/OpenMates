<script lang="ts">
    import { text } from '@repo/ui';
    import { hiddenChatStore } from '../../stores/hiddenChatStore';
    import { notificationStore } from '../../stores/notificationStore';
    import { onMount } from 'svelte';

    interface Props {
        show?: boolean;
        onClose?: () => void;
        onUnlock?: () => void;
        isFirstTime?: boolean; // True if setting code for first time (not used anymore, kept for backward compatibility)
        chatIdToHide?: string | null; // Chat ID to hide after unlock (if provided, encrypt chat first, then unlock)
    }

    let {
        show = false,
        onClose = () => {},
        onUnlock = () => {},
        isFirstTime = false,
        chatIdToHide = null
    }: Props = $props();

    let code = $state('');
    let confirmCode = $state(''); // For first-time setup
    let errorMessage = $state('');
    let isLoading = $state(false);
    let codeInput = $state<HTMLInputElement>();
    let confirmCodeInput = $state<HTMLInputElement>();

    // Get lockout state from store
    let lockoutState = $derived($hiddenChatStore);

    // Validate code format (4-6 digits)
    function isValidCode(c: string): boolean {
        return /^\d{4,6}$/.test(c);
    }

    // Handle code input (only allow digits, max 6)
    function handleCodeInput(event: Event) {
        const target = event.target as HTMLInputElement;
        let value = target.value.replace(/\D/g, ''); // Remove non-digits
        if (value.length > 6) {
            value = value.slice(0, 6);
        }
        code = value;
        errorMessage = '';
    }

    // Handle confirm code input (only allow digits, max 6)
    function handleConfirmCodeInput(event: Event) {
        const target = event.target as HTMLInputElement;
        let value = target.value.replace(/\D/g, ''); // Remove non-digits
        if (value.length > 6) {
            value = value.slice(0, 6);
        }
        confirmCode = value;
        errorMessage = '';
    }

    // Handle form submission
    async function handleSubmit(event: Event) {
        event.preventDefault();
        errorMessage = '';
        isLoading = true;

        try {
            // Check if locked out
            if (lockoutState.isLockedOut) {
                errorMessage = $text('chats.hidden_chats.lockout_message.text', {
                    default: `Too many failed attempts. Please wait ${lockoutState.lockoutRemainingSeconds} seconds.`
                });
                isLoading = false;
                return;
            }

            // First-time setup: require confirmation
            if (isFirstTime) {
                if (!isValidCode(code)) {
                    errorMessage = $text('chats.hidden_chats.invalid_code_format.text', {
                        default: 'Please enter a 4-6 digit code'
                    });
                    isLoading = false;
                    return;
                }

                if (code !== confirmCode) {
                    errorMessage = $text('chats.hidden_chats.codes_dont_match.text', {
                        default: 'Codes do not match'
                    });
                    isLoading = false;
                    confirmCode = '';
                    confirmCodeInput?.focus();
                    return;
                }
            } else {
                // Unlock: validate code format
                if (!isValidCode(code)) {
                    errorMessage = $text('chats.hidden_chats.invalid_code_format.text', {
                        default: 'Please enter a 4-6 digit code'
                    });
                    isLoading = false;
                    return;
                }
            }

            // If we're hiding a chat, encrypt it first, then unlock
            // This ensures unlock succeeds even if no existing chats are encrypted with this code
            let encryptedChatKeyForVerification: string | undefined = undefined;
            
            if (chatIdToHide) {
                // Import services
                const { hiddenChatService } = await import('../../services/hiddenChatService');
                const { chatDB } = await import('../../services/db');
                
                // Get the chat to hide
                const chatToHide = await chatDB.getChat(chatIdToHide);
                if (!chatToHide) {
                    errorMessage = $text('chats.hidden_chats.unlock_error.text', {
                        default: 'Error: Chat not found'
                    });
                    isLoading = false;
                    return;
                }
                
                // Get the chat key (decrypt from encrypted_chat_key if needed)
                let chatKey = chatDB.getChatKey(chatIdToHide);
                if (!chatKey && chatToHide.encrypted_chat_key) {
                    const { decryptChatKeyWithMasterKey } = await import('../../services/cryptoService');
                    try {
                        chatKey = await decryptChatKeyWithMasterKey(chatToHide.encrypted_chat_key);
                    } catch (error) {
                        console.error('[HiddenChatUnlock] Error decrypting chat key for hiding:', error);
                        errorMessage = $text('chats.hidden_chats.unlock_error.text', {
                            default: 'Error decrypting chat key'
                        });
                        isLoading = false;
                        return;
                    }
                }
                
                if (!chatKey) {
                    errorMessage = $text('chats.hidden_chats.unlock_error.text', {
                        default: 'Error: Chat key not found'
                    });
                    isLoading = false;
                    return;
                }
                
                // Encrypt chat key with the code (this doesn't unlock, just encrypts)
                const encryptedChatKey = await hiddenChatService.encryptChatKeyWithCode(chatKey, code);
                if (!encryptedChatKey) {
                    errorMessage = $text('chats.hidden_chats.unlock_error.text', {
                        default: 'Error encrypting chat'
                    });
                    isLoading = false;
                    return;
                }
                
                // Store for verification during unlock
                encryptedChatKeyForVerification = encryptedChatKey;
                
                // Update chat in database
                const updatedChat = {
                    ...chatToHide,
                    encrypted_chat_key: encryptedChatKey,
                    is_hidden: true
                };
                await chatDB.updateChat(updatedChat);
                
                // Sync to server
                const { chatSyncService } = await import('../../services/chatSyncService');
                await chatSyncService.sendUpdateEncryptedChatKey(chatIdToHide, encryptedChatKey);
            }
            
            // Attempt to unlock (after encrypting chat if needed)
            // If we encrypted a chat, pass the encrypted chat key so unlock can verify it even if getAllChats() hasn't picked it up yet
            const result = await hiddenChatStore.unlock(code, encryptedChatKeyForVerification);
            
            if (result.success) {
                // Show success notification
                if (chatIdToHide) {
                    notificationStore.success($text('chats.hidden_chats.unlocked_and_hiding.text', {
                        default: 'Chat hidden and unlocked successfully'
                    }));
                } else {
                    notificationStore.success($text('chats.hidden_chats.unlocked.text', {
                        default: 'Hidden chats unlocked successfully'
                    }));
                }
                
                onUnlock();
                // Reset form
                code = '';
                confirmCode = '';
                onClose();
            } else {
                // Show appropriate error message based on whether any chats were decrypted
                if (result.decryptedCount === 0) {
                    errorMessage = $text('chats.hidden_chats.no_hidden_chats_unlocked.text', {
                        default: 'No hidden chats unlocked. The code may be incorrect or no chats are encrypted with this code.'
                    });
            } else {
                errorMessage = $text('chats.hidden_chats.incorrect_code.text', {
                    default: 'Incorrect code. Please try again.'
                });
                }
                code = '';
                confirmCode = '';
                codeInput?.focus();
            }
        } catch (error: any) {
            console.error('[HiddenChatUnlock] Error unlocking:', error);
            errorMessage = error.message || $text('chats.hidden_chats.unlock_error.text', {
                default: 'An error occurred. Please try again.'
            });
        } finally {
            isLoading = false;
        }
    }

    // Handle close
    function handleClose() {
        code = '';
        confirmCode = '';
        errorMessage = '';
        onClose();
    }

    // Focus input when shown
    $effect(() => {
        if (show && codeInput) {
            // Small delay to ensure input is visible
            setTimeout(() => {
                codeInput?.focus();
            }, 100);
        }
    });

    // Handle escape key
    function handleKeydown(event: KeyboardEvent) {
        if (event.key === 'Escape') {
            handleClose();
        }
    }
</script>

{#if show}
    <div 
        class="hidden-chat-unlock-overlay" 
        role="presentation" 
        onclick={handleClose}
        onkeydown={handleKeydown}
    >
        <div 
            class="hidden-chat-unlock-modal" 
            role="dialog" 
            tabindex={-1}
            onclick={(e) => e.stopPropagation()}
        >
            <div class="modal-header">
                <h3>
                    {isFirstTime 
                        ? $text('chats.hidden_chats.set_code_title.text', { default: 'Set Hidden Chat Code' })
                        : $text('chats.hidden_chats.unlock_title.text', { default: 'Unlock Hidden Chats' })
                    }
                </h3>
                <button class="close-btn" onclick={handleClose}>✕</button>
            </div>

            <div class="modal-content">
                <p class="description">
                    {isFirstTime
                        ? $text('chats.hidden_chats.set_code_description.text', {
                            default: 'Enter a 4-6 digit code to protect your hidden chats. This code is separate from your login password.'
                        })
                        : $text('chats.hidden_chats.unlock_description.text', {
                            default: 'Enter your 4-6 digit code to unlock hidden chats.'
                        })
                    }
                </p>

                <form onsubmit={handleSubmit}>
                    <div class="input-group">
                        <label for="code-input">
                            {$text('chats.hidden_chats.code_label.text', { default: 'Code' })}
                        </label>
                        <input
                            id="code-input"
                            bind:this={codeInput}
                            type="text"
                            inputmode="numeric"
                            pattern="[0-9]*"
                            bind:value={code}
                            oninput={handleCodeInput}
                            placeholder="0000"
                            maxlength="6"
                            autocomplete="off"
                            class:error={!!errorMessage}
                            disabled={isLoading || lockoutState.isLockedOut}
                        />
                    </div>

                    {#if isFirstTime}
                        <div class="input-group">
                            <label for="confirm-code-input">
                                {$text('chats.hidden_chats.confirm_code_label.text', { default: 'Confirm Code' })}
                            </label>
                            <input
                                id="confirm-code-input"
                                bind:this={confirmCodeInput}
                                type="text"
                                inputmode="numeric"
                                pattern="[0-9]*"
                                bind:value={confirmCode}
                                oninput={handleConfirmCodeInput}
                                placeholder="0000"
                                maxlength="6"
                                autocomplete="off"
                                class:error={!!errorMessage}
                                disabled={isLoading || lockoutState.isLockedOut}
                            />
                        </div>
                    {/if}

                    {#if errorMessage}
                        <div class="error-message">
                            {errorMessage}
                        </div>
                    {/if}

                    {#if lockoutState.isLockedOut}
                        <div class="lockout-message">
                            {$text('chats.hidden_chats.lockout_message.text', {
                                default: `Too many failed attempts. Please wait ${lockoutState.lockoutRemainingSeconds} seconds.`
                            })}
                        </div>
                    {/if}

                    <div class="button-group">
                        <button
                            type="button"
                            class="button-secondary"
                            onclick={handleClose}
                            disabled={isLoading}
                        >
                            {$text('chats.hidden_chats.cancel.text', { default: 'Cancel' })}
                        </button>
                        <button
                            type="submit"
                            class="button-primary"
                            disabled={isLoading || !isValidCode(code) || (isFirstTime && code !== confirmCode) || lockoutState.isLockedOut}
                        >
                            {#if isLoading}
                                <span class="loading-spinner"></span>
                            {:else}
                                {isFirstTime
                                    ? $text('chats.hidden_chats.set_code_button.text', { default: 'Set Code' })
                                    : $text('chats.hidden_chats.unlock_button.text', { default: 'Unlock' })
                                }
                            {/if}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    </div>
{/if}

<style>
    .hidden-chat-unlock-overlay {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 10000;
        animation: fadeIn 0.2s ease-in-out;
    }

    @keyframes fadeIn {
        from {
            opacity: 0;
        }
        to {
            opacity: 1;
        }
    }

    .hidden-chat-unlock-modal {
        background: var(--color-grey-blue);
        border-radius: 12px;
        padding: 24px;
        max-width: 400px;
        width: 90%;
        max-height: 90vh;
        overflow-y: auto;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        animation: slideUp 0.2s ease-in-out;
    }

    @keyframes slideUp {
        from {
            transform: translateY(20px);
            opacity: 0;
        }
        to {
            transform: translateY(0);
            opacity: 1;
        }
    }

    .modal-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 20px;
    }

    .modal-header h3 {
        margin: 0;
        font-size: 20px;
        font-weight: 600;
        color: var(--color-text-primary);
    }

    .close-btn {
        all: unset;
        cursor: pointer;
        font-size: 24px;
        color: var(--color-grey-60);
        width: 32px;
        height: 32px;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 50%;
        transition: background-color 0.2s;
    }

    .close-btn:hover {
        background-color: var(--color-grey-20);
    }

    .modal-content {
        display: flex;
        flex-direction: column;
        gap: 20px;
    }

    .description {
        margin: 0;
        color: var(--color-grey-60);
        font-size: 14px;
        line-height: 1.5;
    }

    .input-group {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .input-group label {
        font-size: 14px;
        font-weight: 500;
        color: var(--color-text-primary);
    }

    .input-group input {
        all: unset;
        padding: 12px 16px;
        background: var(--color-grey-20);
        border-radius: 8px;
        font-size: 16px;
        color: var(--color-text-primary);
        border: 2px solid transparent;
        transition: border-color 0.2s;
        font-family: monospace;
        letter-spacing: 0.1em;
        text-align: center;
    }

    .input-group input:focus {
        border-color: var(--color-primary);
        outline: none;
    }

    .input-group input.error {
        border-color: #E80000;
    }

    .input-group input:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .error-message {
        padding: 12px;
        background: rgba(232, 0, 0, 0.1);
        border-radius: 8px;
        color: #E80000;
        font-size: 14px;
    }

    .lockout-message {
        padding: 12px;
        background: rgba(255, 193, 7, 0.1);
        border-radius: 8px;
        color: #FFC107;
        font-size: 14px;
        text-align: center;
    }

    .button-group {
        display: flex;
        gap: 12px;
        justify-content: flex-end;
    }

    .button-primary,
    .button-secondary {
        all: unset;
        padding: 12px 24px;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        transition: opacity 0.2s;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
    }

    .button-primary {
        background: var(--color-primary);
        color: white;
    }

    .button-primary:hover:not(:disabled) {
        opacity: 0.9;
    }

    .button-primary:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .button-secondary {
        background: var(--color-grey-20);
        color: var(--color-text-primary);
    }

    .button-secondary:hover:not(:disabled) {
        background: var(--color-grey-30);
    }

    .button-secondary:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .loading-spinner {
        width: 16px;
        height: 16px;
        border: 2px solid rgba(255, 255, 255, 0.3);
        border-top-color: white;
        border-radius: 50%;
        animation: spin 0.6s linear infinite;
    }

    @keyframes spin {
        to {
            transform: rotate(360deg);
        }
    }
</style>



