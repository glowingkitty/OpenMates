<script lang="ts">
    /**
     * AppSettingsMemoriesPermissionDialog.svelte
     * 
     * Displays a NON-BLOCKING permission dialog asking the user to confirm sharing app settings
     * and memories with the AI assistant. Used when the AI preprocessor determines
     * that certain app data could be relevant to answer the user's question.
     * 
     * IMPORTANT: This is rendered INSIDE ActiveChat.svelte, NOT as a fullscreen modal.
     * Users can still scroll and interact with the chat while this dialog is visible.
     * The dialog appears above the message input, similar to FollowUpSuggestions.
     * 
     * Architecture:
     * - Subscribes to appSettingsMemoriesPermissionStore for state
     * - Dispatches actions back to the store and handler functions
     * - Server sends "request_app_settings_memories" WebSocket message with requested keys
     * - Client shows this dialog to let user accept/reject each category
     * - When user clicks "Include", client sends decrypted data to server
     * - Server caches data for AI processing (chat-specific, auto-evicted)
     */
    import Toggle from './Toggle.svelte';
    import Icon from './Icon.svelte';
    import { text } from '@repo/ui';
    import { fade } from 'svelte/transition';
    import { 
        appSettingsMemoriesPermissionStore,
        isPermissionDialogVisible,
        currentPermissionRequest,
        permissionDialogLoading
    } from '../stores/appSettingsMemoriesPermissionStore';
    import {
        handlePermissionDialogConfirm,
        handlePermissionDialogExclude
    } from '../services/chatSyncServiceHandlersAppSettings';
    import { chatSyncService } from '../services/chatSyncService';
    
    // Toggle selection for a category
    function toggleCategory(key: string) {
        appSettingsMemoriesPermissionStore.toggleCategory(key);
    }
    
    // Handle "Include" button click - send selected categories
    async function handleConfirm() {
        const requestId = appSettingsMemoriesPermissionStore.getCurrentRequestId();
        const selectedKeys = appSettingsMemoriesPermissionStore.getSelectedKeys();
        
        if (!requestId || selectedKeys.length === 0) {
            console.warn('[PermissionDialog] No request ID or no selected keys');
            return;
        }
        
        appSettingsMemoriesPermissionStore.setLoading(true);
        
        try {
            await handlePermissionDialogConfirm(chatSyncService, requestId, selectedKeys);
            appSettingsMemoriesPermissionStore.clear();
        } catch (error) {
            console.error('[PermissionDialog] Error confirming:', error);
            appSettingsMemoriesPermissionStore.setLoading(false);
        }
    }
    
    // Handle "Exclude" button click - reject all
    async function handleExclude() {
        const requestId = appSettingsMemoriesPermissionStore.getCurrentRequestId();
        if (requestId) {
            await handlePermissionDialogExclude(chatSyncService, requestId);
        }
        appSettingsMemoriesPermissionStore.clear();
    }
    
    // Check if any category is selected
    let hasSelection = $derived($currentPermissionRequest?.categories.some(cat => cat.selected) ?? false);
</script>

<!-- Non-blocking dialog - rendered inside ActiveChat above the message input -->
<!-- Users can still scroll/interact with the chat while this is visible -->
{#if $isPermissionDialogVisible && $currentPermissionRequest}
    <div 
        class="permission-dialog-container" 
        role="dialog" 
        aria-labelledby="permission-dialog-title"
        transition:fade={{ duration: 200 }}
    >
        <!-- Header -->
        <div class="dialog-header">
            <div class="dialog-header-icon"></div>
            <span id="permission-dialog-title">{$text('chat.permissions.title') || 'Permissions'}</span>
        </div>
        
        <!-- Question -->
        <p class="dialog-question">
            {$text('chat.permissions.question') || 'Include these App settings & memories in this chat, for a more personalized response?'}
        </p>
        
        <!-- Categories list -->
        <div class="categories-list">
            {#each $currentPermissionRequest.categories as category (category.key)}
                <div class="category-item" class:selected={category.selected}>
                    <Toggle 
                        checked={category.selected}
                        on:change={() => toggleCategory(category.key)}
                        ariaLabel={`Toggle ${category.displayName}`}
                    />
                    
                    <!-- App icon with proper styling - uses Icon component for consistent app icon rendering -->
                    <div class="app-icon-wrapper">
                        <Icon 
                            name={category.appId} 
                            type="app" 
                            size="38px"
                        />
                    </div>
                    
                    <div class="category-info">
                        <span class="category-name">{category.displayName}</span>
                        <span class="category-count">
                            {category.entryCount} {category.entryCount === 1 
                                ? ($text('chat.permissions.entry_singular') || 'entry') 
                                : ($text('chat.permissions.entry_plural') || 'entries')}
                        </span>
                    </div>
                </div>
            {/each}
        </div>
        
        <!-- Action buttons -->
        <div class="dialog-actions">
            <button 
                class="btn-include" 
                onclick={handleConfirm}
                disabled={!hasSelection || $permissionDialogLoading}
            >
                {#if $permissionDialogLoading}
                    <span class="loading-spinner"></span>
                {:else}
                    {$text('chat.permissions.include_selected') || 'Include selected'}
                {/if}
            </button>
            <button 
                class="btn-reject" 
                onclick={handleExclude}
                disabled={$permissionDialogLoading}
            >
                {$text('chat.permissions.reject_all') || 'Reject all'}
            </button>
        </div>
    </div>
{/if}

<style>
    /* Non-blocking dialog container - positioned above message input in ActiveChat */
    /* This is NOT a fullscreen modal - users can still scroll/interact with the chat */
    .permission-dialog-container {
        position: relative;
        background: var(--color-grey-10, #fff);
        border-radius: 16px;
        padding: 16px;
        width: 100%;
        max-width: 629px; /* Match message input max-width */
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
        margin-bottom: 12px;
        border: 1px solid var(--color-grey-25, #e5e5e5);
    }
    
    .dialog-header {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        color: var(--color-grey-60, #666);
        font-size: 13px;
        margin-bottom: 10px;
    }
    
    /* Small settings gear icon next to "Permissions" header text */
    .dialog-header-icon {
        width: 16px;
        height: 16px;
        -webkit-mask-image: url('@openmates/ui/static/icons/settings.svg');
        mask-image: url('@openmates/ui/static/icons/settings.svg');
        -webkit-mask-size: contain;
        mask-size: contain;
        -webkit-mask-repeat: no-repeat;
        mask-repeat: no-repeat;
        -webkit-mask-position: center;
        mask-position: center;
        background-color: var(--color-grey-60, #666);
        flex-shrink: 0;
    }
    
    .dialog-question {
        text-align: center;
        font-size: 14px;
        font-weight: 500;
        color: var(--color-font-primary, #000);
        margin: 0 0 16px 0;
        line-height: 1.4;
    }
    
    .categories-list {
        display: flex;
        flex-direction: column;
        gap: 8px;
        margin-bottom: 16px;
        max-height: 200px; /* Limit height to keep chat visible */
        overflow-y: auto;
    }
    
    .category-item {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 10px 12px;
        background: var(--color-grey-15, #f5f5f5);
        border-radius: 12px;
        transition: background 0.2s ease;
    }
    
    .category-item.selected {
        background: var(--color-grey-20, #eee);
    }
    
    /* App icon wrapper for proper icon sizing within category items */
    .app-icon-wrapper {
        flex-shrink: 0;
    }
    
    .category-info {
        display: flex;
        flex-direction: column;
        gap: 1px;
        flex: 1;
        min-width: 0;
    }
    
    .category-name {
        font-size: 14px;
        font-weight: 600;
        color: var(--color-font-primary, #000);
    }
    
    .category-count {
        font-size: 12px;
        color: var(--color-grey-60, #888);
    }
    
    .dialog-actions {
        display: flex;
        gap: 10px;
    }
    
    .btn-include,
    .btn-reject {
        flex: 1;
        padding: 12px 20px;
        border-radius: 50px;
        font-size: 14px;
        font-weight: 600;
        border: none;
        cursor: pointer;
        transition: all 0.2s ease;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
    }
    
    .btn-include {
        background: var(--color-button-primary, #FF553B);
        color: white;
    }
    
    .btn-include:hover:not(:disabled) {
        background: var(--color-button-primary-hover, #ff6b54);
    }
    
    .btn-reject {
        background: var(--color-grey-20, #e0e0e0);
        color: var(--color-font-primary, #000);
    }
    
    .btn-reject:hover:not(:disabled) {
        background: var(--color-grey-30, #d0d0d0);
    }
    
    .btn-include:disabled,
    .btn-reject:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
    
    .loading-spinner {
        width: 14px;
        height: 14px;
        border: 2px solid rgba(255, 255, 255, 0.3);
        border-top-color: white;
        border-radius: 50%;
        animation: spin 0.8s linear infinite;
    }
    
    @keyframes spin {
        to { transform: rotate(360deg); }
    }
    
    /* Dark mode support */
    @media (prefers-color-scheme: dark) {
        .permission-dialog-container {
            background: var(--color-grey-10, #1a1a1a);
            border-color: var(--color-grey-30, #333);
        }
        
        .category-item {
            background: var(--color-grey-20, #2a2a2a);
        }
        
        .category-item.selected {
            background: var(--color-grey-25, #333);
        }
    }
</style>
