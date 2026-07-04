/*
 * OpenMates runtime platform adapter.
 *
 * Purpose: expose host runtime metadata to shared UI without forking components.
 * Architecture: browser mode is the default; VS Code injects JSON config into
 * #openmates-vscode-config before the bundled app starts.
 * Security: VS Code V1 can request pair-only login without exposing credential
 * login methods inside the webview.
 */

export type OpenMatesPlatform = 'browser' | 'vscode';
export type OpenMatesLoginMode = 'default' | 'pair_only';

export interface OpenMatesRuntimeConfig {
  platform: OpenMatesPlatform;
  loginMode: OpenMatesLoginMode;
  apiBaseUrl?: string;
  remoteAccessSetupCopy?: string;
}

const DEFAULT_RUNTIME_CONFIG: OpenMatesRuntimeConfig = {
  platform: 'browser',
  loginMode: 'default',
};

export function getOpenMatesRuntimeConfig(): OpenMatesRuntimeConfig {
  if (typeof document === 'undefined') return DEFAULT_RUNTIME_CONFIG;

  const configElement = document.getElementById('openmates-vscode-config');
  if (!configElement?.textContent) return DEFAULT_RUNTIME_CONFIG;

  try {
    const rawConfig = JSON.parse(configElement.textContent) as Partial<OpenMatesRuntimeConfig>;
    return {
      platform: rawConfig.platform === 'vscode' ? 'vscode' : 'browser',
      loginMode: rawConfig.loginMode === 'pair_only' ? 'pair_only' : 'default',
      apiBaseUrl: typeof rawConfig.apiBaseUrl === 'string' ? rawConfig.apiBaseUrl : undefined,
      remoteAccessSetupCopy: typeof rawConfig.remoteAccessSetupCopy === 'string' ? rawConfig.remoteAccessSetupCopy : undefined,
    };
  } catch (error) {
    console.warn('[runtime] Failed to parse OpenMates runtime config:', error);
    return DEFAULT_RUNTIME_CONFIG;
  }
}

export function isVscodePairOnlyLogin(): boolean {
  const config = getOpenMatesRuntimeConfig();
  return config.platform === 'vscode' && config.loginMode === 'pair_only';
}
