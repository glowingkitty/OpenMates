// App string keys — type-safe accessors for ALL UI strings used in the native app.
// These resolve through LocalizationManager, which loads translations from the
// web app's i18n JSON files. All keys match the web app's translation paths.
// Every user-visible string in the app must use these keys — no hardcoded English.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.streaming.progressive-presentation, chats.surface.semantic-parity

import Foundation

@MainActor
enum AppStrings {
    // MARK: - Native Live Activities
    static var liveActivityDownloadsTitle: String { L("live_activities.downloads_title") }
    static var liveActivityUpcomingTitle: String { L("live_activities.upcoming_title") }
    static var liveActivityUpcomingDetail: String { L("live_activities.upcoming_detail") }
    static func activeChatsWidgetTotal(count: Int) -> String {
        LocalizationManager.shared.text(count == 1 ? "apple.active_chats_widget.total_one" : "apple.active_chats_widget.total", replacements: ["count": String(count)])
    }
    static func activeChatsWidgetChat(number: Int) -> String {
        LocalizationManager.shared.text("apple.active_chats_widget.chat", replacements: ["number": String(number)])
    }
    static var liveActivityTransfer: String { L("live_activities.transfer") }
    static var liveActivityVerifying: String { L("live_activities.verifying") }
    static var liveActivityWaiting: String { L("live_activities.waiting") }
    static var liveActivityRetrying: String { L("live_activities.retrying") }
    static func liveActivityDownloadComplete(model: String) -> String {
        LocalizationManager.shared.text("live_activities.download_complete", replacements: ["model": model])
    }
    static func liveActivityMultipleDownloads(count: Int) -> String {
        LocalizationManager.shared.text("live_activities.multiple_downloads", replacements: ["count": String(count)])
    }

    // MARK: - Native-only local model lab
    static var localLabPhaseSubmission: String { L("settings.local_models.phase_submission") }
    static var localLabPhaseTokenizer: String { L("settings.local_models.phase_tokenizer") }
    static var localLabPhaseModelLoading: String { L("settings.local_models.phase_model_loading") }
    static var localLabPhaseTranscription: String { L("settings.local_models.phase_transcription") }
    static var localLabPhaseInference: String { L("settings.local_models.phase_inference") }
    static var localLabPhaseCleanup: String { L("settings.local_models.phase_cleanup") }
    static var localLabPhaseCompletion: String { L("settings.local_models.phase_completion") }
    static var localLabPhaseWarning: String { L("settings.local_models.phase_warning") }
    static var localLabBaselineMemory: String { L("settings.local_models.baseline_memory") }
    static var localLabEndMemory: String { L("settings.local_models.end_memory") }
    static func localLabVerifyingProgress(percent: Int) -> String {
        LocalizationManager.shared.text("settings.local_models.verifying_progress", replacements: ["percent": String(percent)])
    }
    static func localLabPhaseDuration(phase: String, seconds: String) -> String {
        LocalizationManager.shared.text("settings.local_models.phase_duration", replacements: ["phase": phase, "seconds": seconds])
    }
    static var localLabArchitectureUnavailable: String { L("settings.local_models.architecture_unavailable") }
    static var localLabPeakMemory: String { L("settings.local_models.peak_memory") }
    static var localLabPocketTTS: String { L("settings.local_models.pocket_tts") }
    static var localLabPocketDescription: String { L("settings.local_models.pocket_description") }
    static var localLabPocketVoice: String { L("settings.local_models.pocket_voice") }
    static var localLabPocketAttribution: String { L("settings.local_models.pocket_attribution") }
    static var localLabPocketInput: String { L("settings.local_models.pocket_input") }
    static var localLabPocketInputLimit: String { L("settings.local_models.pocket_input_limit") }
    static var localLabPocketSynthesis: String { L("settings.local_models.pocket_synthesis") }
    static var localLabPocketCancelling: String { L("settings.local_models.pocket_cancelling") }
    static var localLabPocketPlay: String { L("settings.local_models.pocket_play") }
    static var localLabPocketStop: String { L("settings.local_models.pocket_stop") }
    static var localLabTitle: String { L("settings.local_models.title") }
    static var localLabDescription: String { L("settings.local_models.description") }
    static var localLabToggle: String { L("settings.local_models.toggle") }
    static var localLabScope: String { L("settings.local_models.scope") }
    static var localLabDownload: String { L("settings.local_models.download") }
    static var localLabNotDownloaded: String { L("settings.local_models.not_downloaded") }
    static var localLabReady: String { L("settings.local_models.ready") }
    static var localLabDownloadFailed: String { L("settings.local_models.download_failed") }
    static var localLabNotEnoughSpace: String { L("settings.local_models.not_enough_space") }
    static var localLabRun: String { L("settings.local_models.run") }
    static var localLabImportAudio: String { L("settings.local_models.import_audio") }
    static var localLabRecord: String { L("settings.local_models.record") }
    static var localLabStopRecording: String { L("settings.local_models.stop_recording") }
    static var localLabPrivacyInput: String { L("settings.local_models.privacy_input") }
    static var localLabInputPlaceholder: String { L("settings.local_models.input_placeholder") }
    static var localLabRunning: String { L("settings.local_models.running") }
    static var localLabCancelling: String { L("settings.local_models.cancelling") }
    static var localLabElapsed: String { L("settings.local_models.elapsed") }
    static var localLabRtf: String { L("settings.local_models.rtf") }
    static var localLabThermalNominal: String { L("settings.local_models.thermal_nominal") }
    static var localLabThermalFair: String { L("settings.local_models.thermal_fair") }
    static var localLabThermalSerious: String { L("settings.local_models.thermal_serious") }
    static var localLabThermalCritical: String { L("settings.local_models.thermal_critical") }
    static var localLabUnavailable: String { L("settings.local_models.unavailable") }
    static var localLabResult: String { L("settings.local_models.result") }
    static var localLabNoEntities: String { L("settings.local_models.no_entities") }
    static var localLabAudioError: String { L("settings.local_models.audio_error") }
    static var localLabMicrophoneError: String { L("settings.local_models.microphone_error") }
    static var localLabRunError: String { L("settings.local_models.run_error") }
    static var localLabPrivacyNote: String { L("settings.local_models.privacy_note") }
    static var localLabWhisper: String { L("settings.local_models.whisper") }
    static var localLabPrivacyFilter: String { L("settings.local_models.privacy_filter") }
    static var localLabInstalledSize: String { L("settings.local_models.installed_size") }
    static var localLabRevision: String { L("settings.local_models.revision") }
    static func localLabWaitingForConnection(percent: Int) -> String {
        LocalizationManager.shared.text("settings.local_models.waiting_for_connection", replacements: ["percent": String(percent)])
    }
    static func localLabRetrying(percent: Int) -> String {
        LocalizationManager.shared.text("settings.local_models.retrying_download", replacements: ["percent": String(percent)])
    }
    static func localLabDownloading(percent: Int) -> String {
        LocalizationManager.shared.text("settings.local_models.downloading", replacements: ["percent": String(percent)])
    }
    static func localLabAudioReady(seconds: String) -> String {
        LocalizationManager.shared.text("settings.local_models.audio_ready", replacements: ["seconds": seconds])
    }
    static func localLabEnvironment(cores: Int, memory: String, thermal: String) -> String {
        LocalizationManager.shared.text("settings.local_models.environment", replacements: ["cores": String(cores), "memory": memory, "thermal": thermal])
    }
    static func localLabEntity(label: String, start: Int, end: Int, score: String) -> String {
        LocalizationManager.shared.text("settings.local_models.entity", replacements: ["label": label, "start": String(start), "end": String(end), "score": score])
    }

    /// Saved draft references use the web draftPreview.ts labels, localized here.
    static func draftEmbedPreviewLabel(type: String) -> String {
        let key: String
        switch type {
        case "image": key = "image"
        case "audio", "audio-recording": key = "audio"
        case "recording": key = "recording"
        case "website", "web-website": key = "website"
        case "video", "videos-video": key = "video"
        case "location", "maps": key = "location"
        case "pdf": key = "pdf"
        case "file": key = "file"
        case "book": key = "book"
        case "code", "code-code", "code-code-group": key = "code"
        case "", "embed": key = "embed"
        default:
            return "[" + type.replacingOccurrences(of: "-", with: " ")
                .replacingOccurrences(of: "_", with: " ").capitalized + "]"
        }
        return "[" + L("chat.draft_embed_labels." + key) + "]"
    }

    // MARK: - Common
    static var settings: String { L("common.settings") }
    static var cancel: String { L("common.cancel") }
    static var save: String { L("common.save") }
    static var saveDraft: String { L("common.save_draft") }
    static var done: String { L("common.done") }
    static var delete: String { L("common.delete") }
    static var close: String { L("common.close") }
    static var loading: String { L("common.loading") }
    static var error: String { L("common.error") }
    static var success: String { L("common.success") }
    static var credits: String { L("common.credits") }
    static var pricing: String { L("common.pricing") }
    static var back: String { L("common.back") }
    static var showLess: String { L("common.show_less") }
    // Reuse the catalog's translated navigation action; common.next is absent.
    static var next: String { L("projects.workspace_next") }
    static var skip: String { L("common.skip") }
    static var search: String { L("activity.search") }
    static var quickActionAsk: String { L("activity.quick_action_ask") }
    static var quickActionRecordRequest: String { L("activity.quick_action_record_request") }
    static var quickActionAskAboutPhoto: String { L("activity.quick_action_ask_about_photo") }
    static var quickActionIncognitoAsk: String { L("activity.quick_action_incognito_ask") }
    static var retry: String { L("common.retry") }
    static var confirm: String { L("common.confirm") }
    static var edit: String { L("common.edit") }
    static var add: String { L("common.add") }
    // The shared web catalog defines this action under sessions; common.remove
    // does not exist and previously exposed the raw key on attachment buttons.
    static var remove: String { L("settings.sessions.remove") }
    static var enabled: String { L("common.enabled") }
    static var disabled: String { L("common.disabled") }
    static var on: String { L("common.on") }
    static var off: String { L("common.off") }
    static var yes: String { L("common.yes") }
    static var no: String { L("common.no") }
    static var ok: String { L("common.ok") }
    static var copied: String { L("common.copied") }
    static var version: String { L("settings.current_version") }
    static var openMatesName: String { L("apps.openmates") }
    static var socialMedia: String { L("apps.social_media") }
    static var weatherDay: String { L("apps.weather.day") }
    static var weatherForecast: String { L("apps.weather.forecast") }
    static var weatherForecastRain: String { L("embeds.weather.forecast.rain") }
    static var financeCheckAccounts: String { L("app_skills.finance.check_accounts") }
    static var focusModeActivated: String { L("embeds.focus_mode.activated") }
    static var focusModeActiveBanner: String { L("embeds.focus_mode.active_banner") }
    static var focusModeFocusOn: String { L("embeds.focus_mode.focus_on") }
    static var financeNetCashFlow: String { L("embeds.finance.check_accounts.net_cash_flow") }
    static var financeCashBalance: String { L("embeds.finance.check_accounts.cash_balance") }
    static var financeAccounts: String { L("embeds.finance.check_accounts.accounts") }
    static var financeTransactions: String { L("embeds.finance.check_accounts.transactions") }
    static var financeIncome: String { L("embeds.finance.check_accounts.income") }
    static var financeExpenses: String { L("embeds.finance.check_accounts.expenses") }
    static var financeFilters: String { L("embeds.finance.check_accounts.filters") }
    static var financeAccount: String { L("embeds.finance.check_accounts.account") }
    static var financeSource: String { L("embeds.finance.check_accounts.source") }
    static var financeCategory: String { L("embeds.finance.check_accounts.category") }
    static var financeDirection: String { L("embeds.finance.check_accounts.direction") }
    static var financeState: String { L("embeds.finance.check_accounts.state") }
    static var financePlaceholder: String { L("embeds.finance.check_accounts.placeholder") }
    static var financeFrom: String { L("embeds.finance.check_accounts.from") }
    static var financeTo: String { L("embeds.finance.check_accounts.to") }
    static var financeAll: String { L("embeds.finance.check_accounts.all") }
    static var financeNoMatches: String { L("embeds.finance.check_accounts.no_matches") }
    static var travelFlightDiverted: String { L("embeds.travel.flight.diverted") }
    static var travelFlightTrackAvailable: String { L("embeds.travel.flight.track_available") }
    static var guest: String { L("settings.guest") }
    static var newWindow: String { L("common.new_window") }
    static var chat: String { L("common.chat") }
    static var projects: String { L("navigation.projects") }
    static var plans: String { L("navigation.plans") }
    static var workflows: String { L("navigation.workflows") }
    static var tasks: String { L("navigation.tasks") }
    // MARK: - Tasks workspace
    static var tasksGreeting: String { L("tasks.workspace.greeting") }
    static var tasksNext: String { L("tasks.workspace.next") }
    static var tasksSearch: String { L("tasks.workspace.search") }
    static var tasksFilters: String { L("tasks.workspace.filters") }
    static var tasksPrompt: String { L("tasks.workspace.prompt") }
    static var tasksPromptCompact: String { L("tasks.workspace.prompt_compact") }
    static var tasksSaving: String { L("tasks.workspace.saving") }
    static var tasksEmpty: String { L("tasks.workspace.empty") }
    static var tasksNoMatches: String { L("tasks.workspace.no_matches") }
    static var tasksDrag: String { L("tasks.workspace.drag") }
    static var tasksMoveFailed: String { L("tasks.workspace.move_failed") }
    static func tasksDropToMark(status: String) -> String {
        LocalizationManager.shared.text("tasks.workspace.drop_to_mark", replacements: ["status": status])
    }
    static var tasksLoadError: String { L("tasks.workspace.load_error") }
    static var tasksNew: String { L("tasks.workspace.new_task") }
    static var tasksAdd: String { L("tasks.workspace.add") }
    static var tasksNewPlan: String { L("tasks.workspace.new_plan") }
    static var tasksPlanRequiresProject: String { L("tasks.workspace.plan_requires_project") }
    static var tasksOpenTask: String { L("tasks.workspace.open_task") }
    static var tasksMoreActions: String { L("tasks.workspace.more_actions") }
    static var tasksBlock: String { L("tasks.workspace.block") }
    static var tasksUnblock: String { L("tasks.workspace.unblock") }
    static var tasksOpenPlan: String { L("tasks.workspace.open_plan") }
    static var tasksOpenChat: String { L("tasks.workspace.open_chat") }
    static var tasksShowMore: String { L("tasks.workspace.show_more") }
    static var tasksBacklog: String { L("tasks.workspace.backlog") }
    static var tasksTodo: String { L("tasks.workspace.todo") }
    static var tasksInProgress: String { L("tasks.workspace.in_progress") }
    static var tasksBlocked: String { L("tasks.workspace.blocked") }
    static var tasksDone: String { L("tasks.workspace.done") }
    static var tasksStatus: String { L("tasks.workspace.status") }
    static var tasksAssignee: String { L("tasks.workspace.assignee") }
    static var tasksMe: String { L("tasks.workspace.me") }
    static var tasksUnassigned: String { L("tasks.workspace.unassigned") }
    static var tasksDescription: String { L("tasks.workspace.description") }
    static var tasksNoDescription: String { L("tasks.workspace.no_description") }
    static var tasksDue: String { L("tasks.workspace.due") }
    static var tasksNoDue: String { L("tasks.workspace.no_due") }
    static var tasksProjects: String { L("tasks.workspace.projects") }
    static var tasksNoProject: String { L("tasks.workspace.no_project") }
    static var tasksPlan: String { L("tasks.workspace.plan") }
    static var tasksNoPlan: String { L("tasks.workspace.no_plan") }
    static var tasksDependencies: String { L("tasks.workspace.dependencies") }
    static var tasksNoDependencies: String { L("tasks.workspace.no_dependencies") }
    static var tasksTags: String { L("tasks.workspace.tags") }
    static var tasksNoTags: String { L("tasks.workspace.no_tags") }
    static var tasksChat: String { L("tasks.workspace.chat") }
    static var tasksNoChat: String { L("tasks.workspace.no_chat") }
    static var tasksActivity: String { L("tasks.activity.title") }
    static var tasksCommentPlaceholder: String { L("tasks.activity.placeholder") }
    static var tasksSend: String { L("tasks.activity.send") }
    static var tasksNoActivity: String { L("tasks.activity.empty") }
    static var tasksBlockedReason: String { L("tasks.blocked_heading") }
    static var tasksDeleteConfirmation: String { L("tasks.workspace.delete_confirmation") }
    static var tasksAssignAI: String { L("tasks.workspace.assign_ai") }
    static var tasksMove: String { L("tasks.workspace.move") }
    static var tasksComplete: String { L("tasks.workspace.complete") }
    static var tasksSkip: String { L("tasks.workspace.skip") }
    static var tasksPlanGoal: String { L("tasks.workspace.plan_goal") }
    static var tasksPlanAssumptions: String { L("tasks.workspace.plan_assumptions") }
    static var tasksPlanCriteria: String { L("tasks.workspace.plan_criteria") }
    static var tasksPlanChecks: String { L("tasks.workspace.plan_checks") }
    static var tasksPlanPatterns: String { L("tasks.workspace.plan_patterns") }
    static var tasksPlanOpenAssumptions: String { L("tasks.plan.open_assumptions") }
    static var tasksPlanUncoveredCriteria: String { L("tasks.plan.uncovered_criteria") }
    static var tasksPlanFailedChecks: String { L("tasks.plan.failed_checks") }
    static var tasksPlanAssumptionPlaceholder: String { L("tasks.plan.assumption_placeholder") }
    static var tasksPlanAddAssumption: String { L("tasks.plan.add_assumption") }
    static var tasksPlanCriterionPlaceholder: String { L("tasks.plan.criterion_placeholder") }
    static var tasksPlanAddCriterion: String { L("tasks.plan.add_criterion") }
    static var tasksPlanCheckDescription: String { L("tasks.plan.check_description") }
    static var tasksPlanOptionalCommand: String { L("tasks.plan.optional_command") }
    static var tasksPlanAddCheck: String { L("tasks.plan.add_check") }
    static var tasksPlanActivate: String { L("tasks.workspace.plan_activate") }
    static var tasksPlanComplete: String { L("tasks.workspace.plan_complete") }
    static var tasksWorkflowRunID: String { L("tasks.workspace.workflow_run_id") }
    static var tasksNoWorkflowRunID: String { L("tasks.workspace.no_workflow_run_id") }
    static var tasksWorkflowNodeStatus: String { L("tasks.workspace.workflow_node_status") }
    static var tasksOpenWorkflowRun: String { L("tasks.workspace.open_workflow_run") }
    static var tasksInspirationNextAction: String { L("tasks.workspace.inspiration_next_action") }
    static var tasksInspirationNextActionTitle: String { L("tasks.workspace.inspiration_next_action_title") }
    static var tasksInspirationPriorities: String { L("tasks.workspace.inspiration_priorities") }
    static var tasksInspirationPrioritiesTitle: String { L("tasks.workspace.inspiration_priorities_title") }
    static var tasksInspirationFinishLine: String { L("tasks.workspace.inspiration_finish_line") }
    static var tasksInspirationFinishLineTitle: String { L("tasks.workspace.inspiration_finish_line_title") }
    static var plansInspirationTimeline: String { L("tasks.workspace.plans_inspiration_timeline") }
    static var plansInspirationTimelineTitle: String { L("tasks.workspace.plans_inspiration_timeline_title") }
    static var tasksInspirationCTA: String { L("tasks.workspace.inspiration_create_task") }
    static var plansInspirationCTA: String { L("tasks.workspace.inspiration_create_plan") }
    static var tasksMicUnavailable: String { L("tasks.workspace.voice_input_unavailable") }
    static var tasksEditFailed: String { L("tasks.detail.edit_failed") }
    static var tasksEditConflict: String { L("tasks.detail.edit_conflict") }
    static var tasksPriority: String { L("tasks.detail.priority") }
    static var tasksWidgetTitle: String { L("apple.tasks_widget.title") }
    static var tasksWidgetDescription: String { L("apple.tasks_widget.description") }
    static var tasksWidgetStatusParameter: String { L("apple.tasks_widget.status_parameter") }
    static var tasksWidgetAll: String { L("apple.tasks_widget.all") }
    static var tasksWidgetEmpty: String { L("apple.tasks_widget.empty") }
    static var tasksWidgetOpenApp: String { L("apple.tasks_widget.open_app") }
    static var tasksWidgetNewTask: String { L("apple.tasks_widget.new_task") }
    static var tasksPriorityNone: String { L("tasks.detail.priority_none") }
    static var tasksPriorityLow: String { L("tasks.detail.priority_low") }
    static var tasksPriorityMedium: String { L("tasks.detail.priority_medium") }
    static var tasksPriorityHigh: String { L("tasks.detail.priority_high") }
    static var tasksPriorityUrgent: String { L("tasks.detail.priority_urgent") }
    static var tasksCreatorYou: String { L("tasks.detail.creator_you") }
    static var tasksCreatedSecondsAgo: String { L("tasks.detail.created_seconds_ago") }
    static func tasksCreatedMinutesAgo(_ count: Int) -> String {
        LocalizationManager.shared.text(
            count == 1 ? "tasks.detail.created_minute_ago" : "tasks.detail.created_minutes_ago",
            replacements: ["count": "\(count)"])
    }
    static func tasksCreatedOn(_ date: String) -> String {
        LocalizationManager.shared.text("tasks.detail.created_on", replacements: ["date": date])
    }
    static func tasksCreatedBy(_ created: String, creator: String) -> String {
        LocalizationManager.shared.text("tasks.detail.created_by",
                                        replacements: ["created": created, "creator": creator])
    }
    static var reportIssue: String { L("header.report_issue") }
    static var mapShowAllResults: String { L("embeds.maps.show_all_results") }
    static var models3d: String { L("apps.models3d") }
    static var workspacePreviewEyebrow: String { L("navigation.workspace_preview.eyebrow") }
    static var workspacePreviewReturnToChats: String { L("navigation.workspace_preview.return_to_chats") }

    static func workspacePreviewTitle(_ workspace: String) -> String {
        LocalizationManager.shared.text("navigation.workspace_preview.title", replacements: ["workspace": workspace])
    }

    static func workspacePreviewBody(_ workspace: String) -> String {
        LocalizationManager.shared.text("navigation.workspace_preview.body", replacements: ["workspace": workspace])
    }

    // MARK: - Chat
    static var newChat: String { L("chat.new_chat") }
    static var noChats: String { L("activity.no_chats") }
    static var loadingChats: String { L("activity.loading_chats") }
    static var subChatBatchLoading: String { L("chats.chat.sub_chats.batch_loading") }
    static var subChatAutonomousTask: String { L("chats.chat.sub_chats.autonomous_task") }
    static var subChatTapToOpen: String { L("chats.chat.sub_chats.tap_to_open") }
    static var subChatCompleted: String { L("chats.chat.sub_chats.status_completed") }
    static var subChatNeedsAttention: String { L("chats.chat.sub_chats.status_needs_attention") }
    static var subChatStopped: String { L("chats.chat.sub_chats.status_stopped") }
    static var subChatWaiting: String { L("chats.chat.sub_chats.status_waiting") }
    static var subChatQueued: String { L("chats.chat.sub_chats.status_queued") }
    static func subChatThinking(_ name: String) -> String {
        LocalizationManager.shared.text("chats.chat.sub_chats.status_thinking", replacements: ["name": name])
    }
    static var syncing: String { L("activity.syncing") }
    static var syncComplete: String { L("activity.sync_complete") }
    static var incognito: String { L("activity.incognito") }
    static var sendMessage: String { L("context_menu.send") }
    static var sendAction: String { L("enter_message.send") }
    static var copyMessage: String { L("chats.context_menu.copy.text") }
    static var editMessage: String { L("chats.context_menu.edit.text") }
    static var deleteMessage: String { L("chats.context_menu.delete_message.text") }
    static var forkConversation: String { L("chats.context_menu.fork.text") }
    static var chatMessageInput: String { L("chat.message_input") }
    static var typeMessage: String { L("enter_message.placeholder.touch") }
    static var typeFollowup: String { L("enter_message.placeholder.followup_touch") }
    static var startTyping: String { L("chat.start_typing") }
    static var aiResponding: String { L("enter_message.processing") }
    static func mateIsTyping(_ mate: String) -> String {
        LocalizationManager.shared.text("enter_message.is_typing", replacements: ["mate": mate])
    }
    static func mateIsThinking(_ mate: String) -> String {
        LocalizationManager.shared.text("enter_message.is_thinking", replacements: ["mate": mate])
    }
    static var sendingMessage: String { L("enter_message.sending") }
    static var selectingMateAndModel: String { L("enter_message.status.selecting_mate_and_model") }
    static var selectingMate: String { L("enter_message.status.selecting_mate") }
    static var selectingModel: String { L("enter_message.status.selecting_model") }
    static var analyzingMessage: String { L("enter_message.status.analyzing_message") }
    static var thinkingHeaderStreaming: String { L("chat.thinking.header_streaming") }
    static var thinkingHeaderDone: String { L("chat.thinking.header_done") }
    static var thinkingExpand: String { L("chat.thinking.expand") }
    static var thinkingCollapse: String { L("chat.thinking.collapse") }
    static var stopResponse: String { L("chat.stop_response") }
    static var messageQueued: String { L("enter_message.message_queued") }
    static var loadEarlierMessages: String { L("chat.load_earlier") }
    static var selectChatOrNew: String { L("chat.select_or_new") }
    static var whatToHelpWith: String { L("chat.what_to_help_with") }
    static var whatDoYouNeedHelpWith: String { L("chat.welcome.what_do_you_need_help_with") }
    static var resumeLastChatTitle: String { L("chats.resume_last_chat.title") }
    static var welcomeShowAllChats: String { L("chat.welcome.show_all_chats") }
    static var welcomeShowAllProjects: String { L("chat.welcome.show_all_projects") }
    static var welcomeBackToRecent: String { L("chat.welcome.back_to_recent") }
    static var exploreOpenMatesTitle: String { L("chats.explore_openmates.title") }
    static var previousInspiration: String { L("daily_inspiration.previous") }
    static var nextInspiration: String { L("daily_inspiration.next") }
    static var signUp: String { L("signup.sign_up") }
    static var pinnedChats: String { L("chat.pinned") }
    static var recentChats: String { L("chat.recent") }
    static var hiddenChats: String { L("chat.hidden_chats") }
    static var noHiddenChats: String { L("chat.no_hidden_chats") }
    static var unhide: String { L("chat.unhide") }
    static var piiHide: String { L("chat.pii_hide") }
    static var piiShow: String { L("chat.pii_show") }
    static var renameChat: String { L("chat.rename") }
    static var chatTitle: String { L("chat.title") }
    static var conversationForked: String { L("chat.forked") }
    // Specification: specifications/features/chats/specification.yml
    // Assertion: chats.layout.responsive-history
    static var setReminder: String { L("chat.header.set_reminder") }
    static var chats: String { L("common.chats") }
    static var summary: String { L("common.summary") }
    static var explore: String { L("common.explore") }
    static var openChat: String { L("chat.open_chat") }
    static var searchNoResults: String { L("chats.search.no_results") }
    static var searchResultsLabel: String { L("chats.search.results_label") }
    static var searchGoToMessage: String { L("chats.search.go_to_message") }
    static var searchTagMatch: String { L("chats.search.tag_match") }
    static var today: String { L("activity.today") }
    static var yesterday: String { L("activity.yesterday") }
    static var previous7Days: String { L("activity.previous_7_days") }
    static var previous30Days: String { L("activity.previous_30_days") }
    static var scrollToTop: String { L("chats.scroll_to_top") }
    static var scrollToBottom: String { L("chats.scroll_to_bottom") }
    static var interactiveQuestionFailed: String { L("chat.interactive_question_failed") }
    static var anonymousFreeUsageFeatureNotice: String { L("chat.anonymous_free_usage.feature_notice") }
    static var uploadSignupRequired: String { L("enter_message.attachments.signup_required.title") }
    static var requestFeature: String { L("chat.request_feature") }
    static var requestFeaturePrefill: String { L("chat.request_feature_prefill") }
    static var assistantFeedbackRateLabel: String { L("chat.assistant_feedback.rate_label") }
    static var assistantFeedbackSubmit: String { L("chat.assistant_feedback.submit") }
    static var assistantFeedbackThanks: String { L("chat.assistant_feedback.thanks") }
    static var assistantFeedbackReportTitle: String { L("chat.assistant_feedback.report_title") }

    static func assistantFeedbackStarLabel(count: Int) -> String {
        LocalizationManager.shared.text("chat.assistant_feedback.star_label", replacements: ["count": "\(count)"])
    }

    static func welcomeHeyUser(_ username: String) -> String {
        LocalizationManager.shared.text("chat.welcome.hey_user", replacements: ["username": username])
    }

    static var welcomeHeyGuest: String { L("chat.welcome.hey_guest") }

    // MARK: - Settings sections
    static var settingsAccount: String { L("settings.account") }
    static var settingsAI: String { L("settings.ai") }
    static var settingsBilling: String { L("settings.billing") }
    static var settingsSecurity: String { L("settings.security") }
    static var settingsPrivacy: String { L("settings.privacy") }
    static var settingsInterface: String { L("settings.interface") }
    static var settingsNotifications: String { L("settings.notifications") }
    static var settingsDevelopers: String { L("settings.developers") }
    static var settingsSupport: String { L("settings.support") }
    static var settingsNewsletter: String { L("settings.newsletter") }
    static var settingsReportIssue: String { L("settings.report_issue") }
    static var settingsShared: String { L("settings.shared") }
    static var settingsMates: String { L("settings.mates") }
    static var settingsApps: String { L("settings.app_store") }
    static var settingsMemories: String { L("settings.settings_memories") }
    static var settingsLogout: String { L("settings.logout") }
    static var settingsIncognito: String { L("settings.incognito") }
    static var learningMode: String { L("settings.learning_mode") }
    static var settingsPricing: String { L("settings.pricing") }

    // MARK: - Settings - Account
    static var username: String { L("settings.account.username") }
    static var timezone: String { L("settings.account.timezone") }
    static var email: String { L("settings.account.email") }
    static var interests: String { L("settings.account.interests") }
    static var interestsDescription: String { L("settings.account.interests_description") }
    static var interestsPrivacyNote: String { L("settings.account.interests_privacy_note") }
    static var interestsSaved: String { L("settings.account.interests_saved") }
    static var interestsSaveError: String { L("settings.account.interests_save_error") }
    static var interestsActiveTitle: String { L("chat.interests.active_title") }
    static var interestsExploreTitle: String { L("chat.interests.title") }
    static var interestsContinue: String { L("chat.interests.continue") }
    static var interestsSkip: String { L("chat.interests.skip") }
    static var interestsSelect: String { L("chat.interests.select_interests") }
    static var profilePicture: String { L("settings.account.profile_picture") }
    static var usage: String { L("settings.usage") }
    static var storage: String { L("settings.storage") }
    static var importChats: String { L("settings.account.import_title") }
    static var exportData: String { L("settings.export_data") }
    static var exportDescription: String { L("settings.account.export_description") }
    static var exportGDPRNotice: String { L("settings.account.export_gdpr_notice") }
    static var exportButton: String { L("settings.account.export_button") }
    static var exporting: String { L("settings.account.exporting") }
    static var exportSuccess: String { L("settings.account.export_success") }
    static var exportFilename: String { L("settings.account.export") }
    static var importDescription: String { L("settings.account.import_description") }
    static var importNativeDeferred: String { L("settings.account.import_native_deferred") }
    static var importOpenWeb: String { L("settings.account.import_open_web") }
    static var importChooseFile: String { L("settings.account.import_choose_file") }
    static var importing: String { L("settings.account.import_importing") }
    static var importSafetyNotice: String { L("settings.account.import_safety_notice") }
    static var importSuccess: String { L("settings.account.import_success") }
    static var importMessagesImported: String { L("settings.account.import_messages_imported") }
    static var importMessagesBlocked: String { L("settings.account.import_messages_blocked") }
    static var importCreditsCharged: String { L("settings.account.import_credits_charged") }
    static var importInvalidFormat: String { L("common.error") }
    static var importNoChats: String { L("settings.account.import_select_chats") }
    static var deleteAccount: String { L("settings.delete_account") }
    static var deleteAccountWarning: String { L("settings.delete_account.warning") }
    static var deleteAccountConfirmText: String { L("settings.delete_account.confirm_text") }
    static var permanentlyDeleteAccount: String { L("settings.delete_account.confirm_button") }

    // MARK: - Settings - AI
    static var aiModelProviders: String { L("settings.ai") }
    static var defaultModels: String { L("settings.ai_ask.ai_ask_settings.default_models") }
    static var autoSelectModel: String { L("settings.ai_ask.ai_ask_settings.auto_select_model") }
    static var autoSelectDescription: String { L("settings.ai_ask.ai_ask_settings.auto_select_description") }
    static var simpleRequests: String { L("settings.ai_ask.ai_ask_settings.simple_requests") }
    static var complexRequests: String { L("settings.ai_ask.ai_ask_settings.complex_requests") }
    static var availableModels: String { L("settings.ai_ask.ai_ask_settings.available_models") }
    static var searchModels: String { L("settings.ai_ask.ai_ask_settings.search_placeholder") }
    static var availableProviders: String { L("settings.ai.available_providers") }
    static var auto: String { L("settings.ai_ask.ai_ask_settings.model_auto") }

    // MARK: - Settings - Memories
    static var memoriesTitle: String { L("settings.app_store.settings_memories.title") }
    static var noMemoriesYet: String { L("settings.app_store.settings_memories.hub_no_entries") }
    static var memoriesDescription: String { L("settings.app_store.settings_memories.section_description") }
    static var encryptionNotice: String { L("settings.app_settings_memories.encrypted_notice") }
    static var confirmDeleteMemory: String { L("settings.app_settings_memories.confirm_delete") }
    static var entries: String { L("settings.app_settings_memories.entries") }
    static var memoryKeyRequired: String { L("settings.app_settings_memories.item_key_required") }
    static var memoryValueRequired: String { L("settings.app_settings_memories.item_value_required") }
    static var memoryAuthenticationRequired: String { L("settings.app_settings_memories.authentication_required") }
    static var memorySaving: String { L("settings.app_settings_memories.saving") }

    // MARK: - Settings - Mates
    static var mateInstructions: String { L("settings.mates.system_prompt_heading") }
    static var mateShowFullPrompt: String { L("settings.mates.show_full_prompt") }
    static var mateHideFullPrompt: String { L("settings.mates.hide_full_prompt") }
    static func chatWithMate(_ mateName: String) -> String {
        LocalizationManager.shared.text("settings.mates.chat_with_mate", replacements: ["mate_name": mateName])
    }

    // MARK: - Settings - Apps
    static var showAllApps: String { L("settings.app_store.show_all_apps") }
    static var noAppsAvailable: String { L("settings.app_store.no_apps_available") }
    static var installed: String { L("settings.app_store.installed") }
    static var searchApps: String { L("settings.app_store.search_apps") }
    static var apps: String { L("settings.apps") }
    static var allAppsFilterAll: String { L("settings.app_store.all_apps.filter_all") }
    static var allAppsFilterSettingsMemories: String { L("settings.app_store.all_apps.filter_settings_memories") }
    static var allAppsFilterFocusModes: String { L("settings.app_store.all_apps.filter_focus_modes") }
    static var allAppsFilterSkills: String { L("settings.app_store.all_apps.filter_skills") }
    static var allAppsSortNewest: String { L("settings.app_store.all_apps.sort_by_newest") }
    static var allAppsSortName: String { L("settings.app_store.all_apps.sort_by_name_asc") }
    static var allAppsSortNameDesc: String { L("settings.app_store.all_apps.sort_by_name_desc") }
    static var appStoreSkills: String { L("settings.app_store.skills.title") }
    static var appStoreFocusModes: String { L("settings.app_store.focus_modes.title") }
    static var appStoreMemories: String { L("settings.app_store.settings_memories.title") }
    static var appStoreExamples: String { L("settings.app_store.skills.examples") }
    static var appStoreHowToUse: String { L("settings.app_store.skills.how_to_use") }
    static var appStoreProviders: String { L("settings.app_store.skills.providers") }
    static var appStoreModels: String { L("settings.app_store.skills.models") }
    static var appStoreSystemPrompt: String { L("settings.app_store.focus_modes.system_prompt") }
    static var appStoreShowFullInstruction: String { L("settings.app_store.focus_modes.show_full_instruction") }

    // MARK: - Settings - Security
    static var passkeys: String { L("settings.passkeys") }
    static var password: String { L("settings.password") }
    static var twoFactorAuth: String { L("settings.two_factor_auth") }
    static var recoveryKey: String { L("settings.recovery_key") }
    static var activeSessions: String { L("settings.sessions") }
    static var pairNewDevice: String { L("settings.sessions.pair_initiate_title") }
    static var logoutAllSessions: String { L("settings.logout_all") }
    static var addPasskey: String { L("settings.passkeys.add") }
    static var setup2FA: String { L("settings.two_factor_auth.setup") }
    static var disable2FA: String { L("settings.two_factor_auth.disable") }
    static var regenerateRecoveryKey: String { L("settings.recovery_key.regenerate") }
    static var accountSecurityRequestFailed: String { L("common.error") }
    static var accountSecurityMissingData: String { L("settings.security.auth_description") }
    static var passkeyUnknownDevice: String { L("settings.sessions.unknown_device") }
    static var passkeyAddedSuccessfully: String { L("common.success") }
    static var passkeyDeletedSuccessfully: String { L("common.success") }
    static var passkeyDeleteTitle: String { L("common.delete") }
    static var passkeyDeleteDescription: String { L("settings.security.auth_description") }
    static var passkeyInvalidChallenge: String { L("common.error") }
    static var passkeyRegistrationFailed: String { L("common.error") }
    static var passkeyPRFRequired: String { L("settings.security.passkey_prompt") }
    static var twoFactorChangeApp: String { L("settings.security.tfa_change_app") }
    static var twoFactorResetBackupCodes: String { L("settings.security.tfa_reset_backup_codes") }
    static var twoFactorBackupCodes: String { L("settings.security.tfa_backup_codes") }
    static var twoFactorCodesStored: String { L("settings.security.tfa_backup_codes_description") }
    static var sessionRemove: String { L("settings.sessions.remove") }
    static var sessionLogoutOthers: String { L("settings.sessions.logout_all_others") }
    static var sessionConfirmRemove: String { L("settings.sessions.confirm_remove") }
    static var sessionConfirmLogoutOthers: String { L("settings.sessions.confirm_logout_others") }
    static var sessionConfirmLogoutAll: String { L("settings.sessions.confirm_logout_all") }
    static var currentEmail: String { L("settings.account.email.current_email") }
    static var newEmailPlaceholder: String { L("settings.account.email.new_email_placeholder") }
    static var sendEmailChangeCode: String { L("settings.account.email.send_change_code") }
    static var verifyEmailChangeCode: String { L("settings.account.email.verify_change_code") }
    static var confirmEmailChange: String { L("settings.account.email.confirm_change") }
    static var emailChangeCodeSent: String { L("settings.account.email.change_code_sent") }
    static var emailChangeCodeVerified: String { L("settings.account.email.change_code_verified") }
    static var emailChangeSuccess: String { L("settings.account.email.change_success") }
    static var choosePhoto: String { L("settings.account.profile_picture.upload") }
    static var photoUploading: String { L("settings.account.profile_picture.uploading") }
    static var photoUpdated: String { L("settings.account.profile_picture.upload_success") }
    static var photoUploadError: String { L("settings.account.profile_picture.upload_error") }
    static var photoFileTooLarge: String { L("settings.account.profile_picture.file_too_large") }
    static var photoWrongFormat: String { L("settings.account.profile_picture.wrong_format") }
    static var photoRejected: String { L("settings.profile_image_not_allowed") }
    static var accountDeleted: String { L("settings.account_deleted") }
    static var storageLoading: String { L("settings.storage.storage_loading") }
    static var storageError: String { L("settings.storage.storage_error") }
    static var storageBreakdown: String { L("settings.storage.storage_breakdown_title") }
    static var storageNoFiles: String { L("settings.storage.storage_files_empty") }
    static var storageDeleteFile: String { L("settings.storage.storage_delete_file") }
    static var storageDeleteConfirm: String { L("settings.storage.storage_delete_confirm_single") }
    static var chatStatistics: String { L("settings.account.chats.description") }
    static var chatTotal: String { L("common.chats") }
    static var chatDeleteOld: String { L("settings.account.chats.delete_section_title") }
    static var preview: String { L("common.preview") }
    static var untitled: String { L("common.untitled") }
    static var chatDeleteConfirm: String { L("settings.account.chats.delete_confirm_desc") }
    static var chatDeleteSuccess: String { L("settings.account.chats.delete_success") }
    static var chatOlderThan: String { L("settings.account.chats.delete_older_than") }

    static func passkeyAdded(_ date: String) -> String {
        "\(L("settings.sessions.logged_in")): \(date)"
    }

    static func passkeyLastUsed(_ date: String) -> String {
        "\(L("settings.sessions.logged_in")): \(date)"
    }

    static func storageFilesCount(_ count: Int) -> String {
        LocalizationManager.shared.text("settings.storage.storage_files_count", replacements: ["count": "\(count)"])
    }

    static func storageCategory(_ category: String) -> String {
        L("settings.storage.storage_category_\(category)")
    }

    static func chatDays(_ count: Int) -> String {
        let key = count == 1
            ? "settings.account.chats.delete_option_1d"
            : "settings.account.chats.delete_option_\(count)d"
        return L(key)
    }

    // MARK: - Settings - Privacy
    static var hidePersonalData: String { L("settings.hide_personal_data") }
    static var privacyHidePersonalData: String { L("settings.privacy.hide_personal_data") }
    static var privacyHidePersonalDataChats: String { L("settings.privacy.hide_personal_data.chats") }
    static var privacyHidePersonalDataDescription: String { L("settings.privacy.hide_personal_data.description") }
    static var privacyContacts: String { L("settings.privacy.contacts") }
    static var privacyAddName: String { L("settings.privacy.add_name") }
    static var privacyAddAddress: String { L("settings.privacy.add_address") }
    static var privacyAddBirthday: String { L("settings.privacy.add_birthday") }
    static var privacyForEveryone: String { L("settings.privacy.for_everyone") }
    static var privacyEmailAddresses: String { L("settings.privacy.email_addresses") }
    static var privacyPhoneNumbers: String { L("settings.privacy.phone_numbers") }
    static var privacyCreditCardNumbers: String { L("settings.privacy.credit_card_numbers") }
    static var privacyIbanBankAccount: String { L("settings.privacy.iban_bank_account") }
    static var privacyTaxIdVat: String { L("settings.privacy.tax_id_vat") }
    static var privacyCryptoWallets: String { L("settings.privacy.crypto_wallets") }
    static var privacySocialSecurityNumbers: String { L("settings.privacy.social_security_numbers") }
    static var privacyPassportNumbers: String { L("settings.privacy.passport_numbers") }
    static var privacyForDevelopers: String { L("settings.privacy.for_developers") }
    static var privacyApiKeys: String { L("settings.privacy.api_keys") }
    static var privacyJwtTokens: String { L("settings.privacy.jwt_tokens") }
    static var privacyPrivateKeys: String { L("settings.privacy.private_keys") }
    static var privacyGenericSecrets: String { L("settings.privacy.generic_secrets") }
    static var privacyIpAddresses: String { L("settings.privacy.ip_addresses") }
    static var privacyMacAddresses: String { L("settings.privacy.mac_addresses") }
    static var privacyUserAtHostname: String { L("settings.privacy.user_at_hostname") }
    static var privacyHomeFolder: String { L("settings.privacy.home_folder") }
    static var privacyCustom: String { L("settings.privacy.custom") }
    static var privacyAddCustomEntry: String { L("settings.privacy.add_custom_entry") }
    static var privacyFormTitle: String { L("settings.privacy.form.title") }
    static var privacyFormTextToHide: String { L("settings.privacy.form.text_to_hide") }
    static var privacyFormReplaceWith: String { L("settings.privacy.form.replace_with") }
    static var privacyEncryptionNote: String { L("settings.privacy.encryption_note") }
    static var enhancedPIIModelVerifying: String { L("settings.privacy.enhanced_pii_model.verifying") }
    static var enhancedPIIModelRegexFallback: String { L("settings.privacy.enhanced_pii_model.regex_fallback") }
    static var enhancedPIIModelDiagnosticTitle: String { L("settings.privacy.enhanced_pii_model.diagnostic_title") }
    static var enhancedPIIModelDiagnosticDescription: String { L("settings.privacy.enhanced_pii_model.diagnostic_description") }
    static var enhancedPIIModelTitle: String { L("settings.privacy.enhanced_pii_model.title") }
    static var enhancedPIIModelDescription: String { L("settings.privacy.enhanced_pii_model.description") }
    static var enhancedPIIModelDownload: String { L("settings.privacy.enhanced_pii_model.download") }
    static var enhancedPIIModelDownloading: String { L("settings.privacy.enhanced_pii_model.downloading") }
    static var enhancedPIIModelReady: String { L("settings.privacy.enhanced_pii_model.ready") }
    static var enhancedPIIModelUpdateAvailable: String { L("settings.privacy.enhanced_pii_model.update_available") }
    static var enhancedPIIModelFailed: String { L("settings.privacy.enhanced_pii_model.failed") }
    static var enhancedPIIModelRemove: String { L("settings.privacy.enhanced_pii_model.remove") }
    static var enhancedPIIModelStatusNotDownloaded: String { L("settings.privacy.enhanced_pii_model.status_not_downloaded") }
    static var enhancedPIIModelStatusLocalReady: String { L("settings.privacy.enhanced_pii_model.status_local_ready") }
    static var enhancedPIIModelComposerSuggestionTitle: String { L("settings.privacy.enhanced_pii_model.composer_suggestion_title") }
    static var enhancedPIIModelComposerSuggestionDescription: String { L("settings.privacy.enhanced_pii_model.composer_suggestion_description") }
    static var autoDeleteChats: String { L("settings.privacy.auto_deletion") }
    static var shareDebugLogs: String { L("settings.privacy.debug_logging_title") }
    static var never: String { L("common.never") }
    static var none: String { L("settings.privacy.connected_accounts.none") }
    static var privacyOpenPolicy: String { L("settings.privacy.open_privacy_policy") }
    static var privacyAnonymization: String { L("settings.privacy.anonymization") }
    static var privacyConnectedAccounts: String { L("settings.privacy.connected_accounts.title") }
    static var privacyConnectedAccountsSubtitle: String { L("settings.privacy.connected_accounts.subtitle") }
    static var privacyConnectedAccountsDescription: String { L("settings.privacy.connected_accounts.description") }
    static var privacyConnectedAccountsEmpty: String { L("settings.privacy.connected_accounts.empty") }
    static var privacyConnectedAccountsLoadError: String { L("settings.privacy.connected_accounts.load_error") }
    static var privacyConnectedAccountsList: String { L("settings.privacy.connected_accounts.accounts") }
    static var privacyProviderGoogleCalendar: String { L("settings.privacy.connected_accounts.provider_google_calendar") }
    static var privacyCapabilityRead: String { L("settings.app_store.connected_accounts.capability_read") }
    static var privacyCapabilityWrite: String { L("settings.app_store.connected_accounts.capability_write") }
    static var privacyMapsLocation: String { L("settings.privacy.maps_location") }
    static var privacyNearbyByDefault: String { L("settings.privacy.nearby_by_default") }
    static var privacyAutoDeletion: String { L("settings.privacy.auto_deletion") }
    static var privacyAutoDeletionChats: String { L("settings.privacy.auto_deletion.chats") }
    static var privacyAutoDeletionChatsDescription: String { L("settings.privacy.auto_deletion.chats.description") }
    static var privacyAutoDeletionFiles: String { L("settings.privacy.auto_deletion.files") }
    static var privacyAutoDeletionFilesValue: String { L("settings.privacy.auto_deletion.files.value") }
    static var privacyAutoDeletionUsageData: String { L("settings.privacy.auto_deletion.usage_data") }
    static var privacyAutoDeletionUsageDataValue: String { L("settings.privacy.auto_deletion.usage_data.value") }
    static var privacyAutoDeletionComplianceLogs: String { L("settings.privacy.auto_deletion.compliance_logs") }
    static var privacyAutoDeletionComplianceLogsValue: String { L("settings.privacy.auto_deletion.compliance_logs.value") }
    static var privacyAutoDeletionInvoices: String { L("settings.privacy.auto_deletion.invoices") }
    static var privacyAutoDeletionInvoicesValue: String { L("settings.privacy.auto_deletion.invoices.value") }
    static var privacyAutoDeletionComplianceNote: String { L("settings.privacy.auto_deletion.compliance_note") }
    static var privacyAutoDeletionSelectPeriod: String { L("settings.privacy.auto_deletion.select_period") }
    static var privacyPeriod30Days: String { L("settings.privacy.auto_deletion.period.30_days") }
    static var privacyPeriod60Days: String { L("settings.privacy.auto_deletion.period.60_days") }
    static var privacyPeriod90Days: String { L("settings.privacy.auto_deletion.period.90_days") }
    static var privacyPeriod6Months: String { L("settings.privacy.auto_deletion.period.6_months") }
    static var privacyPeriod1Year: String { L("settings.privacy.auto_deletion.period.1_year") }
    static var privacyPeriod2Years: String { L("settings.privacy.auto_deletion.period.2_years") }
    static var privacyPeriod5Years: String { L("settings.privacy.auto_deletion.period.5_years") }
    static var privacyPeriodNever: String { L("settings.privacy.auto_deletion.period.never") }
    static var privacyStabilityLogsTitle: String { L("settings.privacy.stability_logs_title") }
    static var privacyStabilityLogsDescription: String { L("settings.privacy.stability_logs_description") }
    static var privacyStabilityLogsToggle: String { L("settings.privacy.stability_logs_toggle_label") }
    static var privacyStabilityLogsNote: String { L("settings.privacy.stability_logs_privacy_note") }
    static var privacyDebugLoggingTitle: String { L("settings.privacy.debug_logging_title") }
    static var privacyDebugLoggingDescription: String { L("settings.privacy.debug_logging_description") }
    static var privacyDebugLoggingToggle: String { L("settings.privacy.debug_logging_toggle_label") }
    static var privacyDebugLoggingNeverCollected: String { L("settings.privacy.debug_logging_never_collected") }
    static var privacyShareDebugLogs: String { L("settings.privacy.share_debug_logs_title") }
    static var privacyShareDebugLogsAdminNotice: String { L("settings.privacy.share_debug_logs_admin_notice") }
    static var privacySaveError: String { L("settings.privacy.native.save_error") }
    static var privacyMasterKeyUnavailable: String { L("settings.privacy.native.master_key_unavailable") }
    static var privacyDebugSessionDescription: String { L("settings.privacy.native.debug_session.description") }
    static var privacyDebugSessionDuration: String { L("settings.privacy.native.debug_session.duration") }
    static var privacyDebugSessionStart: String { L("settings.privacy.native.debug_session.start") }
    static var privacyDebugSessionActivating: String { L("settings.privacy.native.debug_session.activating") }
    static var privacyDebugSessionActive: String { L("settings.privacy.native.debug_session.active") }
    static var privacyDebugSessionId: String { L("settings.privacy.native.debug_session.id") }
    static var privacyDebugSessionShareHint: String { L("settings.privacy.native.debug_session.share_hint") }
    static var privacyDebugSessionStop: String { L("settings.privacy.native.debug_session.stop") }
    static var privacyDebugSessionStopping: String { L("settings.privacy.native.debug_session.stopping") }
    static var privacyDebugSessionNoExpiry: String { L("settings.privacy.native.debug_session.no_expiry") }
    static var privacyDebugSessionError: String { L("settings.privacy.native.debug_session.error") }
    static var privacyDebugDuration5Minutes: String { L("settings.privacy.native.debug_session.duration_5m") }
    static var privacyDebugDuration1Hour: String { L("settings.privacy.native.debug_session.duration_1h") }
    static var privacyDebugDuration3Days: String { L("settings.privacy.native.debug_session.duration_3d") }
    static var privacyDebugDuration7Days: String { L("settings.privacy.native.debug_session.duration_7d") }
    static var privacyDebugDurationNoLimit: String { L("settings.privacy.native.debug_session.duration_none") }
    static func privacyDebugSessionMinutesRemaining(_ count: Int) -> String {
        LocalizationManager.shared.text("settings.privacy.native.debug_session.minutes_remaining", replacements: ["count": "\(count)"])
    }
    static func privacyDebugSessionHoursRemaining(_ count: Int) -> String {
        LocalizationManager.shared.text("settings.privacy.native.debug_session.hours_remaining", replacements: ["count": "\(count)"])
    }
    static func privacyDebugSessionDaysRemaining(_ count: Int) -> String {
        LocalizationManager.shared.text("settings.privacy.native.debug_session.days_remaining", replacements: ["count": "\(count)"])
    }

    // MARK: - Settings - Modes
    static var learningModeActive: String { L("settings.learning_mode_active") }
    static var learningModeInactive: String { L("settings.learning_mode_inactive") }
    static var learningModeLoadError: String { L("settings.learning_mode_load_error") }
    static var learningModeSaveError: String { L("settings.learning_mode_save_error") }
    static var learningModeActiveDetail: String { L("settings.learning_mode_active_detail") }
    static var learningModeInactiveDetail: String { L("settings.learning_mode_inactive_detail") }
    static var learningModeGuestActiveDetail: String { L("settings.learning_mode_guest_active_detail") }
    static var learningModeGuestInactiveDetail: String { L("settings.learning_mode_guest_inactive_detail") }
    static var learningModeAgeGroup: String { L("settings.learning_mode_age_group_label") }
    static var learningModeAgeUnder10: String { L("settings.learning_mode_age_under_10") }
    static var learningModeAge10To12: String { L("settings.learning_mode_age_10_12") }
    static var learningModeAge13To15: String { L("settings.learning_mode_age_13_15") }
    static var learningModeAge16To18: String { L("settings.learning_mode_age_16_18") }
    static var learningModeAgeAdult: String { L("settings.learning_mode_age_adult") }
    static var learningModeEnablePasscodeLabel: String { L("settings.learning_mode_enable_passcode_label") }
    static var learningModeDisablePasscodeLabel: String { L("settings.learning_mode_disable_passcode_label") }
    static var learningModeEnablePasscodePlaceholder: String { L("settings.learning_mode_enable_passcode_placeholder") }
    static var learningModeDisablePasscodePlaceholder: String { L("settings.learning_mode_disable_passcode_placeholder") }
    static var learningModeEnableButton: String { L("settings.learning_mode_enable_button") }
    static var learningModeDisableButton: String { L("settings.learning_mode_disable_button") }
    static var learningModeLocked: String { L("settings.learning_mode_locked") }
    static var learningModeShortenedNotice: String { L("learning_mode_shortened_notice") }
    static var incognitoExplainerDescription: String { L("settings.incognito_explainer_description") }
    static var incognitoExplainerDeviceSpecific: String { L("settings.incognito_explainer_feature_device_specific") }
    static var incognitoExplainerNotStored: String { L("settings.incognito_explainer_feature_not_stored") }
    static var incognitoExplainerSessionOnly: String { L("settings.incognito_explainer_feature_session_only") }
    static var incognitoExplainerNoRecovery: String { L("settings.incognito_explainer_feature_no_recovery") }
    static var incognitoExplainerWarningTitle: String { L("settings.incognito_explainer_warning_title") }
    static var incognitoExplainerWarningProviders: String { L("settings.incognito_explainer_warning_providers") }
    static var incognitoExplainerWarningPersonalInfo: String { L("settings.incognito_explainer_warning_personal_info") }
    static var incognitoExplainerUnderstood: String { L("settings.incognito_explainer_understood") }

    static func learningModeAttemptsRemaining(_ count: Int) -> String {
        LocalizationManager.shared.text(
            "settings.learning_mode_attempts_remaining",
            replacements: ["count": "\(count)"]
        )
    }

    // MARK: - Settings - Billing
    static var billingCredits: String { L("settings.billing.credits") }
    static var buyCredits: String { L("settings.buy_credits") }
    static var autoTopUp: String { L("settings.auto_topup") }
    static var purchaseHistory: String { L("settings.billing.purchase_history") }
    static var invoices: String { L("settings.invoices") }
    static var giftCards: String { L("settings.gift_cards") }
    static var getFreeCredits: String { L("settings.billing.get_free_credits") }
    static var referralCode: String { L("settings.billing.referral_code") }
    static var referralQrLabel: String { L("settings.billing.referral_qr_label") }

    static func referralIntro(referrerCredits: String, referredCredits: String) -> String {
        LocalizationManager.shared.text(
            "settings.billing.referral_intro",
            replacements: [
                "referrerCredits": referrerCredits,
                "referredCredits": referredCredits,
            ]
        )
    }

    static func referralProgress(count: String, max: String) -> String {
        LocalizationManager.shared.text(
            "settings.billing.referral_progress",
            replacements: ["count": count, "max": max]
        )
    }

    static var referralConditions: String { L("settings.billing.referral_conditions") }
    static var billingSupport: String { L("settings.billing.apple_support") }
    static var billingUsageDetails: String { L("settings.billing.apple_usage_details") }
    static var billingCreditPackages: String { L("settings.billing.credit_packages") }
    static var billingLoadingProducts: String { L("settings.billing.loading_products") }
    static var billingProcessingPurchase: String { L("settings.billing.processing_purchase") }
    static var billingVerifyingPurchase: String { L("settings.billing.verifying_with_server") }
    static var billingPurchaseComplete: String { L("settings.billing.purchase_complete") }
    static var billingRestorePurchases: String { L("settings.billing.restore_purchases") }
    static var billingLowBalanceAutoTopUp: String { L("settings.billing.low_balance_auto_topup") }
    static var billingLowBalanceDescription: String { L("settings.billing.low_balance_description") }
    static var billingWhenBelow: String { L("settings.billing.when_below") }
    static var billingTopUpPackage: String { L("settings.billing.topup_package") }
    static var billingNoInvoices: String { L("settings.billing.no_invoices") }
    static var billingDownloadInvoice: String { L("settings.billing.invoices_download_invoice") }
    static var billingDownloadCreditNote: String { L("settings.billing.invoices_download_credit_note") }
    static var billingExportUsage: String { L("settings.usage.export") }
    static var billingUsageOverview: String { L("settings.usage.tab_overview") }
    static var billingUsageChats: String { L("settings.usage.tab_chats") }
    static var billingUsageApps: String { L("settings.usage.tab_apps") }
    static var billingUsageAPI: String { L("settings.usage.tab_api") }
    static var billingRedeemGiftCard: String { L("settings.gift_cards.redeem") }
    static var billingPurchaseGiftCard: String { L("settings.gift_cards.buy") }
    static var billingGiftCardCode: String { L("settings.gift_cards.code") }
    static var billingRedeemedGiftCards: String { L("settings.gift_cards.redeemed") }
    static var billingPurchasedGiftCards: String { L("settings.billing.apple_purchased_gift_cards") }
    static var billingNoGiftCards: String { L("settings.billing.apple_no_gift_cards") }
    static var billingGiftCardPurchaseUnavailable: String { L("settings.billing.apple_gift_card_purchase_unavailable") }
    static var billingSupportContribution: String { L("settings.support.one_time") }
    static var billingSupportAmount: String { L("settings.billing.apple_support_amount") }
    static var billingCreateBankTransfer: String { L("settings.billing.apple_create_bank_transfer") }
    static var billingBankTransferDetails: String { L("settings.billing.bank_transfer_details") }
    static var billingTransferAmount: String { L("settings.billing.bank_transfer_amount") }
    static var billingTransferReference: String { L("settings.billing.bank_transfer_reference") }
    static var billingTransferIBAN: String { L("settings.billing.bank_transfer_iban") }
    static var billingTransferBIC: String { L("settings.billing.bank_transfer_bic") }
    static var billingInvalidSupportAmount: String { L("settings.billing.apple_invalid_support_amount") }
    static var billingFulfillmentDelayed: String { L("settings.billing.apple_fulfillment_delayed") }
    static var billingProductNotFound: String { L("settings.billing.apple_product_not_found") }
    static var billingUnknownUsage: String { L("settings.usage.unknown_activity") }

    static func billingCreditsAdded(_ credits: Int) -> String {
        LocalizationManager.shared.text(
            "settings.billing.apple_credits_count",
            replacements: ["credits": credits.formatted()]
        )
    }

    static func billingBankTransferReference(_ reference: String) -> String {
        LocalizationManager.shared.text(
            "settings.billing.apple_bank_transfer_reference",
            replacements: ["reference": reference]
        )
    }

    // MARK: - Settings - Report issue
    static var reportIssueDescription: String { L("settings.report_issue.description") }
    static var reportIssueTitleLabel: String { L("settings.report_issue.title_label") }
    static var reportIssueTitlePlaceholder: String { L("settings.report_issue.title_placeholder") }
    static var reportIssueTitleRequired: String { L("settings.report_issue.title_required") }
    static var reportIssueTitleTooShort: String { L("settings.report_issue.title_too_short") }
    static var reportIssueUserFlowLabel: String { L("settings.report_issue.user_flow_label") }
    static var reportIssueUserFlowPlaceholder: String { L("settings.report_issue.user_flow_placeholder") }
    static var reportIssueUserFlowHint: String { L("settings.report_issue.user_flow_hint") }
    static var reportIssueExpectedLabel: String { L("settings.report_issue.expected_behaviour_label") }
    static var reportIssueExpectedPlaceholder: String { L("settings.report_issue.expected_behaviour_placeholder") }
    static var reportIssueExpectedHint: String { L("settings.report_issue.expected_behaviour_hint") }
    static var reportIssueActualLabel: String { L("settings.report_issue.actual_behaviour_label") }
    static var reportIssueActualPlaceholder: String { L("settings.report_issue.actual_behaviour_placeholder") }
    static var reportIssueActualHint: String { L("settings.report_issue.actual_behaviour_hint") }
    static var reportIssueScreenshotLabel: String { L("settings.report_issue.screenshot_label") }
    static var reportIssueScreenshotHint: String { L("settings.report_issue.screenshot_hint") }
    static var reportIssueScreenshotUploadButton: String { L("settings.report_issue.screenshot_upload_button") }
    static var reportIssueScreenshotRemove: String { L("settings.report_issue.screenshot_remove") }
    static var reportIssueScreenshotSizeTooLarge: String { L("settings.report_issue.screenshot_size_too_large") }
    static var reportIssueScreenshotUploadFailed: String { L("settings.report_issue.screenshot_upload_failed") }
    static var reportIssueSubmitButton: String { L("settings.report_issue.submit_button") }
    static var reportIssueSubmitting: String { L("settings.report_issue.submitting") }
    static var reportIssueSuccess: String { L("settings.report_issue_success") }
    static var reportIssueIssueIdLabel: String { L("settings.report_issue.issue_id_label") }
    static var reportIssueError: String { L("settings.report_issue_error") }

    // MARK: - Connection banners
    static var offlineNotificationTitle: String { L("notifications.connection.offline_banner.title") }
    static var offlineBanner: String { L("notifications.connection.offline_banner") }
    static var reconnectingBanner: String { L("notifications.connection.reconnecting") }

    // MARK: - Settings - Notifications
    static var pushNotifications: String { L("settings.notifications.push") }
    static var chatMessages: String { L("settings.notifications.chat") }
    static var emailNotifications: String { L("settings.notifications.email") }
    static var backupReminders: String { L("settings.notifications.backup") }

    // MARK: - Settings - Interface
    static var theme: String { L("settings.interface.dark_mode") }
    static var language: String { L("settings.interface.language") }
    static var systemTheme: String { L("settings.interface.dark_mode.auto") }
    static var lightTheme: String { L("settings.interface.dark_mode.light") }
    static var darkTheme: String { L("settings.interface.dark_mode.dark") }

    // MARK: - Settings - Developers
    static var apiKeys: String { L("settings.api_keys") }
    static var devices: String { L("settings.devices") }
    static var webhooks: String { L("settings.developers_webhooks") }
    static var developerDeviceAccessTypeRestApi: String { L("settings.developers_devices_access_type_rest_api") }
    static var developerDeviceAccessTypeCli: String { L("settings.developers_devices_access_type_cli") }
    static var developerDeviceAccessTypeSdk: String { L("settings.developers_devices_access_type_sdk") }

    // MARK: - Settings - About
    static var privacyPolicy: String { L("legal.privacy.title") }
    static var termsOfService: String { L("legal.terms.title") }
    static var imprint: String { L("legal.imprint.title") }
    static var openSource: String { L("design_guidelines.maximum_good.open_source") }
    static var about: String { L("settings.app_store.provider_detail.about") }

    // MARK: - Settings - Newsletter
    static var newsletterSubscribe: String { L("settings.newsletter.subscribe") }
    static var newsletterUnsubscribe: String { L("settings.newsletter.unsubscribe") }

    // MARK: - Settings - Server (admin)
    static var serverAdmin: String { L("settings.server") }
    static var serverConnection: String { L("settings.server.connection") }
    static var serverConnectionDescription: String { L("settings.server.connection_description") }
    static var logs: String { L("settings.logs") }

    // MARK: - Auth
    static var login: String { L("login.login") }
    static var signup: String { L("signup.sign_up") }
    static var loginSignup: String { L("header.login_signup") }
    static var signupVersionTitle: String { L("signup.version_title") }
    static var logout: String { L("settings.logout") }
    static var logOut: String { L("settings.logout") }
    static var enterPassword: String { L("auth.enter_password") }
    static var forgotPassword: String { L("auth.forgot_password") }
    static var loginWithPasskey: String { L("auth.login_with_passkey") }
    static var loginWithPassword: String { L("auth.login_with_password") }
    static var loginWithRecoveryKey: String { L("auth.login_with_recovery_key") }
    static var twoFactorRequired: String { L("auth.two_factor_required") }
    static var invalidCredentials: String { L("auth.invalid_credentials") }
    static var loginButton: String { L("login.login_button") }
    static var loginFailed: String { L("login.login_failed") }
    static var passwordPlaceholder: String { L("login.password_placeholder") }
    static var twoFactorCodePlaceholder: String { L("login.2fa_code_placeholder") }
    static var loginWithAnotherAccount: String { L("login.login_with_another_account") }
    static var loginWithBackupCode: String { L("login.login_with_backup_code") }
    static var loginWithTfaApp: String { L("login.login_with_tfa_app") }
    static var backupCodeIsSingleUse: String { L("login.backup_code_is_single_use") }
    static var emailOrPasswordWrong: String { L("login.email_or_password_wrong") }
    static var codeWrong: String { L("login.code_wrong") }
    static var enterOneTimeCode: String { L("signup.enter_one_time_code") }
    static var enterBackupCode: String { L("login.enter_backup_code") }
    static var stayLoggedIn: String { L("login.stay_logged_in") }
    static var toChatToYour: String { L("login.to_chat_to_your") }
    static var digitalTeamMates: String { L("login.digital_team_mates") }
    static var emailPlaceholder: String { L("login.email_placeholder") }
    static var atMissing: String { L("signup.at_missing") }
    static var domainEndingMissing: String { L("signup.domain_ending_missing") }
    static var cantLogin: String { L("login.cant_login") }
    static var yourTfaApp: String { L("login.your_tfa_app") }
    static var checkYourTfaApp: String {
        LocalizationManager.shared.text("login.check_your_2fa_app", replacements: ["tfa_app": yourTfaApp])
    }

    // MARK: - Pair login
    static var pairWaiting: String { L("settings.sessions.pair_waiting") }
    static var pairGenerating: String { L("settings.sessions.pair_generating") }
    static var pairExpired: String { L("settings.sessions.pair_expired") }
    static var pairRefresh: String { L("settings.sessions.pair_refresh") }
    static var pairCopyLink: String { L("settings.sessions.pair_copy_link") }
    static var pairCopied: String { L("settings.sessions.pair_copied") }
    static var pairUrlLabel: String { L("settings.sessions.pair_url_label") }
    static var pairConnectAppleWatchTitle: String { L("settings.sessions.pair_connect_apple_watch_title") }
    static var pairConnectAppleWatchDescription: String { L("settings.sessions.pair_connect_apple_watch_description") }
    static func pairWatchLoginServerMismatch(watchServer: String, phoneServer: String) -> String {
        LocalizationManager.shared.text(
            "settings.sessions.pair_watch_login_server_mismatch",
            replacements: ["watch_server": watchServer, "phone_server": phoneServer]
        )
    }
    static var pairApproveWatchLogin: String { L("settings.sessions.pair_approve_watch_login") }
    static var pairAutoLogoutLabel: String { L("settings.sessions.pair_confirm_auto_logout_label") }
    static var pairAutoLogoutNone: String { L("settings.sessions.pair_auto_logout_none") }
    static var pairAutoLogout30m: String { L("settings.sessions.pair_auto_logout_30m") }
    static var pairAutoLogout1h: String { L("settings.sessions.pair_auto_logout_1h") }
    static var pairAutoLogout4h: String { L("settings.sessions.pair_auto_logout_4h") }
    static var pairAutoLogout8h: String { L("settings.sessions.pair_auto_logout_8h") }
    static var pairAutoLogout24h: String { L("settings.sessions.pair_auto_logout_24h") }
    static var pairStepUpDescription: String { L("settings.sessions.pair_step_up_description") }
    static var pairWatchLoginApproved: String { L("settings.sessions.pair_watch_login_approved") }
    static var pairScanDescription: String { L("settings.sessions.pair_initiate_description") }
    static var pairingQRCode: String { L("settings.sessions.pair_show_qr_code") }
    static var devicePaired: String { L("settings.sessions.pair_complete_success") }
    static var authorizeDevice: String { L("settings.sessions.pair_confirm_title") }
    static var deviceWantsLogin: String { L("settings.sessions.pair_confirm_requesting_device") }
    static var device: String { L("settings.devices") }
    static var location: String { L("settings.sessions.unknown_location") }
    static var deny: String { L("settings.sessions.pair_confirm_deny") }
    static var allow: String { L("settings.sessions.pair_confirm_allow") }
    static var enterThisPin: String { L("settings.sessions.pair_confirm_show_pin") }
    static var pairPinExpires: String { L("settings.sessions.pair_confirm_pin_hint") }
    static var confirmPairing: String { L("settings.sessions.pair_confirm_title") }
    static var pairingCode: String { L("settings.sessions.pair_code_label") }
    // Web currently renders this label as literal copy in SettingsSessionsPairInitiate.svelte.
    static var pairScanCode: String { "Scan code:" }
    static var pairEnterPinTitle: String { L("settings.sessions.pair_enter_pin_title") }
    static var pairEnterPinDescription: String { L("settings.sessions.pair_enter_pin_description") }
    static var pairPinPlaceholder: String { L("settings.sessions.pair_pin_placeholder") }
    static var pairLogin: String { L("settings.sessions.pair_login") }
    static var pairLoggingIn: String { L("settings.sessions.pair_logging_in") }
    static var pairPinLocked: String { L("settings.sessions.pair_pin_locked") }
    static func pairPinError(attempts: String) -> String {
        LocalizationManager.shared.text("settings.sessions.pair_pin_error", replacements: ["n": attempts])
    }

    // MARK: - Enter message / action buttons (ActionButtons.svelte)
    static var attachFiles: String { L("enter_message.attachments.attach_files") }
    static var shareLocation: String { L("enter_message.attachments.share_location") }
    static var sketchAction: String { L("enter_message.attachments.sketch") }
    static var takePhoto: String { L("enter_message.attachments.take_photo") }
    static var enterFullscreen: String { L("enter_message.fullscreen.enter_fullscreen") }
    static var exitFullscreen: String { L("enter_message.fullscreen.exit_fullscreen") }
    static var recordAudio: String { L("enter_message.attachments.record_audio") }
    static var recordingActive: String { L("enter_message.record_audio.recording") }
    static var recordingShortcuts: String { L("enter_message.record_audio.enter_to_finish_escape_to_cancel") }
    static var pressAndHoldToRecord: String { L("enter_message.record_audio.press_and_hold_reminder") }
    static var releaseToFinishRecording: String { L("enter_message.record_audio.release_to_finish") }
    static var pressEnterToFinishRecording: String { L("enter_message.record_audio.press_enter_to_finish") }
    static var slideLeftToCancelRecording: String { L("enter_message.record_audio.slide_left_to_cancel") }
    static var pressEscToCancelRecording: String { L("enter_message.record_audio.press_esc_to_cancel") }
    static var finishRecording: String { L("enter_message.record_audio.finish") }
    static var cancelRecording: String { L("enter_message.record_audio.cancel") }
    static var microphoneBlocked: String { L("enter_message.record_audio.microphone_blocked") }
    static var allowMicrophoneAccess: String { L("enter_message.record_audio.allow_microphone_access") }
    static var getLocation: String { L("enter_message.location.get_location") }
    static var selectedLocation: String { L("enter_message.location.selected_location") }
    static var locationSelect: String { L("enter_message.location.select") }
    static var preciseLocation: String { L("enter_message.location.precise") }
    static var enterMessagePlaceholder: String { L("enter_message.placeholder.touch") }
    static var waitingForUpload: String { L("enter_message.waiting_for_upload") }
    static var uploadProgressProcessing: String { L("enter_message.upload_progress.processing") }
    static var uploadProgressTranscribing: String { L("enter_message.upload_progress.transcribing") }
    static var uploadProgressError: String { L("enter_message.upload_progress.error") }
    static func uploadProgressUploading(percent: String) -> String {
        LocalizationManager.shared.text("enter_message.upload_progress.uploading", replacements: ["percent": percent])
    }
    static var piiBannerTitle: String { L("enter_message.pii.banner_title") }
    static var piiUndoAll: String { L("enter_message.pii.undo_all") }
    static var piiUndoAllShort: String { L("enter_message.pii.undo_all_short") }
    static func piiBannerDescription(summary: String) -> String {
        LocalizationManager.shared.text("enter_message.pii.banner_description", replacements: ["summary": summary])
    }

    // MARK: - Embeds
    static var audioRecording: String { L("app_skills.audio.transcribe.audio_recording") }
    static var audioRecordingDescription: String { L("app_skills.audio.transcribe.description") }
    static var audioTranscriptUnavailable: String { L("app_skills.audio.transcribe.no_transcript") }
    static var audioAutoCorrecting: String { L("app_skills.audio.transcribe.auto_correcting") }
    static var voiceRecording: String { audioRecording }
    static var transcription: String { L("app_skills.audio.transcribe.edit_transcript") }
    static func audioTranscribedBy(model: String) -> String {
        LocalizationManager.shared.text(
            "app_skills.audio.transcribe.transcribed_by",
            replacements: ["model": model]
        )
    }
    static var play: String { L("audio.play") }
    static var pause: String { L("audio.pause") }
    static var locationNearby: String { L("embeds.maps_location.nearby") }
    static var openVideo: String { L("embed.open_video") }
    static var openInBrowser: String { L("embed.open_in_browser") }
    static var loadPDF: String { L("embed.load_pdf") }
    static var decryptingPDF: String { L("embed.decrypting_pdf") }
    static var snippets: String { L("embeds.snippets") }
    static var viaBraveSearch: String { L("embeds.via_brave_search") }
    static var via: String { L("embeds.via") }
    static var videoGetTranscript: String { L("app_skills.videos.get_transcript") }
    static var transcriptYouTubeVideo: String { L("embeds.youtube_video") }
    static var transcriptVia: String { L("embeds.via") }
    static var transcriptWords: String { L("embeds.document_word_plural") }
    static var transcriptNoResults: String { L("embeds.search_no_results") }
    static var searchFailed: String { L("embeds.search_failed") }
    static var embedStoredEncrypted: String { L("embeds.stored_encrypted") }
    static var embedClickToShowDetails: String { L("embeds.click_to_show_details") }
    static var embedTapToShowDetails: String { L("embeds.tap_to_show_details") }
    static var genericProcessingError: String { L("chat.an_error_occured") }
    static var chatStorageMissingAttachmentContent: String { L("chat.send_storage_errors.missing_attachment_content") }
    static var chatStorageStaleAttachmentReference: String { L("chat.send_storage_errors.stale_attachment_reference") }
    static var chatStorageChangedAttachmentReference: String { L("chat.send_storage_errors.changed_attachment_reference") }
    static var chatStorageRetryContextChanged: String { L("chat.send_storage_errors.retry_context_changed") }
    static var imageSearchViewSource: String { L("embeds.image_search.view_source") }
    static var imageSearchOpenImage: String { L("embeds.image_search.open_image") }
    static var imageGenerateGeneratedBy: String { L("embeds.image_generate.generated_by") }
    static var imageGenerateGeneratingVia: String { L("embeds.image_generate.generating_via") }
    static var copy: String { L("common.copy") }
    static var download: String { L("common.download") }
    static var suggestionsExploreNext: String { L("chat.suggestions.explore_next") }
    static var composerSearchEmbed: String { L("chat.suggestions.embed_result") }
    static var composerSearchSkillResult: String { L("chat.suggestions.skill_result") }
    static var composerRelatedChats: String { L("chat.suggestions.related_chats") }
    static var composerSuggestionsNoMatch: String { L("chat.suggestions.filter_no_match") }
    static var suggestionsHeader: String { L("chat.suggestions.header_tap") }
    static var codeRun: String { L("app_skills.code.run") }
    static var codeSearchRepos: String { L("app_skills.code.search_repos") }
    static var codeRunCode: String { L("app_skills.code.run_code") }
    static var codeRunOutput: String { L("app_skills.code.run.output") }
    static var codeRunViewCode: String { L("app_skills.code.run.view_code") }
    static var codeRunAgain: String { L("app_skills.code.run.again") }
    static var codeRunAskFollowup: String { L("app_skills.code.run.ask_followup") }
    static var codeRunCopyOutput: String { L("app_skills.code.run.copy_output") }
    static var codeRunOutputCopied: String { L("app_skills.code.run.output_copied") }
    static var codeRunOutputCopyFailed: String { L("app_skills.code.run.output_copy_failed") }
    static var codeRunStop: String { L("app_skills.code.run.stop") }
    static var codeRunCancelling: String { L("app_skills.code.run.cancelling_button") }
    static var codeRunShowOutput: String { L("app_skills.code.run.show_output") }
    static var codeRunHideOutput: String { L("app_skills.code.run.hide_output") }
    static var codeRunRequiredFile: String { L("app_skills.code.run.required_file") }
    static var pcbSchematicTitle: String { L("embeds.electronics.pcb_schematic.title") }
    static var pcbSchematicPrepareFiles: String { L("embeds.electronics.pcb_schematic.prepare_files") }
    static var pcbSchematicArtifacts: String { L("embeds.electronics.pcb_schematic.artifacts") }
    static var pcbSchematicLogs: String { L("embeds.electronics.pcb_schematic.logs") }
    static var pcbSchematicSafetyNote: String { L("embeds.electronics.pcb_schematic.safety_note") }
    static var reportBadAnswer: String { L("chat.report_bad_answer.button_text") }
    static var fitnessSearchLocations: String { L("app_skills.fitness.search_locations") }
    static var fitnessSearchClasses: String { L("app_skills.fitness.search_classes") }
    static var businessCompanyFinancials: String { L("app_skills.business.company_financials") }
    static var models3dResultTitle: String { L("embeds.models3d.search.result_title") }
    static var models3dFree: String { L("embeds.models3d.search.free") }
    static var models3dNoResults: String { L("embeds.models3d.search.no_results") }
    static var models3dOpenToView: String { L("embeds.models3d.search.open_to_view") }

    static func models3dResultsCount(_ count: Int) -> String {
        LocalizationManager.shared.text("embeds.models3d.search.results_count", replacements: ["count": "\(count)"])
    }

    static func models3dFilesCount(_ count: Int) -> String {
        LocalizationManager.shared.text("embeds.models3d.search.files_count", replacements: ["count": "\(count)"])
    }

    static func models3dOpenOnProvider(_ provider: String) -> String {
        LocalizationManager.shared.text("embeds.models3d.search.open_on_provider", replacements: ["provider": provider])
    }
    static var businessFinancialsNoResults: String { L("embeds.business.company_financials.no_results") }
    static var businessFinancialsOpenToView: String { L("embeds.business.company_financials.open_to_view") }
    static var businessFinancialResultTitle: String { L("embeds.business.company_financials.result_title") }
    static var businessFinancialRevenue: String { L("embeds.business.company_financials.revenue") }
    static var businessFinancialGrossProfit: String { L("embeds.business.company_financials.gross_profit") }
    static var businessFinancialOperatingIncome: String { L("embeds.business.company_financials.operating_income") }
    static var businessFinancialNetIncome: String { L("embeds.business.company_financials.net_income") }
    static var businessFinancialOperatingCashFlow: String { L("embeds.business.company_financials.operating_cash_flow") }
    static var businessFinancialAssets: String { L("embeds.business.company_financials.assets") }
    static var businessFinancialLiabilities: String { L("embeds.business.company_financials.liabilities") }
    static var businessFinancialEquity: String { L("embeds.business.company_financials.equity") }
    static var businessFinancialFiled: String { L("embeds.business.company_financials.filed") }
    static var businessFinancialAnnual: String { L("embeds.business.company_financials.annual") }
    static var businessFinancialQuarterly: String { L("embeds.business.company_financials.quarterly") }
    static var businessFinancialPeriod: String { L("embeds.business.company_financials.period") }
    static var businessFinancialMetrics: String { L("embeds.business.company_financials.metrics") }
    static var businessFinancialNoMetrics: String { L("embeds.business.company_financials.no_metrics") }
    static var businessFinancialSource: String { L("embeds.business.company_financials.source") }
    static var businessFinancialSecFiling: String { L("embeds.business.company_financials.sec_filing") }
    static var businessFinancialOpenFiling: String { L("embeds.business.company_financials.open_filing") }
    static var businessFinancialNotes: String { L("embeds.business.company_financials.notes") }
    static var businessFinancialNotAvailable: String { L("embeds.business.company_financials.not_available") }

    static func businessFinancialsResultsCount(_ count: Int) -> String {
        LocalizationManager.shared.text(
            "embeds.business.company_financials.results_count",
            replacements: ["count": "\(count)"]
        )
    }

    static func openOnProvider(_ provider: String) -> String {
        LocalizationManager.shared.text("embeds.open_on_provider", replacements: ["provider": provider])
    }

    static func bookOnProvider(_ provider: String) -> String {
        LocalizationManager.shared.text("embeds.book_on", replacements: ["provider": provider])
    }

    static func registerOnProvider(_ provider: String) -> String {
        LocalizationManager.shared.text("embeds.register_on_provider", replacements: ["provider": provider])
    }

    static var embedAddMemory: String { L("embeds.add_memory") }
    static var embedForgetMemory: String { L("embeds.forget_memory") }

    static var openGoogleFlights: String {
        L("embeds.open_google_flights")
    }

    static var getBookingLink: String {
        L("embeds.get_booking_link")
    }

    static var perNight: String { L("embeds.per_night") }
    static var total: String { L("embeds.total") }
    static var reviews: String { L("embeds.reviews") }
    static var freeCancellation: String { L("embeds.free_cancellation") }
    static var ecoCertified: String { L("embeds.eco_certified") }
    static var viewOnGoogleHotels: String { L("embeds.view_on_google_hotels") }
    static var zoomIn: String { L("sketchview.zoom_in") }
    static var zoomOut: String { L("sketchview.zoom_out") }
    static var resetZoom: String { L("sketchview.reset_zoom") }
    static var sketchPen: String { L("sketchview.pen") }
    static var sketchEraser: String { L("sketchview.eraser") }
    static var sketchUndo: String { L("sketchview.undo") }
    static var sketchClear: String { L("sketchview.clear") }
    static var sketchDone: String { L("sketchview.done") }
    static var mindMap: String { L("embeds.mindmaps.mindmap") }
    static var resultsViewMap: String { L("embeds.results_view.map") }
    static var resultsViewCalendar: String { L("embeds.results_view.calendar") }
    static var resultsViewFilter: String { L("embeds.results_view.filter") }
    static var resultsViewMinimum: String { L("embeds.results_view.minimum") }
    static var resultsViewMaximum: String { L("embeds.results_view.maximum") }
    static var resultsViewPreviousWeek: String { L("embeds.results_view.previous_week") }
    static var resultsViewNextWeek: String { L("embeds.results_view.next_week") }
    static func resultsViewWeekNumber(week: Int, year: Int) -> String {
        LocalizationManager.shared.text("embeds.results_view.week_number", replacements: ["week": "\(week)", "year": "\(year)"])
    }
    static var resultsViewAll: String { L("embeds.results_view.all") }
    static var resultsViewType: String { L("embeds.results_view.type") }
    static var resultsViewClearFilters: String { L("embeds.results_view.clear_filters") }
    static var resultsViewDepartureTime: String { L("embeds.results_view.departure_time") }
    static var resultsViewArrivalTime: String { L("embeds.results_view.arrival_time") }
    static var resultsViewDuration: String { L("embeds.results_view.duration") }
    static var resultsViewTransferTime: String { L("embeds.results_view.transfer_time") }
    static var resultsViewPrice: String { L("embeds.results_view.price") }
    static var resultsViewCarrier: String { L("embeds.results_view.carrier") }
    static var resultsViewProvider: String { L("embeds.results_view.provider") }
    static func resultsViewRemaining(visible: Int, total: Int) -> String {
        LocalizationManager.shared.text("embeds.results_view.remaining", replacements: ["visible": "\(visible)", "total": "\(total)"])
    }
    static var mindMapInvalidJSON: String { L("embeds.mindmaps.invalid_json") }
    static var mindMapInvalidContent: String { L("embeds.mindmaps.invalid_content") }
    static var mindMapValidationWarnings: String { L("embeds.mindmaps.validation_warnings") }
    static var mindMapSource: String { L("embeds.mindmaps.source") }

    static func mindMapCounts(nodes: Int, edges: Int) -> String {
        LocalizationManager.shared.text("embeds.mindmaps.counts", replacements: ["nodes": "\(nodes)", "edges": "\(edges)"])
    }

    static func mindMapExpand(_ label: String) -> String {
        LocalizationManager.shared.text("embeds.mindmaps.expand", replacements: ["label": label])
    }

    static func mindMapCollapse(_ label: String) -> String {
        LocalizationManager.shared.text("embeds.mindmaps.collapse", replacements: ["label": label])
    }

    static func dataFrom(_ date: String) -> String {
        LocalizationManager.shared.text("embeds.data_from", replacements: ["date": date])
    }

    static func moreResults(_ count: Int) -> String {
        LocalizationManager.shared.text("embeds.more_results", replacements: ["count": "\(count)"])
    }

    static func searchNoResults(for query: String) -> String {
        LocalizationManager.shared.text("embeds.search_no_results_for_query", replacements: ["query": query])
    }

    static func generatedBy(_ model: String) -> String {
        LocalizationManager.shared.text("chat.generated_by", replacements: ["model": model])
    }

    // MARK: - Notifications
    static var offline: String { L("notifications.offline") }
    static var reconnecting: String { L("notifications.reconnecting") }
    static var incognitoModeOn: String { L("notifications.incognito_on") }
    static var incognitoModeOff: String { L("notifications.incognito_off") }
    static var newMessageReceived: String { L("notifications.chat_message.new_message_received") }
    static var clickToRespond: String { L("notifications.click_to_respond") }
    static var incognitoDescription: String { L("settings.incognito.description") }

    // MARK: - Misc
    static var dailyInspiration: String { L("daily_inspiration.label") }
    static var dailyInspirationCTA: String { L("daily_inspiration.click_to_start_chat") }
    static var tapToExplore: String { L("common.tap_to_explore") }
    static var report: String { L("common.report") }
    static var send: String { L("common.send") }
    static var share: String { L("common.share") }
    static var shareChat: String { L("settings.share.share_chat") }
    static var shareEmbed: String { L("settings.share.share_embed") }
    static var sharingChatStatus: String { L("settings.share.sharing_chat_status") }
    static var sharingEmbedStatus: String { L("settings.share.sharing_embed_status") }
    static var shareDescription: String { L("settings.share.share_description") }
    static var shareEmbedDescription: String { L("settings.share.share_embed_description") }
    static var optionalShareSettings: String { L("settings.share.optional_settings") }
    static var sharePasswordProtection: String { L("settings.share.password_protection") }
    static var sharePasswordPlaceholder: String { L("settings.share.password_placeholder") }
    static var shareTimeLimit: String { L("settings.share.time_limit") }
    static var shareNoExpiration: String { L("settings.share.no_expiration") }
    static var shareOneMinute: String { L("settings.share.one_minute") }
    static var shareOneHour: String { L("settings.share.one_hour") }
    static var shareTwentyFourHours: String { L("settings.share.twenty_four_hours") }
    static var shareSevenDays: String { L("settings.share.seven_days") }
    static var shareFourteenDays: String { L("settings.share.fourteen_days") }
    static var shareThirtyDays: String { L("settings.share.thirty_days") }
    static var shareNinetyDays: String { L("settings.share.ninety_days") }
    static var shareCommunity: String { L("settings.share.share_with_community") }
    static var shareHighlights: String { L("settings.share.include_highlights") }
    static var shareSensitiveData: String { L("settings.share.include_sensitive_data") }
    static var shareQRCode: String { L("settings.share.qr_code") }
    static var shareChangeSettings: String { L("settings.share.change_settings") }
    static var shareClickToCopy: String { L("settings.share.click_to_copy") }
    static var shareLinkCopied: String { L("settings.share.link_copied") }
    static var shareUnshare: String { L("settings.share.unshare") }
    static var shareExpirationPrefix: String { L("settings.share.link_will_expire_in") }
    static var pin: String { L("common.pin") }
    static var unpin: String { L("common.unpin") }
    static var archive: String { L("common.archive") }
    static var hide: String { L("common.hide") }
    static var rename: String { L("common.rename") }
    static var stop: String { L("common.stop") }

    // MARK: - Chat banner (ChatHeader.svelte)
    static var creatingNewChat: String { L("chat.creating_new_chat") }
    static var exampleChatBadge: String { L("chat.header.example_chat") }
    static var draftBadge: String { L("enter_message.draft") }
    static var chatHeaderJustNow: String { L("chat.header.just_now") }
    static var incognitoModeActive: String { L("settings.incognito_mode_active") }

    static func chatHeaderMinutesAgo(count: Int) -> String {
        LocalizationManager.shared.text("chat.header.minutes_ago", replacements: ["count": "\(count)"])
    }
    static func chatHeaderStartedToday(time: String) -> String {
        LocalizationManager.shared.text("chat.header.started_today", replacements: ["time": time])
    }
    static func chatHeaderStartedYesterday(time: String) -> String {
        LocalizationManager.shared.text("chat.header.started_yesterday", replacements: ["time": time])
    }
    static func chatHeaderStartedOn(date: String, time: String) -> String {
        "\(date), \(time)"
    }

    // MARK: - Sidebar section headers
    static var introSection: String { L("activity.intro") }
    static var exampleChatsSection: String { L("activity.examples") }
    static var announcementsSection: String { L("activity.announcements") }
    static var legalSection: String { L("activity.legal") }
    static var showHiddenChats: String { L("chats.hidden_chats.show_hidden_chats") }

    // MARK: - Demo chats — intro
    static var teaserLine1: String { L("demo_chats.for_everyone.teaser_line1") }
    static var teaserLine2: String { L("demo_chats.for_everyone.teaser_line2") }
    static var teaserLine3: String { L("demo_chats.for_everyone.teaser_line3") }
    static var demoWhoDevTitle: String { L("demo_chats.who_develops_openmates.title") }
    static var demoWhoDevDescription: String { L("demo_chats.who_develops_openmates.description") }
    static var demoAnnouncementsV09Title: String { L("demo_chats.announcements_introducing_openmates_v09.title") }
    static var demoAnnouncementsV09Description: String { L("demo_chats.announcements_introducing_openmates_v09.description") }

    // MARK: - Legal chats
    static var legalPrivacyTitle: String { L("legal.privacy.title") }
    static var legalPrivacyDescription: String { L("metadata.legal_privacy.description") }
    static var legalTermsTitle: String { L("legal.terms.title") }
    static var legalTermsDescription: String { L("metadata.legal_terms.description") }
    static var legalImprintTitle: String { L("legal.imprint.title") }
    static var legalImprintDescription: String { L("metadata.legal_imprint.description") }

    // MARK: - Example chats
    static var exampleGiganticAirplanesTitle: String { L("example_chats.gigantic_airplanes.title") }
    static var exampleGiganticAirplanesSummary: String { L("example_chats.gigantic_airplanes.summary") }
    static var exampleArtemisMissionTitle: String { L("example_chats.artemis_ii_mission.title") }
    static var exampleArtemisMissionSummary: String { L("example_chats.artemis_ii_mission.summary") }
    static var exampleBeautifulHtmlTitle: String { L("example_chats.beautiful_single_page_html.title") }
    static var exampleBeautifulHtmlSummary: String { L("example_chats.beautiful_single_page_html.summary") }
    static var exampleEuChatControlTitle: String { L("example_chats.eu_chat_control_law.title") }
    static var exampleEuChatControlSummary: String { L("example_chats.eu_chat_control_law.summary") }
    static var exampleFlightsBerlinBangkokTitle: String { L("example_chats.flights_berlin_bangkok.title") }
    static var exampleFlightsBerlinBangkokSummary: String { L("example_chats.flights_berlin_bangkok.summary") }
    static var exampleCreativityDrawingTitle: String { L("example_chats.creativity_drawing_meetups_berlin.title") }
    static var exampleCreativityDrawingSummary: String { L("example_chats.creativity_drawing_meetups_berlin.summary") }

    // MARK: - Credits
    static func creditsAmount(_ amount: String) -> String {
        LocalizationManager.shared.text("settings.credits_amount", replacements: ["credits_amount": amount])
    }

    static func entriesCount(_ count: Int) -> String {
        "\(count) \(L("settings.app_settings_memories.entries"))"
    }

    // MARK: - Helper
    static func localized(_ key: String) -> String {
        L(key)
    }

    private static func L(_ key: String) -> String {
        LocalizationManager.shared.text(key)
    }
}

// MARK: - Workflow workspace
extension AppStrings {
    enum WorkflowBuilderCopy: String {
        case action_question, add_check, add_description, add_trigger, ask_ai_question
        case check, check_question, check_required, close, created, date_range, date_time
        case check_mode, exact_rule, ai_judgment, ai_check_question, ai_check_placeholder
        case select_output, compare_type, compare_value, `if`
        case operator_eq, operator_ne, operator_gt, operator_gte
        case operator_lt, operator_lte, operator_contains
        case delete_workflow, delete_run, delete_node, confirm_delete_node
        case `else`, `false`, draft, do_nothing, do_nothing_add_step
        case if_true, if_unsure, input, next_result, next_run, next_seven_days
        case new_workflow_placeholder, output, output_empty_list, output_type_object
        case show_output_fields, hide_output_fields, example, test_output
        case previous_result, result_position, run_history, save, save_failed
        case send_message, show_all_fields, show_basic_fields, specific_dates, step_in_use
        case then, time_trigger, today, `true`, unavailable, use_app_skill
        case `repeat`, once, hourly, daily, weekly, minute, timezone
        case monday, tuesday, wednesday, thursday, friday, saturday, sunday
        case workflow, workflow_name, workflow_off, workflow_on, description
        case ai_create_submit, ai_create_submitting, ai_edit_placeholder
        case ai_edit_submit, ai_edit_submitting, ai_undo, ai_changes_saved
        case ai_removed, ai_added_nodes, ai_edited_nodes, ai_check_status
        case move_up, move_down, processing, stop, test_again, test_action
        case variable_cost, preview_message
        case sharing_soon, share, run_now
        case to, existing_chat, chat_title, message_question, title_required
        case earlier_action_variable_required
        case trigger_question, app_question, skill_question, use_app, choose_skill
        case add_action, ask_ai, ask_ai_unavailable, back
        case ask_ai_placeholder, ask_ai_app_warning, ask_ai_validation_unavailable
        case ask_ai_instruction_required, checking_instruction
    }

    enum WorkflowRunCopy: String {
        case run, next, cancel, cancel_title, cancel_explanation
        case content_unavailable, empty, execution_failed, loading, time_unavailable
        case status_completed, status_failed, status_cancelled, status_skipped
        case status_queued, status_planned, status_running, status_waiting
        case status_cancellation_requested, status_unavailable
    }

    static func workflowBuilder(_ key: WorkflowBuilderCopy) -> String {
        localized("workflows.builder.\(key.rawValue)")
    }
    static func workflowRun(_ key: WorkflowRunCopy) -> String {
        localized("workflows.runs.\(key.rawValue)")
    }
    static func workflowResultPosition(current: Int, total: Int) -> String {
        LocalizationManager.shared.text("workflows.builder.result_position", replacements: [
            "current": String(current), "total": String(total)
        ])
    }
    static func workflowStepInUse(_ steps: String) -> String {
        LocalizationManager.shared.text("workflows.builder.step_in_use", replacements: ["steps": steps])
    }
    static var workflowVersionHistory: String { localized("workflows.version_history.title") }
    static var workflowVersionRestore: String { localized("workflows.version_history.restore_as_new") }
    static var workflowSidebarLoading: String { localized("workflows.sidebar.loading") }
    static var workflowSidebarEmpty: String { localized("workflows.sidebar.empty") }
    static var workflowSidebarManual: String { localized("workflows.sidebar.manual") }
    static var workflowMyWorkflows: String { localized("workflows.sidebar.my_workflows") }
    static var workflowTemplates: String { localized("workflows.sidebar.templates") }
    static func workflowHomeGreeting(_ name: String) -> String {
        LocalizationManager.shared.text("workflows.home.greeting", replacements: ["name": name])
    }
    static var workflowHomeFallbackName: String { localized("workflows.home.fallback_name") }
    static var workflowHomeSubtitle: String { localized("workflows.home.subtitle") }
    static var workflowHomeShowAll: String { localized("workflows.home.show_all") }
    static var workflowHomeBackToRecent: String { localized("workflows.home.back_to_recent") }
    static var workflowHomeSearch: String { localized("workflows.home.search") }
    static var workflowHomeSearchUnavailable: String { localized("workflows.home.search_unavailable") }
    static var workflowHomeRetentionNone: String { localized("workflows.home.retention_none") }
    static var workflowHomeRetentionLast5: String { localized("workflows.home.retention_last5") }
    static var workflowHomeBadgeNew: String { localized("workflows.home.badge_new") }
    static var workflowHomeBadgeEnabled: String { localized("workflows.home.badge_enabled") }
    static var workflowHomeBadgePaused: String { localized("workflows.home.badge_paused") }
    static var workflowStarterBadge: String { localized("workflows.home.starter_badge") }
    static var workflowStarterRainTitle: String { localized("workflows.home.starter_rain_title") }
    static var workflowStarterRainSummary: String { localized("workflows.home.starter_rain_summary") }
    static var workflowStarterNewsTitle: String { localized("workflows.home.starter_news_title") }
    static var workflowStarterNewsSummary: String { localized("workflows.home.starter_news_summary") }
    static var workflowStarterApartmentsTitle: String { localized("workflows.home.starter_apartments_title") }
    static var workflowStarterApartmentsSummary: String { localized("workflows.home.starter_apartments_summary") }
    static var workflowInspirationPhrase: String { localized("workflows.home.inspiration_phrase") }
    static var workflowInspirationTitle: String { localized("workflows.home.inspiration_title") }
    static var workflowInspirationFeatureTitle: String { localized("workflows.home.inspiration_feature_title") }
    static var workflowInspirationFeatureDescription: String { localized("workflows.home.inspiration_feature_description") }
}

// MARK: - Health, home, nutrition and shopping result embeds
// MARK: - Projects workspace and transient reviews
extension AppStrings {
    static var projectTagline: String { localized("projects.workspace_tagline") }
    static var projectNew: String { localized("projects.workspace_new_project") }
    static var projectNone: String { localized("projects.workspace_no_projects") }
    static var projectCreate: String { localized("projects.workspace_create_project") }
    static var projectLoading: String { localized("projects.workspace_loading") }
    static var projectSettings: String { localized("projects.workspace_project_settings") }
    static var projectEdit: String { localized("projects.workspace_edit_project") }
    static var projectDelete: String { localized("projects.workspace_delete_project") }
    static var projectDeletePrompt: String { localized("projects.workspace_delete_prompt") }
    static var projectDeleteExplanation: String { localized("projects.workspace_delete_explanation") }
    static var projectLabel: String { localized("projects.workspace_project") }
    static var projectOverview: String { localized("projects.workspace_overview") }
    static var projectFiles: String { localized("projects.workspace_files") }
    static var projectRemotePreviewPending: String { localized("projects.workspace_remote_preview_pending") }
    static var projectRemoteFileDetailsPending: String { localized("projects.workspace_remote_file_details_pending") }
    static func projectEntryRange(start: Int, end: Int, total: Int) -> String {
        LocalizationManager.shared.text("projects.workspace_entry_range", replacements: [
            "start": String(start), "end": String(end), "total": String(total)
        ])
    }
    static var projectTasks: String { localized("projects.workspace_tasks") }
    static var projectOverviewLoading: String { localized("projects.workspace_overview_loading") }
    static var projectOverviewTruncated: String { localized("projects.workspace_overview_truncated") }
    static var projectOverviewEmpty: String { localized("projects.workspace_overview_empty") }
    static var projectUpload: String { localized("projects.workspace_upload") }
    static var projectCreateAction: String { localized("projects.workspace_create") }
    static var projectSourceNeeded: String { localized("projects.workspace_source_needed") }
    static var projectOverviewFailed: String { localized("projects.workspace_overview_failed") }
    static var projectTasksHeading: String { localized("projects.workspace_project_tasks") }
    static var projectOpenTasks: String { localized("projects.workspace_open_tasks") }
    static var projectShowNewest: String { localized("projects.workspace_show_newest") }
    static var projectShowOldest: String { localized("projects.workspace_show_oldest") }
    static var projectSortName: String { localized("projects.workspace_sort_name") }
    static var projectSortNewest: String { localized("projects.workspace_sort_newest") }
    static var projectSortOldest: String { localized("projects.workspace_sort_oldest") }
    static var projectSearchFiles: String { localized("projects.workspace_search_files") }
    static func projectGreeting(_ name: String) -> String {
        LocalizationManager.shared.text("projects.workspace_greeting", replacements: ["name": name])
    }
    static var projectNamePrompt: String { localized("projects.workspace_name_prompt") }
    static var projectVoiceInput: String { localized("projects.workspace_voice_input") }
    static var projectVoiceUnavailable: String { localized("projects.workspace_voice_unavailable") }
    static var projectInspirationBrief: String { localized("projects.workspace_inspiration_brief") }
    static var projectInspirationBriefTitle: String { localized("projects.workspace_inspiration_brief_title") }
    static var projectInspirationBriefFeatureTitle: String { localized("projects.workspace_inspiration_brief_feature_title") }
    static var projectInspirationBriefFeatureDescription: String { localized("projects.workspace_inspiration_brief_feature_description") }
    static var projectInspirationMilestones: String { localized("projects.workspace_inspiration_milestones") }
    static var projectInspirationMilestonesTitle: String { localized("projects.workspace_inspiration_milestones_title") }
    static var projectInspirationMilestonesFeatureTitle: String { localized("projects.workspace_inspiration_milestones_feature_title") }
    static var projectInspirationMilestonesFeatureDescription: String { localized("projects.workspace_inspiration_milestones_feature_description") }
    static var projectInspirationAssets: String { localized("projects.workspace_inspiration_assets") }
    static var projectInspirationAssetsTitle: String { localized("projects.workspace_inspiration_assets_title") }
    static var projectInspirationAssetsFeatureTitle: String { localized("projects.workspace_inspiration_assets_feature_title") }
    static var projectInspirationAssetsFeatureDescription: String { localized("projects.workspace_inspiration_assets_feature_description") }
    static var projectInspirationCTA: String { localized("daily_inspiration.tap_to_open_settings") }
    static var projectSearchCurrent: String { localized("projects.search_current_folder") }
    static func projectSearchAcross(_ name: String) -> String {
        LocalizationManager.shared.text("projects.search_across_project", replacements: ["project": name])
    }
    static var projectSearching: String { localized("projects.workspace_searching") }
    static var projectSearchCurrentEmpty: String { localized("projects.workspace_search_current_empty") }
    static var projectSearchAcrossEmpty: String { localized("projects.workspace_search_across_empty") }
    static var projectSearchPartialFailure: String { localized("projects.workspace_search_partial_failure") }
    static var projectPrevious: String { localized("projects.workspace_previous") }
    static var projectNext: String { localized("projects.workspace_next") }
    static var projectTile: String { localized("projects.workspace_tile") }
    static var projectList: String { localized("projects.workspace_list") }
    static var projectCreateFolder: String { localized("projects.workspace_create_folder") }
    static var projectNewWorkflow: String { localized("projects.workspace_new_workflow") }
    static var projectNewPlan: String { localized("projects.workspace_new_plan") }
    static var projectFilesLoading: String { localized("projects.workspace_files_loading") }
    static var projectStoredRemotely: String { localized("projects.workspace_stored_remotely") }
    static var projectConnectedSource: String { localized("projects.workspace_connected_source") }
    static var projectRemoteOpening: String { localized("projects.workspace_remote_opening") }
    static var projectRemoteOnDemand: String { localized("projects.workspace_remote_on_demand") }
    static var projectRemoteLimited: String { localized("projects.workspace_remote_limited") }
    static var projectNameField: String { localized("projects.workspace_project_name") }
    static var projectWritePermission: String { localized("projects.workspace_write_permission") }
    static var projectWritePrompt: String { localized("projects.workspace_write_prompt") }
    static var projectFolderName: String { localized("projects.workspace_folder_name") }
    static var projectDescriptionField: String { localized("projects.workspace_description") }
    static var projectApplyAndShow: String { localized("settings.projects.write_mode_apply_and_show") }
    static var projectAlwaysAsk: String { localized("settings.projects.write_mode_always_ask") }
    static var projectFileApplied: String { localized("projects.file_change_applied") }
    static var projectReadApprovalTitle: String { localized("projects.ignored_read_approval_title") }
    static var projectWriteApprovalTitle: String { localized("projects.file_write_approval_title") }
    static var projectReadApprovalDescription: String { localized("projects.ignored_read_approval_description") }
    static var projectReviewChanges: String { localized("projects.file_change_review") }
    static var projectApproveRead: String { localized("projects.file_read_approve") }
    static var projectApproveWrite: String { localized("projects.file_write_approve") }
    static var projectReject: String { localized("projects.file_approval_reject") }
    static var projectCommandTitle: String { localized("projects.remote_command_title") }
    static var projectCommandEffects: String { localized("projects.remote_command_effects") }
    static var projectCommandRisks: String { localized("projects.remote_command_risks") }
    static var projectCommandUncertainty: String { localized("projects.remote_command_uncertainty") }
    static var projectCommandArguments: String { localized("projects.remote_command_exact_arguments") }
    static var projectCommandDirectory: String { localized("projects.remote_command_directory") }
    static var projectCommandAccess: String { localized("projects.remote_command_source_access") }
    static var projectCommandMode: String { localized("projects.remote_command_mode") }
    static var projectCommandNetwork: String { localized("projects.remote_command_network") }
    static var projectCommandWritable: String { localized("projects.remote_command_writable") }
    static var projectCommandCredentials: String { localized("projects.remote_command_credentials") }
    static var projectCommandLimit: String { localized("projects.remote_command_time_limit") }
    static var projectCommandNone: String { localized("projects.remote_command_none") }
    static var projectCommandOutput: String { localized("projects.remote_command_output") }
    static var projectCommandFailed: String { localized("projects.remote_command_failed") }
    static var projectCommandApprove: String { localized("projects.remote_command_approve") }
    static var projectCommandStop: String { localized("projects.remote_command_stop") }
    static var projectCommandReadOnly: String { localized("projects.remote_command_access_read_only") }
    static var projectCommandReadWrite: String { localized("projects.remote_command_access_read_write") }
    static var projectCommandForeground: String { localized("projects.remote_command_mode_foreground") }
    static var projectCommandBackground: String { localized("projects.remote_command_mode_background") }

    static func projectCommandStatus(_ status: String) -> String {
        let allowed: Set<String> = ["pending", "preparing", "waiting_for_executor", "authorizing",
                                    "running", "stop_requested", "succeeded", "failed", "stopped",
                                    "timed_out", "rejected", "error"]
        return localized("projects.remote_command_status_\(allowed.contains(status) ? status : "error")")
    }
    static func projectCount(_ count: Int, key: String) -> String {
        LocalizationManager.shared.text("projects.\(key)", replacements: ["count": String(count)])
    }
    static func projectBrowserCount(folders: Int, files: Int) -> String {
        LocalizationManager.shared.text("projects.workspace_folder_files_count",
            replacements: ["folders": String(folders), "files": String(files)])
    }
    static func projectStarted(_ date: String) -> String {
        LocalizationManager.shared.text("projects.workspace_started", replacements: ["date": date])
    }
    static func projectStartedToday(_ time: String) -> String {
        LocalizationManager.shared.text("projects.workspace_started_today", replacements: ["time": time])
    }
}

// MARK: - Health, home, nutrition and shopping result embeds
extension AppStrings {
    static func fitnessOpenProvider(_ provider: String) -> String {
        LocalizationManager.shared.text("embeds.fitness.open_provider", replacements: ["provider": provider])
    }
    static var domainLocation: String { localized("common.location") }
    static var domainProvider: String { localized("common.provider") }
    static var domainFrom: String { localized("embeds.from") }
    static var domainListing: String { localized("embeds.search_domain.listing") }
    static var domainRoom: String { localized("embeds.search_domain.room") }
    static var domainRooms: String { localized("embeds.search_domain.rooms") }
    static var domainDelivery: String { localized("embeds.search_domain.delivery") }
    static var domainCategory: String { localized("embeds.search_domain.category") }
    static var domainRent: String { localized("embeds.search_domain.rent") }
    static var domainBuy: String { localized("embeds.search_domain.buy") }
    static var domainEasy: String { localized("embeds.search_domain.easy") }
    static var domainMedium: String { localized("embeds.search_domain.medium") }
    static var domainHard: String { localized("embeds.search_domain.hard") }
    static var domainBio: String { localized("embeds.search_domain.bio") }
    static var domainVegan: String { localized("embeds.search_domain.vegan") }
    static var domainVegetarian: String { localized("embeds.search_domain.vegetarian") }
    static var domainDairyFree: String { localized("embeds.search_domain.dairy_free") }
    static var domainGlutenFree: String { localized("embeds.search_domain.gluten_free") }
    static var domainRegional: String { localized("embeds.search_domain.regional") }
    static var domainInsurancePublic: String { localized("embeds.search_domain.insurance_public") }
    static var domainInsurancePrivate: String { localized("embeds.search_domain.insurance_private") }
    static var domainNutritionRecipe: String { localized("embeds.nutrition.recipe") }
    static var domainNutritionRecipes: String { localized("embeds.nutrition.recipes") }
    static var domainNutritionServings: String { localized("embeds.nutrition.servings") }
    static var domainNutritionIngredients: String { localized("embeds.nutrition.ingredients") }
    static var domainNutritionInstructions: String { localized("embeds.nutrition.instructions") }
    static var domainNutritionInfo: String { localized("embeds.nutrition.nutrition_info") }
    static var domainNutritionHealthScore: String { localized("embeds.nutrition.health_score") }
    static var domainNutritionProtein: String { localized("embeds.nutrition.protein") }
    static var domainNutritionFat: String { localized("embeds.nutrition.fat") }
    static var domainNutritionCarbs: String { localized("embeds.nutrition.carbs") }
    static var domainNutritionViewSource: String { localized("embeds.nutrition.view_source") }
    static var domainShoppingProduct: String { localized("embeds.shopping.product") }
    static var domainShoppingProducts: String { localized("embeds.shopping.products") }
    static var domainShoppingPriceUnavailable: String { localized("embeds.shopping.price_unavailable") }
    static var domainShoppingProductID: String { localized("embeds.shopping.product_id") }
    static var domainShoppingNew: String { localized("embeds.shopping.new") }
    static var domainHealthAppointmentAvailable: String { localized("embeds.health.appointment_available") }
    static var domainHealthAppointmentsAvailable: String { localized("embeds.health.appointments_available") }
    static var domainHealthAppointment: String { localized("embeds.health.appointment") }
    static var domainHealthSearchAppointments: String { localized("app_skills.health.search_appointments") }
    static var domainHealthAlsoAvailable: String { localized("embeds.health.also_available") }
    static func domainHealthReviewCount(_ count: Int) -> String { "(\(count) \(localized("embeds.health.reviews")))" }
    static var domainHealthTelehealth: String { localized("embeds.health.telehealth") }
    static func domainHealthInsuranceVerify(_ provider: String) -> String {
        LocalizationManager.shared.text("embeds.health.insurance_verify_on_provider", replacements: ["provider": provider])
    }
    static func domainHealthSlotsOutdated(_ provider: String) -> String {
        LocalizationManager.shared.text("embeds.health.slots_may_be_outdated", replacements: ["provider": provider])
    }
    static func domainMinutes(_ count: Int) -> String {
        LocalizationManager.shared.text("embeds.search_domain.minutes", replacements: ["count": "\(count)"])
    }
    static func domainHours(_ count: Int) -> String {
        LocalizationManager.shared.text("embeds.search_domain.hours", replacements: ["count": "\(count)"])
    }
    static func domainHoursMinutes(hours: Int, minutes: Int) -> String {
        LocalizationManager.shared.text("embeds.search_domain.hours_minutes", replacements: [
            "hours": "\(hours)", "minutes": "\(minutes)"
        ])
    }
}
