<!-- yaml_details
# YAML file explains structure of the UI.
The yaml structure is used as a base for auto generating & auto updating the documentations
and to help LLMs to answer questions regarding how the UI is used.
Instruction to AI: Only update the yaml structure if the UI structure is updated enough to justify
changes to the documentation (to keep the documentation up to date).
-->
<!-- yaml
component:
  name: SettingsSoftwareUpdate
  description: Admin-only component for checking, installing, and configuring software updates
  states:
    - checking: Loading indicator while checking for updates
    - upToDate: No update available, shows current version info
    - updateAvailable: Shows version diff and install button
    - installing: Update in progress, shows per-server status
    - complete: Update succeeded
    - failed: Update failed with error details
  sections:
    - versionInfo: Current commit SHA with GitHub link
    - updateAction: Check/install button
    - updateSettings: Auto-check, auto-install toggles, check interval, clear cache toggle
    - serverVersions: Per-server version info (core, upload, preview, web_app)
-->

<script lang="ts">
    import { getApiEndpoint, text } from '@repo/ui';
    import { onMount, onDestroy } from 'svelte';
    import SettingsItem from '../../SettingsItem.svelte';
    import { fade } from 'svelte/transition';

    // ===========================================================================
    // Types
    // ===========================================================================

    interface CommitInfo {
        sha: string;
        short_sha: string;
        message: string;
        date: string;
        url: string;
    }

    interface UpdateCheckResult {
        update_available: boolean;
        deployment_mode: string;
        current_version: CommitInfo | null;
        latest_version: CommitInfo | null;
        commits_behind: number;
        checked_at: string;
        error: string | null;
    }

    interface ServiceVersionInfo {
        name: string;
        commit: CommitInfo | null;
        branch: string;
        build_timestamp: string;
        deployment_mode: string;
        reachable: boolean;
        error: string | null;
    }

    interface VersionsResponse {
        services: ServiceVersionInfo[];
        deployment_mode: string;
        github_repo_url: string;
    }

    interface SoftwareUpdateConfig {
        auto_check_enabled: boolean;
        auto_check_interval_hours: number;
        auto_update_enabled: boolean;
        clear_cache_on_update: boolean;
        last_check_at: string | null;
        last_update_at: string | null;
    }

    interface ServerUpdateStatus {
        server: string;
        status: string;
        started_at: string | null;
        finished_at: string | null;
        duration_s: number | null;
        steps: Array<{ name: string; success: boolean; duration_s: number; output?: string }>;
        error: string | null;
    }

    interface InstallStatusResponse {
        overall_status: string;
        servers: ServerUpdateStatus[];
        started_at: string | null;
    }

    // ===========================================================================
    // State
    // ===========================================================================

    let isChecking = $state(true);
    let checkResult = $state<UpdateCheckResult | null>(null);
    let checkError = $state<string | null>(null);

    let versions = $state<VersionsResponse | null>(null);
    let config = $state<SoftwareUpdateConfig | null>(null);

    let updateState = $state<'idle' | 'installing' | 'complete' | 'failed'>('idle');
    let installStatus = $state<InstallStatusResponse | null>(null);
    let installError = $state<string | null>(null);

    let statusPollInterval: ReturnType<typeof setInterval> | null = null;
    let configSaveTimeout: ReturnType<typeof setTimeout> | null = null;

    // Derived state
    let hasUpdate = $derived(checkResult?.update_available === true);
    let currentCommit = $derived(checkResult?.current_version ?? null);
    let latestCommit = $derived(checkResult?.latest_version ?? null);
    let commitsBehind = $derived(checkResult?.commits_behind ?? 0);

    // ===========================================================================
    // Constants
    // ===========================================================================

    const STATUS_POLL_INTERVAL_MS = 3000;
    const SERVER_DISPLAY_NAMES: Record<string, string> = {
        core: 'Core API',
        upload: 'Upload',
        preview: 'Preview',
        web_app: 'Web App',
    };

    // ===========================================================================
    // API Calls
    // ===========================================================================

    async function checkForUpdates(): Promise<void> {
        isChecking = true;
        checkError = null;

        try {
            const response = await fetch(
                getApiEndpoint('/v1/settings/software_update/check'),
                { credentials: 'include' }
            );

            if (!response.ok) {
                checkError = response.status === 403
                    ? 'Admin privileges required.'
                    : $text('settings.no_update_check_error');
                return;
            }

            checkResult = await response.json();
        } catch (err) {
            console.error('Failed to check for updates:', err);
            checkError = $text('settings.no_update_check_error');
        } finally {
            isChecking = false;
        }
    }

    async function loadVersions(): Promise<void> {
        try {
            const response = await fetch(
                getApiEndpoint('/v1/settings/software_update/versions'),
                { credentials: 'include' }
            );
            if (response.ok) {
                versions = await response.json();
            }
        } catch (err) {
            console.error('Failed to load versions:', err);
        }
    }

    async function loadConfig(): Promise<void> {
        try {
            const response = await fetch(
                getApiEndpoint('/v1/settings/software_update/config'),
                { credentials: 'include' }
            );
            if (response.ok) {
                config = await response.json();
            }
        } catch (err) {
            console.error('Failed to load config:', err);
        }
    }

    async function saveConfig(updates: Partial<SoftwareUpdateConfig>): Promise<void> {
        try {
            const response = await fetch(
                getApiEndpoint('/v1/settings/software_update/config'),
                {
                    method: 'PUT',
                    credentials: 'include',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(updates),
                }
            );
            if (response.ok) {
                config = await response.json();
            }
        } catch (err) {
            console.error('Failed to save config:', err);
        }
    }

    async function handleInstallUpdate(): Promise<void> {
        updateState = 'installing';
        installError = null;

        try {
            const response = await fetch(
                getApiEndpoint('/v1/settings/software_update/install'),
                {
                    method: 'POST',
                    credentials: 'include',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        clear_cache: config?.clear_cache_on_update ?? true,
                    }),
                }
            );

            if (!response.ok) {
                const errorData = await response.json().catch(() => null);
                installError = errorData?.detail ?? `Install failed (HTTP ${response.status})`;
                updateState = 'failed';
                return;
            }

            // Start polling for status
            startStatusPolling();
        } catch (err) {
            console.error('Failed to start update:', err);
            installError = 'Failed to trigger update. Check your connection.';
            updateState = 'failed';
        }
    }

    async function pollInstallStatus(): Promise<void> {
        try {
            const response = await fetch(
                getApiEndpoint('/v1/settings/software_update/install_status'),
                { credentials: 'include' }
            );

            if (!response.ok) return;

            installStatus = await response.json();

            if (installStatus) {
                if (installStatus.overall_status === 'success') {
                    updateState = 'complete';
                    stopStatusPolling();
                } else if (installStatus.overall_status === 'failed') {
                    updateState = 'failed';
                    const failedServer = installStatus.servers.find(s => s.status === 'failed');
                    installError = failedServer?.error ?? 'Update failed on one or more servers.';
                    stopStatusPolling();
                }
            }
        } catch (err) {
            // Ignore poll errors (server might be restarting)
            console.debug('Status poll error (may be expected during restart):', err);
        }
    }

    function startStatusPolling(): void {
        stopStatusPolling();
        pollInstallStatus();
        statusPollInterval = setInterval(pollInstallStatus, STATUS_POLL_INTERVAL_MS);
    }

    function stopStatusPolling(): void {
        if (statusPollInterval !== null) {
            clearInterval(statusPollInterval);
            statusPollInterval = null;
        }
    }

    // ===========================================================================
    // Config Toggle Handlers
    // ===========================================================================

    function handleAutoCheckChange(): void {
        if (config) {
            debouncedSaveConfig({ auto_check_enabled: config.auto_check_enabled });
        }
    }

    function handleAutoUpdateChange(): void {
        if (config) {
            debouncedSaveConfig({ auto_update_enabled: config.auto_update_enabled });
        }
    }

    function handleClearCacheChange(): void {
        if (config) {
            debouncedSaveConfig({ clear_cache_on_update: config.clear_cache_on_update });
        }
    }

    function handleIntervalChange(event: Event): void {
        const target = event.target as HTMLSelectElement;
        const hours = parseInt(target.value, 10);
        if (config && !isNaN(hours)) {
            config = { ...config, auto_check_interval_hours: hours };
            debouncedSaveConfig({ auto_check_interval_hours: hours });
        }
    }

    function debouncedSaveConfig(updates: Partial<SoftwareUpdateConfig>): void {
        if (configSaveTimeout !== null) {
            clearTimeout(configSaveTimeout);
        }
        configSaveTimeout = setTimeout(() => {
            saveConfig(updates);
        }, 500);
    }

    // ===========================================================================
    // Helpers
    // ===========================================================================

    function getStatusColor(status: string): string {
        switch (status) {
            case 'success': return '#58BC00';
            case 'failed': return '#FF4444';
            case 'in_progress': return 'var(--color-primary)';
            default: return 'var(--color-grey-60)';
        }
    }

    // ===========================================================================
    // Lifecycle
    // ===========================================================================

    onMount(() => {
        checkForUpdates();
        loadVersions();
        loadConfig();
    });

    onDestroy(() => {
        stopStatusPolling();
        if (configSaveTimeout !== null) {
            clearTimeout(configSaveTimeout);
        }
    });
</script>

{#if isChecking}
    <!-- Checking for updates -->
    <div class="checking-container" in:fade={{ duration: 300 }}>
        <span class="search-icon"></span>
        <p class="checking-text">{$text('settings.checking_for_updates')}</p>
    </div>
{:else if checkError}
    <!-- Error checking for updates -->
    <div class="error-container" in:fade={{ duration: 300 }}>
        <p class="error-text">{checkError}</p>
        <button class="retry-button" onclick={() => checkForUpdates()}>
            {$text('settings.check_now')}
        </button>
    </div>
{:else if updateState === 'installing'}
    <!-- Installing update -->
    <div in:fade={{ duration: 300 }}>
        <SettingsItem
            type="heading"
            icon="subsetting_icon download"
            subtitleTop={$text('settings.installing_update')}
            title={latestCommit?.short_sha ?? ''}
        />

        <div class="progress-container">
            <span class="download-icon animated"></span>
            <p class="progress-text">{$text('settings.installing_update')}</p>

            {#if installStatus?.servers}
                <div class="server-status-list">
                    {#each installStatus.servers as server}
                        <div class="server-status-row">
                            <span
                                class="status-dot"
                                style="background-color: {getStatusColor(server.status)}"
                            ></span>
                            <span class="server-name">{SERVER_DISPLAY_NAMES[server.server] ?? server.server}</span>
                            <span class="server-status-text" style="color: {getStatusColor(server.status)}">
                                {server.status === 'in_progress' ? $text('settings.installing_update') : server.status}
                            </span>
                        </div>
                    {/each}
                </div>
            {/if}
        </div>
    </div>
{:else if updateState === 'complete'}
    <!-- Update complete -->
    <div class="progress-container" in:fade={{ duration: 300 }}>
        <span class="check-icon"></span>
        <p class="progress-text">{$text('settings.update_successful')}</p>

        {#if installStatus?.servers}
            <div class="server-status-list">
                {#each installStatus.servers as server}
                    <div class="server-status-row">
                        <span class="status-dot" style="background-color: {getStatusColor(server.status)}"></span>
                        <span class="server-name">{SERVER_DISPLAY_NAMES[server.server] ?? server.server}</span>
                        {#if server.duration_s}
                            <span class="server-duration">{server.duration_s.toFixed(1)}s</span>
                        {/if}
                    </div>
                {/each}
            </div>
        {/if}
    </div>
{:else if updateState === 'failed'}
    <!-- Update failed -->
    <div class="progress-container" in:fade={{ duration: 300 }}>
        <span class="error-icon"></span>
        <!-- eslint-disable-next-line svelte/no-at-html-tags -- translation contains line breaks -->
        <p class="error-text">{@html $text('settings.update_failed')}</p>
        {#if installError}
            <p class="error-detail">{installError}</p>
        {/if}

        <button class="retry-button" onclick={() => { updateState = 'idle'; installError = null; }}>
            {$text('settings.check_now')}
        </button>
    </div>
{:else}
    <!-- Normal view: version info + update action + settings -->
    <div in:fade={{ duration: 300 }}>
        <!-- Version info header -->
        {#if hasUpdate && latestCommit}
            <SettingsItem
                type="heading"
                icon="subsetting_icon download"
                subtitleTop={$text('settings.new_update_available')}
                title={latestCommit.short_sha}
            />

            <div class="version-info">
                <div class="version-row">
                    <span class="version-label">{$text('settings.current_version')}:</span>
                    {#if currentCommit}
                        <a
                            href={currentCommit.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            class="commit-link"
                        >
                            {currentCommit.short_sha}
                        </a>
                    {:else}
                        <span class="version-value">—</span>
                    {/if}
                </div>

                {#if commitsBehind > 0}
                    <p class="commits-behind">
                        {$text('settings.commits_behind').replace('{count}', String(commitsBehind))}
                    </p>
                {/if}

                {#if latestCommit.message}
                    <p class="commit-message">{latestCommit.message}</p>
                {/if}
            </div>

            <div class="install-button-container">
                <button onclick={handleInstallUpdate}>
                    {$text('settings.install')}
                </button>
            </div>

            <!-- eslint-disable-next-line svelte/no-at-html-tags -- translation contains line breaks -->
            <p class="restart-notice">{@html $text('settings.server_will_be_restarted')}</p>
        {:else}
            <!-- Up to date -->
            <SettingsItem
                type="heading"
                icon="subsetting_icon download"
                subtitleTop={$text('settings.installed')}
                title={currentCommit?.short_sha ?? '—'}
            />

            <div class="up-to-date-container">
                <span class="check-icon small"></span>
                <p class="up-to-date-text">{$text('settings.up_to_date')}</p>
            </div>

            {#if currentCommit?.url}
                <div class="version-info">
                    <a
                        href={currentCommit.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        class="github-link"
                    >
                        {$text('settings.view_on_github')}
                    </a>
                </div>
            {/if}

            <div class="check-button-container">
                <button class="secondary-button" onclick={() => checkForUpdates()}>
                    {$text('settings.check_now')}
                </button>
            </div>
        {/if}

        <!-- Update Settings Section -->
        {#if config}
            <div class="settings-section">
                <h3 class="section-heading">{$text('settings.update_settings')}</h3>

                <div class="setting-row">
                    <span class="setting-label">{$text('settings.auto_check_for_updates')}</span>
                    <input
                        type="checkbox"
                        class="toggle-checkbox"
                        bind:checked={config.auto_check_enabled}
                        onchange={handleAutoCheckChange}
                    />
                </div>

                {#if config.auto_check_enabled}
                    <div class="setting-row">
                        <span class="setting-label">{$text('settings.check_interval')}</span>
                        <select
                            class="interval-select"
                            value={String(config.auto_check_interval_hours)}
                            onchange={handleIntervalChange}
                        >
                            <option value="1">1h</option>
                            <option value="3">3h</option>
                            <option value="6">6h</option>
                            <option value="12">12h</option>
                            <option value="24">24h</option>
                            <option value="48">48h</option>
                            <option value="168">168h</option>
                        </select>
                    </div>

                    <div class="setting-row">
                        <span class="setting-label">{$text('settings.auto_install_updates')}</span>
                        <input
                            type="checkbox"
                            class="toggle-checkbox"
                            bind:checked={config.auto_update_enabled}
                            onchange={handleAutoUpdateChange}
                        />
                    </div>
                {/if}

                <div class="setting-row">
                    <span class="setting-label">{$text('settings.clear_cache_on_update')}</span>
                    <input
                        type="checkbox"
                        class="toggle-checkbox"
                        bind:checked={config.clear_cache_on_update}
                        onchange={handleClearCacheChange}
                    />
                </div>
            </div>
        {/if}

        <!-- Server Versions Section -->
        {#if versions?.services && versions.services.length > 0}
            <div class="settings-section">
                <h3 class="section-heading">{$text('settings.server_versions')}</h3>

                <div class="server-versions-list">
                    {#each versions.services as service}
                        <div class="server-version-row">
                            <div class="server-version-info">
                                <span class="server-version-name">
                                    {SERVER_DISPLAY_NAMES[service.name] ?? service.name}
                                </span>
                                {#if service.reachable && service.commit}
                                    <a
                                        href={service.commit.url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        class="commit-link small"
                                    >
                                        {service.commit.short_sha}
                                    </a>
                                {:else if !service.reachable}
                                    <span class="unreachable-badge">
                                        {$text('settings.unreachable')}
                                    </span>
                                {:else}
                                    <span class="version-value">—</span>
                                {/if}
                            </div>
                            {#if service.branch}
                                <span class="branch-badge">{service.branch}</span>
                            {/if}
                        </div>
                    {/each}
                </div>
            </div>
        {/if}
    </div>
{/if}

<style>
    /* Containers */
    .checking-container,
    .progress-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        margin-top: 40px;
        width: 100%;
    }

    .error-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        margin-top: 40px;
        gap: 16px;
    }

    .up-to-date-container {
        display: flex;
        flex-direction: row;
        align-items: center;
        justify-content: center;
        gap: 8px;
        margin-top: 16px;
    }

    /* Icons */
    .search-icon,
    .download-icon,
    .check-icon,
    .error-icon {
        width: 57px;
        height: 57px;
        -webkit-mask-size: contain;
        mask-size: contain;
        background: var(--color-primary);
    }

    .check-icon.small {
        width: 20px;
        height: 20px;
    }

    .search-icon {
        -webkit-mask: url('@openmates/ui/static/icons/search.svg') no-repeat center;
        mask: url('@openmates/ui/static/icons/search.svg') no-repeat center;
    }

    .download-icon {
        -webkit-mask: url('@openmates/ui/static/icons/download.svg') no-repeat center;
        mask: url('@openmates/ui/static/icons/download.svg') no-repeat center;
    }

    .download-icon.animated {
        animation: pulse 1.5s ease-in-out infinite;
    }

    .check-icon {
        -webkit-mask: url('@openmates/ui/static/icons/check.svg') no-repeat center;
        mask: url('@openmates/ui/static/icons/check.svg') no-repeat center;
        background: #58BC00;
    }

    .error-icon {
        -webkit-mask: url('@openmates/ui/static/icons/close.svg') no-repeat center;
        mask: url('@openmates/ui/static/icons/close.svg') no-repeat center;
        background: #FF4444;
    }

    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.5; }
    }

    /* Text */
    .checking-text,
    .progress-text {
        color: var(--color-grey-60);
        font-size: 14px;
        text-align: center;
    }

    .error-text {
        color: #FF4444;
        font-size: 14px;
        text-align: center;
    }

    .error-detail {
        color: var(--color-grey-60);
        font-size: 12px;
        text-align: center;
        max-width: 300px;
        word-break: break-word;
    }

    .up-to-date-text {
        color: #58BC00;
        font-size: 14px;
        margin: 0;
    }

    /* Version info */
    .version-info {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 6px;
        margin-top: 12px;
        padding: 0 20px;
    }

    .version-row {
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .version-label {
        color: var(--color-grey-60);
        font-size: 13px;
    }

    .version-value {
        color: var(--color-grey-60);
        font-size: 13px;
    }

    .commit-link {
        color: var(--color-primary);
        font-size: 13px;
        font-family: monospace;
        text-decoration: none;
    }

    .commit-link:hover {
        text-decoration: underline;
    }

    .commit-link.small {
        font-size: 12px;
    }

    .commits-behind {
        color: var(--color-warning, #FFA500);
        font-size: 13px;
        margin: 0;
    }

    .commit-message {
        color: var(--color-grey-60);
        font-size: 12px;
        text-align: center;
        margin: 4px 0 0;
        max-width: 300px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }

    .github-link {
        color: var(--color-primary);
        font-size: 13px;
        text-decoration: none;
    }

    .github-link:hover {
        text-decoration: underline;
    }

    /* Buttons */
    .install-button-container,
    .check-button-container {
        display: flex;
        justify-content: center;
        align-items: center;
        margin-top: 16px;
    }

    .restart-notice {
        color: var(--color-grey-60);
        font-size: 14px;
        text-align: center;
        margin-top: 10px;
    }

    .retry-button,
    .secondary-button {
        background: var(--color-grey-20);
        color: var(--color-text);
        border: 1px solid var(--color-grey-30);
        border-radius: 8px;
        padding: 8px 20px;
        font-size: 14px;
        cursor: pointer;
        transition: background 0.2s;
    }

    .retry-button:hover,
    .secondary-button:hover {
        background: var(--color-grey-30);
    }

    /* Settings section */
    .settings-section {
        margin-top: 32px;
        padding: 0 16px;
    }

    .section-heading {
        color: var(--color-grey-60);
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin: 0 0 12px;
        padding-bottom: 8px;
        border-bottom: 1px solid var(--color-grey-20);
    }

    .setting-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 0;
    }

    .setting-label {
        color: var(--color-text);
        font-size: 14px;
    }

    .interval-select {
        background: var(--color-grey-10);
        color: var(--color-text);
        border: 1px solid var(--color-grey-30);
        border-radius: 6px;
        padding: 4px 8px;
        font-size: 13px;
        cursor: pointer;
    }

    .toggle-checkbox {
        width: 18px;
        height: 18px;
        cursor: pointer;
        accent-color: var(--color-primary);
    }

    /* Server versions */
    .server-versions-list {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .server-version-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 8px 0;
        border-bottom: 1px solid var(--color-grey-15, var(--color-grey-10));
    }

    .server-version-row:last-child {
        border-bottom: none;
    }

    .server-version-info {
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .server-version-name {
        color: var(--color-text);
        font-size: 14px;
        font-weight: 500;
    }

    .branch-badge {
        background: var(--color-grey-20);
        color: var(--color-grey-60);
        font-size: 11px;
        padding: 2px 6px;
        border-radius: 4px;
        font-family: monospace;
    }

    .unreachable-badge {
        color: #FF4444;
        font-size: 12px;
    }

    /* Server status (during install) */
    .server-status-list {
        margin-top: 16px;
        width: 100%;
        max-width: 300px;
    }

    .server-status-row {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 0;
    }

    .status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        flex-shrink: 0;
    }

    .server-name {
        color: var(--color-text);
        font-size: 13px;
        flex: 1;
    }

    .server-status-text {
        font-size: 12px;
    }

    .server-duration {
        color: var(--color-grey-60);
        font-size: 12px;
        font-family: monospace;
    }
</style>
