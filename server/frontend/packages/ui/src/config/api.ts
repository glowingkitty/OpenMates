// API base URLs from environment
export const apiUrls = {
    development: import.meta.env.VITE_API_URL_DEV || 'http://localhost:8000',
    production: import.meta.env.VITE_API_URL_PROD || 'https://api.openmates.org'
} as const;

// Helper to get API URL
export function getApiUrl(): string {
    const isDev = import.meta.env.DEV;
    return isDev ? apiUrls.development : apiUrls.production;
}

// API endpoints
export const apiEndpoints = {
    // Frontend exclusive API endpoints
    login: {
        login:              '/v1/auth/login',
        token_refresh:      '/v1/auth/refresh',
        logout:             '/v1/auth/logout',
        otp:                '/v1/auth/otp',
        // Add other login-related endpoints here
    },
    // Developers can also use the API to interact with these API endpoints:
    chat: {
        sendMessage:        '/v1/chat/message',
        cancelProcessing:   '/v1/chat/cancel',
        deleteMessage:      '/v1/chat/delete_message',
        deleteChat:         '/v1/chat/delete',
        // Add other chat-related endpoints here
    }
    // Add other endpoint categories here
} as const;

// Helper to get full API endpoint URL
export function getApiEndpoint(path: string): string {
    return `${getApiUrl()}${path}`;
}
