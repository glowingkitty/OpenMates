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
  MEMORY_TYPE_REGISTRY,
  MATE_NAMES,
  deriveAppUrl,
  type ChatListPage,
  type DecryptedMessage,
  type DecryptedEmbed,
} from "./client.js";

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

  if (!command || command === "help") {
    printHelp();
    return;
  }

  // --help with a command shows that command's help, not the global one
  if (parsed.flags.help === true && !subcommand) {
    // e.g. `openmates chats --help` → show chats help
    if (command === "chats") {
      printChatsHelp();
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
    if (command === "embeds") {
      printEmbedsHelp();
      return;
    }
    printHelp();
    return;
  }

  if (command === "login") {
    await client.loginWithPairAuth();
    console.log("Login successful.");
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
    await handleChats(client, subcommand, rest, parsed.flags);
    return;
  }

  if (command === "apps") {
    await handleApps(client, subcommand, rest, parsed.flags);
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

  throw new Error(`Unknown command '${command}'. Run 'openmates help'.`);
}

// ---------------------------------------------------------------------------
// Chats
// ---------------------------------------------------------------------------

async function handleChats(
  client: OpenMatesClient,
  subcommand: string | undefined,
  rest: string[],
  flags: Record<string, string | boolean>,
): Promise<void> {
  if (!subcommand || subcommand === "help" || flags.help === true) {
    printChatsHelp();
    return;
  }

  if (subcommand === "list") {
    const limit =
      typeof flags.limit === "string" ? parseInt(flags.limit, 10) : 10;
    const page = typeof flags.page === "string" ? parseInt(flags.page, 10) : 1;
    const result = await client.listChats(limit, page);
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
    const result = await client.searchChats(query);
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
    const result = await client.sendMessage({
      message,
      chatId: undefined,
      incognito: false,
    });
    if (flags.json === true) {
      printJson(result);
    } else {
      printChatResponse(result);
    }
    return;
  }

  if (subcommand === "send") {
    const message = rest.join(" ").trim();
    if (!message)
      throw new Error(
        "Missing message text. Usage: openmates chats send [--chat <id>] <message>",
      );
    const chatId = typeof flags.chat === "string" ? flags.chat : undefined;
    const result = await client.sendMessage({
      message,
      chatId,
      incognito: flags.incognito === true,
    });
    if (flags.json === true) {
      printJson(result);
    } else {
      printChatResponse(result);
    }
    return;
  }

  if (subcommand === "incognito") {
    const message = rest.join(" ").trim();
    if (!message)
      throw new Error(
        "Missing message text. Usage: openmates chats incognito <message>",
      );
    const result = await client.sendMessage({ message, incognito: true });
    if (flags.json === true) {
      printJson(result);
    } else {
      printChatResponse(result);
    }
    return;
  }

  if (subcommand === "incognito-history") {
    const history = client.getIncognitoHistory();
    if (flags.json === true) {
      printJson(history);
    } else {
      printIncognitoHistory(history);
    }
    return;
  }

  if (subcommand === "incognito-clear") {
    client.clearIncognitoHistory();
    console.log("Incognito history cleared.");
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
    const { chat, messages } = await client.getChatMessages(resolvedId);
    if (flags.json === true) {
      printJson({ chat, messages });
    } else {
      await printChatConversation(client, chat, messages);
    }
    return;
  }

  console.error(`Unknown chats subcommand '${subcommand}'.\n`);
  printChatsHelp();
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Apps
// ---------------------------------------------------------------------------

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

  // `apps <app> --help` → show app info (same as `apps info <app>`)
  if (
    flags.help === true &&
    subcommand !== "list" &&
    subcommand !== "info" &&
    subcommand !== "skill-info" &&
    subcommand !== "run"
  ) {
    const data = await client.getApp(subcommand);
    await printAppInfo(client, data as AppMetadata);
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
    const data = await client.getApp(appId);
    if (flags.json === true) {
      printJson(data);
    } else {
      await printAppInfo(client, data as AppMetadata);
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

  // `apps run` is removed — the sugar alias `apps <app> <skill> [text]` is
  // the canonical way to run skills. Catch it explicitly so users get a
  // helpful redirect instead of a confusing "unknown subcommand" error.
  if (subcommand === "run") {
    const [app, skill, ...inlineTokens] = rest;
    if (!app || !skill) {
      console.error(
        "The 'run' subcommand has been replaced by the shorter sugar syntax.\n",
      );
      printAppsHelp();
      process.exit(1);
    }
    // Silently forward to the sugar alias execution path
    const inputData = buildSkillInput(flags, inlineTokens);
    const data = await client.runSkill({ app, skill, inputData, apiKey });
    if (flags.json === true) {
      printJson(data);
    } else {
      printSkillResult(app, skill, data);
    }
    return;
  }

  // Sugar alias: openmates apps <app> <skill> [inline text]
  const app = subcommand;
  const skill = rest[0];
  if (app && skill) {
    const inputData = buildSkillInput(flags, rest.slice(1));
    const data = await client.runSkill({ app, skill, inputData, apiKey });
    if (flags.json === true) {
      printJson(data);
    } else {
      printSkillResult(app, skill, data);
    }
    return;
  }

  // `apps <app>` with no skill — treat as `apps info <app>`
  if (app && !skill) {
    const data = await client.getApp(app);
    if (flags.json === true) {
      printJson(data);
    } else {
      await printAppInfo(client, data as AppMetadata);
    }
    return;
  }

  console.error(`Unknown apps subcommand '${subcommand}'.\n`);
  printAppsHelp();
  process.exit(1);
}

/**
 * Build skill input data from --input flag or inline positional text.
 * Inline text is wrapped as { requests: [{ query: text }] } which matches
 * the tool_schema convention used by most query-based skills (web, news, etc.).
 * For skills with different schemas use --input '<json>' explicitly.
 */
function buildSkillInput(
  flags: Record<string, string | boolean>,
  inlineTokens: string[],
): Record<string, unknown> {
  if (typeof flags.input === "string") {
    return JSON.parse(flags.input) as Record<string, unknown>;
  }
  const inlineText = inlineTokens.join(" ").trim();
  if (inlineText) return { requests: [{ query: inlineText }] };
  return {};
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
      printEmbedDetail(embed);
    }
    return;
  }

  console.error(`Unknown embeds subcommand '${subcommand}'.\n`);
  printEmbedsHelp();
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

async function handleSettings(
  client: OpenMatesClient,
  subcommand: string | undefined,
  rest: string[],
  flags: Record<string, string | boolean>,
): Promise<void> {
  if (!subcommand || subcommand === "help" || flags.help === true) {
    printSettingsHelp(client);
    return;
  }

  if (subcommand === "get") {
    const path = rest[0];
    if (!path) {
      console.error("Missing path.\n");
      printSettingsHelp();
      process.exit(1);
    }
    const result = await client.settingsGet(path);
    if (flags.json === true) {
      printJson(result);
    } else {
      printGenericObject(result);
    }
    return;
  }

  if (subcommand === "post") {
    const path = rest[0];
    if (!path) {
      console.error("Missing path.\n");
      printSettingsHelp();
      process.exit(1);
    }
    const dataRaw = typeof flags.data === "string" ? flags.data : "{}";
    const data = JSON.parse(dataRaw) as Record<string, unknown>;
    const result = await client.settingsPost(path, data);
    if (flags.json === true) {
      printJson(result);
    } else {
      printGenericObject(result);
    }
    return;
  }

  if (subcommand === "delete") {
    const path = rest[0];
    if (!path) {
      console.error("Missing path.\n");
      printSettingsHelp();
      process.exit(1);
    }
    const result = await client.settingsDelete(path);
    if (flags.json === true) {
      printJson(result);
    } else {
      printGenericObject(result);
    }
    return;
  }

  if (subcommand === "patch") {
    const path = rest[0];
    if (!path) {
      console.error("Missing path.\n");
      printSettingsHelp();
      process.exit(1);
    }
    const dataRaw = typeof flags.data === "string" ? flags.data : "{}";
    const data = JSON.parse(dataRaw) as Record<string, unknown>;
    const result = await client.settingsPatch(path, data);
    if (flags.json === true) {
      printJson(result);
    } else {
      printGenericObject(result);
    }
    return;
  }

  if (subcommand === "memories") {
    await handleMemories(client, rest, flags);
    return;
  }

  console.error(`Unknown settings subcommand '${subcommand}'.\n`);
  printSettingsHelp();
  process.exit(1);
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
      flags[key] = valueFromEquals;
      continue;
    }

    const next = argv[i + 1];
    if (next && !next.startsWith("--")) {
      flags[key] = next;
      i += 1;
    } else {
      flags[key] = true;
    }
  }

  return { positionals, flags };
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

/** Dim separator line */
function hr(): void {
  process.stdout.write("\x1b[2m" + "─".repeat(60) + "\x1b[0m\n");
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

/** Keep for backwards compat in non-list contexts */
function ansiCategoryPill(category: string | null): string {
  return ansiColorBlock(category);
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

  if (chats.length === 0) {
    console.log("No chats found.");
    return;
  }

  const totalPages = Math.ceil(total / limit);
  process.stdout.write(
    `\x1b[2mChats ${start}–${end} of ${total}  (page ${page}/${totalPages})\x1b[0m\n\n`,
  );

  for (const chat of chats) {
    const block = ansiColorBlock(chat.category);
    const time = formatTimestamp(chat.updatedAt);
    const title = chat.title ?? "(no title)";
    const idStr = chat.shortId;

    // Line 1: colored block + timestamp
    process.stdout.write(`${block}  \x1b[2m${time}\x1b[0m\n`);
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

function printChatResponse(result: {
  chatId: string;
  assistant: string;
  category: string | null;
  modelName: string | null;
  mateName: string | null;
}): void {
  const shortId = result.chatId.slice(0, 8);
  const mateBlock = ansiMateBlock(result.category, result.mateName);
  const modelSuffix = result.modelName
    ? `  \x1b[2m${result.modelName}\x1b[0m`
    : "";
  process.stdout.write(`${SEP}\n`);
  process.stdout.write(`${mateBlock}${modelSuffix}\n`);
  process.stdout.write(`${SEP}\n`);
  console.log(result.assistant);
  process.stdout.write(`${SEP}\n`);
  process.stdout.write(
    `\x1b[2mContinue: openmates chats send --chat ${shortId} "your message"\x1b[0m\n` +
      `\x1b[2mHistory:  openmates chats show ${shortId}\x1b[0m\n`,
  );
}

function printIncognitoHistory(
  history: Array<{ role: string; content: string; createdAt: number }>,
): void {
  if (history.length === 0) {
    console.log("No incognito history.");
    return;
  }
  header(`Incognito history  (${history.length} messages)`);
  console.log();
  for (const msg of history) {
    const ts = formatTimestamp(Math.floor(msg.createdAt / 1000));
    const roleLabel =
      msg.role === "user" ? "\x1b[1mYou\x1b[0m" : "\x1b[36mAssistant\x1b[0m";
    process.stdout.write(`${roleLabel}  \x1b[2m${ts}\x1b[0m\n`);
    console.log(msg.content);
    console.log();
  }
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
function parseMessageSegments(
  content: string,
): Array<{ type: "text" | "embed"; value: string }> {
  const segments: Array<{ type: "text" | "embed"; value: string }> = [];
  // Match both ```json and ```json_embed blocks
  const pattern = /```(?:json_embed|json)\n([\s\S]*?)\n```/g;
  let last = 0;
  let m: RegExpExecArray | null;

  while ((m = pattern.exec(content)) !== null) {
    // Text before this block
    if (m.index > last) {
      segments.push({ type: "text", value: content.slice(last, m.index) });
    }

    // Try to extract an embed_id from the JSON block
    try {
      const parsed = JSON.parse(m[1].trim()) as Record<string, unknown>;
      const embedId =
        typeof parsed.embed_id === "string" ? parsed.embed_id : null;
      if (embedId) {
        segments.push({ type: "embed", value: embedId });
      }
      // If no embed_id, silently discard the block (don't show raw JSON)
    } catch {
      // Malformed JSON — discard
    }

    last = m.index + m[0].length;
  }

  // Remaining text after last block
  if (last < content.length) {
    segments.push({ type: "text", value: content.slice(last) });
  }

  return segments;
}

/**
 * Clean display text: strip unresolvable embed badge refs.
 *
 * - `[!](embed:slug)`  → "" (large preview badge — already shown as embed block above)
 * - `[text](embed:slug)` → "text" (inline text badge — keep the display text only)
 */
function cleanMessageText(text: string): string {
  return text
    .replace(/\[!\]\(embed:[^)]+\)/g, "") // [!](embed:...) → remove
    .replace(/\[([^\]]+)\]\(embed:[^)]+\)/g, "$1") // [text](embed:...) → text
    .replace(/\n{3,}/g, "\n\n") // collapse 3+ blank lines
    .trim();
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
): Promise<void> {
  const block = ansiColorBlock(chat.category);
  const title = chat.title ?? "(no title)";
  const ts = formatTimestamp(chat.updatedAt);

  // Header: colored block + date + # Title
  process.stdout.write(`${block}  \x1b[2m${chat.shortId}  ${ts}\x1b[0m\n`);
  process.stdout.write(`\x1b[1;4m# ${title}\x1b[0m\n\n`);

  if (messages.length === 0) {
    process.stdout.write("\x1b[2m(no messages)\x1b[0m\n");
    return;
  }

  for (const msg of messages) {
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
            await renderInlineEmbed(embed, client);
          } catch {
            process.stdout.write(
              `\x1b[2m📎 openmates embeds show ${seg.value.slice(0, 8)}\x1b[0m\n`,
            );
          }
        } else {
          const cleaned = cleanMessageText(seg.value);
          if (cleaned) process.stdout.write(`${cleaned}\n`);
        }
      }
    }

    // User messages may have embeds from hashed_message_id lookup
    // (files/images/etc the user attached) — show those after the text
    if (msg.role === "user" && msg.embedIds.length > 0) {
      for (const eid of msg.embedIds) {
        try {
          const embed = await client.getEmbed(eid);
          await renderInlineEmbed(embed, client);
        } catch {
          process.stdout.write(
            `\x1b[2m📎 openmates embeds show ${eid.slice(0, 8)}\x1b[0m\n`,
          );
        }
      }
    }
  }

  // Final closing separator
  process.stdout.write(`${SEP}\n`);
  process.stdout.write(
    `\x1b[2mContinue: openmates chats send --chat ${chat.shortId} "your message"\x1b[0m\n`,
  );
}

/**
 * Render an embed inline within a chat message.
 * Mirrors the text content shown by each embed's preview component.
 *
 * Format:
 *   ┌─ 📎 web/search  · "best miro alternatives"  via Brave
 *   │  5 results
 *   │  • AFFiNE — https://github.com/toeverything/AFFiNE
 *   │    Open-source all-in-one workspace...
 *   │  • Excalidraw — https://excalidraw.com
 *   │  … and 3 more
 *   └─ openmates embeds show a3f2b1c4
 */
async function renderInlineEmbed(
  embed: DecryptedEmbed,
  client: OpenMatesClient,
): Promise<void> {
  const shortId = embed.embedId.slice(0, 8);
  const app = embed.appId ?? str(embed.content?.app_id) ?? "";
  const skill = embed.skillId ?? str(embed.content?.skill_id) ?? "";
  const label = skill ? `${app}/${skill}` : app || "embed";
  const c = (embed.content ?? {}) as Record<string, unknown>;

  // Build header suffix: query or title if available
  const query = str(c.query) ?? str(c.search_query) ?? str(c.question);
  const headerSuffix = query ? `  · "${query}"` : "";
  const providerSuffix = str(c.provider) ? `  via ${str(c.provider)}` : "";

  const ln = (s: string) => process.stdout.write(`\x1b[2m│  ${s}\x1b[0m\n`);
  const indent = (s: string) =>
    process.stdout.write(`\x1b[2m│    ${s}\x1b[0m\n`);

  process.stdout.write(
    `\x1b[2m┌─ 📎 ${label}${headerSuffix}${providerSuffix}  ${shortId}\x1b[0m\n`,
  );

  // ── web/search  ────────────────────────────────────────────────────────
  // ── news/search ────────────────────────────────────────────────────────
  // Both show: query, "via Provider", favicons row → N results, top-3 titles+URLs+snippets
  // Architecture note: finished embeds store results as child embeds (embed_ids
  // pipe-separated string) rather than inline results array — load them here.
  if ((app === "web" || app === "news") && skill === "search") {
    const inlineResults = c.results as
      | Array<Record<string, unknown>>
      | undefined;
    if (Array.isArray(inlineResults) && inlineResults.length > 0) {
      renderSearchResults(inlineResults, ln, indent);
    } else {
      // Load child embeds from embed_ids
      const rawIds = c.embed_ids;
      const childIds: string[] =
        typeof rawIds === "string"
          ? rawIds.split("|").filter(Boolean)
          : Array.isArray(rawIds)
            ? (rawIds as string[])
            : [];
      if (childIds.length > 0) {
        const childResults: Array<Record<string, unknown>> = [];
        for (const cid of childIds) {
          try {
            const child = await client.getEmbed(cid);
            const cc = (child.content ?? {}) as Record<string, unknown>;
            childResults.push({
              title: str(cc.title) ?? str(cc.name),
              url: str(cc.url) ?? str(cc.link),
              description:
                str(cc.description) ?? str(cc.snippet) ?? str(cc.summary),
            });
          } catch {
            // skip unresolvable child embeds silently
          }
        }
        renderSearchResults(childResults, ln, indent);
      } else {
        ln("No results");
      }
    }
  }

  // ── maps/search ────────────────────────────────────────────────────────
  // Shows: query, "via Google", N places, top-3 with name+address+rating
  else if (app === "maps" && skill === "search") {
    const results = c.results as Array<Record<string, unknown>> | undefined;
    if (Array.isArray(results) && results.length > 0) {
      ln(`${results.length} place${results.length !== 1 ? "s" : ""}`);
      for (const r of results.slice(0, 3)) {
        const name = str(r.displayName) ?? str(r.name) ?? "";
        const address = str(r.formattedAddress) ?? str(r.address) ?? "";
        const rating = typeof r.rating === "number" ? ` ★ ${r.rating}` : "";
        if (name) indent(`${name}${rating}`);
        if (address) indent(`  ${address}`);
      }
      if (results.length > 3) indent(`… and ${results.length - 3} more`);
    } else {
      ln("No places found");
    }
  }

  // ── travel/search_connections ──────────────────────────────────────────
  // Shows: route summary, trip date, N connections, from-price
  else if (app === "travel" && skill === "search_connections") {
    const results = c.results as Array<Record<string, unknown>> | undefined;
    const embedIds = c.embed_ids as string[] | string | undefined;
    const count =
      c.result_count ??
      (Array.isArray(results) ? results.length : null) ??
      (typeof embedIds === "string"
        ? embedIds.split("|").filter(Boolean).length
        : null) ??
      (Array.isArray(embedIds) ? embedIds.length : 0);
    if (count) ln(`${count} connection${count !== 1 ? "s" : ""}`);
    // Show top results if available in content
    if (Array.isArray(results) && results.length > 0) {
      for (const r of results.slice(0, 3)) {
        const price = str(r.price);
        const currency = str(r.currency) ?? "";
        const origin = str(r.origin);
        const dest = str(r.destination);
        const duration = str(r.duration);
        const stops =
          typeof r.stops === "number"
            ? r.stops === 0
              ? "Direct"
              : `${r.stops} stop${r.stops !== 1 ? "s" : ""}`
            : null;
        const carrier =
          Array.isArray(r.carriers) && r.carriers.length > 0
            ? String(r.carriers[0])
            : null;
        if (origin && dest)
          indent(`${origin} → ${dest}${duration ? `  ${duration}` : ""}`);
        if (price)
          indent(
            `  ${currency} ${price}${stops ? `  ${stops}` : ""}${carrier ? `  ${carrier}` : ""}`,
          );
      }
    }
  }

  // ── travel/connection (individual flight) ──────────────────────────────
  else if (app === "travel" && skill === "connection") {
    const price = str(c.price);
    const currency = str(c.currency) ?? "";
    const origin = str(c.origin);
    const dest = str(c.destination);
    const dep = str(c.departure)?.slice(11, 16); // HH:MM
    const arr = str(c.arrival)?.slice(11, 16);
    const duration = str(c.duration);
    const stops =
      typeof c.stops === "number"
        ? c.stops === 0
          ? "Direct"
          : `${c.stops} stop${c.stops !== 1 ? "s" : ""}`
        : null;
    const carrier =
      Array.isArray(c.carriers) && c.carriers.length > 0
        ? String(c.carriers[0])
        : null;
    if (origin && dest) ln(`${origin} → ${dest}`);
    if (dep && arr) ln(`${dep} – ${arr}${duration ? `  (${duration})` : ""}`);
    if (price)
      ln(
        `${currency} ${price}${stops ? `  · ${stops}` : ""}${carrier ? `  · ${carrier}` : ""}`,
      );
  }

  // ── sheets/sheet ───────────────────────────────────────────────────────
  // Shows: title, NxM dimensions, first few rows of markdown table
  else if (app === "sheets" || embed.type === "sheet") {
    const title = str(c.title);
    const rowCount = c.row_count ?? c.rows;
    const colCount = c.col_count ?? c.cols;
    if (title) ln(title);
    if (rowCount && colCount)
      ln(`${String(rowCount)} rows × ${String(colCount)} columns`);
    // Render first 4 rows of the markdown table
    const table = str(c.table) ?? str(c.code) ?? str(c.content);
    if (table) {
      const rows = table
        .split("\n")
        .filter((l) => l.trim().startsWith("|"))
        .slice(0, 5);
      for (const row of rows) {
        indent(row.slice(0, 100));
      }
    }
  }

  // ── code/get_docs ─────────────────────────────────────────────────────
  // Shows: library ID (monospace), question, "via Context7", word count
  else if (app === "code" && skill === "get_docs") {
    const results = c.results as Array<Record<string, unknown>> | undefined;
    const first = Array.isArray(results) ? results[0] : null;
    const libId =
      (first?.library as Record<string, unknown>)?.id ??
      first?.library_id ??
      str(c.library);
    const wordCount = first?.word_count;
    const docs = str((first?.documentation as string) ?? "");
    if (libId) ln(`Library: ${String(libId)}`);
    if (wordCount) ln(`${String(wordCount)} words  via Context7`);
    if (docs) {
      // First ~200 chars of documentation, stripped of markdown headings
      const preview = docs.replace(/^#+\s+/gm, "").slice(0, 200);
      indent(preview + (docs.length > 200 ? "…" : ""));
    }
  }

  // ── reminder/set-reminder ─────────────────────────────────────────────
  // Shows: prompt (3 lines), trigger_at_formatted, target_type, repeating
  else if (app === "reminder") {
    const prompt = str(c.prompt) ?? str(c.message);
    const time = str(c.trigger_at_formatted) ?? str(c.trigger_at);
    const target = str(c.target_type);
    const repeat = c.is_repeating === true;
    if (prompt) {
      const lines = prompt.split("\n").slice(0, 3);
      for (const l of lines) if (l.trim()) ln(`"${l.trim().slice(0, 80)}"`);
    }
    if (time) ln(`🕑 ${time}`);
    if (target)
      ln(target === "new_chat" ? "Opens new chat" : "Continues this chat");
    if (repeat) ln("Repeating");
  }

  // ── images/generate ───────────────────────────────────────────────────
  // Shows: model, prompt — image is binary so we can't display it
  else if (app === "images") {
    const prompt = str(c.prompt);
    const model = str(c.model);
    if (model) ln(`Model: ${model}`);
    if (prompt)
      ln(`Prompt: ${prompt.slice(0, 120)}${prompt.length > 120 ? "…" : ""}`);
    ln(`[image — use 'openmates embeds show ${shortId}' for details]`);
  }

  // ── pdf/read ─────────────────────────────────────────────────────────
  // Shows: filename, pages info, first ~160 chars of extracted text
  else if (app === "pdf") {
    const filename = str(c.filename);
    const results = c.results as Array<Record<string, unknown>> | undefined;
    const pages =
      c.pages_returned ??
      (Array.isArray(results) && results[0] ? results[0].pages_returned : null);
    const pageCount = c.page_count;
    const text = str(
      Array.isArray(results) && results[0]?.content
        ? String(results[0].content)
        : "",
    );
    if (filename) ln(filename);
    if (pages)
      ln(
        `Pages: ${Array.isArray(pages) ? pages.join(", ") : String(pages)}${pageCount ? ` of ${String(pageCount)}` : ""}`,
      );
    if (text) {
      // Strip markdown, first ~160 chars
      const preview = text
        .replace(/#{1,6}\s+/g, "")
        .replace(/[*_`]/g, "")
        .slice(0, 160);
      indent(preview + (text.length > 160 ? "…" : ""));
    }
  }

  // ── docs/doc ──────────────────────────────────────────────────────────
  else if (app === "docs") {
    const title = str(c.title) ?? str(c.filename);
    const wordCount = c.word_count;
    const html = str(c.html);
    if (title) ln(title);
    if (wordCount) ln(`${String(wordCount)} words`);
    if (html) {
      // Strip HTML tags for text preview
      const preview = html
        .replace(/<[^>]+>/g, " ")
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 200);
      indent(preview + (html.length > 200 ? "…" : ""));
    }
  }

  // ── text_preview fallback for group/unknown embeds ────────────────────
  else if (embed.textPreview) {
    const lines = embed.textPreview.split("\n").slice(0, 5);
    for (const l of lines) if (l.trim()) ln(l.slice(0, 100));
  }

  // ── generic key-value for truly unknown types ─────────────────────────
  else {
    let count = 0;
    for (const [k, v] of Object.entries(c)) {
      if (count >= 4) break;
      if (
        v !== null &&
        v !== undefined &&
        typeof v !== "object" &&
        !k.startsWith("_")
      ) {
        ln(`${k}: ${String(v).slice(0, 80)}`);
        count++;
      }
    }
  }

  process.stdout.write(`\x1b[2m└─ openmates embeds show ${shortId}\x1b[0m\n`);
}

/** Shared search renderer for web/search and news/search.
 * Accepts a pre-resolved array of result objects (with title/url/description). */
function renderSearchResults(
  results: Array<Record<string, unknown>>,
  ln: (s: string) => void,
  indent: (s: string) => void,
): void {
  if (results.length === 0) {
    ln("No results");
    return;
  }
  ln(`${results.length} result${results.length !== 1 ? "s" : ""}`);
  for (const r of results.slice(0, 3)) {
    const title = str(r.title) ?? str(r.name) ?? str(r.headline);
    const url = str(r.url) ?? str(r.link);
    const snippet = str(r.description) ?? str(r.snippet) ?? str(r.summary);
    if (title)
      indent(`\x1b[0m\x1b[2m${title}\x1b[0m\x1b[2m${url ? `  ${url}` : ""}`);
    else if (url) indent(url);
    if (snippet)
      indent(`  ${snippet.slice(0, 100)}${snippet.length > 100 ? "…" : ""}`);
  }
  if (results.length > 3) indent(`… and ${results.length - 3} more`);
}

/**
 * Render embed detail view.
 */
function printEmbedDetail(embed: DecryptedEmbed): void {
  header(`Embed  \x1b[2m${embed.embedId.slice(0, 8)}\x1b[0m`);
  console.log();

  if (embed.type) kv("Type", embed.type);
  if (embed.appId) kv("App", embed.appId);
  if (embed.skillId) kv("Skill", embed.skillId);
  if (embed.createdAt) kv("Created", formatTimestamp(embed.createdAt));
  console.log();

  if (embed.textPreview) {
    header("Preview");
    console.log(embed.textPreview);
    console.log();
  }

  if (embed.content) {
    header("Content");
    // Render content fields in a readable way
    for (const [k, v] of Object.entries(embed.content)) {
      if (v === null || v === undefined) continue;
      if (typeof v === "string") {
        if (v.length > 200) {
          kv(k, v.slice(0, 200) + "…", 20);
        } else {
          kv(k, v, 20);
        }
      } else if (Array.isArray(v)) {
        kv(k, `[${v.length} items]`, 20);
        // Show first 3 items briefly
        for (const item of v.slice(0, 3)) {
          if (item && typeof item === "object") {
            const label =
              (item as Record<string, unknown>).title ??
              (item as Record<string, unknown>).name ??
              (item as Record<string, unknown>).url ??
              JSON.stringify(item).slice(0, 80);
            process.stdout.write(`    \x1b[2m• ${String(label)}\x1b[0m\n`);
          } else {
            process.stdout.write(`    \x1b[2m• ${String(item)}\x1b[0m\n`);
          }
        }
        if (v.length > 3) {
          process.stdout.write(
            `    \x1b[2m  ... and ${v.length - 3} more\x1b[0m\n`,
          );
        }
      } else if (typeof v === "object") {
        kv(k, JSON.stringify(v).slice(0, 120), 20);
      } else {
        kv(k, String(v), 20);
      }
    }
  }
}

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
    `\x1b[2mRun: openmates apps <app-id> <skill-id> "<query>"\x1b[0m`,
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
      // Show required input parameters inline (compact)
      const params = await client
        .getSkillSchema(data.id, skill.id)
        .catch(() => []);
      const required = params.filter((p) => p.required);
      if (required.length > 0) {
        const reqStr = required.map((p) => `${p.name} (${p.type})`).join(", ");
        process.stdout.write(`    \x1b[2mRequired: ${reqStr}\x1b[0m\n`);
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
    `\x1b[2mRun: openmates apps ${data.id} <skill-id> "<query>"\x1b[0m`,
  );
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
        process.stdout.write(
          `    \x1b[2mPricing: ${JSON.stringify(p.pricing)}\x1b[0m\n`,
        );
      }
    }
    console.log();
  }

  // Fetch input parameter schema from OpenAPI spec
  const params = await client.getSkillSchema(appId, data.id).catch(() => []);
  if (params.length > 0) {
    process.stdout.write(`\x1b[1mInput parameters\x1b[0m\n`);
    for (const p of params) {
      const req = p.required ? `\x1b[33m*\x1b[0m` : ` `;
      const typeStr = `\x1b[2m(${p.type})\x1b[0m`;
      const defStr =
        p.default !== undefined && p.default !== null
          ? `  \x1b[2mdefault: ${JSON.stringify(p.default)}\x1b[0m`
          : "";
      process.stdout.write(`  ${req} \x1b[36m${p.name}\x1b[0m  ${typeStr}\n`);
      if (p.description) {
        process.stdout.write(`      \x1b[2m${p.description}${defStr}\x1b[0m\n`);
      } else if (defStr) {
        process.stdout.write(`      ${defStr}\n`);
      }
    }
    const requiredNames = params
      .filter((p) => p.required)
      .map((p) => p.name)
      .join(", ");
    if (requiredNames) {
      process.stdout.write(`\n  \x1b[2m* required: ${requiredNames}\x1b[0m\n`);
    }
    console.log();
  }

  console.log(
    `\x1b[2mRun: openmates apps ${appId} ${data.id} "<query>"\x1b[0m`,
  );
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

  // ── Web / news search-style: { results: [{ results: [...] }] } ──────────
  type SearchItem = Record<string, unknown>;
  const topResults = data?.results as SearchItem[] | undefined;
  if (Array.isArray(topResults)) {
    let totalItems = 0;
    const lines: string[] = [];

    for (const group of topResults) {
      const items = group.results as SearchItem[] | undefined;
      if (!Array.isArray(items)) continue;
      for (const item of items) {
        totalItems += 1;
        const title = str(item.title) ?? str(item.name) ?? str(item.headline);
        const url = str(item.url) ?? str(item.link);
        const desc =
          str(item.description) ?? str(item.snippet) ?? str(item.summary);

        if (title) lines.push(`\x1b[1m${title}\x1b[0m`);
        if (url) lines.push(`\x1b[2m${url}\x1b[0m`);
        if (desc) lines.push(desc);
        lines.push("");
      }
    }

    if (totalItems > 0) {
      header(
        `${capitalise(app)} › ${capitalise(skill)}  \x1b[2m(${totalItems} results${credits !== null ? `, ${credits} credits` : ""})\x1b[0m\n`,
      );
      for (const l of lines) console.log(l);
      return;
    }
  }

  // ── Flat array of items (e.g. shopping results) ──────────────────────────
  if (Array.isArray(data)) {
    header(
      `${capitalise(app)} › ${capitalise(skill)}  \x1b[2m(${(data as unknown[]).length} items${credits !== null ? `, ${credits} credits` : ""})\x1b[0m\n`,
    );
    for (const item of data as SearchItem[]) {
      const title = str(item.title) ?? str(item.name);
      const url = str(item.url) ?? str(item.link);
      const desc = str(item.description) ?? str(item.snippet);
      if (title) process.stdout.write(`\x1b[1m${title}\x1b[0m\n`);
      if (url) process.stdout.write(`\x1b[2m${url}\x1b[0m\n`);
      if (desc) process.stdout.write(`${desc}\n`);
      console.log();
    }
    return;
  }

  // ── AI / text response ───────────────────────────────────────────────────
  const content =
    str(data?.content) ??
    str(data?.text) ??
    str(data?.answer) ??
    str(data?.message) ??
    str(data?.response) ??
    str(data?.output);
  if (content) {
    header(
      `${capitalise(app)} › ${capitalise(skill)}${credits !== null ? `  \x1b[2m(${credits} credits)\x1b[0m` : ""}\n`,
    );
    console.log(content);
    return;
  }

  // ── Generic fallback ─────────────────────────────────────────────────────
  header(
    `${capitalise(app)} › ${capitalise(skill)}${credits !== null ? `  \x1b[2m(${credits} credits)\x1b[0m` : ""}\n`,
  );
  printGenericObject(data);
}

// ---------------------------------------------------------------------------
// Settings / generic renderers
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

function printGenericObject(value: unknown): void {
  if (value === null || value === undefined) {
    console.log("(empty)");
    return;
  }
  if (typeof value === "string") {
    console.log(value);
    return;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      console.log("(empty list)");
      return;
    }
    for (const item of value) {
      if (item && typeof item === "object") {
        printGenericObject(item);
        hr();
      } else {
        console.log(String(item));
      }
    }
    return;
  }
  if (typeof value === "object") {
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (v !== null && v !== undefined) {
        kv(k, typeof v === "object" ? JSON.stringify(v) : String(v));
      }
    }
    return;
  }
  console.log(String(value));
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
// Help text
// ---------------------------------------------------------------------------

function printHelp(): void {
  console.log(`OpenMates CLI

Commands:
  openmates login                            Pair-auth login
  openmates logout                           Log out and clear session
  openmates whoami [--json]                  Show account info
  openmates chats [--help]                   Chat commands (list, search, show, ...)
  openmates apps [--help]                    App skill commands (list, run, ...)
  openmates embeds [--help]                  Embed commands (show)
  openmates settings [--help]                Settings & memories

Flags:
  --json          Output raw JSON instead of formatted output
  --api-url <url> Override API base URL (default: https://api.openmates.org)
  --api-key <key> Optional API key override (or set OPENMATES_API_KEY)
  --help          Show contextual help for any command`);
}

function printChatsHelp(): void {
  console.log(`Chats commands:
  openmates chats list [--limit <n>] [--page <n>] [--json]
  openmates chats show <chat-id> [--json]
  openmates chats search <query> [--json]
  openmates chats new <message> [--json]
  openmates chats send [--chat <id>] [--incognito] <message> [--json]
  openmates chats incognito <message> [--json]
  openmates chats incognito-history [--json]
  openmates chats incognito-clear

Options for 'list':
  --limit <n>   Number of chats per page (default: 10)
  --page <n>    Page number (default: 1)

'show' accepts: full UUID, 8-char short ID, exact/partial title, or "last".

Examples:
  openmates chats list
  openmates chats show d262cb68
  openmates chats show last
  openmates chats show "Flight Connections Berlin to Bangkok"
  openmates chats search "Madrid"
  openmates chats new "Hello, what can you help me with?"
  openmates chats send --chat d262cb68 "follow-up question"`);
}

function printAppsHelp(): void {
  console.log(`Apps commands:
  openmates apps list [--json]
  openmates apps <app-id> [--json]                    App info
  openmates apps info <app-id> [--json]               App info (explicit)
  openmates apps skill-info <app-id> <skill-id> [--json]
  openmates apps <app-id> <skill-id> "<query>" [--json]
  openmates apps <app-id> <skill-id> --input '<json>' [--json]

Authentication:
  Uses your logged-in session (run 'openmates login' first).
  Optionally: --api-key <key> or set OPENMATES_API_KEY.

Examples:
  openmates apps list
  openmates apps web
  openmates apps web search "latest AI news"
  openmates apps news search "climate change"
  openmates apps ai ask "Summarise this: ..."
  openmates apps skill-info web search`);
}

function printEmbedsHelp(): void {
  console.log(`Embeds commands:
  openmates embeds show <embed-id> [--json]

'show' displays the full decrypted content of an embed.
The embed ID can be the full UUID or just the first 8 characters.
Embed IDs are shown when viewing chat conversations (openmates chats show).

Examples:
  openmates embeds show a3f2b1c4`);
}

function printSettingsHelp(client?: OpenMatesClient): void {
  const appUrl = client ? deriveAppUrl(client.apiUrl) : "https://openmates.org";
  const s = (path: string) => `${appUrl}/#settings/${path}`;

  console.log(`\x1b[1mSettings\x1b[0m

\x1b[1mAvailable via CLI:\x1b[0m

  \x1b[1mProfile\x1b[0m
    openmates settings get user/language               Language preference
    openmates settings post user/language --data '{"language":"en"}'
    openmates settings post user/darkmode --data '{"dark_mode":true}'
    openmates settings post user/timezone --data '{"timezone":"Europe/Berlin"}'
    openmates settings post user/username --data '{"encrypted_username":"..."}'
    openmates settings post ai-model-defaults --data '{"simple":"...","complex":"..."}'

  \x1b[1mPrivacy & data\x1b[0m
    openmates settings post auto-delete-chats --data '{"period":"90d"}'
    openmates settings post auto-delete-usage --data '{"period":"1y"}'
    openmates settings get delete-account-preview       Preview account deletion
    openmates settings get export-account-manifest      GDPR data export manifest
    openmates settings get export-account-data          GDPR data export

  \x1b[1mUsage & billing\x1b[0m
    openmates settings get usage [--json]               Paginated usage data
    openmates settings get usage/summaries [--json]     Usage summaries by type
    openmates settings get usage/daily-overview [--json]
    openmates settings get usage/export [--json]        Export as CSV
    openmates settings get billing [--json]             Billing overview
    openmates settings get storage [--json]             Storage overview

  \x1b[1mReminders\x1b[0m
    openmates settings get reminders [--json]           List active reminders

  \x1b[1mMemories\x1b[0m
    openmates settings memories list [--app-id <id>] [--item-type <type>] [--json]
    openmates settings memories types [--app-id <id>] [--json]
    openmates settings memories create --app-id <id> --item-type <type> --data '<json>'
    openmates settings memories update --id <id> --app-id <id> --item-type <type> --data '<json>'
    openmates settings memories delete --id <entry-id>

  \x1b[1mChats\x1b[0m
    openmates settings get chats [--json]               Chat statistics
    openmates settings post import-chat --data '<json>' Import a chat

  \x1b[1mSupport\x1b[0m
    openmates settings post issues --data '<json>'      Report an issue

\x1b[1mWeb app only\x1b[0m (for security — manage in browser):
  Security:         ${s("account/security")}
  Passkeys:         ${s("account/security/passkeys")}
  Password:         ${s("account/security/password")}
  2FA:              ${s("account/security/2fa")}
  Sessions:         ${s("account/security/sessions")}
  API keys:         ${s("developers/api-keys")}
  Devices:          ${s("developers/devices")}
  Buy credits:      ${s("billing/buy-credits")}
  Invoices:         ${s("billing/invoices")}
  Auto top-up:      ${s("billing/auto-topup")}
  Notifications:    ${s("notifications")}
  Privacy:          ${s("privacy")}
  App Store:        ${s("app_store")}
  Mates:            ${s("mates")}
  Interface:        ${s("interface")}
  Delete account:   ${s("account")}`);
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

main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`Error: ${message}`);
  process.exit(1);
});
