# Svelte <-> Swift Counterparts

This file tracks the current native Swift counterparts for the Svelte product UI files being ported. Svelte files should also carry these links in their own header comments when they are edited.

## App Shell & Navigation

| Svelte / CSS source | Swift counterpart |
| --- | --- |
| `frontend/apps/web_app/src/routes/+page.svelte` | `apple/OpenMates/Sources/App/MainAppView.swift`, `apple/OpenMates/Sources/App/RootView.swift` |
| `frontend/packages/ui/src/components/Header.svelte` | `apple/OpenMates/Sources/App/MainAppView.swift` |
| `frontend/packages/ui/src/components/ChatHistory.svelte` | `apple/OpenMates/Sources/App/MainAppView.swift`, `apple/OpenMates/Sources/Shared/Components/ChatListRow.swift` |

## Chat Views

| Svelte / CSS source | Swift counterpart |
| --- | --- |
| `frontend/packages/ui/src/components/ChatHeader.svelte` | `apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift`, `apple/OpenMates/Sources/Features/Chat/Views/ChatHeaderView.swift`, `apple/OpenMates/Sources/Features/Chat/Views/ChatBannerView.swift` |
| `frontend/packages/ui/src/components/ChatMessage.svelte` | `apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift` (MessageBubble) |
| `frontend/packages/ui/src/components/enter_message/MessageInput.svelte` | `apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift`, `apple/OpenMates/Sources/Features/Chat/Views/AttachmentPicker.swift`, `apple/OpenMates/Sources/Features/Chat/Views/VoiceRecordingView.swift`, `apple/OpenMates/Sources/Features/Chat/Views/InputActionButtons.swift` |
| `frontend/packages/ui/src/components/enter_message/MessageInput.styles.css` | `apple/OpenMates/Sources/Features/Chat/Views/ChatView.swift` |
| `frontend/packages/ui/src/components/FollowUpSuggestions.svelte` | `apple/OpenMates/Sources/Features/Chat/Views/FollowUpSuggestions.swift` |
| `frontend/packages/ui/src/components/ChatSearch.svelte` | `apple/OpenMates/Sources/Features/Chat/Views/ChatSearchView.swift` |
| `frontend/packages/ui/src/components/ChatShare.svelte` | `apple/OpenMates/Sources/Features/Chat/Views/ChatShareView.swift` |
| `frontend/packages/ui/src/components/ChatImport.svelte` | `apple/OpenMates/Sources/Features/Chat/Views/ChatImportView.swift` |
| `frontend/packages/ui/src/components/ExampleChats.svelte` | `apple/OpenMates/Sources/Features/Chat/Views/ExampleChatsView.swift` |
| `frontend/packages/ui/src/components/HiddenChatsList.svelte` | `apple/OpenMates/Sources/Features/Chat/Views/HiddenChatsListView.swift` |
| `frontend/packages/ui/src/components/HiddenChats.svelte` | `apple/OpenMates/Sources/Features/Chat/Views/HiddenChatsView.swift` |
| `frontend/packages/ui/src/components/ReminderPicker.svelte` | `apple/OpenMates/Sources/Features/Chat/Views/ReminderView.swift` |
| `frontend/packages/ui/src/components/FocusModeSelector.svelte` | `apple/OpenMates/Sources/Features/Chat/Views/FocusModeView.swift` |
| `frontend/packages/ui/src/components/IncognitoMode.svelte` | `apple/OpenMates/Sources/Features/Chat/Views/IncognitoMode.swift` |
| `frontend/packages/ui/src/components/DailyInspiration.svelte` | `apple/OpenMates/Sources/Features/Chat/Views/DailyInspirationView.swift` |
| `frontend/packages/ui/src/components/MessageContextMenu.svelte` | `apple/OpenMates/Sources/Features/Chat/Views/MessageContextMenu.swift`, `apple/OpenMates/Sources/Features/Chat/Views/ChatContextMenu.swift` |
| `frontend/packages/ui/src/components/MentionDropdown.svelte` | `apple/OpenMates/Sources/Features/Chat/Views/MentionDropdownView.swift` |
| `frontend/packages/ui/src/components/NewChatSuggestions.svelte` | `apple/OpenMates/Sources/Features/Chat/Views/NewChatSuggestionsView.swift` |
| `frontend/packages/ui/src/components/PIIDetection.svelte` | `apple/OpenMates/Sources/Features/Chat/Views/PIIDetectionView.swift` |
| `frontend/packages/ui/src/components/ThinkingSection.svelte` | `apple/OpenMates/Sources/Features/Chat/Views/ThinkingSectionView.swift` |
| `frontend/packages/ui/src/components/ProcessingDetails.svelte` | `apple/OpenMates/Sources/Features/Chat/Views/ProcessingDetailsView.swift` |
| `frontend/packages/ui/src/components/MessageHighlights.svelte` | `apple/OpenMates/Sources/Features/Chat/Views/MessageHighlightsView.swift`, `apple/OpenMates/Sources/Features/Chat/Views/HighlightNavigationView.swift` |
| `frontend/packages/ui/src/components/RichMarkdownRenderer.svelte` | `apple/OpenMates/Sources/Shared/Components/RichMarkdownRenderer.swift` |

## Embeds

| Svelte / CSS source | Swift counterpart |
| --- | --- |
| `frontend/packages/ui/src/components/embeds/UnifiedEmbedPreview.svelte` | `apple/OpenMates/Sources/Features/Embeds/Views/EmbedPreviewCard.swift`, `apple/OpenMates/Sources/Features/Embeds/Views/EmbedContentView.swift` |
| `frontend/packages/ui/src/components/embeds/UnifiedEmbedFullscreen.svelte` | `apple/OpenMates/Sources/Features/Embeds/Views/EmbedFullscreenView.swift`, `apple/OpenMates/Sources/Features/Embeds/Grouping/EmbedFullscreenContainer.swift` |
| `frontend/packages/ui/src/components/embeds/BasicInfosBar.svelte` | `apple/OpenMates/Sources/Features/Embeds/Views/EmbedPreviewCard.swift` |
| `frontend/packages/ui/src/components/embeds/ShareEmbed.svelte` | `apple/OpenMates/Sources/Features/Embeds/Views/ShareEmbedView.swift` |
| `frontend/packages/ui/src/components/embeds/EmbedContextMenu.svelte` | `apple/OpenMates/Sources/Features/Embeds/Views/EmbedContextMenuView.swift` |

## Settings — Main

| Svelte / CSS source | Swift counterpart |
| --- | --- |
| `frontend/packages/ui/src/components/settings/CurrentSettingsPage.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/SettingsView.swift` |
| `frontend/packages/ui/src/components/settings/SettingsMainHeader.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/SettingsView.swift` |

## Settings — Sub-Pages

| Svelte / CSS source | Swift counterpart |
| --- | --- |
| `frontend/packages/ui/src/components/settings/SettingsAccount.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/SettingsSubPages.swift` (AccountSettingsView) |
| `frontend/packages/ui/src/components/settings/SettingsChat.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/SettingsSubPages.swift` (ChatSettingsView) |
| `frontend/packages/ui/src/components/settings/SettingsInterface.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/SettingsSubPages.swift` (InterfaceSettingsView) |
| `frontend/packages/ui/src/components/settings/SettingsSecurity.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/SettingsSubPages.swift` (SecuritySettingsView) |
| `frontend/packages/ui/src/components/settings/SettingsNotifications.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/SettingsSubPages.swift` (NotificationSettingsView) |
| `frontend/packages/ui/src/components/settings/SettingsPrivacy.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/SettingsSubPages.swift` (PrivacySettingsView) |
| `frontend/packages/ui/src/components/settings/SettingsBilling.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/SettingsBillingView.swift` |
| `frontend/packages/ui/src/components/settings/SettingsServer.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/SettingsServerView.swift` |
| `frontend/packages/ui/src/components/settings/SettingsAI.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/SettingsAIFull.swift` |
| `frontend/packages/ui/src/components/settings/SettingsDevelopers.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/SettingsDeveloperFull.swift` |
| `frontend/packages/ui/src/components/settings/SettingsPrivacy.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/SettingsHidePersonalDataView.swift` |
| `frontend/packages/ui/src/components/settings/SettingsMemoriesHub.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/SettingsMemoriesFull.swift` |
| `frontend/packages/ui/src/components/settings/SettingsAllApps.svelte`, `frontend/packages/ui/src/components/settings/SettingsAppStore.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/SettingsAppsFull.swift` |
| `frontend/packages/ui/src/components/settings/SettingsUsage.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/SettingsStorageFull.swift` |
| `frontend/packages/ui/src/components/settings/SettingsMates.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/SettingsMatesView.swift` |
| `frontend/packages/ui/src/components/settings/SettingsShared.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/SettingsSharedView.swift` |
| `frontend/packages/ui/src/components/settings/SettingsAccount.svelte` (email section) | `apple/OpenMates/Sources/Features/Settings/Views/SettingsEmailView.swift` |
| `frontend/packages/ui/src/components/settings/SettingsAccount.svelte` (avatar section) | `apple/OpenMates/Sources/Features/Settings/Views/SettingsProfilePictureView.swift` |
| `frontend/packages/ui/src/components/settings/SettingsPasskeys.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/SettingsSessionPairingView.swift` |
| `frontend/packages/ui/src/components/settings/SettingsSecurity.svelte` (devices section) | `apple/OpenMates/Sources/Features/Settings/Views/SettingsDevicesView.swift` |
| `frontend/packages/ui/src/components/settings/SettingsSupport.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/SettingsSupportView.swift` |
| `frontend/packages/ui/src/components/settings/SettingsPricing.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/SettingsPricingView.swift` |
| `frontend/packages/ui/src/components/settings/SettingsLogs.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/SettingsLogsView.swift` |
| `frontend/packages/ui/src/components/settings/SettingsReportIssue.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/ReportIssueView.swift` |
| `frontend/packages/ui/src/components/settings/SettingsNewsletter.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/NewsletterSettingsView.swift` |
| `frontend/packages/ui/src/components/settings/SettingsShareDebugLogs.svelte` | `apple/OpenMates/Sources/Features/Settings/Views/SettingsShareDebugLogsView.swift` |
| `frontend/packages/ui/src/components/settings/SettingsAccount.svelte` (chats section) | `apple/OpenMates/Sources/Features/Settings/Views/SettingsAccountChatsView.swift` |
| `frontend/packages/ui/src/components/settings/SettingsAccount.svelte` (export section) | `apple/OpenMates/Sources/Features/Settings/Views/SettingsExportAccountView.swift` |
| `frontend/packages/ui/src/components/settings/SettingsAccount.svelte` (incognito section) | `apple/OpenMates/Sources/Features/Settings/Views/SettingsIncognitoInfoView.swift` |

## Settings — Design System Elements

| Svelte / CSS source | Swift counterpart |
| --- | --- |
| `frontend/packages/ui/src/components/settings/elements/SettingsItem.svelte` | `apple/OpenMates/Sources/Shared/Components/OMDesignPrimitives.swift` (OMSettingsRow) |
| `frontend/packages/ui/src/components/settings/elements/SettingsSectionHeading.svelte` | `apple/OpenMates/Sources/Shared/Components/OMDesignPrimitives.swift` (OMSettingsSection) |
| `frontend/packages/ui/src/components/settings/elements/SettingsButton.svelte` | `apple/OpenMates/Sources/Shared/Components/OMButtonStyles.swift`, `apple/OpenMates/Sources/Shared/Components/OMDesignPrimitives.swift` |
| `frontend/packages/ui/src/components/settings/elements/SettingsInput.svelte` | `apple/OpenMates/Sources/Shared/Components/OMButtonStyles.swift`, `apple/OpenMates/Sources/Shared/Components/OMDesignPrimitives.swift` |
| `frontend/packages/ui/src/components/settings/elements/SettingsConsentToggle.svelte` | `apple/OpenMates/Sources/Shared/Components/OMDesignPrimitives.swift` (OMToggle) |
| `frontend/packages/ui/src/components/settings/elements/SettingsDropdown.svelte` | `apple/OpenMates/Sources/Shared/Components/OMDesignPrimitives.swift` (OMDropdown) |
| `frontend/packages/ui/src/components/settings/elements/SettingsConfirmBlock.svelte` | `apple/OpenMates/Sources/Shared/Components/OMDesignPrimitives.swift` (OMConfirmDialog) |
| `frontend/packages/ui/src/components/settings/elements/SettingsPageContainer.svelte` | `apple/OpenMates/Sources/Shared/Components/OMDesignPrimitives.swift` (OMSettingsPage) |
| `frontend/packages/ui/src/components/settings/elements/SettingsPageHeader.svelte` | `apple/OpenMates/Sources/Shared/Components/OMDesignPrimitives.swift` (OMSettingsPage header) |
| `frontend/packages/ui/src/components/settings/elements/SettingsTabs.svelte` | `apple/OpenMates/Sources/Shared/Components/OMDesignPrimitives.swift` (OMSegmentedControl) |

## Auth Views

| Svelte / CSS source | Swift counterpart |
| --- | --- |
| `frontend/packages/ui/src/components/signup/Signup.svelte` | `apple/OpenMates/Sources/Features/Auth/Views/SignupFlowView.swift` |
| `frontend/packages/ui/src/components/signup/SignupNav.svelte` | `apple/OpenMates/Sources/Features/Auth/Views/SignupFlowView.swift` |
| `frontend/packages/ui/src/components/signup/SignupStatusbar.svelte` | `apple/OpenMates/Sources/Features/Auth/Views/SignupFlowView.swift` |
| `frontend/apps/web_app/src/routes/login/+page.svelte` | `apple/OpenMates/Sources/Features/Auth/Views/AuthFlowView.swift`, `apple/OpenMates/Sources/Features/Auth/Views/EmailLookupView.swift` |
| `frontend/apps/web_app/src/routes/login/password/+page.svelte` | `apple/OpenMates/Sources/Features/Auth/Views/PasswordLoginView.swift` |
| `frontend/apps/web_app/src/routes/login/passkey/+page.svelte` | `apple/OpenMates/Sources/Features/Auth/Views/PasskeyLoginView.swift` |
| `frontend/apps/web_app/src/routes/recovery/+page.svelte` | `apple/OpenMates/Sources/Features/Auth/Views/AccountRecoveryView.swift`, `apple/OpenMates/Sources/Features/Auth/Views/RecoveryKeyView.swift`, `apple/OpenMates/Sources/Features/Auth/Views/BackupCodeView.swift` |
| `frontend/apps/web_app/src/routes/verify-device/+page.svelte` | `apple/OpenMates/Sources/Features/Auth/Views/DeviceVerificationView.swift` |

## Public Chats

| Svelte / CSS source | Swift counterpart |
| --- | --- |
| `frontend/packages/ui/src/components/PublicChatList.svelte` | `apple/OpenMates/Sources/Features/PublicChats/Views/PublicChatListView.swift` |
| `frontend/packages/ui/src/components/LegalChat.svelte` | `apple/OpenMates/Sources/Features/PublicChats/Views/LegalChatView.swift` |

## Shared Components

| Svelte / CSS source | Swift counterpart |
| --- | --- |
| `frontend/packages/ui/src/components/AppIcon.svelte` | `apple/OpenMates/Sources/Shared/Components/AppIconView.swift` |
| `frontend/packages/ui/src/styles/buttons.css` | `apple/OpenMates/Sources/Shared/Components/OMButtonStyles.swift` |
| `frontend/packages/ui/src/styles/chat.css` (speech bubble `::before`) | `apple/OpenMates/Sources/Shared/Components/SpeechBubbleShape.swift` |
