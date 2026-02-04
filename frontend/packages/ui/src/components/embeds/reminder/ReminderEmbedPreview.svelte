<!--
  frontend/packages/ui/src/components/embeds/reminder/ReminderEmbedPreview.svelte
  
  Preview component for Reminder embeds.
  Uses UnifiedEmbedPreview as base and provides reminder-specific details content.
  
  Shows:
  - Reminder prompt/message preview
  - Trigger time (formatted)
  - Target type (new chat vs existing chat)
  - Repeat info if applicable
  
  Actions available in fullscreen:
  - Cancel reminder
  - Modify reminder (future)
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { text } from '@repo/ui';
  
  /**
   * Reminder embed data structure from skill response
   */
  interface ReminderData {
    reminder_id?: string;
    trigger_at?: number;
    trigger_at_formatted?: string;
    target_type?: 'new_chat' | 'existing_chat';
    is_repeating?: boolean;
    message?: string;
    email_notification_warning?: string;
    error?: string;
    success?: boolean;
  }
  
  /**
   * Props for reminder embed preview
   */
  interface Props {
    /** Unique embed ID */
    id: string;
    /** Reminder ID from the skill response */
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
    /** Processing status */
    status: 'processing' | 'finished' | 'error';
    /** Error message if any */
    error?: string;
    /** Task ID for cancellation */
    taskId?: string;
    /** Whether to use mobile layout */
    isMobile?: boolean;
    /** Click handler for fullscreen */
    onFullscreen?: () => void;
  }
  
  let {
    id,
    reminderId: reminderIdProp,
    triggerAtFormatted: triggerAtFormattedProp,
    triggerAt: triggerAtProp,
    targetType: targetTypeProp,
    isRepeating: isRepeatingProp = false,
    message: messageProp,
    emailNotificationWarning: emailWarningProp,
    status: statusProp,
    error: errorProp,
    taskId: taskIdProp,
    isMobile = false,
    onFullscreen
  }: Props = $props();
  
  // Local reactive state - can be updated via onEmbedDataUpdated callback
  let localReminderId = $state<string | undefined>(undefined);
  let localTriggerAtFormatted = $state<string | undefined>(undefined);
  let localTriggerAt = $state<number | undefined>(undefined);
  let localTargetType = $state<'new_chat' | 'existing_chat' | undefined>(undefined);
  let localIsRepeating = $state<boolean>(false);
  let localMessage = $state<string | undefined>(undefined);
  let localEmailWarning = $state<string | undefined>(undefined);
  let localStatus = $state<'processing' | 'finished' | 'error'>('processing');
  let localError = $state<string | undefined>(undefined);
  let localTaskId = $state<string | undefined>(undefined);
  
  // Initialize local state from props
  $effect(() => {
    localReminderId = reminderIdProp;
    localTriggerAtFormatted = triggerAtFormattedProp;
    localTriggerAt = triggerAtProp;
    localTargetType = targetTypeProp;
    localIsRepeating = isRepeatingProp || false;
    localMessage = messageProp;
    localEmailWarning = emailWarningProp;
    localStatus = statusProp || 'processing';
    localError = errorProp;
    localTaskId = taskIdProp;
  });
  
  // Use local state as source of truth
  let reminderId = $derived(localReminderId);
  let triggerAtFormatted = $derived(localTriggerAtFormatted);
  let triggerAt = $derived(localTriggerAt);
  let targetType = $derived(localTargetType);
  let isRepeating = $derived(localIsRepeating);
  let message = $derived(localMessage);
  let emailWarning = $derived(localEmailWarning);
  let status = $derived(localStatus);
  let error = $derived(localError);
  let taskId = $derived(localTaskId);
  
  // Icon for reminders
  const skillIconName = 'reminder';
  
  // Build skill name for BasicInfosBar
  let skillName = $derived.by(() => {
    if (status === 'error' && error) {
      return $text('apps.reminder.skills.set_reminder.text');
    }
    return $text('apps.reminder.skills.set_reminder.text');
  });
  
  // Build status text
  let statusText = $derived.by(() => {
    if (status === 'processing') {
      return $text('embeds.reminder.scheduling.text');
    }
    if (status === 'error') {
      return $text('embeds.reminder.error.text');
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
  
  /**
   * Handle embed data updates from server
   * Updates local state when embed status changes
   */
  function handleEmbedDataUpdated(data: { status: string; decodedContent: Record<string, unknown> | null }) {
    console.debug('[ReminderEmbedPreview] Received embed data update:', {
      embedId: id,
      status: data.status,
      hasContent: !!data.decodedContent
    });
    
    // Update status
    if (data.status === 'processing' || data.status === 'finished' || data.status === 'error') {
      localStatus = data.status;
    }
    
    // Update content from decoded data
    if (data.decodedContent) {
      const content = data.decodedContent as ReminderData;
      
      if (content.reminder_id) localReminderId = content.reminder_id;
      if (content.trigger_at_formatted) localTriggerAtFormatted = content.trigger_at_formatted;
      if (content.trigger_at) localTriggerAt = content.trigger_at;
      if (content.target_type) localTargetType = content.target_type;
      if (typeof content.is_repeating === 'boolean') localIsRepeating = content.is_repeating;
      if (content.message) localMessage = content.message;
      if (content.email_notification_warning) localEmailWarning = content.email_notification_warning;
      if (content.error) localError = content.error;
      
      // If success is false, mark as error
      if (content.success === false) {
        localStatus = 'error';
      }
    }
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="reminder"
  skillId="set-reminder"
  {skillIconName}
  {status}
  {skillName}
  {taskId}
  {isMobile}
  {onFullscreen}
  showStatus={true}
  customStatusText={statusText}
  showSkillIcon={false}
  onEmbedDataUpdated={handleEmbedDataUpdated}
>
  {#snippet details({ isMobile: isMobileSnippet })}
    <div class="reminder-preview" class:mobile={isMobileSnippet}>
      {#if status === 'processing'}
        <!-- Processing state: show skeleton -->
        <div class="skeleton-content">
          <div class="skeleton-icon"></div>
          <div class="skeleton-lines">
            <div class="skeleton-line long"></div>
            <div class="skeleton-line short"></div>
          </div>
        </div>
      {:else if status === 'finished' && !error}
        <!-- Finished state: show reminder details -->
        <div class="reminder-content">
          <!-- Trigger time -->
          {#if triggerAtFormatted}
            <div class="reminder-time">
              <span class="time-icon">&#128337;</span>
              <span class="time-text">{triggerAtFormatted}</span>
            </div>
          {/if}
          
          <!-- Target type badge -->
          {#if targetType}
            <div class="reminder-badges">
              <span class="badge target-badge" class:new-chat={targetType === 'new_chat'} class:existing-chat={targetType === 'existing_chat'}>
                {targetTypeText}
              </span>
              {#if isRepeating}
                <span class="badge repeat-badge">
                  {$text('embeds.reminder.repeating.text')}
                </span>
              {/if}
            </div>
          {/if}
          
          <!-- Email warning if present -->
          {#if emailWarning}
            <div class="email-warning">
              <span class="warning-icon">&#9888;</span>
              <span class="warning-text">{emailWarning}</span>
            </div>
          {/if}
        </div>
      {:else}
        <!-- Error state -->
        <div class="error-state">
          <span class="error-icon">&#10060;</span>
          <span class="error-text">{error || $text('embeds.reminder.error_generic.text')}</span>
        </div>
      {/if}
    </div>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .reminder-preview {
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    padding: 12px;
    box-sizing: border-box;
  }
  
  .reminder-preview.mobile {
    padding: 8px;
  }
  
  /* Skeleton loading state */
  .skeleton-content {
    display: flex;
    align-items: center;
    gap: 12px;
    width: 100%;
  }
  
  .skeleton-icon {
    width: 32px;
    height: 32px;
    background: var(--color-grey-20, #eaeaea);
    border-radius: 50%;
    animation: pulse 1.5s ease-in-out infinite;
  }
  
  .skeleton-lines {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  
  .skeleton-line {
    height: 14px;
    background: var(--color-grey-15, #f0f0f0);
    border-radius: 4px;
    animation: pulse 1.5s ease-in-out infinite;
  }
  
  .skeleton-line.long {
    width: 80%;
  }
  
  .skeleton-line.short {
    width: 50%;
  }
  
  @keyframes pulse {
    0%, 100% { opacity: 0.6; }
    50% { opacity: 1; }
  }
  
  /* Reminder content */
  .reminder-content {
    display: flex;
    flex-direction: column;
    gap: 10px;
    width: 100%;
  }
  
  /* Trigger time */
  .reminder-time {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 15px;
    color: var(--color-grey-80, #333);
    font-weight: 500;
  }
  
  .time-icon {
    font-size: 18px;
  }
  
  .time-text {
    flex: 1;
  }
  
  /* Badges */
  .reminder-badges {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  
  .badge {
    display: inline-flex;
    align-items: center;
    padding: 3px 8px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 500;
  }
  
  .target-badge {
    background: var(--color-grey-15, #f0f0f0);
    color: var(--color-grey-70, #555);
  }
  
  .target-badge.new-chat {
    background: var(--color-primary-10, #e8f0ff);
    color: var(--color-primary-70, #4a6eb0);
  }
  
  .target-badge.existing-chat {
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
    gap: 6px;
    padding: 8px;
    background: var(--color-warning-5, #fffdf5);
    border-radius: 6px;
    border: 1px solid var(--color-warning-20, #f5e6c0);
  }
  
  .warning-icon {
    font-size: 14px;
    color: var(--color-warning-60, #c9a02d);
    flex-shrink: 0;
  }
  
  .warning-text {
    font-size: 12px;
    color: var(--color-warning-80, #8a6b1a);
    line-height: 1.4;
  }
  
  /* Error state */
  .error-state {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px;
    background: var(--color-error-5, #fff5f5);
    border-radius: 6px;
    border: 1px solid var(--color-error-20, #f5c0c0);
  }
  
  .error-icon {
    font-size: 16px;
    flex-shrink: 0;
  }
  
  .error-text {
    font-size: 13px;
    color: var(--color-error-70, #b04a4a);
    line-height: 1.4;
  }
  
  /* Mobile adjustments */
  .mobile .reminder-time {
    font-size: 13px;
  }
  
  .mobile .time-icon {
    font-size: 16px;
  }
  
  .mobile .badge {
    font-size: 10px;
    padding: 2px 6px;
  }
  
  .mobile .warning-text,
  .mobile .error-text {
    font-size: 11px;
  }
  
  /* Dark mode support */
  :global(.dark) .reminder-time {
    color: var(--color-grey-20, #eaeaea);
  }
  
  :global(.dark) .target-badge {
    background: var(--color-grey-85, #252525);
    color: var(--color-grey-40, #aaa);
  }
  
  :global(.dark) .target-badge.new-chat {
    background: var(--color-primary-90, #1a2540);
    color: var(--color-primary-40, #7a9ed0);
  }
  
  :global(.dark) .target-badge.existing-chat {
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
  
  :global(.dark) .error-state {
    background: var(--color-error-95, #2a1515);
    border-color: var(--color-error-80, #8a1a1a);
  }
  
  :global(.dark) .error-text {
    color: var(--color-error-40, #d07a7a);
  }
  
  :global(.dark) .skeleton-icon {
    background: var(--color-grey-80, #333);
  }
  
  :global(.dark) .skeleton-line {
    background: var(--color-grey-80, #333);
  }
</style>
