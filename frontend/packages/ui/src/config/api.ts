// API base URLs from environment
// VITE_API_URL: Single URL for self-hosted deployments (takes precedence over all other settings)
// VITE_API_URL_DEV/PROD: Environment-specific URLs for cloud deployments
//
// Upload server URLs from environment
// VITE_UPLOAD_URL: Single URL for self-hosted deployments (takes precedence)
// VITE_UPLOAD_URL_DEV/PROD: Environment-specific upload server URLs for cloud deployments
// The upload server (app-uploads microservice) is a separate VM — NOT proxied through the web app.
// Both dev and prod deployments use the same upload server: https://upload.openmates.org
// The upload server distinguishes dev vs prod requests via the Origin header (set by Caddy).
export const uploadUrls = {
  development:
    import.meta.env.VITE_UPLOAD_URL_DEV || "https://upload.openmates.org",
  production:
    import.meta.env.VITE_UPLOAD_URL_PROD || "https://upload.openmates.org",
} as const;

// Helper to get the upload server base URL
export function getUploadUrl(): string {
  // VITE_UPLOAD_URL takes precedence — used for self-hosted deployments
  if (import.meta.env.VITE_UPLOAD_URL) {
    return import.meta.env.VITE_UPLOAD_URL;
  }

  switch (import.meta.env.VITE_ENV) {
    case "production":
      return uploadUrls.production;
    case "preview":
      return uploadUrls.development;
    default:
      return uploadUrls.development;
  }
}

export const apiUrls = {
  development: import.meta.env.VITE_API_URL_DEV || "http://localhost:8000",
  production: import.meta.env.VITE_API_URL_PROD || "https://api.openmates.org",
} as const;

// Helper to get API URL
export function getApiUrl(): string {
  // VITE_API_URL takes precedence - used for self-hosted deployments
  // This allows setting a single API URL at build time without needing VITE_ENV
  // Example: VITE_API_URL=http://192.168.1.100:8000 pnpm build
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL;
  }

  // Use VITE_ENV to distinguish between environments.
  // This variable should be set in your deployment environment (e.g., Vercel).
  switch (import.meta.env.VITE_ENV) {
    case "production":
      return apiUrls.production;
    case "preview":
      return apiUrls.development; // Use development URL for previews
    default:
      // Fallback for local development where VITE_ENV is not set.
      return apiUrls.development;
  }
}
// Helper to get WebSocket URL
export function getWebSocketUrl(sessionId?: string, token?: string): string {
  const apiUrl = getApiUrl();
  // Replace http with ws and https with wss
  let wsUrl = apiUrl.replace(/^http/, "ws") + "/v1/ws";

  const params: string[] = [];
  if (sessionId) {
    params.push(`sessionId=${sessionId}`);
  }
  if (token) {
    params.push(`token=${encodeURIComponent(token)}`);
  }

  if (params.length > 0) {
    wsUrl += `?${params.join("&")}`;
  }

  return wsUrl;
}

// API endpoints
export const apiEndpoints = {
  auth: {
    // Session management
    lookup: "/v1/auth/lookup", // Email-only first step to get available login methods
    login: "/v1/auth/login", // Login with username/email and password
    logout: "/v1/auth/logout", // Logout and invalidate token
    logoutAll: "/v1/auth/logout/all", // Logout all sessions
    policyViolationLogout: "/v1/auth/policy-violation-logout", // Logout due to policy violation
    session: "/v1/auth/session", // New session endpoint

    // Registration and verification
    check_invite_token_valid: "/v1/auth/check_invite_token_valid", // Check if invite token is valid
    check_username_valid: "/v1/auth/check_username_valid", // Check if username is valid and available
    request_confirm_email_code: "/v1/auth/request_confirm_email_code", // Request confirmation email code
    check_confirm_email_code: "/v1/auth/check_confirm_email_code", // Verify email confirmation code
    setup_password: "/v1/auth/setup_password", // Setup password and create user account

    // Passkey endpoints
    passkey_registration_initiate: "/v1/auth/passkey/registration/initiate", // Initiate passkey registration
    passkey_registration_complete: "/v1/auth/passkey/registration/complete", // Complete passkey registration
    passkey_assertion_initiate: "/v1/auth/passkey/assertion/initiate", // Initiate passkey login
    passkey_assertion_verify: "/v1/auth/passkey/assertion/verify", // Verify passkey login
    passkey_list: "/v1/auth/passkeys", // List all user passkeys
    passkey_rename: "/v1/auth/passkeys/rename", // Rename a passkey
    passkey_delete: "/v1/auth/passkeys/delete", // Delete a passkey
    passkey_verify_device: "/v1/auth/passkey/verify/device", // Verify passkey for new device verification

    // Legacy signup endpoints
    signup: "/v1/auth/signup", // Sign up with username, email, password
    verify_email_code: "/v1/auth/verify_email_code", // Verify email code for older signup flow

    // 2FA management
    setup_2fa: "/v1/auth/2fa/setup/initiate", // Setup 2FA, returns QR code to scan
    request_backup_codes: "/v1/auth/2fa/setup/request-backup-codes", // Get backup codes after verifying 2FA
    confirm_codes_stored: "/v1/auth/2fa/setup/confirm-codes-stored", // Confirm backup codes are stored by user
    confirm_recoverykey_stored: "/v1/auth/recovery-key/confirm-stored", // Confirm recovery key is stored by user
    regenerate_recovery_key: "/v1/auth/recovery-key/regenerate", // Regenerate recovery key (requires auth)
    reset_backup_codes: "/v1/auth/2fa/setup/reset-backup-codes", // Regenerate backup codes (requires auth, 2FA must be enabled)
    setup_2fa_provider: "/v1/auth/2fa/setup/provider", // Save which 2FA provider was used
    verify_2fa_code: "/v1/auth/2fa/setup/verify-signup", // Verify 2FA OTP code during login
    verifyDevice2FA: "/v1/auth/2fa/verify/device", // Verify 2FA OTP code for new device

    // Gifted credits endpoints
    checkGift: "/v1/auth/check-gift", // Check if user has gifted signup credits
    acceptGift: "/v1/auth/accept-gift", // Accept gifted signup credits

    // Account recovery endpoints (for users who lost all login methods including recovery key)
    recovery_request: "/v1/auth/recovery/request-code", // Request account recovery code via email
    recovery_verify: "/v1/auth/recovery/verify-code", // Verify recovery code and get verification token
    recovery_setup_2fa: "/v1/auth/recovery/setup-2fa", // Generate 2FA setup data during recovery
    recovery_full_reset: "/v1/auth/recovery/reset-account", // Full account reset (deletes all data)
  },
  chat: {
    sendMessage: "/v1/chat/message", // Send a message to a chat (or create a new chat if it doesn't exist)
    cancelProcessing: "/v1/chat/cancel", // Cancel processing of a message
    deleteMessage: "/v1/chat/delete_message", // Delete a message from a chat
    deleteChat: "/v1/chat/delete", // Delete a chat
  },
  settings: {
    serverStatus: "/v1/settings/server-status", // Get server status (payment enabled, server edition, etc.)
    reminders: "/v1/settings/reminders", // Get active (pending) reminders for app settings
    user: {
      update_profile_image: "/v1/settings/user/update_profile_image", // Update profile image of user
      consent_privacy_apps: "/v1/settings/user/consent/privacy-apps", // Record consent for privacy/apps settings
      consent_mates: "/v1/settings/user/consent/mates", // Record consent for mates settings
      language: "/v1/settings/user/language", // Update user language
      darkmode: "/v1/settings/user/darkmode", // Update user dark mode preference
      timezone: "/v1/settings/user/timezone", // Update user timezone (auto-detected or manual)
    },
    autoTopUp: {
      lowBalance: "/v1/settings/auto-topup/low-balance", // Update low balance auto top-up settings (requires 2FA)
    },
    autoDeleteChats: "/v1/settings/auto-delete-chats", // Persist chat auto-deletion period
    software_update: {
      check: "/v1/settings/software_update/check", // Check for software updates
      install: "/v1/settings/software_update/install", // Install software update
      install_status: "/v1/settings/software_update/install_status", // Get status of software update installation
    },
    deleteAccountPreview: "/v1/settings/delete-account-preview", // Get preview of account deletion consequences
    deleteAccount: "/v1/settings/delete-account", // Delete user account
    exportAccountManifest: "/v1/settings/export-account-manifest", // Get export manifest (list of all data IDs)
    exportAccountData: "/v1/settings/export-account-data", // Get export data (usage, invoices, profile)
    updatePassword: "/v1/settings/update-password", // Add or change user password
  },
  payments: {
    config: "/v1/payments/config", // Get public config for payment provider
    createOrder: "/v1/payments/create-order", // Create a payment order
    createSupportOrder: "/v1/payments/create-support-order", // Create a supporter contribution order
    orderStatus: "/v1/payments/order-status", // Get the status of a specific order (POST request)
    savePaymentMethod: "/v1/payments/save-payment-method", // Save payment method from successful payment
    hasPaymentMethod: "/v1/payments/has-payment-method", // Check if user has a saved payment method
    listPaymentMethods: "/v1/payments/payment-methods", // List all saved payment methods for user
    processPaymentWithSavedMethod:
      "/v1/payments/process-payment-with-saved-method", // Process payment with saved payment method
    getUserAuthMethods: "/v1/payments/user-auth-methods", // Get user authentication methods (passkey/2FA)
    createSubscription: "/v1/payments/create-subscription", // Create monthly auto top-up subscription
    getSubscription: "/v1/payments/subscription", // Get user's subscription details
    cancelSubscription: "/v1/payments/cancel-subscription", // Cancel monthly subscription
    updateBillingDayPreference: "/v1/payments/update-billing-day-preference", // Update billing day preference
    redeemGiftCard: "/v1/payments/redeem-gift-card", // Redeem a gift card code
    buyGiftCard: "/v1/payments/buy-gift-card", // Purchase a gift card for someone else
    getRedeemedGiftCards: "/v1/payments/redeemed-gift-cards", // Get user's redeemed gift cards
    getPurchasedGiftCards: "/v1/payments/purchased-gift-cards", // Get user's purchased gift cards
    getInvoices: "/v1/payments/invoices", // Get user's invoices
    downloadInvoice: "/v1/payments/invoices/{id}/download", // Download specific invoice PDF
    downloadCreditNote: "/v1/payments/invoices/{id}/credit-note/download", // Download credit note PDF for refunded invoice
    requestRefund: "/v1/payments/refund", // Request refund for unused credits
    // Webhook endpoint is only called by payment providers, not the frontend
  },
  apps: {
    metadata: "/v1/apps/metadata", // Get metadata for all discovered apps
    mostUsed: "/v1/apps/most-used", // Get most used apps in last 30 days (public endpoint)
  },
  admin: {
    generateGiftCards: "/v1/admin/generate-gift-cards", // Admin-only: generate gift card codes
    clientLogs: "/v1/admin/client-logs", // Admin-only: forward browser console logs to Loki for centralized debugging
  },
  server: {
    info: "/v1/server", // Get server information (domain and self_hosted flag based on request validation)
  },
  usage: {
    getUsage: "/v1/settings/usage", // Get user usage data (legacy)
    getSummaries: "/v1/settings/usage/summaries", // Get usage summaries (fast)
    getDetails: "/v1/settings/usage/details", // Get usage details (lazy loading)
    getDailyOverview: "/v1/settings/usage/daily-overview", // Get daily usage overview (all types combined, grouped by day)
    getChatEntries: "/v1/settings/usage/chat-entries", // Get all usage entries for a specific chat (no month filter)
    chatTotal: "/v1/settings/usage/chat-total", // Get total credits for a specific chat
    messageCost: "/v1/settings/usage/message-cost", // Get credits for a specific message
    export: "/v1/settings/usage/export", // Export usage data as CSV
  },
  creators: {
    tip: "/v1/creators/tip", // Tip a creator with credits
  },
  newsletter: {
    subscribe: "/v1/newsletter/subscribe", // Subscribe to newsletter (sends confirmation email)
    confirm: "/v1/newsletter/confirm", // Confirm newsletter subscription (via token)
    unsubscribe: "/v1/newsletter/unsubscribe", // Unsubscribe from newsletter (via persistent token stored in Directus)
  },
  emailBlock: {
    blockEmail: "/v1/block-email", // Block email address from all emails (signup, newsletter, etc.)
  },
} as const;

// Helper to get full API endpoint URL
export function getApiEndpoint(path: string = ""): string {
  // Get the base API URL using the helper function
  const apiBase = getApiUrl();
  return `${apiBase}${path}`;
}
