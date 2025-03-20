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
    auth: {
        // Session management
        login:                      '/v1/auth/login',                          // Login with username/email and password
        logout:                     '/v1/auth/logout',                         // Logout and invalidate token
        logoutAll:                  '/v1/auth/logout/all',                     // Logout all sessions
        token_refresh:              '/v1/auth/refresh',                        // Refresh login token
        
        // Registration and verification
        check_invite_token_valid:   '/v1/auth/check_invite_token_valid',       // Check if invite token is valid
        check_username_valid:       '/v1/auth/check_username_valid',           // Check if username is valid and available
        request_confirm_email_code: '/v1/auth/request_confirm_email_code',     // Request confirmation email code
        check_confirm_email_code:   '/v1/auth/check_confirm_email_code',       // Verify email confirmation code
        
        // Legacy signup endpoints
        signup:                     '/v1/auth/signup',                         // Sign up with username, email, password
        verify_email_code:          '/v1/auth/verify_email_code',              // Verify email code for older signup flow
        
        // 2FA management
        setup_2fa:                  '/v1/auth/setup_2fa',                      // Setup 2FA, returns QR code to scan
        request_backup_codes:       '/v1/auth/request_backup_codes',           // Get backup codes after verifying 2FA
        confirm_codes_stored:       '/v1/auth/confirm_codes_stored',           // Confirm backup codes are stored by user
        setup_2fa_provider:         '/v1/auth/setup_2fa_provider',             // Save which 2FA provider was used
        verify_2fa_code:            '/v1/auth/verify_2fa_code',                // Verify 2FA OTP code during login
        
        // User setup and preferences
        accept_settings:            '/v1/auth/accept_settings',                // Accept initial user settings
        accept_mate_settings:       '/v1/auth/accept_mate_settings',           // Accept AI provider settings
    },
    chat: {
        sendMessage:                '/v1/chat/message',                         // Send a message to a chat (or create a new chat if it doesn't exist)
        cancelProcessing:           '/v1/chat/cancel',                          // Cancel processing of a message
        deleteMessage:              '/v1/chat/delete_message',                  // Delete a message from a chat
        deleteChat:                 '/v1/chat/delete',                          // Delete a chat
    },
    settings: {
        user: {
            update_profile_image:   '/v1/settings/user/update_profile_image',   // Update profile image of user
        },
        software_update: {
            check:                  '/v1/settings/software_update/check',       // Check for software updates
            install:                '/v1/settings/software_update/install',     // Install software update
            install_status:         '/v1/settings/software_update/install_status', // Get status of software update installation
        }
    }
} as const;

// Helper to get full API endpoint URL
export function getApiEndpoint(path: string): string {
    // Get the base API URL from environment or use default
    const apiBase = import.meta.env.VITE_API_URL || 'http://localhost:8000';
    return `${apiBase}${path}`;
}
