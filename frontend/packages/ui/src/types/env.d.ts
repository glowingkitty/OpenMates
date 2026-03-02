/// <reference types="vite/client" />

interface ImportMetaEnv {
  // Self-hosted deployment: Single API URL (takes precedence over DEV/PROD)
  readonly VITE_API_URL: string;
  // Cloud deployment: Environment-specific URLs
  readonly VITE_API_URL_DEV: string;
  readonly VITE_API_URL_PROD: string;
  readonly VITE_WEBSITE_URL_DEV: string;
  readonly VITE_WEBSITE_URL_PROD: string;
  readonly VITE_WEBAPP_URL_DEV: string;
  readonly VITE_WEBAPP_URL_PROD: string;
  readonly VITE_CONTACT_EMAIL: string;
  // Upload server URLs (app-uploads microservice — separate VM, not proxied)
  readonly VITE_UPLOAD_URL: string; // self-hosted single override (highest priority)
  readonly VITE_UPLOAD_URL_DEV: string; // cloud dev upload server URL
  readonly VITE_UPLOAD_URL_PROD: string; // cloud prod upload server URL
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
