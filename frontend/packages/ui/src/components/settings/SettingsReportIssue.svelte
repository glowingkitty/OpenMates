<!--
    SettingsReportIssue Component
    
    This component allows users (including non-authenticated users) to report issues.
    The form includes:
    - Issue title (required)
    - Issue description (optional)
    - Toggle to share chat/embed with the report (optional)
    - Reminder about Signal group for discussion/screenshots
-->
<script lang="ts">
    import { text, notificationStore, activeChatStore, activeEmbedStore } from '@repo/ui';
    import { getApiEndpoint } from '../../config/api';
    import { externalLinks } from '../../config/links';
    import InputWarning from '../common/InputWarning.svelte';
    import Toggle from '../Toggle.svelte';
    import { onMount } from 'svelte';
    import { isPublicChat } from '../../demo_chats/convertToChat';
    import { logCollector } from '../../services/logCollector';
    import { reportIssueStore } from '../../stores/reportIssueStore';
    import { inspectChat } from '../../services/debugUtils';
    
    // Form state
    let issueTitle = $state('');
    let issueDescription = $state('');
    let shareChatEnabled = $state(true);
    let chatOrEmbedUrl = $state('');
    let contactEmail = $state('');
    let isSubmitting = $state(false);
    let successMessage = $state('');
    let errorMessage = $state('');
    let submittedIssueId = $state('');
    let issueIdCopied = $state(false);
    
    /**
     * Whether the current context has an active chat or embed that can be shared.
     * When false, the share toggle is hidden since there's nothing to share.
     */
    let hasActiveChatOrEmbed = $state(false);

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
    let emailInput = $state<HTMLInputElement>();
    
    // Validation state
    let titleError = $state('');
    let descriptionError = $state('');
    let emailError = $state('');
    let showTitleWarning = $state(false);
    let showDescriptionWarning = $state(false);
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
     * Validate form fields
     */
    function validateForm(): boolean {
        let isValid = true;
        
        // Validate title
        if (!issueTitle || !issueTitle.trim()) {
            titleError = $text('settings.report_issue.title_required');
            showTitleWarning = true;
            isValid = false;
        } else if (issueTitle.trim().length < 3) {
            titleError = $text('settings.report_issue.title_too_short');
            showTitleWarning = true;
            isValid = false;
        } else {
            titleError = '';
            showTitleWarning = false;
        }
        
        // Validate description (optional - but if provided, must be at least 10 characters)
        if (issueDescription && issueDescription.trim()) {
            if (issueDescription.trim().length < 10) {
                descriptionError = $text('settings.report_issue.description_too_short');
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
        
        // Validate email if provided (optional field)
        if (contactEmail && contactEmail.trim()) {
            if (!validateEmail(contactEmail)) {
                emailError = $text('settings.report_issue.email_invalid');
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
     * Auto-generate share URL for current chat or embed.
     * The URL is pre-generated so it's ready to include when the user enables the share toggle.
     * Also sets hasActiveChatOrEmbed to control toggle visibility.
     */
    async function autoGenerateShareUrl() {
        // Check if URL is already filled (e.g. from deep link or store)
        if (chatOrEmbedUrl && chatOrEmbedUrl.trim()) {
            hasActiveChatOrEmbed = true;
            return;
        }
        
        try {
            // Check for active embed first
            const activeEmbedId = $activeEmbedStore;
            if (activeEmbedId) {
                hasActiveChatOrEmbed = true;
                console.debug('[SettingsReportIssue] Auto-generating share URL for embed:', activeEmbedId);
                try {
                    const { generateEmbedShareKeyBlob } = await import('../../services/embedShareEncryption');
                    const encryptedBlob = await generateEmbedShareKeyBlob(activeEmbedId, 0, undefined);
                    const baseUrl = window.location.origin;
                    chatOrEmbedUrl = `${baseUrl}/share/embed/${activeEmbedId}#key=${encryptedBlob}`;
                    console.debug('[SettingsReportIssue] Auto-generated embed share URL');
                    return;
                } catch (error) {
                    console.warn('[SettingsReportIssue] Failed to generate embed share URL:', error);
                    // Continue to check for chat
                }
            }
            
            // Check for active chat
            const activeChatId = $activeChatStore;
            if (activeChatId) {
                hasActiveChatOrEmbed = true;
                console.debug('[SettingsReportIssue] Auto-generating share URL for chat:', activeChatId);
                
                // For public chats, use simple format
                if (isPublicChat(activeChatId)) {
                    const baseUrl = window.location.origin;
                    chatOrEmbedUrl = `${baseUrl}/#chat-id=${activeChatId}`;
                    console.debug('[SettingsReportIssue] Auto-generated public chat share URL');
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
                        console.debug('[SettingsReportIssue] Auto-generated chat share URL');
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
     * Collect IndexedDB inspection report for the active chat
     * This report contains only metadata (timestamps, versions, counts, encrypted content lengths)
     * and NO plaintext content - safe to include in issue reports for debugging.
     * 
     * @returns The inspection report string, or null if no active chat
     */
    async function collectChatInspectionReport(): Promise<string | null> {
        try {
            const activeChatId = $activeChatStore;
            if (!activeChatId) {
                console.debug('[SettingsReportIssue] No active chat for IndexedDB inspection');
                return null;
            }
            
            // Skip inspection for public/demo chats (they use a different DB)
            if (isPublicChat(activeChatId)) {
                console.debug('[SettingsReportIssue] Skipping IndexedDB inspection for public chat');
                return null;
            }
            
            console.debug('[SettingsReportIssue] Generating IndexedDB inspection for chat:', activeChatId);
            
            // Generate the inspection report (same format as window.inspectChat)
            // This only returns metadata - no plaintext content is included
            const report = await inspectChat(activeChatId);
            
            console.debug('[SettingsReportIssue] Generated IndexedDB inspection report:', report.length, 'chars');
            return report;
        } catch (error) {
            console.warn('[SettingsReportIssue] Failed to generate IndexedDB inspection:', error);
            return null;
        }
    }

    /**
     * Collect the rendered HTML of the last user message and assistant response
     * from the DOM. This helps debugging by showing exactly what the user saw.
     * 
     * Returns a string containing both messages' HTML, or null if no messages are found.
     * The HTML is extracted from the ProseMirror read-only editor instances in the DOM.
     */
    function collectLastMessagesHtml(): string | null {
        try {
            // Find all message wrappers in the chat history container
            const allMessages = document.querySelectorAll('[data-message-id]');
            if (!allMessages || allMessages.length === 0) {
                console.debug('[SettingsReportIssue] No messages found in DOM for HTML collection');
                return null;
            }
            
            const parts: string[] = [];
            
            // Find the last user message and last assistant message
            // Iterate backwards to find the most recent ones
            let lastUserEl: Element | null = null;
            let lastAssistantEl: Element | null = null;
            
            for (let i = allMessages.length - 1; i >= 0; i--) {
                const wrapper = allMessages[i];
                if (!lastAssistantEl && wrapper.classList.contains('assistant')) {
                    lastAssistantEl = wrapper;
                }
                if (!lastUserEl && wrapper.classList.contains('user')) {
                    lastUserEl = wrapper;
                }
                // Stop once we found both
                if (lastUserEl && lastAssistantEl) break;
            }
            
            // Extract rendered HTML from the ProseMirror editor content
            if (lastUserEl) {
                const proseMirror = lastUserEl.querySelector('.read-only-message .ProseMirror, .chat-message-text .ProseMirror');
                if (proseMirror) {
                    parts.push(`<div data-role="user">\n${proseMirror.innerHTML}\n</div>`);
                }
            }
            
            if (lastAssistantEl) {
                const proseMirror = lastAssistantEl.querySelector('.read-only-message .ProseMirror, .chat-message-text .ProseMirror');
                if (proseMirror) {
                    parts.push(`<div data-role="assistant">\n${proseMirror.innerHTML}\n</div>`);
                }
            }
            
            if (parts.length === 0) {
                console.debug('[SettingsReportIssue] Could not extract HTML from message DOM elements');
                return null;
            }
            
            const result = parts.join('\n');
            console.debug(`[SettingsReportIssue] Collected last messages HTML: ${result.length} chars`);
            return result;
        } catch (error) {
            console.warn('[SettingsReportIssue] Failed to collect last messages HTML:', error);
            return null;
        }
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
            } else if (emailError && emailInput) {
                emailInput.focus();
            }
            return;
        }
        
        isSubmitting = true;
        
        try {
            // SECURITY: Sanitize inputs before sending to backend
            const sanitizedTitle = sanitizeTextInput(issueTitle);
            // Description is optional - send null if empty, otherwise sanitize
            const sanitizedDescription = issueDescription.trim()
                ? sanitizeTextInput(issueDescription)
                : null;
            // Only include the share URL if the toggle is enabled and a URL was generated
            const sanitizedUrl = (shareChatEnabled && chatOrEmbedUrl.trim()) ? chatOrEmbedUrl.trim() : null;
            // Email is optional - send null if empty, otherwise sanitize (email doesn't need HTML sanitization, but trim it)
            const sanitizedEmail = contactEmail.trim() || null;

            // Collect current device information for debugging purposes
            const currentDeviceInfo = collectDeviceInfo();

            // Collect console logs for debugging (last 100 lines)
            const consoleLogs = logCollector.getLogsAsText(100);
            
            // Collect IndexedDB inspection report for active chat (if any)
            // This contains only metadata (timestamps, versions, encrypted content lengths)
            // and NO plaintext content - safe to include for debugging
            const indexedDbReport = await collectChatInspectionReport();
            
            // Collect rendered HTML of the last user message and assistant response
            // This helps debugging rendering issues and seeing exactly what the user saw
            const lastMessagesHtml = collectLastMessagesHtml();

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
                    console_logs: consoleLogs,
                    indexeddb_report: indexedDbReport,
                    last_messages_html: lastMessagesHtml
                }),
                credentials: 'include'
            });
            
            // Parse response - handle both JSON and non-JSON responses
            // Define response data type
            interface ApiResponse {
                success?: boolean;
                message?: string;
                issue_id?: string;
                detail?: Array<{
                    type: string;
                    loc: (string | number)[];
                    msg: string;
                    input?: unknown;
                    ctx?: Record<string, unknown>;
                }> | string;
            }
            
            let data: ApiResponse;
            const defaultErrorMessage = $text('settings.report_issue_error');
            
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
                // Store issue ID separately so it can be displayed as a copyable element
                const baseSuccessMessage = $text('settings.report_issue_success');
                successMessage = data.message || baseSuccessMessage;
                submittedIssueId = data.issue_id || '';
                issueIdCopied = false;
                
                // Show notification
                notificationStore.success(
                    baseSuccessMessage,
                    5000
                );
                
                // Reset form
                issueTitle = '';
                issueDescription = '';
                shareChatEnabled = true;
                chatOrEmbedUrl = '';
                contactEmail = '';
                titleError = '';
                descriptionError = '';
                emailError = '';
                showTitleWarning = false;
                showDescriptionWarning = false;
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
                        errorMessage = $text('settings.report_issue_error');
                        notificationStore.error(
                            errorMessage,
                            10000
                        );
                    } else {
                        // Fallback: show first error message
                        errorMessage = data.detail[0]?.msg || $text('settings.report_issue_error');
                        notificationStore.error(
                            errorMessage,
                            10000
                        );
                    }
                } else {
                    // Handle other API errors (non-validation errors)
                    const apiErrorMessage = data.message || (typeof data.detail === 'string' ? data.detail : $text('settings.report_issue_error'));
                    errorMessage = apiErrorMessage;
                    notificationStore.error(
                        errorMessage,
                        10000
                    );
                }
            }
        } catch (error) {
            console.error('[SettingsReportIssue] Error submitting issue:', error);
            errorMessage = $text('settings.report_issue_error');
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
        (!contactEmail.trim() || validateEmail(contactEmail)) &&
        !isSubmitting
    );
    
    /**
     * Validate description on input change
     */
    function handleDescriptionInput() {
        if (issueDescription && issueDescription.trim()) {
            if (issueDescription.trim().length < 10) {
                descriptionError = $text('settings.report_issue.description_too_short');
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
                emailError = $text('settings.report_issue.email_invalid');
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
    
    // State for copy debug info button
    let isCopyingDebugInfo = $state(false);
    let copyDebugInfoSuccess = $state(false);
    
    /**
     * Build the complete client-side debug info object that would be sent to the server.
     * This allows users to copy and share the debug info for local debugging.
     */
    async function buildClientDebugInfo(): Promise<object> {
        const currentDeviceInfo = collectDeviceInfo();
        const consoleLogs = logCollector.getLogsAsText(100);
        const indexedDbReport = await collectChatInspectionReport();
        
        return {
            device_info: currentDeviceInfo,
            console_logs: consoleLogs,
            indexeddb_report: indexedDbReport,
            active_chat_id: $activeChatStore || null,
            active_embed_id: $activeEmbedStore || null,
            share_chat_enabled: shareChatEnabled,
            chat_or_embed_url: (shareChatEnabled && chatOrEmbedUrl) ? chatOrEmbedUrl : null,
            timestamp: new Date().toISOString(),
            url: window.location.href
        };
    }
    
    /**
     * Copy client-side debug info to clipboard
     */
    async function handleCopyDebugInfo() {
        isCopyingDebugInfo = true;
        copyDebugInfoSuccess = false;
        
        try {
            const debugInfo = await buildClientDebugInfo();
            const debugInfoText = JSON.stringify(debugInfo, null, 2);
            
            await navigator.clipboard.writeText(debugInfoText);
            
            copyDebugInfoSuccess = true;
            notificationStore.success(
                $text('settings.report_issue.copy_debug_info_success'),
                3000
            );
            
            // Reset success state after 3 seconds
            setTimeout(() => {
                copyDebugInfoSuccess = false;
            }, 3000);
        } catch (error) {
            console.error('[SettingsReportIssue] Failed to copy debug info:', error);
            notificationStore.error(
                $text('settings.report_issue.copy_debug_info_error'),
                5000
            );
        } finally {
            isCopyingDebugInfo = false;
        }
    }
    
    /**
     * Copy issue ID to clipboard for easy reference
     */
    async function handleCopyIssueId() {
        if (!submittedIssueId) return;
        
        try {
            await navigator.clipboard.writeText(submittedIssueId);
            issueIdCopied = true;
            
            // Reset copied state after 3 seconds
            setTimeout(() => {
                issueIdCopied = false;
            }, 3000);
        } catch (error) {
            console.error('[SettingsReportIssue] Failed to copy issue ID:', error);
        }
    }
    
    // Auto-generate share URL and collect initial device info when component mounts
    onMount(() => {
        // Check for pre-filled data from store
        if ($reportIssueStore) {
            if ($reportIssueStore.title) issueTitle = $reportIssueStore.title;
            if ($reportIssueStore.description) issueDescription = $reportIssueStore.description;
            // If a URL was passed directly (e.g. from deep link), pre-fill it
            if ($reportIssueStore.url) chatOrEmbedUrl = $reportIssueStore.url;
            // If the store requests sharing the chat, enable the toggle
            if ($reportIssueStore.shareChat) shareChatEnabled = true;
            
            // Clear store after consuming
            reportIssueStore.set(null);
        }

        // Small delay to ensure stores are initialized
        setTimeout(() => {
            autoGenerateShareUrl();
            // Collect initial device info to show in the form
            deviceInfo = collectDeviceInfo();
        }, 100);
    });
</script>

<div class="report-issue-settings">
    <p>{$text('settings.report_issue.description')}</p>
    
    <!-- Issue Report Form -->
    <div class="report-issue-form">
        <!-- Title Input -->
        <div class="input-group">
            <label for="issue-title">{$text('settings.report_issue.title_label')}</label>
            <div class="input-wrapper">
                <input
                    id="issue-title"
                    bind:this={titleInput}
                    type="text"
                    placeholder={$text('settings.report_issue.title_placeholder')}
                    bind:value={issueTitle}
                    onkeypress={handleTitleKeyPress}
                    disabled={isSubmitting}
                    class:error={!!titleError}
                    aria-label={$text('settings.report_issue.title_label')}
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
            <label for="issue-description">{$text('settings.report_issue.description_label')}</label>
            <div class="input-wrapper">
                <textarea
                    id="issue-description"
                    bind:this={descriptionInput}
                    placeholder={$text('settings.report_issue.description_placeholder')}
                    bind:value={issueDescription}
                    oninput={handleDescriptionInput}
                    disabled={isSubmitting}
                    class:error={!!descriptionError}
                    aria-label={$text('settings.report_issue.description_label')}
                    rows="5"
                ></textarea>
                {#if showDescriptionWarning && descriptionError}
                    <InputWarning
                        message={descriptionError}
                    />
                {/if}
            </div>
        </div>
        
        <!-- Share Chat Toggle (only shown when there's an active chat or embed) -->
        {#if hasActiveChatOrEmbed}
            <div class="toggle-group">
                <div class="toggle-row">
                    <label for="share-chat-toggle">{$text('settings.report_issue.share_chat_label')}</label>
                    <Toggle
                        id="share-chat-toggle"
                        bind:checked={shareChatEnabled}
                        disabled={isSubmitting}
                        ariaLabel={$text('settings.report_issue.share_chat_label')}
                    />
                </div>
                <p class="input-hint">{$text('settings.report_issue.share_chat_hint')}</p>
            </div>
        {/if}
        
        <!-- Contact Email Input (Optional) -->
        <div class="input-group">
            <label for="contact-email">{$text('settings.report_issue.email_label')}</label>
            <div class="input-wrapper">
                <input
                    id="contact-email"
                    bind:this={emailInput}
                    type="email"
                    placeholder={$text('settings.report_issue.email_placeholder')}
                    bind:value={contactEmail}
                    oninput={handleEmailInput}
                    disabled={isSubmitting}
                    class:error={!!emailError}
                    aria-label={$text('settings.report_issue.email_label')}
                />
                {#if showEmailWarning && emailError}
                    <InputWarning
                        message={emailError}
                    />
                {/if}
            </div>
            <p class="input-hint">{$text('settings.report_issue.email_hint')}</p>
        </div>
        
        <!-- Signal Group Reminder -->
        <div class="signal-reminder">
            <p class="reminder-text">
                {$text('settings.report_issue.signal_reminder')}{' '}
                <a
                    href={externalLinks.signal}
                    target="_blank"
                    rel="noopener noreferrer"
                    class="signal-link"
                >
                    {$text('settings.report_issue.signal_link')}
                </a>
            </p>
        </div>
        
        <!-- Submit Button -->
        <div class="button-container">
            <button
                onclick={handleSubmit}
                disabled={!isFormValid || isSubmitting}
                aria-label={$text('settings.report_issue.submit_button')}
            >
                {#if isSubmitting}
                    {$text('settings.report_issue.submitting')}
                {:else}
                    {$text('settings.report_issue.submit_button')}
                {/if}
            </button>
        </div>
        
        <!-- Success message -->
        {#if successMessage}
            <div class="message success-message" role="alert">
                {successMessage}
                {#if submittedIssueId}
                    <div class="issue-id-container">
                        <span class="issue-id-label">{$text('settings.report_issue.issue_id_label')}</span>
                        <div class="issue-id-copy-row">
                            <code class="issue-id-value">{submittedIssueId}</code>
                            <button
                                class="issue-id-copy-button"
                                class:copied={issueIdCopied}
                                onclick={handleCopyIssueId}
                                aria-label={$text('settings.report_issue.copy_issue_id')}
                            >
                                {#if issueIdCopied}
                                    {$text('settings.report_issue.issue_id_copied')}
                                {:else}
                                    {$text('settings.report_issue.copy_issue_id')}
                                {/if}
                            </button>
                        </div>
                    </div>
                {/if}
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
            <h4>{$text('settings.report_issue.device_info.heading')}</h4>
            <p class="notice-text">
                {$text('settings.report_issue.device_info.description')}
            </p>
            <ul class="device-info-list">
                <li><strong>{$text('settings.report_issue.device_info.browser_os_label')}:</strong> {deviceInfo.userAgent || 'Loading...'}</li>
                <li><strong>{$text('settings.report_issue.device_info.screen_size_label')}:</strong> {deviceInfo.viewportWidth || 0} × {deviceInfo.viewportHeight || 0} pixels</li>
                <li><strong>{$text('settings.report_issue.device_info.touch_support_label')}:</strong> {deviceInfo.isTouchEnabled ? 'Yes' : 'No'}</li>
            </ul>
            <p class="privacy-notice">
                <strong>{$text('settings.report_issue.device_info.privacy_label')}:</strong>
                {$text('settings.report_issue.device_info.privacy_body')}
            </p>
            
            <!-- Copy Debug Info Button -->
            <div class="copy-debug-info-container">
                <button
                    class="copy-debug-info-button"
                    class:success={copyDebugInfoSuccess}
                    onclick={handleCopyDebugInfo}
                    disabled={isCopyingDebugInfo}
                    aria-label={$text('settings.report_issue.copy_debug_info_button')}
                >
                    {#if isCopyingDebugInfo}
                        {$text('settings.report_issue.copy_debug_info_copying')}
                    {:else if copyDebugInfoSuccess}
                        {$text('settings.report_issue.copy_debug_info_copied')}
                    {:else}
                        {$text('settings.report_issue.copy_debug_info_button')}
                    {/if}
                </button>
                <p class="copy-debug-info-hint">
                    {$text('settings.report_issue.copy_debug_info_hint')}
                </p>
            </div>
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
    
    .toggle-group {
        display: flex;
        flex-direction: column;
        gap: 6px;
    }
    
    .toggle-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 8px 0;
    }
    
    .toggle-row label {
        font-size: 14px;
        font-weight: 500;
        color: var(--color-font-primary);
        flex: 1;
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

    /* Issue ID copyable element within success message */
    .issue-id-container {
        margin-top: 12px;
        padding-top: 10px;
        border-top: 1px solid var(--color-success, #4caf50);
    }

    .issue-id-label {
        display: block;
        font-size: 12px;
        font-weight: 600;
        margin-bottom: 6px;
        opacity: 0.85;
    }

    .issue-id-copy-row {
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .issue-id-value {
        flex: 1;
        padding: 8px 10px;
        background-color: rgba(0, 0, 0, 0.06);
        border: 1px solid var(--color-success, #4caf50);
        border-radius: 6px;
        font-family: monospace;
        font-size: 13px;
        word-break: break-all;
        user-select: all;
        cursor: text;
    }

    .issue-id-copy-button {
        flex-shrink: 0;
        padding: 8px 14px;
        background-color: var(--color-success, #4caf50);
        color: white;
        border: none;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
        white-space: nowrap;
    }

    .issue-id-copy-button:hover {
        opacity: 0.9;
    }

    .issue-id-copy-button:active {
        transform: scale(0.96);
    }

    .issue-id-copy-button.copied {
        background-color: var(--color-success-dark, #2e7d32);
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

    .copy-debug-info-container {
        margin-top: 16px;
        padding-top: 16px;
        border-top: 1px solid var(--color-info, #2196f3);
    }

    .copy-debug-info-button {
        width: 100%;
        padding: 10px 16px;
        background-color: var(--color-grey-30, #e0e0e0);
        color: var(--color-font-primary);
        border: 1px solid var(--color-grey-40, #bdbdbd);
        border-radius: 8px;
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
    }

    .copy-debug-info-button:hover:not(:disabled) {
        background-color: var(--color-grey-40, #bdbdbd);
    }

    .copy-debug-info-button:active:not(:disabled) {
        transform: scale(0.98);
    }

    .copy-debug-info-button:disabled {
        opacity: 0.6;
        cursor: not-allowed;
    }

    .copy-debug-info-button.success {
        background-color: var(--color-success-light, #e8f5e9);
        border-color: var(--color-success, #4caf50);
        color: var(--color-success-dark, #2e7d32);
    }

    .copy-debug-info-hint {
        font-size: 12px;
        color: var(--color-info-dark, #1565c0);
        margin: 8px 0 0 0;
        line-height: 1.4;
        opacity: 0.8;
    }
</style>
