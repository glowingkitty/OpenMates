<!--
Usage Settings - View usage statistics and export usage data
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { text } from '@repo/ui';
    import { apiEndpoints, getApiEndpoint } from '../../config/api';
    import SettingsItem from '../SettingsItem.svelte';
    import { notificationStore } from '../../stores/notificationStore';
    import { chatDB } from '../../services/db';

    // Usage entry interface
    interface UsageEntry {
        id: string;
        type: string;
        source?: string; // "chat", "api_key", or "direct"
        app_id?: string; // Cleartext - always available for new entries
        skill_id?: string; // Cleartext - always available for new entries
        model_used?: string;
        credits?: number; // Optional since it might be missing for some entries
        input_tokens?: number;
        output_tokens?: number;
        chat_id?: string | null; // Cleartext - for matching with IndexedDB
        message_id?: string | null; // Cleartext - for matching with IndexedDB
        created_at: number;
        updated_at: number;
    }

    // Tab types
    type UsageTab = 'chats' | 'apps' | 'api';
    type TimeGrouping = 'month' | 'day';
    type SortOption = 'last_edited' | 'most_expensive';

    let isLoading = $state(false);
    let errorMessage: string | null = $state(null);
    let usageEntries: UsageEntry[] = $state([]);
    
    // Pagination state
    let currentPage = $state(1);
    let pageSize = $state(10);
    let totalCount = $state(0);
    
    // UI state
    let activeTab: UsageTab = $state('chats');
    let timeGrouping: TimeGrouping = $state('month');
    let sortOption: SortOption = $state('last_edited');
    let selectedChatId: string | null = $state(null); // Changed from selectedChatHash to selectedChatId

    // Format credits with dots as thousand separators
    function formatCredits(credits: number): string {
        return credits.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    }

    // Format timestamp to date string
    function formatDate(timestamp: number): string {
        try {
            const date = new Date(timestamp * 1000); // Convert from seconds to milliseconds
            return date.toLocaleDateString(undefined, {
                year: 'numeric',
                month: 'long',
                day: 'numeric'
            });
        } catch {
            return new Date(timestamp * 1000).toISOString();
        }
    }

    // Format timestamp to relative time (e.g., "2 minutes ago")
    function formatRelativeTime(timestamp: number): string {
        try {
            const date = new Date(timestamp * 1000);
            const now = new Date();
            const diffMs = now.getTime() - date.getTime();
            const diffMins = Math.floor(diffMs / 60000);
            const diffHours = Math.floor(diffMs / 3600000);
            const diffDays = Math.floor(diffMs / 86400000);

            if (diffMins < 1) return $text('settings.usage.just_now.text');
            if (diffMins < 60) return `${diffMins} ${$text('settings.usage.minutes_ago.text')}`;
            if (diffHours < 24) return `${diffHours} ${$text('settings.usage.hours_ago.text')}`;
            if (diffDays < 30) return `${diffDays} ${$text('settings.usage.days_ago.text')}`;
            
            return formatDate(timestamp);
        } catch {
            return formatDate(timestamp);
        }
    }

    // Get month/year string from timestamp
    function getMonthYear(timestamp: number): string {
        try {
            const date = new Date(timestamp * 1000);
            return date.toLocaleDateString(undefined, {
                year: 'numeric',
                month: 'long'
            });
        } catch {
            return 'Unknown';
        }
    }

    // Get day string from timestamp
    function getDayString(timestamp: number): string {
        try {
            const date = new Date(timestamp * 1000);
            return date.toLocaleDateString(undefined, {
                year: 'numeric',
                month: 'long',
                day: 'numeric'
            });
        } catch {
            return 'Unknown';
        }
    }

    // Filter usage entries by tab
    function filterByTab(entries: UsageEntry[]): UsageEntry[] {
        switch (activeTab) {
            case 'chats':
                // Entries with chat_id (chat-related usage) or source='chat'
                return entries.filter(e => e.chat_id || e.source === 'chat');
            case 'apps':
                // Entries with app_id and skill_id (app usage)
                return entries.filter(e => e.app_id && e.skill_id);
            case 'api':
                // Entries with source='api_key' or 'direct', or entries without chat_id
                return entries.filter(e => 
                    e.source === 'api_key' || 
                    e.source === 'direct' ||
                    (!e.chat_id && e.source !== 'chat')
                );
            default:
                return entries;
        }
    }

    // Group usage entries by time period
    function groupByTime(entries: UsageEntry[]): Record<string, UsageEntry[]> {
        const groups: Record<string, UsageEntry[]> = {};
        
        entries.forEach(entry => {
            const key = timeGrouping === 'month' 
                ? getMonthYear(entry.created_at)
                : getDayString(entry.created_at);
            
            if (!groups[key]) {
                groups[key] = [];
            }
            groups[key].push(entry);
        });
        
        return groups;
    }

    // Sort usage entries
    function sortEntries(entries: UsageEntry[]): UsageEntry[] {
        const sorted = [...entries];
        
        if (sortOption === 'last_edited') {
            sorted.sort((a, b) => b.updated_at - a.updated_at);
        } else if (sortOption === 'most_expensive') {
            sorted.sort((a, b) => b.credits - a.credits);
        }
        
        return sorted;
    }

    // Group entries by chat ID
    function groupByChat(entries: UsageEntry[]): Record<string, UsageEntry[]> {
        const groups: Record<string, UsageEntry[]> = {};
        
        entries.forEach(entry => {
            const chatId = entry.chat_id || 'other';
            if (!groups[chatId]) {
                groups[chatId] = [];
            }
            groups[chatId].push(entry);
        });
        
        return groups;
    }

    // Calculate total credits for entries
    function calculateTotalCredits(entries: UsageEntry[]): number {
        return entries.reduce((sum, entry) => sum + (entry.credits ?? 0), 0);
    }

    // Get display name for usage entry
    function getEntryDisplayName(entry: UsageEntry): string {
        if (entry.app_id && entry.skill_id) {
            // Try to get app/skill name from translation keys
            const appKey = `apps.${entry.app_id}.text`;
            const skillKey = `apps.${entry.app_id}.skills.${entry.skill_id}.text`;
            try {
                const appName = $text(appKey);
                const skillName = $text(skillKey);
                return `${appName} - ${skillName}`;
            } catch {
                return `${entry.app_id} - ${entry.skill_id}`;
            }
        }
        if (entry.type) {
            return entry.type;
        }
        return $text('settings.usage.unknown_activity.text');
    }

    // Get icon for usage entry
    function getEntryIcon(entry: UsageEntry): string {
        // If it's an app usage, try to use the app icon
        if (entry.app_id) {
            // Common app icons that exist in the icon system
            const appIconMap: Record<string, string> = {
                'web': 'web',
                'ai': 'ai',
                'news': 'news',
                'videos': 'videos',
                'maps': 'maps',
                'code': 'code'
            };
            return appIconMap[entry.app_id] || 'app_store';
        }
        // For API calls
        if (entry.type?.includes('api') || activeTab === 'api') {
            return 'code';
        }
        // Default to chat icon
        return 'chat';
    }
    
    // Check if a chat exists in local IndexedDB (for clickable usage entries)
    async function checkChatExists(chatId: string | null | undefined): Promise<boolean> {
        if (!chatId) return false;
        try {
            const chat = await chatDB.getChat(chatId);
            return !!chat;
        } catch {
            return false;
        }
    }

    // Fetch usage data from API with pagination
    async function fetchUsage(page: number = currentPage) {
        isLoading = true;
        errorMessage = null;

        try {
            const offset = (page - 1) * pageSize;
            const endpoint = `${getApiEndpoint(apiEndpoints.usage.getUsage)}?limit=${pageSize}&offset=${offset}`;
            console.log('Fetching usage from:', endpoint);
            
            const response = await fetch(endpoint, {
                credentials: 'include'
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                const errorDetail = errorData.detail || errorData.message || '';
                throw new Error(`Failed to fetch usage: ${response.status} ${response.statusText}${errorDetail ? ` - ${errorDetail}` : ''}`);
            }

            const data = await response.json();
            console.log('Received usage data:', data);
            
            if (!data || typeof data !== 'object') {
                throw new Error('Invalid response format: expected object');
            }
            
            if (!Array.isArray(data.usage)) {
                console.warn('Response does not contain usage array:', data);
                usageEntries = [];
                totalCount = 0;
            } else {
                usageEntries = data.usage;
                totalCount = data.count || usageEntries.length;
                console.log(`Loaded ${usageEntries.length} usage entries (page ${page})`);
            }
        } catch (error) {
            console.error('Error fetching usage:', error);
            if (error instanceof Error) {
                errorMessage = error.message;
            } else {
                errorMessage = $text('settings.usage.error_loading.text');
            }
            usageEntries = [];
            totalCount = 0;
        } finally {
            isLoading = false;
        }
    }
    
    // Calculate total pages
    const totalPages = $derived(Math.ceil(totalCount / pageSize));
    
    // Navigation functions
    function goToPage(page: number) {
        if (page >= 1 && page <= totalPages) {
            currentPage = page;
            fetchUsage(page);
        }
    }
    
    function nextPage() {
        if (currentPage < totalPages) {
            goToPage(currentPage + 1);
        }
    }
    
    function previousPage() {
        if (currentPage > 1) {
            goToPage(currentPage - 1);
        }
    }

    // Export usage data as CSV
    async function exportToCSV() {
        try {
            notificationStore.info($text('settings.usage.exporting.text'));
            
            // Filter and prepare data
            const filtered = filterByTab(usageEntries);
            const sorted = sortEntries(filtered);
            
            // Create CSV header
            const headers = [
                'Date',
                'Time',
                'Type',
                'App',
                'Skill',
                'Credits',
                'Input Tokens',
                'Output Tokens',
                'Model'
            ];
            
            // Create CSV rows
            const rows = sorted.map(entry => {
                const date = new Date(entry.created_at * 1000);
                return [
                    date.toLocaleDateString(),
                    date.toLocaleTimeString(),
                    entry.type || '',
                    entry.app_id || '',
                    entry.skill_id || '',
                    entry.credits.toString(),
                    entry.input_tokens?.toString() || '',
                    entry.output_tokens?.toString() || '',
                    entry.model_used || ''
                ];
            });
            
            // Combine headers and rows
            const csvContent = [
                headers.join(','),
                ...rows.map(row => row.map(cell => `"${cell}"`).join(','))
            ].join('\n');
            
            // Create and download file
            const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = `usage-export-${new Date().toISOString().split('T')[0]}.csv`;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(url);
            
            notificationStore.success($text('settings.usage.export_success.text'));
        } catch (error) {
            console.error('Error exporting usage:', error);
            notificationStore.error($text('settings.usage.export_error.text'));
        }
    }

    // Export usage data as PDF (placeholder - would need PDF library)
    async function exportToPDF() {
        notificationStore.info($text('settings.usage.pdf_coming_soon.text'));
        // TODO: Implement PDF export using a library like jsPDF
    }

    // Get entries for selected chat
    const selectedChatEntries = $derived.by(() => {
        if (!selectedChatId) return [];
        return usageEntries.filter(e => e.chat_id === selectedChatId);
    });

    // Process and group usage data for display
    const processedUsage = $derived(() => {
        const filtered = filterByTab(usageEntries);
        const sorted = sortEntries(filtered);
        const grouped = groupByTime(sorted);
        
        // Calculate totals for each group
        const groupsWithTotals: Record<string, { entries: UsageEntry[], total: number }> = {};
        Object.entries(grouped).forEach(([key, entries]) => {
            groupsWithTotals[key] = {
                entries: entries,
                total: calculateTotalCredits(entries)
            };
        });
        
        return groupsWithTotals;
    });

    onMount(() => {
        fetchUsage(1);
    });
</script>

<!-- Header with Export button -->
<div class="usage-header">
    <div class="header-content">
        <h2 class="header-title">{$text('settings.usage.title.text')}</h2>
        <button 
            class="export-button"
            onclick={exportToCSV}
            title={$text('settings.usage.export.text')}
        >
            {$text('settings.usage.export.text')}
        </button>
    </div>
    <p class="header-description">{$text('settings.usage.description.text')}</p>
</div>

<!-- Tabs for filtering -->
<div class="usage-tabs">
    <button
        class="tab-button"
        class:active={activeTab === 'chats'}
        onclick={() => activeTab = 'chats'}
        title={$text('settings.usage.tab_chats.text')}
        aria-label={$text('settings.usage.tab_chats.text')}
    >
        <div class="tab-icon icon icon_chat"></div>
    </button>
    <button
        class="tab-button"
        class:active={activeTab === 'apps'}
        onclick={() => activeTab = 'apps'}
        title={$text('settings.usage.tab_apps.text')}
        aria-label={$text('settings.usage.tab_apps.text')}
    >
        <div class="tab-icon icon icon_app_store"></div>
    </button>
    <button
        class="tab-button"
        class:active={activeTab === 'api'}
        onclick={() => activeTab = 'api'}
        title={$text('settings.usage.tab_api.text')}
        aria-label={$text('settings.usage.tab_api.text')}
    >
        <div class="tab-icon icon icon_code"></div>
    </button>
    <button
        class="tab-button"
        class:active={timeGrouping === 'month'}
        onclick={() => timeGrouping = 'month'}
        title={$text('settings.usage.group_by_month.text')}
        aria-label={$text('settings.usage.group_by_month.text')}
    >
        <div class="tab-icon icon icon_calendar"></div>
    </button>
    <button
        class="tab-button"
        class:active={timeGrouping === 'day'}
        onclick={() => timeGrouping = 'day'}
        title={$text('settings.usage.group_by_day.text')}
        aria-label={$text('settings.usage.group_by_day.text')}
    >
        <div class="tab-icon icon icon_calendar"></div>
    </button>
    <button
        class="tab-button"
        onclick={() => sortOption = sortOption === 'last_edited' ? 'most_expensive' : 'last_edited'}
        title={$text('settings.usage.sort.text')}
        aria-label={$text('settings.usage.sort.text')}
    >
        <div class="tab-icon icon icon_sort"></div>
    </button>
</div>

{#if isLoading}
    <div class="loading-state">
        <div class="loading-spinner"></div>
        <span>{$text('settings.usage.loading.text')}</span>
    </div>
{:else if errorMessage}
    <div class="error-message">{errorMessage}</div>
    <SettingsItem
        type="quickaction"
        icon="subsetting_icon subsetting_icon_reload"
        title={$text('retry.text')}
        onClick={fetchUsage}
    />
{:else if usageEntries.length === 0}
    <div class="empty-state">
        <div class="empty-icon"></div>
        <h4>{$text('settings.usage.no_usage_title.text')}</h4>
        <p>{$text('settings.usage.no_usage_description.text')}</p>
    </div>
{:else if selectedChatId && selectedChatEntries.length > 0}
    <!-- Detail view for selected chat -->
    <div class="usage-detail-view">
        <button 
            class="back-button"
            onclick={() => selectedChatId = null}
        >
            <div class="clickable-icon icon_back"></div>
            <span>{$text('settings.usage.back.text')}</span>
        </button>
        
        <div class="detail-header">
            <div class="detail-icon icon icon_chat"></div>
            <div class="detail-info">
                <h3>{$text('settings.usage.chat_details.text')}</h3>
                <p>{getMonthYear(selectedChatEntries[0]?.created_at || 0)}</p>
            </div>
        </div>
        
        <div class="detail-entries">
            {#each selectedChatEntries as entry}
                <div class="detail-entry">
                    <div class="entry-time">{formatRelativeTime(entry.created_at)}</div>
                    <div class="entry-content">
                        <div class="entry-icon icon icon_ai"></div>
                        <div class="entry-info">
                            <div class="entry-label">{$text('settings.usage.activity_ai.text')}</div>
                            <div class="entry-sublabel">{$text('settings.usage.activity_ask.text')}</div>
                        </div>
                        <div class="entry-credits">{formatCredits(entry.credits)}</div>
                    </div>
                </div>
            {/each}
        </div>
        
        <div class="detail-export">
            <button class="export-button" onclick={exportToCSV}>
                {$text('settings.usage.export.text')}
            </button>
        </div>
    </div>
{:else}
    <!-- Main usage view grouped by time -->
    {#each Object.entries(processedUsage) as [timePeriod, { entries, total }]}
        <div class="time-group">
            <div class="time-header">
                <h4 class="time-title">{timePeriod}</h4>
                <div class="time-total">
                    <span class="credits-amount">{formatCredits(total)}</span>
                    <div class="credits-icon"></div>
                </div>
            </div>
            
            {#each entries as entry}
                {#if activeTab === 'chats' && entry.chat_id}
                    <!-- Chat entry with chat_id - make it clickable to view chat details -->
                    <button
                        type="button"
                        class="usage-item clickable"
                        onclick={() => {
                            selectedChatId = entry.chat_id!;
                        }}
                        aria-label={$text('settings.usage.view_chat_details.text')}
                    >
                        <div class="item-icon icon icon_{getEntryIcon(entry)}"></div>
                        <div class="item-content">
                            <div class="item-title">
                                {entry.chat_id ? `Chat: ${entry.chat_id.substring(0, 8)}...` : getEntryDisplayName(entry)}
                            </div>
                        </div>
                        <div class="item-credits">{formatCredits(entry.credits || 0)}</div>
                    </button>
                {:else}
                    <!-- Non-chat entry or entry without chat_id -->
                    <div class="usage-item">
                        <div class="item-icon icon icon_{getEntryIcon(entry)}"></div>
                        <div class="item-content">
                            <div class="item-title">{getEntryDisplayName(entry)}</div>
                        </div>
                        <div class="item-credits">{formatCredits(entry.credits || 0)}</div>
                    </div>
                {/if}
            {/each}
        </div>
    {/each}
    
    <!-- Pagination controls -->
    {#if totalPages > 1}
        <div class="pagination">
            <button
                class="pagination-button"
                onclick={previousPage}
                disabled={currentPage === 1}
                aria-label={$text('settings.usage.previous_page.text')}
            >
                <div class="clickable-icon icon_back"></div>
            </button>
            <span class="pagination-info">
                {$text('settings.usage.page_info.text').replace('{current}', currentPage.toString()).replace('{total}', totalPages.toString())}
            </span>
            <button
                class="pagination-button"
                onclick={nextPage}
                disabled={currentPage === totalPages}
                aria-label={$text('settings.usage.next_page.text')}
            >
                <div class="clickable-icon icon_back" style="transform: rotate(180deg);"></div>
            </button>
        </div>
    {/if}
{/if}

<style>
    .usage-header {
        padding: 10px;
        margin-bottom: 16px;
    }

    .header-content {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;
    }

    .header-title {
        margin: 0;
        color: var(--color-grey-100);
        font-size: 18px;
        font-weight: 600;
    }

    .export-button {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 16px;
        background: var(--color-accent);
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
    }

    .export-button:hover {
        background: var(--color-accent-hover);
        transform: translateY(-1px);
    }

    .header-description {
        margin: 0;
        color: var(--color-grey-60);
        font-size: 14px;
        line-height: 1.4;
    }

    .usage-tabs {
        display: flex;
        gap: 8px;
        padding: 10px;
        margin-bottom: 16px;
        border-bottom: 1px solid var(--color-grey-20);
    }

    .tab-button {
        width: 40px;
        height: 40px;
        border-radius: 50%;
        border: 1px solid var(--color-grey-30);
        background: var(--color-grey-10);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all 0.2s ease;
    }

    .tab-button:hover {
        background: var(--color-grey-15);
        border-color: var(--color-grey-40);
    }

    .tab-button.active {
        background: var(--color-primary);
        border-color: var(--color-primary);
    }

    .tab-icon {
        width: 20px;
        height: 20px;
    }

    .loading-state {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 12px;
        padding: 40px;
        color: var(--color-grey-60);
    }

    .loading-spinner {
        width: 20px;
        height: 20px;
        border: 2px solid var(--color-grey-20);
        border-top: 2px solid var(--color-accent);
        border-radius: 50%;
        animation: spin 1s linear infinite;
    }

    @keyframes spin {
        to { transform: rotate(360deg); }
    }

    .error-message {
        background: rgba(223, 27, 65, 0.1);
        color: #df1b41;
        padding: 12px;
        border-radius: 8px;
        font-size: 13px;
        border: 1px solid rgba(223, 27, 65, 0.3);
        margin: 16px 10px;
    }

    .empty-state {
        text-align: center;
        padding: 40px 20px;
    }

    .empty-icon {
        width: 48px;
        height: 48px;
        margin: 0 auto 16px;
        background-image: url('@openmates/ui/static/icons/usage.svg');
        background-size: contain;
        background-repeat: no-repeat;
        opacity: 0.3;
        filter: invert(1);
    }

    .empty-state h4 {
        margin: 0 0 8px 0;
        color: var(--color-grey-100);
        font-size: 16px;
        font-weight: 600;
    }

    .empty-state p {
        margin: 0;
        color: var(--color-grey-60);
        font-size: 14px;
        line-height: 1.4;
    }

    .time-group {
        margin-bottom: 24px;
    }

    .time-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0 10px 12px;
        margin-bottom: 12px;
        border-bottom: 1px solid var(--color-grey-20);
    }

    .time-title {
        color: var(--color-grey-80);
        font-size: 16px;
        font-weight: 600;
        margin: 0;
    }

    .time-total {
        display: flex;
        align-items: center;
        gap: 6px;
    }

    .credits-amount {
        color: var(--color-grey-80);
        font-size: 14px;
        font-weight: 600;
    }

    .credits-icon {
        width: 16px;
        height: 16px;
        background-image: url('@openmates/ui/static/icons/coins.svg');
        background-size: contain;
        background-repeat: no-repeat;
        background-position: center;
        opacity: 0.6;
    }

    .usage-item {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px 16px;
        margin-bottom: 8px;
        background: var(--color-grey-10);
        border-radius: 12px;
        border: 1px solid var(--color-grey-20);
        transition: all 0.2s ease;
        width: 100%;
        text-align: left;
    }

    .usage-item:hover {
        background: var(--color-grey-15);
        border-color: var(--color-grey-30);
    }

    .usage-item.clickable {
        cursor: pointer;
    }

    button.usage-item {
        border: 1px solid var(--color-grey-20);
        background: var(--color-grey-10);
    }

    button.usage-item:hover {
        background: var(--color-grey-15);
        border-color: var(--color-grey-30);
    }

    .item-icon {
        width: 24px;
        height: 24px;
        flex-shrink: 0;
    }

    .item-content {
        flex: 1;
        min-width: 0;
    }

    .item-title {
        color: var(--color-grey-100);
        font-size: 14px;
        font-weight: 500;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .item-credits {
        color: var(--color-grey-80);
        font-size: 14px;
        font-weight: 600;
        flex-shrink: 0;
    }

    .usage-detail-view {
        padding: 10px;
    }

    .back-button {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 0;
        background: none;
        border: none;
        color: var(--color-grey-60);
        font-size: 14px;
        cursor: pointer;
        margin-bottom: 16px;
    }

    .back-button:hover {
        color: var(--color-grey-80);
    }

    .detail-header {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 24px;
        padding-bottom: 16px;
        border-bottom: 1px solid var(--color-grey-20);
    }

    .detail-icon {
        width: 40px;
        height: 40px;
        border-radius: 50%;
        background: var(--color-primary);
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .detail-info h3 {
        margin: 0 0 4px 0;
        color: var(--color-grey-100);
        font-size: 16px;
        font-weight: 600;
    }

    .detail-info p {
        margin: 0;
        color: var(--color-grey-60);
        font-size: 14px;
    }

    .detail-entries {
        margin-bottom: 24px;
    }

    .detail-entry {
        margin-bottom: 16px;
    }

    .entry-time {
        color: var(--color-grey-60);
        font-size: 12px;
        margin-bottom: 8px;
    }

    .entry-content {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px;
        background: var(--color-grey-10);
        border-radius: 8px;
    }

    .entry-icon {
        width: 24px;
        height: 24px;
        background-size: contain;
        background-repeat: no-repeat;
        flex-shrink: 0;
    }

    .entry-info {
        flex: 1;
    }

    .entry-label {
        color: var(--color-grey-100);
        font-size: 14px;
        font-weight: 500;
    }

    .entry-sublabel {
        color: var(--color-grey-60);
        font-size: 12px;
    }

    .entry-credits {
        color: var(--color-grey-80);
        font-size: 14px;
        font-weight: 600;
    }

    .detail-export {
        text-align: center;
        padding-top: 16px;
        border-top: 1px solid var(--color-grey-20);
    }

    .pagination {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 16px;
        padding: 20px 10px;
        margin-top: 24px;
        border-top: 1px solid var(--color-grey-20);
    }

    .pagination-button {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 36px;
        height: 36px;
        border: 1px solid var(--color-grey-30);
        background: var(--color-grey-10);
        border-radius: 8px;
        cursor: pointer;
        transition: all 0.2s ease;
    }

    .pagination-button:hover:not(:disabled) {
        background: var(--color-grey-15);
        border-color: var(--color-grey-40);
    }

    .pagination-button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .pagination-info {
        color: var(--color-grey-80);
        font-size: 14px;
        font-weight: 500;
    }
</style>
