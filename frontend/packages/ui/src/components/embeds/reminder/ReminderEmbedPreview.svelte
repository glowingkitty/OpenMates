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
    prompt?: string;
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
    /** The reminder prompt/content */
    prompt?: string;
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
    triggerAtFormatted: triggerAtFormattedProp,
    targetType: targetTypeProp,
    isRepeating: isRepeatingProp = false,
    prompt: promptProp,
    emailNotificationWarning: emailWarningProp,
    status: statusProp,
    error: errorProp,
    taskId: taskIdProp,
    isMobile = false,
    onFullscreen
  }: Props = $props();
  
  // Local reactive state - can be updated via onEmbedDataUpdated callback
  let localTriggerAtFormatted = $state<string | undefined>(undefined);
  let localTargetType = $state<'new_chat' | 'existing_chat' | undefined>(undefined);
  let localIsRepeating = $state<boolean>(false);
  let localPrompt = $state<string | undefined>(undefined);
  let localEmailWarning = $state<string | undefined>(undefined);
  let localStatus = $state<'processing' | 'finished' | 'error'>('processing');
  let localError = $state<string | undefined>(undefined);
  let localTaskId = $state<string | undefined>(undefined);
  
  // Initialize local state from props
  $effect(() => {
    localTriggerAtFormatted = triggerAtFormattedProp;
    localTargetType = targetTypeProp;
    localIsRepeating = isRepeatingProp || false;
    localPrompt = promptProp;
    localEmailWarning = emailWarningProp;
    localStatus = statusProp || 'processing';
    localError = errorProp;
    localTaskId = taskIdProp;
  });
  
  // Use local state as source of truth
  let triggerAtFormatted = $derived(localTriggerAtFormatted);
  let targetType = $derived(localTargetType);
  let isRepeating = $derived(localIsRepeating);
  let prompt = $derived(localPrompt);
  let emailWarning = $derived(localEmailWarning);
  let status = $derived(localStatus);
  let error = $derived(localError);
  let taskId = $derived(localTaskId);
  
  // Icon for reminders
  const skillIconName = 'reminder';
  
  // Build skill name for BasicInfosBar
  let skillName = $derived.by(() => {
    if (status === 'error' && error) {
      return $text('apps.reminder.skills.set_reminder');
    }
    return $text('apps.reminder.skills.set_reminder');
  });
  
  // Build status text - use default "Processing..." for processing state (handled by BasicInfosBar)
  // Only provide custom status text for completed state (showing trigger time)
  let statusText = $derived.by(() => {
    if (status === 'processing') {
      // Return undefined to use default "Processing..." from BasicInfosBar
      return undefined;
    }
    if (status === 'error') {
      return $text('embeds.reminder.error');
    }
    if (triggerAtFormatted) {
      return triggerAtFormatted;
    }
    return '';
  });
  
  // Get target type display text
  let targetTypeText = $derived.by(() => {
    if (targetType === 'new_chat') {
      return $text('embeds.reminder.new_chat');
    }
    if (targetType === 'existing_chat') {
      return $text('embeds.reminder.existing_chat');
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
      
      if (content.trigger_at_formatted) localTriggerAtFormatted = content.trigger_at_formatted;
      if (content.target_type) localTargetType = content.target_type;
      if (typeof content.is_repeating === 'boolean') localIsRepeating = content.is_repeating;
      if (content.prompt) localPrompt = content.prompt;
      if (content.email_notification_warning) localEmailWarning = content.email_notification_warning;
      if (content.error) localError = content.error;
      
      // If success is false, mark as error
      if (content.success === false) {
        localStatus = 'error';
      }
    }
  }
  
  /**
   * Truncate prompt to first 3 lines with ellipsis
   */
  let promptPreview = $derived.by(() => {
    if (!prompt) return '';
    const lines = prompt.split('\n').slice(0, 3);
    const truncated = lines.join('\n');
    // Add ellipsis if there are more lines or text is truncated
    if (prompt.split('\n').length > 3 || truncated.length > 150) {
      return truncated.substring(0, 150) + '...';
    }
    return truncated;
  });
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
  showSkillIcon={true}
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
          <!-- Prompt preview (first 3 lines with ellipsis) -->
          {#if promptPreview}
            <div class="reminder-prompt">
              <span class="prompt-text">{promptPreview}</span>
            </div>
          {/if}
          
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
                  {$text('embeds.reminder.repeating')}
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
          <span class="error-text">{error || $text('embeds.reminder.error_generic')}</span>
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
  
  /* Prompt preview */
  .reminder-prompt {
    padding: 8px 10px;
    background: var(--color-grey-10, #f5f5f5);
    border-radius: 6px;
    border-left: 3px solid var(--color-app-reminder, #FF9500);
  }
  
  .prompt-text {
    font-size: 13px;
    color: var(--color-grey-80, #333);
    line-height: 1.4;
    white-space: pre-wrap;
    word-break: break-word;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
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
  :global(.dark) .reminder-prompt {
    background: var(--color-grey-90, #1a1a1a);
  }
  
  :global(.dark) .prompt-text {
    color: var(--color-grey-20, #eaeaea);
  }
  
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
