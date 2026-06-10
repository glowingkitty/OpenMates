<!--
    SettingsFreeTestingCreditsBudget — Admin-only Free testing credits budget.

    Lets server admins enable a finite promotional signup credit budget, inspect
    used/remaining credits, and configure the full per-user grant amount. The
    public signup UI only receives safe active/grant metadata from server-status;
    exact budget totals stay on this admin page.
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { getApiEndpoint, text } from '@repo/ui';
    import {
        SettingsButton,
        SettingsCard,
        SettingsConsentToggle,
        SettingsDetailRow,
        SettingsInfoBox,
        SettingsInput,
        SettingsSectionHeading,
    } from '../../settings/elements';
    import { notificationStore } from '../../../stores/notificationStore';

    type BudgetStatus = {
        enabled: boolean;
        total_budget_credits: number;
        used_budget_credits: number;
        remaining_budget_credits: number;
        per_user_grant_credits: number;
        active: boolean;
        exhausted: boolean;
        exhausted_email_sent_at: string | null;
        updated_at: string | null;
    };

    let isLoading = $state(true);
    let isSaving = $state(false);
    let loadError = $state('');
    let saveError = $state('');
    let budget = $state<BudgetStatus | null>(null);

    let enabled = $state(false);
    let totalBudgetCredits = $state('0');
    let perUserGrantCredits = $state('1000');

    let usedBudgetCredits = $derived(budget?.used_budget_credits ?? 0);
    let remainingBudgetCredits = $derived(Math.max(0, parseCredits(totalBudgetCredits) - usedBudgetCredits));
    let canGrantFullUser = $derived(!enabled || remainingBudgetCredits >= parseCredits(perUserGrantCredits));
    let isFormValid = $derived(
        parseCredits(totalBudgetCredits) >= 0 &&
        parseCredits(perUserGrantCredits) >= 0 &&
        (!enabled || parseCredits(perUserGrantCredits) >= 1) &&
        parseCredits(totalBudgetCredits) >= usedBudgetCredits &&
        canGrantFullUser
    );

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
        if (!value) return $text('settings.server.free_testing_budget.never');
        try {
            return new Date(value).toLocaleString();
        } catch {
            return value;
        }
    }

    function applyBudget(status: BudgetStatus) {
        budget = status;
        enabled = status.enabled;
        totalBudgetCredits = String(status.total_budget_credits);
        perUserGrantCredits = String(status.per_user_grant_credits);
    }

    async function fetchBudget() {
        isLoading = true;
        loadError = '';
        try {
            const response = await fetch(getApiEndpoint('/v1/admin/free-testing-credits-budget'), {
                method: 'GET',
                credentials: 'include',
            });
            if (!response.ok) {
                const data = await response.json().catch(() => null);
                throw new Error(data?.detail || `HTTP ${response.status}`);
            }
            applyBudget(await response.json());
        } catch (error) {
            loadError = error instanceof Error ? error.message : $text('settings.server.free_testing_budget.load_error');
        } finally {
            isLoading = false;
        }
    }

    async function saveBudget() {
        if (!isFormValid || isSaving) return;
        isSaving = true;
        saveError = '';
        try {
            const response = await fetch(getApiEndpoint('/v1/admin/free-testing-credits-budget'), {
                method: 'PUT',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    enabled,
                    total_budget_credits: parseCredits(totalBudgetCredits),
                    per_user_grant_credits: parseCredits(perUserGrantCredits),
                }),
            });
            if (!response.ok) {
                const data = await response.json().catch(() => null);
                throw new Error(data?.detail || `HTTP ${response.status}`);
            }
            applyBudget(await response.json());
            notificationStore.success($text('settings.server.free_testing_budget.save_success'));
        } catch (error) {
            saveError = error instanceof Error ? error.message : $text('settings.server.free_testing_budget.save_error');
            notificationStore.error(saveError);
        } finally {
            isSaving = false;
        }
    }
</script>

<div class="free-testing-budget-settings" data-testid="free-testing-budget-settings">
    <SettingsSectionHeading title={$text('settings.server.free_testing_budget.title')} icon="gift_cards" />

    {#if isLoading}
        <SettingsInfoBox type="info">
            <p>{$text('settings.server.free_testing_budget.loading')}</p>
        </SettingsInfoBox>
    {:else if loadError}
        <SettingsInfoBox type="error">
            <p>{loadError}</p>
        </SettingsInfoBox>
        <SettingsButton variant="secondary" onClick={fetchBudget}>
            {$text('common.retry')}
        </SettingsButton>
    {:else}
        <SettingsInfoBox type={budget?.active ? 'success' : budget?.exhausted ? 'warning' : 'info'}>
            <p>
                {#if budget?.active}
                    {$text('settings.server.free_testing_budget.status_active')}
                {:else if budget?.exhausted}
                    {$text('settings.server.free_testing_budget.status_exhausted')}
                {:else}
                    {$text('settings.server.free_testing_budget.status_disabled')}
                {/if}
            </p>
        </SettingsInfoBox>

        <SettingsCard>
            <SettingsDetailRow label={$text('settings.server.free_testing_budget.used')} value={formatCredits(usedBudgetCredits)} />
            <SettingsDetailRow label={$text('settings.server.free_testing_budget.remaining')} value={formatCredits(remainingBudgetCredits)} highlight={remainingBudgetCredits > 0} />
            <SettingsDetailRow label={$text('settings.server.free_testing_budget.exhausted_email_sent')} value={formatDate(budget?.exhausted_email_sent_at ?? null)} />
            <SettingsDetailRow label={$text('settings.server.free_testing_budget.updated_at')} value={formatDate(budget?.updated_at ?? null)} muted />
        </SettingsCard>

        <SettingsConsentToggle
            bind:checked={enabled}
            consentText={$text('settings.server.free_testing_budget.enabled')}
            ariaLabel={$text('settings.server.free_testing_budget.enabled')}
        />

        <SettingsSectionHeading title={$text('settings.server.free_testing_budget.total_budget')} icon="gift_cards" />
        <SettingsInput
            bind:value={totalBudgetCredits}
            type="number"
            inputmode="numeric"
            min="0"
            hasError={parseCredits(totalBudgetCredits) < usedBudgetCredits}
            dataTestid="free-testing-total-budget-input"
        />

        <SettingsSectionHeading title={$text('settings.server.free_testing_budget.per_user_grant')} icon="gift_cards" />
        <SettingsInput
            bind:value={perUserGrantCredits}
            type="number"
            inputmode="numeric"
            min="0"
            hasError={enabled && (parseCredits(perUserGrantCredits) < 1 || !canGrantFullUser)}
            dataTestid="free-testing-per-user-grant-input"
        />

        {#if parseCredits(totalBudgetCredits) < usedBudgetCredits}
            <SettingsInfoBox type="error">
                <p>{$text('settings.server.free_testing_budget.validation_below_used')}</p>
            </SettingsInfoBox>
        {:else if enabled && !canGrantFullUser}
            <SettingsInfoBox type="warning">
                <p>{$text('settings.server.free_testing_budget.validation_no_partial')}</p>
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
            dataTestid="free-testing-budget-save-button"
        >
            {$text('common.save')}
        </SettingsButton>
    {/if}
</div>

<style>
    .free-testing-budget-settings {
        display: flex;
        flex-direction: column;
        gap: 1rem;
    }
</style>
