/**
 * Settings route definitions — maps settings path strings to their corresponding
 * Svelte components. Extracted from Settings.svelte to reduce file size and improve
 * maintainability.
 *
 * These are the "base" (static) routes. Dynamic routes for app store details and
 * entry detail pages are built at runtime in Settings.svelte via buildSettingsViews().
 */

import type { Component } from "svelte";

// ---------------------------------------------------------------------------
// Component imports — grouped by settings section
// ---------------------------------------------------------------------------

// Interface
import SettingsInterface from "./SettingsInterface.svelte";
import SettingsLanguage from "./interface/SettingsLanguage.svelte";

// Chat
import SettingsChat from "./SettingsChat.svelte";
import SettingsChatNotifications from "./chat/SettingsChatNotifications.svelte";

// Privacy
import SettingsPrivacy from "./SettingsPrivacy.svelte";
import SettingsHidePersonalData from "./privacy/SettingsHidePersonalData.svelte";
import SettingsAddName from "./privacy/SettingsAddName.svelte";
import SettingsAddAddress from "./privacy/SettingsAddAddress.svelte";
import SettingsAddBirthday from "./privacy/SettingsAddBirthday.svelte";
import SettingsAddCustomEntry from "./privacy/SettingsAddCustomEntry.svelte";
import SettingsAutoDeletion from "./privacy/SettingsAutoDeletion.svelte";

// Account & Security
import SettingsAccount from "./SettingsAccount.svelte";
import SettingsTimezone from "./account/SettingsTimezone.svelte";
import SettingsEmail from "./account/SettingsEmail.svelte";
import SettingsDeleteAccount from "./account/SettingsDeleteAccount.svelte";
import SettingsExportAccount from "./account/SettingsExportAccount.svelte";
import SettingsStorage from "./account/SettingsStorage.svelte";
import SettingsSecurity from "./SettingsSecurity.svelte";
import SettingsPasskeys from "./SettingsPasskeys.svelte";
import SettingsPassword from "./security/SettingsPassword.svelte";
import SettingsTwoFactorAuth from "./security/SettingsTwoFactorAuth.svelte";
import SettingsRecoveryKey from "./security/SettingsRecoveryKey.svelte";

// Billing
import SettingsUsage from "./SettingsUsage.svelte";
import SettingsBilling from "./SettingsBilling.svelte";
import SettingsBuyCredits from "./billing/SettingsBuyCredits.svelte";
import SettingsBuyCreditsPayment from "./billing/SettingsBuyCreditsPayment.svelte";
import SettingsBuyCreditsConfirmation from "./billing/SettingsBuyCreditsConfirmation.svelte";
import SettingsRedeemGiftCard from "./billing/SettingsRedeemGiftCard.svelte";
import SettingsAutoTopUp from "./billing/SettingsAutoTopUp.svelte";
import SettingsLowBalanceAutotopup from "./billing/autotopup/SettingsLowBalanceAutotopup.svelte";
import SettingsMonthlyAutotopup from "./billing/autotopup/SettingsMonthlyAutotopup.svelte";
import SettingsInvoices from "./billing/SettingsInvoices.svelte";

// Gift Cards
import SettingsGiftCards from "./giftcards/SettingsGiftCards.svelte";
import SettingsGiftCardsRedeem from "./giftcards/SettingsGiftCardsRedeem.svelte";
import SettingsGiftCardsRedeemed from "./giftcards/SettingsGiftCardsRedeemed.svelte";
import SettingsGiftCardsBuy from "./giftcards/SettingsGiftCardsBuy.svelte";
import SettingsGiftCardsBuyPayment from "./giftcards/SettingsGiftCardsBuyPayment.svelte";
import SettingsGiftCardsPurchaseConfirmation from "./giftcards/SettingsGiftCardsPurchaseConfirmation.svelte";

// App Store
import SettingsAppStore from "./SettingsAppStore.svelte";
import SettingsAllApps from "./SettingsAllApps.svelte";
import AppDetailsWrapper from "./AppDetailsWrapper.svelte";

// Shared / Social
import SettingsShared from "./SettingsShared.svelte";
import SettingsShare from "./share/SettingsShare.svelte";
import SettingsTip from "./tip/SettingsTip.svelte";

// Support & Community
import SettingsSupport from "./SettingsSupport.svelte";
import SettingsSupportOneTime from "./support/SettingsSupportOneTime.svelte";
import SettingsSupportMonthly from "./support/SettingsSupportMonthly.svelte";
import SettingsNewsletter from "./SettingsNewsletter.svelte";
import SettingsReportIssue from "./SettingsReportIssue.svelte";

// Developers
import SettingsDevelopers from "./SettingsDevelopers.svelte";
import SettingsApiKeys from "./developers/SettingsApiKeys.svelte";
import SettingsDevices from "./developers/SettingsDevices.svelte";

// Server (admin only)
import SettingsServer from "./SettingsServer.svelte";
import SettingsSoftwareUpdate from "./server/SettingsSoftwareUpdate.svelte";
import SettingsCommunitySuggestions from "./server/SettingsCommunitySuggestions.svelte";
import SettingsStats from "./server/SettingsStats.svelte";
import SettingsGiftCardGenerator from "./server/SettingsGiftCardGenerator.svelte";
import SettingsDefaultInspirations from "./server/SettingsDefaultInspirations.svelte";

// Incognito
import SettingsIncognitoInfo from "./incognito/SettingsIncognitoInfo.svelte";

// ---------------------------------------------------------------------------
// Base settings views map — static routes known at build time
// ---------------------------------------------------------------------------

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const baseSettingsViews: Record<string, Component<any>> = {
  // Privacy settings — anonymization, device permissions, auto deletion
  privacy: SettingsPrivacy,
  "privacy/hide-personal-data": SettingsHidePersonalData,
  "privacy/hide-personal-data/add-name": SettingsAddName,
  "privacy/hide-personal-data/add-address": SettingsAddAddress,
  "privacy/hide-personal-data/add-birthday": SettingsAddBirthday,
  "privacy/hide-personal-data/add-custom": SettingsAddCustomEntry,
  // Auto-deletion period editing — one component, three routes (category determined from path)
  "privacy/auto-deletion/chats": SettingsAutoDeletion,
  "privacy/auto-deletion/files": SettingsAutoDeletion,
  "privacy/auto-deletion/usage_data": SettingsAutoDeletion,
  // Usage
  usage: SettingsUsage,
  // Chat
  chat: SettingsChat,
  "chat/notifications": SettingsChatNotifications,
  // Billing
  billing: SettingsBilling,
  "billing/buy-credits": SettingsBuyCredits,
  "billing/buy-credits/payment": SettingsBuyCreditsPayment,
  "billing/buy-credits/confirmation": SettingsBuyCreditsConfirmation,
  "billing/redeem-giftcard": SettingsRedeemGiftCard,
  "billing/auto-topup": SettingsAutoTopUp,
  "billing/auto-topup/low-balance": SettingsLowBalanceAutotopup,
  "billing/auto-topup/monthly": SettingsMonthlyAutotopup,
  "billing/invoices": SettingsInvoices,
  // Gift Cards
  gift_cards: SettingsGiftCards,
  "gift_cards/redeem": SettingsGiftCardsRedeem,
  "gift_cards/redeemed": SettingsGiftCardsRedeemed,
  "gift_cards/buy": SettingsGiftCardsBuy,
  "gift_cards/buy/payment": SettingsGiftCardsBuyPayment,
  "gift_cards/buy/confirmation": SettingsGiftCardsPurchaseConfirmation,
  // App Store
  app_store: SettingsAppStore,
  "app_store/all": SettingsAllApps,
  // Shared
  shared: SettingsShared,
  "shared/share": SettingsShare,
  "shared/tip": SettingsTip,
  // Developers
  developers: SettingsDevelopers,
  "developers/api-keys": SettingsApiKeys,
  "developers/devices": SettingsDevices,
  // Interface
  interface: SettingsInterface,
  "interface/language": SettingsLanguage,
  // Server (admin only)
  server: SettingsServer,
  "server/software-update": SettingsSoftwareUpdate,
  "server/community-suggestions": SettingsCommunitySuggestions,
  "server/stats": SettingsStats,
  "server/gift-cards": SettingsGiftCardGenerator,
  "server/default-inspirations": SettingsDefaultInspirations,
  // Incognito
  "incognito/info": SettingsIncognitoInfo,
  // Account
  account: SettingsAccount,
  "account/timezone": SettingsTimezone,
  "account/email": SettingsEmail,
  "account/security": SettingsSecurity,
  "account/security/passkeys": SettingsPasskeys,
  "account/security/password": SettingsPassword,
  "account/security/2fa": SettingsTwoFactorAuth,
  "account/security/recovery-key": SettingsRecoveryKey,
  "account/export": SettingsExportAccount,
  "account/storage": SettingsStorage,
  "account/delete": SettingsDeleteAccount,
  // Newsletter
  newsletter: SettingsNewsletter,
  // Support
  support: SettingsSupport,
  "support/one-time": SettingsSupportOneTime,
  "support/monthly": SettingsSupportMonthly,
  // Report Issue
  report_issue: SettingsReportIssue,
};

/**
 * Re-export AppDetailsWrapper for use in the dynamic route builder
 * (app_store/{app_id} and nested skill/focus/memory routes).
 */
export { AppDetailsWrapper };
