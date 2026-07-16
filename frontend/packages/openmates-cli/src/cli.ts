#!/usr/bin/env node
/*
 * OpenMates CLI command entry.
 *
 * Purpose: provide pair-auth login, chat, app, and settings/memories commands.
 * Architecture: argument router over the OpenMatesClient SDK.
 * Architecture doc: docs/architecture/openmates-cli.md
 * Security: login never prompts for account credentials, only pair PIN.
 * Tests: frontend/packages/openmates-cli/tests/
 */

import {
  OpenMatesClient,
  INTEREST_TAG_IDS,
  MEMORY_TYPE_REGISTRY,
  MATE_NAMES,
  deriveAppUrl,
  type ChatListPage,
  type ChatListItem,
  type DecryptedMessage,
  type DailyInspiration,
  type DecryptedNewChatSuggestion,
  type DocsTree,
  type LearningModeContext,
  type LearningModeAgeGroup,
  type LearningModeStatus,
  type SubChatApprovalRequest,
  type ApiKeyListResult,
  type BankTransferOrderDetails,
  type BankTransferStatus,
  type GiftCardBankTransferStatus,
  type TopicPreferencesPayload,
  type WorkflowCapability,
  type WorkflowDetail,
  type WorkflowGraph,
  type WorkflowInputSessionResult,
  type WorkflowRunDetail,
  type WorkflowRunContentRetention,
  type WorkflowSummary,
  type UserTaskActionInput,
  type UserTaskReorderInput,
  type UserTaskStatus,
} from "./client.js";
import { OpenMates, type ChatResponse, type EncryptedChatMetadata } from "./sdk.js";
import type { PendingTaskUpdateJobFrame, StreamEvent, SubChatEvent, TaskEventFrame } from "./ws.js";
import { createInterface } from "node:readline/promises";
import { stdin, stdout } from "node:process";
import { readFileSync, realpathSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { basename, dirname } from "node:path";
import { randomUUID } from "node:crypto";
import WebSocket from "ws";

import {
  parseMentions,
  listMentionOptions,
  type MentionType,
} from "./mentions.js";
import { APP_SKILL_METADATA } from "./generated/appSkills.js";
import { OutputRedactor } from "./outputRedactor.js";
import { processFiles, formatEmbedsForMessage } from "./fileEmbed.js";
import type { PreparedEmbed } from "./embedCreator.js";
import type { ShareDuration } from "./shareEncryption.js";
import { transcribeUploadedAudio, uploadFile } from "./uploadService.js";
import { createEmbedRef, createEmbedReferenceBlock, toonEncodeContent } from "./embedCreator.js";
import { prepareUrlEmbeds } from "./urlEmbed.js";
import { renderEmbedPreview, renderEmbedFullscreen } from "./embedRenderers.js";
import { handleServer, printServerHelp } from "./server.js";
import {
  buildCodeRunRequestsFromFlags,
  buildCodeRunStreamUrl,
} from "./codeRunInput.js";
import {
  getExampleChatConversation,
  listExampleChatsForApp,
  listExampleChatsForSkill,
  listExampleChats,
  searchExampleChats,
  type ExampleChatConversation,
  type ExampleChatSkillListItem,
} from "./exampleChats.js";
import {
  formatInteractiveQuestionAnswer,
  parseInteractiveQuestionBlock,
  toWaitingForUserResult,
  type InteractiveQuestionAnswer,
  type InteractiveQuestionPayload,
  type WaitingForUserResult,
} from "./interactiveQuestions.js";
import { buildAssistantFeedbackDecision } from "./feedback.js";
import { handleBenchmark, printBenchmarkHelp } from "./benchmark.js";
import { defaultModeForStreams, printProgrammaticQuickstart, runTui } from "./tui.js";
import { SUPPORT_MESSAGE, SUPPORT_URL, renderSupportInfo } from "./support.js";
import {
  listRemoteAccessSources,
  runRgCommand,
  searchStoredRemoteAccessSource,
  startRemoteAccessSource,
  type RemoteAccessSourceRecord,
} from "./remoteAccess.js";
import { buildProtonWriteWarning, runProtonBridgeConnector } from "./protonBridgeConnector.js";
import { buildSelfUpdatePlan, checkSelfUpdateStatus, runSelfUpdate } from "./selfUpdate.js";
import { renderOpenMatesAsciiLogo } from "./branding.js";
import {
  buildCreateUserTaskInput,
  buildUpdateUserTaskInput,
  decryptUserTask,
  decryptUserTasks,
  findTask,
  normalizeTaskStatus,
  parseDueAt,
  renderTaskBoard,
  renderTaskDetail,
  renderTaskList,
  splitCsvFlag,
  type DecryptedUserTask,
} from "./tasksCli.js";

type SignupRequiredResult = {
  status: "signup_required";
  reason: "file_upload_requires_signup";
  signup_required: true;
  message: string;
};

type CliArgs = {
  positionals: string[];
  flags: Record<string, string | boolean>;
};

async function main(): Promise<void> {
  const parsed = parseArgs(process.argv.slice(2));
  const [command, subcommand, ...rest] = parsed.positionals;
  const client = OpenMatesClient.load({
    apiUrl:
      typeof parsed.flags["api-url"] === "string"
        ? parsed.flags["api-url"]
        : undefined,
  });

  const redactor = new OutputRedactor();
  const piiDetectionEnabled = parsed.flags["no-pii-detection"] !== true;
  if (piiDetectionEnabled && shouldInitializeRedactor(command, subcommand)) {
    try {
      const memories = client.hasSession() ? await client.listMemories() : [];
      redactor.initializeFromMemories(memories);
    } catch {
      // Keep high-confidence pattern detection active even if memory loading fails.
      redactor.initializeFromMemories([]);
    }
  }

  if (!command) {
    if (parsed.flags.version !== undefined) {
      handleCliVersion(parsed.flags);
      return;
    }
    if (parsed.flags.help === true) {
      printHelp();
      return;
    }
    if (defaultModeForStreams(process.stdin, process.stdout) === "quickstart") {
      printProgrammaticQuickstart();
      return;
    }
    const result = await runTui(client);
    if (result.action === "signup") {
      await handleSignup(client, parsed.flags);
    }
    return;
  }

  if (command === "help") {
    printHelp();
    return;
  }

  if (command === "version") {
    if (parsed.flags.help === true) {
      printVersionHelp();
      return;
    }
    handleCliVersion(parsed.flags);
    return;
  }

  // --help with a command shows that command's help, not the global one
  if (parsed.flags.help === true && !subcommand) {
    // e.g. `openmates chats --help` → show chats help
    if (command === "chats") {
      printChatsHelp();
      return;
    }
    if (command === "drafts") {
      printDraftsHelp();
      return;
    }
    if (command === "apps") {
      printAppsHelp();
      return;
    }
    if (command === "settings") {
      printSettingsHelp(client);
      return;
    }
    if (command === "workflows") {
      printWorkflowsHelp();
      return;
    }
    if (command === "tasks") {
      printTasksHelp();
      return;
    }
    if (command === "connected-accounts") {
      printConnectedAccountsHelp();
      return;
    }
    if (command === "connect-account") {
      printConnectAccountHelp();
      return;
    }
    if (command === "learning-mode") {
      printLearningModeHelp();
      return;
    }
    if (command === "signup") {
      printSignupHelp();
      return;
    }
    if (command === "e2e") {
      printE2EHelp();
      return;
    }
    if (command === "mentions") {
      printMentionsHelp();
      return;
    }
    if (command === "embeds") {
      printEmbedsHelp();
      return;
    }
    if (command === "inspirations") {
      printInspirationsHelp();
      return;
    }
    if (command === "newchatsuggestions") {
      printNewChatSuggestionsHelp();
      return;
    }
    if (command === "server") {
      printServerHelp();
      return;
    }
    if (command === "update" || command === "upgrade") {
      printSelfUpdateHelp();
      return;
    }
    if (command === "version") {
      printVersionHelp();
      return;
    }
    if (command === "feedback") {
      printFeedbackHelp();
      return;
    }
    if (command === "docs") {
      printDocsHelp();
      return;
    }
    if (command === "benchmark") {
      printBenchmarkHelp();
      return;
    }
    if (command === "remote-access") {
      printRemoteAccessHelp();
      return;
    }
    if (command === "connect-account") {
      printConnectAccountHelp();
      return;
    }
    printHelp();
    return;
  }

  // Server and docs commands don't need login
  if (command === "server") {
    await handleServer(subcommand, rest, parsed.flags);
    return;
  }

  if (command === "docs") {
    await handleDocs(client, subcommand, rest, parsed.flags);
    return;
  }

  if (command === "support") {
    handleSupport(parsed.flags);
    return;
  }

  if (command === "update" || command === "upgrade") {
    handleSelfUpdate(command, parsed.flags);
    return;
  }

  if (command === "login") {
    await client.loginWithPairAuth();
    console.log("Login successful.");
    return;
  }

  if (command === "signup") {
    await handleSignup(client, parsed.flags);
    return;
  }

  if (command === "e2e") {
    await handleE2E(client, subcommand, rest, parsed.flags);
    return;
  }

  if (command === "logout") {
    await client.logout();
    console.log("Logged out.");
    return;
  }

  if (command === "whoami") {
    const user = await client.whoAmI();
    if (parsed.flags.json === true) {
      printJson(user);
    } else {
      printWhoAmI(user as Record<string, unknown>);
    }
    return;
  }

  if (command === "chats") {
    await handleChats(client, subcommand, rest, parsed.flags, redactor);
    return;
  }

  if (command === "tasks") {
    await handleTasks(client, subcommand, rest, parsed.flags);
    return;
  }

  if (command === "drafts") {
    await handleDrafts(client, subcommand, rest, parsed.flags);
    return;
  }

  if (command === "apps") {
    await handleApps(client, subcommand, rest, parsed.flags);
    return;
  }

  if (command === "mentions") {
    await handleMentions(client, subcommand, rest, parsed.flags);
    return;
  }

  if (command === "embeds") {
    await handleEmbeds(client, subcommand, rest, parsed.flags);
    return;
  }

  if (command === "settings") {
    await handleSettings(client, subcommand, rest, parsed.flags);
    return;
  }

  if (command === "workflows") {
    await handleWorkflows(client, subcommand, rest, parsed.flags);
    return;
  }

  if (command === "connected-accounts") {
    await handleConnectedAccounts(client, subcommand, parsed.flags);
    return;
  }

  if (command === "connect-account") {
    await handleConnectAccount(client, subcommand, rest, parsed.flags);
    return;
  }

  if (command === "learning-mode") {
    await handleLearningMode(client, subcommand, parsed.flags);
    return;
  }

  if (command === "inspirations") {
    await handleInspirations(client, parsed.flags);
    return;
  }

  if (command === "newchatsuggestions") {
    await handleNewChatSuggestions(client, parsed.flags);
    return;
  }

  if (command === "feedback") {
    handleFeedback(subcommand, rest, parsed.flags);
    return;
  }

  if (command === "benchmark") {
    await handleBenchmark(client, subcommand, rest, parsed.flags);
    return;
  }

  if (command === "remote-access") {
    await handleRemoteAccess(client, subcommand, rest, parsed.flags);
    return;
  }

  throw new Error(`Unknown command '${command}'. Run 'openmates help'.`);
}

function handleSupport(flags: Record<string, string | boolean>): void {
  if (flags.json === true) {
    printJson({
      url: SUPPORT_URL,
      voluntary: true,
      message: SUPPORT_MESSAGE,
    });
    return;
  }

  console.log(renderSupportInfo());
}

function handleSelfUpdate(command: string, flags: Record<string, string | boolean>): void {
  const plan = buildSelfUpdatePlan(flags);
  const status = checkSelfUpdateStatus(plan);
  const shouldInstall = status.updateAvailable !== false;
  if (flags.json === true) {
    if (!plan.dryRun && shouldInstall) runSelfUpdate(plan, { verbose: flags.verbose === true });
    printJson({
      command,
      status: status.updateAvailable === false ? "up_to_date" : plan.dryRun ? "planned" : "success",
      current_version: plan.currentVersion,
      latest_version: status.latestVersion,
      update_available: status.updateAvailable,
      check_error: status.checkError,
      package_manager: plan.packageManager,
      package: plan.packageSpec,
      run: [plan.command, ...plan.args],
      dry_run: plan.dryRun,
    });
    return;
  }
  console.log(renderOpenMatesAsciiLogo());
  console.log("");
  console.log("Checking for updates...");
  console.log("");
  console.log(`Current version: ${plan.currentVersion}`);
  console.log(`Latest version:  ${status.latestVersion ?? "unknown"}`);
  if (status.checkError) {
    console.log(`Update check failed: ${status.checkError}`);
  }
  console.log("");
  if (plan.dryRun) {
    if (status.updateAvailable === false) {
      console.log("OpenMates CLI is already up to date.");
      return;
    }
    console.log(`Would run: ${[plan.command, ...plan.args].join(" ")}`);
    return;
  }
  if (status.updateAvailable === false) {
    console.log("OpenMates CLI is already up to date.");
    return;
  }
  console.log(`Updating OpenMates CLI with ${plan.packageManager}...`);
  runSelfUpdate(plan, { verbose: flags.verbose === true });
  console.log(`Installed OpenMates CLI ${status.latestVersion ?? plan.target}.`);
  console.log("");
  console.log("OpenMates is up to date.");
}

function handleCliVersion(flags: Record<string, string | boolean>): void {
  const planFlags: Record<string, string | boolean> = { ...flags, "dry-run": true };
  if (planFlags.version === true) delete planFlags.version;
  const plan = buildSelfUpdatePlan(planFlags);
  const status = checkSelfUpdateStatus(plan);
  if (flags.json === true) {
    printJson({
      command: "version",
      current_version: status.currentVersion,
      latest_version: status.latestVersion,
      update_available: status.updateAvailable,
      check_error: status.checkError,
      upgrade_command: status.updateAvailable ? "openmates upgrade" : null,
    });
    return;
  }
  console.log(`OpenMates CLI ${status.currentVersion}`);
  if (status.checkError) {
    console.log(`Update check failed: ${status.checkError}`);
    return;
  }
  if (status.updateAvailable) {
    console.log(`Update available: ${status.latestVersion}`);
    console.log("Run: openmates upgrade");
    return;
  }
  console.log("OpenMates CLI is up to date.");
}

// ---------------------------------------------------------------------------
// User tasks
// ---------------------------------------------------------------------------

async function handleTasks(
  client: OpenMatesClient,
  subcommand: string | undefined,
  rest: string[],
  flags: Record<string, string | boolean>,
): Promise<void> {
  if (!subcommand || subcommand === "help" || flags.help === true) {
    printTasksHelp();
    return;
  }

  const masterKey = client.getMasterKeyBytes();
  const scope = taskScopeFromFlags(flags);

  if (subcommand === "list" || subcommand === "status") {
    if (subcommand === "status" && rest[0]) {
      const task = await resolveTask(client, masterKey, rest[0], scope);
      printTaskOutput(task, flags);
      return;
    }
    const tasks = await loadTasks(client, masterKey, scope);
    if (flags.json === true) printJson({ tasks: tasks.map(taskToJson) });
    else console.log(renderTaskList(tasks));
    return;
  }

  if (subcommand === "board") {
    const tasks = await loadTasks(client, masterKey, scope);
    if (flags.json === true) printJson({ tasks: tasks.map(taskToJson) });
    else console.log(renderTaskBoard(tasks));
    return;
  }

  if (subcommand === "show") {
    const id = rest[0];
    if (!id) throw new Error("Missing task ID. Usage: openmates tasks show <task-id>");
    const task = await resolveTask(client, masterKey, id, scope);
    printTaskOutput(task, flags);
    return;
  }

  if (subcommand === "create") {
    const title = taskTitleFromFlagsOrRest(flags, rest);
    const input = await buildCreateUserTaskInput(masterKey, {
      title,
      description: typeof flags.description === "string" ? flags.description : "",
      status: normalizeTaskStatus(typeof flags.status === "string" ? flags.status : undefined),
      assign: taskAssignFlag(flags),
      chatId: typeof flags.chat === "string" ? flags.chat : null,
      projectIds: splitCsvFlag(flags.project ?? flags.projects),
      planId: typeof flags.plan === "string" ? flags.plan : null,
      dueAt: parseDueAt(flags.due),
    });
    const created = await client.createUserTask(input);
    printTaskOutput(await decryptUserTask(created, masterKey), flags);
    return;
  }

  if (subcommand === "edit") {
    const id = rest[0];
    if (!id) throw new Error("Missing task ID. Usage: openmates tasks edit <task-id> [--title ...]");
    const task = await resolveTask(client, masterKey, id, scope);
    const patch = await buildUpdateUserTaskInput(task, masterKey, {
      title: typeof flags.title === "string" ? flags.title : undefined,
      description: typeof flags.description === "string" ? flags.description : undefined,
      status: normalizeTaskStatus(typeof flags.status === "string" ? flags.status : undefined),
      assign: taskAssignFlag(flags),
      chatId: flags.chat === true ? null : typeof flags.chat === "string" ? flags.chat : undefined,
      projectIds: flags.project || flags.projects ? splitCsvFlag(flags.project ?? flags.projects) : undefined,
      planId: flags.plan === true ? null : typeof flags.plan === "string" ? flags.plan : undefined,
    });
    const updated = await client.updateUserTask(task.taskId, patch);
    printTaskOutput(await decryptUserTask(updated, masterKey), flags);
    return;
  }

  if (subcommand === "delete") {
    const task = await requiredResolvedTask(client, masterKey, rest[0], scope, "delete");
    if (flags.confirm !== true) throw new Error("Deleting a task requires --confirm.");
    const result = await client.deleteUserTask(task.taskId, task.version);
    if (flags.json === true) printJson(result);
    else console.log(`Task deleted: ${task.shortId}`);
    return;
  }

  if (subcommand === "start") {
    const task = await requiredResolvedTask(client, masterKey, rest[0], scope, "start");
    const started = await client.startUserTaskWithAI(task.taskId, {
      version: task.version,
      primary_chat_id: task.primaryChatId ?? undefined,
      linked_project_ids: task.linkedProjectIds,
      plaintext_title: task.title,
      plaintext_description: task.description,
      plaintext_latest_instruction: task.latestInstruction,
    });
    printTaskOutput(await decryptUserTask(started, masterKey), flags);
    return;
  }

  if (["block", "unblock", "skip", "done"].includes(subcommand)) {
    const task = await requiredResolvedTask(client, masterKey, rest[0], scope, subcommand);
    const payload: UserTaskActionInput = { version: task.version };
    if (subcommand === "block") {
      if (typeof flags.reason !== "string") throw new Error("Blocking a task requires --reason <code>.");
      payload.blocked_reason_code = flags.reason;
    }
    const updated = subcommand === "block"
      ? await client.blockUserTask(task.taskId, payload)
      : subcommand === "unblock"
        ? await client.unblockUserTask(task.taskId, payload)
        : subcommand === "skip"
          ? await client.skipUserTask(task.taskId, payload)
          : await client.completeUserTask(task.taskId, payload);
    printTaskOutput(await decryptUserTask(updated, masterKey), flags);
    return;
  }

  if (subcommand === "reorder") {
    const task = await requiredResolvedTask(client, masterKey, rest[0], scope, "reorder");
    const move: UserTaskReorderInput["moves"][number] = { task_id: task.taskId, version: task.version };
    if (typeof flags.before === "string") move.before_task_id = (await resolveTask(client, masterKey, flags.before, scope)).taskId;
    if (typeof flags.after === "string") move.after_task_id = (await resolveTask(client, masterKey, flags.after, scope)).taskId;
    if (typeof flags.status === "string") move.status = normalizeTaskStatus(flags.status);
    if (typeof flags.position === "string") move.position = Number(flags.position);
    const updated = await client.reorderUserTasks({ moves: [move] });
    const decrypted = await decryptUserTasks(updated, masterKey);
    if (flags.json === true) printJson({ tasks: decrypted.map(taskToJson) });
    else console.log(`Task reordered: ${task.shortId}`);
    return;
  }

  throw new Error(`Unknown tasks command '${subcommand}'. Run 'openmates tasks --help'.`);
}

function taskScopeFromFlags(flags: Record<string, string | boolean>): { status?: UserTaskStatus; chatId?: string; projectId?: string; planId?: string } {
  return {
    status: normalizeTaskStatus(typeof flags.status === "string" ? flags.status : undefined),
    chatId: typeof flags.chat === "string" ? flags.chat : undefined,
    projectId: typeof flags.project === "string" ? flags.project : undefined,
    planId: typeof flags.plan === "string" ? flags.plan : undefined,
  };
}

async function loadTasks(
  client: OpenMatesClient,
  masterKey: Uint8Array,
  scope: { status?: UserTaskStatus; chatId?: string; projectId?: string; planId?: string },
): Promise<DecryptedUserTask[]> {
  const records = await client.listUserTasks({ status: scope.status, chatId: scope.chatId, projectId: scope.projectId });
  const tasks = await decryptUserTasks(records, masterKey);
  return scope.planId ? tasks.filter((task) => task.planId === scope.planId) : tasks;
}

async function resolveTask(
  client: OpenMatesClient,
  masterKey: Uint8Array,
  id: string,
  scope: { status?: UserTaskStatus; chatId?: string; projectId?: string; planId?: string },
): Promise<DecryptedUserTask> {
  return findTask(await loadTasks(client, masterKey, { ...scope, status: undefined }), id);
}

async function requiredResolvedTask(
  client: OpenMatesClient,
  masterKey: Uint8Array,
  id: string | undefined,
  scope: { status?: UserTaskStatus; chatId?: string; projectId?: string; planId?: string },
  action: string,
): Promise<DecryptedUserTask> {
  if (!id) throw new Error(`Missing task ID. Usage: openmates tasks ${action} <task-id>`);
  return resolveTask(client, masterKey, id, scope);
}

function printTaskOutput(task: DecryptedUserTask, flags: Record<string, string | boolean>): void {
  if (flags.json === true) printJson({ task: taskToJson(task) });
  else console.log(renderTaskDetail(task));
}

function taskToJson(task: DecryptedUserTask): Record<string, unknown> {
  return {
    task_id: task.taskId,
    short_id: task.shortId,
    title: task.title,
    description: task.description,
    tags: task.tags,
    latest_instruction: task.latestInstruction,
    status: task.status,
    assignee_type: task.assigneeType,
    assignee_hash: task.assigneeHash,
    primary_chat_id: task.primaryChatId,
    linked_project_ids: task.linkedProjectIds,
    plan_id: task.planId,
    due_at: task.dueAt,
    priority: task.priority,
    position: task.position,
    queue_state: task.queueState,
    blocked_reason_code: task.blockedReasonCode,
    ai_execution_state: task.aiExecutionState,
    version: task.version,
  };
}

function taskTitleFromFlagsOrRest(flags: Record<string, string | boolean>, rest: string[]): string {
  const title = typeof flags.title === "string" ? flags.title : rest.join(" ").trim();
  if (!title) throw new Error("Missing task title. Usage: openmates tasks create --title <title>");
  return title;
}

function taskAssignFlag(flags: Record<string, string | boolean>): string | undefined {
  return typeof flags.assign === "string" ? flags.assign : typeof flags.assignee === "string" ? flags.assignee : undefined;
}

async function handleRemoteAccess(
  client: OpenMatesClient,
  subcommand: string | undefined,
  rest: string[],
  flags: Record<string, string | boolean>,
): Promise<void> {
  if (!subcommand || subcommand === "help" || flags.help === true) {
    printRemoteAccessHelp();
    return;
  }

  if (subcommand === "start") {
    const rootPath = typeof flags.path === "string" ? flags.path : rest[0];
    if (!rootPath) {
      throw new Error("Missing source path. Usage: openmates remote-access start --path <folder>");
    }
    const sourceId = typeof flags["source-id"] === "string" ? flags["source-id"] : randomUUID();
    const projectId = typeof flags.project === "string" ? flags.project : undefined;
    validateRemoteSourceRegistrationFlags(projectId, flags);
    const sourceType = parseRemoteAccessSourceType(flags.type);
    const displayName = typeof flags.name === "string" ? flags.name : sourceId;
    const source = startRemoteAccessSource({ sourceId, projectId, rootPath, sourceType, displayName });
    await maybeRegisterRemoteSource(client, source, flags);
    if (flags.json === true) {
      printJson({ source });
    } else {
      console.log(`Remote source attached: ${source.sourceId}`);
      console.log(`Root: ${source.rootPath}`);
      console.log(`Cache: ${source.cachePath}`);
    }
    return;
  }

  if (subcommand === "status" || subcommand === "list") {
    const sources = listRemoteAccessSources();
    if (flags.json === true) {
      printJson({ sources });
    } else if (sources.length === 0) {
      console.log("No remote sources attached.");
    } else {
      for (const source of sources) {
        console.log(`${source.sourceId}\t${source.status}\t${source.rootPath}`);
      }
    }
    return;
  }

  if (subcommand === "search") {
    const sourceId = typeof flags.source === "string" ? flags.source : rest[0];
    const query = typeof flags.source === "string" ? rest.join(" ").trim() : rest.slice(1).join(" ").trim();
    if (!sourceId || !query) {
      throw new Error("Missing source or query. Usage: openmates remote-access search --source <id> <query>");
    }
    const maxResults = parsePositiveIntegerFlag(flags.limit, "--limit");
    const result = await searchStoredRemoteAccessSource({ sourceId, query, maxResults, runRg: runRgCommand });
    if (flags.json === true) {
      printJson(result);
    } else {
      for (const match of result.matches) {
        console.log(`${match.path}:${match.line}: ${match.snippet.trim()}`);
      }
      if (result.excluded > 0 || result.omitted > 0) {
        console.log(`Excluded ${result.excluded}, omitted ${result.omitted}.`);
      }
    }
    return;
  }

  throw new Error(`Unknown remote-access command '${subcommand}'. Run 'openmates remote-access --help'.`);
}

function parsePositiveIntegerFlag(value: string | boolean | undefined, flagName: string): number | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "string") {
    throw new Error(`${flagName} requires a positive integer value`);
  }
  const parsed = Number.parseInt(value, 10);
  if (!Number.isInteger(parsed) || parsed <= 0 || String(parsed) !== value) {
    throw new Error(`${flagName} must be a positive integer`);
  }
  return parsed;
}

function parseResponseTimeoutMs(flags: Record<string, string | boolean>): number | undefined {
  const seconds = parsePositiveIntegerFlag(flags["response-timeout-seconds"], "--response-timeout-seconds");
  return seconds === undefined ? undefined : seconds * 1000;
}

function parseRemoteAccessSourceType(value: string | boolean | undefined): RemoteAccessSourceRecord["sourceType"] {
  if (value === undefined) return "local_folder";
  if (value === "local_folder" || value === "local_git_repository") {
    return value;
  }
  throw new Error("--type must be one of local_folder or local_git_repository for the local remote-access bridge");
}

async function maybeRegisterRemoteSource(
  client: OpenMatesClient,
  source: RemoteAccessSourceRecord,
  flags: Record<string, string | boolean>,
): Promise<void> {
  if (!source.projectId || flags["local-only"] === true) return;
  const encryptedDisplayName = flags["encrypted-display-name"];
  const encryptedMetadata = flags["encrypted-metadata"];
  if (typeof encryptedDisplayName !== "string" || typeof encryptedMetadata !== "string") {
    throw new Error("Missing encrypted Project source metadata after registration validation");
  }
  const timestamp = Math.floor(Date.now() / 1000);
  await client.createProjectSource(source.projectId, {
    source_id: source.sourceId,
    source_type: source.sourceType,
    encrypted_display_name: encryptedDisplayName,
    encrypted_metadata: encryptedMetadata,
    capabilities: ["read", "search", "import"],
    status: source.status,
    created_at: timestamp,
    updated_at: timestamp,
  });
}

function validateRemoteSourceRegistrationFlags(
  projectId: string | undefined,
  flags: Record<string, string | boolean>,
): void {
  if (!projectId || flags["local-only"] === true) return;
  if (typeof flags["encrypted-display-name"] === "string" && typeof flags["encrypted-metadata"] === "string") return;
  throw new Error(
    "remote-access start with --project requires --local-only or both --encrypted-display-name and --encrypted-metadata",
  );
}

function shouldInitializeRedactor(
  command: string | undefined,
  subcommand: string | undefined,
): boolean {
  return (
    command === "chats" &&
    ["new", "send", "answer-interactive", "incognito"].includes(subcommand ?? "")
  );
}

function parseJsonFlag<T>(value: string, flagName: string): T {
  try {
    return JSON.parse(value) as T;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`Invalid JSON for ${flagName}: ${message}`);
  }
}

async function handleDrafts(
  client: OpenMatesClient,
  subcommand: string | undefined,
  rest: string[],
  flags: Record<string, string | boolean>,
): Promise<void> {
  if (!subcommand || subcommand === "help" || flags.help === true) {
    printDraftsHelp();
    return;
  }
  if (subcommand === "create" || subcommand === "update") {
    const chatId = subcommand === "update"
      ? rest[0]
      : typeof flags.chat === "string" ? flags.chat : undefined;
    const markdown = subcommand === "update" ? rest.slice(1).join(" ").trim() : rest.join(" ").trim();
    if (subcommand === "update" && !chatId) throw new Error("Missing chat ID for draft update.");
    if (!markdown) throw new Error(`Missing draft text for draft ${subcommand}.`);
    const draft = await client.saveDraft({
      chatId,
      markdown,
      preview: typeof flags.preview === "string" ? flags.preview : markdown.slice(0, 160),
    });
    printJson(draft);
    return;
  }
  if (subcommand === "list") {
    const drafts = await client.listDrafts(flags.refresh === true);
    printJson({ drafts });
    return;
  }
  if (subcommand === "get") {
    const chatId = rest[0];
    if (!chatId) throw new Error("Missing chat ID for draft get.");
    printJson({ draft: await client.getDraft(chatId, flags.refresh === true) });
    return;
  }
  if (subcommand === "clear") {
    const chatId = rest[0];
    if (!chatId) throw new Error("Missing chat ID for draft clear.");
    await client.clearDraft(chatId);
    printJson({ success: true, chat_id: chatId });
    return;
  }
  if (subcommand === "sync") {
    printJson({ versions: await client.reconcileDraftVersions() });
    return;
  }
  throw new Error(`Unknown drafts subcommand '${subcommand}'.`);
}

// ---------------------------------------------------------------------------
// Chats
// ---------------------------------------------------------------------------

async function handleChats(
  client: OpenMatesClient,
  subcommand: string | undefined,
  rest: string[],
  flags: Record<string, string | boolean>,
  redactor?: OutputRedactor,
): Promise<void> {
  if (!subcommand || subcommand === "help" || flags.help === true) {
    printChatsHelp();
    return;
  }

  const apiKey = resolveApiKey(flags) ?? undefined;

  if (rest[0] === "tasks") {
    await handleTasks(client, rest[1], rest.slice(2), { ...flags, chat: subcommand });
    return;
  }

  if (subcommand === "list") {
    const limit =
      typeof flags.limit === "string" ? parseInt(flags.limit, 10) : 10;
    const page = typeof flags.page === "string" ? parseInt(flags.page, 10) : 1;
    const result = apiKey
      ? await listApiKeyChats(client, apiKey, limit, page)
      : client.hasSession()
        ? await client.listChats(limit, page)
        : listExampleChats(limit, page);
    if (flags.json === true) {
      printJson(result);
    } else {
      printChatsTable(result);
    }
    return;
  }

  if (subcommand === "search") {
    const query = rest.join(" ").trim();
    if (!query)
      throw new Error(
        "Missing search query. Usage: openmates chats search <query>",
      );
    const result = apiKey
      ? await searchApiKeyChats(client, apiKey, query)
      : client.hasSession()
        ? await client.searchChats(query)
        : searchExampleChats(query);
    if (flags.json === true) {
      printJson(result);
    } else {
      printChatsTable({
        chats: result,
        total: result.length,
        page: 1,
        limit: result.length,
        hasMore: false,
      });
    }
    return;
  }

  if (subcommand === "new") {
    const message = rest.join(" ").trim();
    if (!message)
      throw new Error(
        "Missing message text. Usage: openmates chats new <message>",
      );
    const result = apiKey
      ? await sendApiKeyChatNew(client, apiKey, message, flags)
      : await sendMessageStreaming(
          client,
          {
            message,
            chatId: undefined,
            incognito: false,
            json: flags.json === true,
            autoApproveSubChats: flags["auto-approve"] === true,
            autoApproveMemories: flags["auto-approve-memories"] === true,
            acceptTaskProposals: flags["accept-task-proposals"] === true,
            piiDetection: flags["no-pii-detection"] !== true,
            responseTimeoutMs: parseResponseTimeoutMs(flags),
            anonymousLearningMode: client.hasSession() ? undefined : parseAnonymousLearningModeFlags(flags),
          },
          redactor,
        );
    if (flags.json === true) printJson(result);
    return;
  }

  if (subcommand === "send") {
    const chatId = typeof flags.chat === "string" ? flags.chat : undefined;
    let message = rest.join(" ").trim();

    // --followup <n>: pick the nth follow-up suggestion for this chat instead
    // of requiring the user to retype the full text.
    // Requires --chat <id> because suggestions are stored per-chat.
    if (
      typeof flags.followup === "string" ||
      typeof flags.followup === "boolean"
    ) {
      const rawN =
        typeof flags.followup === "string" ? flags.followup : rest[0];
      const n = parseInt(String(rawN), 10);
      if (!chatId) {
        console.error(
          "--followup requires --chat <id> so the chat's suggestions can be loaded.\n" +
            "Usage: openmates chats send --chat <id> --followup <n>",
        );
        process.exit(1);
      }
      if (isNaN(n) || n < 1) {
        console.error(
          `Invalid --followup value '${rawN}'. Must be a positive integer (1, 2, 3, ...).`,
        );
        process.exit(1);
      }

      // Resolve the full chat ID first so getChatFollowUpSuggestions can match it.
      const fullId = await client
        .resolveFullChatId(chatId)
        .catch(() => undefined);
      if (!fullId) {
        console.error(
          `Chat '${chatId}' not found. Run 'openmates chats list' to see available chats.`,
        );
        process.exit(1);
      }

      const suggestions = await client.getChatFollowUpSuggestions(fullId);
      if (suggestions.length === 0) {
        console.error(
          `No follow-up suggestions stored for chat '${chatId}'.\n` +
            "Suggestions are generated by the AI after your conversation and may take a moment to arrive.\n" +
            "Run 'openmates chats show " +
            chatId +
            "' to check if suggestions have been saved.",
        );
        process.exit(1);
      }
      if (n > suggestions.length) {
        console.error(
          `Follow-up #${n} not found — chat '${chatId}' has ${suggestions.length} suggestion${suggestions.length !== 1 ? "s" : ""}.\n`,
        );
        for (let i = 0; i < suggestions.length; i++) {
          process.stderr.write(`  ${i + 1}. ${suggestions[i]}\n`);
        }
        process.exit(1);
      }

      message = suggestions[n - 1];
      if (!flags.json) {
        process.stderr.write(
          `\x1b[2mUsing follow-up #${n}: "${message}"\x1b[0m\n`,
        );
      }
    }

    if (!message) {
      throw new Error(
        "Missing message text.\n" +
          "Usage: openmates chats send [--chat <id>] <message>\n" +
          "   or: openmates chats send --chat <id> --followup <n>",
      );
    }

    const result = await sendMessageStreaming(
      client,
      {
        message,
        chatId,
        incognito: flags.incognito === true,
        json: flags.json === true,
        autoApproveSubChats: flags["auto-approve"] === true,
        autoApproveMemories: flags["auto-approve-memories"] === true,
        acceptTaskProposals: flags["accept-task-proposals"] === true,
        piiDetection: flags["no-pii-detection"] !== true,
        responseTimeoutMs: parseResponseTimeoutMs(flags),
      },
      redactor,
    );
    if (flags.json === true) printJson(result);
    return;
  }

  if (subcommand === "answer-interactive") {
    const chatId = typeof flags.chat === "string" ? flags.chat : undefined;
    const questionJson = typeof flags["question-json"] === "string" ? flags["question-json"] : undefined;
    const answerJson = typeof flags["answer-json"] === "string" ? flags["answer-json"] : undefined;

    if (!chatId || !questionJson || !answerJson) {
      throw new Error(
        "Missing interactive answer data. Usage: openmates chats answer-interactive --chat <id> --question-json '<json>' --answer-json '<json>'",
      );
    }

    const question = parseJsonFlag<InteractiveQuestionPayload>(questionJson, "--question-json");
    const answer = parseJsonFlag<InteractiveQuestionAnswer>(answerJson, "--answer-json");
    const formatted = formatInteractiveQuestionAnswer(question, answer);
    const result = await sendMessageStreaming(
      client,
      {
        message: formatted.messageContent,
        chatId,
        incognito: false,
        json: flags.json === true,
        autoApproveSubChats: flags["auto-approve"] === true,
        autoApproveMemories: flags["auto-approve-memories"] === true,
        acceptTaskProposals: flags["accept-task-proposals"] === true,
        piiDetection: flags["no-pii-detection"] !== true,
        responseTimeoutMs: parseResponseTimeoutMs(flags),
      },
      redactor,
    );
    if (flags.json === true) printJson(result);
    return;
  }

  if (subcommand === "incognito") {
    const message = rest.join(" ").trim();
    if (!message)
      throw new Error(
        "Missing message text. Usage: openmates chats incognito <message>",
      );
    const result = await sendMessageStreaming(
      client,
      {
        message,
        incognito: true,
        json: flags.json === true,
        autoApproveSubChats: flags["auto-approve"] === true,
        autoApproveMemories: flags["auto-approve-memories"] === true,
        piiDetection: flags["no-pii-detection"] !== true,
        responseTimeoutMs: parseResponseTimeoutMs(flags),
      },
      redactor,
    );
    if (flags.json === true) printJson(result);
    return;
  }

  if (subcommand === "incognito-history") {
    printIncognitoNoHistoryNotice(flags.json === true);
    return;
  }

  if (subcommand === "incognito-clear") {
    printIncognitoNoHistoryNotice(flags.json === true);
    return;
  }

  if (subcommand === "show") {
    const chatId = rest[0];
    if (!chatId) {
      console.error("Missing chat ID.\n");
      printChatsHelp();
      process.exit(1);
    }
    // "last" opens the most recently modified chat
    const resolvedId = chatId.toLowerCase() === "last" ? "__last__" : chatId;
    if (!client.hasSession()) {
      const example = resolveExampleChatForOpen(resolvedId === "__last__" ? "1" : resolvedId);
      if (!example) {
        console.error(
          `Example chat '${chatId}' not found. Run 'openmates chats list' to see available examples.`,
        );
        process.exit(1);
      }
      if (flags.json === true) {
        printJson({
          chat: example.chat,
          messages: example.messages,
          follow_up_suggestions: example.followUpSuggestions,
        });
      } else if (flags.raw === true) {
        await printChatConversationRaw(example.chat, example.messages, { example: true });
      } else {
        await printChatConversation(client, example.chat, example.messages, example.followUpSuggestions, { example: true });
      }
      return;
    }
    const { chat, messages } = await client.getChatMessages(resolvedId);
    if (flags.json === true) {
      // Fetch follow-up suggestions for JSON output too
      const followUpSuggestions = await client
        .getChatFollowUpSuggestions(chat.id)
        .catch(() => [] as string[]);
      printJson({ chat, messages, follow_up_suggestions: followUpSuggestions });
    } else if (flags.raw === true) {
      await printChatConversationRaw(chat, messages);
    } else {
      // Fetch follow-up suggestions to display at the end of the conversation
      const followUpSuggestions = await client
        .getChatFollowUpSuggestions(chat.id)
        .catch(() => [] as string[]);
      await printChatConversation(client, chat, messages, followUpSuggestions);
    }
    return;
  }

  if (subcommand === "delete") {
    // Collect IDs from positional args
    const chatIds = rest.filter((arg) => arg.length > 0);
    if (chatIds.length === 0) {
      throw new Error(
        "Missing chat IDs. Usage: openmates chats delete <id1> [id2] [id3] ...",
      );
    }

    // Resolve short IDs so we can show titles for confirmation
    const resolved: Array<{ input: string; title: string | null }> = [];
    for (const id of chatIds) {
      try {
        const { chat } = await client.getChatMessages(id);
        resolved.push({ input: id, title: chat.title ?? null });
      } catch {
        resolved.push({ input: id, title: null });
      }
    }

    if (flags.yes !== true) {
      // Show what will be deleted and ask for confirmation
      process.stdout.write("\nChats to delete:\n");
      for (const r of resolved) {
        const label = r.title ? `"${r.title}"` : "(unable to resolve title)";
        process.stdout.write(`  \x1b[31m\u2717\x1b[0m ${r.input}  ${label}\n`);
      }
      process.stdout.write("\n");

      const rl = await import("node:readline");
      const iface = rl.createInterface({
        input: process.stdin,
        output: process.stdout,
      });
      const answer = await new Promise<string>((resolve) => {
        iface.question(
          `Delete ${resolved.length} chat(s)? This cannot be undone. [y/N] `,
          resolve,
        );
      });
      iface.close();

      if (answer.trim().toLowerCase() !== "y") {
        console.log("Aborted.");
        return;
      }
    }

    // Delete each chat
    let deleted = 0;
    for (const r of resolved) {
      try {
        if (apiKey) {
          await new OpenMates({ apiKey, apiUrl: client.apiUrl }).chats.delete(
            r.input,
            { confirmed: true },
          );
        } else {
          await client.deleteChat(r.input);
        }
        const label = r.title ? `"${r.title}"` : r.input;
        process.stdout.write(`  \x1b[32m\u2713\x1b[0m Deleted ${label}\n`);
        deleted++;
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        process.stdout.write(
          `  \x1b[31m\u2717\x1b[0m Failed to delete ${r.input}: ${msg}\n`,
        );
      }
    }
    console.log(`\n${deleted}/${resolved.length} chat(s) deleted.`);
    return;
  }

  if (subcommand === "download") {
    const chatId = rest[0];
    if (!chatId) {
      console.error("Missing chat ID.\n");
      printChatsHelp();
      process.exit(1);
    }
    const resolvedId = chatId.toLowerCase() === "last" ? "__last__" : chatId;
    const { chat, messages } = await client.getChatMessages(resolvedId);

    // Determine output directory
    const outputDir =
      typeof flags.output === "string" ? flags.output : process.cwd();
    const useZip = flags.zip === true;

    // Generate filename base (same pattern as web app: YYYY-MM-DD_HH-MM-SS_title)
    const timestampMs =
      chat.updatedAt && chat.updatedAt < 1e12
        ? chat.updatedAt * 1000
        : (chat.updatedAt ?? Date.now());
    const dateStr = new Date(timestampMs)
      .toISOString()
      .slice(0, 19)
      .replace(/[:-]/g, "-")
      .replace("T", "_");
    const safeTitle = (chat.title ?? "Untitled Chat")
      .replace(/[<>:"/\\|?*]/g, "")
      .substring(0, 50)
      .trim();
    const filenameBase = `${dateStr}_${safeTitle}`;

    // Build YAML content (mirrors chatExportService.convertChatToYaml)
    const yamlChat: Record<string, unknown> = {
      title: chat.title ?? null,
      exported_at: new Date().toISOString(),
      message_count: messages.length,
      summary: chat.summary ?? null,
    };
    const yamlMessages: Record<string, unknown>[] = [];
    for (const msg of messages) {
      const msgTimestampMs =
        msg.createdAt < 1e12 ? msg.createdAt * 1000 : msg.createdAt;
      yamlMessages.push({
        role: msg.role,
        sender:
          msg.senderName ??
          (msg.role === "user" ? "You" : (msg.category ?? "Assistant")),
        model: msg.modelName ?? null,
        timestamp: new Date(msgTimestampMs).toISOString(),
        content: msg.content,
      });
    }
    // Simple YAML serialization (no external dependency)
    const yamlContent = serializeToYaml({
      chat: yamlChat,
      messages: yamlMessages,
    });

    // Build Markdown content (mirrors zipExportService.convertChatToMarkdown)
    let mdContent = "";
    if (chat.title) mdContent += `# ${chat.title}\n\n`;
    mdContent += `*Created: ${new Date(timestampMs).toISOString()}*\n\n---\n\n`;
    for (const msg of messages) {
      const msgTimestampMs =
        msg.createdAt < 1e12 ? msg.createdAt * 1000 : msg.createdAt;
      const role =
        msg.role === "user" ? "You" : (msg.senderName ?? "Assistant");
      mdContent += `## ${role} - ${new Date(msgTimestampMs).toISOString()}\n\n`;
      // Strip embed JSON blocks from markdown output, keep surrounding text
      const cleaned = msg.content.replace(
        /```(?:json_embed|json)\n[\s\S]*?\n```/g,
        "",
      );
      if (cleaned.trim()) mdContent += `${cleaned.trim()}\n\n`;
    }

    // Extract code embeds and video transcript embeds from messages
    const codeEmbeds: Array<{
      embedId: string;
      language: string;
      filename?: string;
      content: string;
      filePath?: string;
    }> = [];
    const transcriptEmbeds: Array<{
      embedId: string;
      filename: string;
      content: string;
    }> = [];
    const processedEmbedIds = new Set<string>();

    // Collect all embed IDs from messages
    const allEmbedIds: string[] = [];
    for (const msg of messages) {
      const segments = parseMessageSegments(msg.content);
      for (const seg of segments) {
        if (seg.type === "embed" && !processedEmbedIds.has(seg.value)) {
          processedEmbedIds.add(seg.value);
          allEmbedIds.push(seg.value);
        }
      }
    }

    // Process embeds (code + transcripts) with recursive child embed handling
    const embedQueue = [...allEmbedIds];
    while (embedQueue.length > 0) {
      const eid = embedQueue.shift()!;
      try {
        const embed = await client.getEmbed(eid);

        // Code embeds
        if (embed.type === "code" && embed.content) {
          const code =
            typeof embed.content.code === "string"
              ? embed.content.code
              : typeof embed.content.content === "string"
                ? (embed.content.content as string)
                : null;
          if (code) {
            codeEmbeds.push({
              embedId: embed.embedId,
              language:
                typeof embed.content.language === "string"
                  ? embed.content.language
                  : "text",
              filename:
                typeof embed.content.filename === "string"
                  ? embed.content.filename
                  : undefined,
              content: code,
              filePath:
                typeof embed.content.file_path === "string"
                  ? embed.content.file_path
                  : undefined,
            });
          }
        }

        // Video transcript embeds
        if (
          embed.type === "app_skill_use" &&
          embed.appId === "videos" &&
          (embed.skillId === "get_transcript" ||
            embed.skillId === "get-transcript") &&
          embed.content
        ) {
          const results = (embed.content.results ??
            embed.content.data ??
            []) as Array<Record<string, unknown>>;
          if (Array.isArray(results) && results.length > 0) {
            let text = "";
            for (const r of results) {
              const meta = r.metadata as
                | Record<string, unknown>
                | undefined;
              if (meta?.title) text += `# ${meta.title}\n\n`;
              if (r.url) text += `Source: ${r.url}\n\n`;
              text += String(
                r.transcript ??
                  r.formatted_transcript ??
                  r.text ??
                  r.content ??
                  "",
              );
              text += "\n\n---\n\n";
            }
            let fname = `${eid.slice(0, 8)}_transcript.md`;
            const firstMeta = (results[0]?.metadata as
              | Record<string, unknown>
              | undefined);
            if (firstMeta?.title) {
              fname = `${String(firstMeta.title).replace(/[^a-z0-9]/gi, "_").toLowerCase()}_transcript.md`;
            }
            transcriptEmbeds.push({
              embedId: eid,
              filename: fname,
              content: text,
            });
          }
        }

        // Queue child embeds for processing
        if (embed.content?.embed_ids) {
          const childIds = Array.isArray(embed.content.embed_ids)
            ? (embed.content.embed_ids as string[])
            : typeof embed.content.embed_ids === "string"
              ? embed.content.embed_ids.split("|").filter(Boolean)
              : [];
          for (const childId of childIds) {
            if (!processedEmbedIds.has(childId)) {
              processedEmbedIds.add(childId);
              embedQueue.push(childId);
            }
          }
        }
      } catch {
        // Embed not in cache — skip
      }
    }

    // Write files
    const { mkdir, writeFile } = await import("node:fs/promises");
    const { join } = await import("node:path");

    if (useZip) {
      // Zip mode — create temp directory, then shell out to system zip
      const tmpDir = join(outputDir, `.${filenameBase}_tmp`);
      await mkdir(tmpDir, { recursive: true });
      await writeFile(join(tmpDir, `${filenameBase}.yml`), yamlContent);
      await writeFile(join(tmpDir, `${filenameBase}.md`), mdContent);
      if (codeEmbeds.length > 0) {
        for (const ce of codeEmbeds) {
          const fpath =
            ce.filePath ??
            ce.filename ??
            `${ce.embedId.slice(0, 8)}.${getExtForLang(ce.language)}`;
          const fullPath = join(tmpDir, "code", fpath);
          await mkdir(fullPath.substring(0, fullPath.lastIndexOf("/")), {
            recursive: true,
          });
          await writeFile(fullPath, ce.content);
        }
      }
      if (transcriptEmbeds.length > 0) {
        const tDir = join(tmpDir, "transcripts");
        await mkdir(tDir, { recursive: true });
        for (const te of transcriptEmbeds) {
          await writeFile(join(tDir, te.filename), te.content);
        }
      }
      // Create zip using system zip command
      const zipPath = join(outputDir, `${filenameBase}.zip`);
      const { execSync } = await import("node:child_process");
      try {
        execSync(`cd "${tmpDir}" && zip -r "${zipPath}" .`, { stdio: "pipe" });
        // Clean up temp dir
        const { rm } = await import("node:fs/promises");
        await rm(tmpDir, { recursive: true, force: true });
        process.stdout.write(`\x1b[32m\u2713\x1b[0m ${zipPath}\n`);
      } catch {
        // zip not available — keep the directory as fallback
        process.stderr.write(
          `\x1b[33m!\x1b[0m 'zip' command not found — files saved to ${tmpDir}\n`,
        );
      }
    } else {
      // Direct file mode — write files into target directory
      const chatDir = join(outputDir, filenameBase);
      await mkdir(chatDir, { recursive: true });
      const written: string[] = [];

      await writeFile(join(chatDir, `${filenameBase}.yml`), yamlContent);
      written.push(`${filenameBase}.yml`);

      await writeFile(join(chatDir, `${filenameBase}.md`), mdContent);
      written.push(`${filenameBase}.md`);

      if (codeEmbeds.length > 0) {
        for (const ce of codeEmbeds) {
          const fpath =
            ce.filePath ??
            ce.filename ??
            `${ce.embedId.slice(0, 8)}.${getExtForLang(ce.language)}`;
          const fullPath = join(chatDir, "code", fpath);
          await mkdir(fullPath.substring(0, fullPath.lastIndexOf("/")), {
            recursive: true,
          });
          await writeFile(fullPath, ce.content);
          written.push(`code/${fpath}`);
        }
      }

      if (transcriptEmbeds.length > 0) {
        const tDir = join(chatDir, "transcripts");
        await mkdir(tDir, { recursive: true });
        for (const te of transcriptEmbeds) {
          await writeFile(join(tDir, te.filename), te.content);
          written.push(`transcripts/${te.filename}`);
        }
      }

      // Print summary
      const label = chat.title ? `"${chat.title}"` : chat.shortId;
      process.stdout.write(
        `\x1b[1mDownloaded chat ${label}\x1b[0m → ${chatDir}\n\n`,
      );
      for (const f of written) {
        process.stdout.write(`  \x1b[32m\u2713\x1b[0m ${f}\n`);
      }
      process.stdout.write(
        `\n\x1b[2m${written.length} file(s) written.\x1b[0m\n`,
      );
    }

    if (flags.json === true) {
      const files: string[] = [
        `${filenameBase}.yml`,
        `${filenameBase}.md`,
      ];
      for (const ce of codeEmbeds) {
        files.push(
          `code/${ce.filePath ?? ce.filename ?? ce.embedId.slice(0, 8)}`,
        );
      }
      for (const te of transcriptEmbeds) {
        files.push(`transcripts/${te.filename}`);
      }
      printJson({
        chat_id: chat.id,
        title: chat.title,
        output_dir: useZip
          ? join(outputDir, `${filenameBase}.zip`)
          : join(outputDir, filenameBase),
        files,
        code_embeds: codeEmbeds.length,
        transcript_embeds: transcriptEmbeds.length,
      });
    }
    return;
  }

  if (subcommand === "share") {
    const id = rest[0] || "last";
    const durationSeconds = (
      typeof flags.expires === "string" ? parseInt(flags.expires, 10) : 0
    ) as ShareDuration;
    const password =
      typeof flags.password === "string" ? flags.password : undefined;

    if (password && password.length > 10) {
      console.error("Password must be at most 10 characters.");
      process.exit(1);
    }

    try {
      const url = await client.createChatShareLink(
        id,
        durationSeconds,
        password,
      );
      if (flags.json === true) {
        printJson({
          url,
          chat_id: id,
          expires: durationSeconds,
          password_protected: !!password,
        });
      } else {
        process.stdout.write(`\n[1mChat share link[0m\n`);
        process.stdout.write(`${url}\n\n`);
        if (durationSeconds > 0) {
          process.stdout.write(
            `[2mExpires in ${humanizeDuration(durationSeconds)}[0m\n`,
          );
        }
        if (password) {
          process.stdout.write(`[2mPassword protected[0m\n`);
        }
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error(`Share link error: ${msg}`);
      process.exit(1);
    }
    return;
  }

  if (subcommand === "open") {
    if (!client.hasSession()) {
      const target = rest[0] ?? "1";
      const example = resolveExampleChatForOpen(target);
      if (!example) {
        console.error(
          `Example chat '${target}' not found. Run 'openmates chats list' to see available examples.`,
        );
        process.exit(1);
      }
      const appUrl = deriveAppUrl(client.apiUrl);
      const url = `${appUrl}/example/${example.chat.slug}`;
      if (!flags.json) {
        process.stderr.write(
          `\x1b[2mOpening example chat: "${example.chat.title ?? example.chat.slug}"\x1b[0m\n`,
        );
      }
      await openUrl(url);
      if (flags.json === true) {
        printJson({
          url,
          chat_id: example.chat.id,
          slug: example.chat.slug,
          title: example.chat.title,
          source: "example",
        });
      }
      return;
    }

    const n = rest[0] !== undefined ? parseInt(rest[0], 10) : 1;
    if (isNaN(n) || n < 1) {
      console.error(
        `Invalid position '${rest[0]}'. Must be a positive integer (1 = most recent, 2 = second most recent, ...).`,
      );
      process.exit(1);
    }

    // Fetch enough chats to reach position n (sorted most-recent-first)
    const result = await client.listChats(n, 1);
    if (result.total === 0) {
      console.error(
        "No chats found. Run 'openmates chats list' to sync.",
      );
      process.exit(1);
    }
    if (n > result.total) {
      console.error(
        `Only ${result.total} chat(s) available — cannot open chat #${n}.`,
      );
      process.exit(1);
    }

    const chat = result.chats[n - 1];
    const appUrl = deriveAppUrl(client.apiUrl);
    const url = `${appUrl}/#chat-id=${chat.id}`;

    if (!flags.json) {
      const label = chat.title ? `"${chat.title}"` : chat.id.slice(0, 8);
      process.stderr.write(
        `\x1b[2mOpening chat #${n}: ${label}\x1b[0m\n`,
      );
    }

    await openUrl(url);

    if (flags.json === true) {
      printJson({ url, chat_id: chat.id, position: n, title: chat.title });
    }
    return;
  }

  console.error(`Unknown chats subcommand '${subcommand}'.\n`);
  printChatsHelp();
  process.exit(1);
}

async function listApiKeyChats(
  client: OpenMatesClient,
  apiKey: string,
  limit: number,
  page: number,
): Promise<ChatListPage> {
  const safeLimit = Number.isFinite(limit) && limit > 0 ? limit : 10;
  const safePage = Number.isFinite(page) && page > 0 ? page : 1;
  const sdk = new OpenMates({ apiKey, apiUrl: client.apiUrl });
  const chats = await sdk.chats.list({ limit: safeLimit, offset: (safePage - 1) * safeLimit });
  return sdkChatsToChatListPage(chats, safeLimit, safePage);
}

async function searchApiKeyChats(
  client: OpenMatesClient,
  apiKey: string,
  query: string,
): Promise<ChatListItem[]> {
  const sdk = new OpenMates({ apiKey, apiUrl: client.apiUrl });
  const chats = await sdk.chats.search(query, { limit: 0 });
  return sdkChatsToChatListPage(chats, chats.length || 1, 1).chats;
}

function sdkChatsToChatListPage(
  chats: EncryptedChatMetadata[],
  limit: number,
  page: number,
): ChatListPage {
  return {
    chats: chats.map((chat) => {
      const category = typeof chat.category === "string" ? chat.category : null;
      return {
        id: chat.id,
        shortId: chat.id.slice(0, 8),
        title: typeof chat.title === "string" ? chat.title : null,
        summary: typeof chat.chat_summary === "string" ? chat.chat_summary : null,
        updatedAt: normalizeSdkTimestamp(chat.updated_at),
        category,
        mateName: category ? (MATE_NAMES[category] ?? null) : null,
      };
    }),
    total: chats.length,
    page,
    limit,
    hasMore: chats.length >= limit,
  };
}

function normalizeSdkTimestamp(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? Math.floor(parsed / 1000) : null;
  }
  return null;
}

async function sendApiKeyChatNew(
  client: OpenMatesClient,
  apiKey: string,
  message: string,
  flags: Record<string, string | boolean>,
): Promise<Record<string, unknown>> {
  const sdk = new OpenMates({ apiKey, apiUrl: client.apiUrl });
  let response: ChatResponse;
  try {
    response = await sdk.chats.send(message, {
      saveToAccount: false,
    });
  } catch (err) {
    if (!isSdkChatScopeDenied(err)) throw err;
    const aiAskResult = await client.runSkill({
      app: "ai",
      skill: "ask",
      inputData: { prompt: message },
      apiKey,
    });
    response = {
      content: extractAiAskContent(aiAskResult),
      raw: aiAskResult,
    };
  }
  const result = normalizeApiKeyChatResponse(response);
  if (flags.json !== true) {
    const category = typeof result.category === "string" ? result.category : null;
    const modelName = typeof result.modelName === "string" ? result.modelName : null;
    const mateBlock = ansiMateBlock(category, category ? (MATE_NAMES[category] ?? null) : null);
    const modelSuffix = modelName ? `  \x1b[2m${modelName}\x1b[0m` : "";
    process.stdout.write(`${SEP}\n`);
    process.stdout.write(`${mateBlock}${modelSuffix}\n`);
    process.stdout.write(`${SEP}\n`);
    process.stdout.write(`${String(result.assistant ?? "")}\n`);
    const chatId = typeof result.chatId === "string" ? result.chatId : null;
    if (chatId) {
      const shortId = chatId.slice(0, 8);
      process.stdout.write(`${SEP}\n`);
      process.stdout.write(
        `\x1b[2mContinue: openmates chats send --chat ${shortId} "your message"\x1b[0m\n` +
          `\x1b[2mHistory:  openmates chats show ${shortId}\x1b[0m\n`,
      );
    }
  }
  return result;
}

function isSdkChatScopeDenied(err: unknown): boolean {
  return err instanceof Error
    && err.name === "OpenMatesApiError"
    && (err as Error & { status?: number }).status === 403;
}

function extractAiAskContent(value: unknown): string {
  if (!value || typeof value !== "object") return "";
  const record = value as Record<string, unknown>;
  if (typeof record.content === "string") return record.content;
  if (typeof record.response === "string") return record.response;
  if (typeof record.answer === "string") return record.answer;
  const choices = record.choices;
  if (Array.isArray(choices)) {
    const first = choices[0] as Record<string, unknown> | undefined;
    const message = first?.message as Record<string, unknown> | undefined;
    if (typeof message?.content === "string") return message.content;
    if (typeof first?.text === "string") return first.text;
  }
  const data = record.data;
  if (data && typeof data === "object") return extractAiAskContent(data);
  return JSON.stringify(value);
}

function normalizeApiKeyChatResponse(response: ChatResponse): Record<string, unknown> {
  const chatId = typeof response.chat_id === "string" ? response.chat_id : null;
  const category = typeof response.category === "string" ? response.category : null;
  const modelName = typeof response.model_name === "string" ? response.model_name : null;
  return {
    status: "completed",
    chatId,
    chat_id: chatId,
    messageId: null,
    message_id: null,
    assistant: typeof response.content === "string" ? response.content : "",
    category,
    modelName,
    model_name: modelName,
    mateName: category ? (MATE_NAMES[category] ?? null) : null,
    followUpSuggestions: [],
    follow_up_suggestions: [],
    taskEvents: [],
    task_events: [],
    pendingTaskUpdateJobs: [],
    pending_task_update_jobs: [],
    subChatEvents: [],
    sub_chat_events: [],
    appSettingsMemoryRequests: [],
    app_settings_memory_requests: [],
    acceptedTaskProposals: [],
    accepted_task_proposals: [],
    raw: response,
  };
}

function resolveExampleChatForOpen(target: string): ExampleChatConversation | null {
  const numericTarget = parseInt(target, 10);
  if (!Number.isNaN(numericTarget) && String(numericTarget) === target.trim()) {
    if (numericTarget < 1) return null;
    const page = listExampleChats(numericTarget, 1);
    const chat = page.chats[numericTarget - 1];
    return chat ? getExampleChatConversation(chat.id) : null;
  }
  return getExampleChatConversation(target);
}

async function openUrl(url: string): Promise<void> {
  // Open in default browser using platform-appropriate command.
  const { exec } = await import("node:child_process");
  const platform = process.platform;
  const openCmd =
    platform === "darwin"
      ? `open "${url}"`
      : platform === "win32"
        ? `start "" "${url}"`
        : `xdg-open "${url}"`;
  exec(openCmd, (err) => {
    if (err) {
      // Fallback: print the URL so the user can open it manually.
      console.log(url);
    }
  });
}

// ---------------------------------------------------------------------------
// Workflows
// ---------------------------------------------------------------------------

async function handleWorkflows(
  client: OpenMatesClient,
  subcommand: string | undefined,
  rest: string[],
  flags: Record<string, string | boolean>,
): Promise<void> {
  if (!subcommand || subcommand === "help" || flags.help === true) {
    printWorkflowsHelp();
    return;
  }

  if (subcommand === "capabilities") {
    const capabilities = await client.listWorkflowCapabilities();
    if (flags.json === true) {
      printJson(capabilities);
    } else {
      printWorkflowCapabilities(capabilities);
    }
    return;
  }

  if (subcommand === "list") {
    const workflows = await client.listWorkflows();
    if (flags.json === true) {
      printJson(workflows);
    } else {
      printWorkflowList(workflows);
    }
    return;
  }

  if (subcommand === "validate") {
    const file = typeof flags.file === "string" ? flags.file : "";
    if (!file) throw new Error("Missing --file. Example: openmates workflows validate --file workflow.yml");
    const validation = await client.validateWorkflowYaml(readFileSync(file, "utf8"));
    if (flags.json === true) {
      printJson(validation);
    } else {
      kv("Draft valid", validation.draft_valid ? "yes" : "no");
      kv("Ready to enable", validation.enable_ready ? "yes" : "no");
      for (const diagnostic of validation.diagnostics) {
        console.log(`  - ${String(diagnostic.path ?? "$")}: ${String(diagnostic.message ?? diagnostic.code ?? "invalid")}`);
      }
    }
    if (!validation.draft_valid) process.exitCode = 1;
    return;
  }

  if (subcommand === "create") {
    const yamlFile = typeof flags.file === "string" ? flags.file : "";
    if (yamlFile) {
      const result = await client.createWorkflowYaml(readFileSync(yamlFile, "utf8"));
      if (flags.json === true) {
        printJson(result);
      } else {
        printWorkflowDetail(result.workflow);
        kv("Ready to enable", result.validation.enable_ready ? "yes" : "no");
        for (const diagnostic of result.validation.diagnostics) {
          console.log(`  - ${String(diagnostic.path ?? "$")}: ${String(diagnostic.message ?? diagnostic.code ?? "input required")}`);
        }
      }
      return;
    }
    const title = typeof flags.title === "string" ? flags.title.trim() : "";
    const graphJson = typeof flags.graph === "string" ? flags.graph : "";
    if (!title) throw new Error("Missing --title for workflow create.");
    if (!graphJson) throw new Error("Missing --graph JSON for workflow create.");
    const workflow = await client.createWorkflow({
      title,
      graph: parseJsonFlag<WorkflowGraph>(graphJson, "--graph"),
      enabled: flags.enabled === true,
      runContentRetention: parseWorkflowRunContentRetention(flags["run-content-retention"]),
    });
    if (flags.json === true) {
      printJson(workflow);
    } else {
      printWorkflowDetail(workflow);
    }
    return;
  }

  if (subcommand === "update") {
    const workflowId = rest[0];
    const yamlFile = typeof flags.file === "string" ? flags.file : "";
    if (!workflowId || !yamlFile) throw new Error("Missing workflow ID or --file. Example: openmates workflows update <id> --file workflow.yml");
    const result = await client.updateWorkflowYaml(workflowId, readFileSync(yamlFile, "utf8"));
    if (flags.json === true) {
      printJson(result);
    } else {
      printWorkflowDetail(result.workflow);
      kv("Ready to enable", result.validation.enable_ready ? "yes" : "no");
      for (const diagnostic of result.validation.diagnostics) {
        console.log(`  - ${String(diagnostic.path ?? "$")}: ${String(diagnostic.message ?? diagnostic.code ?? "input required")}`);
      }
    }
    return;
  }

  if (subcommand === "input") {
    const text = typeof flags.text === "string" ? flags.text : rest.join(" ").trim();
    if (!text) throw new Error("Missing workflow input text. Example: openmates workflows input \"alert me if it rains\"");
    const session = await client.startWorkflowInput({
      text,
      selectedWorkflowId: typeof flags["workflow-id"] === "string" ? flags["workflow-id"] : undefined,
      selectedProjectId: typeof flags["project-id"] === "string" ? flags["project-id"] : undefined,
    });
    if (flags.json === true) {
      printJson(session);
    } else {
      printWorkflowInputSession(session);
    }
    return;
  }

  if (subcommand === "input-show") {
    const sessionId = rest[0];
    if (!sessionId) throw new Error("Missing session ID. Example: openmates workflows input-show <session-id>");
    const session = await client.getWorkflowInputSession(sessionId);
    if (flags.json === true) {
      printJson(session);
    } else {
      printWorkflowInputSession(session);
      if (session.events.length > 0) {
        console.log("\nEvents:");
        for (const event of session.events) {
          kv(String(event.event_id), `${event.type} · ${event.status}`, 6);
        }
      }
    }
    return;
  }

  if (subcommand === "input-events") {
    const sessionId = rest[0];
    if (!sessionId) throw new Error("Missing session ID. Example: openmates workflows input-events <session-id>");
    const afterEventId = typeof flags.after === "string" ? Number.parseInt(flags.after, 10) : 0;
    const events = await client.listWorkflowInputEvents(sessionId, Number.isFinite(afterEventId) ? afterEventId : 0);
    if (flags.json === true) {
      printJson(events);
    } else {
      for (const event of events) {
        kv(String(event.event_id), `${event.type} · ${event.status}`, 6);
      }
    }
    return;
  }

  if (subcommand === "input-follow-up") {
    const sessionId = rest[0];
    const text = typeof flags.text === "string" ? flags.text : rest.slice(1).join(" ").trim();
    if (!sessionId || !text) throw new Error("Missing session ID or text. Example: openmates workflows input-follow-up <session-id> \"make it weekdays only\"");
    const session = await client.followUpWorkflowInput(sessionId, text);
    if (flags.json === true) {
      printJson(session);
    } else {
      printWorkflowInputSession(session);
    }
    return;
  }

  if (subcommand === "input-stop" || subcommand === "input-undo") {
    const sessionId = rest[0];
    if (!sessionId) throw new Error(`Missing session ID. Example: openmates workflows ${subcommand} <session-id>`);
    const session = subcommand === "input-stop"
      ? await client.stopWorkflowInput(sessionId)
      : await client.undoWorkflowInput(sessionId);
    if (flags.json === true) {
      printJson(session);
    } else {
      printWorkflowInputSession(session);
    }
    return;
  }

  if (subcommand === "show") {
    const workflowId = rest[0];
    if (!workflowId) throw new Error("Missing workflow ID. Example: openmates workflows show <id>");
    const workflow = await client.getWorkflow(workflowId);
    if (flags.json === true) {
      printJson(workflow);
    } else {
      printWorkflowDetail(workflow);
    }
    return;
  }

  if (subcommand === "enable" || subcommand === "disable") {
    const workflowId = rest[0];
    if (!workflowId) throw new Error(`Missing workflow ID. Example: openmates workflows ${subcommand} <id>`);
    const workflow = subcommand === "enable"
      ? await client.enableWorkflow(workflowId)
      : await client.disableWorkflow(workflowId);
    if (flags.json === true) {
      printJson(workflow);
    } else {
      printWorkflowDetail(workflow);
    }
    return;
  }

  if (subcommand === "delete") {
    const workflowId = rest[0];
    if (!workflowId) throw new Error("Missing workflow ID. Example: openmates workflows delete <id> --yes");
    if (flags.yes !== true) throw new Error("Refusing to delete workflow without --yes.");
    const result = await client.deleteWorkflow(workflowId);
    if (flags.json === true) {
      printJson(result);
    } else {
      console.log("Workflow deleted.");
    }
    return;
  }

  if (subcommand === "run") {
    const workflowId = rest[0];
    if (!workflowId) throw new Error("Missing workflow ID. Example: openmates workflows run <id>");
    const idempotencyKey = typeof flags["idempotency-key"] === "string" ? flags["idempotency-key"] : "";
    if (!idempotencyKey) throw new Error("Missing --idempotency-key. Reuse this stable key when retrying the same workflow run.");
    const mode = flags.mode === "test" ? "test" : "manual";
    const input = typeof flags.input === "string" ? parseJsonFlag<Record<string, unknown>>(flags.input, "--input") : {};
    const run = await client.runWorkflow(workflowId, { idempotencyKey, mode, input });
    if (flags.json === true) {
      printJson(run);
    } else {
      printWorkflowRun(run);
    }
    return;
  }

  if (subcommand === "runs") {
    const workflowId = rest[0];
    if (!workflowId) throw new Error("Missing workflow ID. Example: openmates workflows runs <id>");
    const runs = await client.listWorkflowRuns(workflowId);
    if (flags.json === true) {
      printJson(runs);
    } else {
      printWorkflowRuns(runs);
    }
    return;
  }

  if (subcommand === "run-show") {
    const workflowId = rest[0];
    const runId = rest[1];
    if (!workflowId || !runId) throw new Error("Missing workflow/run ID. Example: openmates workflows run-show <workflow-id> <run-id>");
    const run = await client.getWorkflowRun(workflowId, runId);
    if (flags.json === true) {
      printJson(run);
    } else {
      printWorkflowRun(run);
    }
    return;
  }

  if (subcommand === "run-cancel") {
    const workflowId = rest[0];
    const runId = rest[1];
    if (!workflowId || !runId) throw new Error("Missing workflow/run ID. Example: openmates workflows run-cancel <workflow-id> <run-id>");
    const result = await client.cancelWorkflowRun(workflowId, runId);
    if (flags.json === true) {
      printJson(result);
    } else {
      kv("Status", result.status);
    }
    return;
  }

  if (subcommand === "step-test") {
    const workflowId = rest[0];
    const stepId = rest[1];
    if (!workflowId || !stepId) throw new Error("Missing workflow/step ID. Example: openmates workflows step-test <workflow-id> <step-id> --yes");
    const input = typeof flags.input === "string" ? parseJsonFlag<Record<string, unknown>>(flags.input, "--input") : {};
    const run = await client.testWorkflowStep(workflowId, stepId, { input, confirmed: flags.yes === true });
    if (flags.json === true) {
      printJson(run);
    } else {
      printWorkflowRun(run);
    }
    return;
  }

  if (subcommand === "respond") {
    const workflowId = rest[0];
    const runId = rest[1];
    const stepId = rest[2];
    if (!workflowId || !runId || !stepId) throw new Error("Missing workflow/run/step ID. Example: openmates workflows respond <workflow-id> <run-id> <step-id> --input '{\"answer\":\"Berlin\"}'");
    const input = typeof flags.input === "string" ? parseJsonFlag<Record<string, unknown>>(flags.input, "--input") : {};
    const run = await client.respondToWorkflowRun(workflowId, runId, stepId, input);
    if (flags.json === true) {
      printJson(run);
    } else {
      printWorkflowRun(run);
    }
    return;
  }

  if (subcommand === "help-app") {
    const capabilityId = rest[0];
    if (!capabilityId) throw new Error("Missing app skill. Example: openmates workflows help-app weather.forecast");
    const capabilities = await client.listWorkflowCapabilities();
    const capability = capabilities.find((item) => item.id === capabilityId || item.id === capabilityId.replace(":", "."));
    if (!capability) throw new Error(`Workflow capability not found: ${capabilityId}`);
    if (flags.json === true) {
      printJson(capability);
    } else {
      printWorkflowCapabilityHelp(capability);
    }
    return;
  }

  throw new Error(`Unknown workflows command '${subcommand}'. Run 'openmates workflows --help'.`);
}

function printWorkflowList(workflows: WorkflowSummary[]): void {
  if (workflows.length === 0) {
    console.log("No workflows yet.");
    console.log("Create one: openmates workflows create --title \"Morning brief\" --graph '<json>'");
    return;
  }
  header(`Workflows  \x1b[2m(${workflows.length})\x1b[0m\n`);
  for (const workflow of workflows) {
    kv(workflow.id.slice(0, 8), `${workflow.title} · ${workflow.status}${workflow.trigger_summary ? ` · ${workflow.trigger_summary}` : ""}`, 10);
  }
}

function printWorkflowDetail(workflow: WorkflowDetail): void {
  header(`${workflow.title}\n`);
  kv("ID", workflow.id);
  kv("Status", workflow.status);
  kv("Enabled", String(workflow.enabled));
  kv("Run content", workflow.run_content_retention ?? "last_5");
  if (workflow.trigger_summary) kv("Trigger", workflow.trigger_summary);
  kv("Nodes", String(workflow.graph.nodes.length));
  console.log(`\n\x1b[2mRun: openmates workflows run ${workflow.id}\x1b[0m`);
}

function printWorkflowInputSession(session: WorkflowInputSessionResult): void {
  header(`Workflow Input ${session.session_id}\n`);
  kv("Status", session.status);
  kv("Events", String(session.event_cursor));
  kv("Undo", session.undo_available ? "available" : "unavailable");
  if (session.message) kv("Message", session.message);
  if (session.error) kv("Error", session.error);
  if (session.workflow) kv("Workflow", `${session.workflow.title} (${session.workflow.id})`);
}

function printWorkflowRun(run: WorkflowRunDetail): void {
  header(`Workflow Run ${run.id}\n`);
  kv("Status", run.status);
  kv("Trigger", run.trigger_type);
  kv("Content", run.content_available === false ? "unavailable" : `${run.content_storage ?? "unknown"} (${run.content_retention_mode ?? "last_5"})`);
  if (run.content_expires_at) kv("Content expires", new Date(run.content_expires_at * 1000).toISOString());
  kv("Nodes", String(run.node_runs?.length ?? 0));
  if (run.error_summary) kv("Error", run.error_summary);
}

function parseWorkflowRunContentRetention(value: string | boolean | undefined): WorkflowRunContentRetention | undefined {
  if (value === undefined || value === false) return undefined;
  if (value === "last_5" || value === "none") return value;
  throw new Error("Invalid --run-content-retention. Expected last_5 or none.");
}

function printWorkflowRuns(runs: WorkflowRunDetail[]): void {
  if (runs.length === 0) {
    console.log("No workflow runs yet.");
    return;
  }
  header(`Workflow Runs  \x1b[2m(${runs.length})\x1b[0m\n`);
  for (const run of runs) {
    kv(run.id.slice(0, 8), `${run.status} · ${run.trigger_type}`, 10);
  }
}

function printWorkflowCapabilities(capabilities: WorkflowCapability[]): void {
  header("Workflow Capabilities\n");
  for (const capability of capabilities) {
    const state = capability.enabled ? "enabled" : `disabled${capability.reason ? `: ${capability.reason}` : ""}`;
    kv(capability.id, `${capability.title} · ${state}`, 24);
  }
}

function printWorkflowCapabilityHelp(capability: WorkflowCapability): void {
  header(`${capability.title}\n`);
  kv("ID", capability.id);
  kv("Type", capability.type);
  kv("Enabled", capability.enabled ? "yes" : "no");
  if (capability.reason) kv("Reason", capability.reason);
  const metadata = capability.metadata ?? {};
  const workflow = metadata.workflow as Record<string, unknown> | undefined;
  if (workflow) {
    kv("Effect", String(workflow.effect ?? "unknown"));
    kv("Execution", String(workflow.execution_mode ?? "unknown"));
    kv("Approval", String(workflow.approval ?? "unknown"));
    kv("Unattended", workflow.unattended === true ? "yes" : "no");
  }
  if (metadata.input_schema) {
    console.log("\nInput schema:");
    console.log(JSON.stringify(metadata.input_schema, null, 2));
  }
  if (workflow?.test_example_input) {
    console.log("\nTest example:");
    console.log(JSON.stringify(workflow.test_example_input, null, 2));
  }
}

// ---------------------------------------------------------------------------
// Apps
// ---------------------------------------------------------------------------

type JsonSchema = {
  type?: string;
  description?: string;
  properties?: Record<string, JsonSchema>;
  items?: JsonSchema;
  required?: string[];
  enum?: unknown[];
  default?: unknown;
};

type GeneratedAppSkillCommand = {
  app_id: string;
  skill_id: string;
  description?: string;
  schema?: JsonSchema;
};

type AppSkillInputShape = {
  kind: "request-array" | "flat";
  schema: JsonSchema;
  properties: Record<string, JsonSchema>;
  required: string[];
};

const GENERATED_APP_SKILL_COMMANDS = APP_SKILL_METADATA as readonly GeneratedAppSkillCommand[];

const APP_SKILL_COMMAND_EXAMPLES: Record<string, string[]> = {
  "code/get_docs": [
    "openmates apps code get_docs --library React --question \"How do I use useState?\" --json",
  ],
  "code/search_repos": [
    "openmates apps code search_repos \"svelte markdown editor\" --count 3 --json",
  ],
  "electronics/search_components": [
    "openmates apps electronics search_components --category power_converters --input-voltage-min 12 --input-voltage-max 12 --output-voltage 3.3 --output-current-max 3 --max-results 3 --json",
  ],
  "events/search": [
    "openmates apps events search \"technology meetup\" --location Berlin --provider auto --json",
  ],
  "fitness/search_classes": [
    "openmates apps fitness search_classes Yoga --address \"Sorauer Str. 12, Berlin\" --radius-km 3 --attendance-mode onsite --days 7 --limit 5 --json",
  ],
  "fitness/search_locations": [
    "openmates apps fitness search_locations HIIT --address \"Sorauer Str. 12, Berlin\" --radius-km 2 --limit 5 --json",
  ],
  "health/search_appointments": [
    "openmates apps health search_appointments --speciality zahnarzt --city Berlin --json",
  ],
  "home/search": [
    "openmates apps home search Berlin --listing-type rent --json",
  ],
  "images/search": [
    "openmates apps images search \"sunset over ocean\" --json",
  ],
  "maps/search": [
    "openmates apps maps search \"cafes in Berlin Mitte\" --json",
  ],
  "math/calculate": [
    "openmates apps math calculate \"sqrt(144)\" --mode numeric --precision 10 --json",
  ],
  "music/generate": [
    "openmates apps music generate \"A 30 second upbeat electronic test jingle\" --mode jingle --duration-seconds 30 --json",
  ],
  "news/search": [
    "openmates apps news search \"artificial intelligence\" --freshness pw --json",
  ],
  "shopping/search_products": [
    "openmates apps shopping search_products \"bio joghurt\" --provider REWE --json",
  ],
  "travel/search_connections": [
    "openmates apps travel search_connections --origin Berlin --destination Munich --date 2026-08-01 --json",
    "openmates apps travel search_connections --origin Berlin --destination Munich --date 2026-08-01 --transport train --json",
  ],
  "travel/search_stays": [
    "openmates apps travel search_stays \"Hotels in Berlin\" --check-in-date 2026-08-01 --check-out-date 2026-08-03 --json",
  ],
  "videos/get_transcript": [
    "openmates apps videos get_transcript --url https://www.youtube.com/watch?v=dQw4w9WgXcQ --json",
  ],
  "videos/search": [
    "openmates apps videos search \"python programming tutorial\" --json",
  ],
  "weather/forecast": [
    "openmates apps weather forecast Berlin --days 2 --json",
  ],
  "web/read": [
    "openmates apps web read https://example.com --json",
  ],
  "web/search": [
    "openmates apps web search \"OpenMates AI assistant\" --json",
  ],
};

function findGeneratedAppSkillCommand(
  appId: string | undefined,
  skillId: string | undefined,
): GeneratedAppSkillCommand | undefined {
  if (!appId || !skillId) return undefined;
  return GENERATED_APP_SKILL_COMMANDS.find(
    (command) => command.app_id === appId && command.skill_id === skillId,
  );
}

function appSkillInputShape(command: GeneratedAppSkillCommand): AppSkillInputShape {
  const schema = command.schema ?? { type: "object", properties: {} };
  const requests = schema.properties?.requests;
  if (requests?.type === "array") {
    const itemSchema = requests.items ?? { type: "object", properties: {} };
    return {
      kind: "request-array",
      schema: itemSchema,
      properties: itemSchema.properties ?? {},
      required: itemSchema.required ?? [],
    };
  }
  return {
    kind: "flat",
    schema,
    properties: schema.properties ?? {},
    required: schema.required ?? [],
  };
}

async function handleGeneratedAppSkillCommand(
  client: OpenMatesClient,
  command: GeneratedAppSkillCommand,
  positionals: string[],
  flags: Record<string, string | boolean>,
  apiKey?: string,
): Promise<void> {
  if (flags.help === true) {
    printGeneratedAppSkillCommandHelp(command);
    return;
  }

  const inputData = buildGeneratedAppSkillInput(command, positionals, flags);
  try {
    const result = await client.runSkill({
      app: command.app_id,
      skill: command.skill_id,
      inputData,
      apiKey,
    });
    if (flags.json === true) {
      printJson(result);
    } else {
      printSkillResult(command.app_id, command.skill_id, result);
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`\x1b[31m✗ ${command.app_id}/${command.skill_id} failed:\x1b[0m ${msg}`);
    process.exit(1);
  }
}

function buildGeneratedAppSkillInput(
  command: GeneratedAppSkillCommand,
  positionals: string[],
  flags: Record<string, string | boolean>,
): Record<string, unknown> {
  if (typeof flags.input === "string") {
    try {
      const parsed = JSON.parse(flags.input) as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("input must be a JSON object");
      }
      return parsed as Record<string, unknown>;
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      throw new Error(`Invalid --input JSON: ${detail}`);
    }
  }

  const shape = appSkillInputShape(command);
  const value = buildGeneratedAppSkillValue(command, shape, positionals, flags);
  if (shape.kind === "request-array") {
    return { requests: [value] };
  }
  return value;
}

function buildGeneratedAppSkillValue(
  command: GeneratedAppSkillCommand,
  shape: AppSkillInputShape,
  positionals: string[],
  flags: Record<string, string | boolean>,
): Record<string, unknown> {
  if (command.app_id === "travel" && command.skill_id === "search_connections") {
    return buildTravelConnectionsRequest(positionals, flags);
  }

  const value: Record<string, unknown> = {};
  const consumedPositionals = applyPrimaryPositionals(command, shape, value, positionals);
  for (const [name, schema] of Object.entries(shape.properties)) {
    if (value[name] !== undefined || name === "requests") continue;
    const raw = readFlag(flags, name);
    if (raw === undefined) continue;
    value[name] = coerceAppSkillFlagValue(name, raw, schema);
  }

  const remainingPositionals = positionals.slice(consumedPositionals);
  if (remainingPositionals.length > 0) {
    throw new Error(
      `Unexpected argument(s): ${remainingPositionals.join(" ")}\n\nRun: openmates apps ${command.app_id} ${command.skill_id} --help`,
    );
  }

  const missing = shape.required.filter((name) => value[name] === undefined || value[name] === "");
  if (missing.length > 0) {
    throw new Error(
      `Missing required option(s): ${missing.map((name) => `--${kebabCase(name)}`).join(", ")}\n\nRun: openmates apps ${command.app_id} ${command.skill_id} --help`,
    );
  }
  return value;
}

function buildTravelConnectionsRequest(
  positionals: string[],
  flags: Record<string, string | boolean>,
): Record<string, unknown> {
  const origin = stringFlag(flags, "origin") ?? positionals[0];
  const destination = stringFlag(flags, "destination") ?? positionals[1];
  const date = stringFlag(flags, "date") ?? positionals[2];
  if (!origin || !destination || !date) {
    throw new Error(
      "Missing travel route. Use --origin <place> --destination <place> --date <YYYY-MM-DD>.\n\n" +
        "Example: openmates apps travel search_connections --origin Berlin --destination Munich --date 2026-08-01 --json",
    );
  }
  const request: Record<string, unknown> = {
    legs: [{ origin, destination, date }],
  };
  const transport = stringFlag(flags, "transport") ?? stringFlag(flags, "transport-method");
  if (transport) request.transport_methods = [transport];
  return request;
}

function applyPrimaryPositionals(
  command: GeneratedAppSkillCommand,
  shape: AppSkillInputShape,
  value: Record<string, unknown>,
  positionals: string[],
): number {
  if (positionals.length === 0) return 0;

  if (command.app_id === "code" && command.skill_id === "get_docs") {
    if (value.library === undefined) value.library = positionals[0];
    if (value.question === undefined && positionals.length > 1) {
      value.question = positionals.slice(1).join(" ");
    }
    return positionals.length;
  }

  const primary = primaryPositionalProperty(shape.properties, shape.required);
  if (!primary || value[primary] !== undefined) return 0;
  value[primary] = positionals.join(" ");
  return positionals.length;
}

function primaryPositionalProperty(
  properties: Record<string, JsonSchema>,
  required: string[],
): string | undefined {
  const preferred = ["query", "url", "location", "expression", "prompt", "speciality", "library"];
  for (const name of preferred) {
    if (properties[name]?.type === "string") return name;
  }
  return required.find((name) => properties[name]?.type === "string");
}

function readFlag(
  flags: Record<string, string | boolean>,
  name: string,
): string | boolean | undefined {
  return flags[name] ?? flags[kebabCase(name)];
}

function stringFlag(flags: Record<string, string | boolean>, name: string): string | undefined {
  const raw = readFlag(flags, name);
  return typeof raw === "string" && raw.trim() ? raw.trim() : undefined;
}

function coerceAppSkillFlagValue(
  name: string,
  raw: string | boolean,
  schema: JsonSchema,
): unknown {
  if (schema.type === "boolean") return raw === true || raw === "true";
  if (schema.type === "integer") {
    if (typeof raw !== "string") throw new Error(`--${kebabCase(name)} requires an integer value`);
    const parsed = Number.parseInt(raw, 10);
    if (!Number.isInteger(parsed)) throw new Error(`--${kebabCase(name)} must be an integer`);
    return parsed;
  }
  if (schema.type === "number") {
    if (typeof raw !== "string") throw new Error(`--${kebabCase(name)} requires a number value`);
    const parsed = Number(raw);
    if (!Number.isFinite(parsed)) throw new Error(`--${kebabCase(name)} must be a number`);
    return parsed;
  }
  if (schema.type === "array") {
    if (typeof raw !== "string") return [];
    return raw.split(/[,\n]/).map((value) => value.trim()).filter(Boolean);
  }
  return typeof raw === "string" ? raw : String(raw);
}

function printGeneratedAppSkillCommandHelp(command: GeneratedAppSkillCommand): void {
  const shape = appSkillInputShape(command);
  header(`${capitalise(command.app_id)} › ${command.skill_id}`);
  if (command.description) console.log(`\n${command.description}\n`);
  console.log("Usage:");
  console.log(`  openmates apps ${command.app_id} ${command.skill_id} [value] [options] [--json]`);
  console.log(`  openmates apps ${command.app_id} ${command.skill_id} --input '<json>' [--json]`);
  console.log("\nOptions:");
  console.log("  --input <json>       Full app-skill input object. Use this for advanced/nested payloads.");
  for (const [name, schema] of Object.entries(shape.properties)) {
    const required = shape.required.includes(name) ? " required" : "";
    const type = appSkillCliType(schema);
    const description = schema.description ? `  ${schema.description.replace(/\s+/g, " ").slice(0, 120)}` : "";
    console.log(`  --${kebabCase(name)} <${type}>${required}${description}`);
  }
  if (command.app_id === "travel" && command.skill_id === "search_connections") {
    console.log("  --origin <place>     Route origin for a typed connection search.");
    console.log("  --destination <place> Route destination for a typed connection search.");
    console.log("  --date <YYYY-MM-DD>  Departure date for a typed connection search.");
    console.log("  --transport <mode>   Optional transport mode, e.g. train or plane.");
  }
  console.log("  --api-key <key>      Use an API key instead of a stored CLI session.");
  console.log("  --json               Print the raw response envelope as JSON.");
  console.log("\nExamples:");
  const key = `${command.app_id}/${command.skill_id}`;
  const examples = APP_SKILL_COMMAND_EXAMPLES[key] ?? [buildGeneratedAppSkillExample(command, shape)];
  for (const example of examples) console.log(`  ${example}`);
  console.log("\nInspect metadata:");
  console.log(`  openmates apps skill-info ${command.app_id} ${command.skill_id}`);
}

function appSkillCliType(schema: JsonSchema): string {
  if (schema.enum && schema.enum.length > 0) return schema.enum.map(String).join("|");
  if (schema.type === "array") return "csv";
  return schema.type ?? "value";
}

function buildGeneratedAppSkillExample(
  command: GeneratedAppSkillCommand,
  shape: AppSkillInputShape,
): string {
  const primary = primaryPositionalProperty(shape.properties, shape.required);
  const value = primary ? String(buildExampleValue(primary, shape.properties[primary]?.type ?? "string", shape.properties[primary]?.description ?? "")) : "<value>";
  return `openmates apps ${command.app_id} ${command.skill_id} ${JSON.stringify(value)} --json`;
}

function kebabCase(value: string): string {
  return value.replace(/_/g, "-");
}

async function handleApps(
  client: OpenMatesClient,
  subcommand: string | undefined,
  rest: string[],
  flags: Record<string, string | boolean>,
): Promise<void> {
  // API key is optional — session cookies are used when absent
  const apiKey = resolveApiKey(flags) ?? undefined;

  if (!subcommand || subcommand === "help") {
    printAppsHelp();
    return;
  }

  // `apps <app> --help` → show app info. Skill help uses the explicit
  // metadata command `apps skill-info <app> <skill>`, not a generic runner.
  if (
    flags.help === true &&
    subcommand !== "list" &&
    subcommand !== "info" &&
    subcommand !== "skill-info" &&
    subcommand !== "examples"
  ) {
    const potentialApp = subcommand;
    const potentialSkill = rest[0];
    if (potentialSkill) {
      const command = findGeneratedAppSkillCommand(potentialApp, potentialSkill);
      if (command) {
        printGeneratedAppSkillCommandHelp(command);
        return;
      }
      console.error(
        "Generic app-skill CLI execution is not supported.\n\n" +
          "Use an explicit typed command for this app skill, or inspect metadata with:\n" +
          `  openmates apps skill-info ${potentialApp} ${potentialSkill}\n`,
      );
      process.exit(1);
    }
    try {
      const data = await client.getApp(potentialApp);
      await printAppInfo(client, data as AppMetadata);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error(`\x1b[31m✗ ${msg}\x1b[0m\n`);
      const suggestion = await suggestAppOrSkill(
        client,
        potentialApp,
        potentialSkill ?? "",
        apiKey,
      );
      if (suggestion) console.error(`${suggestion}\n`);
      console.error(`List all apps: openmates apps list`);
      process.exit(1);
    }
    return;
  }

  if (subcommand === "list") {
    const data = await client.listApps(apiKey);
    if (flags.json === true) {
      printJson(data);
    } else {
      printAppsList(data as AppsListResponse);
    }
    return;
  }

  if (subcommand === "info") {
    const appId = rest[0];
    if (!appId) {
      console.error("Missing app ID.\n");
      printAppsHelp();
      process.exit(1);
    }
    try {
      const data = await client.getApp(appId);
      if (flags.json === true) {
        printJson(data);
      } else {
        await printAppInfo(client, data as AppMetadata);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error(`\x1b[31m✗ ${msg}\x1b[0m\n`);
      const suggestion = await suggestAppOrSkill(client, appId, "", apiKey);
      if (suggestion) console.error(`${suggestion}\n`);
      console.error(`List all apps: openmates apps list`);
      process.exit(1);
    }
    return;
  }

  if (subcommand === "skill-info") {
    const [appId, skillId] = rest;
    if (!appId || !skillId) {
      console.error(`Missing ${!appId ? "app ID" : "skill ID"}.\n`);
      printAppsHelp();
      process.exit(1);
    }
    const data = await client.getSkillInfo(appId, skillId, apiKey);
    if (flags.json === true) {
      printJson(data);
    } else {
      await printSkillInfo(client, appId, data as SkillMetadata);
    }
    return;
  }

  if (subcommand === "examples") {
    const [appId, skillId] = rest;
    if (flags.help === true) {
      printAppsHelp();
      return;
    }
    if (!appId) {
      console.error("Missing app ID.\n");
      printAppsHelp();
      process.exit(1);
    }

    const examples = skillId
      ? listExampleChatsForSkill(appId, skillId)
      : listExampleChatsForApp(appId);
    if (flags.json === true) {
      printJson({
        app_id: appId,
        skill_id: skillId ?? null,
        examples: examples.map(exampleChatForSkillToJson),
      });
    } else {
      printExampleChatsForSkill(appId, skillId, examples);
    }
    return;
  }

  if (subcommand === "run") {
    console.error(
      "Generic app-skill CLI execution is not supported.\n\n" +
        "Use an explicit typed command such as `openmates tasks ...`, `openmates workflows ...`, or another app-specific command.\n" +
        "Inspect app metadata with `openmates apps list`, `openmates apps info <app-id>`, or `openmates apps skill-info <app-id> <skill-id>`.\n",
    );
    process.exit(1);
  }

  // ── travel booking-link: resolve a booking URL from a booking_token ────
  // openmates apps travel booking-link --token "..." [--context '{...}']
  if (subcommand === "travel" && rest[0] === "booking-link") {
    const token = typeof flags.token === "string" ? flags.token : undefined;
    if (!token) {
      console.error(
        "Missing --token flag.\n\n" +
          "Usage:\n" +
          "  openmates apps travel booking-link --token \"<booking_token>\" [--context '<json>']\n\n" +
          "The booking_token is shown in the output of:\n" +
          "  openmates apps travel search_connections --input '...'\n",
      );
      process.exit(1);
    }
    let bookingContext: Record<string, string> | undefined;
    if (typeof flags.context === "string") {
      try {
        bookingContext = JSON.parse(flags.context) as Record<string, string>;
      } catch {
        console.error("Invalid --context JSON.");
        process.exit(1);
      }
    }
    try {
      const result = await client.getBookingLink({
        bookingToken: token,
        bookingContext,
        apiKey,
      });
      if (flags.json === true) {
        printJson(result);
      } else if (result.success && result.booking_url) {
        header(
          `Travel › Booking Link${result.credits_charged ? `  \x1b[2m(${result.credits_charged} credits)\x1b[0m` : ""}\n`,
        );
        kv("URL", result.booking_url);
        if (result.booking_provider) kv("Provider", result.booking_provider);
        console.log(
          `\n\x1b[2mOpen this URL in your browser to complete the booking.\x1b[0m`,
        );
      } else {
        console.error(
          `\x1b[31m✗ Booking link not found:\x1b[0m ${result.error ?? "no booking URL available for this flight"}`,
        );
        process.exit(1);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error(`\x1b[31m✗ Booking link request failed:\x1b[0m ${msg}`);
      process.exit(1);
    }
    return;
  }

  if (subcommand === "code" && rest[0] === "run") {
    await handleCodeRun(client, flags, apiKey);
    return;
  }

  if (subcommand === "models3d" && rest[0] === "search") {
    await handleModels3dSearch(client, flags, apiKey);
    return;
  }

  const generatedCommand = findGeneratedAppSkillCommand(subcommand, rest[0]);
  if (generatedCommand) {
    await handleGeneratedAppSkillCommand(client, generatedCommand, rest.slice(1), flags, apiKey);
    return;
  }

  const app = subcommand;
  const skill = rest[0];
  if (app && skill) {
    console.error(
      "Generic app-skill CLI execution is not supported.\n\n" +
        `There is no generic runner for \`openmates apps ${app} ${skill}\`.\n` +
        "Use the app's explicit typed command or inspect metadata with:\n" +
        `  openmates apps skill-info ${app} ${skill}\n`,
    );
    process.exit(1);
  }

  // `apps <app>` with no skill — treat as `apps info <app>`
  if (app && !skill) {
    try {
      const data = await client.getApp(app);
      if (flags.json === true) {
        printJson(data);
      } else {
        await printAppInfo(client, data as AppMetadata);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error(`\x1b[31m✗ ${msg}\x1b[0m\n`);
      const suggestion = await suggestAppOrSkill(client, app, "", apiKey);
      if (suggestion) console.error(`${suggestion}\n`);
      console.error(`List all apps: openmates apps list`);
      process.exit(1);
    }
    return;
  }

  console.error(`Unknown apps subcommand '${subcommand}'.\n`);
  printAppsHelp();
  process.exit(1);
}

const MODELS3D_SEARCH_SORTS = new Set(["best_match", "popular", "downloads", "newest"]);

async function handleModels3dSearch(
  client: OpenMatesClient,
  flags: Record<string, string | boolean>,
  apiKey?: string,
): Promise<void> {
  const query = typeof flags.query === "string" ? flags.query.trim() : "";
  if (!query) {
    console.error(
      "Missing --query flag.\n\n" +
        "Usage:\n" +
        "  openmates apps models3d search --query benchy [--count 10] [--providers Printables] [--sort best_match|popular|downloads|newest] [--free-only] [--json]\n",
    );
    process.exit(1);
  }

  const count = parsePositiveIntegerFlag(flags.count, "--count");
  const sort = typeof flags.sort === "string" ? flags.sort.trim().toLowerCase() : undefined;
  if (sort && !MODELS3D_SEARCH_SORTS.has(sort)) {
    console.error(`--sort must be one of: ${Array.from(MODELS3D_SEARCH_SORTS).join(", ")}`);
    process.exit(1);
  }

  const providers = [
    ...splitCsvFlag(flags.provider),
    ...splitCsvFlag(flags.providers),
  ];
  const request: Record<string, unknown> = { query };
  if (count !== undefined) request.count = count;
  if (providers.length > 0) request.providers = providers;
  if (sort) request.sort = sort;
  if (flags["free-only"] === true) request.free_only = true;

  try {
    const result = await client.runSkill({
      app: "models3d",
      skill: "search",
      inputData: { requests: [request] },
      apiKey,
    });
    if (flags.json === true) {
      printJson(result);
    } else {
      printSkillResult("models3d", "search", result);
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`\x1b[31m✗ 3D model search failed:\x1b[0m ${msg}`);
    process.exit(1);
  }
}

interface CodeRunSkillResponse {
  success?: boolean;
  data?: {
    results?: Array<{
      execution_id?: string;
      status?: string;
      target_filename?: string;
      files?: string[];
      stream_path?: string;
      status_path?: string;
      credits_per_minute?: number;
    }>;
  };
}

async function handleCodeRun(
  client: OpenMatesClient,
  flags: Record<string, string | boolean>,
  apiKey?: string,
): Promise<void> {
  const requests = await buildCodeRunRequestsFromFlags({
    code: typeof flags.code === "string" ? flags.code : undefined,
    language: typeof flags.language === "string" ? flags.language : undefined,
    filename: typeof flags.filename === "string" ? flags.filename : undefined,
    entry: typeof flags.entry === "string" ? flags.entry : undefined,
    file: typeof flags.file === "string" ? flags.file : undefined,
    dir: typeof flags.dir === "string" ? flags.dir : undefined,
    url: typeof flags.url === "string" ? flags.url : undefined,
    repo: typeof flags.repo === "string" ? flags.repo : undefined,
    include: typeof flags.include === "string" ? flags.include : undefined,
    exclude: typeof flags.exclude === "string" ? flags.exclude : undefined,
    noInternet: flags["no-internet"] === true,
    chat: typeof flags.chat === "string" ? flags.chat : undefined,
    targetEmbed: typeof flags["target-embed"] === "string" ? flags["target-embed"] : undefined,
  });

  if (flags.json !== true) {
    const first = requests[0];
    if (first.mode === "direct") {
      process.stderr.write(`Starting Code Run for ${first.entry_path} (${first.files.length} file${first.files.length === 1 ? "" : "s"})...\n`);
    }
  }

  const response = await client.runSkill({
    app: "code",
    skill: "run",
    inputData: { requests: requests as unknown as Array<Record<string, unknown>> },
    apiKey,
  }) as CodeRunSkillResponse;
  const result = response.data?.results?.[0];
  if (!result?.execution_id || !result.status_path) {
    throw new Error("Code Run did not return an execution id.");
  }

  const streamAuth = apiKey ? null : await client.getCodeRunStreamAuth();
  let finalStatus: Record<string, unknown>;
  if (streamAuth && result.stream_path) {
    const url = buildCodeRunStreamUrl({
      apiUrl: client.apiUrl,
      executionId: result.execution_id,
      sessionId: streamAuth.sessionId,
      token: streamAuth.token,
    });
    try {
      finalStatus = await streamCodeRunToTerminal(url, flags.json === true);
    } catch (err) {
      if (!streamAuth.fallbackToken || streamAuth.fallbackToken === streamAuth.token) throw err;
      const fallbackUrl = buildCodeRunStreamUrl({
        apiUrl: client.apiUrl,
        executionId: result.execution_id,
        sessionId: streamAuth.sessionId,
        token: streamAuth.fallbackToken,
      });
      finalStatus = await streamCodeRunToTerminal(fallbackUrl, flags.json === true);
    }
  } else {
    finalStatus = await pollCodeRunStatus(client, result.status_path, apiKey, flags.json === true);
  }

  if (flags.json === true) {
    printJson({ ...result, final: finalStatus });
  }
}

async function streamCodeRunToTerminal(url: string, jsonMode: boolean): Promise<Record<string, unknown>> {
  return await new Promise((resolve, reject) => {
    const ws = new WebSocket(url);
    let lastStatus: Record<string, unknown> = {};
    ws.on("message", (data) => {
      try {
        const message = JSON.parse(String(data)) as { type?: string; payload?: Record<string, unknown> };
        const payload = message.payload ?? {};
        if (message.type === "code_run_event") {
          const kind = String(payload.kind ?? "status");
          const text = String(payload.text ?? "");
          if (!jsonMode) {
            if (kind === "stdout") process.stdout.write(text);
            else process.stderr.write(text);
          }
        } else if (message.type === "code_run_update") {
          lastStatus = { ...lastStatus, ...payload };
          const status = String(payload.status ?? "");
          if (["finished", "failed", "timeout", "cancelled"].includes(status)) {
            ws.close();
            resolve(lastStatus);
          }
        }
      } catch (err) {
        ws.close();
        reject(err);
      }
    });
    ws.on("error", () => reject(new Error("Code Run stream failed.")));
    ws.on("close", () => {
      if (Object.keys(lastStatus).length > 0) resolve(lastStatus);
    });
  });
}

async function pollCodeRunStatus(
  client: OpenMatesClient,
  statusPath: string,
  apiKey: string | undefined,
  jsonMode: boolean,
): Promise<Record<string, unknown>> {
  for (;;) {
    const status = await client.getCodeRunStatus(statusPath, apiKey);
    const value = String(status.status ?? "");
    if (!jsonMode && value) process.stderr.write(`Code Run status: ${value}\n`);
    if (["finished", "failed", "timeout", "cancelled"].includes(value)) return status;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}

/**
 * Suggest the closest app or skill name when a 404 occurs.
 * Uses Levenshtein distance for fuzzy matching against available apps/skills.
 */
async function suggestAppOrSkill(
  client: OpenMatesClient,
  app: string,
  skill: string,
  apiKey?: string,
): Promise<string | null> {
  try {
    const data = (await client.listApps(apiKey)) as {
      apps?: Array<{ id: string; skills?: Array<{ id: string }> }>;
    };
    const apps = data.apps ?? [];
    const appIds = apps.map((a) => a.id);

    // Check if app exists
    const matchedApp = apps.find((a) => a.id === app);
    if (!matchedApp) {
      // Suggest closest app name
      const closest = findClosestMatch(app, appIds);
      if (closest) {
        const suffix = skill ? ` ${skill}` : "";
        return `Did you mean: openmates apps ${closest}${suffix}`;
      }
      return `Available apps: ${appIds.join(", ")}`;
    }

    // App exists but skill not found — suggest closest skill
    const skillIds = (matchedApp.skills ?? []).map((s) => s.id);
    const closest = findClosestMatch(skill, skillIds);
    if (closest) {
      return `Did you mean: openmates apps ${app} ${closest}`;
    }
    if (skillIds.length > 0) {
      return `Available skills for '${app}': ${skillIds.join(", ")}`;
    }
    return null;
  } catch {
    return null;
  }
}

/** Simple Levenshtein distance for short CLI names. */
function levenshtein(a: string, b: string): number {
  const m = a.length;
  const n = b.length;
  const dp: number[][] = Array.from({ length: m + 1 }, () =>
    Array(n + 1).fill(0) as number[],
  );
  for (let i = 0; i <= m; i++) dp[i][0] = i;
  for (let j = 0; j <= n; j++) dp[0][j] = j;
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      dp[i][j] =
        a[i - 1] === b[j - 1]
          ? dp[i - 1][j - 1]
          : 1 + Math.min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1]);
    }
  }
  return dp[m][n];
}

/** Find the closest match within a reasonable edit distance (max 3). */
function findClosestMatch(
  input: string,
  candidates: string[],
): string | null {
  let best: string | null = null;
  let bestDist = 4; // max acceptable distance
  for (const candidate of candidates) {
    const dist = levenshtein(input.toLowerCase(), candidate.toLowerCase());
    if (dist < bestDist) {
      bestDist = dist;
      best = candidate;
    }
  }
  return best;
}

// ---------------------------------------------------------------------------
// Embeds
// ---------------------------------------------------------------------------

async function handleEmbeds(
  client: OpenMatesClient,
  subcommand: string | undefined,
  rest: string[],
  flags: Record<string, string | boolean>,
): Promise<void> {
  if (!subcommand || subcommand === "help" || flags.help === true) {
    printEmbedsHelp();
    return;
  }

  if (subcommand === "show") {
    const embedId = rest[0];
    if (!embedId) {
      console.error("Missing embed ID.\n");
      printEmbedsHelp();
      process.exit(1);
    }
    const embed = await client.getEmbed(embedId);
    if (flags.json === true) {
      printJson(embed);
    } else {
      await renderEmbedFullscreen(embed, client);
    }
    return;
  }

  if (subcommand === "share") {
    const id = rest[0];
    if (!id) {
      console.error(
        "Missing embed ID. Usage: openmates embeds share <embed-id>",
      );
      process.exit(1);
    }
    const durationSeconds = (
      typeof flags.expires === "string" ? parseInt(flags.expires, 10) : 0
    ) as ShareDuration;
    const password =
      typeof flags.password === "string" ? flags.password : undefined;

    if (password && password.length > 10) {
      console.error("Password must be at most 10 characters.");
      process.exit(1);
    }

    try {
      const url = await client.createEmbedShareLink(
        id,
        durationSeconds,
        password,
      );
      if (flags.json === true) {
        printJson({
          url,
          embed_id: id,
          expires: durationSeconds,
          password_protected: !!password,
        });
      } else {
        process.stdout.write(`\n[1mEmbed share link[0m\n`);
        process.stdout.write(`${url}\n\n`);
        if (durationSeconds > 0) {
          process.stdout.write(
            `[2mExpires in ${humanizeDuration(durationSeconds)}[0m\n`,
          );
        }
        if (password) {
          process.stdout.write(`[2mPassword protected[0m\n`);
        }
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error(`Share link error: ${msg}`);
      process.exit(1);
    }
    return;
  }

  if (subcommand === "preview") {
    await handleEmbedPreviewCommand(client, rest, flags);
    return;
  }

  if (subcommand === "versions") {
    const action = rest[0];
    const embedId = rest[1];
    if (!action || !embedId || !["list", "show", "restore"].includes(action)) {
      console.error("Usage: openmates embeds versions <list|show|restore> <embed-id> [--version <n>]\n");
      printEmbedsHelp();
      process.exit(1);
    }

    if (action === "list") {
      const versions = await client.listEmbedVersions(embedId);
      if (flags.json === true) {
        printJson(versions);
      } else {
        process.stdout.write(`\n\x1b[1mEmbed versions\x1b[0m ${versions.embed_id}\n`);
        for (const version of versions.versions) {
          const marker = version.version_number === versions.current_version ? " (current)" : "";
          const date = new Date(version.created_at * 1000).toISOString();
          process.stdout.write(`  v${version.version_number}${marker}  ${date}\n`);
        }
        if (versions.readonly) process.stdout.write("\x1b[2mRead-only shared history\x1b[0m\n");
      }
      return;
    }

    const version = typeof flags.version === "string" ? parseInt(flags.version, 10) : NaN;
    if (!Number.isFinite(version) || version <= 0) {
      console.error("Missing or invalid --version <n>.");
      process.exit(1);
    }

    if (action === "show") {
      const result = await client.getEmbedVersion(embedId, version);
      if (typeof result.content !== "string") {
        throw new Error("Embed version content was not available after local reconstruction.");
      }
      if (typeof flags.output === "string") {
        writeFileSync(flags.output, result.content, "utf-8");
        if (flags.json === true) {
          printJson({ ...result, output: flags.output });
        } else {
          process.stdout.write(`Wrote ${result.embed_id} v${result.version_number} to ${flags.output}\n`);
        }
      } else if (flags.json === true) {
        printJson(result);
      } else {
        process.stdout.write(`\n\x1b[1m${result.embed_id} v${result.version_number}\x1b[0m\n`);
        process.stdout.write(`${result.content}\n`);
      }
      return;
    }

    if (flags.yes !== true) {
      await confirmOrExit(`Restore embed ${embedId} to version ${version}? This creates a new latest version. [y/N] `);
    }
    const restored = await client.restoreEmbedVersion(embedId, version);
    if (flags.json === true) {
      printJson(restored);
    } else {
      process.stdout.write(
        `Restored v${restored.restored_from_version} as new v${restored.version_number} for ${restored.embed_id}.\n`,
      );
    }
    return;
  }

  console.error(`Unknown embeds subcommand '${subcommand}'.\n`);
  printEmbedsHelp();
  process.exit(1);
}

async function handleEmbedPreviewCommand(
  client: OpenMatesClient,
  rest: string[],
  flags: Record<string, string | boolean>,
): Promise<void> {
  const action = rest[0];
  if (!action || action === "help") {
    printEmbedsHelp();
    return;
  }

  if (action === "start") {
    const embedId = rest[1];
    const chatId = typeof flags["chat-id"] === "string" ? flags["chat-id"] : typeof flags.chat === "string" ? flags.chat : undefined;
    if (!embedId || !chatId) {
      throw new Error("Usage: openmates embeds preview start <embed-id> --chat-id <chat-id> [--wait] [--json]");
    }
    const started = await client.startApplicationPreview({
      embedId,
      chatId,
      sharedContext: typeof flags["shared-context"] === "string" ? flags["shared-context"] : undefined,
      requestedRuntime: typeof flags.runtime === "string" ? flags.runtime : undefined,
      sourceMessageId: typeof flags["source-message-id"] === "string" ? flags["source-message-id"] : undefined,
    });
    const result = flags.wait === true
      ? await waitForApplicationPreview(client, started, flags)
      : started;
    printApplicationPreviewResult(result, flags);
    return;
  }

  if (action === "status") {
    const sessionId = rest[1];
    if (!sessionId) throw new Error("Usage: openmates embeds preview status <session-id> [--json]");
    printApplicationPreviewResult(await client.getApplicationPreviewStatus(sessionId), flags);
    return;
  }

  if (action === "open") {
    const sessionId = rest[1];
    if (!sessionId) throw new Error("Usage: openmates embeds preview open <session-id> [--json]");
    printApplicationPreviewResult(await client.openApplicationPreview(sessionId), flags);
    return;
  }

  if (action === "stop") {
    const sessionId = rest[1];
    if (!sessionId) throw new Error("Usage: openmates embeds preview stop <session-id> [--json]");
    printApplicationPreviewResult(await client.stopApplicationPreview(sessionId), flags);
    return;
  }

  throw new Error(`Unknown embeds preview command '${action}'. Run 'openmates embeds --help'.`);
}

async function waitForApplicationPreview(
  client: OpenMatesClient,
  started: { session_id: string; status: string },
  flags: Record<string, string | boolean>,
): Promise<Record<string, unknown>> {
  const timeoutSeconds = parsePositiveIntegerFlag(flags["timeout-seconds"], "--timeout-seconds") ?? 120;
  const deadline = Date.now() + timeoutSeconds * 1000;
  let current: Record<string, unknown> = started as unknown as Record<string, unknown>;
  while (Date.now() < deadline) {
    const status = String(current.status ?? "");
    if (["running", "failed", "timeout", "cancelled", "stopped"].includes(status)) return current;
    await new Promise((resolve) => setTimeout(resolve, 1000));
    current = await client.getApplicationPreviewStatus(started.session_id) as unknown as Record<string, unknown>;
  }
  throw new Error(`Application preview did not reach a terminal or running state within ${timeoutSeconds}s`);
}

function printApplicationPreviewResult(result: unknown, flags: Record<string, string | boolean>): void {
  if (flags.json === true) {
    printJson(result);
    return;
  }
  const value = result && typeof result === "object" ? result as Record<string, unknown> : {};
  console.log(`Session: ${String(value.session_id ?? "")}`);
  console.log(`Status: ${String(value.status ?? "unknown")}`);
  if (typeof value.preview_url === "string") console.log(`Preview URL: ${value.preview_url}`);
  if (typeof value.charged_credits === "number") console.log(`Charged credits: ${value.charged_credits}`);
  if (typeof value.error === "string" && value.error) console.log(`Error: ${value.error}`);
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

type SettingsInfoCommand = {
  path: string[];
  description: string;
  examples: string[];
  webPath?: string;
  reason?: string;
};

const SETTINGS_EXECUTABLE_COMMANDS: SettingsInfoCommand[] = [
  { path: ["account", "info"], description: "Show account info", examples: ["openmates settings account info --json"] },
  { path: ["account", "timezone", "set"], description: "Set account timezone", examples: ["openmates settings account timezone set Europe/Berlin"] },
  { path: ["account", "interests", "list"], description: "Show encrypted account topic interests", examples: ["openmates settings account interests list --json"] },
  { path: ["account", "interests", "set"], description: "Set encrypted account topic interests", examples: ["openmates settings account interests set software_development run_code privacy"] },
  { path: ["account", "interests", "clear"], description: "Clear encrypted account topic interests", examples: ["openmates settings account interests clear --yes"] },
  { path: ["account", "export", "manifest"], description: "Show account export manifest", examples: ["openmates settings account export manifest --json"] },
  { path: ["account", "export", "data"], description: "Fetch account export data", examples: ["openmates settings account export data --json"] },
  { path: ["account", "import-chat"], description: "Import a CLI chat export file", examples: ["openmates settings account import-chat ./chat.yml", "openmates settings account import-chat ./payload.json"] },
  { path: ["account", "username", "set"], description: "Change account username", examples: ["openmates settings account username set alice_123"] },
  { path: ["account", "profile-picture", "set"], description: "Upload a profile picture", examples: ["openmates settings account profile-picture set ./avatar.jpg"] },
  { path: ["account", "chats", "stats"], description: "Show chat statistics", examples: ["openmates settings account chats stats"] },
  { path: ["account", "delete", "preview"], description: "Preview account deletion impact", examples: ["openmates settings account delete preview"] },
  { path: ["account", "delete"], description: "Delete your account with email code plus 2FA when configured", examples: ["openmates settings account delete --yes"] },
  { path: ["account", "storage", "overview"], description: "Show storage overview", examples: ["openmates settings account storage overview"] },
  { path: ["account", "storage", "files"], description: "List stored files", examples: ["openmates settings account storage files --category images"] },
  { path: ["account", "storage", "delete"], description: "Delete one stored file by file ID", examples: ["openmates settings account storage delete <file-id> --yes"] },
  { path: ["interface", "language", "set"], description: "Set interface language", examples: ["openmates settings interface language set en"] },
  { path: ["interface", "dark-mode", "set"], description: "Set dark mode on or off", examples: ["openmates settings interface dark-mode set on"] },
  { path: ["interface", "font", "set"], description: "Set interface font", examples: ["openmates settings interface font set lexend"] },
  { path: ["ai", "models", "set-defaults"], description: "Set default AI models", examples: ["openmates settings ai models set-defaults --simple mistral/mistral-small-2506", "openmates settings ai models set-defaults --simple auto"] },
  { path: ["privacy", "auto-delete", "chats", "set"], description: "Set chat auto-deletion period", examples: ["openmates settings privacy auto-delete chats set 90d"] },
  { path: ["privacy", "debug-logs", "share"], description: "Create a debug log sharing session", examples: ["openmates settings privacy debug-logs share --duration 1h --confirm"] },
  { path: ["billing", "overview"], description: "Show billing overview", examples: ["openmates settings billing overview"] },
  { path: ["billing", "usage"], description: "Show usage history", examples: ["openmates settings billing usage --json"] },
  { path: ["billing", "usage", "summaries"], description: "Show usage summaries", examples: ["openmates settings billing usage summaries"] },
  { path: ["billing", "usage", "daily"], description: "Show daily usage overview", examples: ["openmates settings billing usage daily"] },
  { path: ["billing", "usage", "export"], description: "Export usage data", examples: ["openmates settings billing usage export --json"] },
  { path: ["billing", "buy-credits", "bank-transfer"], description: "Buy credits by SEPA bank transfer", examples: ["openmates settings billing buy-credits bank-transfer --credits 110000"] },
  { path: ["billing", "bank-transfer", "status"], description: "Show bank-transfer order status", examples: ["openmates settings billing bank-transfer status <order-id>"] },
  { path: ["billing", "bank-transfer", "list"], description: "List pending bank-transfer orders", examples: ["openmates settings billing bank-transfer list"] },
  { path: ["billing", "invoices", "list"], description: "List invoices", examples: ["openmates settings billing invoices list --json"] },
  { path: ["billing", "invoices", "download"], description: "Download an invoice PDF", examples: ["openmates settings billing invoices download <invoice-id> --output ./invoices"] },
  { path: ["billing", "invoices", "credit-note"], description: "Download a credit note PDF", examples: ["openmates settings billing invoices credit-note <invoice-id> --output ./invoices"] },
  { path: ["billing", "invoices", "refund"], description: "Request a refund for an invoice", examples: ["openmates settings billing invoices refund <invoice-id> --yes"] },
  { path: ["billing", "gift-card", "redeem"], description: "Redeem a gift card", examples: ["openmates settings billing gift-card redeem ABCD-1234"] },
  { path: ["billing", "gift-card", "list"], description: "List redeemed gift cards", examples: ["openmates settings billing gift-card list"] },
  { path: ["billing", "gift-card", "buy", "bank-transfer"], description: "Buy a gift card by SEPA bank transfer", examples: ["openmates settings billing gift-card buy bank-transfer --credits 21000"] },
  { path: ["billing", "gift-card", "purchase-status"], description: "Show gift-card bank-transfer purchase status", examples: ["openmates settings billing gift-card purchase-status <order-id>"] },
  { path: ["billing", "gift-card", "purchased"], description: "List purchased unused gift cards", examples: ["openmates settings billing gift-card purchased"] },
  { path: ["billing", "auto-topup", "low-balance", "set"], description: "Configure low-balance auto top-up", examples: ["openmates settings billing auto-topup low-balance set --enabled true --amount 1000 --currency eur --email you@example.com"] },
  { path: ["notifications", "status"], description: "Show notification settings", examples: ["openmates settings notifications status --json"] },
  { path: ["notifications", "list"], description: "List recent notification events", examples: ["openmates settings notifications list --limit 20 --json"] },
  { path: ["notifications", "stream"], description: "Stream notification events with SSE", examples: ["openmates settings notifications stream", "openmates settings notifications stream --count 1 --json"] },
  { path: ["notifications", "email", "set"], description: "Configure email notifications", examples: ["openmates settings notifications email set --enabled true --email you@example.com --ai-responses true --backup-reminder true --webhook-chats true"] },
  { path: ["notifications", "backup", "set"], description: "Configure backup reminder emails", examples: ["openmates settings notifications backup set --enabled true --interval 30 --email you@example.com"] },
  { path: ["reminders", "list"], description: "List active reminders", examples: ["openmates settings reminders list"] },
  { path: ["reminders", "update"], description: "Update a reminder", examples: ["openmates settings reminders update <id> --enabled false"] },
  { path: ["reminders", "delete"], description: "Delete a reminder", examples: ["openmates settings reminders delete <id> --yes"] },
  { path: ["developers", "api-keys", "list"], description: "List API keys", examples: ["openmates settings developers api-keys list"] },
  { path: ["developers", "api-keys", "create"], description: "Create an API key and reveal it once", examples: ["openmates settings developers api-keys create sdk-test --yes"] },
  { path: ["developers", "api-keys", "revoke"], description: "Revoke an API key", examples: ["openmates settings developers api-keys revoke <key-id> --yes"] },
  { path: ["report-issue", "create"], description: "Report an issue", examples: ["openmates settings report-issue create --title \"Bug\" --body \"What happened\""] },
  { path: ["report-issue", "status"], description: "Show issue status", examples: ["openmates settings report-issue status <issue-id>"] },
  { path: ["mates", "list"], description: "List available mates", examples: ["openmates settings mates list"] },
  { path: ["mates", "info"], description: "Show mate details", examples: ["openmates settings mates info software_development"] },
  { path: ["mates", "consent"], description: "Record mate settings consent", examples: ["openmates settings mates consent --yes"] },
  { path: ["newsletter", "categories"], description: "Show newsletter category preferences", examples: ["openmates settings newsletter categories"] },
  { path: ["newsletter", "categories", "set"], description: "Set newsletter category preferences", examples: ["openmates settings newsletter categories set --updates true --tips true --daily false"] },
  { path: ["newsletter", "subscribe"], description: "Subscribe an email to the newsletter", examples: ["openmates settings newsletter subscribe you@example.com --language en"] },
  { path: ["newsletter", "confirm"], description: "Confirm newsletter subscription token", examples: ["openmates settings newsletter confirm <token>"] },
  { path: ["newsletter", "unsubscribe"], description: "Unsubscribe with newsletter token", examples: ["openmates settings newsletter unsubscribe <token>"] },
  { path: ["memories"], description: "Manage encrypted memories", examples: ["openmates settings memories list", "openmates settings memories create --app-id code --item-type projects --data '{\"name\":\"OpenMates\"}'"] },
];

const SETTINGS_INFO_COMMANDS: SettingsInfoCommand[] = [
  { path: ["account", "email"], description: "Email changes are web-only", webPath: "account/email", reason: "Email changes require a guided identity verification flow.", examples: ["openmates settings account email"] },
  { path: ["security"], description: "Security settings are web-only", webPath: "account/security", reason: "Security settings require browser APIs or high-risk reauthentication.", examples: ["openmates settings security"] },
  { path: ["security", "passkeys"], description: "Passkeys are web-only", webPath: "account/security/passkeys", reason: "Passkeys require WebAuthn browser APIs.", examples: ["openmates settings security passkeys"] },
  { path: ["security", "password"], description: "Password changes are web-only", webPath: "account/security/password", reason: "The CLI never asks for account credentials.", examples: ["openmates settings security password"] },
  { path: ["security", "2fa"], description: "2FA setup and changes are web-only", webPath: "account/security/2fa", reason: "2FA setup requires a guided browser verification flow.", examples: ["openmates settings security 2fa"] },
  { path: ["security", "recovery-key"], description: "Recovery key settings are web-only", webPath: "account/security/recovery-key", reason: "Recovery keys are a high-risk account recovery surface.", examples: ["openmates settings security recovery-key"] },
  { path: ["security", "sessions"], description: "Session management is web-only", webPath: "account/security/sessions", reason: "The CLI is a paired restricted session; approval and revocation stay in the browser.", examples: ["openmates settings security sessions"] },
  { path: ["billing", "buy-credits"], description: "Credit purchase is web-only", webPath: "billing/buy-credits", reason: "Payment checkout must use the browser/payment provider UI.", examples: ["openmates settings billing buy-credits"] },
  { path: ["billing", "gift-card", "buy"], description: "Gift card purchase is web-only", webPath: "billing/gift-cards/buy", reason: "Payment checkout must use the browser/payment provider UI.", examples: ["openmates settings billing gift-card buy"] },
  { path: ["billing", "auto-topup", "monthly"], description: "Monthly auto top-up is web-only for now", webPath: "billing/auto-topup/monthly", reason: "Recurring payment setup needs a payment-flow audit before CLI support.", examples: ["openmates settings billing auto-topup monthly"] },
  { path: ["privacy", "personal-data"], description: "Personal data management is not CLI-ready yet", webPath: "privacy/hide-personal-data", reason: "The CLI needs a dedicated encrypted personal-data UX before exposing writes.", examples: ["openmates settings privacy personal-data"] },
  { path: ["shared", "tip"], description: "Tips are web-only", webPath: "shared/tip", reason: "Payment checkout must use the browser/payment provider UI.", examples: ["openmates settings shared tip"] },
  { path: ["developers", "devices"], description: "Developer devices are web-only", webPath: "developers/devices", reason: "Device approvals and revocations are sensitive.", examples: ["openmates settings developers devices"] },
  { path: ["developers", "webhooks"], description: "Developer webhooks are not CLI-ready yet", webPath: "developers/webhooks", reason: "Webhook CRUD needs a backend/API audit before CLI support.", examples: ["openmates settings developers webhooks"] },
  { path: ["support"], description: "Support payments are web-only", webPath: "support", reason: "Payment flows must use the browser/payment provider UI.", examples: ["openmates settings support"] },
  { path: ["incognito", "info"], description: "Explain incognito mode", reason: "Incognito chats are sent without saving chat history. The CLI stores no incognito transcript.", examples: ["openmates chats incognito \"Private question\""] },
  { path: ["server"], description: "Server admin settings are web/admin-only", webPath: "server", reason: "Use `openmates server --help` for self-hosted terminal server management.", examples: ["openmates server status"] },
];

function matches(actual: string[], expected: string[]): boolean {
  return expected.every((part, index) => actual[index] === part);
}

function findSettingsInfoCommand(tokens: string[]): SettingsInfoCommand | null {
  const all = [...SETTINGS_INFO_COMMANDS, ...SETTINGS_EXECUTABLE_COMMANDS];
  return all
    .sort((a, b) => b.path.length - a.path.length)
    .find((command) => matches(tokens, command.path)) ?? null;
}

async function printSettingsResult(
  resultPromise: Promise<unknown>,
  flags: Record<string, string | boolean>,
): Promise<void> {
  const result = await resultPromise;
  if (flags.json === true) {
    printJson(result);
  } else {
    printGenericObject(result);
  }
}

function printApiKeyList(
  result: ApiKeyListResult,
  flags: Record<string, string | boolean>,
): void {
  if (flags.json === true) {
    printJson(result);
    return;
  }
  if (result.api_keys.length === 0) {
    process.stdout.write("No API keys found.\n");
    return;
  }
  for (const key of result.api_keys) {
    const name = String(key.name || "Unnamed API key");
    const id = String(key.id || "unknown");
    const prefix = String(key.key_prefix || "sk-api-...");
    const access = key.full_access === false ? "Restricted access" : "Full access";
    const pendingCount = typeof key.pending_device_count === "number" ? key.pending_device_count : 0;
    process.stdout.write(`${name} (${id})\n`);
    process.stdout.write(`  Prefix: ${prefix}\n`);
    process.stdout.write(`  Access: ${access}\n`);
    process.stdout.write(`  Created: ${formatCliDateTime(key.created_at)}\n`);
    process.stdout.write(`  Last used: ${formatCliDateTime(key.last_used_at, "Never used")}\n`);
    process.stdout.write(`  Credit limit: ${formatCliCreditLimit(key.credit_limit)}\n`);
    if (pendingCount > 0) {
      process.stdout.write(`  Confirm device: ${pendingCount} pending request${pendingCount === 1 ? "" : "s"}\n`);
    }
  }
}

function formatCliDateTime(value: unknown, emptyLabel = "Unknown"): string {
  if (typeof value !== "string" || !value) return emptyLabel;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function formatCliCreditLimit(value: unknown): string {
  if (!value || typeof value !== "object") return "Unlimited credits";
  const limit = value as { credits?: unknown; period?: unknown };
  if (typeof limit.credits !== "number" || typeof limit.period !== "string") return "Unlimited credits";
  return `${limit.credits} credits / ${limit.period}`;
}

async function printSettingsMutationResult(
  resultPromise: Promise<unknown>,
  flags: Record<string, string | boolean>,
): Promise<void> {
  const result = await resultPromise;
  if (flags.json === true) {
    printJson(result);
    return;
  }
  process.stdout.write("\x1b[32m✓\x1b[0m Settings updated\n");
  if (result && typeof result === "object") printGenericObject(result);
}

function printTopicPreferences(
  preferences: TopicPreferencesPayload | null,
  flags: Record<string, string | boolean>,
  successLabel?: string,
): void {
  const payload = preferences ?? {
    version: 1,
    selectedTagIds: [],
    updatedAt: null,
  };
  const result = {
    ...payload,
    availableTagIds: INTEREST_TAG_IDS,
  };

  if (flags.json === true) {
    printJson(result);
    return;
  }

  if (successLabel) {
    process.stdout.write(`\x1b[32m✓\x1b[0m ${successLabel}\n`);
  }
  const selected = result.selectedTagIds.length > 0
    ? result.selectedTagIds.join(", ")
    : "none";
  process.stdout.write(`Selected interests: ${selected}\n`);
  process.stdout.write(`Available interests: ${INTEREST_TAG_IDS.join(", ")}\n`);
}

function printReportIssueCreateResult(result: unknown, flags: Record<string, string | boolean>): void {
  if (flags.json === true) {
    printJson(result);
    return;
  }

  process.stdout.write("\x1b[32m✓\x1b[0m Issue reported\n");
  const obj = result && typeof result === "object" ? result as Record<string, unknown> : {};
  const issueId = typeof obj.issue_id === "string" ? obj.issue_id : "";
  const shortIssueId = typeof obj.short_issue_id === "string" ? obj.short_issue_id : "";
  if (shortIssueId || issueId) {
    console.log(`Issue reference: ${shortIssueId || issueId}`);
  }
  if (issueId && shortIssueId && issueId !== shortIssueId) {
    console.log(`Internal issue ID: ${issueId}`);
  }
  if (typeof obj.message === "string") {
    console.log(obj.message);
  }
}

function addQueryParam(
  params: URLSearchParams,
  key: string,
  value: string | boolean | undefined,
): void {
  if (typeof value === "string" && value.length > 0) params.set(key, value);
}

function parseOnOff(value: string | undefined, label: string): boolean {
  if (value === "on" || value === "true" || value === "1") return true;
  if (value === "off" || value === "false" || value === "0") return false;
  throw new Error(`Invalid ${label} value '${value ?? ""}'. Use on/off or true/false.`);
}

function parseModelDefaultFlag(value: string | boolean, flag: string): string | null {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`Missing value for ${flag}. Use a provider/model-id or auto.`);
  }
  if (value === "auto" || value === "null") return null;
  return value;
}

function parseRequiredNumber(value: string | boolean | undefined, flag: string): number {
  if (typeof value !== "string") throw new Error(`Missing ${flag}.`);
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) throw new Error(`Invalid ${flag}: ${value}`);
  return parsed;
}

function parseOptionalNumber(value: string | boolean | undefined, fallback: number, flag: string): number {
  if (value === undefined) return fallback;
  return parseRequiredNumber(value, flag);
}

function parseOptionalBoolean(
  value: string | boolean | undefined,
  fallback: boolean,
  label: string,
): boolean {
  if (value === undefined) return fallback;
  if (typeof value === "boolean") return value;
  return parseOnOff(value, label);
}

function parseDataOrFlags(
  flags: Record<string, string | boolean>,
  booleanFlags: string[],
): Record<string, unknown> {
  if (typeof flags.data === "string") return JSON.parse(flags.data) as Record<string, unknown>;
  const body: Record<string, unknown> = {};
  for (const key of booleanFlags) {
    if (flags[key] !== undefined) body[key] = parseOnOff(String(flags[key]), key);
  }
  if (Object.keys(body).length === 0) throw new Error("Provide --data '<json>' or a supported flag.");
  return body;
}

function parseChatImportPayload(raw: string): { chats: Array<Record<string, unknown>> } {
  const trimmed = raw.trim();
  if (!trimmed) throw new Error("Import file is empty.");

  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    const parsed = JSON.parse(trimmed) as unknown;
    if (Array.isArray(parsed)) return { chats: parsed as Array<Record<string, unknown>> };
    if (parsed && typeof parsed === "object" && Array.isArray((parsed as Record<string, unknown>).chats)) {
      return parsed as { chats: Array<Record<string, unknown>> };
    }
    if (parsed && typeof parsed === "object") {
      const object = parsed as Record<string, unknown>;
      if (object.chat || object.messages) return { chats: [normalizeImportedChat(object)] };
    }
    throw new Error("JSON import must contain a chats array, a chat object, or messages.");
  }

  return { chats: [parseCliExportYaml(trimmed)] };
}

function normalizeImportedChat(source: Record<string, unknown>): Record<string, unknown> {
  const chat = source.chat && typeof source.chat === "object"
    ? source.chat as Record<string, unknown>
    : source;
  const messages = Array.isArray(source.messages) ? source.messages : [];
  return {
    title: chat.title ?? null,
    draft: chat.draft ?? null,
    summary: chat.summary ?? null,
    messages: messages.map((message) => normalizeImportedMessage(message as Record<string, unknown>)),
  };
}

function normalizeImportedMessage(message: Record<string, unknown>): Record<string, unknown> {
  return {
    role: message.role,
    content: message.content,
    completed_at: message.completed_at ?? message.timestamp ?? null,
    assistant_category: message.assistant_category ?? null,
    thinking: message.thinking ?? null,
    has_thinking: message.has_thinking ?? null,
    thinking_tokens: message.thinking_tokens ?? null,
  };
}

function parseCliExportYaml(raw: string): Record<string, unknown> {
  const chat: Record<string, unknown> = {};
  const messages: Array<Record<string, unknown>> = [];
  const lines = raw.split("\n");
  let section: "chat" | "messages" | null = null;
  let currentMessage: Record<string, unknown> | null = null;
  const multilineState: {
    current: { target: Record<string, unknown>; key: string; indent: number } | null;
  } = { current: null };

  const setValue = (target: Record<string, unknown>, key: string, value: string, indent: number) => {
    if (value === "|") {
      target[key] = "";
      multilineState.current = { target, key, indent: indent + 2 };
      return;
    }
    target[key] = parseYamlScalar(value);
  };

  for (const line of lines) {
    const indent = line.match(/^ */)?.[0].length ?? 0;
    const trimmed = line.trimEnd();
    if (!trimmed.trim()) continue;

    if (multilineState.current) {
      if (indent >= multilineState.current.indent) {
        const previous = String(multilineState.current.target[multilineState.current.key] ?? "");
        const nextLine = line.slice(multilineState.current.indent);
        multilineState.current.target[multilineState.current.key] = previous ? `${previous}\n${nextLine}` : nextLine;
        continue;
      }
      multilineState.current = null;
    }

    if (trimmed === "chat:") {
      section = "chat";
      currentMessage = null;
      continue;
    }
    if (trimmed === "messages:") {
      section = "messages";
      currentMessage = null;
      continue;
    }
    if (section === "messages" && trimmed.trim() === "-") {
      currentMessage = {};
      messages.push(currentMessage);
      continue;
    }

    const match = /^\s*([\w-]+):\s*(.*)$/.exec(line);
    if (!match) continue;
    const [, key, value] = match;
    if (section === "chat") setValue(chat, key, value, indent);
    if (section === "messages" && currentMessage) setValue(currentMessage, key, value, indent);
  }

  if (messages.length === 0) throw new Error("Import YAML did not contain any messages.");
  return normalizeImportedChat({ chat, messages });
}

function parseYamlScalar(value: string): unknown {
  const trimmed = value.trim();
  if (trimmed === "null") return null;
  if (trimmed === "true") return true;
  if (trimmed === "false") return false;
  if (trimmed !== "" && Number.isFinite(Number(trimmed))) return Number(trimmed);
  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'"))
  ) {
    return trimmed.slice(1, -1).replace(/\\"/g, '"').replace(/\\\\/g, "\\");
  }
  return trimmed;
}

async function saveDownloadedDocument(
  document: { filename: string; data: Uint8Array },
  output: string | boolean | undefined,
): Promise<string> {
  const { mkdir, writeFile } = await import("node:fs/promises");
  const { join, basename, dirname } = await import("node:path");
  const target = typeof output === "string" ? output : ".";
  const filename = basename(document.filename || "document.pdf");
  const filePath = target.endsWith(".pdf") ? target : join(target, filename);
  await mkdir(dirname(filePath), { recursive: true });
  await writeFile(filePath, document.data);
  return filePath;
}

function printMates(json: boolean): void {
  const mates = Object.entries(MATE_NAMES).map(([id, name]) => ({ id, name, mention: `@mate:${id}` }));
  if (json) {
    printJson(mates);
    return;
  }
  header("Mates");
  for (const mate of mates) console.log(`${mate.id.padEnd(28)} ${mate.name.padEnd(10)} ${mate.mention}`);
}

function printMateInfo(mateId: string, json: boolean): void {
  const name = MATE_NAMES[mateId];
  if (!name) throw new Error(`Unknown mate '${mateId}'. Run 'openmates settings mates list'.`);
  const data = { id: mateId, name, mention: `@mate:${mateId}` };
  if (json) {
    printJson(data);
    return;
  }
  header(`${name} (${mateId})`);
  console.log(`Mention: ${data.mention}`);
  console.log(`Use: openmates chats send "${data.mention} <message>"`);
}

async function confirmOrExit(question: string): Promise<void> {
  const rl = await import("node:readline");
  const iface = rl.createInterface({ input: process.stdin, output: process.stdout });
  const answer = await new Promise<string>((resolve) => iface.question(question, resolve));
  iface.close();
  if (answer.trim().toLowerCase() !== "y") {
    console.log("Aborted.");
    process.exit(0);
  }
}

async function promptLine(question: string): Promise<string> {
  const rl = await import("node:readline");
  const iface = rl.createInterface({ input: process.stdin, output: process.stdout });
  const answer = await new Promise<string>((resolve) => iface.question(question, resolve));
  iface.close();
  return answer.trim();
}

async function promptSecret(question: string): Promise<string> {
  if (!process.stdin.isTTY) {
    return promptLine(question);
  }
  return new Promise<string>((resolve) => {
    const stdin = process.stdin;
    const wasRaw = stdin.isRaw;
    let value = "";
    process.stdout.write(question);
    stdin.setRawMode(true);
    stdin.resume();
    const onData = (chunk: Buffer) => {
      const char = chunk.toString("utf8");
      if (char === "\r" || char === "\n") {
        stdin.off("data", onData);
        stdin.setRawMode(wasRaw);
        process.stdout.write("\n");
        resolve(value);
        return;
      }
      if (char === "\u0003") {
        stdin.off("data", onData);
        stdin.setRawMode(wasRaw);
        process.stdout.write("\n");
        process.exit(130);
      }
      if (char === "\u007f" || char === "\b") {
        value = value.slice(0, -1);
        return;
      }
      value += char;
    };
    stdin.on("data", onData);
  });
}

async function handleConnectedAccounts(
  client: OpenMatesClient,
  subcommand: string | undefined,
  flags: Record<string, string | boolean>,
): Promise<void> {
  if (!subcommand || subcommand === "help" || flags.help === true) {
    printConnectedAccountsHelp();
    return;
  }
  if (subcommand !== "import") {
    throw new Error(`Unknown connected-accounts command '${subcommand}'. Run 'openmates connected-accounts --help'.`);
  }
  if (flags.passcode !== undefined) {
    throw new Error("Connected account import passcodes must be entered through the hidden prompt, not a command-line flag.");
  }
  const payload = typeof flags.payload === "string" ? flags.payload.trim() : "";
  if (!payload) {
    throw new Error("Missing --payload. Paste the command generated by connected account settings.");
  }
  if (!client.hasSession()) {
    throw new Error("Not logged in. Run `openmates login` before importing a connected account.");
  }
  const passcode = await promptSecret("Connected account import passcode: ");
  const result = await client.importConnectedAccountFromCliPayload({
    encryptedPayload: payload,
    passcode,
  });
  if (flags.json === true) {
    printJson({
      id: result.id,
      provider_id: result.providerId,
      app_id: result.appId,
      validation: result.validation,
    });
    return;
  }
  console.log("Connected account imported.");
  console.log(`Provider: ${result.providerId}`);
  console.log(`App: ${result.appId}`);
  console.log("Validation: harmless read succeeded");
}

async function handleConnectAccount(
  client: OpenMatesClient,
  subcommand: string | undefined,
  _rest: string[],
  flags: Record<string, string | boolean>,
): Promise<void> {
  if (!subcommand || subcommand === "help" || flags.help === true) {
    printConnectAccountHelp();
    return;
  }
  if (subcommand !== "proton") {
    throw new Error(`Unknown connect-account provider '${subcommand}'. Run 'openmates connect-account --help'.`);
  }
  if (!client.hasSession()) {
    throw new Error("Not logged in. Run `openmates login` before connecting Proton Mail.");
  }
  const result = await runProtonBridgeConnector(
    client,
    { write: flags.write === true, flags },
    {
      confirmWriteMode: async () => {
        console.log(buildProtonWriteWarning());
        const answer = await promptPlainText("Type ENABLE WRITE to continue: ");
        return answer.trim() === "ENABLE WRITE";
      },
    },
  );
  if (flags.json === true) {
    printJson({
      connected_account_id: result.connectedAccountId,
      connector_session_id: result.connectorSessionId,
      capabilities: result.capabilities,
    });
    return;
  }
  console.log("Proton Mail connector is online.");
  console.log(`Connected account: ${result.connectedAccountId}`);
}

async function promptPlainText(question: string): Promise<string> {
  const rl = createInterface({ input: stdin, output: stdout });
  try {
    return await rl.question(question);
  } finally {
    rl.close();
  }
}

async function writeSecretFile(filePath: string, content: string, force = false): Promise<string> {
  const { mkdir, writeFile, stat } = await import("node:fs/promises");
  const { dirname } = await import("node:path");
  try {
    await stat(filePath);
    if (!force) throw new Error(`${filePath} already exists. Use --force to overwrite.`);
  } catch (error) {
    if (error instanceof Error && "code" in error && (error as NodeJS.ErrnoException).code !== "ENOENT") {
      throw error;
    }
    if (error instanceof Error && !("code" in error)) throw error;
  }
  await mkdir(dirname(filePath), { recursive: true });
  await writeFile(filePath, content, { mode: 0o600 });
  return filePath;
}

async function generateProvisioningPassword(): Promise<string> {
  const { randomBytes } = await import("node:crypto");
  return `OM-${randomBytes(18).toString("base64url")}-aA2#`;
}

function decodeBase32(input: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const cleaned = input.toUpperCase().replace(/[^A-Z2-7]/g, "");
  let bits = "";
  for (const char of cleaned) {
    const value = alphabet.indexOf(char);
    if (value >= 0) bits += value.toString(2).padStart(5, "0");
  }
  const bytes: number[] = [];
  for (let index = 0; index + 8 <= bits.length; index += 8) {
    bytes.push(Number.parseInt(bits.slice(index, index + 8), 2));
  }
  return Buffer.from(bytes);
}

async function generateTotpCode(secret: string): Promise<string> {
  const { createHmac } = await import("node:crypto");
  const counter = Math.floor(Date.now() / 1000 / 30);
  const counterBuffer = Buffer.alloc(8);
  counterBuffer.writeBigUInt64BE(BigInt(counter));
  const hmac = createHmac("sha1", decodeBase32(secret)).update(counterBuffer).digest();
  const offset = hmac[hmac.length - 1] & 0x0f;
  const code = (hmac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return String(code).padStart(6, "0");
}

async function runSecuritySetup(client: OpenMatesClient, flags: Record<string, string | boolean>, options: { autoGenerateTotp?: boolean } = {}): Promise<{
  otpSecret?: string | null;
  backupCodes?: string[];
  recoveryKey?: string;
  backupCodesPath?: string;
  recoveryKeyPath?: string;
}> {
  const result: {
    otpSecret?: string | null;
    backupCodes?: string[];
    recoveryKey?: string;
    backupCodesPath?: string;
    recoveryKeyPath?: string;
  } = {};

  if (flags["skip-2fa"] === true) {
    if (flags.yes !== true) await confirmOrExit("Skip 2FA setup? This weakens account protection. [y/N] ");
  } else {
    const setup = await client.startTotpSetup();
    result.otpSecret = setup.secret ?? null;
    if (setup.otpauth_url) client.renderTotpQrCode(setup.otpauth_url);
    if (setup.secret) console.log(`Manual TOTP secret: ${setup.secret}`);
    const code = typeof process.env.OPENMATES_CLI_SIGNUP_TOTP_CODE === "string"
      ? process.env.OPENMATES_CLI_SIGNUP_TOTP_CODE
      : options.autoGenerateTotp && setup.secret
        ? await generateTotpCode(setup.secret)
        : await promptLine("Enter current 2FA code: ");
    await client.verifyTotpSetup(code);
    const provider = typeof flags.provider === "string" ? flags.provider : "Authenticator app";
    await client.setTotpProvider(provider);
    const backup = await client.requestBackupCodes();
    result.backupCodes = backup.backup_codes;
    const backupOutput = typeof flags["backup-codes-output"] === "string" ? flags["backup-codes-output"] : undefined;
    if (backupOutput) {
      result.backupCodesPath = await writeSecretFile(backupOutput, `${backup.backup_codes.join("\n")}\n`, flags.force === true);
      await client.confirmBackupCodesStored();
    } else if (flags.yes === true) {
      await client.confirmBackupCodesStored();
    } else {
      console.log("Backup codes:");
      for (const backupCode of backup.backup_codes) console.log(`  ${backupCode}`);
      await confirmOrExit("I stored these backup codes safely. Continue? [y/N] ");
      await client.confirmBackupCodesStored();
    }
  }

  if (flags["skip-recovery-key"] === true) {
    if (flags.yes !== true) await confirmOrExit("Skip recovery-key setup? You may lose access to encrypted data. [y/N] ");
  } else {
    const recovery = await client.createAndConfirmRecoveryKey();
    result.recoveryKey = recovery.recoveryKey;
    const recoveryOutput = typeof flags["recovery-key-output"] === "string" ? flags["recovery-key-output"] : undefined;
    if (recoveryOutput) {
      result.recoveryKeyPath = await writeSecretFile(recoveryOutput, `${recovery.recoveryKey}\n`, flags.force === true);
    } else {
      console.log(`Recovery key: ${recovery.recoveryKey}`);
      if (flags.yes !== true) await confirmOrExit("I stored this recovery key safely. Continue? [y/N] ");
    }
  }

  return result;
}

type SignupCommandResult = {
  user: unknown;
  backupCodesPath?: string;
  recoveryKeyPath?: string;
  security: Awaited<ReturnType<typeof runSecuritySetup>>;
  giftCard: unknown;
};

async function handleSignup(client: OpenMatesClient, flags: Record<string, string | boolean>, options: { autoGenerateTotp?: boolean } = {}): Promise<SignupCommandResult> {
  if (flags.password !== undefined) {
    throw new Error("Passwords must be entered through hidden prompts, not command-line flags.");
  }
  const email = typeof flags.email === "string" ? flags.email : await promptLine("Email: ");
  const username = typeof flags.username === "string" ? flags.username : await promptLine("Username: ");
  const inviteCode = typeof flags["invite-code"] === "string" ? flags["invite-code"] : "";
  const language = typeof flags.language === "string" ? flags.language : "en";
  const password = process.env.OPENMATES_CLI_SIGNUP_PASSWORD ?? await promptSecret("Password: ");
  if (!process.env.OPENMATES_CLI_SIGNUP_PASSWORD) {
    const confirmPassword = await promptSecret("Confirm password: ");
    if (password !== confirmPassword) throw new Error("Passwords do not match.");
  }

  await client.requestSignupEmailCode({ email, inviteCode, language });
  const emailCode = process.env.OPENMATES_CLI_SIGNUP_EMAIL_CODE ?? await promptLine("Email verification code: ");
  await client.verifySignupEmailCode({ email, username, inviteCode, code: emailCode, language });
  const signup = await client.setupPasswordAccount({ email, username, password, inviteCode, language });
  const security = await runSecuritySetup(client, flags, options);

  let giftCardResult: unknown = null;
  if (typeof flags["gift-card-code"] === "string") {
    giftCardResult = await client.redeemGiftCard(flags["gift-card-code"]);
  }

  const response = {
    success: true,
    user: signup.user ?? null,
    backup_codes_path: security.backupCodesPath ?? null,
    recovery_key_path: security.recoveryKeyPath ?? null,
    gift_card: giftCardResult,
  };
  if (flags.json === true) {
    printJson(response);
  } else {
    console.log("\x1b[32m✓\x1b[0m Account created and CLI session saved.");
    if (security.backupCodesPath) console.log(`Backup codes saved to ${security.backupCodesPath}`);
    if (security.recoveryKeyPath) console.log(`Recovery key saved to ${security.recoveryKeyPath}`);
    console.log("Buy credits or redeem a gift card:");
    console.log("  openmates settings billing buy-credits bank-transfer --credits 110000");
    console.log("  openmates settings billing gift-card redeem <CODE>");
  }

  return {
    user: signup.user ?? null,
    backupCodesPath: security.backupCodesPath,
    recoveryKeyPath: security.recoveryKeyPath,
    security,
    giftCard: giftCardResult,
  };
}

async function handleE2E(
  client: OpenMatesClient,
  subcommand: string | undefined,
  rest: string[],
  flags: Record<string, string | boolean>,
): Promise<void> {
  if (subcommand !== "provision-auth-accounts") {
    printE2EHelp();
    return;
  }
  if (client.apiUrl.includes("api.openmates.org") && !client.apiUrl.includes("api.dev.openmates.org")) {
    throw new Error("E2E provisioning refuses production API URLs.");
  }
  if (flags.password !== undefined) throw new Error("Use generated passwords or OPENMATES_CLI_SIGNUP_PASSWORD, not --password.");
  const inviteCode = process.env.OPENMATES_CLI_SIGNUP_INVITE_CODE;
  if (!inviteCode) throw new Error("OPENMATES_CLI_SIGNUP_INVITE_CODE is required for E2E provisioning.");
  const slot = parseRequiredNumber(flags.slot, "--slot");
  if (![14, 15, 16, 17, 18, 19, 20].includes(slot)) {
    throw new Error("Only reserved slots 14-20 are supported.");
  }
  const artifact = typeof flags.artifact === "string" ? flags.artifact : `test-results/credential-updates/slot-${slot}.env`;
  const domain = typeof flags.domain === "string" ? flags.domain : process.env.OPENMATES_CLI_E2E_EMAIL_DOMAIN;
  const email = typeof flags.email === "string"
    ? flags.email
    : domain
      ? `cli-e2e-slot-${slot}-${Date.now()}@${domain}`
      : await promptLine("E2E account email: ");
  const username = typeof flags.username === "string" ? flags.username : `cli_e2e_slot_${slot}_${Date.now()}`;
  const generatedPassword = process.env.OPENMATES_CLI_SIGNUP_PASSWORD ?? await generateProvisioningPassword();
  const originalSignupPassword = process.env.OPENMATES_CLI_SIGNUP_PASSWORD;
  process.env.OPENMATES_CLI_SIGNUP_PASSWORD = generatedPassword;
  let signup: SignupCommandResult | null = null;
  try {
    signup = await handleSignup(client, {
      ...flags,
      email,
      username,
      "invite-code": inviteCode,
      yes: true,
      json: false,
      "backup-codes-output": typeof flags["backup-codes-output"] === "string" ? flags["backup-codes-output"] : `${artifact}.backup-codes`,
      "recovery-key-output": typeof flags["recovery-key-output"] === "string" ? flags["recovery-key-output"] : `${artifact}.recovery-key`,
    }, { autoGenerateTotp: true });
  } finally {
    if (originalSignupPassword === undefined) delete process.env.OPENMATES_CLI_SIGNUP_PASSWORD;
    else process.env.OPENMATES_CLI_SIGNUP_PASSWORD = originalSignupPassword;
  }
  if (!signup.security.otpSecret) throw new Error("Provisioning did not create a TOTP secret.");
  const artifactBody = [
    `OPENMATES_TEST_ACCOUNT_${slot}_EMAIL=${email}`,
    `OPENMATES_TEST_ACCOUNT_${slot}_PASSWORD=${generatedPassword}`,
    `OPENMATES_TEST_ACCOUNT_${slot}_OTP_KEY=${signup.security.otpSecret}`,
    `# Backup codes: ${artifact}.backup-codes`,
    `# Recovery key: ${artifact}.recovery-key`,
    "",
  ].join("\n");
  const path = await writeSecretFile(artifact, artifactBody, flags.force === true);
  if (flags.json === true) printJson({ success: true, artifact: path, slot, email });
  else console.log(`Provisioning artifact written to ${path}. Upload secrets through the trusted manual process.`);
}

function printBankTransferOrder(order: BankTransferOrderDetails, giftCard: boolean): void {
  header(giftCard ? "Gift Card Bank Transfer" : "Bank Transfer");
  console.log(`Order ID: ${order.order_id}`);
  console.log(`Credits: ${order.credits_amount}`);
  console.log(`Amount: EUR ${order.amount_eur}`);
  console.log(`Reference: ${order.reference}`);
  console.log(`IBAN: ${order.iban}`);
  console.log(`BIC: ${order.bic}`);
  console.log(`Bank: ${order.bank_name}`);
  console.log(`Account holder: ${order.account_holder_name}`);
  if (order.account_holder_address_line1) console.log(`Address: ${order.account_holder_address_line1}`);
  if (order.account_holder_address_line2) console.log(`         ${order.account_holder_address_line2}`);
  if (order.account_holder_postal_code || order.account_holder_city) {
    console.log(`         ${[order.account_holder_postal_code, order.account_holder_city].filter(Boolean).join(" ")}`);
  }
  if (order.account_holder_country) console.log(`         ${order.account_holder_country}`);
  console.log(`Expires: ${order.expires_at}`);
  console.log("\nInclude the exact reference in your bank transfer. Missing or changed references require manual review.");
  if (giftCard) {
    console.log(`Gift-card code appears after payment is matched: openmates settings billing gift-card purchase-status ${order.order_id}`);
  } else {
    console.log(`Check status: openmates settings billing bank-transfer status ${order.order_id}`);
  }
}

function printBankTransferStatus(status: BankTransferStatus | GiftCardBankTransferStatus, giftCard: boolean): void {
  header(giftCard ? "Gift Card Purchase Status" : "Bank Transfer Status");
  console.log(`Order ID: ${status.order_id}`);
  console.log(`Status: ${status.status}`);
  console.log(`Credits: ${status.credits_amount}`);
  console.log(`Amount: EUR ${status.amount_eur}`);
  console.log(`Reference: ${status.reference}`);
  console.log(`Expires: ${status.expires_at}`);
  if (giftCard) {
    const code = (status as GiftCardBankTransferStatus).gift_card_code;
    console.log(`Gift-card code: ${code || "available after payment is matched"}`);
  }
}

function printSettingsInfoCommand(
  client: OpenMatesClient,
  command: SettingsInfoCommand,
  json: boolean,
): void {
  const appUrl = deriveAppUrl(client.apiUrl);
  const webUrl = command.webPath ? `${appUrl}/#settings/${command.webPath}` : null;
  if (json) {
    printJson({
      command: `openmates settings ${command.path.join(" ")}`,
      supported_in_cli: false,
      description: command.description,
      reason: command.reason ?? null,
      web_url: webUrl,
      examples: command.examples,
    });
    return;
  }
  header(command.description);
  if (command.reason) console.log(command.reason);
  if (webUrl) console.log(`\nOpen in web app:\n  ${webUrl}`);
  if (command.examples.length > 0) {
    console.log("\nExamples:");
    for (const example of command.examples) console.log(`  ${example}`);
  }
}

async function handleSettings(
  client: OpenMatesClient,
  subcommand: string | undefined,
  rest: string[],
  flags: Record<string, string | boolean>,
): Promise<void> {
  if (!subcommand || subcommand === "help") {
    printSettingsHelp(client, subcommand ? [] : undefined);
    return;
  }

  const tokens = [subcommand, ...rest].filter((token) => token !== "help");
  const apiKey = resolveApiKey(flags) ?? undefined;
  if (rest.includes("help") || Boolean(flags.help)) {
    printSettingsHelp(client, tokens);
    return;
  }

  if (["get", "post", "patch", "delete"].includes(subcommand)) {
    console.error(
      "Raw settings passthrough is no longer supported. Use a predefined settings command.\n",
    );
    printSettingsHelp(client);
    process.exit(1);
  }

  if (matches(tokens, ["account", "info"])) {
    const user = await client.whoAmI();
    if (flags.json === true) {
      printJson(user);
    } else {
      printWhoAmI(user as Record<string, unknown>);
    }
    return;
  }

  if (matches(tokens, ["account", "timezone", "set"])) {
    const timezone = rest[2];
    if (!timezone) throw new Error("Missing timezone. Example: openmates settings account timezone set Europe/Berlin");
    await printSettingsMutationResult(
      client.settingsPost("user/timezone", { timezone }),
      flags,
    );
    return;
  }

  if (matches(tokens, ["account", "interests", "list"])) {
    const preferences = await client.getTopicPreferences();
    printTopicPreferences(preferences, flags);
    return;
  }

  if (matches(tokens, ["account", "interests", "set"])) {
    const selectedTagIds = rest.slice(2);
    if (selectedTagIds.length === 0) {
      throw new Error(
        `Missing interest tag IDs. Use one or more of: ${INTEREST_TAG_IDS.join(", ")}`,
      );
    }
    const preferences = await client.setTopicPreferences(selectedTagIds);
    printTopicPreferences(preferences, flags, "Interests updated");
    return;
  }

  if (matches(tokens, ["account", "interests", "clear"])) {
    if (flags.yes !== true) {
      await confirmOrExit("Clear account interests? [y/N] ");
    }
    const preferences = await client.clearTopicPreferences();
    printTopicPreferences(preferences, flags, "Interests cleared");
    return;
  }

  if (matches(tokens, ["account", "export", "manifest"])) {
    await printSettingsResult(client.settingsGet("export-account-manifest"), flags);
    return;
  }

  if (matches(tokens, ["account", "export", "data"])) {
    await printSettingsResult(client.settingsGet("export-account-data"), flags);
    return;
  }

  if (matches(tokens, ["account", "import-chat"])) {
    const file = rest[1];
    if (!file) throw new Error("Missing import file. Example: openmates settings account import-chat ./chat.yml");
    const { readFile } = await import("node:fs/promises");
    const content = await readFile(file, "utf-8");
    await printSettingsMutationResult(
      client.settingsPost("import-chat", parseChatImportPayload(content)),
      flags,
    );
    return;
  }

  if (matches(tokens, ["account", "username", "set"])) {
    const username = rest[2];
    if (!username) throw new Error("Missing username. Example: openmates settings account username set alice_123");
    await printSettingsMutationResult(client.updateUsername(username), flags);
    return;
  }

  if (matches(tokens, ["account", "profile-picture", "set"])) {
    const file = rest[2];
    if (!file) throw new Error("Missing image file. Example: openmates settings account profile-picture set ./avatar.jpg");
    await printSettingsMutationResult(client.updateProfileImage(file), flags);
    return;
  }

  if (matches(tokens, ["account", "chats", "stats"])) {
    await printSettingsResult(client.settingsGet("chats"), flags);
    return;
  }

  if (matches(tokens, ["account", "delete", "preview"])) {
    await printSettingsResult(client.settingsGet("delete-account-preview"), flags);
    return;
  }

  if (matches(tokens, ["account", "delete"])) {
    if (flags["email-code"] !== undefined || flags["totp-code"] !== undefined) {
      throw new Error("Deletion verification codes must be entered through interactive prompts, not command-line flags.");
    }
    const preview = await client.settingsGet("delete-account-preview");
    if (flags.json !== true) {
      header("Delete Account Preview");
      printGenericObject(preview);
    }
    if (flags.yes !== true) {
      await confirmOrExit("Delete this account and all associated data? [y/N] ");
    }
    await client.requestDeleteAccountEmailCode();
    const emailCode = await promptLine("Enter email verification code: ");
    await client.verifyDeleteAccountEmailCode(emailCode);
    const authMethods = await client.getAuthMethodsStatus();
    const totpCode = authMethods.has_2fa
      ? await promptLine("Enter 2FA code: ")
      : undefined;
    const result = await client.deleteAccountWithCliVerification(totpCode);
    if (flags.json === true) printJson(result);
    else console.log("\x1b[32m✓\x1b[0m Account deletion requested and local CLI session cleared");
    return;
  }

  if (matches(tokens, ["account", "storage", "overview"])) {
    await printSettingsResult(client.settingsGet("storage"), flags);
    return;
  }

  if (matches(tokens, ["account", "storage", "files"])) {
    const params = new URLSearchParams();
    addQueryParam(params, "category", flags.category ?? flags.type);
    const query = params.toString();
    await printSettingsResult(client.settingsGet(`storage/files${query ? `?${query}` : ""}`), flags);
    return;
  }

  if (matches(tokens, ["account", "storage", "delete"])) {
    const fileId = rest[3];
    const category = typeof flags.category === "string" ? flags.category : undefined;
    const scope = flags.all === true ? "all" : category ? "category" : "single";
    if (scope === "single" && !fileId) throw new Error("Missing file ID.");
    if (flags.yes !== true) await confirmOrExit(`Delete stored file data (${scope})? This cannot be undone. [y/N] `);
    await printSettingsMutationResult(
      client.settingsDelete("storage/files", { scope, file_id: fileId, category }),
      flags,
    );
    return;
  }

  if (matches(tokens, ["interface", "language", "set"])) {
    const language = rest[2];
    if (!language) throw new Error("Missing language code. Example: openmates settings interface language set en");
    await printSettingsMutationResult(client.settingsPost("user/language", { language }), flags);
    return;
  }

  if (matches(tokens, ["interface", "dark-mode", "set"])) {
    const value = parseOnOff(rest[2], "dark mode");
    await printSettingsMutationResult(client.settingsPost("user/darkmode", { dark_mode: value }), flags);
    return;
  }

  if (matches(tokens, ["interface", "font", "set"])) {
    const font = rest[2];
    if (!font) throw new Error("Missing font. Example: openmates settings interface font set lexend");
    await printSettingsMutationResult(client.settingsPost("user/ui-font", { ui_font: font }), flags);
    return;
  }

  if (matches(tokens, ["ai", "models", "set-defaults"])) {
    const body: Record<string, string | null> = {};
    if (flags.simple !== undefined) {
      body.default_ai_model_simple = parseModelDefaultFlag(flags.simple, "--simple");
    }
    if (flags.complex !== undefined) {
      body.default_ai_model_complex = parseModelDefaultFlag(flags.complex, "--complex");
    }
    if (Object.keys(body).length === 0) {
      throw new Error("Provide --simple <model-id|auto> and/or --complex <model-id|auto>.");
    }
    await printSettingsMutationResult(client.settingsPost("ai-model-defaults", body, apiKey), flags);
    return;
  }

  if (matches(tokens, ["privacy", "auto-delete", "chats", "set"])) {
    const period = rest[3];
    if (!period) throw new Error("Missing period. Example: openmates settings privacy auto-delete chats set 90d");
    await printSettingsMutationResult(client.settingsPost("auto-delete-chats", { period }), flags);
    return;
  }

  if (matches(tokens, ["privacy", "debug-logs", "share"])) {
    if (flags.yes !== true && flags.confirm !== true) {
      await confirmOrExit("Share debug logs with OpenMates support? [y/N] ");
    }
    const duration = typeof flags.duration === "string" ? flags.duration : "1h";
    await printSettingsMutationResult(client.settingsPost("debug-session", { duration }), flags);
    return;
  }

  if (matches(tokens, ["billing", "overview"])) {
    await printSettingsResult(client.settingsGet("billing"), flags);
    return;
  }

  if (matches(tokens, ["billing", "usage", "summaries"])) {
    await printSettingsResult(client.settingsGet("usage/summaries"), flags);
    return;
  }

  if (matches(tokens, ["billing", "usage", "daily"])) {
    await printSettingsResult(client.settingsGet("usage/daily-overview"), flags);
    return;
  }

  if (matches(tokens, ["billing", "usage", "export"])) {
    await printSettingsResult(client.settingsGet("usage/export"), flags);
    return;
  }

  if (matches(tokens, ["billing", "usage"])) {
    await printSettingsResult(client.settingsGet("usage"), flags);
    return;
  }

  if (matches(tokens, ["billing", "buy-credits", "bank-transfer"])) {
    const credits = parseRequiredNumber(flags.credits, "--credits");
    const order = await client.createBankTransferOrder(credits);
    if (flags.json === true) {
      printJson(order);
    } else {
      printBankTransferOrder(order, false);
    }
    return;
  }

  if (matches(tokens, ["billing", "bank-transfer", "status"])) {
    const orderId = rest[2];
    if (!orderId) throw new Error("Missing order ID.");
    const status = await client.getBankTransferStatus(orderId);
    if (flags.json === true) {
      printJson(status);
    } else {
      printBankTransferStatus(status, false);
    }
    return;
  }

  if (matches(tokens, ["billing", "bank-transfer", "list"])) {
    await printSettingsResult(client.listBankTransferOrders(), flags);
    return;
  }

  if (matches(tokens, ["billing", "invoices", "list"])) {
    await printSettingsResult(client.listInvoices(), flags);
    return;
  }

  if (matches(tokens, ["billing", "invoices", "download"])) {
    const invoiceId = rest[2];
    if (!invoiceId) throw new Error("Missing invoice ID.");
    const document = await client.downloadInvoice(invoiceId);
    const filePath = await saveDownloadedDocument(document, flags.output);
    if (flags.json === true) printJson({ path: filePath, filename: document.filename });
    else console.log(`\x1b[32m✓\x1b[0m Invoice saved to ${filePath}`);
    return;
  }

  if (matches(tokens, ["billing", "invoices", "credit-note"])) {
    const invoiceId = rest[2];
    if (!invoiceId) throw new Error("Missing invoice ID.");
    const document = await client.downloadCreditNote(invoiceId);
    const filePath = await saveDownloadedDocument(document, flags.output);
    if (flags.json === true) printJson({ path: filePath, filename: document.filename });
    else console.log(`\x1b[32m✓\x1b[0m Credit note saved to ${filePath}`);
    return;
  }

  if (matches(tokens, ["billing", "invoices", "refund"])) {
    const invoiceId = rest[2];
    if (!invoiceId) throw new Error("Missing invoice ID.");
    if (flags.yes !== true) await confirmOrExit(`Request refund for invoice ${invoiceId}? [y/N] `);
    await printSettingsMutationResult(client.requestRefund(invoiceId), flags);
    return;
  }

  if (matches(tokens, ["billing", "gift-card", "redeem"]) || (subcommand === "gift-card" && rest[0] === "redeem")) {
    const code = matches(tokens, ["billing", "gift-card", "redeem"]) ? rest[2] : rest[1];
    if (!code) throw new Error("Missing gift card code.");
    const result = await client.redeemGiftCard(code);
    if (flags.json === true) {
      printJson(result);
    } else if (result.success) {
      process.stdout.write(`\x1b[32m✓\x1b[0m Gift card redeemed! +${result.credits_added} credits\n`);
      process.stdout.write(`  Balance: ${result.current_credits} credits\n`);
    } else {
      process.stdout.write(`\x1b[31m✗\x1b[0m ${result.message}\n`);
    }
    return;
  }

  if (matches(tokens, ["billing", "gift-card", "list"]) || (subcommand === "gift-card" && rest[0] === "list")) {
    await printSettingsResult(client.listRedeemedGiftCards(), flags);
    return;
  }

  if (matches(tokens, ["billing", "gift-card", "buy", "bank-transfer"])) {
    const credits = parseRequiredNumber(flags.credits, "--credits");
    const order = await client.createGiftCardBankTransferOrder(credits);
    if (flags.json === true) {
      printJson(order);
    } else {
      printBankTransferOrder(order, true);
    }
    return;
  }

  if (matches(tokens, ["billing", "gift-card", "purchase-status"])) {
    const orderId = rest[3];
    if (!orderId) throw new Error("Missing order ID.");
    const status = await client.getGiftCardPurchaseStatus(orderId);
    if (flags.json === true) {
      printJson(status);
    } else {
      printBankTransferStatus(status, true);
    }
    return;
  }

  if (matches(tokens, ["billing", "gift-card", "purchased"])) {
    await printSettingsResult(client.listPurchasedGiftCards(), flags);
    return;
  }

  if (matches(tokens, ["billing", "auto-topup", "low-balance", "set"])) {
    const enabled = parseOnOff(String(flags.enabled ?? ""), "low-balance auto top-up");
    const amount = parseRequiredNumber(flags.amount, "--amount");
    const currency = typeof flags.currency === "string" ? flags.currency : "eur";
    const email = typeof flags.email === "string" ? flags.email : undefined;
    if (enabled && !email) throw new Error("Provide --email when enabling low-balance auto top-up.");
    await printSettingsMutationResult(
      client.settingsPost("auto-topup/low-balance", { enabled, threshold: 100, amount, currency, email }),
      flags,
    );
    return;
  }

  if (matches(tokens, ["notifications", "status"])) {
    const user = await client.whoAmI() as Record<string, unknown>;
    const status = {
      enabled: user.email_notifications_enabled ?? false,
      preferences: user.email_notification_preferences ?? {},
      backup_reminder_interval_days: user.backup_reminder_interval_days ?? null,
      encrypted_notification_email_configured: Boolean(user.encrypted_notification_email),
    };
    if (flags.json === true) {
      printJson(status);
    } else {
      printGenericObject(status);
    }
    return;
  }

  if (matches(tokens, ["notifications", "list"])) {
    const limit = parseOptionalNumber(flags.limit, 50, "--limit");
    await printSettingsResult(client.listNotifications(limit), flags);
    return;
  }

  if (matches(tokens, ["notifications", "stream"])) {
    const count = flags.count === undefined ? null : parseRequiredNumber(flags.count, "--count");
    let received = 0;
    for await (const event of client.streamNotifications()) {
      if (flags.json === true) {
        printJson(event);
      } else {
        printGenericObject(event);
      }
      received += 1;
      if (count !== null && received >= count) break;
    }
    return;
  }

  if (matches(tokens, ["notifications", "email", "set"])) {
    const enabled = parseOnOff(String(flags.enabled ?? ""), "email notifications");
    const email = typeof flags.email === "string" ? flags.email : null;
    if (enabled && !email) throw new Error("Provide --email when enabling email notifications.");
    const preferences = {
      aiResponses: parseOptionalBoolean(flags["ai-responses"], true, "AI response notifications"),
      backupReminder: parseOptionalBoolean(flags["backup-reminder"], false, "backup reminder notifications"),
      webhookChats: parseOptionalBoolean(flags["webhook-chats"], false, "webhook chat notifications"),
    };
    await printSettingsMutationResult(
      client.updateEmailNotificationSettings({ enabled, email, preferences }),
      flags,
    );
    return;
  }

  if (matches(tokens, ["notifications", "backup", "set"])) {
    const enabled = parseOnOff(String(flags.enabled ?? ""), "backup reminders");
    const email = typeof flags.email === "string" ? flags.email : null;
    const interval = parseRequiredNumber(flags.interval, "--interval");
    if (enabled && !email) throw new Error("Provide --email when enabling backup reminders.");
    await printSettingsMutationResult(
      client.updateEmailNotificationSettings({
        enabled,
        email,
        preferences: { aiResponses: false, backupReminder: enabled },
        backup_reminder_interval_days: interval,
      }),
      flags,
    );
    return;
  }

  if (matches(tokens, ["reminders", "list"])) {
    await printSettingsResult(client.settingsGet("reminders"), flags);
    return;
  }

  if (matches(tokens, ["reminders", "update"])) {
    const id = rest[1];
    if (!id) throw new Error("Missing reminder ID.");
    const body = parseDataOrFlags(flags, ["enabled"]);
    await printSettingsMutationResult(client.settingsPatch(`reminders/${id}`, body), flags);
    return;
  }

  if (matches(tokens, ["reminders", "delete"])) {
    const id = rest[1];
    if (!id) throw new Error("Missing reminder ID.");
    if (flags.yes !== true) await confirmOrExit(`Delete reminder ${id}? [y/N] `);
    await printSettingsMutationResult(client.settingsDelete(`reminders/${id}`), flags);
    return;
  }

  if (matches(tokens, ["developers", "api-keys", "list"])) {
    const result = await client.listApiKeys();
    printApiKeyList(result, flags);
    return;
  }

  if (matches(tokens, ["developers", "api-keys", "create"])) {
    const name = rest[2] ?? (typeof flags.name === "string" ? flags.name : "CLI API key");
    if (flags.yes !== true) {
      await confirmOrExit(
        "Create a full-access API key with unlimited credits and no expiration? The key is shown once. [y/N] ",
      );
    }
    const result = await client.createApiKey({ name });
    if (flags.json === true) {
      printJson(result);
    } else {
      console.log("\x1b[33m!\x1b[0m Full access enabled");
      console.log("\x1b[33m!\x1b[0m Credit limit: unlimited");
      console.log("\x1b[33m!\x1b[0m Expiration: never");
      console.log("\nAPI key (shown once):");
      console.log(result.api_key);
      console.log("\nStore this securely. OpenMates cannot show it again.");
    }
    return;
  }

  if (matches(tokens, ["developers", "api-keys", "revoke"])) {
    const id = rest[2];
    if (!id) throw new Error("Missing API key ID.");
    if (flags.yes !== true) await confirmOrExit(`Revoke API key ${id}? [y/N] `);
    await printSettingsMutationResult(client.revokeApiKey(id), flags);
    return;
  }

  if (matches(tokens, ["report-issue", "create"])) {
    const title = typeof flags.title === "string" ? flags.title : undefined;
    const body = typeof flags.body === "string" ? flags.body : undefined;
    if (!title || !body) throw new Error("Provide --title and --body.");
    const result = await client.settingsPost("issues", { title, description: body });
    printReportIssueCreateResult(result, flags);
    return;
  }

  if (matches(tokens, ["report-issue", "status"])) {
    const id = rest[1];
    if (!id) throw new Error("Missing issue ID.");
    await printSettingsResult(client.settingsGet(`issues/${id}/status`), flags);
    return;
  }

  if (matches(tokens, ["mates", "list"])) {
    printMates(flags.json === true);
    return;
  }

  if (matches(tokens, ["mates", "info"])) {
    const mateId = rest[1];
    if (!mateId) throw new Error("Missing mate ID. Example: openmates settings mates info software_development");
    printMateInfo(mateId, flags.json === true);
    return;
  }

  if (matches(tokens, ["mates", "consent"])) {
    if (flags.yes !== true) await confirmOrExit("Record consent for mate settings? [y/N] ");
    await printSettingsMutationResult(client.settingsPost("user/consent/mates", { consent: true }), flags);
    return;
  }

  if (matches(tokens, ["newsletter", "categories"]) && tokens.length === 2) {
    await printSettingsResult(client.getNewsletterCategories(), flags);
    return;
  }

  if (matches(tokens, ["newsletter", "categories", "set"])) {
    const categories = {
      updates_and_announcements: parseOptionalBoolean(flags.updates, true, "updates newsletter"),
      tips_and_tricks: parseOptionalBoolean(flags.tips, true, "tips newsletter"),
      daily_inspirations: parseOptionalBoolean(flags.daily, true, "daily inspirations newsletter"),
    };
    await printSettingsMutationResult(client.updateNewsletterCategories(categories), flags);
    return;
  }

  if (matches(tokens, ["newsletter", "subscribe"])) {
    const email = rest[1];
    if (!email) throw new Error("Missing email. Example: openmates settings newsletter subscribe you@example.com");
    const language = typeof flags.language === "string" ? flags.language : "en";
    const darkmode = parseOptionalBoolean(flags.darkmode, false, "newsletter dark mode");
    await printSettingsMutationResult(client.subscribeNewsletter(email, language, darkmode), flags);
    return;
  }

  if (matches(tokens, ["newsletter", "confirm"])) {
    const token = rest[1];
    if (!token) throw new Error("Missing confirmation token.");
    await printSettingsMutationResult(client.confirmNewsletter(token), flags);
    return;
  }

  if (matches(tokens, ["newsletter", "unsubscribe"])) {
    const token = rest[1];
    if (!token) throw new Error("Missing unsubscribe token.");
    await printSettingsMutationResult(client.unsubscribeNewsletter(token), flags);
    return;
  }

  if (subcommand === "memories") {
    await handleMemories(client, rest, flags);
    return;
  }

  const webOnly = findSettingsInfoCommand(tokens);
  if (webOnly) {
    printSettingsInfoCommand(client, webOnly, flags.json === true);
    return;
  }

  console.error(`Unknown settings command '${tokens.join(" ")}'.\n`);
  printSettingsHelp(client, [subcommand]);
  process.exit(1);
}

const LEARNING_MODE_AGE_GROUPS = new Set<LearningModeAgeGroup>([
  "under_10",
  "10_12",
  "13_15",
  "16_18",
  "adult",
]);

async function handleLearningMode(
  client: OpenMatesClient,
  subcommand: string | undefined,
  flags: Record<string, string | boolean>,
): Promise<void> {
  if (!subcommand || subcommand === "help" || flags.help === true) {
    printLearningModeHelp();
    return;
  }

  if (subcommand === "status") {
    printLearningModeStatus(await client.getLearningModeStatus(), flags.json === true);
    return;
  }

  if (subcommand === "enable") {
    const ageGroup = parseLearningModeAgeGroup(flags["age-group"]);
    const passcode = parseRequiredStringFlag(flags.passcode, "--passcode");
    printLearningModeStatus(
      await client.activateLearningMode({ ageGroup, passcode }),
      flags.json === true,
    );
    return;
  }

  if (subcommand === "disable") {
    const passcode = parseRequiredStringFlag(flags.passcode, "--passcode");
    printLearningModeStatus(await client.deactivateLearningMode(passcode), flags.json === true);
    return;
  }

  console.error(`Unknown learning-mode command '${subcommand}'.\n`);
  printLearningModeHelp();
  process.exit(1);
}

function parseLearningModeAgeGroup(value: string | boolean | undefined): LearningModeAgeGroup {
  if (typeof value !== "string" || !LEARNING_MODE_AGE_GROUPS.has(value as LearningModeAgeGroup)) {
    throw new Error("Provide --age-group as one of: under_10, 10_12, 13_15, 16_18, adult.");
  }
  return value as LearningModeAgeGroup;
}

function parseAnonymousLearningModeFlags(flags: Record<string, string | boolean>): LearningModeContext | undefined {
  if (flags["learning-mode"] !== true) return undefined;
  return {
    enabled: true,
    ageGroup: parseLearningModeAgeGroup(flags["age-group"]),
    source: "anonymous_session",
  };
}

function parseRequiredStringFlag(value: string | boolean | undefined, name: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`Provide ${name}.`);
  }
  return value;
}

function printLearningModeStatus(status: LearningModeStatus, json: boolean): void {
  if (json) {
    printJson(status);
    return;
  }
  console.log(`Learning Mode: ${status.enabled ? "enabled" : "disabled"}`);
  if (status.age_group) console.log(`Age group: ${status.age_group}`);
  if (status.failed_attempts > 0) console.log(`Failed disable attempts: ${status.failed_attempts}`);
  if (status.deactivation_blocked_until) {
    console.log(`Disable blocked until: ${new Date(status.deactivation_blocked_until * 1000).toISOString()}`);
  }
}

// ---------------------------------------------------------------------------
// Memories
// ---------------------------------------------------------------------------

async function handleMemories(
  client: OpenMatesClient,
  rest: string[],
  flags: Record<string, string | boolean>,
): Promise<void> {
  const action = rest[0];

  if (!action || action === "help") {
    printMemoriesHelp();
    return;
  }

  if (action === "list") {
    const appId = typeof flags["app-id"] === "string" ? flags["app-id"] : null;
    const itemType =
      typeof flags["item-type"] === "string" ? flags["item-type"] : null;
    let result = await client.listMemories();
    if (appId) result = result.filter((m) => m.app_id === appId);
    if (itemType) result = result.filter((m) => m.item_type === itemType);
    if (flags.json === true) {
      printJson(result);
    } else {
      printMemoriesList(result);
    }
    return;
  }

  if (action === "types") {
    const types = Object.entries(MEMORY_TYPE_REGISTRY).map(([key, def]) => ({
      key,
      app_id: def.appId,
      item_type: def.itemType,
      entry_type: def.entryType,
      required: def.required,
      properties: Object.keys(def.properties),
    }));
    const appFilter =
      typeof flags["app-id"] === "string" ? flags["app-id"] : null;
    const filtered = appFilter
      ? types.filter((t) => t.app_id === appFilter)
      : types;
    if (flags.json === true) {
      printJson(filtered);
    } else {
      printMemoryTypes(filtered);
    }
    return;
  }

  if (action === "create") {
    const appId = typeof flags["app-id"] === "string" ? flags["app-id"] : "";
    const itemType =
      typeof flags["item-type"] === "string" ? flags["item-type"] : "";
    const dataRaw = typeof flags.data === "string" ? flags.data : null;

    if (!appId || !itemType) {
      console.error(
        "Missing required flags.\n\n" +
          "Usage: openmates settings memories create --app-id <id> --item-type <type> --data '<json>'\n\n" +
          "Run 'openmates settings memories types' to see all available types.",
      );
      process.exit(1);
    }
    if (!dataRaw) {
      console.error(
        "Missing --data '<json>'. Provide the memory field values as a JSON object.\n\n" +
          `Example: --data '{"name":"Python","proficiency":"advanced"}'`,
      );
      process.exit(1);
    }

    const itemValue = JSON.parse(dataRaw) as Record<string, unknown>;
    const result = await client.createMemory({ appId, itemType, itemValue });
    if (flags.json === true) {
      printJson(result);
    } else {
      console.log(
        `\x1b[32m✓\x1b[0m Memory created  \x1b[2mid: ${result.id}\x1b[0m`,
      );
    }
    return;
  }

  if (action === "update") {
    const entryId = typeof flags.id === "string" ? flags.id : "";
    const appId = typeof flags["app-id"] === "string" ? flags["app-id"] : "";
    const itemType =
      typeof flags["item-type"] === "string" ? flags["item-type"] : "";
    const dataRaw = typeof flags.data === "string" ? flags.data : null;
    const currentVersion =
      typeof flags.version === "string" ? parseInt(flags.version, 10) : 1;

    if (!entryId || !appId || !itemType) {
      console.error(
        "Missing required flags.\n\n" +
          "Usage: openmates settings memories update --id <entry-id> --app-id <id> --item-type <type> --data '<json>' [--version <n>]",
      );
      process.exit(1);
    }
    if (!dataRaw) {
      console.error("Missing --data '<json>'.");
      process.exit(1);
    }

    const itemValue = JSON.parse(dataRaw) as Record<string, unknown>;
    const result = await client.updateMemory({
      entryId,
      appId,
      itemType,
      itemValue,
      currentVersion,
    });
    if (flags.json === true) {
      printJson(result);
    } else {
      console.log(
        `\x1b[32m✓\x1b[0m Memory updated  \x1b[2mid: ${result.id}\x1b[0m`,
      );
    }
    return;
  }

  if (action === "delete") {
    const entryId = typeof flags.id === "string" ? flags.id : (rest[1] ?? "");
    if (!entryId) {
      console.error(
        "Missing entry ID.\n\nUsage: openmates settings memories delete --id <entry-id>",
      );
      process.exit(1);
    }
    const result = await client.deleteMemory(entryId);
    if (flags.json === true) {
      printJson(result);
    } else {
      console.log(`\x1b[32m✓\x1b[0m Memory deleted`);
    }
    return;
  }

  console.error(
    `Unknown memories action '${action}'.\n\nUsage: openmates settings memories <list|types|create|update|delete>`,
  );
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Argument parsing
// ---------------------------------------------------------------------------

function handleFeedback(
  subcommand: string | undefined,
  _rest: string[],
  flags: Record<string, string | boolean>,
): void {
  if (!subcommand || subcommand === "help" || flags.help === true) {
    printFeedbackHelp();
    return;
  }

  if (subcommand !== "assistant-response") {
    throw new Error(`Unknown feedback command '${subcommand}'. Run 'openmates feedback --help'.`);
  }

  const rawRating = flags.rating;
  if (typeof rawRating !== "string") {
    throw new Error("Missing --rating <1-5>.");
  }

  const decision = buildAssistantFeedbackDecision(Number(rawRating));
  if (flags.json === true) {
    printJson(decision);
    return;
  }

  console.log(decision.message);
  if (decision.action === "report_issue") {
    console.log(`Report issue title: ${decision.reportTitle}`);
    console.log("Open the report issue form and include the affected assistant response.");
  }
}

function parseArgs(argv: string[]): CliArgs {
  const positionals: string[] = [];
  const flags: Record<string, string | boolean> = {};

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith("--")) {
      positionals.push(arg);
      continue;
    }
    const keyValue = arg.slice(2).split("=", 2);
    const key = keyValue[0];
    const valueFromEquals = keyValue[1];

    if (valueFromEquals !== undefined) {
      flags[key] = appendFlagValue(flags[key], valueFromEquals);
      continue;
    }

    const next = argv[i + 1];
    if (next && !next.startsWith("--")) {
      flags[key] = appendFlagValue(flags[key], next);
      i += 1;
    } else {
      flags[key] = true;
    }
  }

  return { positionals, flags };
}

function appendFlagValue(existing: string | boolean | undefined, value: string): string {
  if (typeof existing === "string" && existing.length > 0) return `${existing}\n${value}`;
  return value;
}

function resolveApiKey(flags: Record<string, string | boolean>): string | null {
  if (typeof flags["api-key"] === "string" && flags["api-key"].length > 0) {
    return flags["api-key"];
  }
  if (process.env.OPENMATES_API_KEY) return process.env.OPENMATES_API_KEY;
  return null;
}

// ---------------------------------------------------------------------------
// Output primitives
// ---------------------------------------------------------------------------

/** Raw JSON output for --json flag */
function printJson(value: unknown): void {
  console.log(JSON.stringify(value, null, 2));
}

/** Bold section header */
function header(text: string): void {
  process.stdout.write(`\x1b[1m${text}\x1b[0m\n`);
}

/** Key-value row: "  key   value" */
function kv(key: string, value: string, keyWidth = 16): void {
  const padded = key.padEnd(keyWidth);
  process.stdout.write(`  \x1b[2m${padded}\x1b[0m ${value}\n`);
}

// ---------------------------------------------------------------------------
// Chats renderers
// ---------------------------------------------------------------------------

/**
 * Category gradient colors — start color of each gradient from categoryUtils.ts
 */
const CATEGORY_ANSI_COLORS: Record<string, [number, number, number]> = {
  software_development: [21, 93, 145],
  business_development: [0, 64, 64],
  medical_health: [253, 80, 160],
  legal_law: [35, 156, 255],
  openmates_official: [99, 102, 241],
  maker_prototyping: [234, 118, 0],
  marketing_sales: [255, 140, 0],
  finance: [17, 145, 6],
  design: [16, 16, 16],
  electrical_engineering: [35, 56, 136],
  movies_tv: [0, 194, 197],
  history: [73, 137, 242],
  science: [206, 91, 6],
  life_coach_psychology: [253, 178, 80],
  cooking_food: [253, 132, 80],
  activism: [245, 61, 0],
  general_knowledge: [222, 30, 102],
  onboarding_support: [99, 100, 255],
};

const CATEGORY_LABELS: Record<string, string> = {
  software_development: "Software Dev",
  business_development: "Business",
  medical_health: "Health",
  legal_law: "Legal",
  openmates_official: "OpenMates",
  maker_prototyping: "Maker",
  marketing_sales: "Marketing",
  finance: "Finance",
  design: "Design",
  electrical_engineering: "Electrical",
  movies_tv: "Movies & TV",
  history: "History",
  science: "Science",
  life_coach_psychology: "Psychology",
  cooking_food: "Cooking",
  activism: "Activism",
  general_knowledge: "General",
  onboarding_support: "Support",
};

/**
 * Solid 2-character colored square block — no text, pure color signal.
 * Used as a category indicator in list and conversation views.
 */
function ansiColorBlock(category: string | null): string {
  if (!category || !CATEGORY_ANSI_COLORS[category]) {
    return "\x1b[2m░░\x1b[0m"; // dim placeholder for uncategorized
  }
  const [r, g, b] = CATEGORY_ANSI_COLORS[category];
  return `\x1b[48;2;${r};${g};${b}m  \x1b[0m`;
}

/**
 * Colored block with mate name as text — used in conversation per-message headers.
 */
function ansiMateBlock(
  category: string | null,
  mateName: string | null,
): string {
  const label =
    mateName ??
    (category ? (CATEGORY_LABELS[category] ?? category) : "Assistant");
  if (!category || !CATEGORY_ANSI_COLORS[category]) {
    return `\x1b[2m${label}\x1b[0m`;
  }
  const [r, g, b] = CATEGORY_ANSI_COLORS[category];
  return `\x1b[48;2;${r};${g};${b}m\x1b[97m ${label} \x1b[0m`;
}

function formatTimestamp(ts: number | null): string {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function printChatsTable(result: ChatListPage): void {
  const { chats, total, page, limit, hasMore } = result;
  const start = (page - 1) * limit + 1;
  const end = start + chats.length - 1;
  const exampleOnly = chats.every((chat) => chat.source === "example");

  if (chats.length === 0) {
    console.log("No chats found.");
    return;
  }

  const totalPages = Math.ceil(total / limit);
  process.stdout.write(
    `\x1b[2m${exampleOnly ? "Example chats" : "Chats"} ${start}–${end} of ${total}  (page ${page}/${totalPages})\x1b[0m\n\n`,
  );

  for (const chat of chats) {
    const block = ansiColorBlock(chat.category);
    const time = formatTimestamp(chat.updatedAt);
    const title = chat.title ?? "(no title)";
    const idStr = chat.shortId;
    const sourceLabel = chat.source === "example" ? "  \x1b[33mEXAMPLE CHAT\x1b[0m" : "";

    // Line 1: colored block + timestamp
    process.stdout.write(`${block}  \x1b[2m${time}\x1b[0m${sourceLabel}\n`);
    // Line 2: bold title as headline
    process.stdout.write(`\x1b[1m${title}\x1b[0m\n`);
    // Line 3: full summary (no truncation)
    if (chat.summary) {
      process.stdout.write(`\x1b[2m${chat.summary}\x1b[0m\n`);
    }
    // Line 4: show command hint
    process.stdout.write(`\x1b[2m→ openmates chats show ${idStr}\x1b[0m\n`);
    // Separator
    process.stdout.write(`\x1b[2m${"─".repeat(60)}\x1b[0m\n`);
  }

  if (hasMore) {
    const nextPage = page + 1;
    const nextCmd = `chats list --page ${nextPage}${limit !== 10 ? ` --limit ${limit}` : ""}`;
    process.stdout.write(`\n\x1b[2mNext page: openmates ${nextCmd}\x1b[0m\n`);
  }
}

/**
 * Send a message with live streaming output.
 *
 * Prints a typing indicator while waiting, streams content as it arrives
 * (diff-printing new characters), and renders inline embeds after completion.
 */
async function sendMessageStreaming(
  client: OpenMatesClient,
  params: {
    message: string;
    chatId?: string;
    incognito?: boolean;
    json?: boolean;
    autoApproveSubChats?: boolean;
    autoApproveMemories?: boolean;
    acceptTaskProposals?: boolean;
    piiDetection?: boolean;
    anonymousLearningMode?: LearningModeContext;
    responseTimeoutMs?: number;
  },
  redactor?: OutputRedactor,
): Promise<{
  status: "completed" | "waiting_for_user";
  chatId: string;
  messageId: string | null;
  assistant: string;
  category: string | null;
  modelName: string | null;
  mateName: string | null;
  followUpSuggestions: string[];
  taskEvents: TaskEventFrame[];
  pendingTaskUpdateJobs: PendingTaskUpdateJobFrame[];
  subChatEvents: SubChatEvent[];
  appSettingsMemoryRequests: Array<{
    requestId: string | null;
    requestedKeys: string[];
    approvedKeys: string[];
    entryCount: number;
  }>;
  acceptedTaskProposals: Array<Record<string, unknown>>;
} | WaitingForUserResult | SignupRequiredResult> {
  let headerPrinted = false;
  let typingShown = false;
  // Track which embed IDs we've already rendered during streaming
  const renderedEmbedIds = new Set<string>();
  // Track how much raw content we've processed (for diff-printing)
  let processedRawLength = 0;
  // Queue of embed IDs to render after streaming, with optional meta
  // from the JSON block for fallback rendering of unsynced embeds
  const pendingEmbedRenders: Array<{
    id: string;
    meta?: Record<string, unknown>;
  }> = [];

  const clearTyping = () => {
    if (typingShown) {
      process.stdout.write("\r\x1b[K");
      typingShown = false;
    }
  };

  const onStream = (event: StreamEvent) => {
    if (params.json) return;

    if (event.kind === "typing") {
      const mateName =
        event.category && MATE_NAMES[event.category]
          ? MATE_NAMES[event.category]
          : "Mate";
      process.stdout.write(`\x1b[2m${mateName} is typing...\x1b[0m`);
      typingShown = true;
      return;
    }

    if (event.kind === "chunk" || event.kind === "done") {
      clearTyping();

      if (!headerPrinted) {
        const mateBlock = ansiMateBlock(event.category, null);
        const modelSuffix = event.modelName
          ? `  \x1b[2m${event.modelName}\x1b[0m`
          : "";
        process.stdout.write(`${SEP}\n`);
        process.stdout.write(`${mateBlock}${modelSuffix}\n`);
        process.stdout.write(`${SEP}\n`);
        headerPrinted = true;
      }

      // Process new content since last chunk using segment parsing.
      // This lets us detect embed JSON blocks as they arrive and queue
      // them for rendering at their natural position in the output.
      const raw = event.content;
      if (raw.length <= processedRawLength) return;

      // Parse the FULL content each time (embed blocks may span multiple
      // chunks), then output only the new segments we haven't printed yet.
      // Each segment carries rawLength — the number of characters it
      // consumed in the original string (including ```json\n...\n```
      // delimiters for embed blocks). We track offset in raw-string
      // coordinates so that processedRawLength subtraction works correctly.
      const segments = parseMessageSegments(raw);
      let offset = 0;
      for (const seg of segments) {
        const segEnd = offset + seg.rawLength;
        if (seg.type === "embed") {
          if (!renderedEmbedIds.has(seg.value)) {
            renderedEmbedIds.add(seg.value);
            pendingEmbedRenders.push({ id: seg.value, meta: seg.meta });
          }
        } else {
          // Only print text we haven't printed yet
          const clean = seg.value.replace(/\n{3,}/g, "\n\n");
          const alreadyPrinted = Math.max(0, processedRawLength - offset);
          if (alreadyPrinted < clean.length) {
            const chunk = clean.slice(alreadyPrinted);
            // Redact personal data and secrets from streamed output
            const safeChunk = redactor?.isInitialized
              ? redactor.redact(chunk)
              : chunk;
            process.stdout.write(safeChunk);
          }
        }
        offset = segEnd;
      }
      processedRawLength = raw.length;
    }
  };

  const onSubChatEvent = (event: SubChatEvent) => {
    if (params.json) return;
    clearTyping();
    const payload = event.payload;
    if (event.type === "spawn_sub_chats") {
      const count = Array.isArray(payload.sub_chats) ? payload.sub_chats.length : 0;
      process.stderr.write(
        `\x1b[2mStarting ${count} sub-chat${count === 1 ? "" : "s"} for parallel research...\x1b[0m\n`,
      );
      return;
    }
    if (event.type === "sub_chat_progress") {
      const completed = typeof payload.completed === "number" ? payload.completed : null;
      const total = typeof payload.total === "number" ? payload.total : null;
      const status = typeof payload.status === "string" ? payload.status : "running";
      const progress = completed !== null && total !== null ? `${completed}/${total}` : status;
      process.stderr.write(`\x1b[2mSub-chats: ${progress} ${status}\x1b[0m\n`);
      return;
    }
    if (event.type === "sub_chat_confirmation_resolved") {
      const status = typeof payload.status === "string" ? payload.status : "resolved";
      process.stderr.write(`\x1b[2mSub-chat approval ${status}.\x1b[0m\n`);
      return;
    }
    if (event.type === "awaiting_user_input") {
      process.stderr.write(
        "\x1b[33mA sub-chat needs additional user input. Continue this chat in the web app if the parent cannot finish.\x1b[0m\n",
      );
    }
  };

  const onSubChatApprovalRequest = async (
    request: SubChatApprovalRequest,
  ): Promise<boolean> => {
    if (params.autoApproveSubChats) return true;
    clearTyping();
    const count = request.subChats.length;
    const remaining =
      request.remainingSubChats === null
        ? ""
        : ` (${request.remainingSubChats} remaining for this parent chat)`;
    process.stderr.write(
      `\x1b[33mDeep research wants to start ${count} additional sub-chat${count === 1 ? "" : "s"}${remaining}.\x1b[0m\n`,
    );
    const rl = createInterface({ input: process.stdin, output: process.stderr });
    try {
      const answer = await rl.question("Approve? [y/N] ");
      return answer.trim().toLowerCase() === "y" || answer.trim().toLowerCase() === "yes";
    } finally {
      rl.close();
    }
  };

  // ── Prepared embeds array (encrypted after real chat/message IDs exist) ────
  const preparedEmbeds: PreparedEmbed[] = [];

  // ── Mention resolution ─────────────────────────────────────────────
  // Parse @mentions in the message, resolve to backend wire syntax.
  // If any mentions fail to resolve, show error and abort.
  let finalMessage = params.message;
  if (params.message.includes("@")) {
    try {
      const mentionCtx = await client.buildMentionContext();
      const parsed = parseMentions(params.message, mentionCtx);
      finalMessage = parsed.processedMessage;

      // Report unresolved mentions as errors
      if (parsed.unresolved.length > 0) {
        clearTyping();
        for (const u of parsed.unresolved) {
          process.stderr.write(
            `\x1b[31mError:\x1b[0m Unknown mention ${u.original}\n`,
          );
          if (u.suggestions.length > 0) {
            process.stderr.write(
              `  Did you mean: ${u.suggestions.join(", ")}?\n`,
            );
          }
        }
        process.stderr.write(
          "\nUse \x1b[2mopenmates mentions list\x1b[0m to see all available mentions.\n",
        );
        process.exit(1);
      }

      // Process file @path references into proper encrypted embeds
      if (parsed.filePaths.length > 0) {
        if (!client.hasSession()) {
          clearTyping();
          const result: SignupRequiredResult = {
            status: "signup_required",
            reason: "file_upload_requires_signup",
            signup_required: true,
            message: "File uploads require signup. Your message text can be kept as a draft, but files must be attached after creating an account.",
          };
          if (!params.json) {
            process.stderr.write(`${result.message}\n`);
          }
          return result;
        }

        const fileResult = processFiles(parsed.filePaths, redactor ?? null);

        // Report blocked files
        for (const b of fileResult.blocked) {
          clearTyping();
          process.stderr.write(
            `\x1b[31mBlocked:\x1b[0m @${b.path} — ${b.error}\n`,
          );
        }

        // Report file errors
        for (const e of fileResult.errors) {
          clearTyping();
          process.stderr.write(
            `\x1b[31mError:\x1b[0m @${e.path} — ${e.error}\n`,
          );
        }

        // Abort if any blocked or errors
        if (fileResult.blocked.length > 0 || fileResult.errors.length > 0) {
          process.exit(1);
        }

        // Show processed files confirmation
        if (fileResult.embeds.length > 0 && !params.json) {
          clearTyping();
          for (const fe of fileResult.embeds) {
            const suffix = fe.zeroKnowledge
              ? " (zero-knowledge)"
              : fe.secretsRedacted
                ? " (secrets redacted)"
                : fe.requiresUpload
                  ? " (uploading...)"
                  : "";
            process.stderr.write(
              `\x1b[2m  \x1b[36m@${fe.displayName}\x1b[2m${suffix}\x1b[0m\n`,
            );
          }
        }

        // Upload files that require S3 upload (images, PDFs)
        for (const fe of fileResult.embeds) {
          if (fe.requiresUpload && fe.localPath) {
            try {
              const session = client.getSession();
              const uploadResult = await uploadFile(fe.localPath, session);

              const embedType = fe.embed.type;
              const audioTranscription =
                embedType === "audio-recording"
                  ? await transcribeUploadedAudio(
                      uploadResult,
                      fe.displayName,
                      session,
                      { chatId: params.chatId, requestId: uploadResult.embed_id },
                    )
                  : null;
              const embedRef = fe.embed.embedRef ?? createEmbedRef(embedType, uploadResult.embed_id);
              fe.embed.embedRef = embedRef;

              const uploadedContent =
                embedType === "audio-recording"
                  ? {
                      app_id: "audio",
                      skill_id: "transcribe",
                      type: "audio-recording",
                      status: "finished",
                      filename: fe.displayName,
                      embed_ref: embedRef,
                      mime_type: uploadResult.content_type,
                      transcript: audioTranscription?.transcript ?? null,
                      transcript_original: audioTranscription?.transcript_original ?? null,
                      transcript_corrected: audioTranscription?.transcript_corrected ?? null,
                      use_corrected: audioTranscription?.use_corrected ?? null,
                      correction_model: audioTranscription?.correction_model ?? null,
                      model: audioTranscription?.model ?? null,
                      s3_base_url: uploadResult.s3_base_url,
                      files: uploadResult.files,
                      aes_key: uploadResult.aes_key,
                      aes_nonce: uploadResult.aes_nonce,
                      vault_wrapped_aes_key: uploadResult.vault_wrapped_aes_key,
                    }
                  : embedType === "pdf"
                    ? {
                        type: "pdf",
                        status: "processing",
                        filename: fe.displayName,
                        embed_ref: embedRef,
                        page_count: uploadResult.page_count ?? null,
                        content_hash: uploadResult.content_hash,
                        s3_base_url: uploadResult.s3_base_url,
                        files: uploadResult.files,
                        aes_key: uploadResult.aes_key,
                        aes_nonce: uploadResult.aes_nonce,
                        vault_wrapped_aes_key: uploadResult.vault_wrapped_aes_key,
                      }
                    : {
                        type: "image",
                        app_id: "images",
                        skill_id: "upload",
                        status: "finished",
                        filename: fe.displayName,
                        embed_ref: embedRef,
                        content_hash: uploadResult.content_hash,
                        s3_base_url: uploadResult.s3_base_url,
                        files: uploadResult.files,
                        aes_key: uploadResult.aes_key,
                        aes_nonce: uploadResult.aes_nonce,
                        vault_wrapped_aes_key: uploadResult.vault_wrapped_aes_key,
                        ai_detection: uploadResult.ai_detection,
                      };

              // Update the embed with upload server response data.
              fe.embed.content = toonEncodeContent(uploadedContent);
              fe.embed.status = embedType === "pdf" ? "processing" : "finished";
              fe.embed.contentHash = uploadResult.content_hash;

              // Use the server-assigned embed_id
              fe.embed.embedId = uploadResult.embed_id;
              fe.referenceBlock = createEmbedReferenceBlock(embedRef);

              if (!params.json) {
                process.stderr.write(
                  `\x1b[32m  \u2713\x1b[0m \x1b[2m${fe.displayName} uploaded\x1b[0m\n`,
                );
              }
            } catch (err) {
              const msg = err instanceof Error ? err.message : String(err);
              process.stderr.write(
                `\x1b[31mUpload failed:\x1b[0m ${fe.displayName} — ${msg}\n`,
              );
              process.exit(1);
            }
          }
        }

        // Remove @path tokens from the message text
        for (const fp of parsed.filePaths) {
          finalMessage = finalMessage.replace(
            new RegExp(
              `@${fp.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&")}`,
              "g",
            ),
            "",
          );
        }
        finalMessage = finalMessage.trim();

        // Append embed reference blocks to the message
        const embedRefs = formatEmbedsForMessage(fileResult.embeds);
        if (embedRefs) {
          finalMessage += embedRefs;
        }

        preparedEmbeds.push(...fileResult.embeds.map((fileEmbed) => fileEmbed.embed));
      }

      // Show resolved mentions as confirmation
      if (parsed.resolved.length > 0 && !params.json) {
        clearTyping();
        for (const r of parsed.resolved) {
          const typeLabel = r.type.replace("_", " ");
          process.stderr.write(
            `\x1b[2m  ${r.original} → ${r.displayName} (${typeLabel})\x1b[0m\n`,
          );
        }
      }

    } catch {
      // If mention resolution fails (e.g., network error), send as-is
      // The backend will receive the raw @tokens and ignore unknown ones
    }
  }

  const piiResult = params.piiDetection !== false && redactor?.isInitialized
    ? redactor.redactWithMappings(finalMessage)
    : { redacted: finalMessage, mappings: [] };
  finalMessage = piiResult.redacted;

  if (!client.hasSession()) {
    let result: Awaited<ReturnType<OpenMatesClient["sendAnonymousMessage"]>>;
    try {
      result = await client.sendAnonymousMessage({
        message: finalMessage,
        learningMode: params.anonymousLearningMode,
      });
    } finally {
      clearTyping();
    }
    if (!params.json) {
      const mateBlock = ansiMateBlock(result.category, result.mateName);
      const modelSuffix = result.modelName
        ? `  \x1b[2m${result.modelName}\x1b[0m`
        : "";
      process.stdout.write(`${SEP}\n`);
      process.stdout.write(`${mateBlock}${modelSuffix}\n`);
      process.stdout.write(`${SEP}\n`);
      process.stdout.write(`${result.assistant}\n`);
    }
    return { ...result, taskEvents: [], pendingTaskUpdateJobs: [], acceptedTaskProposals: [] };
  }

  const urlResult = prepareUrlEmbeds(finalMessage);
  finalMessage = urlResult.message;
  preparedEmbeds.push(...urlResult.embeds);

  const result = await client.sendMessage({
    message: finalMessage,
    chatId: params.chatId,
    incognito: params.incognito,
    onStream,
    onSubChatEvent,
    onSubChatApprovalRequest,
    autoApproveSubChats: params.autoApproveSubChats,
    autoApproveMemories: params.autoApproveMemories,
    responseTimeoutMs: params.responseTimeoutMs,
    preparedEmbeds: preparedEmbeds.length > 0 ? preparedEmbeds : undefined,
    piiMappings: piiResult.mappings.map((mapping) => ({
      placeholder: mapping.placeholder,
      original: mapping.original,
      type: mapping.type,
    })),
  });

  clearTyping();

  const acceptedTaskProposals = params.acceptTaskProposals === true && result.status === "completed"
    ? await acceptChatTaskProposals(client, result.chatId, result.taskProposals, `${finalMessage}\n\n${result.assistant}`)
    : [];

  if (result.status === "waiting_for_user") {
    const question = parseInteractiveQuestionBlock(result.assistant);
    if (params.json && question) {
      return toWaitingForUserResult({
        chatId: result.chatId,
        messageId: result.messageId ?? "",
        parentId: result.chatId,
        question,
      });
    }

    if (!params.json) {
      process.stderr.write(
        "\x1b[33mOpenMates needs more input to continue.\x1b[0m\n" +
          "Continue in the web app, or rerun with --json to inspect the structured waiting state.\n",
      );
    }
    return { ...result, acceptedTaskProposals: [] };
  }

  if (!params.json) {
    if (!headerPrinted) {
      const mateBlock = ansiMateBlock(result.category, result.mateName);
      const modelSuffix = result.modelName
        ? `  \x1b[2m${result.modelName}\x1b[0m`
        : "";
      process.stdout.write(`${SEP}\n`);
      process.stdout.write(`${mateBlock}${modelSuffix}\n`);
      process.stdout.write(`${SEP}\n`);
    }

    // Render all embeds that were queued during streaming.
    // They appear after the text for now — the AI writes embed JSON before
    // the prose, so they should have been queued first. We also render
    // any embeds from the final content that weren't seen during streaming.
    const finalSegments = parseMessageSegments(result.assistant);
    const streamed = processedRawLength > 0;

    if (!streamed) {
      // No streaming happened — render everything from final content
      for (const seg of finalSegments) {
        if (seg.type === "embed") {
          try {
            const embed = await client.getEmbed(seg.value);
            await renderEmbedPreview(embed, client);
          } catch {
            renderEmbedFromMeta(seg.value, seg.meta);
          }
        } else {
          const cleaned = seg.value.replace(/\n{3,}/g, "\n\n");
          if (cleaned.trim()) process.stdout.write(cleaned);
        }
      }
      process.stdout.write("\n");
    } else {
      // Streaming happened — render queued embeds + any new ones
      process.stdout.write("\n");
      for (const seg of finalSegments) {
        if (seg.type === "embed" && !renderedEmbedIds.has(seg.value)) {
          pendingEmbedRenders.push({ id: seg.value, meta: seg.meta });
          renderedEmbedIds.add(seg.value);
        }
      }
    }

    // Now render all queued embed previews
    for (const entry of pendingEmbedRenders) {
      try {
        const embed = await client.getEmbed(entry.id);
        await renderEmbedPreview(embed, client);
      } catch {
        renderEmbedFromMeta(entry.id, entry.meta);
      }
    }

    const shortId = result.chatId.slice(0, 8);
    process.stdout.write(`${SEP}\n`);

    // Show follow-up suggestions if the post-processor returned any.
    // These are persisted per-chat and appear in `chats show` as well.
    if (result.followUpSuggestions.length > 0) {
      process.stdout.write(`\x1b[2mSuggested follow-ups:\x1b[0m\n`);
      for (const suggestion of result.followUpSuggestions) {
        const escapedSuggestion = suggestion.replace(/"/g, '\\"');
        process.stdout.write(
          `  \x1b[2m• ${suggestion}\x1b[0m\n` +
            `    \x1b[2mopenmates chats send --chat ${shortId} "${escapedSuggestion}"\x1b[0m\n`,
        );
      }
      process.stdout.write(`${SEP}\n`);
    }

    if (result.taskEvents.length > 0) {
      process.stdout.write(`\x1b[2mTask updates:\x1b[0m\n`);
      for (const event of result.taskEvents) {
        process.stdout.write(`  \x1b[2m- ${formatTaskEvent(event)}\x1b[0m\n`);
      }
      process.stdout.write(`${SEP}\n`);
    }

    if (result.pendingTaskUpdateJobs.length > 0) {
      const count = result.pendingTaskUpdateJobs.length;
      process.stdout.write(
        `\x1b[2mPending encrypted task update${count === 1 ? "" : "s"}: ${count}\x1b[0m\n` +
          `${SEP}\n`,
      );
    }

    process.stdout.write(
      `\x1b[2mContinue: openmates chats send --chat ${shortId} "your message"\x1b[0m\n` +
        `\x1b[2mHistory:  openmates chats show ${shortId}\x1b[0m\n`,
    );
  }

  return { ...result, acceptedTaskProposals };
}

function formatTaskEvent(event: TaskEventFrame): string {
  const taskLabel = event.short_id || event.task_id;
  const title = event.title ? ` "${event.title}"` : "";
  const status = event.status ? ` (${event.status})` : "";
  const reason = event.reason ? `: ${event.reason}` : "";
  switch (event.event_type) {
    case "created":
      return `${taskLabel} created${title}${status}`;
    case "updated":
      return `${taskLabel} updated${title}${status}`;
    case "blocked":
      return `${taskLabel} blocked${reason}`;
    case "completed":
      return `${taskLabel} completed${title}`;
    case "unblocked":
      return `${taskLabel} unblocked`;
    default:
      return `${taskLabel} ${event.event_type}${title}${status}${reason}`;
  }
}

async function acceptChatTaskProposals(
  client: OpenMatesClient,
  chatId: string,
  proposals: Array<{
    title: string;
    description?: string | null;
    status?: UserTaskStatus;
    assignee_type?: "ai" | "user";
  }>,
  fallbackText: string,
): Promise<Array<Record<string, unknown>>> {
  let proposalsToAccept = proposals;
  if (proposalsToAccept.length === 0 && fallbackText.trim()) {
    const extractionText = buildTaskProposalFallbackText(fallbackText);
    proposalsToAccept = await client.extractUserTaskProposals({
      correctedText: extractionText,
      contextChatId: chatId,
    });
  }
  if (proposalsToAccept.length === 0) return [];
  const masterKey = client.getMasterKeyBytes();
  const accepted: Array<Record<string, unknown>> = [];
  for (const proposal of proposalsToAccept) {
    const input = await buildCreateUserTaskInput(masterKey, {
      title: proposal.title,
      description: proposal.description ?? "",
      status: proposal.status,
      assign: proposal.assignee_type ?? "user",
      chatId,
    });
    const created = await client.createUserTask(input);
    const decrypted = await decryptUserTask(created, masterKey);
    accepted.push(taskToJson(decrypted));
  }
  return accepted;
}

function buildTaskProposalFallbackText(text: string): string {
  const seen = new Set<string>();
  const bulletLines = text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => /^[-*•]\s+/.test(line))
    .map((line) => line.replace(/^([-*•]\s*)\[[ xX]\]\s*/, "$1"))
    .filter((line) => {
      const key = line.replace(/^[-*•]\s+/, "").trim().toLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  return bulletLines.length > 0 ? bulletLines.join("\n") : text;
}

function printIncognitoNoHistoryNotice(json: boolean): void {
  const message =
    "Incognito chats are not stored. There is no incognito history to show or clear.";
  if (json) {
    printJson({ history: [], stored: false, message });
    return;
  }
  console.log(message);
}

const SEP = `\x1b[2m${"─".repeat(60)}\x1b[0m`;

/**
 * Parse the inline embed UUID blocks from AI message content.
 *
 * The AI writes embed references as:
 *   ```json
 *   {"type":"app_skill_use","embed_id":"<uuid>","app_id":"...","skill_id":"...","query":"..."}
 *   ```
 * or the legacy:
 *   ```json_embed
 *   {"embed_id":"<uuid>"}
 *   ```
 *
 * Returns the content split into segments: either plain text segments or embed
 * UUID strings prefixed with "EMBED:" so the renderer can fetch them in-place.
 */
/** Parsed segment from AI message content.
 * rawLength = number of characters this segment consumed in the original string.
 * For text segments, rawLength === value.length.
 * For embed segments, rawLength includes the full \`\`\`json\n...\n\`\`\` delimiters. */
type MessageSegment =
  | { type: "text"; value: string; rawLength: number }
  | {
      type: "embed";
      value: string;
      meta?: Record<string, unknown>;
      rawLength: number;
    };

function parseMessageSegments(content: string): MessageSegment[] {
  const segments: MessageSegment[] = [];
  // Match both ```json and ```json_embed blocks
  const pattern = /```(?:json_embed|json)\n([\s\S]*?)\n```/g;
  let last = 0;
  let m: RegExpExecArray | null;

  while ((m = pattern.exec(content)) !== null) {
    // Text before this block
    if (m.index > last) {
      const text = content.slice(last, m.index);
      segments.push({ type: "text", value: text, rawLength: text.length });
    }

    // Try to extract an embed_id from the JSON block.
    // Keep the full parsed JSON as `meta` so we can render a preview
    // even when the embed isn't in the local sync cache (failed/processing).
    // rawLength = length of the entire ```json\n...\n``` block in the original string.
    const blockRawLength = m[0].length;
    try {
      const parsed = JSON.parse(m[1].trim()) as Record<string, unknown>;
      const embedId =
        typeof parsed.embed_id === "string" ? parsed.embed_id : null;
      if (embedId) {
        segments.push({
          type: "embed",
          value: embedId,
          meta: parsed,
          rawLength: blockRawLength,
        });
      }
    } catch {
      // Malformed JSON — discard
    }

    last = m.index + m[0].length;
  }

  // Remaining text after last block
  if (last < content.length) {
    const text = content.slice(last);
    segments.push({ type: "text", value: text, rawLength: text.length });
  }

  return segments;
}

/**
 * Render an embed preview from the inline JSON metadata when the embed
 * is not found in the sync cache (failed, processing, or not yet synced).
 */
function renderEmbedFromMeta(
  embedId: string,
  meta?: Record<string, unknown>,
): void {
  const shortId = embedId.slice(0, 8);
  if (!meta) {
    process.stdout.write(
      `\x1b[2m┌─\x1b[0m \x1b[33m⟳\x1b[0m \x1b[1membed\x1b[0m  \x1b[33mProcessing...\x1b[0m\n`,
    );
    process.stdout.write(`\x1b[2m└─ openmates embeds show ${shortId}\x1b[0m\n`);
    return;
  }

  const app = typeof meta.app_id === "string" ? meta.app_id : "";
  const skill = typeof meta.skill_id === "string" ? meta.skill_id : "";
  const label = skill ? `${app}/${skill}` : app || "embed";
  const query = typeof meta.query === "string" ? `  · "${meta.query}"` : "";
  const provider =
    typeof meta.provider === "string" ? `  via ${meta.provider}` : "";

  // Mark as Processing (not in cache = not finished)
  process.stdout.write(
    `\x1b[2m┌─\x1b[0m \x1b[33m⟳\x1b[0m \x1b[1m${label}\x1b[0m${query}\x1b[2m${provider}\x1b[0m  \x1b[33mProcessing...\x1b[0m\n`,
  );
  process.stdout.write(`\x1b[2m└─ openmates embeds show ${shortId}\x1b[0m\n`);
}

/**
 * Render message text with embed references resolved.
 *
 * Embed references in message content use markdown link syntax:
 * - `[!](embed:slug)` — block-level preview badge (rendered as child embed preview)
 * - `[text](embed:slug)` — inline text badge (rendered as "text [↗ domain]")
 *
 * The embedRefIndex maps slugs to decrypted embeds so we can render them.
 * Falls back to displaying the slug domain when the embed can't be resolved.
 */
async function renderMessageText(
  text: string,
  embedRefIndex: Map<string, import("./client.js").DecryptedEmbed>,
  client: import("./client.js").OpenMatesClient,
): Promise<void> {
  // Split text into segments: regular text vs embed reference lines.
  // Process line-by-line to handle [!](embed:...) block refs properly.
  const lines = text.split("\n");
  const outputLines: string[] = [];

  for (const line of lines) {
    // Check for block-level embed refs: [!](embed:slug) or [](embed:slug)
    // These may appear alone on a line or with whitespace
    const blockMatch = line.match(/^\s*\[!?\]\(embed:([^)]+)\)\s*$/);
    if (blockMatch) {
      // Flush any pending text before rendering embed blocks
      if (outputLines.length > 0) {
        const flushed = outputLines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
        if (flushed) process.stdout.write(`${flushed}\n`);
        outputLines.length = 0;
      }

      const slug = blockMatch[1];
      const embed = embedRefIndex.get(slug);
      if (embed) {
        await renderEmbedPreview(embed, client);
      } else {
        // Unresolved block ref — show slug as hint
        const domain = slug.replace(/-[A-Za-z0-9]{3}$/, "");
        process.stdout.write(
          `\x1b[2m┌─\x1b[0m \x1b[33m?\x1b[0m \x1b[2m${domain}\x1b[0m\n` +
            `\x1b[2m└─ (embed not in cache)\x1b[0m\n`,
        );
      }
      continue;
    }

    // Replace inline embed refs: [text](embed:slug) → "text [↗ domain]"
    const processed = line.replace(
      /\[([^\]]+)\]\(embed:([^)]+)\)/g,
      (_match, displayText: string, slug: string) => {
        const embed = embedRefIndex.get(slug);
        if (embed) {
          // Use the embed's URL or text preview for extra context
          const url =
            typeof embed.content?.url === "string" ? embed.content.url : null;
          const domain = url
            ? new URL(url).hostname.replace(/^www\./, "")
            : slug.replace(/-[A-Za-z0-9]{3}$/, "");
          return `${displayText} \x1b[2m[↗ ${domain}]\x1b[0m`;
        }
        // Unresolved — show slug domain as fallback
        const domain = slug.replace(/-[A-Za-z0-9]{3}$/, "");
        return `${displayText} \x1b[2m[↗ ${domain}]\x1b[0m`;
      },
    );
    outputLines.push(processed);
  }

  // Flush remaining text
  if (outputLines.length > 0) {
    const flushed = outputLines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
    if (flushed) process.stdout.write(`${flushed}\n`);
  }
}

/**
 * Render a full chat conversation with messages, colored mate blocks, and inline embed content.
 *
 * Layout per message:
 *   ────────────────────────
 *    You   2026-03-16 18:17   (or mate block for assistant)
 *   ────────────────────────
 *   message text
 *   [embed blocks inline at their json block positions]
 *
 * After last message:
 *   ────────────────────────
 */
async function printChatConversation(
  client: OpenMatesClient,
  chat: {
    id: string;
    shortId: string;
    title: string | null;
    category: string | null;
    mateName: string | null;
    updatedAt: number | null;
  },
  messages: DecryptedMessage[],
  followUpSuggestions?: string[],
  options: { example?: boolean } = {},
): Promise<void> {
  const block = ansiColorBlock(chat.category);
  const title = chat.title ?? "(no title)";
  const ts = formatTimestamp(chat.updatedAt);

  if (options.example) {
    process.stdout.write("\x1b[33mEXAMPLE CHAT\x1b[0m\n");
    process.stdout.write("\x1b[2mThis is a public example chat. Log in to create and sync your own private chats.\x1b[0m\n\n");
  }

  // Header: colored block + date + # Title
  process.stdout.write(`${block}  \x1b[2m${chat.shortId}  ${ts}\x1b[0m\n`);
  process.stdout.write(`\x1b[1;4m# ${title}\x1b[0m\n\n`);

  if (messages.length === 0) {
    process.stdout.write("\x1b[2m(no messages)\x1b[0m\n");
    return;
  }

  // Collect parent embed IDs from message JSON blocks, then build a
  // slug → DecryptedEmbed index for only their child embeds.
  // This avoids decrypting all 2000+ embeds in the cache.
  const parentEmbedIds = new Set<string>();
  for (const msg of messages) {
    if (!msg.content) continue;
    const segs = parseMessageSegments(msg.content);
    for (const seg of segs) {
      if (seg.type === "embed" && seg.value) {
        parentEmbedIds.add(seg.value);
      }
    }
  }
  // Also check if any message text contains embed: refs at all
  const hasEmbedRefs = !options.example && messages.some(
    (m) => m.content && /\(embed:[^)]+\)/.test(m.content),
  );
  const embedRefIndex = hasEmbedRefs
    ? await client.buildEmbedRefIndex(parentEmbedIds)
    : new Map<string, import("./client.js").DecryptedEmbed>();

  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i];
    const msgTs = formatTimestamp(msg.createdAt);

    // ── Separator + sender header ──────────────────────────────────────────
    process.stdout.write(`${SEP}\n`);

    if (msg.role === "user") {
      process.stdout.write(`\x1b[1mYou\x1b[0m  \x1b[2m${msgTs}\x1b[0m\n`);
    } else if (msg.role === "assistant" || msg.role === "ai") {
      const msgCategory = msg.category ?? chat.category;
      const msgMateName = msgCategory
        ? (MATE_NAMES[msgCategory] ?? chat.mateName)
        : chat.mateName;
      const mateBlock = ansiMateBlock(msgCategory, msgMateName);
      const modelSuffix = msg.modelName
        ? `  \x1b[2m${msg.modelName}\x1b[0m`
        : "";
      process.stdout.write(
        `${mateBlock}${modelSuffix}  \x1b[2m${msgTs}\x1b[0m\n`,
      );
    } else {
      process.stdout.write(`\x1b[2m${msg.role}  ${msgTs}\x1b[0m\n`);
    }

    process.stdout.write(`${SEP}\n`);

    // ── Message body: text + inline embeds at their actual positions ───────
    if (msg.content) {
      const segments = parseMessageSegments(msg.content);

      for (const seg of segments) {
        if (seg.type === "embed") {
          try {
            const embed = await client.getEmbed(seg.value);
            await renderEmbedPreview(embed, client);
          } catch {
            // Embed not in cache — render from inline JSON metadata if available.
            // This handles embeds that failed/are processing and weren't synced.
            renderEmbedFromMeta(seg.value, seg.meta);
          }
        } else {
          await renderMessageText(seg.value, embedRefIndex, client);
        }
      }
    }

    // NOTE: Skill embeds (web/search, events/search, etc.) are associated
    // with the user's message via hashed_message_id, but they are rendered
    // inline in the assistant's message where the AI placed the ```json
    // embed reference. We do NOT render msg.embedIds here — that caused
    // the duplicate embed display bug. User-attached files (images, PDFs)
    // are embedded in the user message content itself as json blocks.
  }

  // Final closing separator
  process.stdout.write(`${SEP}\n`);

  // Show follow-up suggestions if available for this chat.
  // These are generated by the post-processor and persisted per-chat.
  if (followUpSuggestions && followUpSuggestions.length > 0) {
    process.stdout.write(`\x1b[2mSuggested follow-ups:\x1b[0m\n`);
    for (const suggestion of followUpSuggestions) {
      const escapedSuggestion = suggestion.replace(/"/g, '\\"');
      process.stdout.write(
        `  \x1b[2m• ${suggestion}\x1b[0m\n` +
          `    \x1b[2mopenmates chats send --chat ${chat.shortId} "${escapedSuggestion}"\x1b[0m\n`,
      );
    }
    process.stdout.write(`${SEP}\n`);
  }

  process.stdout.write(
    options.example
      ? `\x1b[2mOpen in browser: openmates chats open ${chat.shortId}\x1b[0m\n`
      : `\x1b[2mContinue: openmates chats send --chat ${chat.shortId} "your message"\x1b[0m\n`,
  );
}

/**
 * Print chat conversation in raw mode — shows the original decrypted message
 * content without any embed rendering or text cleaning. Useful for debugging
 * how the AI wrote embed references and understanding the underlying format.
 */
async function printChatConversationRaw(
  chat: {
    id: string;
    shortId: string;
    title: string | null;
    category: string | null;
    mateName: string | null;
    updatedAt: number | null;
  },
  messages: DecryptedMessage[],
  options: { example?: boolean } = {},
): Promise<void> {
  const title = chat.title ?? "(no title)";
  const ts = formatTimestamp(chat.updatedAt);

  if (options.example) {
    process.stdout.write("EXAMPLE CHAT\n");
    process.stdout.write("This is a public example chat. Log in to create and sync your own private chats.\n\n");
  }

  process.stdout.write(`\x1b[2m${chat.shortId}  ${ts}\x1b[0m\n`);
  process.stdout.write(`\x1b[1;4m# ${title}\x1b[0m  \x1b[2m(raw)\x1b[0m\n\n`);

  if (messages.length === 0) {
    process.stdout.write("\x1b[2m(no messages)\x1b[0m\n");
    return;
  }

  for (const msg of messages) {
    const msgTs = formatTimestamp(msg.createdAt);

    process.stdout.write(`${SEP}\n`);

    const role =
      msg.role === "user"
        ? "You"
        : (msg.senderName ?? msg.role);
    process.stdout.write(`\x1b[1m${role}\x1b[0m  \x1b[2m${msgTs}\x1b[0m\n`);
    process.stdout.write(`${SEP}\n`);

    if (msg.content) {
      process.stdout.write(`${msg.content}\n`);
    } else {
      process.stdout.write("\x1b[2m(empty)\x1b[0m\n");
    }
  }

  process.stdout.write(`${SEP}\n`);
}

// Legacy renderInlineEmbed and printEmbedDetail removed — replaced by
// renderEmbedPreview() and renderEmbedFullscreen() in embedRenderers.ts.

// ---------------------------------------------------------------------------
// Apps renderers
// ---------------------------------------------------------------------------

interface SkillMetadata {
  id: string;
  name: string;
  description?: string;
  providers?: Array<{
    provider: string;
    name?: string;
    description?: string;
    pricing?: unknown;
  }>;
}

interface AppMetadata {
  id: string;
  name: string;
  description?: string;
  skills?: SkillMetadata[];
  focus_modes?: Array<{ id: string; name: string; description?: string }>;
  settings_and_memories?: Array<{
    id: string;
    name: string;
    description?: string;
  }>;
}

interface AppsListResponse {
  apps?: AppMetadata[];
}

function printAppsList(data: AppsListResponse): void {
  const apps =
    data?.apps ?? (Array.isArray(data) ? (data as AppMetadata[]) : []);
  if (apps.length === 0) {
    console.log("No apps available.");
    return;
  }
  header(`Apps  (${apps.length})\n`);
  for (const app of apps) {
    const skillCount = app.skills?.length ?? 0;
    process.stdout.write(
      `\x1b[1m${app.name ?? app.id}\x1b[0m  \x1b[2m${app.id}\x1b[0m  ` +
        `\x1b[2m${skillCount} skill${skillCount !== 1 ? "s" : ""}\x1b[0m\n`,
    );
    if (app.description) {
      process.stdout.write(`  \x1b[2m${app.description}\x1b[0m\n`);
    }
    if (app.skills && app.skills.length > 0) {
      for (const skill of app.skills) {
        process.stdout.write(
          `    \x1b[36m${app.id} ${skill.id}\x1b[0m` +
            (skill.name !== skill.id ? `  \x1b[2m${skill.name}\x1b[0m` : "") +
            "\n",
        );
      }
    }
    console.log();
  }
  console.log(
    `\x1b[2mInspect: openmates apps skill-info <app-id> <skill-id>\x1b[0m`,
  );
}

async function printAppInfo(
  client: OpenMatesClient,
  data: AppMetadata,
): Promise<void> {
  header(`${data.name ?? data.id}  \x1b[2m(${data.id})\x1b[0m`);
  if (data.description) {
    console.log(`\n${data.description}\n`);
  } else {
    console.log();
  }

  const skills = data.skills ?? [];
  if (skills.length > 0) {
    process.stdout.write(`\x1b[1mSkills\x1b[0m\n`);
    for (const skill of skills) {
      process.stdout.write(
        `  \x1b[36m${skill.id}\x1b[0m  ${skill.name ?? skill.id}\n`,
      );
      if (skill.description) {
        process.stdout.write(`    \x1b[2m${skill.description}\x1b[0m\n`);
      }
      const providers = skill.providers ?? [];
      if (providers.length > 0) {
        const names = providers.map((p) => p.name ?? p.provider).join(", ");
        process.stdout.write(`    \x1b[2mProviders: ${names}\x1b[0m\n`);
      }
      // Show required input parameters inline (compact) — use --help for full detail
      const params = await client
        .getSkillSchema(data.id, skill.id)
        .catch(() => []);
      const required = params.filter((p) => p.required);
      if (required.length > 0) {
        // Show name + a short type hint (strip "array of {...}" to just "array")
        const reqStr = required
          .map((p) => {
            const shortType = p.type.startsWith("array of") ? "array" : p.type;
            return `${p.name} \x1b[2m(${shortType})\x1b[0m`;
          })
          .join("  ");
        process.stdout.write(`    \x1b[2mRequired:\x1b[0m ${reqStr}\n`);
        process.stdout.write(
          `    \x1b[2mopenmates apps skill-info ${data.id} ${skill.id}  for details\x1b[0m\n`,
        );
      }
      const exampleCount = listExampleChatsForSkill(data.id, skill.id).length;
      if (exampleCount > 0) {
        process.stdout.write(
          `    \x1b[2mExamples: openmates apps examples ${data.id} ${skill.id} (${exampleCount})\x1b[0m\n`,
        );
      }
    }
    console.log();
  }

  const focuses = data.focus_modes ?? [];
  if (focuses.length > 0) {
    process.stdout.write(`\x1b[1mFocus modes\x1b[0m\n`);
    for (const f of focuses) {
      process.stdout.write(`  \x1b[36m${f.id}\x1b[0m  ${f.name}\n`);
      if (f.description) {
        process.stdout.write(`    \x1b[2m${f.description}\x1b[0m\n`);
      }
    }
    console.log();
  }

  console.log(
    `\x1b[2mDetails: openmates apps skill-info ${data.id} <skill-id>\x1b[0m`,
  );
}

async function printSkillInfo(
  client: OpenMatesClient,
  appId: string,
  data: SkillMetadata,
): Promise<void> {
  header(`${data.name ?? data.id}  \x1b[2m(${appId}/${data.id})\x1b[0m`);
  if (data.description) {
    console.log(`\n${data.description}\n`);
  } else {
    console.log();
  }

  // Providers
  const providers = data.providers ?? [];
  if (providers.length > 0) {
    process.stdout.write(`\x1b[1mProviders\x1b[0m\n`);
    for (const p of providers) {
      process.stdout.write(
        `  \x1b[36m${p.provider}\x1b[0m  ${p.name ?? p.provider}\n`,
      );
      if (p.description) {
        process.stdout.write(`    \x1b[2m${p.description}\x1b[0m\n`);
      }
      if (p.pricing) {
        const pr = p.pricing as Record<string, unknown>;
        const perReq = pr.per_request_credits ?? pr.credits;
        if (perReq !== undefined)
          process.stdout.write(
            `    \x1b[2m${perReq} credits per request\x1b[0m\n`,
          );
      }
    }
    console.log();
  }

  // Fetch input parameter schema from OpenAPI spec
  const params = await client.getSkillSchema(appId, data.id).catch(() => []);
  const requiredParams = params.filter((p) => p.required);
  const optionalParams = params.filter((p) => !p.required);

  if (params.length > 0) {
    // ── Required parameters ──────────────────────────────────────────────
    if (requiredParams.length > 0) {
      process.stdout.write(`\x1b[1mRequired parameters\x1b[0m\n`);
      for (const p of requiredParams) {
        process.stdout.write(
          `  \x1b[33m*\x1b[0m \x1b[1m${p.name}\x1b[0m  \x1b[2m(${p.type})\x1b[0m\n`,
        );
        if (p.description) {
          // Wrap long descriptions at ~72 chars
          const lines = wrapText(p.description, 68);
          for (const l of lines)
            process.stdout.write(`      \x1b[2m${l}\x1b[0m\n`);
        }
      }
      console.log();
    }

    // ── Optional parameters ──────────────────────────────────────────────
    if (optionalParams.length > 0) {
      process.stdout.write(`\x1b[1mOptional parameters\x1b[0m\n`);
      for (const p of optionalParams) {
        const defStr =
          p.default !== undefined && p.default !== null
            ? `  \x1b[2m[default: ${JSON.stringify(p.default)}]\x1b[0m`
            : "";
        process.stdout.write(
          `    \x1b[36m${p.name}\x1b[0m  \x1b[2m(${p.type})\x1b[0m${defStr}\n`,
        );
        if (p.description) {
          const lines = wrapText(p.description, 68);
          for (const l of lines)
            process.stdout.write(`      \x1b[2m${l}\x1b[0m\n`);
        }
      }
      console.log();
    }

    // ── Example input JSON ───────────────────────────────────────────────
    // Build a minimal schema example showing required fields + first 2 optional.
    const exampleItem: Record<string, unknown> = {};
    for (const p of requiredParams) {
      exampleItem[p.name] = buildExampleValue(p.name, p.type, p.description);
    }
    // Show up to 2 optional params to give context
    for (const p of optionalParams.slice(0, 2)) {
      exampleItem[p.name] =
        p.default ?? buildExampleValue(p.name, p.type, p.description);
    }
    process.stdout.write(`\x1b[1mInput example\x1b[0m\n`);
    const usesFlatInput = params.some((p) => p.inputShape === "flat");
    const examplePayload = usesFlatInput ? exampleItem : { requests: [exampleItem] };
    const exampleJson = JSON.stringify(examplePayload, null, 2)
      .split("\n")
      .map((l) => `  ${l}`)
      .join("\n");
    process.stdout.write(`${exampleJson}\n`);
    console.log();
  } else {
    console.log(`\x1b[2mThis skill does not declare input parameters.\x1b[0m`);
  }

  const examples = listExampleChatsForSkill(appId, data.id);
  if (examples.length > 0) {
    console.log();
    printExampleChatsForSkill(appId, data.id, examples, { compact: true });
  }
}

function exampleChatForSkillToJson(example: ExampleChatSkillListItem): Record<string, unknown> {
  return {
    chat_id: example.id,
    short_id: example.shortId,
    slug: example.slug,
    title: example.title,
    summary: example.summary,
    updated_at: example.updatedAt,
    category: example.category,
    source: example.source,
    linked_app_skills: example.linkedAppSkills,
    commands: {
      show: `openmates chats show ${example.id}`,
      open: `openmates chats open ${example.slug}`,
    },
  };
}

function printExampleChatsForSkill(
  appId: string,
  skillId: string | undefined,
  examples: ExampleChatSkillListItem[],
  options: { compact?: boolean } = {},
): void {
  const label = skillId ? `${appId}/${skillId}` : appId;
  header(`Example chats for ${label}`);
  if (examples.length === 0) {
    console.log(`\nNo example chats are linked to ${label} yet.`);
    if (skillId) {
      console.log("\nInspect the skill:");
      console.log(`  openmates apps skill-info ${appId} ${skillId}`);
    } else {
      console.log("\nInspect available skills:");
      console.log(`  openmates apps ${appId}`);
    }
    return;
  }

  const visibleExamples = options.compact ? examples.slice(0, 3) : examples;
  console.log();
  visibleExamples.forEach((example, index) => {
    console.log(`${index + 1}. ${example.title ?? example.id}`);
    console.log(`   ${example.id}`);
    if (example.summary) console.log(`   ${example.summary}`);
    if (!skillId) {
      const linkedSkills = example.linkedAppSkills
        .filter((key) => key.startsWith(`${appId}.`))
        .join(", ");
      console.log(`   Skills: ${linkedSkills}`);
    }
    console.log(`   Show: openmates chats show ${example.id}`);
    console.log(`   Open: openmates chats open ${example.slug}`);
    console.log();
  });
  if (options.compact && examples.length > visibleExamples.length) {
    console.log(`More examples: openmates apps examples ${appId}${skillId ? ` ${skillId}` : ""}`);
  } else if (options.compact) {
    console.log(`All examples: openmates apps examples ${appId}${skillId ? ` ${skillId}` : ""}`);
  }
}

/** Wrap text at `width` chars, preserving existing sentence structure. */
function wrapText(text: string, width: number): string[] {
  const words = text.split(" ");
  const lines: string[] = [];
  let current = "";
  for (const w of words) {
    if (current.length + w.length + 1 > width && current.length > 0) {
      lines.push(current);
      current = w;
    } else {
      current = current.length > 0 ? `${current} ${w}` : w;
    }
  }
  if (current.length > 0) lines.push(current);
  return lines;
}

/** Build a placeholder example value for a param based on name/type/description. */
function buildExampleValue(
  name: string,
  type: string,
  description: string,
): unknown {
  // Common patterns
  if (name === "query" || name.endsWith("_query")) return "Berlin AI meetups";
  if (name === "location") return "Berlin, Germany";
  if (name === "url") return "https://example.com";
  if (name === "date" || name.includes("_date")) return "2026-04-15";
  if (name === "check_in_date") return "2026-04-15";
  if (name === "check_out_date") return "2026-04-18";
  if (name === "legs") {
    return [{ origin: "BER", destination: "LHR", date: "2026-04-15" }];
  }
  if (type.startsWith("array")) {
    // Try to infer item structure from description
    if (
      description.toLowerCase().includes("origin") &&
      description.toLowerCase().includes("destination")
    ) {
      return [
        {
          origin: "<IATA>",
          destination: "<IATA>",
          date: "YYYY-MM-DD",
        },
      ];
    }
    return ["<value>"];
  }
  if (type === "integer" || type === "number") return 1;
  if (type === "boolean") return false;
  return `<${name}>`;
}

/**
 * Smart skill result renderer.
 * Handles the common { success, data, credits_charged } envelope and extracts
 * the inner content into a readable format.  Falls back to a generic key-value
 * display for shapes it doesn't recognise.
 */
function printSkillResult(app: string, skill: string, raw: unknown): void {
  const res = raw as Record<string, unknown>;

  // Top-level error
  if (res.success === false) {
    console.error(
      `\x1b[31m✗ Skill failed:\x1b[0m ${res.error ?? "unknown error"}`,
    );
    return;
  }

  const data = (res.data ?? res) as Record<string, unknown>;
  const credits =
    typeof res.credits_charged === "number" ? res.credits_charged : null;

  if (data.success === false) {
    console.error(
      `\x1b[31m✗ Skill failed:\x1b[0m ${data.error ?? res.error ?? "unknown error"}`,
    );
    return;
  }

  if (str(data.status) === "waiting_for_client" && data.pending_client_search && typeof data.pending_client_search === "object") {
    const pending = data.pending_client_search as Record<string, unknown>;
    header(`${capitalise(app)} › ${capitalise(skill)}${credits !== null ? `  \x1b[2m(${credits} credits)\x1b[0m` : ""}\n`);
    console.log("Waiting for a connected task client to search encrypted local task content.");
    const requestId = str(pending.request_id);
    if (requestId) kv("request", requestId, 12);
    if (pending.notification_queued === true) kv("notification", "queued", 12);
    return;
  }

  // ── Grouped results: { results: [{ id, results: [...] }] } ──────────────
  // This is the standard shape for request-array skills. App-skill embed
  // responses can also return a flat results array of child task/workflow items.
  type ResultItem = Record<string, unknown>;
  const topResults = data?.results as ResultItem[] | undefined;
  if (Array.isArray(topResults)) {
    const resultItems: ResultItem[] = [];
    for (const group of topResults) {
      const items = group.results as ResultItem[] | undefined;
      if (Array.isArray(items)) resultItems.push(...items);
      else resultItems.push(group);
    }
    if (resultItems.length === 0) {
      header(
        `${capitalise(app)} › ${capitalise(skill)}  \x1b[2m(${credits !== null ? `${credits} credits` : "no results"})\x1b[0m\n`,
      );
      console.log("No results found.");
      const topLevelReason = str(data.no_result_reason) ?? str(data.error);
      if (topLevelReason) kv("reason", topLevelReason, 12);
      for (const group of topResults) {
        const reason = str(group.no_result_reason) ?? str(group.error);
        if (reason) kv("reason", reason, 12);
        const groupSuggestions = group.suggestions;
        if (Array.isArray(groupSuggestions) && groupSuggestions.length > 0) {
          kv("try", (groupSuggestions as unknown[]).map((value) => String(value)).join(" · "), 12);
        }
      }
      const responseSuggestions = data.suggestions_follow_up_requests;
      if (Array.isArray(responseSuggestions) && responseSuggestions.length > 0) {
        kv("try", (responseSuggestions as unknown[]).map((value) => String(value)).join(" · "), 12);
      }
      const provider = str(data.provider);
      if (provider) console.log(`\x1b[2mProvider: ${provider}\x1b[0m`);
      return;
    }
    if (resultItems.length > 0) {
      header(
        `${capitalise(app)} › ${capitalise(skill)}  \x1b[2m(${resultItems.length} result${resultItems.length !== 1 ? "s" : ""}${credits !== null ? `, ${credits} credits` : ""})\x1b[0m\n`,
      );
      let resultNum = 0;
      for (const item of resultItems) {
        resultNum += 1;
        printSkillResultItem(item, resultNum, resultItems.length);
      }

      // ── Provider info ──────────────────────────────────────────────────
      const provider = str(data.provider);
      if (provider) {
        console.log(`\x1b[2mProvider: ${provider}\x1b[0m`);
      }

      // ── Follow-up suggestions ──────────────────────────────────────────
      const suggestions = data.suggestions_follow_up_requests;
      if (Array.isArray(suggestions) && suggestions.length > 0) {
        console.log(
          `\x1b[2mSuggestions: ${(suggestions as string[]).join(" · ")}\x1b[0m`,
        );
      }
      return;
    }
  }

  // ── AI / text response ───────────────────────────────────────────────────
  const textContent =
    str(data?.content) ??
    str(data?.text) ??
    str(data?.answer) ??
    str(data?.message) ??
    str(data?.response) ??
    str(data?.output);
  if (textContent) {
    header(
      `${capitalise(app)} › ${capitalise(skill)}${credits !== null ? `  \x1b[2m(${credits} credits)\x1b[0m` : ""}\n`,
    );
    console.log(textContent);
    return;
  }

  // ── Generic fallback ─────────────────────────────────────────────────────
  header(
    `${capitalise(app)} › ${capitalise(skill)}${credits !== null ? `  \x1b[2m(${credits} credits)\x1b[0m` : ""}\n`,
  );
  printGenericObject(data);
}

/**
 * Print a single skill result item with a numbered header line and full details.
 *
 * For known high-volume search result types a compact human-readable card is
 * printed by default. Full provider payloads remain available through --json.
 * For unknown types, printGenericObject renders every field.
 */
function printSkillResultItem(
  item: Record<string, unknown>,
  num: number,
  total: number,
): void {
  const itemType = str(item.type);
  const numLabel = total > 1 ? `\x1b[36m[${num}]\x1b[0m ` : "";

  // ── OpenMates task child embed result ───────────────────────────────────
  if (itemType === "task") {
    const title = str(item.title) ?? "Untitled task";
    const taskId = str(item.short_id) ?? str(item.task_id) ?? "unknown-task";
    const summary = [str(item.status), str(item.assignee) ? `assignee: ${str(item.assignee)}` : null]
      .filter(Boolean)
      .join(" · ");
    console.log(`${numLabel}\x1b[1mtask · ${taskId} · ${title}\x1b[0m${summary ? `  ${summary}` : ""}`);
    console.log(`\x1b[2m  → openmates tasks show ${taskId}\x1b[0m`);
    console.log("");
    return;
  }

  // ── OpenMates workflow child embed result ───────────────────────────────
  if (itemType === "workflow") {
    const title = str(item.title) ?? "Untitled workflow";
    const workflowId = str(item.workflow_id) ?? str(item.id) ?? "unknown-workflow";
    const status = str(item.status);
    console.log(`${numLabel}\x1b[1mworkflow · ${title}\x1b[0m${status ? `  ${status}` : ""}`);
    console.log(`\x1b[2m  → openmates workflows show ${workflowId}\x1b[0m`);
    console.log("");
    return;
  }

  // ── Connection (travel flights/trains) ─────────────────────────────────
  if (itemType === "connection") {
    const origin = str(item.origin) ?? "?";
    const dest = str(item.destination) ?? "?";
    const dep = str(item.departure) ?? "";
    const arr = str(item.arrival) ?? "";
    const dur = str(item.duration) ?? "";
    const price = str(item.total_price);
    const currency = str(item.currency) ?? "EUR";
    const stops = typeof item.stops === "number" ? item.stops : undefined;
    const carriers = Array.isArray(item.carriers)
      ? (item.carriers as string[]).join(", ")
      : null;
    const stopsLabel =
      stops === 0 ? "direct" : stops === 1 ? "1 stop" : `${stops} stops`;

    // Header: [N] BER → LHR  54 EUR · direct · Eurowings
    const summary: string[] = [];
    if (price) summary.push(`${price} ${currency}`);
    if (stops !== undefined) summary.push(stopsLabel);
    if (carriers) summary.push(carriers);
    console.log(
      `${numLabel}\x1b[1m${origin} → ${dest}\x1b[0m  ${summary.join(" · ")}`,
    );
    // Sub-line: departure → arrival (duration)
    if (dep || arr || dur) {
      const parts: string[] = [];
      if (dep) parts.push(dep);
      if (arr) parts.push(`→ ${arr}`);
      if (dur) parts.push(`(${dur})`);
      console.log(`  ${parts.join("  ")}`);
    }
    // Booking link hint
    if (typeof item.booking_token === "string") {
      console.log(`\x1b[2m  → Get booking URL (25 credits):\x1b[0m`);
      console.log(
        `\x1b[2m    rerun with --json to copy booking_token, then use openmates apps travel booking-link\x1b[0m`,
      );
    }
    console.log("");
    return;
  }

  // ── Stay (travel hotels/accommodation) ─────────────────────────────────
  if (itemType === "stay") {
    const name = str(item.name) ?? str(item.property_name) ?? "Unknown";
    const rating = item.overall_rating ?? item.rating;
    const price =
      str(item.rate_per_night) ?? str(item.price_per_night) ?? str(item.price);
    const summary: string[] = [];
    if (rating) summary.push(`★ ${rating}`);
    if (price) summary.push(price);
    console.log(`${numLabel}\x1b[1m${name}\x1b[0m  ${summary.join(" · ")}`);
    const amenities = Array.isArray(item.amenities)
      ? (item.amenities as unknown[]).map((value) => String(value)).slice(0, 6)
      : [];
    if (amenities.length > 0) kv("amenities", amenities.join(", "), 14);
    const reviews = item.reviews;
    if (reviews !== undefined && reviews !== null) kv("reviews", String(reviews), 14);
    const link = str(item.link) ?? str(item.url);
    if (link) kv("url", link, 14);
    console.log("");
    return;
  }

  // ── Event result ────────────────────────────────────────────────────────
  if (itemType === "event_result") {
    const title = str(item.title) ?? str(item.name) ?? "Untitled event";
    const provider = str(item.provider);
    const start = str(item.date_start);
    const end = str(item.date_end);
    const venue = item.venue as Record<string, unknown> | undefined;
    const venueName = venue && typeof venue === "object" ? str(venue.name) : null;
    const city = venue && typeof venue === "object" ? str(venue.city) : null;
    const price = formatEventPrice(item);
    const summary = [provider, price].filter(Boolean).join(" · ");
    console.log(`${numLabel}\x1b[1m${title}\x1b[0m${summary ? `  ${summary}` : ""}`);
    if (start || end) {
      console.log(`  ${[start, end ? `→ ${end}` : null].filter(Boolean).join("  ")}`);
    }
    if (venueName || city) kv("venue", [venueName, city].filter(Boolean).join(", "), 14);
    const constraints = item.constraint_matches;
    if (constraints && typeof constraints === "object") {
      for (const [key, value] of Object.entries(constraints as Record<string, unknown>)) {
        if (value !== undefined && value !== null && value !== "") kv(key, String(value), 14);
      }
    }
    const url = str(item.url);
    if (url) kv("url", url, 14);
    console.log("");
    return;
  }

  // ── Place result (maps) ────────────────────────────────────────────────
  if (itemType === "place_result") {
    const name = str(item.name) ?? str(item.displayName) ?? "Unknown";
    const rating = item.rating;
    const addr =
      str(item.formatted_address) ?? str(item.address) ?? str(item.vicinity);
    const summary: string[] = [];
    if (rating) summary.push(`★ ${rating}`);
    if (addr) summary.push(addr);
    console.log(`${numLabel}\x1b[1m${name}\x1b[0m  ${summary.join(" · ")}`);
    printGenericObject(item, 1);
    console.log("");
    return;
  }

  // ── Fitness result (Urban Sports Club locations/classes) ────────────────
  if (str(item.provider) === "Urban Sports Club" && (item.venue_id || item.appointment_id)) {
    const name = str(item.name) ?? "Unknown fitness result";
    const isClass = typeof item.appointment_id === "string";
    const plans = Array.isArray(item.plans_required)
      ? (item.plans_required as unknown[]).map((value) => String(value)).join(", ")
      : null;
    const distance = typeof item.distance_km === "number" ? `${item.distance_km} km` : null;
    const rating = item.rating ? `★ ${item.rating}` : null;
    const spots = str(item.spots_display);
    const mode = str(item.attendance_mode);
    const summary = [isClass ? str(item.category) : null, mode, distance, rating, spots, plans ? `plans: ${plans}` : null]
      .filter(Boolean)
      .join(" · ");

    console.log(`${numLabel}\x1b[1m${name}\x1b[0m${summary ? `  ${summary}` : ""}`);
    const date = str(item.date);
    const timeRange = str(item.time_range);
    if (date || timeRange) console.log(`  ${[date, timeRange].filter(Boolean).join("  ")}`);
    const venueName = str(item.venue_name);
    const venueAddress = str(item.venue_address) ?? str(item.address);
    if (venueName) kv("venue", venueName, 14);
    if (venueAddress) kv("address", venueAddress, 14);
    const disciplines = Array.isArray(item.disciplines)
      ? (item.disciplines as unknown[]).map((value) => String(value)).slice(0, 6)
      : [];
    if (disciplines.length > 0) kv("disciplines", disciplines.join(", "), 14);
    const url = str(item.detail_url) ?? str(item.url) ?? str(item.venue_url);
    if (url) kv("url", url, 14);
    console.log("");
    return;
  }

  // ── Generic item — just number + printGenericObject for all fields ─────
  // Works for web/news search results, events, shopping, health, etc.
  const title = str(item.title) ?? str(item.name) ?? str(item.headline);
  if (title) {
    console.log(`${numLabel}\x1b[1m${title}\x1b[0m`);
    printGenericObject(item, 1);
  } else {
    console.log(`${numLabel}Result ${num}`);
    printGenericObject(item, 1);
  }
  console.log("");
}

function formatEventPrice(item: Record<string, unknown>): string | null {
  const fee = item.fee;
  if (fee && typeof fee === "object") {
    const feeRecord = fee as Record<string, unknown>;
    const amount = str(feeRecord.amount) ?? str(feeRecord.display) ?? str(feeRecord.min);
    const currency = str(feeRecord.currency);
    if (amount) return currency && !amount.includes(currency) ? `${amount} ${currency}` : amount;
  }
  const price = str(item.price);
  if (price) return price;
  if (item.is_paid === false) return "free";
  return null;
}

// ---------------------------------------------------------------------------

function printWhoAmI(user: Record<string, unknown>): void {
  header("Account\n");
  const show = (k: string, label?: string) => {
    const v = user[k];
    if (v !== undefined && v !== null && v !== "") kv(label ?? k, String(v));
  };
  show("username", "Username");
  show("id", "User ID");
  show("is_admin", "Admin");
  show("credits", "Credits");
  show("language", "Language");
  show("subscription_status", "Subscription");
  // Any remaining keys
  const shown = new Set([
    "username",
    "id",
    "is_admin",
    "credits",
    "language",
    "subscription_status",
  ]);
  for (const [k, v] of Object.entries(user)) {
    if (!shown.has(k) && v !== null && v !== undefined && v !== "") {
      kv(k, typeof v === "object" ? JSON.stringify(v) : String(v));
    }
  }
}

/**
 * Human-readable structured output for any API response.
 * Arrays of objects are printed as separated blocks.
 * Nested objects are recursively formatted with indentation.
 * Known response types (billing, invoices) get specialized formatting.
 */
function printGenericObject(value: unknown, indent = 0): void {
  const pad = "  ".repeat(indent);
  if (value === null || value === undefined) {
    console.log(`${pad}(empty)`);
    return;
  }
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    console.log(`${pad}${value}`);
    return;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      console.log(`${pad}(empty list)`);
      return;
    }
    for (let i = 0; i < value.length; i++) {
      const item = value[i];
      if (item && typeof item === "object") {
        printGenericObject(item, indent);
        if (i < value.length - 1) {
          process.stdout.write(`${pad}\x1b[2m${"─".repeat(40)}\x1b[0m\n`);
        }
      } else {
        console.log(`${pad}${String(item)}`);
      }
    }
    return;
  }
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;

    // ── Billing response: specialized formatting ──
    if ("payment_tier" in obj && "invoices" in obj) {
      printBillingResponse(obj);
      return;
    }

    if (Array.isArray(obj.invoices)) {
      printInvoicesResponse(obj.invoices as Array<Record<string, unknown>>);
      return;
    }

    for (const [k, v] of Object.entries(obj)) {
      if (v === null || v === undefined) continue;
      if (Array.isArray(v)) {
        if (v.length === 0) {
          process.stdout.write(
            `${pad}  \x1b[2m${k.padEnd(20)}\x1b[0m (none)\n`,
          );
        } else if (v.length > 0 && typeof v[0] === "object") {
          process.stdout.write(
            `\n${pad}  \x1b[1m${k}\x1b[0m  \x1b[2m(${v.length})\x1b[0m\n`,
          );
          printGenericObject(v, indent + 1);
        } else {
          process.stdout.write(
            `${pad}  \x1b[2m${k.padEnd(20)}\x1b[0m ${v.join(", ")}\n`,
          );
        }
      } else if (typeof v === "object") {
        process.stdout.write(`${pad}  \x1b[1m${k}\x1b[0m\n`);
        printGenericObject(v, indent + 1);
      } else {
        process.stdout.write(`${pad}  \x1b[2m${k.padEnd(20)}\x1b[0m ${v}\n`);
      }
    }
    return;
  }
  console.log(`${pad}${String(value)}`);
}

/** Specialized billing overview renderer */
function printBillingResponse(obj: Record<string, unknown>): void {
  header("Billing\n");
  const credits = obj.credits ?? obj.current_credits;
  if (credits !== undefined) kv("Credits", String(credits));
  if (obj.payment_tier !== undefined)
    kv("Payment tier", String(obj.payment_tier));

  // Auto top-up
  const atEnabled = obj.auto_topup_enabled;
  if (atEnabled !== undefined) {
    kv("Auto top-up", atEnabled ? "enabled" : "disabled");
    if (atEnabled) {
      if (obj.auto_topup_threshold !== undefined)
        kv("  Threshold", `${obj.auto_topup_threshold} credits`);
      if (obj.auto_topup_amount !== undefined)
        kv("  Amount", `${obj.auto_topup_amount} credits`);
      if (obj.auto_topup_currency !== undefined)
        kv("  Currency", String(obj.auto_topup_currency).toUpperCase());
    }
  }

  // Invoices
  const invoices = obj.invoices as Array<Record<string, unknown>> | undefined;
  if (Array.isArray(invoices) && invoices.length > 0) printInvoicesResponse(invoices);

  // Print remaining unknown keys
  const shown = new Set([
    "credits",
    "current_credits",
    "payment_tier",
    "auto_topup_enabled",
    "auto_topup_threshold",
    "auto_topup_amount",
    "auto_topup_currency",
    "invoices",
  ]);
  for (const [k, v] of Object.entries(obj)) {
    if (!shown.has(k) && v !== null && v !== undefined) {
      kv(k, typeof v === "object" ? JSON.stringify(v) : String(v));
    }
  }
}

function printInvoicesResponse(invoices: Array<Record<string, unknown>>): void {
  if (invoices.length === 0) {
    process.stdout.write("\n  \x1b[1mInvoices\x1b[0m  \x1b[2m(0)\x1b[0m\n");
    return;
  }

  process.stdout.write(
    `\n  \x1b[1mInvoices\x1b[0m  \x1b[2m(${invoices.length})\x1b[0m\n\n`,
  );
  for (const inv of invoices) {
    const date = str(inv.date) ?? "—";
    const amt = str(inv.amount) ?? "—";
    const creditsP = inv.credits_purchased ?? "—";
    const refund = str(inv.refund_status);
    const refundTag =
      refund && refund !== "none" ? `  \x1b[33m[${refund}]\x1b[0m` : "";
    const giftTag = inv.is_gift_card ? "  \x1b[35m[gift card]\x1b[0m" : "";
    const transferStatus = str(inv.transaction_status);
    const transferTag = transferStatus ? `  \x1b[36m[${transferStatus}]\x1b[0m` : "";
    process.stdout.write(
      `    ${date}  \x1b[2m€${amt}\x1b[0m  ${creditsP} credits${refundTag}${giftTag}${transferTag}\n`,
    );
    const bankTransferReference = str(inv.bank_transfer_reference);
    if (bankTransferReference) {
      kv("      Bank transfer reference", bankTransferReference, 30);
    }
  }
}

function printMemoriesList(
  memories: Array<{
    id: string;
    app_id: string;
    item_type: string;
    item_version: number;
    updated_at: number;
    data: Record<string, unknown>;
  }>,
): void {
  if (memories.length === 0) {
    console.log("No memories found.");
    return;
  }
  header(`Memories  (${memories.length})\n`);
  for (const mem of memories) {
    const ts = formatTimestamp(mem.updated_at);
    process.stdout.write(
      `\x1b[1m${mem.app_id}/${mem.item_type}\x1b[0m  \x1b[2mv${mem.item_version}  ${ts}  id:${mem.id.slice(0, 8)}\x1b[0m\n`,
    );
    // Show top-level data fields (skip internal _ fields)
    for (const [k, v] of Object.entries(mem.data)) {
      if (!k.startsWith("_") && v !== null && v !== undefined) {
        kv(k, String(v), 20);
      }
    }
    console.log();
  }
}

function printMemoryTypes(
  types: Array<{
    key: string;
    app_id: string;
    item_type: string;
    entry_type: string;
    required: string[];
    properties: string[];
  }>,
): void {
  if (types.length === 0) {
    console.log("No memory types found.");
    return;
  }
  header(`Memory types  (${types.length})\n`);
  let lastApp = "";
  for (const t of types) {
    if (t.app_id !== lastApp) {
      if (lastApp !== "") console.log();
      process.stdout.write(`\x1b[1m${t.app_id}\x1b[0m\n`);
      lastApp = t.app_id;
    }
    process.stdout.write(
      `  \x1b[36m${t.item_type}\x1b[0m  \x1b[2m${t.entry_type}\x1b[0m\n`,
    );
    kv("required", t.required.join(", ") || "none", 12);
    kv("fields", t.properties.join(", "), 12);
  }
  console.log();
  console.log(
    `\x1b[2mCreate: openmates settings memories create --app-id <id> --item-type <type> --data '<json>'\x1b[0m`,
  );
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function str(v: unknown): string | null {
  if (typeof v === "string" && v.trim()) return v.trim();
  return null;
}

function capitalise(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// ---------------------------------------------------------------------------
// Inspirations
// ---------------------------------------------------------------------------

/**
 * Handle `openmates inspirations [--lang <code>] [--json]`.
 *
 * Fetches today's daily inspirations.
 * - Logged-in users: personalized encrypted inspirations decrypted locally.
 * - Not logged in: public defaults for the day (cleartext).
 */
async function handleInspirations(
  client: OpenMatesClient,
  flags: Record<string, string | boolean>,
): Promise<void> {
  const lang = typeof flags.lang === "string" ? flags.lang : "en";
  const inspirations = await client.getDailyInspirations(lang);

  if (flags.json === true) {
    printJson(inspirations);
    return;
  }

  if (inspirations.length === 0) {
    console.log("No inspirations available for today.");
    return;
  }

  const isLoggedIn = client.hasSession();
  const source = isLoggedIn ? "personalized" : "public";
  console.log(
    `[1mDaily Inspirations[0m  [2m(${source}${lang !== "en" ? `, ${lang}` : ""})[0m
`,
  );

  for (let i = 0; i < inspirations.length; i++) {
    printInspiration(inspirations[i], i + 1);
  }
}

/** Render a single inspiration to the terminal in human-readable form. */
function printInspiration(ins: DailyInspiration, index: number): void {
  const categoryLabel = ins.category ? ` [2m[${ins.category}][0m` : "";
  const openedBadge = ins.is_opened ? " [2m(opened)[0m" : "";
  console.log(
    `[1m${index}. ${ins.title || ins.phrase}[0m${categoryLabel}${openedBadge}`,
  );
  if (ins.title && ins.phrase) {
    console.log(`   [3m${ins.phrase}[0m`);
  }
  if (ins.assistant_response) {
    // Wrap long responses at ~80 chars for terminal readability
    const lines = wrapText(ins.assistant_response, 78);
    for (const line of lines) console.log(`   ${line}`);
  }
  if (ins.video) {
    const v = ins.video;
    const duration =
      v.duration_seconds != null
        ? ` · ${formatDuration(v.duration_seconds)}`
        : "";
    const views =
      v.view_count != null ? ` · ${v.view_count.toLocaleString()} views` : "";
    const channel = v.channel_name ? ` · ${v.channel_name}` : "";
    console.log(
      `   [2mVideo: ${v.title || v.youtube_id}${channel}${duration}${views}[0m`,
    );
    if (v.youtube_id) {
      console.log(`   [2mhttps://www.youtube.com/watch?v=${v.youtube_id}[0m`);
    }
  }
  if (ins.follow_up_suggestions.length > 0) {
    console.log(
      `   [2mSuggestions: ${ins.follow_up_suggestions.join(" · ")}[0m`,
    );
  }
  console.log();
}

/** Format seconds into m:ss or h:mm:ss. */
function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0)
    return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

// ---------------------------------------------------------------------------
// New Chat Suggestions
// ---------------------------------------------------------------------------

/**
 * Handle `openmates newchatsuggestions [--limit <n>] [--json]`.
 *
 * Lists the personalized new-chat suggestions generated by the AI post-processor.
 * These are the same suggestions shown in the web app's home screen row
 * ("What would you like to do today?"). Requires login.
 *
 * Suggestions are encrypted per-user in Directus and decrypted locally.
 */
async function handleNewChatSuggestions(
  client: OpenMatesClient,
  flags: Record<string, string | boolean>,
): Promise<void> {
  if (flags.help === true) {
    printNewChatSuggestionsHelp();
    return;
  }

  const limit =
    typeof flags.limit === "string" ? parseInt(flags.limit, 10) : 10;
  const suggestions = await client.listNewChatSuggestions(limit);

  if (flags.json === true) {
    printJson(suggestions);
    return;
  }

  if (suggestions.length === 0) {
    console.log("No new chat suggestions available.");
    console.log(
      `\x1b[2mSuggestions are generated after your first few conversations.\x1b[0m`,
    );
    return;
  }

  header(`New Chat Suggestions  \x1b[2m(${suggestions.length})\x1b[0m\n`);
  printNewChatSuggestionsList(suggestions);
}

/** Render new-chat suggestions in human-readable terminal format. */
function printNewChatSuggestionsList(
  suggestions: DecryptedNewChatSuggestion[],
): void {
  for (let i = 0; i < suggestions.length; i++) {
    const s = suggestions[i];
    printNewChatSuggestion(s, i + 1);
  }
  console.log(
    `\x1b[2mStart a chat: openmates chats new "<suggestion text>"\x1b[0m`,
  );
}

/** Render a single new-chat suggestion. */
function printNewChatSuggestion(
  s: DecryptedNewChatSuggestion,
  index: number,
): void {
  const escapedBody = s.body.replace(/"/g, '\\"');
  process.stdout.write(`\x1b[1m${index}.\x1b[0m ${s.body}\n`);
  process.stdout.write(
    `   \x1b[2mopenmates chats new "${escapedBody}"\x1b[0m\n`,
  );
  console.log();
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Mentions
// ---------------------------------------------------------------------------

/**
 * Handle `openmates mentions` commands.
 * Lists available @mentions that can be used in chat messages.
 *
 * Mirrors: MentionDropdown.svelte (web app)
 */
async function handleMentions(
  client: OpenMatesClient,
  subcommand: string | undefined,
  _rest: string[],
  flags: Record<string, string | boolean>,
): Promise<void> {
  if (!subcommand || subcommand === "help" || subcommand === "list") {
    // Parse optional --type filter
    const typeFilter =
      typeof flags.type === "string" ? (flags.type as MentionType) : undefined;

    const validTypes = [
      "model",
      "model_alias",
      "mate",
      "skill",
      "focus_mode",
      "settings_memory",
    ];
    if (typeFilter && !validTypes.includes(typeFilter)) {
      console.error(
        `Invalid type '${typeFilter}'. Valid types: ${validTypes.join(", ")}`,
      );
      process.exit(1);
    }

    const context = await client.buildMentionContext();
    const options = listMentionOptions(context, typeFilter);

    if (flags.json === true) {
      console.log(JSON.stringify(options, null, 2));
      return;
    }

    if (options.length === 0) {
      console.log(
        "No mentions available" +
          (typeFilter ? ` for type '${typeFilter}'` : "") +
          ".",
      );
      return;
    }

    // Group by type for readable output
    const grouped = new Map<string, typeof options>();
    for (const opt of options) {
      const group = grouped.get(opt.type) || [];
      group.push(opt);
      grouped.set(opt.type, group);
    }

    const typeLabels: Record<string, string> = {
      model_alias: "Model Aliases",
      model: "AI Models",
      mate: "Mates",
      skill: "Skills",
      focus_mode: "Focus Modes",
      settings_memory: "Memories",
    };

    for (const [type, items] of grouped) {
      const label = typeLabels[type] || type;
      process.stdout.write(`\n\x1b[1m${label}\x1b[0m\n`);
      for (const item of items) {
        process.stdout.write(
          `  \x1b[36m${item.displayName.padEnd(35)}\x1b[0m \x1b[2m${item.description}\x1b[0m\n`,
        );
      }
    }
    process.stdout.write("\n");
    return;
  }

  if (subcommand === "search") {
    const query = _rest.join(" ").trim();
    if (!query) {
      console.error(
        "Missing search query. Usage: openmates mentions search <query>",
      );
      process.exit(1);
    }

    const context = await client.buildMentionContext();
    const allOptions = listMentionOptions(context);

    // Fuzzy match against all options
    const normalizedQuery = query.toLowerCase().replace(/[\s_-]+/g, "");
    const matches = allOptions
      .filter((opt) => {
        const normalizedName = opt.displayName
          .toLowerCase()
          .replace(/[@\s_-]+/g, "");
        const normalizedDesc = opt.description
          .toLowerCase()
          .replace(/[\s_-]+/g, "");
        return (
          normalizedName.includes(normalizedQuery) ||
          normalizedDesc.includes(normalizedQuery)
        );
      })
      .slice(0, 15);

    if (flags.json === true) {
      console.log(JSON.stringify(matches, null, 2));
      return;
    }

    if (matches.length === 0) {
      console.log(`No mentions matching '${query}'.`);
      return;
    }

    process.stdout.write(`\n\x1b[1mMatches for '${query}':\x1b[0m\n`);
    for (const m of matches) {
      const typeLabel = m.type.replace("_", " ");
      process.stdout.write(
        `  \x1b[36m${m.displayName.padEnd(35)}\x1b[0m \x1b[2m${m.description} (${typeLabel})\x1b[0m\n`,
      );
    }
    process.stdout.write("\n");
    return;
  }

  console.error(`Unknown mentions subcommand '${subcommand}'.\n`);
  printMentionsHelp();
  process.exit(1);
}

// Help text
// ---------------------------------------------------------------------------

/** Format a share duration for display */
/**
 * Simple YAML serializer for chat export (no external dependency).
 * Handles nested objects, arrays, and multiline strings.
 * Mirrors chatExportService.convertToYamlString for compatibility.
 */
export function serializeToYaml(
  data: Record<string, unknown>,
  indent: number = 0,
): string {
  const pad = "  ".repeat(indent);
  let out = "";
  for (const [key, val] of Object.entries(data)) {
    if (val === null || val === undefined) {
      out += `${pad}${key}: null\n`;
    } else if (typeof val === "boolean" || typeof val === "number") {
      out += `${pad}${key}: ${val}\n`;
    } else if (typeof val === "string") {
      if (val.includes("\n")) {
        out += `${pad}${key}: |\n`;
        for (const line of val.split("\n")) {
          out += `${pad}  ${line}\n`;
        }
      } else {
        // Escape strings that could be misinterpreted as YAML
        const needsQuote =
          val.includes(":") ||
          val.includes("#") ||
          val.startsWith("{") ||
          val.startsWith("[") ||
          val.startsWith("'") ||
          val.startsWith('"') ||
          val === "" ||
          val === "true" ||
          val === "false" ||
          val === "null";
        out += `${pad}${key}: ${needsQuote ? `"${val.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"` : val}\n`;
      }
    } else if (Array.isArray(val)) {
      out += `${pad}${key}:\n`;
      for (const item of val) {
        if (typeof item === "object" && item !== null) {
          out += `${pad}- \n`;
          out += serializeToYaml(
            item as Record<string, unknown>,
            indent + 2,
          );
        } else {
          out += `${pad}- ${item}\n`;
        }
      }
    } else if (typeof val === "object") {
      out += `${pad}${key}:\n`;
      out += serializeToYaml(val as Record<string, unknown>, indent + 1);
    }
  }
  return out;
}

/** Map language identifier to file extension for code embed downloads. */
export function getExtForLang(language: string): string {
  const map: Record<string, string> = {
    javascript: "js",
    typescript: "ts",
    python: "py",
    ruby: "rb",
    rust: "rs",
    golang: "go",
    go: "go",
    java: "java",
    kotlin: "kt",
    swift: "swift",
    csharp: "cs",
    "c#": "cs",
    cpp: "cpp",
    "c++": "cpp",
    c: "c",
    html: "html",
    css: "css",
    scss: "scss",
    json: "json",
    yaml: "yml",
    yml: "yml",
    xml: "xml",
    sql: "sql",
    shell: "sh",
    bash: "sh",
    zsh: "sh",
    powershell: "ps1",
    dockerfile: "Dockerfile",
    docker: "Dockerfile",
    markdown: "md",
    md: "md",
    toml: "toml",
    ini: "ini",
    lua: "lua",
    r: "r",
    php: "php",
    perl: "pl",
    scala: "scala",
    svelte: "svelte",
    vue: "vue",
    jsx: "jsx",
    tsx: "tsx",
  };
  return map[language.toLowerCase()] ?? (language.toLowerCase() || "txt");
}

function humanizeDuration(seconds: number): string {
  if (seconds === 0) return "never";
  if (seconds < 3600) return `${Math.round(seconds / 60)} minute(s)`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} hour(s)`;
  return `${Math.round(seconds / 86400)} day(s)`;
}

function printMentionsHelp(): void {
  console.log(`Mentions commands:
  openmates mentions list [--type <type>] [--json]
  openmates mentions search <query> [--json]

Types:
  model_alias       Model shortcuts (@Best, @Fast)
  model             AI models (@Claude-Opus-4.6, @GPT-5.4)
  mate              AI mates/personas (@Sophia, @Finn)
  skill             App skills (@Web-Search, @Code-Get-Docs)
  focus_mode        Focus modes (@Web-Research)
  settings_memory   Memories (@Code-Projects)

Use @mentions in chat messages:
  openmates chats new "@Sophia tell me about React hooks"
  openmates chats send --chat abc "@best what's the weather?"
  openmates chats new "@Web-Search latest AI news"
  openmates chats new "@Code-Projects review my architecture"`);
}

function printHelp(): void {
  console.log(`OpenMates CLI

Commands:
  openmates login                            Pair-auth login
  openmates signup                           Create an account from the terminal
  openmates logout                           Log out and clear session
  openmates whoami [--json]                  Show account info
  openmates chats [--help]                   Chat commands (list, search, show, ...)
  openmates tasks [--help]                   Task commands (list, create, board, ...)
  openmates drafts [--help]                  Encrypted draft lifecycle commands
  openmates apps [--help]                    App skill commands (list, run, ...)
  openmates workflows [--help]               Server-side workflow commands
  openmates mentions [--help]                List available @mentions
  openmates embeds [--help]                  Embed commands (show)
  openmates settings [--help]                Predefined settings commands
  openmates connected-accounts [--help]      Connected account import helpers
  openmates connect-account [--help]         Local connected-account setup helpers
  openmates learning-mode [--help]           Account-wide Learning Mode controls
  openmates inspirations [--lang <code>] [--json]   Daily inspirations
  openmates newchatsuggestions [--limit <n>] [--json]   Personalized new chat suggestions
  openmates feedback [--help]                Assistant response feedback helpers
  openmates benchmark [--help]               Run real model benchmarks with usage tagged as benchmark spend
  openmates remote-access [--help]           Attach and search local Project sources
  openmates support                          Show voluntary financial support options
  openmates version                          Show CLI version and update availability
  openmates update                           Update the installed OpenMates CLI package
  openmates upgrade                          Alias for openmates update
  openmates server [--help]                   Server management (install, start, stop, ...)
  openmates docs [--help]                     Browse, search, and download documentation
  openmates e2e provision-auth-accounts       Provision local E2E auth-account artifacts

Flags:
  --json          Output raw JSON instead of formatted output
  --api-url <url> Override API base URL (default: installed self-host server, then https://api.openmates.org)
  --api-key <key> Optional API key override (or set OPENMATES_API_KEY)
  --version       Show CLI version and update availability
  --help          Show contextual help for any command`);
}

function printVersionHelp(): void {
  console.log(`OpenMates CLI version command:
  openmates version [--json]
  openmates --version [--json]

Prints the installed CLI version, checks the latest npm version, and shows the
upgrade command when an update is available.

Options:
  --json  Output the version/update status as JSON`);
}

function printSelfUpdateHelp(): void {
  console.log(`OpenMates CLI update commands:
  openmates update [--version <version|tag>] [--package-manager <name>] [--dry-run] [--verbose] [--json]
  openmates upgrade [--version <version|tag>] [--package-manager <name>] [--dry-run] [--verbose] [--json]

Updates the globally installed openmates package. The default target is latest.

Options:
  --version <version|tag>       Install a specific npm version or dist-tag (default: latest)
  --package-manager <name>      npm, pnpm, yarn, or bun (default: detect, then npm)
  --dry-run                     Print the package-manager command without running it
  --verbose                     Stream package-manager output during installation
  --json                        Output the update plan/result as JSON`);
}

function printRemoteAccessHelp(): void {
  console.log(`Remote access commands:
  openmates remote-access start --path <folder> [--source-id <id>] [--project <id>] [--type <type>] [--local-only] [--json]
  openmates remote-access status [--json]
  openmates remote-access search --source <id> <query> [--limit <n>] [--json]

Source types:
  local_folder, local_git_repository

Security:
  Source metadata is stored locally under ~/.openmates/remote-sources.json.
  Preview cache defaults to ~/.openmates/remote-cache/<source-id>.
  Search is read-only, runs rg inside the approved source root, and excludes
  high-risk, binary, and out-of-root paths by default.`);
}

function printConnectedAccountsHelp(): void {
  console.log(`Connected account commands:
  openmates connected-accounts import --payload <OMCA1...> [--json]

Imports one passcode-protected connected account generated from web settings.
The CLI prompts for the passcode interactively, validates the provider token with
a harmless read, then re-encrypts the account for the currently logged-in CLI
account before storing it.

Options:
  --payload <OMCA1...>  Required encrypted import payload from web settings
  --json               Output a redacted JSON summary

Security:
  Do not pass the passcode as a flag. It is always entered through a hidden prompt.`);
}

function printConnectAccountHelp(): void {
  console.log(`Connect account commands:
  openmates connect-account proton [--write] [--json]

Starts a local Proton Mail Bridge connector for OpenMates Mail. Proton Bridge
owns Proton login. OpenMates never asks for your Proton account password.
Proton Mail Bridge requires a paid Proton Mail plan; free Proton accounts cannot
use Bridge IMAP/SMTP access.
If Bridge is missing, the CLI prints OS-specific install instructions and stops;
install Bridge yourself, sign in through Proton Bridge, then rerun this command.

Proton connector behavior:
  Read-only by default.
  Active only while this CLI process keeps running.
  Use screen, tmux, or zellij for long-lived terminal sessions.
  Bridge IMAP/SMTP credentials stay local to this process and are not stored in OpenMates cloud.

Options:
  --write  Enable Proton Mail send capability after confirmation. Sends are delayed 30 seconds for undo.
  --json   Output a redacted JSON summary`);
}

function printFeedbackHelp(): void {
  console.log(`Feedback commands:
  openmates feedback assistant-response --rating <1-5> [--json]

Mirrors the web chat assistant-response feedback decision:
  4-5 stars  Thank the user only
  1-3 stars  Thank the user and prompt a report issue with the standard prefill

Options:
  --rating <1-5>  Required star rating
  --json          Output the decision contract as JSON`);
}

function printLearningModeHelp(): void {
  console.log(`Learning Mode commands:
  openmates learning-mode status [--json]
  openmates learning-mode enable --age-group <group> --passcode <passcode> [--json]
  openmates learning-mode disable --passcode <passcode> [--json]

Learning Mode is account-wide and applies to CLI, web, Apple, and API chat requests.

Age groups:
  under_10, 10_12, 13_15, 16_18, adult

Options:
  --age-group <group>  Required for enable
  --passcode <value>   Required for enable and disable
  --json               Output backend status JSON`);
}

function printSignupHelp(): void {
  console.log(`Signup command:
  openmates signup --email <email> --username <name> --invite-code <code>

Creates a password account using client-side encrypted signup crypto. Passwords
are entered through hidden prompts and cannot be passed with --password.

Options:
  --email <email>                    Email address; prompted when omitted
  --username <name>                  Username; prompted when omitted
  --invite-code <code>               Invite code when required
  --gift-card-code <code>            Redeem after account creation
  --backup-codes-output <path>       Save backup codes to a 0600 file
  --recovery-key-output <path>       Save recovery key to a 0600 file
  --skip-2fa                         Explicitly skip 2FA setup after warning
  --skip-recovery-key                Explicitly skip recovery key after warning
  --yes                              Confirm warning prompts
  --json                             Output non-secret JSON summary`);
}

function printE2EHelp(): void {
  console.log(`E2E provisioning command:
  openmates e2e provision-auth-accounts --slot 15 --artifact ./test-results/credential-updates/slot-15.env --api-url https://api.dev.openmates.org

Creates local ignored credential artifacts for reserved E2E auth accounts. The
command refuses production API URLs and does not upload GitHub secrets.

Options:
  --slot <14-20>                     Reserved auth-account slot
  --artifact <path>                  Output .env artifact path
  --email <email>                    Test email; prompted/generated when omitted
  --domain <mail-domain>             Generate email at this domain
  --force                            Overwrite local artifact files
  --yes                              Confirm prompts where possible`);
}

function printChatsHelp(): void {
  console.log(`Chats commands:
  openmates chats list [--limit <n>] [--page <n>] [--json]
  openmates chats show <chat-id> [--raw] [--json]
  openmates chats open [<n|example-id|slug>] [--json]
  openmates chats search <query> [--json]
  openmates chats new <message> [--json] [--learning-mode --age-group <group>] [--auto-approve] [--auto-approve-memories] [--accept-task-proposals] [--no-pii-detection]
  openmates chats send [--chat <id>] [--incognito] <message> [--json] [--auto-approve] [--auto-approve-memories] [--accept-task-proposals] [--no-pii-detection]
  openmates chats send --chat <id> --followup <n> [--json] [--auto-approve] [--auto-approve-memories]
  openmates chats answer-interactive --chat <id> --question-json '<json>' --answer-json '<json>' [--json] [--accept-task-proposals]
  openmates chats download <chat-id> [--output <path>] [--zip] [--json]
  openmates chats delete <id1> [id2] [id3] ... [--yes]
  openmates chats share [<chat-id>] [--expires <seconds>] [--password <pwd>] [--json]
  openmates chats incognito <message> [--json] [--no-pii-detection]
  openmates chats incognito-history [--json]      Deprecated: incognito stores no history
  openmates chats incognito-clear                 Deprecated: incognito stores no history

Options for 'list':
  --limit <n>   Number of chats per page (default: 10)
  --page <n>    Page number (default: 1)

Options for 'show':
  --raw         Show raw decrypted message content without rendering embeds
                or cleaning embed references. Useful for debugging.

Options for 'open':
  <n>           Position of the chat to open (default: 1 = most recent)
  <example-id|slug>
                Logged out: public example chat ID or slug
                1 = most recent, 2 = second most recent, etc.
                Opens the chat in your default browser.

Options for 'send':
  --chat <id>      Chat to continue (full UUID or 8-char short ID)
  --followup <n>   Send the nth follow-up suggestion for this chat instead of
                   typing the full message (requires --chat)
  --incognito      Send without saving to chat history

Options for 'answer-interactive':
  --chat <id>           Chat containing the interactive question
  --question-json       The question payload returned by 'chats send --json'
  --answer-json         Structured answer JSON, for example '{"selection":["opt_a"]}'

Options for 'new', 'send', and 'incognito':
  --auto-approve           Automatically approve server-requested sub-chat batches.
                           Without this, the CLI prompts in the terminal like the web app.
  --auto-approve-memories  Explicitly approve server-requested memory categories.
                            Memories are never approved by default.
                            Use only for trusted non-interactive runs.
  --no-pii-detection       Send the message exactly as typed. By default, the CLI
                            replaces detected PII with placeholders before send.

Saved-chat task options for 'new', 'send', and 'answer-interactive':
  --accept-task-proposals  Explicitly save assistant task proposals as encrypted
                            Tasks V1 records scoped to the chat. Without this,
                            proposals remain review-only, like the web app card.

Guest-only options for logged-out 'new':
  --learning-mode          Opt anonymous chat into request-scoped Learning Mode.
  --age-group <group>      Required with --learning-mode: under_10, 10_12,
                            13_15, 16_18, or adult.

Options for 'download':
  --output <path>  Target directory (default: current directory)
  --zip            Create a .zip archive instead of a folder
  Downloads: .yml (YAML export), .md (Markdown), code/ (code embeds),
  transcripts/ (video transcripts). Files are saved into a folder named
  with the chat's date and title.

Options for 'delete':
  --yes         Skip confirmation prompt

'show' accepts: full UUID, 8-char short ID, exact/partial title, or "last".

@mentions:
  Use @mentions in messages to invoke models, mates, skills, or attach files:
  @Best, @Fast          Model aliases
  @Claude-Opus-4.6      Specific model
  @Sophia               AI mate/persona
  @Web-Search           App skill
  @Code-Projects        Memories
  @/path/to/file.ts     Attach local file (secrets auto-redacted)

  Sensitive files (.env) use zero-knowledge mode (only names + last 3 chars).
  Private keys (.pem, .key, SSH keys) are blocked by default.

  See all options: openmates mentions list

Examples:
  openmates chats list
  openmates chats open              (opens most recent chat in browser)
  openmates chats open 3            (opens 3rd most recent chat)
  openmates chats open gigantic-airplanes-transporting-rocket-parts
  openmates chats show d262cb68
  openmates chats show last
  openmates chats show "Flight Connections Berlin to Bangkok"
  openmates chats search "Madrid"
  openmates chats new "Hello, what can you help me with?"
  openmates chats new "Help me understand fractions" --learning-mode --age-group 10_12
  openmates chats send --chat d262cb68 "follow-up question"
  openmates chats send --chat d262cb68 --followup 1
  openmates chats send --chat d262cb68 --followup 3
  openmates chats new "@Sophia help me with @./src/app.ts"
  openmates chats new "@best review @/home/user/project/.env"
  openmates chats download last
  openmates chats download d262cb68 --output ~/exports
  openmates chats download last --zip
  openmates chats delete d262cb68 a1b2c3d4
  openmates chats share d262cb68
  openmates chats share last --expires 604800
  openmates chats share d262cb68 --password mypass`);
}

function printTasksHelp(): void {
  console.log(`Tasks commands:
  openmates tasks list [--status <status>] [--chat <id>] [--project <id>] [--json]
  openmates tasks board [--chat <id>] [--project <id>] [--json]
  openmates tasks show <task-id|short-id> [--json]
  openmates tasks create --title <title> [--description <text>] [--assign user|ai] [--chat <id>] [--project <id>] [--status <status>] [--due <date>] [--json]
  openmates tasks edit <task-id|short-id> [--title <title>] [--description <text>] [--assign user|ai] [--status <status>] [--json]
  openmates tasks delete <task-id|short-id> --confirm [--json]
  openmates tasks start <task-id|short-id> [--json]
  openmates tasks status [<task-id|short-id>] [--json]
  openmates tasks block <task-id|short-id> --reason <code> [--json]
  openmates tasks unblock <task-id|short-id> [--json]
  openmates tasks skip <task-id|short-id> [--json]
  openmates tasks done <task-id|short-id> [--json]
  openmates tasks reorder <task-id|short-id> [--before <task-id>] [--after <task-id>] [--position <n>] [--status <status>] [--json]

Chat-scoped aliases:
  openmates chats <chat-id> tasks list
  openmates chats <chat-id> tasks board
  openmates chats <chat-id> tasks create --title <title>

Statuses:
  backlog, todo, in_progress, blocked, done

Notes:
  Task IDs accept full task_id or human short IDs such as OM-6.
  Normal output decrypts task title and description locally; use --json for machine-readable plaintext fields.`);
}

function printDraftsHelp(): void {
  console.log(`Draft commands:
  openmates drafts create <text> [--chat <uuid>] [--preview <text>] [--json]
  openmates drafts update <chat-id> <text> [--preview <text>] [--json]
  openmates drafts list [--refresh] [--json]
  openmates drafts get <chat-id> [--refresh] [--json]
  openmates drafts clear <chat-id> [--json]
  openmates drafts sync [--json]

Draft plaintext is encrypted locally with the account master key. Only Format-D
ciphertext and version metadata are sent to the server or written to CLI cache.`);
}

function printAppsHelp(): void {
  console.log(`Apps commands:
  openmates apps list [--json]
  openmates apps <app-id> [--json]                    App info
  openmates apps info <app-id> [--json]               App info (explicit)
  openmates apps skill-info <app-id> <skill-id> [--json]
  openmates apps examples <app-id> [skill-id] [--json]
  openmates apps <app-id> <skill-id> [value] [options] [--json]
  openmates apps <app-id> <skill-id> --input '<json>' [--json]
  openmates apps code run --language python --code 'print("Hello")'
  openmates apps code run --entry main.py --file main.py [--file requirements.txt]
  openmates apps code run --entry main.py --dir ./project [--exclude node_modules]
  openmates apps models3d search --query benchy [--count 10] [--providers Printables] [--json]
  openmates apps travel booking-link --token "<token>" [--context '<json>']

Authentication:
  Uses your logged-in session (run 'openmates login' first).
  Optionally: --api-key <key> or set OPENMATES_API_KEY.

Examples:
  openmates apps list
  openmates apps web
  openmates apps web search "OpenMates AI assistant" --json
  openmates apps weather forecast Berlin --days 2 --json
  openmates apps math calculate "sqrt(144)" --mode numeric --json
  openmates apps code get_docs --library React --question "How do I use useState?" --json
  openmates apps examples travel search_connections
  openmates apps code run --language python --filename hello.py --code 'print("Hello from CLI")'
  openmates apps models3d search --query benchy --count 2 --providers Printables --json
  openmates apps travel booking-link --token "<booking_token from search result>"
  openmates apps skill-info web search`);
}

function printWorkflowsHelp(): void {
  console.log(`Workflows commands:
  openmates workflows list [--json]
  openmates workflows capabilities [--json]
  openmates workflows validate --file workflow.yml [--json]
  openmates workflows create --file workflow.yml [--json]
  openmates workflows update <workflow-id> --file workflow.yml [--json]
  openmates workflows create --title <title> --graph '<json>' [--enabled] [--run-content-retention last_5|none] [--json]
  openmates workflows input <text> [--workflow-id <id>] [--project-id <id>] [--json]
  openmates workflows input-show <session-id> [--json]
  openmates workflows input-events <session-id> [--after <event-id>] [--json]
  openmates workflows input-follow-up <session-id> <text> [--json]
  openmates workflows input-stop <session-id> [--json]
  openmates workflows input-undo <session-id> [--json]
  openmates workflows show <workflow-id> [--json]
  openmates workflows enable <workflow-id> [--json]
  openmates workflows disable <workflow-id> [--json]
  openmates workflows run <workflow-id> --idempotency-key <stable-key> [--mode manual|test] [--input '<json>'] [--json]
  openmates workflows runs <workflow-id> [--json]
  openmates workflows run-show <workflow-id> <run-id> [--json]
  openmates workflows run-cancel <workflow-id> <run-id> [--json]
  openmates workflows step-test <workflow-id> <step-id> [--input '<json>'] [--yes] [--json]
  openmates workflows respond <workflow-id> <run-id> <step-id> --input '<json>' [--json]
  openmates workflows help-app <app.skill> [--json]
  openmates workflows delete <workflow-id> --yes [--json]

Workflows run on the OpenMates server, not in this terminal process. The CLI
uses your paired session and shows the same workflow/run records as web, SDKs,
and Apple clients.

Examples:
  openmates workflows list
  openmates workflows capabilities --json
  openmates workflows help-app weather.forecast
  openmates workflows input "alert me if it rains tomorrow"
  openmates workflows run wf_123 --mode test --json`);
}

function printEmbedsHelp(): void {
  console.log(`Embeds commands:
  openmates embeds show <embed-id> [--json]
  openmates embeds share <embed-id> [--expires <seconds>] [--password <pwd>] [--json]
  openmates embeds preview start <embed-id> --chat-id <chat-id> [--wait] [--timeout-seconds <n>] [--json]
  openmates embeds preview status <session-id> [--json]
  openmates embeds preview open <session-id> [--json]
  openmates embeds preview stop <session-id> [--json]
  openmates embeds versions list <embed-id> [--json]
  openmates embeds versions show <embed-id> --version <n> [--output <path>] [--json]
  openmates embeds versions restore <embed-id> --version <n> [--yes] [--json]

'show' displays the full decrypted content of an embed.
The 'preview' commands manage generated application live preview sessions.
The 'versions' commands list, inspect, and non-destructively restore history.
The embed ID can be the full UUID or just the first 8 characters.
Embed IDs are shown when viewing chat conversations (openmates chats show).

Examples:
  openmates embeds show a3f2b1c4
  openmates embeds preview start a3f2b1c4 --chat-id 11111111-1111-4111-8111-111111111111 --wait --json
  openmates embeds preview stop 22222222-2222-4222-8222-222222222222 --json
  openmates embeds versions list a3f2b1c4
  openmates embeds versions show a3f2b1c4 --version 1
  openmates embeds versions restore a3f2b1c4 --version 1 --yes`);
}

function printInspirationsHelp(): void {
  console.log(`Inspirations command:
  openmates inspirations [--lang <code>] [--json]

Fetches today's daily inspirations.
  - Logged in:  personalized inspirations (decrypted from your account).
  - Not logged in: public inspirations for the day (no login required).

Options:
  --lang <code>  ISO 639-1 language code for public inspirations (default: en).
                 Supported: en, de, zh, es, fr, pt, ru, ja, ko, it, tr, vi,
                            id, pl, nl, ar, hi, th, cs, sv
  --json         Output raw JSON instead of formatted output.

Examples:
  openmates inspirations
  openmates inspirations --lang de
  openmates inspirations --json`);
}

function printSettingsHelp(client?: OpenMatesClient, filter?: string[]): void {
  const commands = [...SETTINGS_EXECUTABLE_COMMANDS, ...SETTINGS_INFO_COMMANDS]
    .filter((command) => {
      if (!filter || filter.length === 0) return true;
      return filter.every((part, index) => command.path[index] === part);
    })
    .sort((a, b) => a.path.join(" ").localeCompare(b.path.join(" ")));

  const appUrl = client ? deriveAppUrl(client.apiUrl) : "https://openmates.org";
  const title = filter && filter.length > 0
    ? `Settings: ${filter.join(" ")}`
    : "Settings";

  header(title);
  console.log("Predefined commands only. Raw settings get/post/patch/delete is not supported.\n");

  if (commands.length === 0) {
    console.log("No matching settings commands.");
    return;
  }

  for (const command of commands) {
    const isInfoOnly = SETTINGS_INFO_COMMANDS.includes(command);
    const label = `openmates settings ${command.path.join(" ")}`;
    process.stdout.write(`  ${label.padEnd(58)} ${command.description}`);
    if (isInfoOnly) process.stdout.write(" \x1b[2m(info/web-only)\x1b[0m");
    process.stdout.write("\n");
    if (filter && filter.length > 0) {
      for (const example of command.examples) process.stdout.write(`      e.g. ${example}\n`);
      if (command.webPath) process.stdout.write(`      web: ${appUrl}/#settings/${command.webPath}\n`);
    }
  }

  console.log("\nUse --help after a group for examples, e.g. openmates settings billing --help");
}

function printNewChatSuggestionsHelp(): void {
  console.log(`New chat suggestions command:
  openmates newchatsuggestions [--limit <n>] [--json]

Shows personalized new chat suggestions generated for your account.
These are the same suggestions shown in the web app's home screen row.
Suggestions are generated by the AI after each conversation and are
encrypted per-user — only you can read them.

Requires login (run 'openmates login' first).

Options:
  --limit <n>    Maximum number of suggestions to show (default: 10)
  --json         Output raw JSON instead of formatted output

Examples:
  openmates newchatsuggestions
  openmates newchatsuggestions --limit 5
  openmates newchatsuggestions --json`);
}

function printMemoriesHelp(): void {
  console.log(`Memories commands:
  openmates settings memories list [--app-id <id>] [--item-type <type>] [--json]
  openmates settings memories types [--app-id <id>] [--json]
  openmates settings memories create --app-id <id> --item-type <type> --data '<json>'
  openmates settings memories update --id <id> --app-id <id> --item-type <type> --data '<json>' [--version <n>]
  openmates settings memories delete --id <entry-id>

Examples:
  openmates settings memories types --app-id code
  openmates settings memories list --app-id code
  openmates settings memories create --app-id code --item-type preferred_tech --data '{"name":"Python","proficiency":"advanced"}'
  openmates settings memories delete --id <uuid>`);
}

// ---------------------------------------------------------------------------
// Docs
// ---------------------------------------------------------------------------

async function handleDocs(
  client: OpenMatesClient,
  subcommand: string | undefined,
  rest: string[],
  flags: Record<string, string | boolean>,
): Promise<void> {
  if (!subcommand || subcommand === "help" || flags.help === true) {
    printDocsHelp();
    return;
  }

  if (subcommand === "list") {
    const tree = await client.listDocs();
    if (flags.json === true) {
      printJson(tree);
    } else {
      printDocsTree(tree);
    }
    return;
  }

  if (subcommand === "search") {
    const query = rest.join(" ").trim();
    if (!query) {
      console.error("Error: provide a search query.");
      console.error("Usage: openmates docs search <query>");
      process.exit(1);
    }
    const results = await client.searchDocs(query);
    if (flags.json === true) {
      printJson(results);
    } else if (results.length === 0) {
      console.log(`No results for "${query}".`);
    } else {
      console.log(`Found ${results.length} result(s) for "${query}":\n`);
      for (const r of results) {
        console.log(`  \x1b[1m${r.title}\x1b[0m`);
        console.log(`  \x1b[2m${r.slug}\x1b[0m`);
        console.log(`  ${r.snippet}\n`);
      }
    }
    return;
  }

  if (subcommand === "show") {
    const slug = rest[0];
    if (!slug) {
      console.error("Error: provide a doc slug.");
      console.error("Usage: openmates docs show <slug>");
      process.exit(1);
    }
    const content = await client.getDoc(slug);
    console.log(content);
    return;
  }

  if (subcommand === "download") {
    const { writeFile, mkdir } = await import("node:fs/promises");
    const { join, dirname } = await import("node:path");

    if (flags.all === true) {
      // Download all docs
      const outputDir =
        typeof flags.output === "string" ? flags.output : "./openmates-docs";
      const tree = await client.listDocs();
      const slugs = collectSlugs(tree);
      await mkdir(outputDir, { recursive: true });
      let count = 0;
      for (const slug of slugs) {
        const content = await client.getDoc(slug);
        const filePath = join(outputDir, `${slug}.md`);
        await mkdir(dirname(filePath), { recursive: true });
        await writeFile(filePath, content, "utf-8");
        count++;
        process.stderr.write(`\r  Downloaded ${count}/${slugs.length}`);
      }
      process.stderr.write("\n");
      console.log(`Downloaded ${count} docs to ${outputDir}/`);
      return;
    }

    const slug = rest[0];
    if (!slug) {
      console.error(
        "Error: provide a doc slug or --all to download everything.",
      );
      console.error("Usage: openmates docs download <slug> [--output <path>]");
      console.error("       openmates docs download --all [--output <dir>]");
      process.exit(1);
    }
    const content = await client.getDoc(slug);
    const filename = typeof flags.output === "string" ? flags.output : `${slug.split("/").pop()}.md`;
    await writeFile(filename, content, "utf-8");
    console.log(`Saved to ${filename}`);
    return;
  }

  console.error(`Unknown docs subcommand '${subcommand}'.`);
  printDocsHelp();
  process.exit(1);
}

/** Collect all file slugs from a docs tree recursively. */
function collectSlugs(tree: DocsTree): string[] {
  const slugs: string[] = [];
  for (const file of tree.files) {
    slugs.push(file.slug);
  }
  for (const folder of tree.folders) {
    slugs.push(...collectSlugs(folder));
  }
  return slugs;
}

/** Print the docs tree to terminal with indentation. */
function printDocsTree(tree: DocsTree, indent = 0): void {
  const prefix = "  ".repeat(indent);
  for (const folder of tree.folders) {
    console.log(`${prefix}\x1b[1m${folder.title}\x1b[0m/`);
    printDocsTree(folder, indent + 1);
  }
  for (const file of tree.files) {
    console.log(
      `${prefix}  ${file.title} \x1b[2m(${file.slug})\x1b[0m`,
    );
  }
}

function printDocsHelp(): void {
  console.log(`Docs commands:
  openmates docs list [--json]                   List all documentation
  openmates docs search <query> [--json]         Search docs by keyword
  openmates docs show <slug>                     Display a doc in the terminal
  openmates docs download <slug> [--output <p>]  Download a doc as .md file
  openmates docs download --all [--output <dir>] Download all docs

No login required — docs are public.

Examples:
  openmates docs list
  openmates docs search "encryption"
  openmates docs show user-guide/getting-started
  openmates docs download architecture/core/security
  openmates docs download --all --output ./docs`);
}

function isCliEntrypoint(): boolean {
  const entrypoint = process.argv[1];
  if (!entrypoint) return false;

  try {
    const invokedPath = realpathSync(entrypoint);
    const modulePath = realpathSync(fileURLToPath(import.meta.url));
    return (
      invokedPath === modulePath ||
      (basename(invokedPath) === "cli.js" && dirname(invokedPath) === dirname(modulePath))
    );
  } catch {
    return false;
  }
}

if (isCliEntrypoint()) {
  main().catch((error) => {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`Error: ${message}`);
    process.exit(1);
  });
}
