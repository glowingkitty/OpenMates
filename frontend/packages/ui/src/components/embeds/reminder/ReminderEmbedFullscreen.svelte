<!--
  frontend/packages/ui/src/components/embeds/reminder/ReminderEmbedFullscreen.svelte
  
  Fullscreen view for Reminder embeds.
  Uses UnifiedEmbedFullscreen as base and provides reminder-specific content.
  
  Shows:
  - Reminder details (trigger time, target type, repeating status)
  - Cancel reminder button
  - Email notification warning if applicable
  - Basic infos bar at the bottom
-->

<script lang="ts">
  import UnifiedEmbedFullscreen from '../UnifiedEmbedFullscreen.svelte';
  import { text } from '@repo/ui';
  import { notificationStore } from '../../../stores/notificationStore';
  
  /**
   * Props for reminder embed fullscreen
   */
  interface Props {
    /** Reminder ID */
    reminderId?: string;
    /** Human-readable trigger time */
    triggerAtFormatted?: string;
    /** Unix timestamp of trigger */
    triggerAt?: number;
    /** Target type: new_chat or existing_chat */
    targetType?: 'new_chat' | 'existing_chat';
    /** Whether this is a repeating reminder */
    isRepeating?: boolean;
    /** Confirmation message from the skill */
    message?: string;
    /** Warning about email notifications */
    emailNotificationWarning?: string;
    /** Error message if any */
    error?: string;
    /** Close handler */
    onClose: () => void;
    /** Optional: Embed ID for sharing */
    embedId?: string;
    /** Whether there is a previous embed to navigate to */
    hasPreviousEmbed?: boolean;
    /** Whether there is a next embed to navigate to */
    hasNextEmbed?: boolean;
    /** Handler to navigate to the previous embed */
    onNavigatePrevious?: () => void;
    /** Handler to navigate to the next embed */
    onNavigateNext?: () => void;
    /** Whether to show the "chat" button */
    showChatButton?: boolean;
    /** Callback when user clicks the "chat" button */
    onShowChat?: () => void;
    /** Optional callback when reminder is cancelled */
    onReminderCancelled?: (reminderId: string) => void;
  }
  
  let {
    reminderId,
    triggerAtFormatted,
    triggerAt,
    targetType,
    isRepeating = false,
    message,
    emailNotificationWarning,
    error,
    onClose,
    embedId,
    hasPreviousEmbed = false,
    hasNextEmbed = false,
    onNavigatePrevious,
    onNavigateNext,
    showChatButton = false,
    onShowChat,
    onReminderCancelled
  }: Props = $props();
  
  // State for cancel operation
  let isCancelling = $state(false);
  let cancelError = $state<string | undefined>(undefined);
  let isCancelled = $state(false);
  
  // Build skill name for BasicInfosBar
  let skillName = $derived($text('apps.reminder.skills.set_reminder.text'));
  
  // Build status text
  let statusText = $derived.by(() => {
    if (isCancelled) {
      return $text('embeds.reminder.cancelled.text');
    }
    if (error) {
      return $text('embeds.error.text');
    }
    if (triggerAtFormatted) {
      return triggerAtFormatted;
    }
    return '';
  });
  
  // Get target type display text
  let targetTypeText = $derived.by(() => {
    if (targetType === 'new_chat') {
      return $text('embeds.reminder.new_chat.text');
    }
    if (targetType === 'existing_chat') {
      return $text('embeds.reminder.existing_chat.text');
    }
    return '';
  });
  
  // Check if reminder is still active (not cancelled, not in the past)
  let isReminderActive = $derived.by(() => {
    if (isCancelled) return false;
    if (!triggerAt) return false;
    // Check if trigger time is in the future
    const now = Date.now() / 1000; // Convert to Unix timestamp
    return triggerAt > now;
  });
  
  // Icon for reminders
  const skillIconName = 'reminder';
  
  /**
   * Handle cancel reminder action
   * This would typically call an API or dispatch an event to cancel the reminder
   */
  async function handleCancelReminder() {
    if (!reminderId || isCancelling || isCancelled) return;
    
    isCancelling = true;
    cancelError = undefined;
    
    try {
      console.debug('[ReminderEmbedFullscreen] Cancelling reminder:', reminderId);
      
      // TODO: Implement actual cancel API call
      // For now, we'll simulate the cancel action
      // The actual implementation would call the cancel-reminder skill via WebSocket
      // or through a dedicated API endpoint
      
      // Simulate API call delay
      await new Promise(resolve => setTimeout(resolve, 500));
      
      // Mark as cancelled
      isCancelled = true;
      
      // Notify parent component
      if (onReminderCancelled) {
        onReminderCancelled(reminderId);
      }
      
      notificationStore.success($text('embeds.reminder.cancel_success.text'));
      console.debug('[ReminderEmbedFullscreen] Reminder cancelled successfully');
    } catch (err) {
      console.error('[ReminderEmbedFullscreen] Failed to cancel reminder:', err);
      cancelError = err instanceof Error ? err.message : 'Unknown error';
      notificationStore.error($text('embeds.reminder.cancel_error.text'));
    } finally {
      isCancelling = false;
    }
  }
</script>

<UnifiedEmbedFullscreen
  appId="reminder"
  skillId="set-reminder"
  {skillIconName}
  {skillName}
  showStatus={true}
  customStatusText={statusText}
  showSkillIcon={false}
  title=""
  {onClose}
  {embedId}
  {hasPreviousEmbed}
  {hasNextEmbed}
  {onNavigatePrevious}
  {onNavigateNext}
  {showChatButton}
  {onShowChat}
>
  {#snippet content()}
    <div class="reminder-fullscreen">
      {#if error}
        <!-- Error state -->
        <div class="error-container">
          <div class="error-icon">&#10060;</div>
          <h3 class="error-title">{$text('embeds.reminder.error.text')}</h3>
          <p class="error-message">{error}</p>
        </div>
      {:else if isCancelled}
        <!-- Cancelled state -->
        <div class="cancelled-container">
          <div class="cancelled-icon">&#9989;</div>
          <h3 class="cancelled-title">{$text('embeds.reminder.cancelled.text')}</h3>
          <p class="cancelled-message">{$text('embeds.reminder.cancelled_message.text')}</p>
        </div>
      {:else}
        <!-- Normal reminder display -->
        <div class="reminder-content">
          <!-- Main reminder info card -->
          <div class="reminder-card">
            <!-- Trigger time - prominently displayed -->
            {#if triggerAtFormatted}
              <div class="trigger-time-section">
                <span class="trigger-icon">&#128337;</span>
                <div class="trigger-info">
                  <span class="trigger-label">{$text('embeds.reminder.scheduled_for.text')}</span>
                  <span class="trigger-time">{triggerAtFormatted}</span>
                </div>
              </div>
            {/if}
            
            <!-- Reminder properties -->
            <div class="reminder-properties">
              <!-- Target type -->
              {#if targetType}
                <div class="property-row">
                  <span class="property-label">{$text('embeds.reminder.target_type.text')}</span>
                  <span class="property-value badge" class:new-chat={targetType === 'new_chat'} class:existing-chat={targetType === 'existing_chat'}>
                    {targetTypeText}
                  </span>
                </div>
              {/if}
              
              <!-- Repeating status -->
              <div class="property-row">
                <span class="property-label">{$text('embeds.reminder.repeating.text')}</span>
                <span class="property-value">
                  {#if isRepeating}
                    <span class="badge repeat-badge">{$text('embeds.reminder.yes.text')}</span>
                  {:else}
                    {$text('embeds.reminder.no.text')}
                  {/if}
                </span>
              </div>
              
              <!-- Reminder ID (for reference) -->
              {#if reminderId}
                <div class="property-row">
                  <span class="property-label">{$text('embeds.reminder.id.text')}</span>
                  <span class="property-value id-value">{reminderId.slice(0, 8)}...</span>
                </div>
              {/if}
            </div>
            
            <!-- Email warning if present -->
            {#if emailNotificationWarning}
              <div class="email-warning">
                <span class="warning-icon">&#9888;</span>
                <span class="warning-text">{emailNotificationWarning}</span>
              </div>
            {/if}
          </div>
          
          <!-- Action buttons -->
          <div class="action-buttons">
            {#if isReminderActive}
              <button 
                class="action-btn cancel-btn" 
                onclick={handleCancelReminder}
                disabled={isCancelling}
              >
                {#if isCancelling}
                  <span class="spinner"></span>
                  <span>{$text('embeds.reminder.cancelling.text')}</span>
                {:else}
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="15" y1="9" x2="9" y2="15"></line>
                    <line x1="9" y1="9" x2="15" y2="15"></line>
                  </svg>
                  <span>{$text('embeds.reminder.cancel.text')}</span>
                {/if}
              </button>
            {:else if !isCancelled}
              <div class="inactive-notice">
                <span class="notice-icon">&#8987;</span>
                <span>{$text('embeds.reminder.already_fired.text')}</span>
              </div>
            {/if}
          </div>
          
          <!-- Cancel error if any -->
          {#if cancelError}
            <div class="cancel-error">
              <span class="error-icon-small">&#10060;</span>
              <span>{cancelError}</span>
            </div>
          {/if}
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedFullscreen>

<style>
  .reminder-fullscreen {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    overflow: auto;
    padding: 24px;
    box-sizing: border-box;
  }
  
  /* Error container */
  .error-container,
  .cancelled-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    min-height: 200px;
    text-align: center;
    padding: 32px;
  }
  
  .error-icon,
  .cancelled-icon {
    font-size: 48px;
    margin-bottom: 16px;
  }
  
  .error-title,
  .cancelled-title {
    font-size: 18px;
    font-weight: 600;
    margin: 0 0 8px 0;
    color: var(--color-grey-90, #1a1a1a);
  }
  
  .error-message,
  .cancelled-message {
    font-size: 14px;
    color: var(--color-grey-60, #666);
    margin: 0;
    max-width: 400px;
  }
  
  /* Reminder content */
  .reminder-content {
    display: flex;
    flex-direction: column;
    gap: 20px;
    max-width: 500px;
    margin: 0 auto;
    width: 100%;
  }
  
  /* Reminder card */
  .reminder-card {
    background: var(--color-grey-5, #fafafa);
    border: 1px solid var(--color-grey-15, #f0f0f0);
    border-radius: 12px;
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  
  /* Trigger time section */
  .trigger-time-section {
    display: flex;
    align-items: center;
    gap: 12px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--color-grey-15, #f0f0f0);
  }
  
  .trigger-icon {
    font-size: 32px;
    flex-shrink: 0;
  }
  
  .trigger-info {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  
  .trigger-label {
    font-size: 12px;
    color: var(--color-grey-50, #888);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
  
  .trigger-time {
    font-size: 18px;
    font-weight: 600;
    color: var(--color-grey-90, #1a1a1a);
  }
  
  /* Properties */
  .reminder-properties {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  
  .property-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  
  .property-label {
    font-size: 14px;
    color: var(--color-grey-60, #666);
  }
  
  .property-value {
    font-size: 14px;
    color: var(--color-grey-90, #1a1a1a);
    font-weight: 500;
  }
  
  .property-value.id-value {
    font-family: monospace;
    font-size: 12px;
    color: var(--color-grey-50, #888);
  }
  
  /* Badges */
  .badge {
    display: inline-flex;
    align-items: center;
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 500;
  }
  
  .badge.new-chat {
    background: var(--color-primary-10, #e8f0ff);
    color: var(--color-primary-70, #4a6eb0);
  }
  
  .badge.existing-chat {
    background: var(--color-success-10, #e8fff0);
    color: var(--color-success-70, #4ab06a);
  }
  
  .repeat-badge {
    background: var(--color-warning-10, #fff8e8);
    color: var(--color-warning-70, #b08a4a);
  }
  
  /* Email warning */
  .email-warning {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 12px;
    background: var(--color-warning-5, #fffdf5);
    border-radius: 8px;
    border: 1px solid var(--color-warning-20, #f5e6c0);
    margin-top: 4px;
  }
  
  .warning-icon {
    font-size: 16px;
    color: var(--color-warning-60, #c9a02d);
    flex-shrink: 0;
  }
  
  .warning-text {
    font-size: 13px;
    color: var(--color-warning-80, #8a6b1a);
    line-height: 1.4;
  }
  
  /* Action buttons */
  .action-buttons {
    display: flex;
    justify-content: center;
    gap: 12px;
    margin-top: 8px;
  }
  
  .action-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 12px 24px;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s ease;
    border: none;
  }
  
  .action-btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
  
  .cancel-btn {
    background: var(--color-error-10, #fff5f5);
    color: var(--color-error-70, #b04a4a);
    border: 1px solid var(--color-error-30, #f0c0c0);
  }
  
  .cancel-btn:hover:not(:disabled) {
    background: var(--color-error-15, #ffefef);
    border-color: var(--color-error-40, #e0a0a0);
  }
  
  .cancel-btn:active:not(:disabled) {
    transform: scale(0.98);
  }
  
  .cancel-btn svg {
    flex-shrink: 0;
  }
  
  /* Spinner */
  .spinner {
    width: 16px;
    height: 16px;
    border: 2px solid var(--color-error-30, #f0c0c0);
    border-top-color: var(--color-error-70, #b04a4a);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  
  @keyframes spin {
    to { transform: rotate(360deg); }
  }
  
  /* Inactive notice */
  .inactive-notice {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 16px;
    background: var(--color-grey-10, #f5f5f5);
    border-radius: 8px;
    font-size: 13px;
    color: var(--color-grey-60, #666);
  }
  
  .notice-icon {
    font-size: 16px;
  }
  
  /* Cancel error */
  .cancel-error {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 10px;
    background: var(--color-error-5, #fff5f5);
    border-radius: 6px;
    font-size: 13px;
    color: var(--color-error-70, #b04a4a);
  }
  
  .error-icon-small {
    font-size: 14px;
  }
  
  /* Dark mode */
  :global(.dark) .error-title,
  :global(.dark) .cancelled-title {
    color: var(--color-grey-10, #f5f5f5);
  }
  
  :global(.dark) .error-message,
  :global(.dark) .cancelled-message {
    color: var(--color-grey-40, #999);
  }
  
  :global(.dark) .reminder-card {
    background: var(--color-grey-90, #1a1a1a);
    border-color: var(--color-grey-80, #333);
  }
  
  :global(.dark) .trigger-time-section {
    border-bottom-color: var(--color-grey-80, #333);
  }
  
  :global(.dark) .trigger-time {
    color: var(--color-grey-10, #f5f5f5);
  }
  
  :global(.dark) .property-label {
    color: var(--color-grey-50, #888);
  }
  
  :global(.dark) .property-value {
    color: var(--color-grey-20, #eaeaea);
  }
  
  :global(.dark) .badge.new-chat {
    background: var(--color-primary-90, #1a2540);
    color: var(--color-primary-40, #7a9ed0);
  }
  
  :global(.dark) .badge.existing-chat {
    background: var(--color-success-90, #1a4025);
    color: var(--color-success-40, #7ad09a);
  }
  
  :global(.dark) .repeat-badge {
    background: var(--color-warning-90, #40351a);
    color: var(--color-warning-40, #d0ba7a);
  }
  
  :global(.dark) .email-warning {
    background: var(--color-warning-95, #2a2515);
    border-color: var(--color-warning-80, #8a6b1a);
  }
  
  :global(.dark) .warning-text {
    color: var(--color-warning-40, #d0ba7a);
  }
  
  :global(.dark) .cancel-btn {
    background: var(--color-error-90, #2a1515);
    border-color: var(--color-error-70, #8a1a1a);
    color: var(--color-error-40, #d07a7a);
  }
  
  :global(.dark) .cancel-btn:hover:not(:disabled) {
    background: var(--color-error-85, #351a1a);
  }
  
  :global(.dark) .inactive-notice {
    background: var(--color-grey-85, #252525);
    color: var(--color-grey-50, #888);
  }
  
  :global(.dark) .cancel-error {
    background: var(--color-error-95, #2a1515);
    color: var(--color-error-40, #d07a7a);
  }
  
  /* Responsive */
  @media (max-width: 768px) {
    .reminder-fullscreen {
      padding: 16px;
    }
    
    .reminder-card {
      padding: 16px;
    }
    
    .trigger-icon {
      font-size: 28px;
    }
    
    .trigger-time {
      font-size: 16px;
    }
    
    .action-btn {
      padding: 10px 20px;
      font-size: 13px;
    }
  }
</style>
