// frontend/apps/web_app/src/lib/types/sync.ts

export type SyncPhase = 'none' | 'phase1' | 'phase2' | 'phase3' | 'complete' | 'error';

export interface SyncStatus {
    phase1Complete: boolean;
    phase2Complete: boolean;
    phase3Complete: boolean;
    cachePrimed: boolean;
    currentPhase: SyncPhase;
    chatCount: number;
    lastSyncTimestamp: number | null;
}

export interface Chat {
    id: string;
    title: string;
    unreadCount: number;
    mates: string[];
    createdAt: number;
    updatedAt: number;
    lastAccessed: number;
}

export interface Message {
    id: string;
    chatId: string;
    content: string;
    senderName: string;
    category?: string;
    role: 'user' | 'assistant' | 'system';
    createdAt: number;
    status: 'delivered' | 'pending' | 'failed';
}

export interface SyncEvent {
    type: 'priorityChatReady' | 'recentChatsReady' | 'fullSyncReady' | 'cache_primed' | 'sync_status_response';
    payload: any;
}

export interface Phase1Payload {
    chat_id: string;
    chat_details: any;
    messages: Message[];
    phase: 'phase1';
}

export interface Phase2Payload {
    chats: any[];
    chat_count: number;
    phase: 'phase2';
}

export interface Phase3Payload {
    chats: any[];
    chat_count: number;
    phase: 'phase3';
}

export interface SyncStatusPayload {
    cache_primed: boolean;
    chat_count: number;
    timestamp: number;
}

export interface StorageStatistics {
    user_id: string;
    chat_count: number;
    max_chat_count: number;
    storage_usage_mb: number;
    max_storage_mb: number;
    utilization_percent: number;
    storage_utilization_percent: number;
    timestamp: number;
}

export interface EvictionCandidate {
    chat_id: string;
    timestamp: number;
    priority: number;
}

export interface StorageStatus {
    current_chat_count: number;
    max_chat_count: number;
    storage_usage_mb: number;
    max_storage_mb: number;
    needs_eviction: boolean;
    eviction_candidates: EvictionCandidate[];
}
