/// <reference types="vite/client" />

interface ImportMetaEnv {
    readonly VITE_API_URL_DEV: string
    readonly VITE_API_URL_PROD: string
    readonly VITE_WEBSITE_URL_DEV: string
    readonly VITE_WEBSITE_URL_PROD: string
    readonly VITE_WEBAPP_URL_DEV: string
    readonly VITE_WEBAPP_URL_PROD: string
    readonly VITE_CONTACT_EMAIL: string
    // Explicitly add MODE, though vite/client should provide it
    readonly MODE: 'development' | 'production' | string;
}

interface ImportMeta {
    readonly env: ImportMetaEnv
}
