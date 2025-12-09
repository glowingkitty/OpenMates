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
    import { chatMetadataCache, type DecryptedChatMetadata } from '../../services/chatMetadataCache';
    import type { Chat } from '../../types/chat';
    import * as LucideIcons from '@lucide/svelte';
    import Icon from '../Icon.svelte';
    import { decryptWithMasterKey, getKeyFromStorage } from '../../services/cryptoService';

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
        api_key_hash?: string | null; // SHA-256 hash of the API key that created this usage entry
        created_at: number;
        updated_at: number;
    }

    // Chat usage summary interface
    interface ChatUsageSummary {
        chat_id: string;
        month: string;
        totalCredits: number;
        chat?: Chat | null;
        metadata?: DecryptedChatMetadata | null;
    }

    // App usage summary interface
    interface AppUsageSummary {
        app_id: string;
        month: string;
        totalCredits: number;
    }

    // API key interface
    interface ApiKey {
        id: string;
        key_hash: string;
        name: string;
        key_prefix: string;
        created_at: string;
        last_used_at?: string | null;
    }

    // API key usage summary interface
    interface ApiKeyUsageSummary {
        api_key_hash: string;
        month: string;
        totalCredits: number;
        apiKey?: ApiKey | null;
        encrypted_name?: string; // Encrypted API key name from backend (client decrypts)
        encrypted_key_prefix?: string; // Encrypted API key prefix from backend (client decrypts)
    }

    // Tab types
    type UsageTab = 'chats' | 'apps' | 'api';
    type TimeGrouping = 'month' | 'day';
    type SortOption = 'last_edited' | 'most_expensive';

    let isLoading = $state(false);
    let errorMessage: string | null = $state(null);
    let usageEntries: UsageEntry[] = $state([]);
    
    // Summary state (new architecture)
    let loadedMonths = $state(3); // Number of months loaded so far
    let isLoadingSummaries = $state(false);
    let isLoadingDetails = $state(false);
    
    // UI state
    let activeTab: UsageTab = $state('chats');
    let timeGrouping: TimeGrouping = $state('month');
    let sortOption: SortOption = $state('last_edited');
    let selectedChatId: string | null = $state(null); // Changed from selectedChatHash to selectedChatId
    let selectedAppId: string | null = $state(null); // Selected app for detail view
    let selectedAppMonth: string | null = $state(null); // Selected app's month for detail view
    let selectedApiKeyHash: string | null = $state(null); // Selected API key hash for detail view
    let selectedApiKeyMonth: string | null = $state(null); // Selected API key's month for detail view
    
    // Chat metadata cache for usage display
    let chatMetadataMap = $state<Map<string, { chat: Chat | null; metadata: DecryptedChatMetadata | null }>>(new Map());
    
    // API keys cache
    let apiKeys = $state<ApiKey[]>([]);
    let isLoadingApiKeys = $state(false);
    
    // Track if we've done initial load to prevent duplicate requests
    let hasInitialized = $state(false);

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
            // Handle undefined credits by treating them as 0
            sorted.sort((a, b) => (b.credits ?? 0) - (a.credits ?? 0));
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

    // Fetch usage summaries from API (new architecture)
    async function fetchUsageSummaries(type: UsageTab, months: number = loadedMonths) {
        isLoadingSummaries = true;
        errorMessage = null;

        try {
            // Optionally load API keys as fallback (backend now provides encrypted data in summaries)
            // This is kept for backward compatibility if encrypted data is missing
            if (type === 'api' && apiKeys.length === 0 && !isLoadingApiKeys) {
                // Load in background, don't wait for it
                loadApiKeys().catch(err => console.warn('[SettingsUsage] Failed to load API keys:', err));
            }

            // Map tab type to API type
            const apiTypeMap: Record<UsageTab, string> = {
                'chats': 'chats',
                'apps': 'apps',
                'api': 'api_keys'
            };
            
            const apiType = apiTypeMap[type];
            const endpoint = `${getApiEndpoint(apiEndpoints.usage.getSummaries)}?type=${apiType}&months=${months}`;
            console.log('Fetching usage summaries from:', endpoint);
            
            const response = await fetch(endpoint, {
                credentials: 'include'
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                const errorDetail = errorData.detail || errorData.message || '';
                throw new Error(`Failed to fetch usage summaries: ${response.status} ${response.statusText}${errorDetail ? ` - ${errorDetail}` : ''}`);
            }

            const data = await response.json();
            console.log('Received usage summaries:', data);
            
            if (!data || typeof data !== 'object' || !Array.isArray(data.summaries)) {
                throw new Error('Invalid response format: expected summaries array');
            }

            // Determine if more months exist based on API-provided count (total available months).
            const totalAvailableMonths = typeof data.count === 'number' ? data.count : data.summaries.length;
            hasMoreMonths = totalAvailableMonths > months;
            
            // Update summaries based on type
            if (type === 'chats') {
                await updateChatSummariesFromAPI(data.summaries);
            } else if (type === 'apps') {
                await updateAppSummariesFromAPI(data.summaries);
            } else if (type === 'api') {
                await updateApiKeySummariesFromAPI(data.summaries);
            }
            
            console.log(`Loaded ${data.summaries.length} ${type} summaries for ${months} months`);
        } catch (error) {
            console.error('Error fetching usage summaries:', error);
            if (error instanceof Error) {
                errorMessage = error.message;
            } else {
                errorMessage = $text('settings.usage.error_loading.text');
            }
            hasMoreMonths = false;
        } finally {
            isLoadingSummaries = false;
        }
    }
    
    // Fetch usage details for a specific summary item
    async function fetchUsageDetails(type: UsageTab, identifier: string, yearMonth: string) {
        isLoadingDetails = true;
        errorMessage = null;

        try {
            // Map tab type to API type
            const apiTypeMap: Record<UsageTab, string> = {
                'chats': 'chat',
                'apps': 'app',
                'api': 'api_key'
            };
            
            const apiType = apiTypeMap[type];
            const endpoint = `${getApiEndpoint(apiEndpoints.usage.getDetails)}?type=${apiType}&identifier=${encodeURIComponent(identifier)}&year_month=${yearMonth}`;
            console.log('Fetching usage details from:', endpoint);
            
            const response = await fetch(endpoint, {
                credentials: 'include'
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                const errorDetail = errorData.detail || errorData.message || '';
                throw new Error(`Failed to fetch usage details: ${response.status} ${response.statusText}${errorDetail ? ` - ${errorDetail}` : ''}`);
            }

            const data = await response.json();
            console.log('Received usage details:', data);
            
            if (!data || typeof data !== 'object' || !Array.isArray(data.entries)) {
                throw new Error('Invalid response format: expected entries array');
            }
            
            // Update usageEntries with the details
            usageEntries = data.entries;
            console.log(`Loaded ${data.entries.length} usage entries for ${type} '${identifier}', month '${yearMonth}'`);
        } catch (error) {
            console.error('Error fetching usage details:', error);
            if (error instanceof Error) {
                errorMessage = error.message;
            } else {
                errorMessage = $text('settings.usage.error_loading.text');
            }
            usageEntries = [];
        } finally {
            isLoadingDetails = false;
        }
    }
    
    // Update chat summaries from API response
    async function updateChatSummariesFromAPI(summaries: any[]) {
        // Clear existing data and rebuild (or merge if we want to support incremental loading)
        const groupedByMonth = new Map<string, ChatUsageSummary[]>();
        
        for (const summary of summaries) {
            const month = summary.year_month;
            if (!groupedByMonth.has(month)) {
                groupedByMonth.set(month, []);
            }
            
            // Load chat metadata
            const { chat, metadata } = await loadChatMetadata(summary.chat_id);
            
            groupedByMonth.get(month)!.push({
                chat_id: summary.chat_id,
                month: summary.year_month,
                totalCredits: summary.total_credits || 0,
                chat: chat,
                metadata: metadata
            });
        }
        
        // Sort summaries within each month by total credits (descending)
        groupedByMonth.forEach((summaries, month) => {
            summaries.sort((a, b) => b.totalCredits - a.totalCredits);
        });
        
        // Update state - create new Map instance to trigger reactivity in Svelte 5
        chatsByMonth = new Map(groupedByMonth);
        console.log('Updated chatsByMonth:', chatsByMonth.size, 'months, entries:', Array.from(chatsByMonth.entries()));
    }
    
    // Update app summaries from API response
    function updateAppSummariesFromAPI(summaries: any[]) {
        const groupedByMonth = new Map<string, AppUsageSummary[]>();
        
        for (const summary of summaries) {
            const month = summary.year_month;
            if (!groupedByMonth.has(month)) {
                groupedByMonth.set(month, []);
            }
            
            groupedByMonth.get(month)!.push({
                app_id: summary.app_id,
                month: summary.year_month,
                totalCredits: summary.total_credits || 0
            });
        }
        
        // Sort summaries within each month by total credits (descending)
        groupedByMonth.forEach((summaries, month) => {
            summaries.sort((a, b) => b.totalCredits - a.totalCredits);
        });
        
        // Update state - replace entire Map to trigger reactivity
        appsByMonth = new Map(groupedByMonth);
        console.log('Updated appsByMonth:', appsByMonth.size, 'months');
    }
    
    // Update API key summaries from API response
    // Backend now includes encrypted_name and encrypted_key_prefix in summaries
    async function updateApiKeySummariesFromAPI(summaries: any[]) {
        const groupedByMonth = new Map<string, ApiKeyUsageSummary[]>();
        const labelsMap = new Map<string, { title: string; subtitle: string }>();
        
        for (const summary of summaries) {
            const month = summary.year_month;
            if (!groupedByMonth.has(month)) {
                groupedByMonth.set(month, []);
            }
            
            // Use encrypted data from backend (client will decrypt)
            // Fallback to apiKeys array lookup if encrypted data not available (backward compatibility)
            let apiKey: ApiKey | null = null;
            let encryptedName = summary.encrypted_name || '';
            let encryptedPrefix = summary.encrypted_key_prefix || '';
            
            // If encrypted data not provided, try to find in apiKeys array (backward compatibility)
            if (!encryptedName && !encryptedPrefix) {
                apiKey = apiKeys.find(k => k.key_hash === summary.api_key_hash) || null;
                if (apiKey) {
                    encryptedName = apiKey.name || '';
                    encryptedPrefix = apiKey.key_prefix || '';
                }
            }
            
            const summaryObj: ApiKeyUsageSummary = {
                api_key_hash: summary.api_key_hash,
                month: summary.year_month,
                totalCredits: summary.total_credits || 0,
                apiKey: apiKey,
                encrypted_name: encryptedName,
                encrypted_key_prefix: encryptedPrefix
            };
            
            groupedByMonth.get(month)!.push(summaryObj);
            
            // Decrypt and cache label for this summary
            const labelKey = `${summary.api_key_hash}:${month}`;
            const label = await getApiKeyLabel(summaryObj);
            labelsMap.set(labelKey, label);
        }
        
        // Sort summaries within each month by total credits (descending)
        groupedByMonth.forEach((summaries, month) => {
            summaries.sort((a, b) => b.totalCredits - a.totalCredits);
        });
        
        // Update state - replace entire Map to trigger reactivity
        apiKeysByMonth = new Map(groupedByMonth);
        apiKeyLabels = new Map(labelsMap);
        console.log('Updated apiKeysByMonth:', apiKeysByMonth.size, 'months');
    }
    
    // Show more months
    async function showMoreMonths() {
        loadedMonths += 3;
        await fetchUsageSummaries(activeTab, loadedMonths);
    }
    
    // Whether additional months are available based on server-provided total count.
    let hasMoreMonths = $state(false);

    // Export usage data as CSV (backend generates the file)
    // Exports ALL usage entries for the current time frame (chats, apps, and API keys)
    async function exportToCSV() {
        try {
            notificationStore.info($text('settings.usage.exporting.text'));
            
            // Build export URL with current time frame (no type filter - exports everything)
            const params = new URLSearchParams({
                months: loadedMonths.toString()
            });
            
            const endpoint = `${getApiEndpoint(apiEndpoints.usage.export)}?${params.toString()}`;
            console.log('Exporting ALL usage data from:', endpoint);
            
            // Fetch CSV from backend
            const response = await fetch(endpoint, {
                credentials: 'include'
            });
            
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                const errorDetail = errorData.detail || errorData.message || '';
                throw new Error(`Failed to export usage data: ${response.status} ${response.statusText}${errorDetail ? ` - ${errorDetail}` : ''}`);
            }
            
            // Get filename from Content-Disposition header or use default
            const contentDisposition = response.headers.get('Content-Disposition');
            let filename = `usage-export-${new Date().toISOString().split('T')[0]}.csv`;
            if (contentDisposition) {
                const filenameMatch = contentDisposition.match(/filename="?([^"]+)"?/);
                if (filenameMatch) {
                    filename = filenameMatch[1];
                }
            }
            
            // Download the CSV file
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(url);
            
            notificationStore.success($text('settings.usage.export_success.text'));
        } catch (error) {
            console.error('Error exporting usage:', error);
            if (error instanceof Error) {
                notificationStore.error(error.message);
            } else {
                notificationStore.error($text('settings.usage.export_error.text'));
            }
        }
    }

    // Export usage data as PDF (placeholder - would need PDF library)
    async function exportToPDF() {
        notificationStore.info($text('settings.usage.pdf_coming_soon.text'));
        // TODO: Implement PDF export using a library like jsPDF
    }

    // Usage entries are now loaded directly via fetchUsageDetails, no need for derived values

    /**
     * Get gradient colors for a category based on mate configuration
     * (Same as Chat.svelte)
     */
    function getCategoryGradientColors(category: string): { start: string; end: string } | null {
        const categoryGradients: Record<string, { start: string; end: string }> = {
            'software_development': { start: '#155D91', end: '#42ABF4' },
            'business_development': { start: '#004040', end: '#008080' },
            'medical_health': { start: '#FD50A0', end: '#F42C2D' },
            'legal_law': { start: '#239CFF', end: '#005BA5' },
            'openmates_official': { start: '#6366f1', end: '#4f46e5' },
            'maker_prototyping': { start: '#EA7600', end: '#FBAB59' },
            'marketing_sales': { start: '#FF8C00', end: '#F4B400' },
            'finance': { start: '#119106', end: '#15780D' },
            'design': { start: '#101010', end: '#2E2E2E' },
            'electrical_engineering': { start: '#233888', end: '#2E4EC8' },
            'movies_tv': { start: '#00C2C5', end: '#3170DC' },
            'history': { start: '#4989F2', end: '#2F44BF' },
            'science': { start: '#FF7300', end: '#D5320' },
            'life_coach_psychology': { start: '#FDB250', end: '#F42C2D' },
            'cooking_food': { start: '#FD8450', end: '#F42C2D' },
            'activism': { start: '#F53D00', end: '#F56200' },
            'general_knowledge': { start: '#DE1E66', end: '#FF763B' }
        };
        return categoryGradients[category] || null;
    }

    /**
     * Get fallback icon for a category when no icon names are provided
     * (Same as Chat.svelte)
     */
    function getFallbackIconForCategory(category: string): string {
        const categoryIcons: Record<string, string> = {
            'software_development': 'code',
            'business_development': 'briefcase',
            'medical_health': 'heart',
            'legal_law': 'gavel',
            'openmates_official': 'shield-check',
            'maker_prototyping': 'wrench',
            'marketing_sales': 'megaphone',
            'finance': 'dollar-sign',
            'design': 'palette',
            'electrical_engineering': 'zap',
            'movies_tv': 'tv',
            'history': 'clock',
            'science': 'microscope',
            'life_coach_psychology': 'users',
            'cooking_food': 'utensils',
            'activism': 'trending-up',
            'general_knowledge': 'help-circle'
        };
        return categoryIcons[category] || 'help-circle';
    }

    /**
     * Get the Lucide icon component by name
     * (Same as Chat.svelte)
     */
    function getLucideIcon(iconName: string) {
        const pascalCaseName = iconName
            .split('-')
            .map(word => word.charAt(0).toUpperCase() + word.slice(1))
            .join('');
        return LucideIcons[pascalCaseName] || LucideIcons.HelpCircle;
    }

    /**
     * Load chat metadata for a chat_id
     * Fetches from IndexedDB and decrypts metadata
     */
    async function loadChatMetadata(chatId: string): Promise<{ chat: Chat | null; metadata: DecryptedChatMetadata | null }> {
        // Check cache first
        if (chatMetadataMap.has(chatId)) {
            return chatMetadataMap.get(chatId)!;
        }

        // For non-UUID chat IDs (like "demo-welcome"), return null immediately
        // These are demo/placeholder chats not stored in IndexedDB
        const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
        if (!uuidPattern.test(chatId)) {
            console.debug(`[SettingsUsage] Skipping metadata load for non-UUID chat_id: ${chatId} (likely a demo/placeholder chat)`);
            const result = { chat: null, metadata: null };
            chatMetadataMap.set(chatId, result);
            return result;
        }

        try {
            // Fetch chat from IndexedDB
            const chat = await chatDB.getChat(chatId);
            if (!chat) {
                const result = { chat: null, metadata: null };
                chatMetadataMap.set(chatId, result);
                return result;
            }

            // Get decrypted metadata
            const metadata = await chatMetadataCache.getDecryptedMetadata(chat);
            const result = { chat, metadata };
            chatMetadataMap.set(chatId, result);
            return result;
        } catch (error) {
            console.error(`[SettingsUsage] Error loading chat metadata for ${chatId}:`, error);
            const result = { chat: null, metadata: null };
            chatMetadataMap.set(chatId, result);
            return result;
        }
    }

    // Chat usage summaries grouped by month
    // Use a reactive object wrapper to ensure Svelte 5 detects changes
    let chatsByMonth = $state<Map<string, ChatUsageSummary[]>>(new Map());
    
    // Derived value to check if we have any chat summaries
    const hasChatSummaries = $derived(chatsByMonth.size > 0 && Array.from(chatsByMonth.values()).some(arr => arr.length > 0));
    let isLoadingChatMetadata = $state(false);

    // Chat summaries are now loaded from API, not computed from usageEntries

    // App usage summaries grouped by month
    let appsByMonth = $state<Map<string, AppUsageSummary[]>>(new Map());

    /**
     * Load API keys from the API endpoint
     */
    async function loadApiKeys() {
        isLoadingApiKeys = true;
        try {
            const response = await fetch(getApiEndpoint('/v1/settings/api-keys'), {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                credentials: 'include'
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Failed to load API keys');
            }

            const data = await response.json();
            const rawKeys = data.api_keys || [];
            
            // Decrypt encrypted_name and encrypted_key_prefix for each key
            const masterKey = await getKeyFromStorage();
            if (!masterKey) {
                console.warn('[SettingsUsage] Master key not found, cannot decrypt API key names');
                apiKeys = [];
                return;
            }

            apiKeys = await Promise.all(
                rawKeys.map(async (key: any) => {
                    let decryptedName = key.encrypted_name || '';
                    let decryptedPrefix = key.encrypted_key_prefix || '';
                    
                    try {
                        if (key.encrypted_name) {
                            const decrypted = await decryptWithMasterKey(key.encrypted_name);
                            if (decrypted) {
                                decryptedName = decrypted;
                            }
                        }
                        if (key.encrypted_key_prefix) {
                            const decrypted = await decryptWithMasterKey(key.encrypted_key_prefix);
                            if (decrypted) {
                                decryptedPrefix = decrypted;
                            }
                        }
                    } catch (err) {
                        console.error('[SettingsUsage] Error decrypting API key fields:', err);
                    }

                    return {
                        id: key.id,
                        key_hash: key.key_hash || '',
                        name: decryptedName,
                        key_prefix: decryptedPrefix,
                        created_at: key.created_at || '',
                        last_used_at: key.last_used_at || null
                    };
                })
            );
        } catch (err: any) {
            console.error('[SettingsUsage] Error loading API keys:', err);
            apiKeys = [];
        } finally {
            isLoadingApiKeys = false;
        }
    }

    // API key usage summaries grouped by month
    let apiKeysByMonth = $state<Map<string, ApiKeyUsageSummary[]>>(new Map());
    
    // Map of (api_key_hash + month) -> decrypted label for API keys
    let apiKeyLabels = $state<Map<string, { title: string; subtitle: string }>>(new Map());

    // API key summaries are now loaded from API, not computed from usageEntries

    // App summaries are now loaded from API, not computed from usageEntries

    /**
     * Get icon name from app_id
     * Maps app_id to icon name for Icon component
     */
    function getAppIconName(appId: string): string {
        // App IDs typically match icon names (e.g., "ai", "web", "videos")
        // Handle special cases if needed
        return appId.toLowerCase();
    }

    /**
     * Get app name from app_id using translation
     */
    function getAppName(appId: string): string {
        try {
            return $text(`apps.${appId}.text`);
        } catch {
            return appId;
        }
    }

    /**
     * Shorten a decrypted API key prefix for display so users can identify keys without leaking full values.
     */
    function shortenKeyPrefix(prefix: string | null | undefined): string {
        if (!prefix) {
            return '';
        }
        if (prefix.length <= 8) {
            return prefix;
        }
        return `${prefix.slice(0, 4)}…${prefix.slice(-2)}`;
    }

    /**
     * Build a friendly label for an API key summary.
     * Decrypts encrypted_name and encrypted_key_prefix from the summary.
     * Falls back to apiKey object if encrypted data not available (backward compatibility).
     */
    async function getApiKeyLabel(summary: ApiKeyUsageSummary): Promise<{ title: string; subtitle: string }> {
        let name = '';
        let prefix = '';
        let prefixFromBackend = false; // Track if prefix came from backend encrypted field
        
        // Try to decrypt encrypted fields from summary (preferred method)
        if (summary.encrypted_name || summary.encrypted_key_prefix) {
            try {
                if (summary.encrypted_name) {
                    const decrypted = await decryptWithMasterKey(summary.encrypted_name);
                    if (decrypted) {
                        name = decrypted.trim();
                    }
                }
                if (summary.encrypted_key_prefix) {
                    const decrypted = await decryptWithMasterKey(summary.encrypted_key_prefix);
                    if (decrypted) {
                        prefix = decrypted.trim();
                        prefixFromBackend = true; // Prefix came from backend (already shortened)
                    }
                }
            } catch (err) {
                console.error('[SettingsUsage] Error decrypting API key fields:', err);
            }
        }
        
        // Fallback to apiKey object if encrypted data not available or decryption failed
        if (!name && !prefix && summary.apiKey) {
            name = summary.apiKey.name?.trim() || '';
            prefix = summary.apiKey.key_prefix || '';
            // prefixFromBackend remains false - this is from fallback, so we'll shorten it
        }
        
        const title = name && name.length > 0 ? name : $text('settings.usage.api_key_details.text');
        // Backend always provides a shortened prefix, so display it as-is without further shortening
        // If no prefix available, show empty subtitle (title will be "API key")
        const subtitle = prefix || '';
        
        return { title, subtitle };
    }

    // Fetch summaries when the active tab actually changes after the initial load.
    // We explicitly track the last tab to avoid double-fetching when hasInitialized flips to true.
    let lastFetchedTab: UsageTab = activeTab;
    $effect(() => {
        if (!hasInitialized) {
            // Initial mount handled separately.
            lastFetchedTab = activeTab;
            return;
        }
        if (activeTab === lastFetchedTab) {
            return;
        }
        lastFetchedTab = activeTab;
        fetchUsageSummaries(activeTab, loadedMonths);
    });

    // Load API keys when API tab is active
    $effect(() => {
        if (activeTab === 'api' && apiKeys.length === 0 && !isLoadingApiKeys) {
            loadApiKeys();
        }
    });

    // Load metadata for selected chat when it changes
    $effect(() => {
        if (selectedChatId) {
            loadChatMetadata(selectedChatId);
        }
    });

    // Process and group usage data for display
    const processedUsage = $derived.by(() => {
        console.log('Processing usage entries:', {
            totalEntries: usageEntries.length,
            activeTab,
            timeGrouping,
            sortOption
        });
        
        const filtered = filterByTab(usageEntries);
        console.log('Filtered entries:', filtered.length);
        
        const sorted = sortEntries(filtered);
        console.log('Sorted entries:', sorted.length);
        
        const grouped = groupByTime(sorted);
        console.log('Grouped entries:', Object.keys(grouped).length, 'groups');
        console.log('Grouped data:', grouped);
        
        // Calculate totals for each group
        const groupsWithTotals: Record<string, { entries: UsageEntry[], total: number }> = {};
        Object.entries(grouped).forEach(([key, entries]) => {
            groupsWithTotals[key] = {
                entries: entries,
                total: calculateTotalCredits(entries)
            };
        });
        
        console.log('Final processedUsage:', groupsWithTotals);
        return groupsWithTotals;
    });

    onMount(() => {
        // Load initial summaries
        fetchUsageSummaries(activeTab, loadedMonths).then(() => {
            hasInitialized = true;
        });
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
            onClick={() => fetchUsageSummaries(activeTab, loadedMonths)}
        />
{:else if selectedChatId && usageEntries.length > 0}
    <!-- Detail view for selected chat -->
    <div class="usage-detail-view">
        <button 
            class="back-button"
            onclick={() => selectedChatId = null}
        >
            <div class="clickable-icon icon_back"></div>
            <span>{$text('settings.usage.back.text')}</span>
        </button>
        
        {#if selectedChatId}
            {@const selectedChatMetadata = chatMetadataMap.get(selectedChatId)}
            {@const selectedChat = selectedChatMetadata?.chat}
            {@const selectedMetadata = selectedChatMetadata?.metadata}
            {@const selectedCategory = selectedMetadata?.category || null}
            {@const selectedIconName = selectedMetadata?.icon || (selectedCategory ? getFallbackIconForCategory(selectedCategory) : 'help-circle')}
            {@const selectedGradientColors = selectedCategory ? getCategoryGradientColors(selectedCategory) : null}
            {@const SelectedIconComponent = getLucideIcon(selectedIconName)}
            {@const selectedTitle = selectedMetadata?.title || selectedChat?.title || 'Chat'}
            
            <div class="detail-header">
                <div class="detail-icon-wrapper">
                    <div 
                        class="detail-icon-circle" 
                        style={selectedGradientColors ? `background: linear-gradient(135deg, ${selectedGradientColors.start}, ${selectedGradientColors.end})` : 'background: #cccccc'}
                    >
                        <div class="detail-icon">
                            <SelectedIconComponent size={20} color="white" />
                        </div>
                    </div>
                </div>
                <div class="detail-info">
                    <h3>{selectedTitle}</h3>
                    <p>{selectedAppMonth || getMonthYear(usageEntries[0]?.created_at || 0)}</p>
                </div>
            </div>
        {/if}
        
        {#if isLoadingDetails}
            <div class="loading-state">
                <div class="loading-spinner"></div>
                <span>{$text('settings.usage.loading.text')}</span>
            </div>
        {:else}
        <div class="detail-entries">
            {#each usageEntries as entry}
                {@const appName = entry.app_id ? (() => {
                    try {
                        return $text(`apps.${entry.app_id}.text`);
                    } catch {
                        return entry.app_id;
                    }
                })() : null}
                {@const skillName = entry.skill_id && entry.app_id ? (() => {
                    try {
                        return $text(`apps.${entry.app_id}.skills.${entry.skill_id}.text`);
                    } catch {
                        return entry.skill_id;
                    }
                })() : null}
                {@const displayName = appName && skillName ? `${appName} - ${skillName}` : appName || entry.type || $text('settings.usage.unknown_activity.text')}
                {@const entryIcon = getEntryIcon(entry)}
                
                <div class="detail-entry">
                    <div class="entry-time">{formatRelativeTime(entry.created_at)}</div>
                    <div class="entry-content">
                        <div class="entry-icon icon icon_{entryIcon}"></div>
                        <div class="entry-info">
                            <div class="entry-label">{displayName}</div>
                            {#if entry.app_id && entry.skill_id}
                                <div class="entry-sublabel">{skillName || entry.skill_id}</div>
                            {/if}
                        </div>
                        <div class="entry-credits">
                            <span class="credits-amount">{formatCredits(entry.credits || 0)}</span>
                            <Icon name="coins" type="default" size="16px" className="credits-icon-img" />
                        </div>
                    </div>
                </div>
                {/each}
        </div>
        {/if}
        
        <div class="detail-export">
            <button class="export-button" onclick={exportToCSV}>
                {$text('settings.usage.export.text')}
            </button>
        </div>
    </div>
{:else}
    <!-- Main usage view grouped by time -->
    {#if activeTab === 'api' && selectedApiKeyHash}
        <!-- Detail view for selected API key -->
        <div class="usage-detail-view">
            <button 
                class="back-button"
                onclick={() => {
                    selectedApiKeyHash = null;
                    selectedApiKeyMonth = null;
                }}
            >
                <div class="clickable-icon icon_back"></div>
                <span>{$text('settings.usage.back.text')}</span>
            </button>
            
            {#if selectedApiKeyHash && selectedApiKeyMonth}
                {@const labelKey = `${selectedApiKeyHash}:${selectedApiKeyMonth}`}
                {@const apiKeyLabel = apiKeyLabels.get(labelKey) || { title: $text('settings.usage.api_key_details.text'), subtitle: '' }}
                
                <div class="detail-header">
                    <div class="detail-icon-wrapper">
                        <Icon 
                            name="code"
                            type="default"
                            size="40px"
                        />
                    </div>
                    <div class="detail-info">
                        <h3>{apiKeyLabel.title}</h3>
                        {#if apiKeyLabel.subtitle}
                            <p>{apiKeyLabel.subtitle}</p>
                        {:else}
                            <p>{$text('settings.usage.api_key_details.text')}</p>
                        {/if}
                    </div>
                </div>
            {/if}
            
            {#if isLoadingDetails}
                <div class="loading-state">
                    <div class="loading-spinner"></div>
                    <span>{$text('settings.usage.loading.text')}</span>
                </div>
            {:else}
            <div class="detail-entries">
                {#each usageEntries as entry}
                    {@const appName = entry.app_id ? (() => {
                        try {
                            return $text(`apps.${entry.app_id}.text`);
                        } catch {
                            return entry.app_id;
                        }
                    })() : null}
                    {@const skillName = entry.skill_id && entry.app_id ? (() => {
                        try {
                            return $text(`apps.${entry.app_id}.skills.${entry.skill_id}.text`);
                        } catch {
                            return entry.skill_id;
                        }
                    })() : null}
                    {@const displayName = appName && skillName ? `${appName} - ${skillName}` : appName || entry.type || $text('settings.usage.unknown_activity.text')}
                    {@const entryIcon = getEntryIcon(entry)}
                    
                    <div class="detail-entry">
                        <div class="entry-time">{formatRelativeTime(entry.created_at)}</div>
                        <div class="entry-content">
                            <div class="entry-icon icon icon_{entryIcon}"></div>
                            <div class="entry-info">
                                <div class="entry-label">{displayName}</div>
                                {#if entry.skill_id}
                                    <div class="entry-sublabel">{skillName || entry.skill_id}</div>
                                {/if}
                            </div>
                            <div class="entry-credits">
                                <span class="credits-amount">{formatCredits(entry.credits || 0)}</span>
                                <Icon name="coins" type="default" size="16px" className="credits-icon-img" />
                            </div>
                        </div>
                    </div>
                {/each}
            </div>
            {/if}
        </div>
    {:else if activeTab === 'apps' && selectedAppId && selectedAppMonth}
        <!-- Detail view for selected app -->
        <div class="usage-detail-view">
            <button 
                class="back-button"
                onclick={() => {
                    selectedAppId = null;
                    selectedAppMonth = null;
                }}
            >
                <div class="clickable-icon icon_back"></div>
                <span>{$text('settings.usage.back.text')}</span>
            </button>
            
            {#if selectedAppId}
                {@const appName = getAppName(selectedAppId)}
                {@const appIconName = getAppIconName(selectedAppId)}
                
                <div class="detail-header">
                    <div class="detail-icon-wrapper">
                        <Icon 
                            name={appIconName}
                            type="app"
                            size="40px"
                        />
                    </div>
                    <div class="detail-info">
                        <h3>{appName}</h3>
                        <p>{selectedAppMonth}</p>
                    </div>
                </div>
            {/if}
            
            {#if isLoadingDetails}
                <div class="loading-state">
                    <div class="loading-spinner"></div>
                    <span>{$text('settings.usage.loading.text')}</span>
                </div>
            {:else}
            <div class="detail-entries">
                {#each usageEntries as entry}
                    {@const skillName = entry.skill_id && entry.app_id ? (() => {
                        try {
                            return $text(`apps.${entry.app_id}.skills.${entry.skill_id}.text`);
                        } catch {
                            return entry.skill_id;
                        }
                    })() : null}
                    {@const displayName = skillName || entry.type || $text('settings.usage.unknown_activity.text')}
                    {@const entryIcon = getEntryIcon(entry)}
                    
                    <div class="detail-entry">
                        <div class="entry-time">{formatRelativeTime(entry.created_at)}</div>
                        <div class="entry-content">
                            <div class="entry-icon icon icon_{entryIcon}"></div>
                            <div class="entry-info">
                                <div class="entry-label">{displayName}</div>
                                {#if entry.skill_id}
                                    <div class="entry-sublabel">{skillName || entry.skill_id}</div>
                                {/if}
                            </div>
                            <div class="entry-credits">
                                <span class="credits-amount">{formatCredits(entry.credits || 0)}</span>
                                <Icon name="coins" type="default" size="16px" className="credits-icon-img" />
                            </div>
                        </div>
                    </div>
                {/each}
            </div>
            {/if}
        </div>
    {:else if activeTab === 'chats'}
        <!-- Chat view: Show chats grouped by month with total credits -->
        {#if isLoadingSummaries}
            <div class="loading-state">
                <div class="loading-spinner"></div>
                <span>{$text('settings.usage.loading.text')}</span>
            </div>
        {:else if !hasChatSummaries}
            <div class="empty-state">
                <div class="empty-icon"></div>
                <h4>{$text('settings.usage.no_usage_title.text')}</h4>
                <p>No chat usage found. Try switching tabs.</p>
            </div>
        {:else}
            {#each Array.from(chatsByMonth.entries()) as [month, summaries]}
                {@const monthTotal = summaries.reduce((sum, s) => sum + s.totalCredits, 0)}
                <div class="time-group">
                    <div class="time-header">
                        <h4 class="time-title">{month}</h4>
                        <div class="time-total">
                            <span class="credits-amount">{formatCredits(monthTotal)}</span>
                            <Icon name="coins" type="default" size="16px" className="credits-icon-img" />
                        </div>
                    </div>
                    
                    {#each summaries as summary}
                        {@const chat = summary.chat}
                        {@const metadata = summary.metadata}
                        {@const category = metadata?.category || null}
                        {@const iconName = metadata?.icon || (category ? getFallbackIconForCategory(category) : 'help-circle')}
                        {@const gradientColors = category ? getCategoryGradientColors(category) : null}
                        {@const IconComponent = getLucideIcon(iconName)}
                        {@const title = metadata?.title || chat?.title || 'Chat'}
                        
                        <button
                            type="button"
                            class="chat-usage-item clickable"
                            onclick={async () => {
                                selectedChatId = summary.chat_id;
                                // Fetch details for this chat and month
                                await fetchUsageDetails('chats', summary.chat_id, summary.month);
                            }}
                            aria-label={$text('settings.usage.view_chat_details.text')}
                        >
                            <div class="chat-usage-icon-wrapper">
                                <div 
                                    class="chat-usage-icon-circle" 
                                    style={gradientColors ? `background: linear-gradient(135deg, ${gradientColors.start}, ${gradientColors.end})` : 'background: #cccccc'}
                                >
                                    <div class="chat-usage-icon">
                                        <IconComponent size={16} color="white" />
                                    </div>
                                </div>
                            </div>
                            <div class="chat-usage-content">
                                <div class="chat-usage-title">{title}</div>
                            </div>
                            <div class="chat-usage-credits">
                                <span class="credits-amount">{formatCredits(summary.totalCredits)}</span>
                                <Icon name="coins" type="default" size="16px" className="credits-icon-img" />
                            </div>
                        </button>
                    {/each}
                </div>
            {/each}
        {/if}
    {:else if activeTab === 'apps'}
        <!-- Apps view: Show apps grouped by month with total credits -->
        {#if appsByMonth.size === 0}
            <div class="empty-state">
                <div class="empty-icon"></div>
                <h4>{$text('settings.usage.no_usage_title.text')}</h4>
                <p>No app usage found. Try switching tabs.</p>
            </div>
        {:else}
            {#each Array.from(appsByMonth.entries()) as [month, summaries]}
                {@const monthTotal = summaries.reduce((sum, s) => sum + s.totalCredits, 0)}
                <div class="time-group">
                    <div class="time-header">
                        <h4 class="time-title">{month}</h4>
                        <div class="time-total">
                            <span class="credits-amount">{formatCredits(monthTotal)}</span>
                            <Icon name="coins" type="default" size="16px" className="credits-icon-img" />
                        </div>
                    </div>
                    
                    {#each summaries as summary}
                        {@const appName = getAppName(summary.app_id)}
                        {@const appIconName = getAppIconName(summary.app_id)}
                        
                        <button
                            type="button"
                            class="app-usage-item clickable"
                            onclick={async () => {
                                selectedAppId = summary.app_id;
                                selectedAppMonth = summary.month;
                                // Fetch details for this app and month
                                await fetchUsageDetails('apps', summary.app_id, summary.month);
                            }}
                            aria-label={$text('settings.usage.view_app_details.text')}
                        >
                            <div class="app-usage-icon-wrapper">
                                <Icon 
                                    name={appIconName}
                                    type="app"
                                    size="28px"
                                />
                            </div>
                            <div class="app-usage-content">
                                <div class="app-usage-title">{appName}</div>
                            </div>
                            <div class="app-usage-credits">
                                <span class="credits-amount">{formatCredits(summary.totalCredits)}</span>
                                <Icon name="coins" type="default" size="16px" className="credits-icon-img" />
                            </div>
                        </button>
                    {/each}
                </div>
            {/each}
        {/if}
    {:else if activeTab === 'api'}
        <!-- API keys view: Show API keys grouped by month with total credits -->
        {#if isLoadingApiKeys || isLoadingSummaries}
            <div class="loading-state">
                <div class="loading-spinner"></div>
                <span>{$text('settings.usage.loading.text')}</span>
            </div>
        {:else if apiKeysByMonth.size === 0}
            <div class="empty-state">
                <div class="empty-icon"></div>
                <h4>{$text('settings.usage.no_usage_title.text')}</h4>
                <p>No API key usage found. Try switching tabs.</p>
            </div>
        {:else}
            {#each Array.from(apiKeysByMonth.entries()) as [month, summaries]}
                {@const monthTotal = summaries.reduce((sum, s) => sum + s.totalCredits, 0)}
                <div class="time-group">
                    <div class="time-header">
                        <h4 class="time-title">{month}</h4>
                        <div class="time-total">
                            <span class="credits-amount">{formatCredits(monthTotal)}</span>
                            <Icon name="coins" type="default" size="16px" className="credits-icon-img" />
                        </div>
                    </div>
                    
                    {#each summaries as summary}
                        {@const labelKey = `${summary.api_key_hash}:${summary.month}`}
                        {@const apiKeyLabel = apiKeyLabels.get(labelKey) || { title: $text('settings.usage.api_key_details.text'), subtitle: '' }}
                        
                        <button
                            type="button"
                            class="api-key-usage-item clickable"
                            onclick={async () => {
                                selectedApiKeyHash = summary.api_key_hash;
                                selectedApiKeyMonth = summary.month;
                                // Fetch details for this API key and month
                                await fetchUsageDetails('api', summary.api_key_hash, summary.month);
                            }}
                            aria-label={$text('settings.usage.view_api_key_details.text')}
                        >
                            <div class="api-key-usage-icon-wrapper">
                                <Icon 
                                    name="code"
                                    type="default"
                                    size="28px"
                                />
                            </div>
                            <div class="api-key-usage-content">
                                <div class="api-key-usage-title">{apiKeyLabel.title}</div>
                                {#if apiKeyLabel.subtitle}
                                    <div class="api-key-usage-prefix">{apiKeyLabel.subtitle}</div>
                                {/if}
                            </div>
                            <div class="api-key-usage-credits">
                                <span class="credits-amount">{formatCredits(summary.totalCredits)}</span>
                                <Icon name="coins" type="default" size="16px" className="credits-icon-img" />
                            </div>
                        </button>
                    {/each}
                </div>
            {/each}
        {/if}
    {:else}
        <!-- Non-chat/app/api view: Show entries grouped by time -->
        {@const processedEntries = Object.entries(processedUsage)}
        {#if processedEntries.length === 0 && usageEntries.length > 0}
            <div class="empty-state">
                <div class="empty-icon"></div>
                <h4>{$text('settings.usage.no_usage_title.text')}</h4>
                <p>No entries match the current filter. Try switching tabs.</p>
            </div>
        {:else}
            {#each processedEntries as [timePeriod, { entries, total }]}
            <div class="time-group">
                <div class="time-header">
                    <h4 class="time-title">{timePeriod}</h4>
                    <div class="time-total">
                        <span class="credits-amount">{formatCredits(total)}</span>
                        <Icon name="coins" type="default" size="16px" className="credits-icon-img" />
                    </div>
                </div>
                
                {#each entries as entry}
                    <!-- Non-chat entry or entry without chat_id -->
                    <div class="usage-item">
                        <div class="item-icon icon icon_{getEntryIcon(entry)}"></div>
                        <div class="item-content">
                            <div class="item-title">{getEntryDisplayName(entry)}</div>
                        </div>
                        <div class="item-credits">
                            <span class="credits-amount">{formatCredits(entry.credits || 0)}</span>
                            <Icon name="coins" type="default" size="16px" className="credits-icon-img" />
                        </div>
                    </div>
                {/each}
            </div>
            {/each}
        {/if}
    {/if}
    
    <!-- Show more months button -->
    {#if hasMoreMonths && !isLoadingSummaries}
        <div class="show-more-container">
            <button
                class="show-more-button"
                onclick={showMoreMonths}
                aria-label={$text('settings.usage.show_more.text')}
            >
                {$text('settings.usage.show_more.text')}
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

    .credits-icon-img {
        width: 16px;
        height: 16px;
        opacity: 0.6;
        flex-shrink: 0;
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
        display: flex;
        align-items: center;
        gap: 4px;
    }

    /* Chat usage item styles (matching Chat.svelte) */
    .chat-usage-item {
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
        cursor: pointer;
    }

    .chat-usage-item:hover {
        background: var(--color-grey-15);
        border-color: var(--color-grey-30);
    }

    .chat-usage-icon-wrapper {
        flex: 0 0 28px;
        position: relative;
        height: 28px;
    }

    .chat-usage-icon-circle {
        width: 28px;
        height: 28px;
        border-radius: 50%;
        position: relative;
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0px 2px 4px rgba(0, 0, 0, 0.1);
        border: 2px solid var(--color-background);
        transition: all 0.2s ease;
    }

    .chat-usage-icon {
        width: 16px;
        height: 16px;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .chat-usage-content {
        flex: 1;
        min-width: 0;
    }

    .chat-usage-title {
        color: var(--color-grey-100);
        font-size: 14px;
        font-weight: 500;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .chat-usage-credits {
        color: var(--color-grey-80);
        font-size: 14px;
        font-weight: 600;
        flex-shrink: 0;
        display: flex;
        align-items: center;
        gap: 4px;
    }

    /* App usage item styles (similar to chat usage) */
    .app-usage-item {
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
        cursor: pointer;
    }

    .app-usage-item:hover {
        background: var(--color-grey-15);
        border-color: var(--color-grey-30);
    }

    .app-usage-icon-wrapper {
        flex: 0 0 28px;
        position: relative;
        height: 28px;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .app-usage-content {
        flex: 1;
        min-width: 0;
    }

    .app-usage-title {
        color: var(--color-grey-100);
        font-size: 14px;
        font-weight: 500;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .app-usage-credits {
        color: var(--color-grey-80);
        font-size: 14px;
        font-weight: 600;
        flex-shrink: 0;
        display: flex;
        align-items: center;
        gap: 4px;
    }

    /* API key usage item styles (similar to app usage) */
    .api-key-usage-item {
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
        cursor: pointer;
    }

    .api-key-usage-item:hover {
        background: var(--color-grey-15);
        border-color: var(--color-grey-30);
    }

    .api-key-usage-icon-wrapper {
        flex: 0 0 28px;
        position: relative;
        height: 28px;
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .api-key-usage-content {
        flex: 1;
        min-width: 0;
    }

    .api-key-usage-title {
        color: var(--color-grey-100);
        font-size: 14px;
        font-weight: 500;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .api-key-usage-prefix {
        color: var(--color-grey-60);
        font-size: 12px;
        font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
        margin-top: 2px;
    }

    .api-key-usage-credits {
        color: var(--color-grey-80);
        font-size: 14px;
        font-weight: 600;
        flex-shrink: 0;
        display: flex;
        align-items: center;
        gap: 4px;
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

    .detail-icon-wrapper {
        flex: 0 0 40px;
        position: relative;
        height: 40px;
    }

    .detail-icon-circle {
        width: 40px;
        height: 40px;
        border-radius: 50%;
        position: relative;
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0px 2px 4px rgba(0, 0, 0, 0.1);
        border: 2px solid var(--color-background);
    }

    .detail-icon {
        width: 20px;
        height: 20px;
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
        display: flex;
        align-items: center;
        gap: 4px;
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

    .show-more-container {
        display: flex;
        justify-content: center;
        padding: 20px 10px;
        margin-top: 24px;
        border-top: 1px solid var(--color-grey-20);
    }

    .show-more-button {
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 12px 24px;
        background: var(--color-grey-10);
        border: 1px solid var(--color-grey-30);
        border-radius: 8px;
        color: var(--color-grey-80);
        font-size: 14px;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.2s ease;
    }

    .show-more-button:hover {
        background: var(--color-grey-15);
        border-color: var(--color-grey-40);
    }
</style>
