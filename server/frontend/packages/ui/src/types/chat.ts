export interface MessagePart {
    type: 'text' | 'app-cards';
    content: string | any[];
}

export interface Message {
    id: string;
    role: string; // "user" or mate name
    messageParts: MessagePart[];
    timestamp: Date;
}

export interface Chat {
    id: string;
    title: string;
    isDraft: boolean;
    draftContent?: any;
    mates: string[];
    status?: 'draft' | 'sending' | 'pending' | 'typing';
    typingMate?: string;
    unreadCount?: number;
    lastUpdated: Date;
    messages: Message[];
}
