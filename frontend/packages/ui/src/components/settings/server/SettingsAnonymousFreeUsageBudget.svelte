<!--
    SettingsAnonymousFreeUsageBudget — Admin-only anonymous free usage budget.

    Lets official-cloud admins configure the shared logged-out trial budget,
    derived daily/weekly caps, and per-identity abuse cap. Public clients only
    receive safe active/reset metadata; exact counters stay on this admin page.
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { getApiEndpoint, text } from '@repo/ui';
    import {
        SettingsButton,
        SettingsCard,
        SettingsDetailRow,
        SettingsInfoBox,
        SettingsInput,
        SettingsPageContainer,
        SettingsSectionHeading,
    } from '../../settings/elements';
    import { notificationStore } from '../../../stores/notificationStore';
    import { initializeServerStatus } from '../../../stores/serverStatusStore';

    type BudgetStatus = {
        enabled: boolean;
        monthly_budget_credits: number;
        daily_hard_cap_percent: number;
        daily_hard_cap_credits: number;
        weekly_cap_percent: number;
        weekly_cap_credits: number;
        per_identity_daily_cap_credits: number;
        daily_used_credits: number;
        weekly_used_credits: number;
        monthly_remaining_credits: number;
        daily_remaining_credits: number;
        weekly_remaining_credits: number;
        active: boolean;
        reason: string | null;
        reset_at: string;
        updated_at: string | null;
    };

    let isLoading = $state(true);
    let isSaving = $state(false);
    let loadError = $state('');
    let saveError = $state('');
    let budget = $state<BudgetStatus | null>(null);

    let monthlyBudgetCredits = $state('0');
    let dailyHardCapPercent = $state('5');
    let weeklyCapPercent = $state('25');
    let perIdentityDailyCapCredits = $state('400');

    let monthlyCredits = $derived(parseCredits(monthlyBudgetCredits));
    let dailyPercent = $derived(parseCredits(dailyHardCapPercent));
    let weeklyPercent = $derived(parseCredits(weeklyCapPercent));
    let perIdentityDailyCap = $derived(parseCredits(perIdentityDailyCapCredits));
    let derivedDailyCapCredits = $derived(Math.floor(monthlyCredits * dailyPercent / 100));
    let derivedWeeklyCapCredits = $derived(Math.floor(monthlyCredits * weeklyPercent / 100));
    let isFormValid = $derived(
        monthlyCredits >= 0 &&
        dailyPercent >= 0 && dailyPercent <= 100 &&
        weeklyPercent >= 0 && weeklyPercent <= 100 &&
        perIdentityDailyCap >= 0 &&
        (monthlyCredits === 0 || perIdentityDailyCap >= 1)
    );
    let activatesOnSave = $derived(monthlyCredits > 0 && dailyPercent > 0 && weeklyPercent > 0 && perIdentityDailyCap >= 1);

    onMount(() => {
        fetchBudget();
    });

    function parseCredits(value: string): number {
        const parsed = Number.parseInt(value, 10);
        return Number.isFinite(parsed) ? parsed : 0;
    }

    function formatCredits(value: number): string {
        return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
    }

    function formatDate(value: string | null): string {
        if (!value) return $text('settings.server.anonymous_free_usage_budget.never');
        try {
            return new Date(value).toLocaleString();
        } catch {
            return value;
        }
    }

    function applyBudget(status: BudgetStatus) {
        budget = status;
        monthlyBudgetCredits = String(status.monthly_budget_credits);
        dailyHardCapPercent = String(status.daily_hard_cap_percent);
        weeklyCapPercent = String(status.weekly_cap_percent);
        perIdentityDailyCapCredits = String(status.per_identity_daily_cap_credits);
    }

    async function fetchBudget() {
        isLoading = true;
        loadError = '';
        try {
            const response = await fetch(getApiEndpoint('/v1/admin/anonymous-free-usage-budget'), {
                method: 'GET',
                credentials: 'include',
                cache: 'no-store',
            });
            if (!response.ok) {
                const data = await response.json().catch(() => null);
                throw new Error(data?.detail || `HTTP ${response.status}`);
            }
            applyBudget(await response.json());
        } catch (error) {
            loadError = error instanceof Error ? error.message : $text('settings.server.anonymous_free_usage_budget.load_error');
        } finally {
            isLoading = false;
        }
    }

    async function saveBudget() {
        if (!isFormValid || isSaving) return;
        isSaving = true;
        saveError = '';
        try {
            const response = await fetch(getApiEndpoint('/v1/admin/anonymous-free-usage-budget'), {
                method: 'PUT',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    enabled: activatesOnSave,
                    monthly_budget_credits: monthlyCredits,
                    daily_hard_cap_percent: dailyPercent,
                    weekly_cap_percent: weeklyPercent,
                    per_identity_daily_cap_credits: perIdentityDailyCap,
                }),
            });
            if (!response.ok) {
                const data = await response.json().catch(() => null);
                throw new Error(data?.detail || `HTTP ${response.status}`);
            }
            applyBudget(await response.json());
            await initializeServerStatus(true);
            notificationStore.success($text('settings.server.anonymous_free_usage_budget.save_success'));
        } catch (error) {
            saveError = error instanceof Error ? error.message : $text('settings.server.anonymous_free_usage_budget.save_error');
            notificationStore.error(saveError);
        } finally {
            isSaving = false;
        }
    }
</script>

<SettingsPageContainer maxWidth="default">
<div data-testid="anonymous-free-usage-budget-settings">
    <SettingsSectionHeading title={$text('settings.server.anonymous_free_usage_budget.title')} icon="ai" />

    {#if isLoading}
        <SettingsInfoBox type="info">
            <p>{$text('settings.server.anonymous_free_usage_budget.loading')}</p>
        </SettingsInfoBox>
    {:else if loadError}
        <SettingsInfoBox type="error">
            <p>{loadError}</p>
        </SettingsInfoBox>
        <SettingsButton variant="secondary" onClick={fetchBudget} dataTestid="anonymous-free-usage-budget-retry-button">
            {$text('common.retry')}
        </SettingsButton>
    {:else}
        <SettingsInfoBox type={budget?.active ? 'success' : 'info'}>
            <p>
                {#if budget?.active}
                    {$text('settings.server.anonymous_free_usage_budget.status_active')}
                {:else if budget?.reason === 'daily_exhausted'}
                    {$text('settings.server.anonymous_free_usage_budget.status_daily_exhausted')}
                {:else if budget?.reason === 'weekly_exhausted'}
                    {$text('settings.server.anonymous_free_usage_budget.status_weekly_exhausted')}
                {:else}
                    {$text('settings.server.anonymous_free_usage_budget.status_disabled')}
                {/if}
            </p>
        </SettingsInfoBox>

        <SettingsCard>
            <SettingsDetailRow label={$text('settings.server.anonymous_free_usage_budget.daily_cap')} value={formatCredits(budget?.daily_hard_cap_credits ?? derivedDailyCapCredits)} />
            <SettingsDetailRow label={$text('settings.server.anonymous_free_usage_budget.weekly_cap')} value={formatCredits(budget?.weekly_cap_credits ?? derivedWeeklyCapCredits)} />
            <SettingsDetailRow label={$text('settings.server.anonymous_free_usage_budget.daily_used')} value={formatCredits(budget?.daily_used_credits ?? 0)} />
            <SettingsDetailRow label={$text('settings.server.anonymous_free_usage_budget.weekly_used')} value={formatCredits(budget?.weekly_used_credits ?? 0)} />
            <SettingsDetailRow label={$text('settings.server.anonymous_free_usage_budget.daily_remaining')} value={formatCredits(budget?.daily_remaining_credits ?? 0)} highlight={(budget?.daily_remaining_credits ?? 0) > 0} />
            <SettingsDetailRow label={$text('settings.server.anonymous_free_usage_budget.weekly_remaining')} value={formatCredits(budget?.weekly_remaining_credits ?? 0)} highlight={(budget?.weekly_remaining_credits ?? 0) > 0} />
            <SettingsDetailRow label={$text('settings.server.anonymous_free_usage_budget.reset_at')} value={formatDate(budget?.reset_at ?? null)} muted />
            <SettingsDetailRow label={$text('settings.server.anonymous_free_usage_budget.updated_at')} value={formatDate(budget?.updated_at ?? null)} muted />
        </SettingsCard>

        <SettingsSectionHeading title={$text('settings.server.anonymous_free_usage_budget.monthly_budget')} icon="gift_cards" />
        <SettingsInput
            bind:value={monthlyBudgetCredits}
            type="number"
            inputmode="numeric"
            min="0"
            hasError={monthlyCredits < 0}
            dataTestid="anonymous-free-usage-monthly-budget-input"
        />

        <SettingsSectionHeading title={$text('settings.server.anonymous_free_usage_budget.daily_percent')} icon="usage" />
        <SettingsInput
            bind:value={dailyHardCapPercent}
            type="number"
            inputmode="numeric"
            min="0"
            max="100"
            hasError={dailyPercent < 0 || dailyPercent > 100}
            dataTestid="anonymous-free-usage-daily-percent-input"
        />

        <SettingsSectionHeading title={$text('settings.server.anonymous_free_usage_budget.weekly_percent')} icon="usage" />
        <SettingsInput
            bind:value={weeklyCapPercent}
            type="number"
            inputmode="numeric"
            min="0"
            max="100"
            hasError={weeklyPercent < 0 || weeklyPercent > 100}
            dataTestid="anonymous-free-usage-weekly-percent-input"
        />

        <SettingsSectionHeading title={$text('settings.server.anonymous_free_usage_budget.per_identity_cap')} icon="security" />
        <SettingsInput
            bind:value={perIdentityDailyCapCredits}
            type="number"
            inputmode="numeric"
            min={monthlyCredits > 0 ? '1' : '0'}
            hasError={perIdentityDailyCap < 0 || (monthlyCredits > 0 && perIdentityDailyCap < 1)}
            dataTestid="anonymous-free-usage-per-identity-cap-input"
        />

        <SettingsCard>
            <SettingsDetailRow label={$text('settings.server.anonymous_free_usage_budget.monthly_remaining')} value={formatCredits(budget?.monthly_remaining_credits ?? Math.max(0, monthlyCredits))} highlight={(budget?.monthly_remaining_credits ?? monthlyCredits) > 0} />
            <SettingsDetailRow label={$text('settings.server.anonymous_free_usage_budget.derived_daily_cap')} value={formatCredits(derivedDailyCapCredits)} />
            <SettingsDetailRow label={$text('settings.server.anonymous_free_usage_budget.derived_weekly_cap')} value={formatCredits(derivedWeeklyCapCredits)} />
        </SettingsCard>

        {#if dailyPercent < 0 || dailyPercent > 100 || weeklyPercent < 0 || weeklyPercent > 100}
            <SettingsInfoBox type="error">
                <p>{$text('settings.server.anonymous_free_usage_budget.validation_percent')}</p>
            </SettingsInfoBox>
        {/if}

        {#if monthlyCredits > 0 && perIdentityDailyCap < 1}
            <SettingsInfoBox type="error">
                <p>{$text('settings.server.anonymous_free_usage_budget.validation_per_identity_cap')}</p>
            </SettingsInfoBox>
        {/if}

        {#if saveError}
            <SettingsInfoBox type="error">
                <p>{saveError}</p>
            </SettingsInfoBox>
        {/if}

        <SettingsButton
            fullWidth
            disabled={!isFormValid}
            loading={isSaving}
            onClick={saveBudget}
            dataTestid="anonymous-free-usage-budget-save-button"
        >
            {$text('common.save')}
        </SettingsButton>
    {/if}
</div>
</SettingsPageContainer>
