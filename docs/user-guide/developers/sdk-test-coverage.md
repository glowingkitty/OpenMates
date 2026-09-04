---
status: generated
last_verified: 2026-07-26
source: scripts/generate_sdk_reference.py
---

# OpenMates SDK Test Coverage Matrix

This generated matrix maps every public SDK method to direct test mentions or namespace-level smoke coverage.
The deploy gate fails when a method has neither direct nor namespace coverage in either package.

Run `python3 scripts/audit_sdk_test_coverage.py` to verify this file is current and complete.

| Namespace | npm | pip | npm coverage | pip coverage |
| --- | --- | --- | --- | --- |
| `account` | `om.account.acceptPartialExport()` | `om.account.accept_partial_export()` | namespace smoke: sdk.test.ts, account-export-sdk.test.ts, account-import-sdk.test.ts | namespace smoke: test_sdk.py, test_account_export.py, test_account_import.py |
| `account` | `om.account.cancelExport()` | `om.account.cancel_export()` | namespace smoke: sdk.test.ts, account-export-sdk.test.ts, account-import-sdk.test.ts | namespace smoke: test_sdk.py, test_account_export.py, test_account_import.py |
| `account` | `om.account.clearInterests()` | `om.account.clear_interests()` | namespace smoke: sdk.test.ts, account-export-sdk.test.ts, account-import-sdk.test.ts | namespace smoke: test_sdk.py, test_account_export.py, test_account_import.py |
| `account` | `om.account.completeExport()` | `om.account.complete_export()` | namespace smoke: sdk.test.ts, account-export-sdk.test.ts, account-import-sdk.test.ts | namespace smoke: test_sdk.py, test_account_export.py, test_account_import.py |
| `account` | `om.account.completeImport()` | `om.account.complete_import()` | namespace smoke: sdk.test.ts, account-export-sdk.test.ts, account-import-sdk.test.ts | direct |
| `account` | `om.account.compressImport()` | `om.account.compress_import()` | namespace smoke: sdk.test.ts, account-export-sdk.test.ts, account-import-sdk.test.ts | namespace smoke: test_sdk.py, test_account_export.py, test_account_import.py |
| `account` | `om.account.confirmImport()` | `om.account.confirm_import()` | namespace smoke: sdk.test.ts, account-export-sdk.test.ts, account-import-sdk.test.ts | namespace smoke: test_sdk.py, test_account_export.py, test_account_import.py |
| `account` | `om.account.deleteStorage()` | `om.account.delete_storage()` | namespace smoke: sdk.test.ts, account-export-sdk.test.ts, account-import-sdk.test.ts | namespace smoke: test_sdk.py, test_account_export.py, test_account_import.py |
| `account` | `om.account.downloadExport()` | `om.account.download_export()` | direct | direct |
| `account` | `om.account.exportChunk()` | `om.account.export_chunk()` | direct | direct |
| `account` | `om.account.exportChunks()` | `om.account.export_chunks()` | direct | direct |
| `account` | `om.account.exportData()` | `om.account.export_data()` | namespace smoke: sdk.test.ts, account-export-sdk.test.ts, account-import-sdk.test.ts | namespace smoke: test_sdk.py, test_account_export.py, test_account_import.py |
| `account` | `om.account.exportJobManifest()` | `om.account.export_job_manifest()` | namespace smoke: sdk.test.ts, account-export-sdk.test.ts, account-import-sdk.test.ts | namespace smoke: test_sdk.py, test_account_export.py, test_account_import.py |
| `account` | `om.account.exportManifest()` | `om.account.export_manifest()` | direct | namespace smoke: test_sdk.py, test_account_export.py, test_account_import.py |
| `account` | `om.account.getExport()` | `om.account.get_export()` | namespace smoke: sdk.test.ts, account-export-sdk.test.ts, account-import-sdk.test.ts | namespace smoke: test_sdk.py, test_account_export.py, test_account_import.py |
| `account` | `om.account.importChats()` | `om.account.import_chats()` | direct | direct |
| `account` | `om.account.importStatus()` | `om.account.import_status()` | direct | namespace smoke: test_sdk.py, test_account_export.py, test_account_import.py |
| `account` | `om.account.info()` | `om.account.info()` | direct | direct |
| `account` | `om.account.iterExportChunks()` | `om.account.iter_export_chunks()` | direct | direct |
| `account` | `om.account.listInterests()` | `om.account.list_interests()` | direct | direct |
| `account` | `om.account.parseChatGPTImport()` | `om.account.parse_chatgpt_import()` | direct | direct |
| `account` | `om.account.parseClaudeImport()` | `om.account.parse_claude_import()` | direct | direct |
| `account` | `om.account.parseGenericImport()` | `om.account.parse_generic_import()` | direct | direct |
| `account` | `om.account.parseOpenCodeImport()` | `om.account.parse_opencode_import()` | direct | direct |
| `account` | `om.account.parseOpenMatesImport()` | `om.account.parse_openmates_import()` | direct | direct |
| `account` | `om.account.persistImport()` | `om.account.persist_import()` | namespace smoke: sdk.test.ts, account-export-sdk.test.ts, account-import-sdk.test.ts | namespace smoke: test_sdk.py, test_account_export.py, test_account_import.py |
| `account` | `om.account.previewImport()` | `om.account.preview_import()` | namespace smoke: sdk.test.ts, account-export-sdk.test.ts, account-import-sdk.test.ts | namespace smoke: test_sdk.py, test_account_export.py, test_account_import.py |
| `account` | `om.account.scanImport()` | `om.account.scan_import()` | namespace smoke: sdk.test.ts, account-export-sdk.test.ts, account-import-sdk.test.ts | namespace smoke: test_sdk.py, test_account_export.py, test_account_import.py |
| `account` | `om.account.setInterests()` | `om.account.set_interests()` | namespace smoke: sdk.test.ts, account-export-sdk.test.ts, account-import-sdk.test.ts | namespace smoke: test_sdk.py, test_account_export.py, test_account_import.py |
| `account` | `om.account.setTimezone()` | `om.account.set_timezone()` | direct | direct |
| `account` | `om.account.setUsername()` | `om.account.set_username()` | namespace smoke: sdk.test.ts, account-export-sdk.test.ts, account-import-sdk.test.ts | namespace smoke: test_sdk.py, test_account_export.py, test_account_import.py |
| `account` | `om.account.startExport()` | `om.account.start_export()` | namespace smoke: sdk.test.ts, account-export-sdk.test.ts, account-import-sdk.test.ts | namespace smoke: test_sdk.py, test_account_export.py, test_account_import.py |
| `account` | `om.account.storageFiles()` | `om.account.storage_files()` | namespace smoke: sdk.test.ts, account-export-sdk.test.ts, account-import-sdk.test.ts | namespace smoke: test_sdk.py, test_account_export.py, test_account_import.py |
| `account` | `om.account.storageOverview()` | `om.account.storage_overview()` | namespace smoke: sdk.test.ts, account-export-sdk.test.ts, account-import-sdk.test.ts | namespace smoke: test_sdk.py, test_account_export.py, test_account_import.py |
| `api_keys` | `om.apiKeys.create()` | `om.api_keys.create()` | direct | direct |
| `api_keys` | `om.apiKeys.list()` | `om.api_keys.list()` | direct | direct |
| `api_keys` | `om.apiKeys.revoke()` | `om.api_keys.revoke()` | direct | direct |
| `benchmark` | `om.benchmark.estimate()` | `om.benchmark.estimate()` | direct | direct |
| `benchmark` | `om.benchmark.run()` | `om.benchmark.run()` | direct | direct |
| `billing` | `om.billing.bankTransferStatus()` | `om.billing.bank_transfer_status()` | direct | direct |
| `billing` | `om.billing.chatTotal()` | `om.billing.chat_total()` | direct | direct |
| `billing` | `om.billing.createBankTransferOrder()` | `om.billing.create_bank_transfer_order()` | direct | direct |
| `billing` | `om.billing.createGiftCardBankTransferOrder()` | `om.billing.create_gift_card_bank_transfer_order()` | direct | namespace smoke: test_sdk.py |
| `billing` | `om.billing.downloadCreditNote()` | `om.billing.download_credit_note()` | namespace smoke: sdk.test.ts, billing.test.ts | namespace smoke: test_sdk.py |
| `billing` | `om.billing.downloadInvoice()` | `om.billing.download_invoice()` | namespace smoke: sdk.test.ts, billing.test.ts | namespace smoke: test_sdk.py |
| `billing` | `om.billing.giftCardPurchaseStatus()` | `om.billing.gift_card_purchase_status()` | direct | namespace smoke: test_sdk.py |
| `billing` | `om.billing.listBankTransferOrders()` | `om.billing.list_bank_transfer_orders()` | direct | direct |
| `billing` | `om.billing.listInvoices()` | `om.billing.list_invoices()` | direct | direct |
| `billing` | `om.billing.listPurchasedGiftCards()` | `om.billing.list_purchased_gift_cards()` | namespace smoke: sdk.test.ts, billing.test.ts | namespace smoke: test_sdk.py |
| `billing` | `om.billing.listRedeemedGiftCards()` | `om.billing.list_redeemed_gift_cards()` | namespace smoke: sdk.test.ts, billing.test.ts | namespace smoke: test_sdk.py |
| `billing` | `om.billing.overview()` | `om.billing.overview()` | direct | direct |
| `billing` | `om.billing.redeemGiftCard()` | `om.billing.redeem_gift_card()` | namespace smoke: sdk.test.ts, billing.test.ts | namespace smoke: test_sdk.py |
| `billing` | `om.billing.requestRefund()` | `om.billing.request_refund()` | namespace smoke: sdk.test.ts, billing.test.ts | namespace smoke: test_sdk.py |
| `billing` | `om.billing.setLowBalanceAutoTopup()` | `om.billing.set_low_balance_auto_topup()` | namespace smoke: sdk.test.ts, billing.test.ts | namespace smoke: test_sdk.py |
| `billing` | `om.billing.usage()` | `om.billing.usage()` | direct | direct |
| `billing` | `om.billing.usageDaily()` | `om.billing.usage_daily()` | namespace smoke: sdk.test.ts, billing.test.ts | namespace smoke: test_sdk.py |
| `billing` | `om.billing.usageDetails()` | `om.billing.usage_details()` | direct | direct |
| `billing` | `om.billing.usageExport()` | `om.billing.usage_export()` | direct | direct |
| `billing` | `om.billing.usageOverview()` | `om.billing.usage_overview()` | direct | direct |
| `billing` | `om.billing.usageSummaries()` | `om.billing.usage_summaries()` | namespace smoke: sdk.test.ts, billing.test.ts | namespace smoke: test_sdk.py |
| `chats` | `om.chats.addToProject()` | `om.chats.add_to_project()` | direct | direct |
| `chats` | `om.chats.delete()` | `om.chats.delete()` | direct | direct |
| `chats` | `om.chats.export()` | `om.chats.export()` | direct | direct |
| `chats` | `om.chats.followUps()` | `om.chats.follow_ups()` | direct | direct |
| `chats` | `om.chats.fork()` | `om.chats.fork()` | direct | direct |
| `chats` | `om.chats.incognito()` | `om.chats.incognito()` | direct | namespace smoke: test_sdk.py, test_cleartext_boundary.py |
| `chats` | `om.chats.list()` | `om.chats.list()` | direct | direct |
| `chats` | `om.chats.load()` | `om.chats.load()` | direct | direct |
| `chats` | `om.chats.messagePages()` | `om.chats.message_pages()` | namespace smoke: sdk.test.ts, sdk-cleartext-boundary.test.ts | namespace smoke: test_sdk.py, test_cleartext_boundary.py |
| `chats` | `om.chats.messages()` | `om.chats.messages()` | direct | direct |
| `chats` | `om.chats.removeFromProject()` | `om.chats.remove_from_project()` | direct | direct |
| `chats` | `om.chats.retry()` | `om.chats.retry()` | direct | direct |
| `chats` | `om.chats.rewind()` | `om.chats.rewind()` | direct | direct |
| `chats` | `om.chats.search()` | `om.chats.search()` | direct | direct |
| `chats` | `om.chats.send()` | `om.chats.send()` | direct | direct |
| `chats` | `om.chats.share()` | `om.chats.share()` | direct | direct |
| `connected_accounts` | `om.connectedAccounts.import()` | `om.connected_accounts.import_account()` | direct | direct |
| `design` | `om.design.exportIcon()` | `om.design.export_icon()` | direct | direct |
| `docs` | `om.docs.download()` | `om.docs.download()` | direct | direct |
| `docs` | `om.docs.list()` | `om.docs.list()` | direct | direct |
| `docs` | `om.docs.search()` | `om.docs.search()` | direct | direct |
| `docs` | `om.docs.show()` | `om.docs.show()` | direct | direct |
| `drafts` | `om.drafts.get()` | `om.drafts.get()` | direct | direct |
| `drafts` | `om.drafts.getEncrypted()` | `om.drafts.get_encrypted()` | direct | direct |
| `drafts` | `om.drafts.list()` | `om.drafts.list()` | direct | direct |
| `drafts` | `om.drafts.listEncrypted()` | `om.drafts.list_encrypted()` | direct | direct |
| `embeds` | `om.embeds.addToProject()` | `om.embeds.add_to_project()` | direct | direct |
| `embeds` | `om.embeds.removeFromProject()` | `om.embeds.remove_from_project()` | direct | direct |
| `embeds` | `om.embeds.restoreVersion()` | `om.embeds.restore_version()` | direct | direct |
| `embeds` | `om.embeds.share()` | `om.embeds.share()` | direct | direct |
| `embeds` | `om.embeds.show()` | `om.embeds.show()` | direct | direct |
| `embeds` | `om.embeds.version()` | `om.embeds.version()` | direct | direct |
| `embeds` | `om.embeds.versions()` | `om.embeds.versions()` | direct | direct |
| `feedback` | `om.feedback.assistantResponse()` | `om.feedback.assistant_response()` | direct | direct |
| `finance` | `om.finance.checkAccounts()` | `om.finance.check_accounts()` | direct | direct |
| `history` | `om.history.list()` | `om.history.list()` | direct | direct |
| `history` | `om.history.show()` | `om.history.show()` | direct | direct |
| `history` | `om.history.undo()` | `om.history.undo()` | direct | direct |
| `ideabucket` | `om.ideabucket.add()` | `om.ideabucket.add()` | direct | direct |
| `ideabucket` | `om.ideabucket.process()` | `om.ideabucket.process()` | direct | direct |
| `ideabucket` | `om.ideabucket.saveSettings()` | `om.ideabucket.save_settings()` | namespace smoke: ideabucket.test.ts, sdk.test.ts | namespace smoke: test_sdk.py |
| `ideabucket` | `om.ideabucket.settings()` | `om.ideabucket.settings()` | direct | direct |
| `ideabucket` | `om.ideabucket.status()` | `om.ideabucket.status()` | direct | direct |
| `inspirations` | `om.inspirations.list()` | `om.inspirations.list()` | direct | direct |
| `learning_mode` | `om.learningMode.disable()` | `om.learning_mode.disable()` | direct | direct |
| `learning_mode` | `om.learningMode.enable()` | `om.learning_mode.enable()` | direct | direct |
| `learning_mode` | `om.learningMode.status()` | `om.learning_mode.status()` | direct | direct |
| `memories` | `om.memories.create()` | `om.memories.create()` | direct | direct |
| `memories` | `om.memories.delete()` | `om.memories.delete()` | direct | direct |
| `memories` | `om.memories.list()` | `om.memories.list()` | direct | direct |
| `memories` | `om.memories.types()` | `om.memories.types()` | direct | direct |
| `memories` | `om.memories.update()` | `om.memories.update()` | direct | direct |
| `new_chat_suggestions` | `om.newChatSuggestions.list()` | `om.new_chat_suggestions.list()` | direct | direct |
| `notifications` | `om.notifications.list()` | `om.notifications.list()` | direct | direct |
| `notifications` | `om.notifications.status()` | `om.notifications.status()` | direct | direct |
| `plans` | `om.plans.activate()` | `om.plans.activate()` | direct | direct |
| `plans` | `om.plans.addToProject()` | `om.plans.add_to_project()` | direct | direct |
| `plans` | `om.plans.addVerificationEvidence()` | `om.plans.add_verification_evidence()` | namespace smoke: sdk-plans.test.ts | namespace smoke: test_plans.py |
| `plans` | `om.plans.ask()` | `om.plans.ask()` | direct | direct |
| `plans` | `om.plans.attach()` | `om.plans.attach()` | direct | direct |
| `plans` | `om.plans.complete()` | `om.plans.complete()` | direct | direct |
| `plans` | `om.plans.create()` | `om.plans.create()` | direct | direct |
| `plans` | `om.plans.createAssumption()` | `om.plans.create_assumption()` | namespace smoke: sdk-plans.test.ts | namespace smoke: test_plans.py |
| `plans` | `om.plans.createCriterion()` | `om.plans.create_criterion()` | namespace smoke: sdk-plans.test.ts | namespace smoke: test_plans.py |
| `plans` | `om.plans.createLearning()` | `om.plans.create_learning()` | namespace smoke: sdk-plans.test.ts | namespace smoke: test_plans.py |
| `plans` | `om.plans.createLearningTasks()` | `om.plans.create_learning_tasks()` | namespace smoke: sdk-plans.test.ts | namespace smoke: test_plans.py |
| `plans` | `om.plans.createReferencePattern()` | `om.plans.create_reference_pattern()` | namespace smoke: sdk-plans.test.ts | namespace smoke: test_plans.py |
| `plans` | `om.plans.createVerification()` | `om.plans.create_verification()` | namespace smoke: sdk-plans.test.ts | namespace smoke: test_plans.py |
| `plans` | `om.plans.delete()` | `om.plans.delete()` | direct | direct |
| `plans` | `om.plans.deleteAssumption()` | `om.plans.delete_assumption()` | namespace smoke: sdk-plans.test.ts | namespace smoke: test_plans.py |
| `plans` | `om.plans.deleteCriterion()` | `om.plans.delete_criterion()` | namespace smoke: sdk-plans.test.ts | namespace smoke: test_plans.py |
| `plans` | `om.plans.deleteLearning()` | `om.plans.delete_learning()` | namespace smoke: sdk-plans.test.ts | namespace smoke: test_plans.py |
| `plans` | `om.plans.deleteReferencePattern()` | `om.plans.delete_reference_pattern()` | namespace smoke: sdk-plans.test.ts | namespace smoke: test_plans.py |
| `plans` | `om.plans.deleteVerification()` | `om.plans.delete_verification()` | namespace smoke: sdk-plans.test.ts | namespace smoke: test_plans.py |
| `plans` | `om.plans.getVerificationRun()` | `om.plans.get_verification_run()` | namespace smoke: sdk-plans.test.ts | namespace smoke: test_plans.py |
| `plans` | `om.plans.history()` | `om.plans.history()` | direct | direct |
| `plans` | `om.plans.list()` | `om.plans.list()` | direct | direct |
| `plans` | `om.plans.listAssumptions()` | `om.plans.list_assumptions()` | direct | direct |
| `plans` | `om.plans.listCriteria()` | `om.plans.list_criteria()` | direct | direct |
| `plans` | `om.plans.listLearnings()` | `om.plans.list_learnings()` | namespace smoke: sdk-plans.test.ts | namespace smoke: test_plans.py |
| `plans` | `om.plans.listReferencePatterns()` | `om.plans.list_reference_patterns()` | direct | direct |
| `plans` | `om.plans.listVerifications()` | `om.plans.list_verifications()` | direct | direct |
| `plans` | `om.plans.removeFromProject()` | `om.plans.remove_from_project()` | direct | direct |
| `plans` | `om.plans.restore()` | `om.plans.restore()` | direct | direct |
| `plans` | `om.plans.resume()` | `om.plans.resume()` | direct | direct |
| `plans` | `om.plans.show()` | `om.plans.show()` | direct | direct |
| `plans` | `om.plans.start()` | `om.plans.start()` | direct | direct |
| `plans` | `om.plans.update()` | `om.plans.update()` | direct | direct |
| `plans` | `om.plans.updateAssumption()` | `om.plans.update_assumption()` | namespace smoke: sdk-plans.test.ts | namespace smoke: test_plans.py |
| `plans` | `om.plans.updateCriterion()` | `om.plans.update_criterion()` | namespace smoke: sdk-plans.test.ts | namespace smoke: test_plans.py |
| `plans` | `om.plans.updateLearning()` | `om.plans.update_learning()` | namespace smoke: sdk-plans.test.ts | namespace smoke: test_plans.py |
| `plans` | `om.plans.updateReferencePattern()` | `om.plans.update_reference_pattern()` | namespace smoke: sdk-plans.test.ts | namespace smoke: test_plans.py |
| `plans` | `om.plans.updateVerification()` | `om.plans.update_verification()` | namespace smoke: sdk-plans.test.ts | namespace smoke: test_plans.py |
| `projects` | `om.projects.archive()` | `om.projects.archive()` | direct | direct |
| `projects` | `om.projects.ask()` | `om.projects.ask()` | direct | direct |
| `projects` | `om.projects.create()` | `om.projects.create()` | direct | direct |
| `projects` | `om.projects.delete()` | `om.projects.delete()` | direct | direct |
| `projects` | `om.projects.history()` | `om.projects.history()` | direct | direct |
| `projects` | `om.projects.list()` | `om.projects.list()` | direct | direct |
| `projects` | `om.projects.restore()` | `om.projects.restore()` | direct | direct |
| `projects` | `om.projects.show()` | `om.projects.show()` | direct | direct |
| `projects` | `om.projects.unarchive()` | `om.projects.unarchive()` | direct | direct |
| `projects` | `om.projects.update()` | `om.projects.update()` | direct | direct |
| `reminders` | `om.reminders.delete()` | `om.reminders.delete()` | direct | direct |
| `reminders` | `om.reminders.list()` | `om.reminders.list()` | direct | direct |
| `reminders` | `om.reminders.update()` | `om.reminders.update()` | direct | direct |
| `settings` | `om.settings.setChatAutoDelete()` | `om.settings.set_chat_auto_delete()` | namespace smoke: sdk.test.ts | namespace smoke: test_sdk.py |
| `settings` | `om.settings.setDarkMode()` | `om.settings.set_dark_mode()` | direct | direct |
| `settings` | `om.settings.setFont()` | `om.settings.set_font()` | namespace smoke: sdk.test.ts | namespace smoke: test_sdk.py |
| `settings` | `om.settings.setLanguage()` | `om.settings.set_language()` | namespace smoke: sdk.test.ts | namespace smoke: test_sdk.py |
| `settings` | `om.settings.setModelDefaults()` | `om.settings.set_model_defaults()` | direct | direct |
| `settings` | `om.settings.shareDebugLogs()` | `om.settings.share_debug_logs()` | direct | direct |
| `tasks` | `om.tasks.addActivityComment()` | `om.tasks.add_activity_comment()` | direct | direct |
| `tasks` | `om.tasks.addToProject()` | `om.tasks.add_to_project()` | direct | direct |
| `tasks` | `om.tasks.ask()` | `om.tasks.ask()` | direct | direct |
| `tasks` | `om.tasks.block()` | `om.tasks.block()` | direct | direct |
| `tasks` | `om.tasks.complete()` | `om.tasks.complete()` | direct | direct |
| `tasks` | `om.tasks.create()` | `om.tasks.create()` | direct | direct |
| `tasks` | `om.tasks.delete()` | `om.tasks.delete()` | direct | direct |
| `tasks` | `om.tasks.deleteActivityComment()` | `om.tasks.delete_activity_comment()` | direct | direct |
| `tasks` | `om.tasks.deleteById()` | `om.tasks.delete_by_id()` | namespace smoke: sdk-tasks.test.ts | direct |
| `tasks` | `om.tasks.done()` | `om.tasks.done()` | direct | direct |
| `tasks` | `om.tasks.edit()` | `om.tasks.edit()` | direct | direct |
| `tasks` | `om.tasks.history()` | `om.tasks.history()` | direct | direct |
| `tasks` | `om.tasks.list()` | `om.tasks.list()` | direct | direct |
| `tasks` | `om.tasks.listActivity()` | `om.tasks.list_activity()` | direct | direct |
| `tasks` | `om.tasks.move()` | `om.tasks.move()` | direct | direct |
| `tasks` | `om.tasks.removeFromProject()` | `om.tasks.remove_from_project()` | direct | direct |
| `tasks` | `om.tasks.reorder()` | `om.tasks.reorder()` | direct | direct |
| `tasks` | `om.tasks.restore()` | `om.tasks.restore()` | direct | direct |
| `tasks` | `om.tasks.show()` | `om.tasks.show()` | direct | direct |
| `tasks` | `om.tasks.skip()` | `om.tasks.skip()` | direct | direct |
| `tasks` | `om.tasks.start()` | `om.tasks.start()` | direct | direct |
| `tasks` | `om.tasks.startAI()` | `om.tasks.start_ai()` | direct | direct |
| `tasks` | `om.tasks.unblock()` | `om.tasks.unblock()` | direct | direct |
| `tasks` | `om.tasks.update()` | `om.tasks.update()` | direct | direct |
| `teams` | `om.teams.acceptInvite()` | `om.teams.accept_invite()` | direct | direct |
| `teams` | `om.teams.accessRequests()` | `om.teams.access_requests()` | direct | direct |
| `teams` | `om.teams.approveAccess()` | `om.teams.approve_access()` | direct | direct |
| `teams` | `om.teams.bankTransferStatus()` | `om.teams.bank_transfer_status()` | direct | direct |
| `teams` | `om.teams.billing()` | `om.teams.billing()` | direct | direct |
| `teams` | `om.teams.create()` | `om.teams.create()` | direct | direct |
| `teams` | `om.teams.createBankTransferOrder()` | `om.teams.create_bank_transfer_order()` | direct | direct |
| `teams` | `om.teams.createPlain()` | `om.teams.create_plain()` | direct | direct |
| `teams` | `om.teams.declineInvite()` | `om.teams.decline_invite()` | direct | direct |
| `teams` | `om.teams.export()` | `om.teams.export()` | direct | direct |
| `teams` | `om.teams.get()` | `om.teams.get()` | direct | direct |
| `teams` | `om.teams.getProfileImage()` | `om.teams.get_profile_image()` | direct | direct |
| `teams` | `om.teams.import()` | `om.teams.import_team()` | direct | direct |
| `teams` | `om.teams.invite()` | `om.teams.invite()` | direct | direct |
| `teams` | `om.teams.list()` | `om.teams.list()` | direct | direct |
| `teams` | `om.teams.listBankTransferOrders()` | `om.teams.list_bank_transfer_orders()` | direct | direct |
| `teams` | `om.teams.memories()` | `om.teams.memories()` | direct | direct |
| `teams` | `om.teams.rejectAccess()` | `om.teams.reject_access()` | direct | direct |
| `teams` | `om.teams.removeMember()` | `om.teams.remove_member()` | direct | direct |
| `teams` | `om.teams.update()` | `om.teams.update()` | direct | direct |
| `teams` | `om.teams.updateGeneratedProfileImage()` | `om.teams.update_generated_profile_image()` | direct | direct |
| `teams` | `om.teams.usage()` | `om.teams.usage()` | direct | direct |
| `wikipedia` | `om.wikipedia.search()` | `om.wikipedia.search()` | direct | direct |
| `wikipedia` | `om.wikipedia.summary()` | `om.wikipedia.summary()` | direct | direct |
| `workflows` | `om.workflows.addToProject()` | `om.workflows.add_to_project()` | direct | direct |
| `workflows` | `om.workflows.ask()` | `om.workflows.ask()` | direct | direct |
| `workflows` | `om.workflows.cancelRun()` | `om.workflows.cancel_run()` | direct | direct |
| `workflows` | `om.workflows.capabilities()` | `om.workflows.capabilities()` | direct | direct |
| `workflows` | `om.workflows.completeImportedBinding()` | `om.workflows.complete_imported_binding()` | namespace smoke: sdk-workflows.test.ts, workflows.test.ts | direct |
| `workflows` | `om.workflows.create()` | `om.workflows.create()` | direct | direct |
| `workflows` | `om.workflows.createFromYaml()` | `om.workflows.create_from_yaml()` | direct | direct |
| `workflows` | `om.workflows.createTemplateShortUrl()` | `om.workflows.create_template_short_url()` | direct | direct |
| `workflows` | `om.workflows.delete()` | `om.workflows.delete()` | direct | direct |
| `workflows` | `om.workflows.disable()` | `om.workflows.disable()` | direct | direct |
| `workflows` | `om.workflows.enable()` | `om.workflows.enable()` | direct | direct |
| `workflows` | `om.workflows.followUpInput()` | `om.workflows.follow_up_input()` | direct | direct |
| `workflows` | `om.workflows.get()` | `om.workflows.get()` | direct | direct |
| `workflows` | `om.workflows.getPublicTemplateProjection()` | `om.workflows.get_public_template_projection()` | direct | direct |
| `workflows` | `om.workflows.history()` | `om.workflows.history()` | direct | direct |
| `workflows` | `om.workflows.importTemplate()` | `om.workflows.import_template()` | direct | direct |
| `workflows` | `om.workflows.inputEvents()` | `om.workflows.input_events()` | direct | direct |
| `workflows` | `om.workflows.inputSession()` | `om.workflows.input_session()` | direct | direct |
| `workflows` | `om.workflows.keep()` | `om.workflows.keep()` | direct | direct |
| `workflows` | `om.workflows.list()` | `om.workflows.list()` | direct | direct |
| `workflows` | `om.workflows.removeFromProject()` | `om.workflows.remove_from_project()` | direct | direct |
| `workflows` | `om.workflows.respond()` | `om.workflows.respond()` | direct | direct |
| `workflows` | `om.workflows.restore()` | `om.workflows.restore()` | direct | direct |
| `workflows` | `om.workflows.revokeShortUrl()` | `om.workflows.revoke_short_url()` | direct | direct |
| `workflows` | `om.workflows.revokeTemplateProjection()` | `om.workflows.revoke_template_projection()` | direct | direct |
| `workflows` | `om.workflows.run()` | `om.workflows.run()` | direct | direct |
| `workflows` | `om.workflows.runDetail()` | `om.workflows.run_detail()` | direct | direct |
| `workflows` | `om.workflows.runs()` | `om.workflows.runs()` | direct | direct |
| `workflows` | `om.workflows.startInput()` | `om.workflows.start_input()` | direct | direct |
| `workflows` | `om.workflows.stepTest()` | `om.workflows.step_test()` | direct | direct |
| `workflows` | `om.workflows.stopInput()` | `om.workflows.stop_input()` | direct | direct |
| `workflows` | `om.workflows.temporary()` | `om.workflows.temporary()` | direct | direct |
| `workflows` | `om.workflows.undoInput()` | `om.workflows.undo_input()` | direct | direct |
| `workflows` | `om.workflows.unrevokeTemplateProjection()` | `om.workflows.unrevoke_template_projection()` | direct | direct |
| `workflows` | `om.workflows.update()` | `om.workflows.update()` | direct | direct |
| `workflows` | `om.workflows.updateFromYaml()` | `om.workflows.update_from_yaml()` | direct | direct |
| `workflows` | `om.workflows.upsertTemplateProjection()` | `om.workflows.upsert_template_projection()` | direct | direct |
| `workflows` | `om.workflows.validateYaml()` | `om.workflows.validate_yaml()` | direct | direct |
