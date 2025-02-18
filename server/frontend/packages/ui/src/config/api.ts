import { verify } from "crypto";

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
    signup: {
        check_invite_token_valid:   '/v1/auth/check_invite_token_valid',    // Check if invite token is still valid
        check_username_valid:       '/v1/auth/check_username_valid',        // Check if username is valid and available
        signup:                     '/v1/auth/signup',                      // Sign up with username, email, password, mark terms & privacy policy as accepted
        request_email_code:         '/v1/auth/request_email_code',          // For email verification
        verify_email_code:          '/v1/auth/verify_email_code',           // Verify if email code is valid, if so, mark email address as verified
        setup_2fa:                  '/v1/auth/setup_2fa',                   // Setup 2FA for user, returns the QR code for user to scan
        request_backup_codes:       '/v1/auth/request_backup_codes',        // Verify if 2FA code is valid and return backup codes (one time use)
        confirm_codes_stored:       '/v1/auth/confirm_codes_stored',        // Confirm that user has safely stored backup codes (sets 2FA as setup and mandatory for login)
        setup_2fa_provider:         '/v1/auth/setup_2fa_provider',          // Save in profile which 2FA provider was used (to show correct 2FA setup instructions on login screen)
        accept_settings:            '/v1/auth/accept_settings',             // Accept settings (default or custom)
        accept_mate_settings:       '/v1/auth/accept_mate_settings',        // Accept mate settings (default or custom), and AI providers
    },
    login: {
        login:                      '/v1/auth/login',                       // Login with username and password. If 2FA is enabled and 2FA provider is saved, also returns the 2FA provider as hint.
        token_refresh:              '/v1/auth/refresh',                     // Refresh login token
        logout:                     '/v1/auth/logout',                      // Logout and invalidate token
        verify_2fa_code:            '/v1/auth/verify_2fa_code',             // Check if 2FA OTP code is valid
    },
    chat: {
        sendMessage:                '/v1/chat/message',                     // Send a message to a chat (or create a new chat if it doesn't exist)
        cancelProcessing:           '/v1/chat/cancel',                      // Cancel processing of a message
        deleteMessage:              '/v1/chat/delete_message',              // Delete a message from a chat
        deleteChat:                 '/v1/chat/delete',                      // Delete a chat
    },
    settings: {
        update_profile_image:     '/v1/settings/update_profile_image',      // Update profile image of user
    },
} as const;

// Helper to get full API endpoint URL
export function getApiEndpoint(path: string): string {
    return `${getApiUrl()}${path}`;
}
