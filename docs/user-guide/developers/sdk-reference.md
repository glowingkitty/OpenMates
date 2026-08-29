---
status: generated
last_verified: 2026-07-26
source: scripts/generate_sdk_reference.py
---

# OpenMates SDK Reference

This generated reference lists every public npm and pip SDK method that must stay in parity.
Public SDK methods accept cleartext inputs and return cleartext outputs; encryption and decryption happen inside the SDKs.

Run `python3 scripts/generate_sdk_reference.py --check` to verify this file is current.

## `account`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.account.acceptPartialExport()` | `om.account.accept_partial_export()` | `export_id` | `export_id` | `object` |
| `om.account.cancelExport()` | `om.account.cancel_export()` | `export_id` | `export_id` | `object` |
| `om.account.clearInterests()` | `om.account.clear_interests()` | `none` | `none` | `object` |
| `om.account.completeExport()` | `om.account.complete_export()` | `export_id` | `export_id` | `object` |
| `om.account.completeImport()` | `om.account.complete_import()` | `import_id, imported_chat_ids, source_fingerprints, record_counts, client_failures` | `import_id, imported_chat_ids, source_fingerprints, record_counts, client_failures` | `object` |
| `om.account.compressImport()` | `om.account.compress_import()` | `import_id, sanitized_messages, scan_sequence, source_fingerprint, prior_summary, sequence, final_batch, batch_id` | `import_id, sanitized_messages, scan_sequence, source_fingerprint, prior_summary, sequence, final_batch, batch_id` | `object` |
| `om.account.confirmImport()` | `om.account.confirm_import()` | `import_id, selected_fingerprints` | `import_id, selected_fingerprints` | `object` |
| `om.account.deleteStorage()` | `om.account.delete_storage()` | `confirmed, file_id, category, all` | `confirmed, input` | `object` |
| `om.account.downloadExport()` | `om.account.download_export()` | `domains, input, format, include_advanced_metadata, accept_partial` | `accept_partial, input` | `object` |
| `om.account.exportChunk()` | `om.account.export_chunk()` | `export_id, chunk_id` | `export_id, chunk_id` | `object` |
| `om.account.exportChunks()` | `om.account.export_chunks()` | `export_id` | `export_id` | `object` |
| `om.account.exportData()` | `om.account.export_data()` | `none` | `none` | `object` |
| `om.account.exportJobManifest()` | `om.account.export_job_manifest()` | `export_id` | `export_id` | `object` |
| `om.account.exportManifest()` | `om.account.export_manifest()` | `none` | `none` | `object` |
| `om.account.getExport()` | `om.account.get_export()` | `export_id` | `export_id` | `object` |
| `om.account.importChats()` | `om.account.import_chats()` | `parsed, select` | `parsed, select` | `object` |
| `om.account.importStatus()` | `om.account.import_status()` | `import_id` | `import_id` | `object` |
| `om.account.info()` | `om.account.info()` | `none` | `none` | `object` |
| `om.account.iterExportChunks()` | `om.account.iter_export_chunks()` | `export_id` | `export_id` | `object` |
| `om.account.listInterests()` | `om.account.list_interests()` | `none` | `none` | `object` |
| `om.account.parseChatGPTImport()` | `om.account.parse_chatgpt_import()` | `input, source_name, source` | `input, source_name, source` | `object` |
| `om.account.parseClaudeImport()` | `om.account.parse_claude_import()` | `input, source_name, source` | `input, source_name, source` | `object` |
| `om.account.parseGenericImport()` | `om.account.parse_generic_import()` | `input, source_name, source` | `input, source, source_name` | `object` |
| `om.account.parseOpenCodeImport()` | `om.account.parse_opencode_import()` | `input, source_name, source` | `input, source_name, source` | `object` |
| `om.account.parseOpenMatesImport()` | `om.account.parse_openmates_import()` | `input, source_name, password, source` | `input, source_name, password, source` | `object` |
| `om.account.persistImport()` | `om.account.persist_import()` | `import_id, chats` | `import_id, chats` | `object` |
| `om.account.previewImport()` | `om.account.preview_import()` | `source, chats, chat_count, source_fingerprints, estimated_tokens, estimated_tokens_by_chat, estimated_bytes` | `source, chats, chat_count, source_fingerprints, estimated_tokens, estimated_tokens_by_chat, estimated_bytes` | `object` |
| `om.account.scanImport()` | `om.account.scan_import()` | `import_id, chats, sequence, final_batch, batch_id` | `import_id, chats, sequence, final_batch, batch_id` | `object` |
| `om.account.setInterests()` | `om.account.set_interests()` | `selected_tag_ids` | `selected_tag_ids` | `object` |
| `om.account.setTimezone()` | `om.account.set_timezone()` | `timezone` | `timezone` | `object` |
| `om.account.setUsername()` | `om.account.set_username()` | `username` | `username` | `object` |
| `om.account.startExport()` | `om.account.start_export()` | `domains, input, format, include_advanced_metadata` | `domains, input, format, include_advanced_metadata` | `object` |
| `om.account.storageFiles()` | `om.account.storage_files()` | `input` | `input` | `object` |
| `om.account.storageOverview()` | `om.account.storage_overview()` | `none` | `none` | `object` |

## `api_keys`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.apiKeys.create()` | `om.api_keys.create()` | `name, full_access, scopes, credit_limit, expires_at` | `name, full_access, scopes, credit_limit, expires_at` | `object` |
| `om.apiKeys.list()` | `om.api_keys.list()` | `none` | `none` | `object` |
| `om.apiKeys.revoke()` | `om.api_keys.revoke()` | `id` | `id` | `object` |

## `benchmark`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.benchmark.estimate()` | `om.benchmark.estimate()` | `input` | `input` | `object` |
| `om.benchmark.run()` | `om.benchmark.run()` | `input` | `input` | `object` |

## `billing`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.billing.bankTransferStatus()` | `om.billing.bank_transfer_status()` | `order_id` | `order_id` | `object` |
| `om.billing.chatTotal()` | `om.billing.chat_total()` | `chat_id` | `chat_id` | `object` |
| `om.billing.createBankTransferOrder()` | `om.billing.create_bank_transfer_order()` | `credits, email_encryption_key` | `credits, email_encryption_key` | `object` |
| `om.billing.createGiftCardBankTransferOrder()` | `om.billing.create_gift_card_bank_transfer_order()` | `credits, email_encryption_key` | `credits, email_encryption_key` | `object` |
| `om.billing.downloadCreditNote()` | `om.billing.download_credit_note()` | `invoice_id` | `invoice_id` | `object` |
| `om.billing.downloadInvoice()` | `om.billing.download_invoice()` | `invoice_id` | `invoice_id` | `object` |
| `om.billing.giftCardPurchaseStatus()` | `om.billing.gift_card_purchase_status()` | `order_id` | `order_id` | `object` |
| `om.billing.listBankTransferOrders()` | `om.billing.list_bank_transfer_orders()` | `none` | `none` | `object` |
| `om.billing.listInvoices()` | `om.billing.list_invoices()` | `none` | `none` | `object` |
| `om.billing.listPurchasedGiftCards()` | `om.billing.list_purchased_gift_cards()` | `none` | `none` | `object` |
| `om.billing.listRedeemedGiftCards()` | `om.billing.list_redeemed_gift_cards()` | `none` | `none` | `object` |
| `om.billing.overview()` | `om.billing.overview()` | `none` | `none` | `object` |
| `om.billing.redeemGiftCard()` | `om.billing.redeem_gift_card()` | `code` | `code` | `object` |
| `om.billing.requestRefund()` | `om.billing.request_refund()` | `invoice_id, confirmed, email_encryption_key` | `invoice_id, confirmed, email_encryption_key` | `object` |
| `om.billing.setLowBalanceAutoTopup()` | `om.billing.set_low_balance_auto_topup()` | `input` | `input` | `object` |
| `om.billing.usage()` | `om.billing.usage()` | `input` | `input` | `object` |
| `om.billing.usageDaily()` | `om.billing.usage_daily()` | `none` | `none` | `object` |
| `om.billing.usageDetails()` | `om.billing.usage_details()` | `type, identifier, year_month` | `type, identifier, year_month` | `object` |
| `om.billing.usageExport()` | `om.billing.usage_export()` | `months` | `months` | `object` |
| `om.billing.usageOverview()` | `om.billing.usage_overview()` | `input` | `input` | `object` |
| `om.billing.usageSummaries()` | `om.billing.usage_summaries()` | `none` | `none` | `object` |

## `chats`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.chats.addToProject()` | `om.chats.add_to_project()` | `id, project_id, folder` | `id, project_id, folder` | `object` |
| `om.chats.delete()` | `om.chats.delete()` | `id, confirmed` | `id, confirmed` | `object` |
| `om.chats.export()` | `om.chats.export()` | `id, format` | `id, format` | `object` |
| `om.chats.followUps()` | `om.chats.follow_ups()` | `id` | `id` | `list` |
| `om.chats.fork()` | `om.chats.fork()` | `id, from_message_id, title` | `id, from_message_id, title` | `object` |
| `om.chats.incognito()` | `om.chats.incognito()` | `message` | `message` | `object` |
| `om.chats.list()` | `om.chats.list()` | `limit, offset` | `limit, offset` | `list` |
| `om.chats.load()` | `om.chats.load()` | `id` | `id` | `object` |
| `om.chats.messagePages()` | `om.chats.message_pages()` | `id, direction, limit, before_timestamp, before_message_id, after_timestamp, after_message_id, anchor_message_id, respect_compression_boundary, all` | `id, limit, input` | `object` |
| `om.chats.messages()` | `om.chats.messages()` | `id, direction, limit, before_timestamp, before_message_id, after_timestamp, after_message_id, anchor_message_id, respect_compression_boundary, all` | `id, direction, limit, before_timestamp, before_message_id, after_timestamp, after_message_id, anchor_message_id, respect_compression_boundary, all` | `object` |
| `om.chats.removeFromProject()` | `om.chats.remove_from_project()` | `id, project_id` | `id, project_id` | `object` |
| `om.chats.retry()` | `om.chats.retry()` | `id, dry_run, confirmed` | `id, dry_run, confirmed` | `object` |
| `om.chats.rewind()` | `om.chats.rewind()` | `id, to_message_id, send, dry_run, confirmed` | `id, to_message_id, send, dry_run, confirmed` | `object` |
| `om.chats.search()` | `om.chats.search()` | `input, limit, offset` | `input, limit, offset` | `list` |
| `om.chats.send()` | `om.chats.send()` | `message, save_to_account, focus_mode, id, slug, title, goal, goal_title, team_id, history, memory_ids, model, recovery_poll_interval, recovery_timeout, connected_account_directory, connected_account_token_ref_inputs, sender_name, team_member_mentions` | `message, history, save_to_account, focus_mode, memory_ids, model, id, slug, title, goal, goal_title, team_id, sender_name, team_member_mentions, connected_account_directory, connected_account_token_ref_inputs, recovery_poll_interval, recovery_timeout` | `object` |
| `om.chats.share()` | `om.chats.share()` | `id, expires, password` | `id, expires, password` | `object` |

## `connected_accounts`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.connectedAccounts.import()` | `om.connected_accounts.import_account()` | `input, passcode, team_id` | `input, passcode, team_id` | `object` |

## `design`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.design.exportIcon()` | `om.design.export_icon()` | `input` | `svg_path, prefix, name, output_path, format, color, palette, allow_palette_recolor, size, width, height` | `object` |

## `docs`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.docs.download()` | `om.docs.download()` | `slug` | `slug` | `object` |
| `om.docs.list()` | `om.docs.list()` | `none` | `none` | `object` |
| `om.docs.search()` | `om.docs.search()` | `input` | `input` | `object` |
| `om.docs.show()` | `om.docs.show()` | `slug` | `slug` | `object` |

## `drafts`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.drafts.get()` | `om.drafts.get()` | `chat_id` | `chat_id` | `object` |
| `om.drafts.getEncrypted()` | `om.drafts.get_encrypted()` | `chat_id` | `chat_id` | `object` |
| `om.drafts.list()` | `om.drafts.list()` | `none` | `none` | `list` |
| `om.drafts.listEncrypted()` | `om.drafts.list_encrypted()` | `none` | `none` | `list` |

## `embeds`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.embeds.addToProject()` | `om.embeds.add_to_project()` | `id, project_id, folder` | `id, project_id, folder` | `object` |
| `om.embeds.removeFromProject()` | `om.embeds.remove_from_project()` | `id, project_id` | `id, project_id` | `object` |
| `om.embeds.restoreVersion()` | `om.embeds.restore_version()` | `id, version, confirmed` | `id, version, confirmed` | `object` |
| `om.embeds.share()` | `om.embeds.share()` | `id, expires, password` | `id, expires, password` | `object` |
| `om.embeds.show()` | `om.embeds.show()` | `id` | `id` | `object` |
| `om.embeds.version()` | `om.embeds.version()` | `id, version` | `id, version` | `object` |
| `om.embeds.versions()` | `om.embeds.versions()` | `id` | `id` | `object` |

## `feedback`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.feedback.assistantResponse()` | `om.feedback.assistant_response()` | `rating` | `rating` | `object` |

## `finance`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.finance.checkAccounts()` | `om.finance.check_accounts()` | `period, start_date, end_date, projection_horizon, connected_account_requests, csv_statements, connected_account_token_ref_inputs, chat_id, message_id, prompt_injection_protection` | `input, connected_account_token_ref_inputs, chat_id, message_id, prompt_injection_protection` | `object` |

## `history`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.history.list()` | `om.history.list()` | `object_type, object_id, limit` | `object_type, object_id, limit` | `list` |
| `om.history.show()` | `om.history.show()` | `change_set_id` | `change_set_id` | `object` |
| `om.history.undo()` | `om.history.undo()` | `change_set_id` | `change_set_id` | `object` |

## `ideabucket`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.ideabucket.add()` | `om.ideabucket.add()` | `text, chat_id, bucket_id, scheduled_send_at, prompt` | `input` | `object` |
| `om.ideabucket.process()` | `om.ideabucket.process()` | `bucket_id, now` | `bucket_id, now` | `object` |
| `om.ideabucket.saveSettings()` | `om.ideabucket.save_settings()` | `processing_prompt, processing_times` | `input` | `object` |
| `om.ideabucket.settings()` | `om.ideabucket.settings()` | `none` | `none` | `object` |
| `om.ideabucket.status()` | `om.ideabucket.status()` | `bucket_id` | `bucket_id` | `object` |

## `inspirations`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.inspirations.list()` | `om.inspirations.list()` | `language` | `language` | `object` |

## `learning_mode`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.learningMode.disable()` | `om.learning_mode.disable()` | `passcode` | `passcode` | `object` |
| `om.learningMode.enable()` | `om.learning_mode.enable()` | `age_group, passcode` | `age_group, passcode` | `object` |
| `om.learningMode.status()` | `om.learning_mode.status()` | `none` | `none` | `object` |

## `memories`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.memories.create()` | `om.memories.create()` | `input` | `input` | `object` |
| `om.memories.delete()` | `om.memories.delete()` | `id, confirmed` | `id, confirmed` | `object` |
| `om.memories.list()` | `om.memories.list()` | `input` | `input` | `object` |
| `om.memories.types()` | `om.memories.types()` | `input` | `input` | `object` |
| `om.memories.update()` | `om.memories.update()` | `id, input` | `id, input` | `object` |

## `new_chat_suggestions`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.newChatSuggestions.list()` | `om.new_chat_suggestions.list()` | `limit` | `limit` | `object` |

## `notifications`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.notifications.list()` | `om.notifications.list()` | `limit` | `limit` | `object` |
| `om.notifications.status()` | `om.notifications.status()` | `none` | `none` | `object` |

## `plans`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.plans.activate()` | `om.plans.activate()` | `id, chat_id` | `id, chat_id` | `object` |
| `om.plans.addToProject()` | `om.plans.add_to_project()` | `id, project_id` | `id, project_id` | `object` |
| `om.plans.addVerificationEvidence()` | `om.plans.add_verification_evidence()` | `id, verification_id, input` | `id, verification_id, input` | `object` |
| `om.plans.ask()` | `om.plans.ask()` | `instruction, create, update, updates` | `instruction, create, update, updates` | `object` |
| `om.plans.attach()` | `om.plans.attach()` | `id, chat_id` | `id, chat_id` | `object` |
| `om.plans.complete()` | `om.plans.complete()` | `id` | `id` | `object` |
| `om.plans.create()` | `om.plans.create()` | `input` | `input` | `object` |
| `om.plans.createAssumption()` | `om.plans.create_assumption()` | `id, assumption_id, text, category, status, required_before, linked_sub_chat_id, linked_task_id, linked_criterion_ids, source_count, corrected_text, evidence_summary, blocker_reason, waiver_reason, sources, proof_inputs` | `id, input` | `object` |
| `om.plans.createCriterion()` | `om.plans.create_criterion()` | `id, input` | `id, input` | `object` |
| `om.plans.createLearning()` | `om.plans.create_learning()` | `id, input` | `id, input` | `object` |
| `om.plans.createLearningTasks()` | `om.plans.create_learning_tasks()` | `id, input` | `id, input` | `object` |
| `om.plans.createReferencePattern()` | `om.plans.create_reference_pattern()` | `id, pattern_id, title, description, category, status, required_before, source_count, linked_task_ids, linked_check_ids, sources, match_rules, anti_patterns, evidence_summary, waiver_reason` | `id, input` | `object` |
| `om.plans.createVerification()` | `om.plans.create_verification()` | `id, input` | `id, input` | `object` |
| `om.plans.delete()` | `om.plans.delete()` | `id, confirmed` | `id, confirmed` | `object` |
| `om.plans.deleteAssumption()` | `om.plans.delete_assumption()` | `id, assumption_id` | `id, assumption_id` | `object` |
| `om.plans.deleteCriterion()` | `om.plans.delete_criterion()` | `id, criterion_id` | `id, criterion_id` | `object` |
| `om.plans.deleteLearning()` | `om.plans.delete_learning()` | `id, learning_id` | `id, learning_id` | `object` |
| `om.plans.deleteReferencePattern()` | `om.plans.delete_reference_pattern()` | `id, pattern_id` | `id, pattern_id` | `object` |
| `om.plans.deleteVerification()` | `om.plans.delete_verification()` | `id, verification_id` | `id, verification_id` | `object` |
| `om.plans.getVerificationRun()` | `om.plans.get_verification_run()` | `id, verification_id, run_id` | `id, verification_id, run_id` | `object` |
| `om.plans.history()` | `om.plans.history()` | `id, limit` | `id, limit` | `list` |
| `om.plans.list()` | `om.plans.list()` | `status, chat_id, project_id, active_only` | `status, chat_id, project_id, active_only` | `list` |
| `om.plans.listAssumptions()` | `om.plans.list_assumptions()` | `id` | `id` | `list` |
| `om.plans.listCriteria()` | `om.plans.list_criteria()` | `id` | `id` | `list` |
| `om.plans.listLearnings()` | `om.plans.list_learnings()` | `id` | `id` | `list` |
| `om.plans.listReferencePatterns()` | `om.plans.list_reference_patterns()` | `id` | `id` | `list` |
| `om.plans.listVerifications()` | `om.plans.list_verifications()` | `id` | `id` | `list` |
| `om.plans.removeFromProject()` | `om.plans.remove_from_project()` | `id, project_id` | `id, project_id` | `object` |
| `om.plans.restore()` | `om.plans.restore()` | `id, entry_id, state` | `id, entry_id, state` | `object` |
| `om.plans.resume()` | `om.plans.resume()` | `id` | `id` | `object` |
| `om.plans.show()` | `om.plans.show()` | `id` | `id` | `object` |
| `om.plans.start()` | `om.plans.start()` | `id` | `id` | `object` |
| `om.plans.update()` | `om.plans.update()` | `id, input` | `id, input` | `object` |
| `om.plans.updateAssumption()` | `om.plans.update_assumption()` | `id, assumption_id, input` | `id, assumption_id, input` | `object` |
| `om.plans.updateCriterion()` | `om.plans.update_criterion()` | `id, criterion_id, input` | `id, criterion_id, input` | `object` |
| `om.plans.updateLearning()` | `om.plans.update_learning()` | `id, learning_id, input` | `id, learning_id, input` | `object` |
| `om.plans.updateReferencePattern()` | `om.plans.update_reference_pattern()` | `id, pattern_id, input` | `id, pattern_id, input` | `object` |
| `om.plans.updateVerification()` | `om.plans.update_verification()` | `id, verification_id, input` | `id, verification_id, input` | `object` |

## `projects`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.projects.archive()` | `om.projects.archive()` | `id, context` | `id, personal, team_id` | `object` |
| `om.projects.ask()` | `om.projects.ask()` | `instruction, create, update, updates, exact_delete, exact_deletes` | `instruction, create, update, updates, exact_delete, exact_deletes` | `object` |
| `om.projects.create()` | `om.projects.create()` | `name, slug, description, icon, color, pinned, archived, context` | `input, personal, team_id` | `object` |
| `om.projects.delete()` | `om.projects.delete()` | `id, confirmed` | `id, confirmed, personal, team_id` | `object` |
| `om.projects.history()` | `om.projects.history()` | `id, limit` | `id, limit, personal, team_id` | `list` |
| `om.projects.list()` | `om.projects.list()` | `include_archived` | `personal, team_id, include_archived` | `list` |
| `om.projects.restore()` | `om.projects.restore()` | `id, entry_id, state` | `id, entry_id, state, personal, team_id` | `object` |
| `om.projects.show()` | `om.projects.show()` | `id, context` | `id, personal, team_id` | `object` |
| `om.projects.unarchive()` | `om.projects.unarchive()` | `id, context` | `id, personal, team_id` | `object` |
| `om.projects.update()` | `om.projects.update()` | `id, input, context` | `id, input, personal, team_id` | `object` |

## `reminders`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.reminders.delete()` | `om.reminders.delete()` | `id, confirmed` | `id, confirmed` | `object` |
| `om.reminders.list()` | `om.reminders.list()` | `none` | `none` | `object` |
| `om.reminders.update()` | `om.reminders.update()` | `id, input` | `id, input` | `object` |

## `settings`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.settings.setChatAutoDelete()` | `om.settings.set_chat_auto_delete()` | `period` | `period` | `object` |
| `om.settings.setDarkMode()` | `om.settings.set_dark_mode()` | `enabled` | `enabled` | `object` |
| `om.settings.setFont()` | `om.settings.set_font()` | `font` | `font` | `object` |
| `om.settings.setLanguage()` | `om.settings.set_language()` | `language` | `language` | `object` |
| `om.settings.setModelDefaults()` | `om.settings.set_model_defaults()` | `default_ai_model_simple, default_ai_model_complex, default_ai_model_most_demanding` | `default_ai_model_simple, default_ai_model_complex, default_ai_model_most_demanding` | `object` |
| `om.settings.shareDebugLogs()` | `om.settings.share_debug_logs()` | `duration, confirmed` | `confirmed, duration` | `object` |

## `tasks`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.tasks.addToProject()` | `om.tasks.add_to_project()` | `id, project_id, input` | `id, project_id, input` | `object` |
| `om.tasks.ask()` | `om.tasks.ask()` | `instruction, create, creates, update, updates, exact_delete, exact_deletes` | `instruction, create, creates, update, updates, exact_delete, exact_deletes` | `object` |
| `om.tasks.block()` | `om.tasks.block()` | `id, reason, status, chat_id, project_id, plan_id, team_id, labels, tags, priority` | `id, reason, input` | `object` |
| `om.tasks.complete()` | `om.tasks.complete()` | `id, status, chat_id, project_id, plan_id, team_id, labels, tags, priority` | `id, input` | `object` |
| `om.tasks.create()` | `om.tasks.create()` | `input` | `input` | `object` |
| `om.tasks.delete()` | `om.tasks.delete()` | `id, confirmed, status, chat_id, project_id, plan_id, team_id, labels, tags, priority, input` | `id, confirmed, input` | `object` |
| `om.tasks.deleteById()` | `om.tasks.delete_by_id()` | `id, confirmed, status, chat_id, project_id, plan_id, team_id, labels, tags, priority, input` | `id, confirmed, input` | `object` |
| `om.tasks.done()` | `om.tasks.done()` | `id, status, chat_id, project_id, plan_id, team_id, labels, tags, priority` | `id, input` | `object` |
| `om.tasks.edit()` | `om.tasks.edit()` | `id, input, status, chat_id, project_id, plan_id, team_id, labels, tags, priority` | `id, input, input` | `object` |
| `om.tasks.history()` | `om.tasks.history()` | `id, status, chat_id, project_id, plan_id, team_id, labels, tags, priority, limit` | `id, limit, input` | `list` |
| `om.tasks.list()` | `om.tasks.list()` | `status, chat_id, project_id, plan_id, team_id, labels, tags, priority` | `status, chat_id, project_id, plan_id, labels, tags, priority, team_id` | `list` |
| `om.tasks.move()` | `om.tasks.move()` | `id, move, status, chat_id, project_id, plan_id, team_id, labels, tags, priority` | `id, move, input` | `list` |
| `om.tasks.removeFromProject()` | `om.tasks.remove_from_project()` | `id, project_id, input` | `id, project_id, input` | `object` |
| `om.tasks.reorder()` | `om.tasks.reorder()` | `id, move, status, chat_id, project_id, plan_id, team_id, labels, tags, priority` | `id, move, input` | `list` |
| `om.tasks.restore()` | `om.tasks.restore()` | `id, entry_id, state, input` | `id, entry_id, state, input` | `object` |
| `om.tasks.show()` | `om.tasks.show()` | `id, status, chat_id, project_id, plan_id, team_id, labels, tags, priority` | `id, input` | `object` |
| `om.tasks.skip()` | `om.tasks.skip()` | `id, status, chat_id, project_id, plan_id, team_id, labels, tags, priority` | `id, input` | `object` |
| `om.tasks.start()` | `om.tasks.start()` | `id, status, chat_id, project_id, plan_id, team_id, labels, tags, priority` | `id, input` | `object` |
| `om.tasks.startAI()` | `om.tasks.start_ai()` | `id, status, chat_id, project_id, plan_id, team_id, labels, tags, priority` | `id, input` | `object` |
| `om.tasks.unblock()` | `om.tasks.unblock()` | `id, status, chat_id, project_id, plan_id, team_id, labels, tags, priority` | `id, input` | `object` |
| `om.tasks.update()` | `om.tasks.update()` | `id, input, status, chat_id, project_id, plan_id, team_id, labels, tags, priority` | `id, input, input` | `object` |

## `teams`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.teams.acceptInvite()` | `om.teams.accept_invite()` | `invite_id, input` | `invite_id, input` | `object` |
| `om.teams.accessRequests()` | `om.teams.access_requests()` | `id, status` | `id, status` | `list` |
| `om.teams.approveAccess()` | `om.teams.approve_access()` | `id, access_request_id, input` | `id, access_request_id, input` | `object` |
| `om.teams.bankTransferStatus()` | `om.teams.bank_transfer_status()` | `id, order_id` | `id, order_id` | `object` |
| `om.teams.billing()` | `om.teams.billing()` | `id` | `id` | `object` |
| `om.teams.create()` | `om.teams.create()` | `input` | `input` | `object` |
| `om.teams.createBankTransferOrder()` | `om.teams.create_bank_transfer_order()` | `id, credits, email_encryption_key` | `id, credits, email_encryption_key` | `object` |
| `om.teams.createPlain()` | `om.teams.create_plain()` | `name, description, slug, id, profile, created_at` | `input, id, input` | `object` |
| `om.teams.declineInvite()` | `om.teams.decline_invite()` | `invite_id, input` | `invite_id, input` | `object` |
| `om.teams.export()` | `om.teams.export()` | `id, input` | `id, input` | `object` |
| `om.teams.get()` | `om.teams.get()` | `id` | `id` | `object` |
| `om.teams.getProfileImage()` | `om.teams.get_profile_image()` | `id` | `id` | `object` |
| `om.teams.import()` | `om.teams.import_team()` | `input` | `input` | `object` |
| `om.teams.invite()` | `om.teams.invite()` | `id, input` | `id, input` | `object` |
| `om.teams.list()` | `om.teams.list()` | `none` | `none` | `list` |
| `om.teams.listBankTransferOrders()` | `om.teams.list_bank_transfer_orders()` | `id` | `id` | `object` |
| `om.teams.memories()` | `om.teams.memories()` | `id` | `id` | `list` |
| `om.teams.rejectAccess()` | `om.teams.reject_access()` | `id, access_request_id, input` | `id, access_request_id, input` | `object` |
| `om.teams.removeMember()` | `om.teams.remove_member()` | `id, member_user_id, input` | `id, member_user_id, input` | `object` |
| `om.teams.update()` | `om.teams.update()` | `id, input` | `id, input` | `object` |
| `om.teams.updateGeneratedProfileImage()` | `om.teams.update_generated_profile_image()` | `id, icon_name, background_color` | `id, input, input` | `object` |
| `om.teams.usage()` | `om.teams.usage()` | `id, member_user_id` | `id, member_user_id` | `list` |

## `wikipedia`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.wikipedia.search()` | `om.wikipedia.search()` | `input, language, limit` | `input, language, limit` | `object` |
| `om.wikipedia.summary()` | `om.wikipedia.summary()` | `title, language` | `title, language` | `object` |

## `workflows`

| npm | pip | npm inputs | pip inputs | Return |
| --- | --- | --- | --- | --- |
| `om.workflows.addToProject()` | `om.workflows.add_to_project()` | `id, project_id, folder` | `id, project_id, folder` | `object` |
| `om.workflows.ask()` | `om.workflows.ask()` | `instruction, create, exact_update, exact_action, selected_object_id` | `instruction, create, exact_update, exact_action, selected_object_id` | `object` |
| `om.workflows.cancelRun()` | `om.workflows.cancel_run()` | `id, run_id` | `id, run_id` | `object` |
| `om.workflows.capabilities()` | `om.workflows.capabilities()` | `none` | `none` | `list` |
| `om.workflows.completeImportedBinding()` | `om.workflows.complete_imported_binding()` | `id, input` | `id, binding_type, node_id` | `object` |
| `om.workflows.create()` | `om.workflows.create()` | `title, slug, description, graph, enabled, run_content_retention, lifecycle, source, source_chat_id, created_by_assistant, auto_delete_at` | `title, description, graph, enabled, run_content_retention, lifecycle, source, slug, source_chat_id, created_by_assistant, auto_delete_at` | `object` |
| `om.workflows.createFromYaml()` | `om.workflows.create_from_yaml()` | `source` | `source` | `object` |
| `om.workflows.createTemplateShortUrl()` | `om.workflows.create_template_short_url()` | `input` | `token, encrypted_url, template_id, ttl_seconds, password_protected` | `object` |
| `om.workflows.delete()` | `om.workflows.delete()` | `id, confirmed` | `id, confirmed` | `object` |
| `om.workflows.disable()` | `om.workflows.disable()` | `id` | `id` | `object` |
| `om.workflows.enable()` | `om.workflows.enable()` | `id` | `id` | `object` |
| `om.workflows.followUpInput()` | `om.workflows.follow_up_input()` | `session_id, text` | `session_id, text` | `object` |
| `om.workflows.get()` | `om.workflows.get()` | `id` | `id` | `object` |
| `om.workflows.getPublicTemplateProjection()` | `om.workflows.get_public_template_projection()` | `template_id` | `template_id` | `object` |
| `om.workflows.history()` | `om.workflows.history()` | `id, limit` | `id, limit` | `list` |
| `om.workflows.importTemplate()` | `om.workflows.import_template()` | `input` | `input` | `object` |
| `om.workflows.inputEvents()` | `om.workflows.input_events()` | `session_id, after_event_id` | `session_id, after_event_id` | `list` |
| `om.workflows.inputSession()` | `om.workflows.input_session()` | `session_id` | `session_id` | `object` |
| `om.workflows.keep()` | `om.workflows.keep()` | `id` | `id` | `object` |
| `om.workflows.list()` | `om.workflows.list()` | `none` | `none` | `list` |
| `om.workflows.removeFromProject()` | `om.workflows.remove_from_project()` | `id, project_id` | `id, project_id` | `object` |
| `om.workflows.respond()` | `om.workflows.respond()` | `id, run_id, step_id, input` | `id, run_id, step_id, input` | `object` |
| `om.workflows.restore()` | `om.workflows.restore()` | `id, entry_id, state` | `id, entry_id, state` | `object` |
| `om.workflows.revokeShortUrl()` | `om.workflows.revoke_short_url()` | `token` | `token` | `object` |
| `om.workflows.revokeTemplateProjection()` | `om.workflows.revoke_template_projection()` | `id` | `id` | `object` |
| `om.workflows.run()` | `om.workflows.run()` | `id, idempotency_key, mode, input` | `id, idempotency_key, mode, input` | `object` |
| `om.workflows.runDetail()` | `om.workflows.run_detail()` | `id, run_id` | `id, run_id` | `object` |
| `om.workflows.runs()` | `om.workflows.runs()` | `id` | `id` | `list` |
| `om.workflows.startInput()` | `om.workflows.start_input()` | `input` | `text, input_type, audio_ref, selected_workflow_id, selected_project_id` | `object` |
| `om.workflows.stepTest()` | `om.workflows.step_test()` | `id, step_id, input, confirmed` | `id, step_id, input, confirmed` | `object` |
| `om.workflows.stopInput()` | `om.workflows.stop_input()` | `session_id` | `session_id` | `object` |
| `om.workflows.temporary()` | `om.workflows.temporary()` | `none` | `none` | `list` |
| `om.workflows.undoInput()` | `om.workflows.undo_input()` | `session_id` | `session_id` | `object` |
| `om.workflows.unrevokeTemplateProjection()` | `om.workflows.unrevoke_template_projection()` | `id` | `id` | `object` |
| `om.workflows.update()` | `om.workflows.update()` | `id, title, slug, description, graph, enabled, run_content_retention` | `id, title, description, graph, enabled, run_content_retention, slug` | `object` |
| `om.workflows.updateFromYaml()` | `om.workflows.update_from_yaml()` | `id, source` | `id, source` | `object` |
| `om.workflows.upsertTemplateProjection()` | `om.workflows.upsert_template_projection()` | `id, input` | `id, template_id, source_version, ciphertext, ciphertext_checksum, owner_wrapped_key, projection_schema_version` | `object` |
| `om.workflows.validateYaml()` | `om.workflows.validate_yaml()` | `source` | `source` | `object` |
