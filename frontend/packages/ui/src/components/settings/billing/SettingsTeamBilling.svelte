<script lang="ts">
  import { createEventDispatcher, onMount } from "svelte";
  import { text } from "@repo/ui";
  import {
    SettingsButton,
    SettingsButtonGroup,
    SettingsInfoBox,
    SettingsDropdown,
    SettingsItem,
    SettingsPageContainer,
    SettingsPageHeader,
  } from "../elements";
  import SettingsMenuItem from "../../SettingsItem.svelte";
  import TeamSettingsHeader from "../TeamSettingsHeader.svelte";
  import {
    listTeams,
    loadTeamBilling,
    type TeamViewModel,
  } from "../../../services/teamService";
  import {
    billingPath,
    type BillingContext,
  } from "../../../services/billingContext";
  import { getEmailDecryptedWithMasterKey } from "../../../services/cryptoService";
  import { pricingTiers } from "../../../config/pricing";
  import SettingsBillingAddress from "./SettingsBillingAddress.svelte";
  import SettingsBuyCredits from "./SettingsBuyCredits.svelte";
  import SettingsBuyCreditsPayment from "./SettingsBuyCreditsPayment.svelte";
  import SettingsInvoices from "./SettingsInvoices.svelte";
  import SettingsTeamMonthlyAutoTopup from "./SettingsTeamMonthlyAutoTopup.svelte";
  import SettingsTeamUsage from "./SettingsTeamUsage.svelte";

  let {
    teamId,
    activeSettingsView = "",
    preview = false,
    previewBalance = 0,
    previewRole = "owner",
    previewTeam,
  }: {
    teamId: string;
    activeSettingsView?: string;
    preview?: boolean;
    previewBalance?: number;
    previewRole?: string;
    previewTeam?: TeamViewModel;
  } = $props();
  const dispatch = createEventDispatcher();
  let context: BillingContext = $derived({ kind: "team", teamId });
  let routePrefix = $derived(`teams/${teamId}/billing`);
  let section = $derived(
    activeSettingsView.startsWith(`${routePrefix}/`)
      ? activeSettingsView.slice(routePrefix.length + 1)
      : "",
  );
  let balance = $state(0);
  let role = $state("member");
  let loading = $state(true);
  let error = $state("");
  let usageEntries: Array<{
    event_id: string;
    created_at: string | number;
    workspace_type: string;
    credit_amount: number;
    actor_user_hash?: string | null;
    object_id_hash?: string | null;
  }> | null = $state(null);
  let autoEnabled = $state(false);
  let autoReady = $state(false);
  let autoAmount = $state("");
  let autoCurrency = $state("EUR");
  let autoPaymentMethodId = $state("");
  let paymentMethods: Array<{
    id: string;
    card?: { brand?: string; last4?: string };
  }> = $state([]);
  let autoSaving = $state(false);
  let autoSaved = $state(false);
  let autoError = $state("");
  let downloadsExpanded = $state(false);
  let generation = 0;
  let canManage = $derived(role === "owner" || role === "admin");

  $effect(() => {
    if (!teamId || preview) return;
    const token = ++generation;
    loading = true;
    error = "";
    void (async () => {
      try {
        const teams = await listTeams();
        const team = teams.find((entry) => entry.team_id === teamId);
        if (!team) throw new Error("Team not available");
        if (token !== generation) return;
        role = team.role;
        if (role !== "owner" && role !== "admin") return;
        const billing = await loadTeamBilling(team);
        if (token !== generation) return;
        balance = billing.balanceCredits;
        {
          const [autoResponse, usageResponse, methodsResponse] =
            await Promise.all([
              fetch(billingPath(context, "autoTopup"), {
                credentials: "include",
              }),
              fetch(billingPath(context, "usage"), { credentials: "include" }),
              fetch(billingPath(context, "methods"), {
                credentials: "include",
              }),
            ]);
          if (token !== generation) return;
          if (autoResponse.ok) {
            const auto = await autoResponse.json();
            autoEnabled = !!auto.enabled;
            autoAmount = String(auto.amount ?? "");
            autoCurrency = String(auto.currency ?? "EUR").toUpperCase();
            autoPaymentMethodId = auto.payment_method_id ?? "";
          } else autoError = $text("settings.billing.team_billing_unavailable");
          if (usageResponse.ok) {
            const data = await usageResponse.json();
            usageEntries = Array.isArray(data.usage) ? data.usage : [];
          } else error = $text("settings.billing.team_usage_error");
          if (methodsResponse.ok) {
            const methods = await methodsResponse.json();
            paymentMethods = Array.isArray(methods.payment_methods)
              ? methods.payment_methods
              : [];
          } else autoError = $text("settings.billing.team_billing_unavailable");
          autoReady = autoResponse.ok && methodsResponse.ok;
        }
      } catch {
        if (token === generation)
          error = $text("settings.billing.team_billing_unavailable");
      } finally {
        if (token === generation) loading = false;
      }
    })();
  });

  onMount(() => {
    if (preview) {
      role = previewRole;
      balance = previewBalance;
      usageEntries = [
        {
          event_id: "preview-1",
          created_at: Date.now() / 1000,
          workspace_type: "chat",
          credit_amount: 12,
          actor_user_hash: "01234567abcdef",
          object_id_hash: "fedcba9876543210",
        },
        {
          event_id: "preview-2",
          created_at: Date.now() / 1000,
          workspace_type: "apps",
          credit_amount: 8,
          actor_user_hash: "01234567abcdef",
          object_id_hash: "aabbccdd98765432",
        },
        {
          event_id: "preview-3",
          created_at: Date.now() / 1000,
          workspace_type: "workflow",
          credit_amount: 5,
          actor_user_hash: "76543210abcdef",
          object_id_hash: "11223344aabbccdd",
        },
      ];
      loading = false;
      autoReady = true;
    }
    return () => {
      generation++;
    };
  });

  function navigate(path: string, title: string, icon: string): void {
    dispatch("openSettings", {
      settingsPath: path ? `${routePrefix}/${path}` : routePrefix,
      direction: "forward",
      icon,
      title,
    });
  }

  function changeAutoCurrency(value: string): void {
    autoCurrency = value;
    if (
      !pricingTiers.some(
        (tier) =>
          String(tier.credits) === autoAmount &&
          tier.price[value.toLowerCase() as "eur" | "usd"] !== undefined,
      )
    ) {
      autoAmount = "";
    }
  }

  async function saveAutoTopup(): Promise<void> {
    autoError = "";
    autoSaved = false;
    const amount = Number(autoAmount);
    if (
      autoEnabled &&
      (!Number.isSafeInteger(amount) ||
        amount <= 0 ||
        !autoPaymentMethodId.trim())
    ) {
      autoError = $text("settings.billing.team_auto_topup_error");
      return;
    }
    if (preview) {
      autoSaved = true;
      return;
    }
    autoSaving = true;
    const token = generation;
    try {
      const email = autoEnabled ? await getEmailDecryptedWithMasterKey() : null;
      if (autoEnabled && !email) throw new Error("Account email unavailable");
      const response = await fetch(billingPath(context, "autoTopup"), {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enabled: autoEnabled,
          amount: autoEnabled ? amount : 0,
          currency: autoCurrency.toLowerCase(),
          threshold: 100,
          ...(autoEnabled
            ? { payment_method_id: autoPaymentMethodId.trim(), email }
            : {}),
        }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      if (token === generation) autoSaved = true;
    } catch {
      if (token === generation)
        autoError = $text("settings.billing.team_auto_topup_error");
    } finally {
      if (token === generation) autoSaving = false;
    }
  }

  async function exportUsage(format: "csv" | "pdf"): Promise<void> {
    error = "";
    try {
      const response = await fetch(
        `${billingPath(context, "usageExport")}?format=${format}`,
        { credentials: "include" },
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      const disposition = response.headers.get("Content-Disposition") ?? "";
      link.download =
        disposition.match(/filename="?([^";]+)"?/)?.[1] ??
        `team-usage.${format}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch {
      error = $text("settings.billing.team_usage_error");
    }
  }
</script>

<div
  class:preview-frame={preview}
  class="team-billing-frame"
  data-testid="team-billing-frame"
>
  {#if preview}
    <TeamSettingsHeader {activeSettingsView} team={previewTeam} />
  {/if}
  <SettingsPageContainer>
    <div data-testid="team-billing-page">
      {#key teamId}
        {#if loading}
          <SettingsInfoBox type="info"
            ><p>{$text("common.loading")}</p></SettingsInfoBox
          >
        {:else if error && !canManage}
          <SettingsInfoBox type="warning"
            ><p role="alert">{error}</p></SettingsInfoBox
          >
        {:else if !canManage}
          <SettingsInfoBox type="warning"
            ><p>
              {$text("settings.billing.team_billing_admin_only")}
            </p></SettingsInfoBox
          >
        {:else if section === "address"}
          <SettingsBillingAddress {teamId} {preview} />
        {:else if section === "buy-credits"}
          <SettingsBuyCredits
            {routePrefix}
            on:openSettings={(event) => dispatch("openSettings", event.detail)}
          />
        {:else if section === "buy-credits/payment"}
          <SettingsBuyCreditsPayment
            {context}
            {routePrefix}
            on:openSettings={(event) => dispatch("openSettings", event.detail)}
          />
        {:else if section === "buy-credits/confirmation"}
          <SettingsPageHeader
            title={$text("settings.billing.purchase_successful")}
          />
          <SettingsInfoBox type="success"
            ><p data-testid="team-billing-purchase-confirmed">
              {$text("settings.billing.purchase_successful")}
            </p></SettingsInfoBox
          >
          <SettingsButton
            variant="secondary"
            onClick={() =>
              navigate(
                "",
                $text("settings.billing.team_billing_title"),
                "coins",
              )}
          >
            {$text("settings.billing.team_billing_title")}
          </SettingsButton>
        {:else if section === "invoices"}
          <SettingsInvoices {context} />
        {:else if section === "auto-topup"}
          <SettingsPageHeader
            title={$text("settings.billing.team_auto_topup")}
          />
          <SettingsItem
            type="submenu"
            icon="subsetting_icon low_balance"
            title={$text("settings.billing.on_low_balance")}
            onClick={() =>
              navigate(
                "auto-topup/low-balance",
                $text("settings.billing.on_low_balance"),
                "low_balance",
              )}
            data-testid="team-auto-topup-low-balance"
          />
          <SettingsItem
            type="submenu"
            icon="subsetting_icon calendar"
            title={$text("settings.billing.team_monthly_auto_topup")}
            onClick={() =>
              navigate(
                "auto-topup/monthly",
                $text("settings.billing.team_monthly_auto_topup"),
                "calendar",
              )}
            data-testid="team-auto-topup-monthly"
          />
        {:else if section === "auto-topup/monthly"}
          <SettingsTeamMonthlyAutoTopup {teamId} {preview} />
        {:else if section === "auto-topup/low-balance"}
          <SettingsPageHeader
            title={$text("settings.billing.team_auto_topup")}
          />
          {#if !autoReady}
            <SettingsInfoBox type="warning"
              ><p role="alert">
                {$text("settings.billing.team_billing_unavailable")}
              </p></SettingsInfoBox
            >
          {:else}
            <SettingsItem
              type="toggle"
              icon="subsetting_icon reload"
              title={$text("settings.billing.auto_topup")}
              hasToggle
              checked={autoEnabled}
              onClick={() => (autoEnabled = !autoEnabled)}
              data-testid="team-auto-topup-toggle"
            />
            {#if autoEnabled}
              <SettingsDropdown
                bind:value={autoCurrency}
                options={[
                  { value: "EUR", label: "EUR (€)" },
                  { value: "USD", label: "USD ($)" },
                ]}
                onChange={changeAutoCurrency}
                ariaLabel={$text("settings.billing.currency")}
                dataTestid="team-auto-topup-currency"
              />
              <SettingsDropdown
                bind:value={autoAmount}
                options={pricingTiers
                  .filter(
                    (tier) =>
                      !tier.bank_transfer_only &&
                      tier.price[
                        autoCurrency.toLowerCase() as "eur" | "usd"
                      ] !== undefined,
                  )
                  .map((tier) => ({
                    value: String(tier.credits),
                    label: `${tier.credits.toLocaleString()} ${$text("common.credits")}`,
                  }))}
                ariaLabel={$text("settings.billing.team_auto_topup_amount")}
                placeholder={$text("settings.billing.team_auto_topup_amount")}
                dataTestid="team-auto-topup-amount"
              />
              <SettingsDropdown
                bind:value={autoPaymentMethodId}
                options={paymentMethods.map((method) => ({
                  value: method.id,
                  label: `${method.card?.brand ?? $text("settings.billing.card_fallback")} •••• ${method.card?.last4 ?? ""}`,
                }))}
                ariaLabel={$text("settings.billing.team_auto_topup_method")}
                placeholder={$text("settings.billing.team_auto_topup_method")}
                dataTestid="team-auto-topup-method"
              />
            {/if}
            <SettingsButtonGroup align="left"
              ><SettingsButton
                loading={autoSaving}
                dataTestid="team-auto-topup-save"
                onClick={() => void saveAutoTopup()}
                >{$text("common.save")}</SettingsButton
              ></SettingsButtonGroup
            >
            {#if autoError}<SettingsInfoBox type="warning"
                ><p role="alert">{autoError}</p></SettingsInfoBox
              >{/if}
            {#if autoSaved}<SettingsInfoBox type="success"
                ><p data-testid="team-auto-topup-saved">
                  {$text("settings.billing.team_auto_topup_saved")}
                </p></SettingsInfoBox
              >{/if}
          {/if}
        {:else}
          <div class="billing-overview">
            <div class="team-balance-card" data-testid="team-billing-balance">
              <div class="balance-amount">
                <span>{balance.toLocaleString()}</span><span
                  class="balance-coins"
                  aria-hidden="true"
                ></span>
              </div>
              <div class="balance-label">
                {$text("settings.billing.team_balance_remaining")}
              </div>
              {#if balance <= 0}<p class="balance-warning">
                  {$text("settings.billing.team_zero_balance_warning")}
                </p>{/if}
            </div>
            <div class="billing-actions">
              <SettingsMenuItem
                type="submenu"
                icon="coins"
                title={$text("common.buy_credits")}
                onClick={() =>
                  navigate("buy-credits", $text("common.buy_credits"), "coins")}
                data-testid="team-billing-buy-credits"
              />
              <SettingsMenuItem
                type="submenu"
                icon="reload"
                title={$text("settings.billing.auto_topup")}
                onClick={() =>
                  navigate(
                    "auto-topup",
                    $text("settings.billing.auto_topup"),
                    "reload",
                  )}
                data-testid="team-billing-auto-topup"
              />
              <SettingsMenuItem
                type="submenu"
                icon="document"
                title={$text("common.invoices")}
                onClick={() =>
                  navigate("invoices", $text("common.invoices"), "document")}
                data-testid="team-billing-invoices"
              />
              <SettingsMenuItem
                type="submenu"
                icon="maps"
                title={$text("settings.billing.billing_address")}
                onClick={() =>
                  navigate(
                    "address",
                    $text("settings.billing.billing_address"),
                    "maps",
                  )}
                data-testid="team-billing-address"
              />
            </div>
            <div class="billing-usage-heading">
              <SettingsMenuItem
                type="heading"
                icon="usage"
                title={$text("settings.usage")}
              />
            </div>
            <SettingsMenuItem
              type="submenu"
              icon="download"
              iconBackground="none"
              title={$text("settings.billing.team_usage_download")}
              subtitleBottom="CSV & PDF"
              onClick={() => (downloadsExpanded = !downloadsExpanded)}
              data-testid="team-usage-download"
            />
            {#if downloadsExpanded}
              <SettingsButtonGroup align="left">
                <SettingsButton
                  variant="secondary"
                  dataTestid="team-usage-csv"
                  onClick={() => void exportUsage("csv")}
                >
                  {$text("settings.billing.team_usage_export_csv")}
                </SettingsButton>
                <SettingsButton
                  variant="secondary"
                  dataTestid="team-usage-pdf"
                  onClick={() => void exportUsage("pdf")}
                >
                  {$text("settings.billing.team_usage_export_pdf")}
                </SettingsButton>
              </SettingsButtonGroup>
            {/if}
            {#if usageEntries !== null}<SettingsTeamUsage
                entries={usageEntries}
              />{/if}
          </div>
          {#if error}<SettingsInfoBox type="warning"
              ><p role="alert">{error}</p></SettingsInfoBox
            >{/if}
        {/if}
      {/key}
    </div>
  </SettingsPageContainer>
</div>

<style>
  .team-billing-frame {
    width: 100%;
  }
  .team-billing-frame.preview-frame {
    min-height: 719px;
    background: var(--color-grey-20);
  }
  .team-billing-frame :global(.settings-page-container) {
    padding-top: 11px;
  }
  .billing-overview {
    padding: 0 6px;
  }
  .billing-overview :global(.menu-item) {
    padding: 5px 10px;
  }
  .team-balance-card {
    box-sizing: border-box;
    height: 129px;
    margin: 0 7px 0 10px;
    border-radius: 12px;
    background: var(--color-primary);
    box-shadow: var(--shadow-xs);
    color: var(--color-font-button);
    display: flex;
    flex-direction: column;
    align-items: center;
    padding-top: 12px;
    text-align: center;
  }
  .balance-amount {
    display: flex;
    align-items: center;
    gap: 3px;
    font-size: var(--font-size-p);
    font-weight: 700;
    line-height: 25px;
  }
  .balance-coins {
    width: 25px;
    height: 25px;
    background: var(--color-font-button);
    -webkit-mask: var(--icon-url-coins) center / contain no-repeat;
    mask: var(--icon-url-coins) center / contain no-repeat;
  }
  .balance-label {
    color: color-mix(in srgb, var(--color-font-button) 50%, transparent);
    margin-top: 8px;
    font-size: var(--font-size-p);
    line-height: 20px;
  }
  .balance-warning {
    max-width: 220px;
    margin: 17px 0 0;
    font-size: var(--font-size-p);
    font-weight: 500;
    line-height: 20px;
  }
  .billing-actions {
    margin-top: 11px;
  }
  .billing-actions :global(.menu-title),
  .billing-usage-heading :global(.menu-title),
  .billing-overview :global([data-testid="team-usage-download"] .menu-title) {
    font-weight: 700;
  }
  .billing-usage-heading {
    margin-top: 20px;
  }
  .billing-usage-heading :global(.menu-item) {
    font-weight: 700;
  }
  @media (max-width: 350px) {
    .billing-overview {
      padding: 0 6px;
    }
  }
</style>
