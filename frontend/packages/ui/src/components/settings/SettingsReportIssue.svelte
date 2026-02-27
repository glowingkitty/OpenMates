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
    import { text, notificationStore, activeChatStore, activeEmbedStore, websocketStatus, isOnline, phasedSyncState } from '@repo/ui';
    import { getApiEndpoint } from '../../config/api';
    import { externalLinks } from '../../config/links';
    import InputWarning from '../common/InputWarning.svelte';
    import Toggle from '../Toggle.svelte';
    import { onMount, createEventDispatcher } from 'svelte';
    import { isPublicChat } from '../../demo_chats/convertToChat';
    import { logCollector } from '../../services/logCollector';
    import { userActionTracker } from '../../services/userActionTracker';
    import { reportIssueStore, submittedIssueIdStore, reportIssueFormDraftStore } from '../../stores/reportIssueStore';
    import { inspectChat } from '../../services/debugUtils';
    import { authStore } from '../../stores/authStore';
    import { getEmailDecryptedWithMasterKey } from '../../services/cryptoService';
    import { aiTypingStore } from '../../stores/aiTypingStore';
    import { hasPendingSends } from '../../stores/pendingUploadStore';

    const dispatch = createEventDispatcher();
    
    // Form state
    let issueTitle = $state('');
    // Structured description fields — replace the old single freeform textarea.
    // All three are optional. On submit they are composed into a formatted description
    // string sent to the backend's existing `description` field.
    let userFlow = $state('');
    let expectedBehaviour = $state('');
    let actualBehaviour = $state('');
    let shareChatEnabled = $state(true);
    let chatOrEmbedUrl = $state('');
    let contactEmail = $state('');
    let isSubmitting = $state(false);
    let errorMessage = $state('');

    /**
     * For authenticated users: the decrypted account email loaded on mount.
     * Used as the value submitted when includeEmailToggle is true.
     */
    let authenticatedUserEmail = $state('');

    /**
     * For authenticated users: whether to include their account email in the report.
     * Defaults to true (opt-in by default) so users get follow-up contact.
     */
    let includeEmailToggle = $state(true);
    
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
    let userFlowInput = $state<HTMLTextAreaElement>();
    let emailInput = $state<HTMLInputElement>();
    
    // Validation state (description fields are all optional, no per-field errors needed)
    let titleError = $state('');
    let emailError = $state('');
    let showTitleWarning = $state(false);
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
     * Validate form fields.
     * Only the title is required. All three structured description fields and email are optional.
     */
    function validateForm(): boolean {
        let isValid = true;
        
        // Validate title (required, min 3 chars)
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
        
        // Validate email if provided (optional field — guest users only)
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
     * Collect the outerHTML of the currently active chat entry in the sidebar
     * (the `.chat-item.active` element rendered by Chat.svelte inside Chats.svelte).
     *
     * This captures exactly what the user sees in the chat list for the active
     * chat: title, status label (typing / draft / sending), category icon state,
     * and any typing-indicator shimmer text. Useful for debugging "wrong chat
     * shown as active" and "typing indicator stuck" issues.
     *
     * Returns the sanitised outerHTML string, or null if nothing is found.
     */
    function collectActiveChatSidebarHtml(): string | null {
        try {
            // The active chat wrapper in Chats.svelte carries both class="chat-item"
            // and class="active" on the same element, and aria-current="page".
            // Try the aria-current selector first (most reliable), then fall back to
            // the compound class selector.
            const activeEl =
                document.querySelector('[aria-current="page"]') ??
                document.querySelector('.chat-item.active');

            if (!activeEl) {
                console.debug('[SettingsReportIssue] No active chat sidebar element found');
                return null;
            }

            const html = activeEl.outerHTML;
            console.debug(`[SettingsReportIssue] Collected active chat sidebar HTML: ${html.length} chars`);
            return html;
        } catch (error) {
            console.warn('[SettingsReportIssue] Failed to collect active chat sidebar HTML:', error);
            return null;
        }
    }

    /**
     * Collect a snapshot of all runtime state that is useful for debugging
     * message-sending and sync issues.
     *
     * Fields returned:
     * - websocket_status  — current WS connection state (connected/disconnected/error…)
     * - is_online         — navigator.onLine (boolean)
     * - ai_typing_status  — aiTypingStore snapshot (isTyping, chatId, category, model…)
     * - has_pending_sends — whether the active chat has queued uploads blocking send
     * - phased_sync_state — subset of phasedSyncState useful for debugging sync issues
     */
    function collectRuntimeDebugState(): object {
        try {
            const activeChatId = $activeChatStore;

            // Read aiTypingStore — manual get() since it uses a legacy writable store
            let aiTypingSnapshot: object | null = null;
            const unsubAI = aiTypingStore.subscribe((val) => { aiTypingSnapshot = val; });
            unsubAI(); // unsubscribe immediately — we only need a one-shot read

            // Read websocketStatus
            let wsSnapshot: object | null = null;
            const unsubWS = websocketStatus.subscribe((val) => { wsSnapshot = val; });
            unsubWS();

            // isOnline — readable store
            let onlineSnapshot = true;
            const unsubOnline = isOnline.subscribe((val) => { onlineSnapshot = val; });
            unsubOnline();

            // phasedSyncState — pick the fields relevant for send/sync debugging
            const syncState = $phasedSyncState;
            const syncSnapshot = {
                initialSyncCompleted: syncState.initialSyncCompleted,
                userMadeExplicitChoice: syncState.userMadeExplicitChoice,
                currentActiveChatId: syncState.currentActiveChatId,
                phase1ChatId: syncState.phase1ChatId,
                lastSyncTimestamp: syncState.lastSyncTimestamp,
                initialChatLoaded: syncState.initialChatLoaded,
            };

            // pendingUploads — just a boolean per active chat
            const pendingSends = activeChatId ? hasPendingSends(activeChatId) : false;

            return {
                websocket_status: wsSnapshot,
                is_online: onlineSnapshot,
                ai_typing_status: aiTypingSnapshot,
                has_pending_sends: pendingSends,
                phased_sync_state: syncSnapshot,
            };
        } catch (error) {
            console.warn('[SettingsReportIssue] Failed to collect runtime debug state:', error);
            return { error: String(error) };
        }
    }

    /**
     * Handle form submission
     */
    async function handleSubmit() {
        // Reset error message from any previous submission attempt
        errorMessage = '';
        
        // Validate form
        if (!validateForm()) {
            // Focus first invalid field
            if (titleError && titleInput) {
                titleInput.focus();
            } else if (emailError && emailInput) {
                emailInput.focus();
            }
            return;
        }
        
        isSubmitting = true;
        
        try {
            // SECURITY: Sanitize inputs before sending to backend
            const sanitizedTitle = sanitizeTextInput(issueTitle);

            // Compose the three structured fields into a single formatted description.
            // Only include sections that have content; send null if everything is empty.
            const descriptionParts: string[] = [];
            if (userFlow.trim()) {
                descriptionParts.push(`## What did you do?\n${sanitizeTextInput(userFlow)}`);
            }
            if (expectedBehaviour.trim()) {
                descriptionParts.push(`## Expected behaviour\n${sanitizeTextInput(expectedBehaviour)}`);
            }
            if (actualBehaviour.trim()) {
                descriptionParts.push(`## Actual behaviour\n${sanitizeTextInput(actualBehaviour)}`);
            }
            const sanitizedDescription = descriptionParts.length > 0
                ? descriptionParts.join('\n\n')
                : null;
            // Only include the share URL if the toggle is enabled and a URL was generated
            const sanitizedUrl = (shareChatEnabled && chatOrEmbedUrl.trim()) ? chatOrEmbedUrl.trim() : null;
            // For authenticated users: use their account email if the toggle is on, otherwise null.
            // For guest users: use the manually entered email (optional input field).
            const sanitizedEmail = $authStore.isAuthenticated
                ? (includeEmailToggle && authenticatedUserEmail.trim() ? authenticatedUserEmail.trim() : null)
                : (contactEmail.trim() || null);

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

            // Collect the outerHTML of the active chat entry in the sidebar.
            // Captures the chat's visible state (title, typing indicator, category icon, etc.)
            // at the moment of submission — useful for "wrong chat active" and "typing stuck" bugs.
            const activeChatSidebarHtml = collectActiveChatSidebarHtml();

            // Collect runtime state: WS connection, online status, AI typing, pending uploads, sync
            const runtimeDebugState = collectRuntimeDebugState();

            // Determine the user's current UI language for confirmation email localisation
            const currentLanguage = localStorage.getItem('preferredLanguage')
                || navigator.language.split('-')[0]
                || 'en';

            // Collect user action history (last 20 interactions: button names / navigation only)
            // NO user-typed text content is included — only developer-authored labels
            const actionHistory = userActionTracker.getActionHistoryAsText();

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
                    language: currentLanguage,
                    device_info: currentDeviceInfo,
                    console_logs: consoleLogs,
                    indexeddb_report: indexedDbReport,
                    last_messages_html: lastMessagesHtml,
                    active_chat_sidebar_html: activeChatSidebarHtml,
                    runtime_debug_state: runtimeDebugState,
                    action_history: actionHistory,
                    // Screenshot PNG captured via getDisplayMedia() — only sent for authenticated users.
                    // The data URI prefix ("data:image/png;base64,") is stripped server-side.
                    // Null if no screenshot was captured or user is a guest.
                    screenshot_png_base64: ($authStore.isAuthenticated && screenshotDataUrl)
                        ? screenshotDataUrl
                        : null,
                    // outerHTML of the DOM element the user picked via the element picker overlay.
                    // Null if the user did not pick an element.
                    picked_element_html: pickedElementHtml ?? null
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
                const issueId = data.issue_id || '';

                // Reset form fields
                issueTitle = '';
                userFlow = '';
                expectedBehaviour = '';
                actualBehaviour = '';
                shareChatEnabled = true;
                chatOrEmbedUrl = '';
                contactEmail = '';
                // Re-enable the email toggle for authenticated users after a successful submission
                includeEmailToggle = true;
                titleError = '';
                emailError = '';
                showTitleWarning = false;
                showEmailWarning = false;

                // Clear the form draft store so it doesn't restore stale data on the next report
                reportIssueFormDraftStore.set(null);

                // Clear picked element and screenshot state so they don't persist after submission
                pickedElementHtml = null;
                screenshotDataUrl = null;
                screenshotError = '';
                showUploadFallback = typeof navigator !== 'undefined' &&
                    typeof (navigator.mediaDevices as { getDisplayMedia?: unknown } | undefined)?.getDisplayMedia !== 'function';
                if (screenshotFileInput) screenshotFileInput.value = '';

                // Write the issue ID to the shared store so the confirmation sub-page
                // can read it without prop drilling through the settings router.
                submittedIssueIdStore.set(issueId);
                dispatch('openSettings', {
                    settingsPath: 'report_issue/confirmation',
                    direction: 'forward',
                    icon: 'report_issue',
                    title: $text('settings.report_issue.confirmation_title')
                });
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
     * Handle Enter key press in title input — move focus to the first structured field
     */
    function handleTitleKeyPress(event: KeyboardEvent) {
        if (event.key === 'Enter' && !isSubmitting) {
            event.preventDefault();
            if (userFlowInput) {
                userFlowInput.focus();
            }
        }
    }
    
    /**
     * Check if form is valid.
     * Only title is required (min 3 chars). All description fields are optional (no minimum).
     * Email is optional but must be valid if provided (guest only).
     */
    let isFormValid = $derived(
        issueTitle.trim().length >= 3 &&
        ($authStore.isAuthenticated || !contactEmail.trim() || validateEmail(contactEmail)) &&
        !isSubmitting
    );
    
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
    
    // ===================== DOM ELEMENT PICKER =====================
    // Lets the user tap/click any element on the page to capture its outerHTML for debugging.
    // Works on both desktop (hover + click) and touch (first tap selects, confirm bar finalizes).
    //
    // Flow:
    //  1. User clicks "Pick Element" → settings panel slides out via 'closeSettingsMenu' event.
    //  2. A full-screen overlay is injected, with a floating instruction bar at the top.
    //  3. pointermove (desktop) highlights the element under cursor with a red outline.
    //  4. First tap/click: locks the element as "selected" (first-tap state).
    //  5. A "Confirm / Cancel" button group appears in the instruction bar.
    //  6. Tapping the same element again OR pressing "Confirm" captures its outerHTML.
    //  7. Pressing "Cancel" or Escape aborts without capturing.
    //  8. After capture/cancel, settings re-opens via 'openSettingsFromPicker' event.
    //     (Settings.svelte registers a 'openSettingsMenu' listener symmetrically to closeSettingsMenu.)
    //
    // Element exclusions:
    //  - The picker overlay and instruction bar itself
    //  - Elements with bounding rect < 20×20 px (tiny icons, text spans)

    /** outerHTML captured by the element picker, or null if not yet captured */
    let pickedElementHtml = $state<string | null>(null);
    /** True while the picker overlay is active (user is selecting an element) */
    let isPickerActive = $state(false);

    /**
     * Internal references for the picker overlay elements and event handlers.
     * These are created and destroyed dynamically — not rendered in the Svelte template.
     */
    let _pickerOverlay: HTMLElement | null = null;
    let _pickerHighlightedEl: Element | null = null;
    let _pickerSelectedEl: Element | null = null;
    let _pickerInstructionBar: HTMLElement | null = null;

    /**
     * Apply a highlight outline to an element during picker mode.
     * Stores/restores the element's original outline style.
     */
    function _pickerHighlight(el: Element | null) {
        if (_pickerHighlightedEl && _pickerHighlightedEl !== el) {
            // Remove highlight from previous element (unless it's also the selected one)
            if (_pickerHighlightedEl !== _pickerSelectedEl) {
                (_pickerHighlightedEl as HTMLElement).style.outline = '';
                (_pickerHighlightedEl as HTMLElement).style.outlineOffset = '';
            }
        }
        if (el && el !== _pickerSelectedEl) {
            (el as HTMLElement).style.outline = '2px solid #e53935';
            (el as HTMLElement).style.outlineOffset = '2px';
        }
        _pickerHighlightedEl = el;
    }

    /**
     * Apply a "selected" (first-tap) highlight to an element.
     * Uses a distinct colour to differentiate selected from hovered.
     */
    function _pickerSelect(el: Element) {
        // Clear previous selection outline
        if (_pickerSelectedEl && _pickerSelectedEl !== el) {
            (_pickerSelectedEl as HTMLElement).style.outline = '';
            (_pickerSelectedEl as HTMLElement).style.outlineOffset = '';
        }
        (el as HTMLElement).style.outline = '3px solid #f57f17';
        (el as HTMLElement).style.outlineOffset = '2px';
        _pickerSelectedEl = el;

        // Show the confirm/cancel row in the instruction bar
        if (_pickerInstructionBar) {
            const confirmRow = _pickerInstructionBar.querySelector('.picker-confirm-row') as HTMLElement | null;
            if (confirmRow) confirmRow.style.display = 'flex';
        }
    }

    /**
     * Remove all picker outlines from highlighted and selected elements.
     */
    function _pickerClearStyles() {
        if (_pickerHighlightedEl) {
            (_pickerHighlightedEl as HTMLElement).style.outline = '';
            (_pickerHighlightedEl as HTMLElement).style.outlineOffset = '';
            _pickerHighlightedEl = null;
        }
        if (_pickerSelectedEl) {
            (_pickerSelectedEl as HTMLElement).style.outline = '';
            (_pickerSelectedEl as HTMLElement).style.outlineOffset = '';
            _pickerSelectedEl = null;
        }
    }

    /**
     * Check whether an element is part of the picker overlay itself or is too small to be useful.
     * Elements < 20×20 px are excluded to avoid selecting tiny icons or inline text spans.
     */
    function _isPickerExcluded(el: Element): boolean {
        if (!el) return true;
        if (_pickerOverlay && _pickerOverlay.contains(el)) return true;
        try {
            const rect = el.getBoundingClientRect();
            if (rect.width < 20 || rect.height < 20) return true;
        } catch {
            return true;
        }
        return false;
    }

    /**
     * Pointer-move handler: highlight the element under the pointer.
     */
    function _pickerPointerMove(e: PointerEvent) {
        // Temporarily hide overlay to hit-test elements underneath
        if (_pickerOverlay) _pickerOverlay.style.pointerEvents = 'none';
        const el = document.elementFromPoint(e.clientX, e.clientY);
        if (_pickerOverlay) _pickerOverlay.style.pointerEvents = 'all';

        if (!el || _isPickerExcluded(el)) return;
        if (el !== _pickerHighlightedEl) {
            _pickerHighlight(el);
        }
    }

    /**
     * Pointer-down handler: first tap selects, second tap on the same element confirms.
     */
    function _pickerPointerDown(e: PointerEvent) {
        e.preventDefault();
        e.stopPropagation();

        // Temporarily lift overlay pointer events to find the real target
        if (_pickerOverlay) _pickerOverlay.style.pointerEvents = 'none';
        const el = document.elementFromPoint(e.clientX, e.clientY);
        if (_pickerOverlay) _pickerOverlay.style.pointerEvents = 'all';

        if (!el || _isPickerExcluded(el)) return;

        if (!_pickerSelectedEl) {
            // First tap: select this element
            _pickerSelect(el);
        } else if (el === _pickerSelectedEl) {
            // Second tap on same element: confirm
            _confirmPick();
        } else {
            // Tap on a different element: move selection
            _pickerSelect(el);
        }
    }

    /**
     * Keyboard handler: Escape cancels the picker.
     */
    function _pickerKeyDown(e: KeyboardEvent) {
        if (e.key === 'Escape') {
            cancelElementPicker();
        }
    }

    /**
     * Confirm the currently selected element: capture its outerHTML and clean up.
     */
    function _confirmPick() {
        if (!_pickerSelectedEl) return;
        try {
            pickedElementHtml = _pickerSelectedEl.outerHTML;
            console.debug(
                `[SettingsReportIssue] Picked element HTML captured: ${pickedElementHtml.length} chars`
            );
        } catch (error) {
            console.warn('[SettingsReportIssue] Failed to capture element outerHTML:', error);
        }
        _pickerCleanup(true);
    }

    /**
     * Remove the picker overlay, event listeners, and element outlines.
     * @param reopenSettings - Whether to dispatch the window event to re-open the settings panel.
     */
    function _pickerCleanup(reopenSettings: boolean) {
        // Remove event listeners
        document.removeEventListener('pointermove', _pickerPointerMove);
        document.removeEventListener('pointerdown', _pickerPointerDown, true);
        document.removeEventListener('keydown', _pickerKeyDown);

        // Clear element outlines
        _pickerClearStyles();

        // Remove overlay from DOM
        if (_pickerOverlay && _pickerOverlay.parentNode) {
            _pickerOverlay.parentNode.removeChild(_pickerOverlay);
        }
        _pickerOverlay = null;
        _pickerInstructionBar = null;

        isPickerActive = false;

        // Re-open the settings panel and navigate back to the report_issue page.
        // We pass returnTo so Settings.svelte can restore the correct sub-page after
        // toggleMenu() resets activeSettingsView to 'main' on close.
        if (reopenSettings) {
            // Update the form draft with the freshly picked element HTML before the
            // component is destroyed by the settings panel re-opening.
            // _saveFormDraft() was called earlier (when the picker *started*) with
            // pickedElementHtml still null — we must update it now so the restored
            // form shows the captured element preview.
            _saveFormDraft();

            window.dispatchEvent(new CustomEvent('openSettingsMenu', {
                detail: { returnTo: 'report_issue' }
            }));
        }
    }

    /**
     * Persist the current form state to reportIssueFormDraftStore before the
     * settings panel is closed.  This allows the form to be restored exactly as
     * the user left it after the component is unmounted and re-mounted when the
     * settings panel re-opens (CurrentSettingsPage.svelte recreates the component
     * on every view switch).
     */
    function _saveFormDraft() {
        reportIssueFormDraftStore.set({
            issueTitle,
            userFlow,
            expectedBehaviour,
            actualBehaviour,
            shareChatEnabled,
            chatOrEmbedUrl,
            contactEmail,
            includeEmailToggle,
            pickedElementHtml,
            screenshotDataUrl
        });
    }

    /**
     * Start the element picker:
     *  1. Save form draft to store so state survives the component remount.
     *  2. Close the settings panel (via window event).
     *  3. Inject the picker overlay.
     *  4. Register event listeners.
     */
    function startElementPicker() {
        if (isPickerActive) return;

        isPickerActive = true;
        _pickerSelectedEl = null;
        _pickerHighlightedEl = null;

        // Persist form state before the component is destroyed by the settings panel closing.
        _saveFormDraft();

        // Close the settings panel so the full page is accessible.
        // Settings.svelte listens for 'closeSettingsMenu' and calls toggleMenu() safely.
        window.dispatchEvent(new CustomEvent('closeSettingsMenu'));

        // Small delay to let the settings panel animate out before injecting the overlay
        setTimeout(() => {
            _injectPickerOverlay();
        }, 350);
    }

    /**
     * Inject the full-screen picker overlay and register all interaction handlers.
     */
    function _injectPickerOverlay() {
        // Create the main transparent overlay (captures pointer events to prevent clicks on the page)
        const overlay = document.createElement('div');
        overlay.className = 'picker-overlay-root';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-label', 'Element picker');
        Object.assign(overlay.style, {
            position: 'fixed',
            inset: '0',
            zIndex: '2147483646', // just below browser chrome
            pointerEvents: 'all',
            cursor: 'crosshair',
            background: 'transparent'
        });

        // Instruction bar at the top of the overlay
        const bar = document.createElement('div');
        bar.className = 'picker-instruction-bar';
        Object.assign(bar.style, {
            position: 'absolute',
            top: '0',
            left: '0',
            right: '0',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '8px',
            padding: '12px 16px',
            background: 'rgba(25, 25, 30, 0.92)',
            backdropFilter: 'blur(8px)',
            color: '#fff',
            fontSize: '14px',
            fontFamily: 'system-ui, sans-serif',
            boxShadow: '0 2px 12px rgba(0,0,0,0.4)',
            zIndex: '2147483647',
            pointerEvents: 'all'
        });

        // Instruction text row
        const instructionText = document.createElement('div');
        instructionText.style.cssText = 'display:flex;align-items:center;gap:12px;width:100%;justify-content:center;';
        instructionText.innerHTML = `
            <span style="color:#f9a825;font-weight:600;">⊹</span>
            <span>${$text('settings.report_issue.element_picker_instruction')}</span>
        `;
        bar.appendChild(instructionText);

        // Confirm + Cancel row (hidden until an element is selected)
        const confirmRow = document.createElement('div');
        confirmRow.className = 'picker-confirm-row';
        Object.assign(confirmRow.style, {
            display: 'none',
            gap: '10px',
            alignItems: 'center'
        });

        const confirmBtn = document.createElement('button');
        confirmBtn.textContent = $text('settings.report_issue.element_picker_confirm');
        Object.assign(confirmBtn.style, {
            padding: '8px 20px',
            background: '#f57f17',
            color: '#fff',
            border: 'none',
            borderRadius: '6px',
            fontWeight: '600',
            fontSize: '13px',
            cursor: 'pointer',
            fontFamily: 'system-ui, sans-serif'
        });
        confirmBtn.addEventListener('click', (e) => { e.stopPropagation(); _confirmPick(); });

        const cancelBtn = document.createElement('button');
        cancelBtn.textContent = $text('settings.report_issue.element_picker_cancel');
        Object.assign(cancelBtn.style, {
            padding: '8px 16px',
            background: 'rgba(255,255,255,0.15)',
            color: '#fff',
            border: '1px solid rgba(255,255,255,0.3)',
            borderRadius: '6px',
            fontSize: '13px',
            cursor: 'pointer',
            fontFamily: 'system-ui, sans-serif'
        });
        cancelBtn.addEventListener('click', (e) => { e.stopPropagation(); cancelElementPicker(); });

        confirmRow.appendChild(confirmBtn);
        confirmRow.appendChild(cancelBtn);
        bar.appendChild(confirmRow);

        overlay.appendChild(bar);
        document.body.appendChild(overlay);

        _pickerOverlay = overlay;
        _pickerInstructionBar = bar;
        // confirmBtn and cancelBtn are referenced via closures only — no need to store them

        // Register interaction handlers
        document.addEventListener('pointermove', _pickerPointerMove, { passive: true });
        document.addEventListener('pointerdown', _pickerPointerDown, { capture: true });
        document.addEventListener('keydown', _pickerKeyDown);
    }

    /**
     * Cancel the element picker without capturing anything.
     */
    function cancelElementPicker() {
        _pickerCleanup(true);
    }

    /**
     * Remove a previously captured element from the report.
     */
    function removePickedElement() {
        pickedElementHtml = null;
    }

    /** True while copying the picked element HTML to clipboard (prevents double-click) */
    let isCopyingElementHtml = $state(false);
    /** Briefly true after a successful copy — triggers the "Copied!" label */
    let copyElementHtmlSuccess = $state(false);

    /**
     * Copy the captured element outerHTML to the system clipboard.
     * Shows a brief "Copied!" confirmation that resets after 2 seconds.
     */
    async function copyPickedElementHtml() {
        if (!pickedElementHtml || isCopyingElementHtml) return;
        isCopyingElementHtml = true;
        try {
            await navigator.clipboard.writeText(pickedElementHtml);
            copyElementHtmlSuccess = true;
            setTimeout(() => { copyElementHtmlSuccess = false; }, 2000);
        } catch (error) {
            console.error('[SettingsReportIssue] Failed to copy element HTML to clipboard:', error);
            notificationStore.error($text('settings.report_issue.copy_debug_info_error'), 4000);
        } finally {
            isCopyingElementHtml = false;
        }
    }

    // ===================== SCREENSHOT CAPTURE =====================
    // Screenshot state — only available for authenticated users.
    // getDisplayMedia() requires browser permission; the PNG is sent as base64 in the JSON payload.
    // On iOS (where getDisplayMedia is not supported) or after a non-permission capture failure,
    // a file-upload fallback (<input type="file">) is shown instead.

    /** Base64 PNG data URL (includes "data:image/png;base64," prefix) or null if not captured */
    let screenshotDataUrl = $state<string | null>(null);
    /** True while the getDisplayMedia dialog is open / frame is being captured */
    let isCapturingScreenshot = $state(false);
    /** Human-readable capture error shown below the screenshot button */
    let screenshotError = $state('');
    /**
     * True after a non-permission capture failure — reveals the upload fallback button.
     * Also true on iOS where getDisplayMedia is not available at all.
     */
    let showUploadFallback = $state(
        typeof navigator !== 'undefined' &&
        typeof (navigator.mediaDevices as { getDisplayMedia?: unknown } | undefined)?.getDisplayMedia !== 'function'
    );
    /** Reference to the hidden file input used for the upload fallback */
    let screenshotFileInput = $state<HTMLInputElement | null>(null);

    /**
     * Capture the current screen using the native Screen Capture API (getDisplayMedia).
     *
     * Flow:
     *  1. Call getDisplayMedia — browser shows a screen/tab picker dialog.
     *  2. Grab one video frame from the returned MediaStream.
     *  3. Draw the frame onto a hidden <canvas> and export as PNG data URL.
     *  4. Stop all tracks immediately to close the browser's capture indicator.
     *  5. Store the PNG in screenshotDataUrl for preview and later submission.
     */
    async function captureScreenshot() {
        screenshotError = '';
        isCapturingScreenshot = true;

        let stream: MediaStream | null = null;
        try {
            // preferCurrentTab is a Chrome 107+ hint to pre-select the current tab.
            // Other browsers ignore it and show the standard full picker.
            // We cast to any to avoid TS errors on the non-standard extensions.
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            stream = await (navigator.mediaDevices as any).getDisplayMedia({
                video: { displaySurface: 'browser', frameRate: 1 },
                audio: false,
                preferCurrentTab: true
            });

            const track = stream!.getVideoTracks()[0];
            if (!track) throw new Error('No video track in screen capture stream');

            let png: string;

            // Use ImageCapture API (Chrome/Edge) if available — cleaner than a <video> element
            if (typeof ImageCapture !== 'undefined') {
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                const ic = new (ImageCapture as any)(track);
                const bitmap = await ic.grabFrame();
                const canvas = document.createElement('canvas');
                canvas.width = bitmap.width;
                canvas.height = bitmap.height;
                const ctx = canvas.getContext('2d')!;
                ctx.drawImage(bitmap, 0, 0);
                bitmap.close();
                png = canvas.toDataURL('image/png');
            } else {
                // Fallback: attach stream to a hidden <video> element, then draw one frame
                const video = document.createElement('video');
                video.autoplay = true;
                video.muted = true;
                video.srcObject = stream;
                await new Promise<void>((resolve, reject) => {
                    video.onloadedmetadata = () => void video.play().then(resolve).catch(reject);
                    video.onerror = () => reject(new Error('Video load error'));
                    setTimeout(() => reject(new Error('Video load timeout')), 5000);
                });
                const canvas = document.createElement('canvas');
                canvas.width = video.videoWidth || 1280;
                canvas.height = video.videoHeight || 720;
                canvas.getContext('2d')!.drawImage(video, 0, 0);
                video.srcObject = null;
                png = canvas.toDataURL('image/png');
            }

            // Reject if the estimated decoded size exceeds 2 MB
            const estimatedBytes = Math.round(png.length * 0.75);
            if (estimatedBytes > 2 * 1024 * 1024) {
                screenshotError = $text('settings.report_issue.screenshot_size_too_large');
                screenshotDataUrl = null;
            } else {
                screenshotDataUrl = png;
                console.debug(
                    `[SettingsReportIssue] Screenshot captured: ~${Math.round(estimatedBytes / 1024)} KB PNG`
                );
            }
        } catch (error: unknown) {
            const err = error as { name?: string };
            if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
                screenshotError = $text('settings.report_issue.screenshot_permission_denied');
            } else {
                // On any other failure (NotSupportedError on iOS, etc.) reveal the upload fallback
                screenshotError = $text('settings.report_issue.screenshot_capture_failed');
                showUploadFallback = true;
                console.warn('[SettingsReportIssue] Screenshot capture failed:', error);
            }
        } finally {
            // Always stop the stream to close the browser's screen-share indicator
            stream?.getTracks().forEach(t => t.stop());
            isCapturingScreenshot = false;
        }
    }

    /**
     * Handle a file chosen via the upload fallback <input type="file">.
     * Reads the image as a base64 data URL and stores it in screenshotDataUrl.
     * Validates the 2 MB size limit before accepting.
     */
    function handleScreenshotUpload(event: Event) {
        screenshotError = '';
        const input = event.target as HTMLInputElement;
        const file = input.files?.[0];
        if (!file) return;

        if (file.size > 2 * 1024 * 1024) {
            screenshotError = $text('settings.report_issue.screenshot_size_too_large');
            input.value = '';
            return;
        }

        const reader = new FileReader();
        reader.onload = () => {
            const result = reader.result as string;
            screenshotDataUrl = result;
            console.debug(
                `[SettingsReportIssue] Screenshot uploaded: ~${Math.round(file.size / 1024)} KB`
            );
        };
        reader.onerror = () => {
            screenshotError = $text('settings.report_issue.screenshot_upload_failed');
            console.warn('[SettingsReportIssue] FileReader error on screenshot upload');
        };
        reader.readAsDataURL(file);
    }

    /** Remove the attached screenshot and clear any error. */
    function removeScreenshot() {
        screenshotDataUrl = null;
        screenshotError = '';
        // Reset the file input so the same file can be re-selected if needed
        if (screenshotFileInput) screenshotFileInput.value = '';
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
        const actionHistory = userActionTracker.getActionHistoryAsText();
        const activeChatSidebarHtml = collectActiveChatSidebarHtml();
        const runtimeDebugState = collectRuntimeDebugState();
        
        return {
            device_info: currentDeviceInfo,
            console_logs: consoleLogs,
            indexeddb_report: indexedDbReport,
            action_history: actionHistory,
            active_chat_id: $activeChatStore || null,
            active_embed_id: $activeEmbedStore || null,
            share_chat_enabled: shareChatEnabled,
            chat_or_embed_url: (shareChatEnabled && chatOrEmbedUrl) ? chatOrEmbedUrl : null,
            active_chat_sidebar_html: activeChatSidebarHtml,
            runtime_debug_state: runtimeDebugState,
            picked_element_html: pickedElementHtml ?? null,
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
    
    // Auto-generate share URL and collect initial device info when component mounts
    onMount(() => {
        // ── Priority order for pre-filling the form ──────────────────────────────
        // 1. reportIssueStore  — set by deep links / ChatMessage "Report" button.
        //    Applied first as the baseline.
        // 2. reportIssueFormDraftStore — set just before the picker overlay opens
        //    (when the settings panel closes and this component is destroyed).
        //    Applied second and takes precedence because it represents the user's
        //    most recent in-progress edits and must survive the unmount/remount cycle.
        //    If both stores are set simultaneously, the draft values win.

        // Check for pre-filled data from store (deep link / ChatMessage trigger)
        if ($reportIssueStore) {
            if ($reportIssueStore.title) issueTitle = $reportIssueStore.title;
            // Map legacy store description to the user flow field (most common pre-fill use-case)
            if ($reportIssueStore.description) userFlow = $reportIssueStore.description;
            // If a URL was passed directly (e.g. from deep link), pre-fill it
            if ($reportIssueStore.url) chatOrEmbedUrl = $reportIssueStore.url;
            // If the store requests sharing the chat, enable the toggle
            if ($reportIssueStore.shareChat) shareChatEnabled = true;
            
            // Clear store after consuming
            reportIssueStore.set(null);
        }

        // Restore in-progress form draft (survives settings panel close/reopen during picker)
        // This must run AFTER reportIssueStore so draft values take precedence over deep-link
        // pre-fills (the user may have already edited the pre-filled values before picking).
        const draft = $reportIssueFormDraftStore;
        if (draft) {
            issueTitle = draft.issueTitle;
            userFlow = draft.userFlow;
            expectedBehaviour = draft.expectedBehaviour;
            actualBehaviour = draft.actualBehaviour;
            shareChatEnabled = draft.shareChatEnabled;
            chatOrEmbedUrl = draft.chatOrEmbedUrl;
            contactEmail = draft.contactEmail;
            includeEmailToggle = draft.includeEmailToggle;
            pickedElementHtml = draft.pickedElementHtml;
            screenshotDataUrl = draft.screenshotDataUrl;
            // Clear the draft now that it has been consumed
            reportIssueFormDraftStore.set(null);
            console.debug('[SettingsReportIssue] Restored form draft from store after remount');
        }

        // For authenticated users, load their account email so it can be pre-filled
        // in the "include email" toggle hint.
        if ($authStore.isAuthenticated) {
            getEmailDecryptedWithMasterKey()
                .then((email) => {
                    if (email) {
                        authenticatedUserEmail = email;
                    }
                })
                .catch((error) => {
                    // Non-fatal: user can still submit without an email
                    console.warn('[SettingsReportIssue] Failed to load account email for toggle hint:', error);
                });
        }

        // Small delay to ensure stores are initialized
        setTimeout(() => {
            autoGenerateShareUrl();
            // Collect initial device info to show in the form
            deviceInfo = collectDeviceInfo();
        }, 100);
    });
</script>

<div class="report-issue-settings" data-section="report-issue">
    <p>{$text('settings.report_issue.description')}</p>
    
    <!-- Issue Report Form -->
    <div class="report-issue-form">
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
        
        <!-- User Flow — "What did you do?" (optional) -->
        <div class="input-group">
            <label for="user-flow">{$text('settings.report_issue.user_flow_label')}</label>
            <div class="input-wrapper">
                <textarea
                    id="user-flow"
                    bind:this={userFlowInput}
                    placeholder={$text('settings.report_issue.user_flow_placeholder')}
                    bind:value={userFlow}
                    disabled={isSubmitting}
                    aria-label={$text('settings.report_issue.user_flow_label')}
                    rows="3"
                ></textarea>
            </div>
            <p class="input-hint">{$text('settings.report_issue.user_flow_hint')}</p>
        </div>

        <!-- Expected Behaviour (optional) -->
        <div class="input-group">
            <label for="expected-behaviour">{$text('settings.report_issue.expected_behaviour_label')}</label>
            <div class="input-wrapper">
                <textarea
                    id="expected-behaviour"
                    placeholder={$text('settings.report_issue.expected_behaviour_placeholder')}
                    bind:value={expectedBehaviour}
                    disabled={isSubmitting}
                    aria-label={$text('settings.report_issue.expected_behaviour_label')}
                    rows="2"
                ></textarea>
            </div>
            <p class="input-hint">{$text('settings.report_issue.expected_behaviour_hint')}</p>
        </div>

        <!-- Actual Behaviour (optional) -->
        <div class="input-group">
            <label for="actual-behaviour">{$text('settings.report_issue.actual_behaviour_label')}</label>
            <div class="input-wrapper">
                <textarea
                    id="actual-behaviour"
                    placeholder={$text('settings.report_issue.actual_behaviour_placeholder')}
                    bind:value={actualBehaviour}
                    disabled={isSubmitting}
                    aria-label={$text('settings.report_issue.actual_behaviour_label')}
                    rows="2"
                ></textarea>
            </div>
            <p class="input-hint">{$text('settings.report_issue.actual_behaviour_hint')}</p>
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
        
        <!-- Contact Email Section -->
        <!-- Authenticated users: toggle to include their account email (on by default) -->
        <!-- Guest users: free-text email input (optional) -->
        {#if $authStore.isAuthenticated}
            <div class="toggle-group">
                <div class="toggle-row">
                    <label for="include-email-toggle">{$text('settings.report_issue.email_toggle_label')}</label>
                    <Toggle
                        id="include-email-toggle"
                        bind:checked={includeEmailToggle}
                        disabled={isSubmitting}
                        ariaLabel={$text('settings.report_issue.email_toggle_label')}
                    />
                </div>
                <p class="input-hint">
                    {#if includeEmailToggle && authenticatedUserEmail}
                        {$text('settings.report_issue.email_toggle_hint').replace('{email}', authenticatedUserEmail)}
                    {:else if includeEmailToggle}
                        <!-- Email not yet loaded; show a neutral hint while loading -->
                        {$text('settings.report_issue.email_hint')}
                    {:else}
                        {$text('settings.report_issue.email_toggle_off_hint')}
                    {/if}
                </p>
            </div>
        {:else}
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
        {/if}

        <!-- DOM Element Picker — all users (guest and authenticated) -->
        <!-- Lets the user tap/click any broken UI element to capture its HTML for debugging. -->
        <!-- The settings panel temporarily closes while the picker overlay is active. -->
        <div class="input-group element-picker-section">
            <p class="input-label">{$text('settings.report_issue.element_picker_label')}</p>
            <p class="input-hint">{$text('settings.report_issue.element_picker_hint')}</p>

            {#if pickedElementHtml}
                <!-- Preview of the captured element HTML + action buttons -->
                <div class="picked-element-preview">
                    <details class="picked-element-details">
                        <summary class="picked-element-summary">
                            {$text('settings.report_issue.element_picker_preview_label')}
                        </summary>
                        <pre class="picked-element-html">{pickedElementHtml}</pre>
                    </details>
                    <div class="picked-element-actions">
                        <button
                            type="button"
                            class="element-picker-copy-btn"
                            class:success={copyElementHtmlSuccess}
                            onclick={copyPickedElementHtml}
                            disabled={isSubmitting || isCopyingElementHtml}
                        >
                            {copyElementHtmlSuccess
                                ? $text('settings.report_issue.element_picker_copied')
                                : $text('settings.report_issue.element_picker_copy')}
                        </button>
                        <button
                            type="button"
                            class="element-picker-remove-btn"
                            onclick={removePickedElement}
                            disabled={isSubmitting}
                        >
                            {$text('settings.report_issue.element_picker_remove')}
                        </button>
                    </div>
                </div>
            {:else}
                <!-- Start picker button -->
                <button
                    type="button"
                    class="element-picker-btn"
                    class:active={isPickerActive}
                    onclick={startElementPicker}
                    disabled={isSubmitting || isPickerActive}
                >
                    {isPickerActive
                        ? $text('settings.report_issue.element_picker_active')
                        : $text('settings.report_issue.element_picker_button')}
                </button>
            {/if}
        </div>

        <!-- Screenshot Capture — authenticated users only -->
        {#if $authStore.isAuthenticated}
            <div class="input-group screenshot-section">
                <p class="input-label">{$text('settings.report_issue.screenshot_label')}</p>
                <p class="input-hint">{$text('settings.report_issue.screenshot_hint')}</p>

                {#if screenshotDataUrl}
                    <!-- Preview + remove -->
                    <div class="screenshot-preview-wrapper">
                        <img
                            src={screenshotDataUrl}
                            alt={$text('settings.report_issue.screenshot_preview_alt')}
                            class="screenshot-preview"
                        />
                        <button
                            type="button"
                            class="screenshot-remove-btn"
                            onclick={removeScreenshot}
                            disabled={isSubmitting}
                        >
                            {$text('settings.report_issue.screenshot_remove')}
                        </button>
                    </div>
                {:else if showUploadFallback}
                    <!-- Upload fallback — shown on iOS or after a non-permission capture failure -->
                    <!-- Hidden file input; the visible styled button triggers it -->
                    <input
                        bind:this={screenshotFileInput}
                        type="file"
                        accept="image/*"
                        class="screenshot-file-input"
                        onchange={handleScreenshotUpload}
                        disabled={isSubmitting}
                        aria-label={$text('settings.report_issue.screenshot_upload_button')}
                    />
                    <button
                        type="button"
                        class="screenshot-capture-btn"
                        onclick={() => screenshotFileInput?.click()}
                        disabled={isSubmitting}
                    >
                        {$text('settings.report_issue.screenshot_upload_button')}
                    </button>
                {:else}
                    <!-- Screen capture button — desktop browsers with getDisplayMedia support -->
                    <button
                        type="button"
                        class="screenshot-capture-btn"
                        onclick={captureScreenshot}
                        disabled={isCapturingScreenshot || isSubmitting}
                    >
                        {isCapturingScreenshot
                            ? $text('settings.report_issue.screenshot_capturing')
                            : $text('settings.report_issue.screenshot_capture_button')}
                    </button>
                {/if}

                {#if screenshotError}
                    <p class="screenshot-error">{screenshotError}</p>
                {/if}
            </div>
        {/if}

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

            <!-- Recent user-action history (last 20 interactions, button names / navigation only) -->
            <div class="action-history-section">
                <h5 class="action-history-heading">{$text('settings.report_issue.action_history_heading')}</h5>
                <p class="action-history-description">{$text('settings.report_issue.action_history_description')}</p>
                {#if userActionTracker.getActionHistory().length === 0}
                    <p class="action-history-empty">{$text('settings.report_issue.action_history_empty')}</p>
                {:else}
                    <ul class="action-history-list">
                        {#each userActionTracker.getActionHistory().slice(-10).reverse() as entry}
                            <li class="action-history-entry">
                                <span class="action-type action-type-{entry.type}">{entry.type}</span>
                                <span class="action-label">{entry.action}</span>
                                {#if entry.key}
                                    <span class="action-key">[{entry.key}]</span>
                                {/if}
                            </li>
                        {/each}
                    </ul>
                {/if}
            </div>

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
    
    .input-group label,
    .input-label {
        font-size: 14px;
        font-weight: 500;
        color: var(--color-font-primary);
        margin: 0;
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
    
    .input-wrapper input.error {
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

    /* ---- User action history section ---- */
    .action-history-section {
        margin: 14px 0 0 0;
        padding-top: 12px;
        border-top: 1px solid var(--color-info, #2196f3);
    }

    .action-history-heading {
        margin: 0 0 4px 0;
        font-size: 13px;
        font-weight: 600;
        color: var(--color-info-dark, #1565c0);
    }

    .action-history-description {
        font-size: 11px;
        color: var(--color-info-dark, #1565c0);
        margin: 0 0 8px 0;
        line-height: 1.4;
        opacity: 0.8;
        font-style: italic;
    }

    .action-history-empty {
        font-size: 12px;
        color: var(--color-info-dark, #1565c0);
        margin: 0;
        opacity: 0.6;
        font-style: italic;
    }

    .action-history-list {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: 3px;
    }

    .action-history-entry {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 11px;
        font-family: monospace;
        color: var(--color-info-dark, #1565c0);
        line-height: 1.4;
    }

    /* Colour-coded type badges */
    .action-type {
        display: inline-block;
        padding: 1px 5px;
        border-radius: 3px;
        font-size: 10px;
        font-weight: 600;
        text-transform: uppercase;
        flex-shrink: 0;
        min-width: 52px;
        text-align: center;
        background-color: rgba(0, 0, 0, 0.08);
    }

    .action-type-click {
        background-color: rgba(33, 150, 243, 0.15);
        color: var(--color-info-dark, #1565c0);
    }

    .action-type-focus {
        background-color: rgba(76, 175, 80, 0.15);
        color: var(--color-success-dark, #2e7d32);
    }

    .action-type-keypress {
        background-color: rgba(255, 152, 0, 0.15);
        color: #e65100;
    }

    .action-label {
        flex: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .action-key {
        flex-shrink: 0;
        opacity: 0.7;
        font-size: 10px;
    }

    /* ===================== SCREENSHOT SECTION ===================== */

    .screenshot-section {
        gap: 8px;
    }

    .screenshot-capture-btn {
        align-self: flex-start;
        padding: 8px 16px;
        border: 1px solid var(--color-border, #ccc);
        border-radius: var(--border-radius-md, 6px);
        background: var(--color-surface-2, #f5f5f5);
        color: var(--color-text, #222);
        font-size: 14px;
        cursor: pointer;
        transition: background 0.15s;
    }

    .screenshot-capture-btn:hover:not(:disabled) {
        background: var(--color-surface-3, #e8e8e8);
    }

    .screenshot-capture-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .screenshot-preview-wrapper {
        display: flex;
        flex-direction: column;
        gap: 8px;
        align-items: flex-start;
    }

    .screenshot-preview {
        max-width: 100%;
        max-height: 200px;
        border-radius: var(--border-radius-md, 6px);
        border: 1px solid var(--color-border, #ccc);
        object-fit: contain;
    }

    .screenshot-remove-btn {
        padding: 6px 12px;
        border: 1px solid var(--color-danger, #e53935);
        border-radius: var(--border-radius-md, 6px);
        background: transparent;
        color: var(--color-danger, #e53935);
        font-size: 13px;
        cursor: pointer;
        transition: background 0.15s;
    }

    .screenshot-remove-btn:hover:not(:disabled) {
        background: rgba(229, 57, 53, 0.08);
    }

    .screenshot-remove-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .screenshot-error {
        font-size: 13px;
        color: var(--color-danger, #e53935);
        margin: 0;
    }

    /* Hide the native file input — the styled button triggers it programmatically */
    .screenshot-file-input {
        display: none;
    }

    /* ===================== ELEMENT PICKER SECTION ===================== */

    .element-picker-section {
        gap: 8px;
    }

    /* "Pick Element" button — matches screenshot-capture-btn style */
    .element-picker-btn {
        align-self: flex-start;
        padding: 8px 16px;
        border: 1px solid var(--color-border, #ccc);
        border-radius: var(--border-radius-md, 6px);
        background: var(--color-surface-2, #f5f5f5);
        color: var(--color-text, #222);
        font-size: 14px;
        cursor: pointer;
        transition: background 0.15s, border-color 0.15s;
    }

    .element-picker-btn:hover:not(:disabled) {
        background: var(--color-surface-3, #e8e8e8);
    }

    .element-picker-btn.active {
        border-color: var(--color-primary, #1976d2);
        color: var(--color-primary, #1976d2);
    }

    .element-picker-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    /* Preview box shown after an element is captured */
    .picked-element-preview {
        display: flex;
        flex-direction: column;
        gap: 8px;
        align-items: flex-start;
        width: 100%;
    }

    .picked-element-details {
        width: 100%;
        border: 1px solid var(--color-border, #ccc);
        border-radius: var(--border-radius-md, 6px);
        overflow: hidden;
    }

    .picked-element-summary {
        padding: 8px 12px;
        font-size: 13px;
        color: var(--color-font-secondary, #555);
        cursor: pointer;
        user-select: none;
        background: var(--color-grey-20, #f5f5f5);
        list-style: none;
    }

    .picked-element-summary::marker,
    .picked-element-summary::-webkit-details-marker {
        display: none;
    }

    .picked-element-summary::before {
        content: '▶ ';
        font-size: 10px;
        opacity: 0.6;
        margin-right: 4px;
        transition: transform 0.15s;
    }

    .picked-element-details[open] .picked-element-summary::before {
        content: '▼ ';
    }

    /* Scrollable pre block showing the captured outerHTML */
    .picked-element-html {
        margin: 0;
        padding: 10px 12px;
        font-size: 11px;
        font-family: monospace;
        line-height: 1.5;
        white-space: pre-wrap;
        word-break: break-all;
        max-height: 180px;
        overflow-y: auto;
        background: var(--color-grey-10, #fafafa);
        color: var(--color-font-primary, #222);
        border-top: 1px solid var(--color-border, #ccc);
    }

    /* Row holding Copy HTML + Remove buttons */
    .picked-element-actions {
        display: flex;
        gap: 8px;
        align-items: center;
        flex-wrap: wrap;
    }

    /* Copy HTML button */
    .element-picker-copy-btn {
        padding: 6px 12px;
        border: 1px solid var(--color-border, #ccc);
        border-radius: var(--border-radius-md, 6px);
        background: var(--color-surface-2, #f5f5f5);
        color: var(--color-font-primary, #222);
        font-size: 13px;
        cursor: pointer;
        transition: background 0.15s, border-color 0.15s, color 0.15s;
    }

    .element-picker-copy-btn:hover:not(:disabled) {
        background: var(--color-surface-3, #e8e8e8);
    }

    .element-picker-copy-btn.success {
        border-color: var(--color-success, #4caf50);
        color: var(--color-success-dark, #2e7d32);
        background: var(--color-success-light, #e8f5e9);
    }

    .element-picker-copy-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    /* Remove button — matches screenshot-remove-btn style */
    .element-picker-remove-btn {
        padding: 6px 12px;
        border: 1px solid var(--color-danger, #e53935);
        border-radius: var(--border-radius-md, 6px);
        background: transparent;
        color: var(--color-danger, #e53935);
        font-size: 13px;
        cursor: pointer;
        transition: background 0.15s;
    }

    .element-picker-remove-btn:hover:not(:disabled) {
        background: rgba(229, 57, 53, 0.08);
    }

    .element-picker-remove-btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
</style>
