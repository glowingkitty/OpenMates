/// <reference types="vite/client" />

interface ImportMetaEnv {
    // Self-hosted deployment: Single API URL (takes precedence over DEV/PROD)
    readonly VITE_API_URL: string
    // Cloud deployment: Environment-specific URLs
    readonly VITE_API_URL_DEV: string
    readonly VITE_API_URL_PROD: string
    readonly VITE_WEBSITE_URL_DEV: string
    readonly VITE_WEBSITE_URL_PROD: string
    readonly VITE_WEBAPP_URL_DEV: string
    readonly VITE_WEBAPP_URL_PROD: string
    readonly VITE_CONTACT_EMAIL: string
}

interface ImportMeta {
    readonly env: ImportMetaEnv
}
