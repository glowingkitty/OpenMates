<script lang="ts">
    import { onMount, createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { getApiEndpoint } from '../../../config/api';
    import SettingsButton from '../elements/SettingsButton.svelte';
    import SettingsButtonGroup from '../elements/SettingsButtonGroup.svelte';
    import SettingsCard from '../elements/SettingsCard.svelte';
    import SettingsCodeBlock from '../elements/SettingsCodeBlock.svelte';
    import SettingsConfirmBlock from '../elements/SettingsConfirmBlock.svelte';
    import SettingsDetailRow from '../elements/SettingsDetailRow.svelte';
    import SettingsDropdown from '../elements/SettingsDropdown.svelte';
    import SettingsInfoBox from '../elements/SettingsInfoBox.svelte';
    import SettingsInput from '../elements/SettingsInput.svelte';
    import SettingsItem from '../elements/SettingsItem.svelte';
    import SettingsLoadingState from '../elements/SettingsLoadingState.svelte';
    import SettingsPageContainer from '../elements/SettingsPageContainer.svelte';
    import SettingsSectionHeading from '../elements/SettingsSectionHeading.svelte';
    import { appSkillsStore } from '../../../stores/appSkillsStore';
    import {
        encryptWithMasterKeyDirect,
        decryptWithMasterKey,
        deriveKeyFromApiKey,
        encryptKey,
        getKeyFromStorage,
        uint8ArrayToBase64,
    } from '../../../services/cryptoService';

    const API_KEYS_ROOT_PATH = 'developers/api-keys';
    const API_KEYS_CREATE_PATH = 'developers/api-keys/create';
    const MAX_API_KEYS = 5;

    const dispatch = createEventDispatcher();

    interface ApiKey {
        id: string;
        name: string;
        key_prefix: string;
        created_at: string | null;
        last_used: string | null;
        encrypted_name?: string;
        encrypted_key_prefix?: string;
        full_access?: boolean;
        scopes?: Record<string, unknown>;
        credit_limit?: { period: string; credits: number } | null;
        pending_device_count?: number;
    }

    type CreditPeriod = 'unlimited' | 'daily' | 'weekly' | 'monthly' | 'lifetime';
    type ExpirationPreset = '7d' | '30d' | '90d' | '1y' | 'never';
    type AppsMode = 'all' | 'selected';
    type ScopeDefinition = { id: string; labelKey: string };
    type ScopeCategory = { id: string; labelKey: string; icon: string; scopes: ScopeDefinition[] };

    const SCOPE_CATEGORIES: ScopeCategory[] = [
        {
            id: 'chat', labelKey: 'settings.api_keys.category_chats', icon: 'chat', scopes: [
                { id: 'chat:create_incognito', labelKey: 'settings.api_keys.scope_chat_create_incognito' },
                { id: 'chat:create_saved', labelKey: 'settings.api_keys.scope_chat_create_saved' },
                { id: 'chat:read_existing', labelKey: 'settings.api_keys.scope_chat_read_existing' },
                { id: 'chat:append_existing', labelKey: 'settings.api_keys.scope_chat_append_existing' },
                { id: 'chat:delete', labelKey: 'settings.api_keys.scope_chat_delete' },
                { id: 'chat:share', labelKey: 'settings.api_keys.scope_chat_share' },
                { id: 'chat:export', labelKey: 'settings.api_keys.scope_chat_export' },
            ]
        },
        {
            id: 'tasks', labelKey: 'settings.api_keys.category_tasks', icon: 'task', scopes: [
                { id: 'task:read', labelKey: 'settings.api_keys.scope_task_read' },
                { id: 'task:read_metadata', labelKey: 'settings.api_keys.scope_task_read_metadata' },
                { id: 'task:create', labelKey: 'settings.api_keys.scope_task_create' },
                { id: 'task:write', labelKey: 'settings.api_keys.scope_task_write' },
            ]
        },
        {
            id: 'projects', labelKey: 'settings.api_keys.category_projects', icon: 'puzzle', scopes: [
                { id: 'project:read', labelKey: 'settings.api_keys.scope_project_read' },
                { id: 'project:create', labelKey: 'settings.api_keys.scope_project_create' },
                { id: 'project:write', labelKey: 'settings.api_keys.scope_project_write' },
            ]
        },
        {
            id: 'plans', labelKey: 'settings.api_keys.category_plans', icon: 'puzzle', scopes: [
                { id: 'plan:read', labelKey: 'settings.api_keys.scope_plan_read' },
                { id: 'plan:read_metadata', labelKey: 'settings.api_keys.scope_plan_read_metadata' },
                { id: 'plan:create', labelKey: 'settings.api_keys.scope_plan_create' },
                { id: 'plan:write', labelKey: 'settings.api_keys.scope_plan_write' },
            ]
        },
        {
            id: 'workflows', labelKey: 'settings.api_keys.category_workflows', icon: 'create', scopes: [
                { id: 'workflow:read', labelKey: 'settings.api_keys.scope_workflow_read' },
                { id: 'workflow:create', labelKey: 'settings.api_keys.scope_workflow_create' },
                { id: 'workflow:write', labelKey: 'settings.api_keys.scope_workflow_write' },
                { id: 'workflow:execute', labelKey: 'settings.api_keys.scope_workflow_execute' },
            ]
        },
        {
            id: 'memories', labelKey: 'settings.api_keys.category_memories', icon: 'settings_memories', scopes: [
                { id: 'memory:read', labelKey: 'settings.api_keys.scope_memory_read' },
                { id: 'memory:write', labelKey: 'settings.api_keys.scope_memory_write' },
            ]
        },
        {
            id: 'account', labelKey: 'settings.api_keys.category_account_export', icon: 'download', scopes: [
                { id: 'account:export', labelKey: 'settings.api_keys.scope_account_export' },
                { id: 'account:import', labelKey: 'settings.api_keys.scope_account_import' },
            ]
        },
        {
            id: 'developer', labelKey: 'settings.api_keys.title', icon: 'key', scopes: [
                { id: 'developer:api_keys:read', labelKey: 'settings.api_keys.scope_api_keys_read' },
                { id: 'developer:api_keys:create', labelKey: 'settings.api_keys.scope_api_keys_create' },
                { id: 'developer:api_keys:revoke', labelKey: 'settings.api_keys.scope_api_keys_revoke' },
            ]
        },
        {
            id: 'developer', labelKey: 'common.devices', icon: 'devices', scopes: [
                { id: 'developer:devices:read', labelKey: 'settings.api_keys.scope_devices_read' },
                { id: 'developer:devices:approve', labelKey: 'settings.api_keys.scope_devices_approve' },
                { id: 'developer:devices:revoke', labelKey: 'settings.api_keys.scope_devices_revoke' },
            ]
        },
    ];

    const FIXED_SCOPES = SCOPE_CATEGORIES.flatMap((category) => category.scopes.map((scope) => scope.id));
    const APP_SCOPE_OPTIONS = Object.values(appSkillsStore.getState().apps)
        .filter((app) => !app.internal && app.skills.length > 0)
        .sort((left, right) => left.id.localeCompare(right.id));

    let {
        activeSettingsView = API_KEYS_ROOT_PATH,
    }: {
        activeSettingsView?: string;
    } = $props();

    let apiKeys = $state<ApiKey[]>([]);
    let loading = $state(true);
    let error = $state<string>('');
    let newKeyName = $state('');
    let createdKey = $state('');
    let showCreatedKey = $state(false);
    let creatingKey = $state(false);
    let fullAccess = $state(true);
    let selectedScopes = $state<Record<string, boolean>>(createEmptyScopeSelection());
    let appsMode = $state<AppsMode>('selected');
    let selectedApps = $state<Record<string, boolean>>({});
    let selectedAppSkills = $state<Record<string, boolean>>({});
    let creditPeriod = $state<CreditPeriod>('unlimited');
    let creditAmount = $state('1000');
    let expirationPreset = $state<ExpirationPreset>('never');
    let showRevokeConfirm = $state(false);
    let revokeConfirmChecked = $state(false);

    let isCreateView = $derived(activeSettingsView === API_KEYS_CREATE_PATH);
    let selectedApiKeyId = $derived.by(() => {
        if (!activeSettingsView.startsWith(`${API_KEYS_ROOT_PATH}/`)) return '';
        if (activeSettingsView === API_KEYS_CREATE_PATH) return '';
        return activeSettingsView.split('/')[2] ?? '';
    });
    let isDetailView = $derived(Boolean(selectedApiKeyId));
    let selectedApiKey = $derived(apiKeys.find((key) => key.id === selectedApiKeyId) ?? null);
    let creditPeriodOptions = $derived([
        { value: 'unlimited', label: $text('settings.api_keys.credit_unlimited') },
        { value: 'daily', label: $text('settings.api_keys.credit_daily') },
        { value: 'weekly', label: $text('settings.api_keys.credit_weekly') },
        { value: 'monthly', label: $text('settings.api_keys.credit_monthly') },
        { value: 'lifetime', label: $text('settings.api_keys.credit_lifetime') },
    ]);

    let expirationOptions = $derived([
        { value: '7d', label: $text('settings.api_keys.expiration_7d') },
        { value: '30d', label: $text('settings.api_keys.expiration_30d') },
        { value: '90d', label: $text('settings.api_keys.expiration_90d') },
        { value: '1y', label: $text('settings.api_keys.expiration_1y') },
        { value: 'never', label: $text('settings.api_keys.expiration_never') },
    ]);

    onMount(() => {
        if (!isCreateView) loadApiKeys();
    });

    async function normalizeApiKey(key: Record<string, unknown>): Promise<ApiKey> {
        let decryptedName = (key.encrypted_name as string) || '';
        let decryptedPrefix = (key.encrypted_key_prefix as string) || '';
        const lastUsed = (key.last_used_at as string) || null;

        try {
            if (key.encrypted_name) {
                const decrypted = await decryptWithMasterKey(key.encrypted_name as string);
                if (decrypted) decryptedName = decrypted;
            }
            if (key.encrypted_key_prefix) {
                const decrypted = await decryptWithMasterKey(key.encrypted_key_prefix as string);
                if (decrypted) decryptedPrefix = decrypted;
            }
        } catch (err) {
            console.error('Error decrypting API key fields:', err);
        }

        return {
            id: key.id as string,
            created_at: (key.created_at as string) || null,
            name: decryptedName,
            key_prefix: decryptedPrefix,
            last_used: lastUsed,
            full_access: (key.full_access as boolean | undefined) ?? true,
            scopes: (key.scopes as Record<string, unknown>) || {},
            credit_limit: (key.credit_limit as ApiKey['credit_limit']) || null,
            pending_device_count: Number(key.pending_device_count || 0),
        } satisfies ApiKey;
    }

    function mergeApiKeys(nextKeys: ApiKey[], preserveExisting = false) {
        if (!preserveExisting) {
            apiKeys = nextKeys;
            return;
        }
        const merged = new Map(apiKeys.map((key) => [key.id, key]));
        for (const key of nextKeys) merged.set(key.id, key);
        apiKeys = Array.from(merged.values()).sort((a, b) => {
            const bTime = b.created_at ? new Date(b.created_at).getTime() : 0;
            const aTime = a.created_at ? new Date(a.created_at).getTime() : 0;
            return bTime - aTime;
        });
    }

    async function loadApiKeys({ preserveExisting = false } = {}) {
        try {
            loading = true;
            error = '';
            // Keep this endpoint aligned with CLI safety gates:
            // frontend/packages/openmates-cli/src/client.ts (BLOCKED_SETTINGS_POST_PATHS)
            const response = await fetch(getApiEndpoint('/v1/settings/api-keys'), {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                credentials: 'include'
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Failed to load API keys');
            }

            const data = await response.json();
            const rawKeys = data.api_keys || [];
            if (!(await getKeyFromStorage())) {
                throw new Error('Master key not found. Please log in again.');
            }

            mergeApiKeys(await Promise.all(rawKeys.map(normalizeApiKey)), preserveExisting);
        } catch (err: unknown) {
            console.error('Error loading API keys:', err);
            error = (err instanceof Error ? err.message : null) || 'Failed to load API keys';
        } finally {
            loading = false;
        }
    }

    function generateApiKey(): string {
        const chars = 'ABCDEFGHIJKLMNPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz123456789';
        let result = 'sk-api-';
        const maxUnbiasedValue = Math.floor(256 / chars.length) * chars.length;
        while (result.length < 'sk-api-'.length + 32) {
            const randomValues = crypto.getRandomValues(new Uint8Array(32));
            for (const value of randomValues) {
                if (value >= maxUnbiasedValue) continue;
                result += chars.charAt(value % chars.length);
                if (result.length >= 'sk-api-'.length + 32) break;
            }
        }
        return result;
    }

    function createEmptyScopeSelection() {
        return Object.fromEntries(FIXED_SCOPES.map((scope) => [scope, false]));
    }

    function buildScopes(): Record<string, unknown> {
        if (fullAccess) return {};

        const scopes: Record<string, unknown> = {
            chat: [], tasks: [], projects: [], plans: [], workflows: [], memories: [], account: [], developer: [],
            apps: {
                mode: appsMode,
                allowed_skills: appsMode === 'selected'
                    ? Object.entries(selectedAppSkills).filter(([, selected]) => selected).map(([skill]) => skill)
                    : [],
                allowed_apps: appsMode === 'selected'
                    ? Object.entries(selectedApps).filter(([, selected]) => selected).map(([app]) => app)
                    : [],
            },
        };
        for (const category of SCOPE_CATEGORIES) {
            const groupScopes = scopes[category.id] as string[];
            for (const scope of category.scopes) {
                if (selectedScopes[scope.id]) groupScopes.push(scope.id);
            }
        }
        return scopes;
    }

    function buildCreditLimit() {
        if (creditPeriod === 'unlimited') return null;
        return { period: creditPeriod, credits: Math.max(1, Math.floor(Number(creditAmount) || 1)) };
    }

    function buildExpiresAt() {
        if (expirationPreset === 'never') return null;
        const daysByPreset = { '7d': 7, '30d': 30, '90d': 90, '1y': 365 } as const;
        const expires = new Date();
        expires.setDate(expires.getDate() + daysByPreset[expirationPreset]);
        return expires.toISOString();
    }

    function resetCreateForm() {
        newKeyName = '';
        createdKey = '';
        showCreatedKey = false;
        fullAccess = true;
        resetLimitedScopes();
        creditPeriod = 'unlimited';
        creditAmount = '1000';
        expirationPreset = 'never';
    }

    function resetLimitedScopes() {
        selectedScopes = createEmptyScopeSelection();
        appsMode = 'selected';
        selectedApps = {};
        selectedAppSkills = {};
    }

    function toggleFullAccess() {
        fullAccess = !fullAccess;
        if (!fullAccess) resetLimitedScopes();
    }

    function toggleScope(scope: string) {
        selectedScopes[scope] = !selectedScopes[scope];
    }

    function toggleApp(appId: string) {
        selectedApps[appId] = !selectedApps[appId];
        if (selectedApps[appId]) {
            for (const skill of APP_SCOPE_OPTIONS.find((app) => app.id === appId)?.skills ?? []) {
                selectedAppSkills[`${appId}:${skill.id}`] = false;
            }
        }
    }

    function toggleAppSkill(appId: string, skillId: string) {
        const key = `${appId}:${skillId}`;
        selectedAppSkills[key] = !selectedAppSkills[key];
    }

    function testIdPart(value: string): string {
        return value.replaceAll('_', '-');
    }

    async function hashApiKey(key: string): Promise<string> {
        const encoder = new TextEncoder();
        const data = encoder.encode(key);
        const hashBuffer = await crypto.subtle.digest('SHA-256', data);
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
    }

    async function createApiKey() {
        if (!newKeyName.trim()) {
            error = $text('settings.api_keys.name_required');
            return;
        }

        try {
            creatingKey = true;
            error = '';

            const masterKey = await getKeyFromStorage();
            if (!masterKey) {
                throw new Error('Master key not found. Please log in again.');
            }

            const apiKey = generateApiKey();
            const apiKeyHash = await hashApiKey(apiKey);
            const keyPrefix = apiKey.substring(0, 12) + '...';
            const encryptedName = await encryptWithMasterKeyDirect(newKeyName.trim(), masterKey);
            const encryptedKeyPrefix = await encryptWithMasterKeyDirect(keyPrefix, masterKey);

            if (!encryptedName || !encryptedKeyPrefix) {
                throw new Error('Failed to encrypt API key data');
            }

            const salt = crypto.getRandomValues(new Uint8Array(16));
            const derivedKey = await deriveKeyFromApiKey(apiKey, salt);
            const { wrapped: encryptedMasterKey, iv: keyIv } = await encryptKey(masterKey, derivedKey);

            const response = await fetch(getApiEndpoint('/v1/settings/api-keys'), {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                credentials: 'include',
                body: JSON.stringify({
                    encrypted_name: encryptedName,
                    api_key_hash: apiKeyHash,
                    encrypted_key_prefix: encryptedKeyPrefix,
                    encrypted_master_key: encryptedMasterKey,
                    salt: uint8ArrayToBase64(salt),
                    key_iv: keyIv,
                    full_access: fullAccess,
                    scopes: buildScopes(),
                    credit_limit: buildCreditLimit(),
                    expires_at: buildExpiresAt(),
                })
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Failed to create API key');
            }

            const createdRecord = await response.json();
            const optimisticKey = await normalizeApiKey(createdRecord);
            mergeApiKeys([optimisticKey], true);
            createdKey = apiKey;
            showCreatedKey = true;
            newKeyName = '';
            await loadApiKeys({ preserveExisting: true });
        } catch (err: unknown) {
            error = (err instanceof Error ? err.message : null) || 'Failed to create API key';
        } finally {
            creatingKey = false;
        }
    }

    async function deleteApiKey(keyId: string) {
        try {
            const response = await fetch(getApiEndpoint(`/v1/settings/api-keys/${keyId}`), {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                credentials: 'include'
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || 'Failed to delete API key');
            }

            showRevokeConfirm = false;
            revokeConfirmChecked = false;
            await loadApiKeys();
            navigateToApiKeys('backward');
        } catch (err: unknown) {
            console.error('Error deleting API key:', err);
            error = (err instanceof Error ? err.message : null) || 'Failed to delete API key';
        }
    }

    function formatDate(dateString: string | null | undefined) {
        if (!dateString) return $text('settings.api_keys.unknown');
        return new Date(dateString).toLocaleDateString();
    }

    function formatDateTime(dateString: string | null | undefined) {
        if (!dateString) return $text('settings.api_keys.unknown');
        return new Date(dateString).toLocaleString();
    }

    function describeCreditLimit(key: ApiKey) {
        if (!key.credit_limit) return $text('settings.api_keys.unlimited_credits');
        return $text('settings.api_keys.credit_limit_summary')
            .replace('{credits}', key.credit_limit.credits.toString())
            .replace('{period}', key.credit_limit.period);
    }

    function describeLastUsed(key: ApiKey) {
        if (!key.last_used) return $text('settings.api_keys.never_used');
        return $text('settings.api_keys.last_used_on').replace('{date}', formatDateTime(key.last_used));
    }

    function describeAccess(key: ApiKey) {
        return key.full_access ? $text('settings.api_keys.full_access') : $text('settings.api_keys.limited_access');
    }

    function navigateToApiKeys(direction = 'forward') {
        dispatch('openSettings', {
            settingsPath: API_KEYS_ROOT_PATH,
            direction,
            icon: 'key',
            title: $text('settings.developers_api_keys')
        });
    }

    function navigateToCreateApiKey() {
        if (apiKeys.length >= MAX_API_KEYS) return;
        resetCreateForm();
        dispatch('openSettings', {
            settingsPath: API_KEYS_CREATE_PATH,
            direction: 'forward',
            icon: 'key',
            title: $text('settings.api_keys.create_title')
        });
    }

    function navigateToApiKeyDetails(key: ApiKey) {
        showRevokeConfirm = false;
        revokeConfirmChecked = false;
        dispatch('openSettings', {
            settingsPath: `${API_KEYS_ROOT_PATH}/${key.id}`,
            direction: 'forward',
            icon: 'key',
            title: key.name || $text('settings.api_keys.detail_title')
        });
    }

    function navigateToDevices() {
        dispatch('openSettings', {
            settingsPath: 'developers/devices',
            direction: 'forward',
            icon: 'devices',
            title: $text('common.devices')
        });
    }
</script>

{#if isCreateView}
    <SettingsPageContainer maxWidth="wide">
        {#if error}
            <SettingsInfoBox type="error">{error}</SettingsInfoBox>
        {/if}

        {#if showCreatedKey}
            <SettingsInfoBox type="warning">
                <p>{$text('settings.api_keys.created_warning')}</p>
            </SettingsInfoBox>
            <SettingsCodeBlock code={createdKey} copyable dataTestid="api-key-created-value" />
            <SettingsButtonGroup align="right">
                <SettingsButton dataTestid="api-key-done-button" onClick={() => navigateToApiKeys('backward')}>
                    {$text('settings.api_keys.copied_done')}
                </SettingsButton>
            </SettingsButtonGroup>
        {:else}
            <SettingsInfoBox type="info">
                <p>{$text('settings.api_keys.create_description')}</p>
            </SettingsInfoBox>

            <SettingsSectionHeading title={$text('settings.api_keys.name_section')} icon="key" />
            <SettingsInput
                type="text"
                placeholder={$text('settings.api_keys.name_placeholder')}
                bind:value={newKeyName}
                maxlength={100}
                dataTestid="api-key-name-input"
            />

            <SettingsSectionHeading title={$text('settings.api_keys.access_section')} icon="privacy" />
            <SettingsItem
                type="subsubmenu"
                icon="subsetting_icon key"
                title={$text('settings.api_keys.full_access')}
                subtitleTop={$text('settings.api_keys.full_access_description')}
                hasToggle={true}
                checked={fullAccess}
                data-testid="api-key-full-access"
                onClick={toggleFullAccess}
            />
            {#if fullAccess}
                <SettingsInfoBox type="warning" ariaLabel={$text('settings.api_keys.full_access_warning_title')}>
                    <p>{$text('settings.api_keys.full_access_warning')}</p>
                </SettingsInfoBox>
            {:else}
                {#each SCOPE_CATEGORIES as category}
                    <SettingsSectionHeading title={$text(category.labelKey)} icon={category.icon} />
                    <SettingsCard padding="sm" ariaLabel={$text(category.labelKey)}>
                        {#each category.scopes as scope}
                            <SettingsItem
                                type="subsubmenu"
                                title={$text(scope.labelKey)}
                                subtitleTop={scope.id}
                                hasToggle={true}
                                checked={selectedScopes[scope.id]}
                                data-testid={`api-key-scope-${scope.id.replaceAll(':', '-').replaceAll('_', '-')}`}
                                onClick={() => toggleScope(scope.id)}
                            />
                        {/each}
                    </SettingsCard>
                {/each}
                <SettingsSectionHeading title={$text('settings.api_keys.category_app_skills')} icon="skill" />
                <SettingsCard padding="sm" ariaLabel={$text('settings.api_keys.category_app_skills')}>
                    <SettingsItem
                        type="subsubmenu"
                        title={$text('settings.api_keys.apps_all')}
                        subtitleTop={$text('settings.api_keys.apps_access')}
                        hasToggle={true}
                        checked={appsMode === 'all'}
                        data-testid="api-key-all-app-skills"
                        onClick={() => appsMode = appsMode === 'all' ? 'selected' : 'all'}
                    />
                </SettingsCard>
                {#if appsMode === 'selected'}
                    {#each APP_SCOPE_OPTIONS as app}
                        <SettingsSectionHeading
                            title={app.name_translation_key ? $text(app.name_translation_key) : (app.name ?? app.id)}
                            icon="apps"
                        />
                        <SettingsCard
                            padding="sm"
                            ariaLabel={app.name_translation_key ? $text(app.name_translation_key) : (app.name ?? app.id)}
                        >
                            <SettingsItem
                                type="subsubmenu"
                                title={$text('settings.api_keys.apps_all')}
                                subtitleTop={app.id}
                                hasToggle={true}
                                checked={selectedApps[app.id] ?? false}
                                data-testid={`api-key-app-${testIdPart(app.id)}-all-skills`}
                                onClick={() => toggleApp(app.id)}
                            />
                            {#if !selectedApps[app.id]}
                                {#each app.skills as skill}
                                    <SettingsItem
                                        type="subsubmenu"
                                        title={$text(skill.name_translation_key)}
                                        subtitleTop={`${app.id}:${skill.id}`}
                                        hasToggle={true}
                                        checked={selectedAppSkills[`${app.id}:${skill.id}`] ?? false}
                                        data-testid={`api-key-app-${testIdPart(app.id)}-skill-${testIdPart(skill.id)}`}
                                        onClick={() => toggleAppSkill(app.id, skill.id)}
                                    />
                                {/each}
                            {/if}
                        </SettingsCard>
                    {/each}
                {/if}
            {/if}

            <SettingsSectionHeading title={$text('settings.api_keys.limits_section')} icon="coins" />
            <SettingsDropdown
                value={creditPeriod}
                options={creditPeriodOptions}
                ariaLabel={$text('settings.api_keys.credit_limit')}
                dataTestid="api-key-credit-period-select"
                onChange={(value) => creditPeriod = value as CreditPeriod}
            />
            {#if creditPeriod === 'unlimited'}
                <SettingsInfoBox type="warning" ariaLabel={$text('settings.api_keys.credit_unlimited_warning_title')}>
                    <p>{$text('settings.api_keys.credit_unlimited_warning')}</p>
                </SettingsInfoBox>
            {:else}
                <SettingsInput
                    type="number"
                    placeholder={$text('settings.api_keys.credit_amount_placeholder')}
                    bind:value={creditAmount}
                    min="1"
                    dataTestid="api-key-credit-amount-input"
                />
            {/if}

            <SettingsDropdown
                value={expirationPreset}
                options={expirationOptions}
                ariaLabel={$text('settings.api_keys.expiration')}
                dataTestid="api-key-expiration-select"
                onChange={(value) => expirationPreset = value as ExpirationPreset}
            />
            {#if expirationPreset === 'never'}
                <SettingsInfoBox type="warning" ariaLabel={$text('settings.api_keys.expiration_never_warning_title')}>
                    <p>{$text('settings.api_keys.expiration_never_warning')}</p>
                </SettingsInfoBox>
            {/if}

            <SettingsButtonGroup align="space-between">
                <SettingsButton variant="secondary" dataTestid="api-key-cancel-button" onClick={() => navigateToApiKeys('backward')} disabled={creatingKey}>
                    {$text('common.cancel')}
                </SettingsButton>
                <SettingsButton
                    dataTestid="api-key-create-confirm"
                    onClick={createApiKey}
                    disabled={!newKeyName.trim()}
                    loading={creatingKey}
                >
                    {creatingKey ? $text('settings.api_keys.creating') : $text('settings.api_keys.create_title')}
                </SettingsButton>
            </SettingsButtonGroup>
        {/if}
    </SettingsPageContainer>
{:else if isDetailView}
    <SettingsPageContainer maxWidth="wide">
        {#if error}
            <SettingsInfoBox type="error">{error}</SettingsInfoBox>
        {/if}

        {#if loading}
            <SettingsLoadingState text={$text('settings.api_keys.loading')} />
        {:else if !selectedApiKey}
            <SettingsLoadingState
                variant="empty"
                text={$text('settings.api_keys.not_found')}
                hint={$text('settings.api_keys.not_found_hint')}
            />
        {:else}
            <SettingsSectionHeading title={selectedApiKey.name} icon="key" />
            <SettingsCard>
                <SettingsDetailRow label={$text('settings.api_keys.prefix')} value={selectedApiKey.key_prefix} />
                <SettingsDetailRow label={$text('settings.api_keys.created')} value={formatDate(selectedApiKey.created_at)} />
                <SettingsDetailRow label={$text('settings.api_keys.last_used')} value={describeLastUsed(selectedApiKey)} />
                <SettingsDetailRow label={$text('settings.api_keys.access')} value={describeAccess(selectedApiKey)} />
                <SettingsDetailRow label={$text('settings.api_keys.credit_limit')} value={describeCreditLimit(selectedApiKey)} />
            </SettingsCard>

            <SettingsInfoBox type="info">
                <p>{$text('settings.api_keys.detail_secret_note')}</p>
            </SettingsInfoBox>

            {#if showRevokeConfirm}
                <SettingsConfirmBlock
                    warningText={$text('settings.api_keys.revoke_warning')}
                    confirmLabel={$text('settings.api_keys.revoke_confirm_label')}
                    bind:checked={revokeConfirmChecked}
                />
                <SettingsButtonGroup align="space-between">
                    <SettingsButton
                        variant="secondary"
                        dataTestid="api-key-revoke-cancel-button"
                        onClick={() => {
                            showRevokeConfirm = false;
                            revokeConfirmChecked = false;
                        }}
                    >
                        {$text('common.cancel')}
                    </SettingsButton>
                    <SettingsButton
                        variant="danger"
                        dataTestid="api-key-delete-button"
                        disabled={!revokeConfirmChecked}
                        onClick={() => deleteApiKey(selectedApiKey.id)}
                    >
                        {$text('settings.api_keys.revoke_key')}
                    </SettingsButton>
                </SettingsButtonGroup>
            {:else}
                <SettingsButtonGroup align="right">
                    <SettingsButton variant="danger" dataTestid="api-key-delete-button" onClick={() => showRevokeConfirm = true}>
                        {$text('settings.api_keys.revoke_key')}
                    </SettingsButton>
                </SettingsButtonGroup>
            {/if}
        {/if}
    </SettingsPageContainer>
{:else}
    <SettingsPageContainer maxWidth="wide">
        <SettingsInfoBox type="info">
            <p>{$text('settings.developers_api_keys_description')}</p>
        </SettingsInfoBox>

        {#if error}
            <SettingsInfoBox type="error">{error}</SettingsInfoBox>
        {/if}

        <SettingsButtonGroup align="right">
            <SettingsButton
                dataTestid="api-key-create-button"
                onClick={navigateToCreateApiKey}
                disabled={apiKeys.length >= MAX_API_KEYS}
            >
                {$text('settings.api_keys.create_title')}
            </SettingsButton>
        </SettingsButtonGroup>

        {#if loading}
            <SettingsLoadingState text={$text('settings.api_keys.loading')} />
        {:else if apiKeys.length === 0}
            <SettingsLoadingState
                variant="empty"
                text={$text('settings.api_keys.empty_title')}
                hint={$text('settings.api_keys.empty_hint')}
            />
        {:else}
            {#each apiKeys as key (key.id)}
                <SettingsItem
                    type="subsubmenu"
                    icon="subsetting_icon key"
                    title={key.name}
                    subtitleTop={`${key.key_prefix} · ${describeLastUsed(key)} · ${describeAccess(key)} · ${describeCreditLimit(key)}`}
                    data-testid="api-key-item"
                    onClick={() => navigateToApiKeyDetails(key)}
                />
                {#if (key.pending_device_count || 0) > 0}
                    <SettingsButton
                        variant="secondary"
                        dataTestid="api-key-confirm-device-link"
                        onClick={navigateToDevices}
                    >
                        {$text('settings.api_keys.confirm_device')}
                    </SettingsButton>
                {/if}
            {/each}
        {/if}

        {#if apiKeys.length >= MAX_API_KEYS}
            <SettingsInfoBox type="warning" ariaLabel={$text('settings.api_keys.limit_warning_title')}>
                <p>{$text('settings.api_keys.limit_warning').replace('{max}', MAX_API_KEYS.toString())}</p>
            </SettingsInfoBox>
        {/if}
    </SettingsPageContainer>
{/if}
