export type MessageStatus = 'pending' | 'sent' | 'waiting_for_internet' | 'error';

export interface MessagePart {
    type: 'text' | 'app-cards';
    content: string | any[];
}

export interface Message {
    id: string;
    role: string; // "user" or mate name
    content: any; // TipTap JSON content
    status?: MessageStatus;
    timestamp: number;
}

export interface Chat {
    id: string;
    title: string;
    isDraft?: boolean;
    draftContent?: any;
    mates: string[];
    status?: 'draft' | 'sending' | 'pending' | 'typing';
    typingMate?: string;
    unreadCount?: number;
    lastUpdated: Date;
    messages: Message[];
    _v?: number; // Version number for sync conflict resolution (optional on client)
}

// Represents the metadata for a chat shown in the activity list
export interface ChatListEntry {
    id: string;
    title: string;
    lastUpdated: string | Date; // ISO string or Date object
    unreadCount?: number;
    isDraft?: boolean; // Keep track if it's primarily a draft
    // Add other relevant metadata fields if needed, e.g., folderId, icon, mateId
    // TODO: Verify these fields against the actual WebSocket payload for chat list updates.
}
