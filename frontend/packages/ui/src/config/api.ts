// API base URLs from environment
export const apiUrls = {
    development: import.meta.env.VITE_API_URL_DEV || 'http://localhost:8000',
    production: import.meta.env.VITE_API_URL_PROD || 'https://api.openmates.org'
} as const;

// Helper to get API URL
export function getApiUrl(): string {
    // Use VITE_ENV to distinguish between environments.
    // This variable should be set in your deployment environment (e.g., Vercel).
    switch (import.meta.env.VITE_ENV) {
        case 'production':
            return apiUrls.production;
        case 'preview':
            return apiUrls.development; // Use development URL for previews
        default:
            // Fallback for local development where VITE_ENV is not set.
            return apiUrls.development;
    }
}
// Helper to get WebSocket URL
export function getWebSocketUrl(sessionId?: string): string {
    const apiUrl = getApiUrl();
    // Replace http with ws and https with wss
    let wsUrl = apiUrl.replace(/^http/, 'ws') + '/v1/ws';
    if (sessionId) {
        wsUrl += `?sessionId=${sessionId}`;
    }
    return wsUrl;
}

// API endpoints
export const apiEndpoints = {
    auth: {
        // Session management
        lookup:                     '/v1/auth/lookup',                         // Email-only first step to get available login methods
        login:                      '/v1/auth/login',                          // Login with username/email and password
        logout:                     '/v1/auth/logout',                         // Logout and invalidate token
        logoutAll:                  '/v1/auth/logout/all',                     // Logout all sessions
        policyViolationLogout:      '/v1/auth/policy-violation-logout',        // Logout due to policy violation
        session:                    '/v1/auth/session',                        // New session endpoint
        
        // Registration and verification
        check_invite_token_valid:   '/v1/auth/check_invite_token_valid',       // Check if invite token is valid
        check_username_valid:       '/v1/auth/check_username_valid',           // Check if username is valid and available
        request_confirm_email_code: '/v1/auth/request_confirm_email_code',     // Request confirmation email code
        check_confirm_email_code:   '/v1/auth/check_confirm_email_code',       // Verify email confirmation code
        setup_password:             '/v1/auth/setup_password',                 // Setup password and create user account
        
        // Legacy signup endpoints
        signup:                     '/v1/auth/signup',                         // Sign up with username, email, password
        verify_email_code:          '/v1/auth/verify_email_code',              // Verify email code for older signup flow
        
        // 2FA management
        setup_2fa:                  '/v1/auth/2fa/setup/initiate',             // Setup 2FA, returns QR code to scan
        request_backup_codes:       '/v1/auth/2fa/setup/request-backup-codes', // Get backup codes after verifying 2FA
        confirm_codes_stored:       '/v1/auth/2fa/setup/confirm-codes-stored', // Confirm backup codes are stored by user
        confirm_recoverykey_stored: '/v1/auth/recovery-key/confirm-stored',   // Confirm recovery key is stored by user
        setup_2fa_provider:         '/v1/auth/2fa/setup/provider',             // Save which 2FA provider was used
        verify_2fa_code:            '/v1/auth/2fa/setup/verify-signup',        // Verify 2FA OTP code during login
        verifyDevice2FA:            '/v1/auth/2fa/verify/device',              // Verify 2FA OTP code for new device
        
        // Gifted credits endpoints
        checkGift:                  '/v1/auth/check-gift',                     // Check if user has gifted signup credits
        acceptGift:                 '/v1/auth/accept-gift',                    // Accept gifted signup credits
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
            consent_privacy_apps:   '/v1/settings/user/consent/privacy-apps',   // Record consent for privacy/apps settings
            consent_mates:          '/v1/settings/user/consent/mates',          // Record consent for mates settings
            language:               '/v1/settings/user/language',               // Update user language
            darkmode:               '/v1/settings/user/darkmode',               // Update user dark mode preference
        },
        software_update: {
            check:                  '/v1/settings/software_update/check',       // Check for software updates
            install:                '/v1/settings/software_update/install',     // Install software update
            install_status:         '/v1/settings/software_update/install_status', // Get status of software update installation
        }
    },
    payments: {
        config:                     '/v1/payments/config',                      // Get public config for Revolut widget
        createOrder:                '/v1/payments/create-order',                // Create a payment order with Revolut
        orderStatus:                '/v1/payments/order-status',                // Get the status of a specific order (POST request)
        // Webhook endpoint is only called by Revolut, not the frontend
    }
} as const;

// Helper to get full API endpoint URL
export function getApiEndpoint(path: string): string {
    // Get the base API URL using the helper function
    const apiBase = getApiUrl();
    return `${apiBase}${path}`;
}
