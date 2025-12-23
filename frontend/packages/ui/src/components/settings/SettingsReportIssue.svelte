<!--
    SettingsReportIssue Component
    
    This component allows users (including non-authenticated users) to report issues.
    The form includes:
    - Issue title (required)
    - Issue description (optional)
    - Chat or embed URL (optional)
    - Reminder about Signal group for discussion/screenshots
-->
<script lang="ts">
    import { text, notificationStore, activeChatStore, activeEmbedStore } from '@repo/ui';
    import { getApiEndpoint } from '../../config/api';
    import { externalLinks } from '../../config/links';
    import InputWarning from '../common/InputWarning.svelte';
    import { onMount } from 'svelte';
    import { isPublicChat } from '../../demo_chats/convertToChat';
    
    // Form state
    let issueTitle = $state('');
    let issueDescription = $state('');
    let chatOrEmbedUrl = $state('');
    let isSubmitting = $state(false);
    let successMessage = $state('');
    let errorMessage = $state('');

    // Device information (collected for debugging purposes)
    let deviceInfo = $state({
        userAgent: '',
        viewportWidth: 0,
        viewportHeight: 0,
        isTouchEnabled: false
    });
    
    // Input references for warnings
    let titleInput = $state<HTMLInputElement>();
    let descriptionInput = $state<HTMLTextAreaElement>();
    let urlInput = $state<HTMLInputElement>();
    
    // Validation state
    let titleError = $state('');
    let descriptionError = $state('');
    let urlError = $state('');
    let showTitleWarning = $state(false);
    let showDescriptionWarning = $state(false);
    let showUrlWarning = $state(false);
    
    /**
     * Validate URL format - must be a shared chat or embed URL
     * Valid formats:
     * - /share/chat/{chatId}#key={blob}
     * - /share/embed/{embedId}#key={blob}
     * - /#chat-id={chatId} (for public chats)
     */
    function validateUrl(url: string): boolean {
        if (!url || !url.trim()) {
            // URL is optional, so empty is valid
            return true;
        }
        
        const trimmedUrl = url.trim();
        
        // Check if it's a public chat link format
        if (trimmedUrl.includes('#chat-id=')) {
            return true;
        }
        
        // Check if it's a shared chat or embed URL with key parameter
        // Must contain '/share/chat/' or '/share/embed' AND 'key=' in the URL
        const hasShareChat = trimmedUrl.includes('/share/chat/');
        const hasShareEmbed = trimmedUrl.includes('/share/embed');
        const hasKey = trimmedUrl.includes('key=');
        
        if ((hasShareChat || hasShareEmbed) && hasKey) {
            return true;
        }
        
        return false;
    }
    
    /**
     * Validate form fields
     */
    function validateForm(): boolean {
        let isValid = true;
        
        // Validate title
        if (!issueTitle || !issueTitle.trim()) {
            titleError = $text('settings.report_issue.title_required.text');
            showTitleWarning = true;
            isValid = false;
        } else if (issueTitle.trim().length < 3) {
            titleError = $text('settings.report_issue.title_too_short.text');
            showTitleWarning = true;
            isValid = false;
        } else {
            titleError = '';
            showTitleWarning = false;
        }
        
        // Validate description (optional - no validation needed, any length is acceptable)
        descriptionError = '';
        showDescriptionWarning = false;
        
        // Validate URL if provided
        if (chatOrEmbedUrl && chatOrEmbedUrl.trim()) {
            if (!validateUrl(chatOrEmbedUrl)) {
                urlError = $text('settings.report_issue.url_invalid.text');
                showUrlWarning = true;
                isValid = false;
            } else {
                urlError = '';
                showUrlWarning = false;
            }
        } else {
            urlError = '';
            showUrlWarning = false;
        }
        
        return isValid;
    }
    
    /**
     * Auto-generate share URL for current chat or embed when opened from ActiveChat
     */
    async function autoGenerateShareUrl() {
        // Check if URL is already filled (user may have manually entered it)
        if (chatOrEmbedUrl && chatOrEmbedUrl.trim()) {
            return;
        }
        
        try {
            // Check for active embed first
            const activeEmbedId = $activeEmbedStore;
            if (activeEmbedId) {
                console.debug('[SettingsReportIssue] Auto-generating share URL for embed:', activeEmbedId);
                try {
                    const { generateEmbedShareKeyBlob } = await import('../../services/embedShareEncryption');
                    const encryptedBlob = await generateEmbedShareKeyBlob(activeEmbedId, 0, undefined);
                    const baseUrl = window.location.origin;
                    chatOrEmbedUrl = `${baseUrl}/share/embed/${activeEmbedId}#key=${encryptedBlob}`;
                    console.debug('[SettingsReportIssue] Auto-generated embed share URL:', chatOrEmbedUrl);
                    return;
                } catch (error) {
                    console.warn('[SettingsReportIssue] Failed to generate embed share URL:', error);
                    // Continue to check for chat
                }
            }
            
            // Check for active chat
            const activeChatId = $activeChatStore;
            if (activeChatId) {
                console.debug('[SettingsReportIssue] Auto-generating share URL for chat:', activeChatId);
                
                // For public chats, use simple format
                if (isPublicChat(activeChatId)) {
                    const baseUrl = window.location.origin;
                    chatOrEmbedUrl = `${baseUrl}/#chat-id=${activeChatId}`;
                    console.debug('[SettingsReportIssue] Auto-generated public chat share URL:', chatOrEmbedUrl);
                    return;
                }
                
                // For private chats, generate encrypted share link
                try {
                    const { chatDB } = await import('../../services/db');
                    const chatKey = chatDB.getOrGenerateChatKey(activeChatId);
                    
                    if (chatKey) {
                        // Convert chat key to base64 if needed
                        const chatKeyBase64 = chatKey instanceof Uint8Array 
                            ? btoa(String.fromCharCode(...chatKey))
                            : chatKey;
                        
                        const { generateShareKeyBlob } = await import('../../services/shareEncryption');
                        const encryptedBlob = await generateShareKeyBlob(
                            activeChatId,
                            chatKeyBase64,
                            0, // No expiration
                            undefined // No password
                        );
                        
                        const baseUrl = window.location.origin;
                        chatOrEmbedUrl = `${baseUrl}/share/chat/${activeChatId}#key=${encryptedBlob}`;
                        console.debug('[SettingsReportIssue] Auto-generated chat share URL:', chatOrEmbedUrl);
                    }
                } catch (error) {
                    console.warn('[SettingsReportIssue] Failed to generate chat share URL:', error);
                }
            }
        } catch (error) {
            console.error('[SettingsReportIssue] Error auto-generating share URL:', error);
        }
    }
    
    /**
     * SECURITY: Sanitize text input by removing HTML tags and escaping special characters
     * This is a defense-in-depth measure - the backend also sanitizes all inputs.
     * 
     * @param text - The text to sanitize
     * @returns Sanitized text with HTML tags removed
     */
    function sanitizeTextInput(text: string): string {
        if (!text) return '';
        
        // Remove HTML tags using a simple regex (defense-in-depth)
        // The backend will do proper HTML escaping, but we remove tags here too
        let sanitized = text.replace(/<[^>]*>/g, '');
        
        // Trim whitespace
        sanitized = sanitized.trim();
        
        return sanitized;
    }
    
    /**
     * Collect device information for debugging purposes
     */
    function collectDeviceInfo() {
        return {
            userAgent: navigator.userAgent || '',
            viewportWidth: window.innerWidth || 0,
            viewportHeight: window.innerHeight || 0,
            isTouchEnabled: 'ontouchstart' in window || navigator.maxTouchPoints > 0
        };
    }

    /**
     * Handle form submission
     */
    async function handleSubmit() {
        // Reset messages
        successMessage = '';
        errorMessage = '';
        
        // Validate form
        if (!validateForm()) {
            // Focus first invalid field
            if (titleError && titleInput) {
                titleInput.focus();
            } else if (descriptionError && descriptionInput) {
                descriptionInput.focus();
            }
            return;
        }
        
        isSubmitting = true;
        
        try {
            // SECURITY: Sanitize inputs before sending to backend
            // The backend will also sanitize, but this provides defense-in-depth
            const sanitizedTitle = sanitizeTextInput(issueTitle);
            // Description is optional - send null if empty, otherwise sanitize
            const sanitizedDescription = issueDescription.trim()
                ? sanitizeTextInput(issueDescription)
                : null;
            const sanitizedUrl = chatOrEmbedUrl.trim() || null;

            // Collect current device information for debugging purposes
            const currentDeviceInfo = collectDeviceInfo();

            const response = await fetch(getApiEndpoint('/v1/settings/issues'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'Origin': window.location.origin
                },
                body: JSON.stringify({
                    title: sanitizedTitle,
                    description: sanitizedDescription,
                    chat_or_embed_url: sanitizedUrl,
                    device_info: currentDeviceInfo
                }),
                credentials: 'include'
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                // Show success message
                successMessage = data.message || $text('settings.report_issue_success.text');
                
                // Show notification
                notificationStore.success(
                    $text('settings.report_issue_success.text'),
                    5000
                );
                
                // Reset form
                issueTitle = '';
                issueDescription = '';
                chatOrEmbedUrl = '';
                titleError = '';
                descriptionError = '';
                showTitleWarning = false;
                showDescriptionWarning = false;
            } else {
                // Show error message from API or default error
                errorMessage = data.message || data.detail || $text('settings.report_issue_error.text');
                notificationStore.error(
                    errorMessage,
                    10000
                );
            }
        } catch (error) {
            console.error('[SettingsReportIssue] Error submitting issue:', error);
            errorMessage = $text('settings.report_issue_error.text');
            notificationStore.error(
                errorMessage,
                10000
            );
        } finally {
            isSubmitting = false;
        }
    }
    
    /**
     * Handle Enter key press in title input
     */
    function handleTitleKeyPress(event: KeyboardEvent) {
        if (event.key === 'Enter' && !isSubmitting) {
            event.preventDefault();
            if (descriptionInput) {
                descriptionInput.focus();
            }
        }
    }
    
    /**
     * Check if form is valid
     * Description is optional with no minimum length requirement
     */
    let isFormValid = $derived(
        issueTitle.trim().length >= 3 &&
        (!chatOrEmbedUrl.trim() || validateUrl(chatOrEmbedUrl)) &&
        !isSubmitting
    );
    
    /**
     * Validate URL on input change
     */
    function handleUrlInput() {
        if (chatOrEmbedUrl && chatOrEmbedUrl.trim()) {
            if (!validateUrl(chatOrEmbedUrl)) {
                urlError = $text('settings.report_issue.url_invalid.text');
                showUrlWarning = true;
            } else {
                urlError = '';
                showUrlWarning = false;
            }
        } else {
            urlError = '';
            showUrlWarning = false;
        }
    }
    
    // Auto-generate share URL and collect initial device info when component mounts
    onMount(() => {
        // Small delay to ensure stores are initialized
        setTimeout(() => {
            autoGenerateShareUrl();
            // Collect initial device info to show in the form
            deviceInfo = collectDeviceInfo();
        }, 100);
    });
</script>

<div class="report-issue-settings">
    <p>{$text('settings.report_issue.description.text')}</p>
    
    <!-- Issue Report Form -->
    <div class="report-issue-form">
        <!-- Title Input -->
        <div class="input-group">
            <label for="issue-title">{$text('settings.report_issue.title_label.text')}</label>
            <div class="input-wrapper">
                <input
                    id="issue-title"
                    bind:this={titleInput}
                    type="text"
                    placeholder={$text('settings.report_issue.title_placeholder.text')}
                    bind:value={issueTitle}
                    onkeypress={handleTitleKeyPress}
                    disabled={isSubmitting}
                    class:error={!!titleError}
                    aria-label={$text('settings.report_issue.title_label.text')}
                    required
                />
                {#if showTitleWarning && titleError}
                    <InputWarning
                        message={titleError}
                        target={titleInput}
                    />
                {/if}
            </div>
        </div>
        
        <!-- Description Input -->
        <div class="input-group">
            <label for="issue-description">{$text('settings.report_issue.description_label.text')}</label>
            <div class="input-wrapper">
                <textarea
                    id="issue-description"
                    bind:this={descriptionInput}
                    placeholder={$text('settings.report_issue.description_placeholder.text')}
                    bind:value={issueDescription}
                    disabled={isSubmitting}
                    class:error={!!descriptionError}
                    aria-label={$text('settings.report_issue.description_label.text')}
                    rows="5"
                ></textarea>
                {#if showDescriptionWarning && descriptionError}
                    <InputWarning
                        message={descriptionError}
                        target={descriptionInput}
                    />
                {/if}
            </div>
        </div>
        
        <!-- Shared Chat or Embed URL Input (Optional) -->
        <div class="input-group">
            <label for="chat-embed-url">{$text('settings.report_issue.url_label.text')}</label>
            <div class="input-wrapper">
                <input
                    id="chat-embed-url"
                    bind:this={urlInput}
                    type="url"
                    placeholder={$text('settings.report_issue.url_placeholder.text')}
                    bind:value={chatOrEmbedUrl}
                    oninput={handleUrlInput}
                    disabled={isSubmitting}
                    class:error={!!urlError}
                    aria-label={$text('settings.report_issue.url_label.text')}
                />
                {#if showUrlWarning && urlError}
                    <InputWarning
                        message={urlError}
                        target={urlInput}
                    />
                {/if}
            </div>
        </div>
        
        <!-- Signal Group Reminder -->
        <div class="signal-reminder">
            <p class="reminder-text">
                {$text('settings.report_issue.signal_reminder.text')}{' '}
                <a
                    href={externalLinks.signal}
                    target="_blank"
                    rel="noopener noreferrer"
                    class="signal-link"
                >
                    {$text('settings.report_issue.signal_link.text')}
                </a>
            </p>
        </div>
        
        <!-- Submit Button -->
        <div class="button-container">
            <button
                onclick={handleSubmit}
                disabled={!isFormValid || isSubmitting}
                aria-label={$text('settings.report_issue.submit_button.text')}
            >
                {#if isSubmitting}
                    {$text('settings.report_issue.submitting.text')}
                {:else}
                    {$text('settings.report_issue.submit_button.text')}
                {/if}
            </button>
        </div>
        
        <!-- Success message -->
        {#if successMessage}
            <div class="message success-message" role="alert">
                {successMessage}
            </div>
        {/if}
        
        <!-- Error message -->
        {#if errorMessage}
            <div class="message error-message" role="alert">
                {errorMessage}
            </div>
        {/if}

        <!-- Device Information Notice -->
        <div class="device-info-notice">
            <h4>{$text('settings.report_issue.device_info.heading.text')}</h4>
            <p class="notice-text">
                {$text('settings.report_issue.device_info.description.text')}
            </p>
            <ul class="device-info-list">
                <li><strong>{$text('settings.report_issue.device_info.browser_os_label.text')}:</strong> {deviceInfo.userAgent || 'Loading...'}</li>
                <li><strong>{$text('settings.report_issue.device_info.screen_size_label.text')}:</strong> {deviceInfo.viewportWidth || 0} × {deviceInfo.viewportHeight || 0} pixels</li>
                <li><strong>{$text('settings.report_issue.device_info.touch_support_label.text')}:</strong> {deviceInfo.isTouchEnabled ? 'Yes' : 'No'}</li>
            </ul>
            <p class="privacy-notice">
                <strong>{$text('settings.report_issue.device_info.privacy_label.text')}:</strong>
                {$text('settings.report_issue.device_info.privacy_body.text')}
            </p>
        </div>
    </div>
</div>

<style>
    .report-issue-settings {
        margin: 20px;
    }
    
    .report-issue-form {
        display: flex;
        flex-direction: column;
        gap: 16px;
    }
    
    .input-group {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }
    
    .input-group label {
        font-size: 14px;
        font-weight: 500;
        color: var(--color-font-primary);
    }
    
    .input-wrapper {
        position: relative;
        width: 100%;
    }
    
    .input-wrapper input,
    .input-wrapper textarea {
        width: 100%;
        padding: 12px;
        border: 1px solid var(--color-grey-30);
        border-radius: 8px;
        font-size: 14px;
        font-family: inherit;
        background-color: var(--color-grey-20);
        color: var(--color-font-primary);
        transition: border-color 0.2s ease;
    }
    
    .input-wrapper input:focus,
    .input-wrapper textarea:focus {
        outline: none;
        border-color: var(--color-primary);
    }
    
    .input-wrapper input.error,
    .input-wrapper textarea.error {
        border-color: var(--color-error, #e74c3c);
    }
    
    .input-wrapper input:disabled,
    .input-wrapper textarea:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }
    
    .input-wrapper textarea {
        resize: vertical;
        min-height: 100px;
    }
    
    .signal-reminder {
        padding: 12px;
        background-color: var(--color-info-light, #e3f2fd);
        border: 1px solid var(--color-info, #2196f3);
        border-radius: 8px;
        margin-top: 8px;
    }
    
    .reminder-text {
        font-size: 13px;
        color: var(--color-info-dark, #1565c0);
        margin: 0;
        line-height: 1.5;
    }
    
    .signal-link {
        color: var(--color-info-dark, #1565c0);
        text-decoration: underline;
        font-weight: 500;
        transition: opacity 0.2s ease;
    }
    
    .signal-link:hover {
        opacity: 0.8;
    }
    
    .signal-link:focus {
        outline: 2px solid var(--color-primary);
        outline-offset: 2px;
        border-radius: 2px;
    }
    
    .button-container {
        margin-top: 8px;
    }
    
    .button-container button {
        width: 100%;
        padding: 12px;
        background-color: var(--color-button-primary);
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
    }
    
    .button-container button:hover:not(:disabled) {
        transform: scale(1.02);
    }
    
    .button-container button:active:not(:disabled) {
        transform: scale(0.98);
    }
    
    .button-container button:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }
    
    .message {
        padding: 12px;
        border-radius: 8px;
        font-size: 14px;
        line-height: 1.4;
    }
    
    .success-message {
        background-color: var(--color-success-light, #e8f5e9);
        color: var(--color-success-dark, #2e7d32);
        border: 1px solid var(--color-success, #4caf50);
    }
    
    .error-message {
        background-color: var(--color-error-light, #ffebee);
        color: var(--color-error-dark, #c62828);
        border: 1px solid var(--color-error, #f44336);
    }

    .device-info-notice {
        padding: 16px;
        background-color: var(--color-info-light, #e3f2fd);
        border: 1px solid var(--color-info, #2196f3);
        border-radius: 8px;
        margin-top: 8px;
        margin-bottom: 16px;
    }

    .device-info-notice h4 {
        margin: 0 0 12px 0;
        font-size: 16px;
        font-weight: 600;
        color: var(--color-info-dark, #1565c0);
    }

    .notice-text {
        font-size: 14px;
        color: var(--color-info-dark, #1565c0);
        margin: 0 0 12px 0;
        line-height: 1.4;
    }

    .device-info-list {
        margin: 12px 0;
        padding-left: 20px;
        font-size: 13px;
        color: var(--color-info-dark, #1565c0);
        line-height: 1.5;
    }

    .device-info-list li {
        margin-bottom: 6px;
        word-break: break-all;
    }

    .privacy-notice {
        font-size: 13px;
        color: var(--color-info-dark, #1565c0);
        margin: 12px 0 0 0;
        line-height: 1.4;
        font-style: italic;
        padding-top: 8px;
        border-top: 1px solid var(--color-info, #2196f3);
    }
</style>
