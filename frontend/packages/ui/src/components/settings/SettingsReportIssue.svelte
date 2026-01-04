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
    import { logCollector } from '../../services/logCollector';
    
    // Form state
    let issueTitle = $state('');
    let issueDescription = $state('');
    let chatOrEmbedUrl = $state('');
    let contactEmail = $state('');
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
    let emailInput = $state<HTMLInputElement>();
    
    // Validation state
    let titleError = $state('');
    let descriptionError = $state('');
    let urlError = $state('');
    let emailError = $state('');
    let showTitleWarning = $state(false);
    let showDescriptionWarning = $state(false);
    let showUrlWarning = $state(false);
    let showEmailWarning = $state(false);
    
    /**
     * Validate email format - must be a valid email address
     * Email is optional, so empty string is valid
     */
    function validateEmail(email: string): boolean {
        if (!email || !email.trim()) {
            // Email is optional, so empty is valid
            return true;
        }
        
        const trimmedEmail = email.trim();
        // Basic email validation regex
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return emailRegex.test(trimmedEmail);
    }
    
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
        
        // Validate description (optional - but if provided, must be at least 10 characters)
        if (issueDescription && issueDescription.trim()) {
            if (issueDescription.trim().length < 10) {
                descriptionError = $text('settings.report_issue.description_too_short.text');
                showDescriptionWarning = true;
                isValid = false;
            } else {
                descriptionError = '';
                showDescriptionWarning = false;
            }
        } else {
            // Description is optional - empty is valid
            descriptionError = '';
            showDescriptionWarning = false;
        }
        
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
        
        // Validate email if provided (optional field)
        if (contactEmail && contactEmail.trim()) {
            if (!validateEmail(contactEmail)) {
                emailError = $text('settings.report_issue.email_invalid.text');
                showEmailWarning = true;
                isValid = false;
            } else {
                emailError = '';
                showEmailWarning = false;
            }
        } else {
            emailError = '';
            showEmailWarning = false;
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
            } else if (urlError && urlInput) {
                urlInput.focus();
            } else if (emailError && emailInput) {
                emailInput.focus();
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
            // Email is optional - send null if empty, otherwise sanitize (email doesn't need HTML sanitization, but trim it)
            const sanitizedEmail = contactEmail.trim() || null;

            // Collect current device information for debugging purposes
            const currentDeviceInfo = collectDeviceInfo();

            // Collect console logs for debugging (last 100 lines)
            const consoleLogs = logCollector.getLogsAsText(100);

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
                    contact_email: sanitizedEmail,
                    device_info: currentDeviceInfo,
                    console_logs: consoleLogs
                }),
                credentials: 'include'
            });
            
            // Parse response - handle both JSON and non-JSON responses
            // Define response data type
            interface ApiResponse {
                success?: boolean;
                message?: string;
                detail?: Array<{
                    type: string;
                    loc: (string | number)[];
                    msg: string;
                    input?: unknown;
                    ctx?: Record<string, unknown>;
                }> | string;
            }
            
            let data: ApiResponse;
            const defaultErrorMessage = $text('settings.report_issue_error.text');
            
            try {
                const contentType = response.headers.get('content-type');
                if (contentType && contentType.includes('application/json')) {
                    data = await response.json();
                } else {
                    // Non-JSON response - create error object
                    const text = await response.text();
                    data = {
                        success: false,
                        message: text || defaultErrorMessage
                    };
                }
            } catch (parseError) {
                // Failed to parse response - create error object
                console.error('[SettingsReportIssue] Failed to parse response:', parseError);
                data = {
                    success: false,
                    message: defaultErrorMessage
                };
            }
            
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
                contactEmail = '';
                titleError = '';
                descriptionError = '';
                urlError = '';
                emailError = '';
                showTitleWarning = false;
                showDescriptionWarning = false;
                showUrlWarning = false;
                showEmailWarning = false;
            } else {
                // Handle FastAPI validation errors (422 status)
                // FastAPI returns validation errors in data.detail as an array
                if (response.status === 422 && Array.isArray(data.detail)) {
                    // Parse validation errors and map them to form fields
                    let hasFieldErrors = false;
                    
                    for (const error of data.detail) {
                        const fieldPath = error.loc || [];
                        const fieldName = fieldPath[fieldPath.length - 1]; // Get last element (field name)
                        const fieldErrorMessage = error.msg || '';
                        
                        // Map backend field names to frontend state
                        if (fieldName === 'title') {
                            titleError = fieldErrorMessage;
                            showTitleWarning = true;
                            hasFieldErrors = true;
                            if (titleInput) {
                                titleInput.focus();
                            }
                        } else if (fieldName === 'description') {
                            descriptionError = fieldErrorMessage;
                            showDescriptionWarning = true;
                            hasFieldErrors = true;
                            if (descriptionInput) {
                                descriptionInput.focus();
                            }
                        } else if (fieldName === 'chat_or_embed_url') {
                            urlError = fieldErrorMessage;
                            showUrlWarning = true;
                            hasFieldErrors = true;
                            if (urlInput) {
                                urlInput.focus();
                            }
                        } else if (fieldName === 'contact_email') {
                            emailError = fieldErrorMessage;
                            showEmailWarning = true;
                            hasFieldErrors = true;
                            if (emailInput) {
                                emailInput.focus();
                            }
                        }
                    }
                    
                    // If we mapped field errors, show a general error message too
                    if (hasFieldErrors) {
                        errorMessage = $text('settings.report_issue_error.text');
                        notificationStore.error(
                            errorMessage,
                            10000
                        );
                    } else {
                        // Fallback: show first error message
                        errorMessage = data.detail[0]?.msg || $text('settings.report_issue_error.text');
                        notificationStore.error(
                            errorMessage,
                            10000
                        );
                    }
                } else {
                    // Handle other API errors (non-validation errors)
                    const apiErrorMessage = data.message || (typeof data.detail === 'string' ? data.detail : $text('settings.report_issue_error.text'));
                    errorMessage = apiErrorMessage;
                    notificationStore.error(
                        errorMessage,
                        10000
                    );
                }
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
     * Description is optional but must be at least 10 characters if provided
     * Email is optional but must be valid if provided
     */
    let isFormValid = $derived(
        issueTitle.trim().length >= 3 &&
        (!issueDescription.trim() || issueDescription.trim().length >= 10) &&
        (!chatOrEmbedUrl.trim() || validateUrl(chatOrEmbedUrl)) &&
        (!contactEmail.trim() || validateEmail(contactEmail)) &&
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
    
    /**
     * Validate description on input change
     */
    function handleDescriptionInput() {
        if (issueDescription && issueDescription.trim()) {
            if (issueDescription.trim().length < 10) {
                descriptionError = $text('settings.report_issue.description_too_short.text');
                showDescriptionWarning = true;
            } else {
                descriptionError = '';
                showDescriptionWarning = false;
            }
        } else {
            // Description is optional - empty is valid
            descriptionError = '';
            showDescriptionWarning = false;
        }
    }
    
    /**
     * Validate email on input change
     */
    function handleEmailInput() {
        if (contactEmail && contactEmail.trim()) {
            if (!validateEmail(contactEmail)) {
                emailError = $text('settings.report_issue.email_invalid.text');
                showEmailWarning = true;
            } else {
                emailError = '';
                showEmailWarning = false;
            }
        } else {
            emailError = '';
            showEmailWarning = false;
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
                    oninput={handleDescriptionInput}
                    disabled={isSubmitting}
                    class:error={!!descriptionError}
                    aria-label={$text('settings.report_issue.description_label.text')}
                    rows="5"
                ></textarea>
                {#if showDescriptionWarning && descriptionError}
                    <InputWarning
                        message={descriptionError}
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
                    />
                {/if}
            </div>
        </div>
        
        <!-- Contact Email Input (Optional) -->
        <div class="input-group">
            <label for="contact-email">{$text('settings.report_issue.email_label.text')}</label>
            <div class="input-wrapper">
                <input
                    id="contact-email"
                    bind:this={emailInput}
                    type="email"
                    placeholder={$text('settings.report_issue.email_placeholder.text')}
                    bind:value={contactEmail}
                    oninput={handleEmailInput}
                    disabled={isSubmitting}
                    class:error={!!emailError}
                    aria-label={$text('settings.report_issue.email_label.text')}
                />
                {#if showEmailWarning && emailError}
                    <InputWarning
                        message={emailError}
                    />
                {/if}
            </div>
            <p class="input-hint">{$text('settings.report_issue.email_hint.text')}</p>
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
    
    .input-hint {
        font-size: 12px;
        color: var(--color-font-secondary, #666);
        margin: 4px 0 0 0;
        line-height: 1.4;
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
